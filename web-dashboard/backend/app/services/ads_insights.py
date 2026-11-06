"""P4 Insights ingestion worker job (roadmap 4.2).

For every linked ad account that is due, the job pulls Meta Insights at the
campaign, ad set and ad levels with a daily breakdown (``time_increment=1``),
plus optional campaign-level breakdowns (age, gender, platform position,
country), and upserts them into ``ad_insights_daily``.

* Incremental: each run re-reads only from ``insights_synced_through`` minus
  the attribution lookback, so late conversions are corrected.
* Idempotent: rows are upserted on their natural key, and rows of a fully
  re-read window that Meta no longer returns are removed, so a re-run never
  duplicates or leaves stale numbers.
* Rate-limit aware: Meta's throttling headers are read on every page; at the
  configured utilization (or on a throttling error) the run stops, keeps what
  it stored, and the link backs off until ``throttle_until``.
* Large ranges (``ADS_INSIGHTS_ASYNC_MIN_DAYS`` and longer) use an async
  report run; an unfinished report is resumed on the next tick.
* Lease-based pickup with ``FOR UPDATE SKIP LOCKED``; one link is never
  synced by two workers at once.

After a successful sync the spend guard runs for the link's owner and pauses
their live platform campaigns when a cap is reached (``ads_campaigns``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, delete, exists, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.db.models import AdAccountLink, AdCampaign, AdInsightDaily, AdInsightSyncRun, uuid_str
from app.services import ads_accounts as accounts
from app.services import ads_metrics as metrics
from app.services.ads_meta_graph import AdsAuth, AdsGraphError, MetaAdsGraph

logger = get_logger(__name__)
JOB_NAME = "ads-insights"
CLAIM_LIMIT = 2
UPSERT_BATCH = 500
REQUIRED_TABLES = ("ad_account_links", "ad_insights_daily", "ad_insight_sync_runs", "ad_campaigns")
ERROR_RETRY_SECONDS = 1800
RECONNECT_RETRY_SECONDS = 6 * 3600

SessionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(UTC)


def configured_breakdowns() -> tuple[str, ...]:
    raw = str(settings.ADS_INSIGHTS_BREAKDOWNS or "")
    items = [item.strip().lower() for item in raw.split(",")]
    return tuple(dict.fromkeys(item for item in items if item in metrics.BREAKDOWNS))


def account_today(timezone_name: str, now: datetime) -> date:
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return now.astimezone(zone).date()


class ThrottleStop(RuntimeError):
    def __init__(self, throttle: metrics.Throttle) -> None:
        super().__init__("ads-insights-throttled")
        self.throttle = throttle


class ReportPending(RuntimeError):
    """An async report is still running; the next tick resumes it."""


@dataclass
class SyncPlan:
    date_from: date
    date_to: date
    mode: str
    jobs: list[tuple[str, str]] = field(default_factory=list)


def plan_sync(link: AdAccountLink, *, now: datetime) -> SyncPlan:
    today = account_today(link.timezone_name, now)
    date_from, date_to = metrics.sync_window(
        today,
        link.insights_synced_through,
        initial_backfill_days=int(settings.ADS_INSIGHTS_INITIAL_BACKFILL_DAYS),
        lookback_days=int(settings.ADS_INSIGHTS_LOOKBACK_DAYS),
    )
    mode = "async" if metrics.days_in(date_from, date_to) >= int(settings.ADS_INSIGHTS_ASYNC_MIN_DAYS) else "sync"
    jobs = [(level, "none") for level in metrics.LEVELS]
    jobs.extend(("campaign", breakdown) for breakdown in configured_breakdowns())
    return SyncPlan(date_from=date_from, date_to=date_to, mode=mode, jobs=jobs)


def upsert_statement(rows: list[dict[str, Any]]) -> Any:
    statement = pg_insert(AdInsightDaily).values(rows)
    updated = {
        name: statement.excluded[name]
        for name in (
            "object_name", "campaign_id", "adset_id", "currency", "spend", "impressions",
            "reach", "clicks", "link_clicks", "conversions", "conversion_value", "frequency",
            "ctr", "cpc", "cpm", "actions", "fetched_at", "updated_at",
        )
    }
    return statement.on_conflict_do_update(
        constraint="uq_ad_insights_daily_natural_key", set_=updated
    )


class InsightsJob:
    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        graph: MetaAdsGraph | None = None,
        clock: Callable[[], datetime] = _now,
        lease_seconds: int | None = None,
        report_poll_attempts: int = 6,
        report_poll_interval: float = 5.0,
    ) -> None:
        self.session_factory: SessionFactory = session_factory or SessionLocal
        self.graph = graph or MetaAdsGraph()
        self.clock = clock
        self.lease_seconds = int(lease_seconds or settings.ADS_INSIGHTS_LEASE_SECONDS)
        self.report_poll_attempts = report_poll_attempts
        self.report_poll_interval = report_poll_interval
        self.worker_id = f"{JOB_NAME}:{uuid4()}"
        self.ready: bool | None = None
        self.synced = 0
        self.throttled = 0
        self.failed = 0
        self.last_run_at: datetime | None = None
        self._pending_throttle: metrics.Throttle | None = None

    async def preflight(self) -> bool:
        async with self.session_factory() as session:
            checks = " AND ".join(f"to_regclass('{name}') IS NOT NULL" for name in REQUIRED_TABLES)
            self.ready = bool(await session.scalar(text(f"SELECT {checks}")))
        return self.ready

    # --- pickup ----------------------------------------------------------------------

    async def claim_due(self, limit: int = CLAIM_LIMIT) -> list[str]:
        now = self.clock()
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(AdAccountLink)
                    .where(
                        AdAccountLink.status.in_(("active", "error")),
                        AdAccountLink.next_sync_at.is_not(None),
                        AdAccountLink.next_sync_at <= now,
                        or_(AdAccountLink.throttle_until.is_(None), AdAccountLink.throttle_until <= now),
                        or_(AdAccountLink.lease_expires_at.is_(None), AdAccountLink.lease_expires_at <= now),
                    )
                    .order_by(AdAccountLink.next_sync_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.lease_owner = self.worker_id
                row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                row.sync_state = "syncing"
            ids = [row.id for row in rows]
            await session.commit()
        return ids

    async def _leased(self, session: AsyncSession, link_id: str) -> AdAccountLink | None:
        return await session.scalar(
            select(AdAccountLink)
            .where(AdAccountLink.id == link_id, AdAccountLink.lease_owner == self.worker_id)
            .with_for_update()
        )

    # --- one link --------------------------------------------------------------------

    async def sync_link(self, link_id: str) -> str:
        now = self.clock()
        async with self.session_factory() as session:
            link = await self._leased(session, link_id)
            if link is None:
                return "lease-lost"
            try:
                auth = await accounts.link_auth(session, link)
            except accounts.AdsError as exc:
                await self._finish(session, link, state="reconnect", error=exc.code, delay=RECONNECT_RETRY_SECONDS)
                await session.commit()
                return "reconnect"
            plan = plan_sync(link, now=now)
            run = await self._open_run(session, link, plan, now)
            await session.commit()
            run_id = run.id
        outcome = "succeeded"
        error: str | None = None
        throttle = metrics.Throttle()
        rows_total = 0
        calls_before = self.graph.calls
        try:
            for index, (level, breakdown) in enumerate(plan.jobs):
                count, pressure = await self._ingest(auth, link_id, run_id, plan, level, breakdown)
                rows_total += count
                if pressure is not None:
                    throttle = pressure
                    if index + 1 < len(plan.jobs):
                        raise ThrottleStop(pressure)
        except ThrottleStop as stop:
            outcome, throttle, error = "throttled", stop.throttle, "ads-insights-throttled"
        except ReportPending:
            outcome, error = "pending", "ads-insights-report-pending"
        except AdsGraphError as exc:
            if exc.throttled:
                outcome, error = "throttled", exc.code
                throttle = metrics.Throttle(retry_after_seconds=exc.retry_after_seconds)
            else:
                outcome, error = ("reconnect" if exc.reconnect else "failed"), exc.code
        async with self.session_factory() as session:
            link_row = await self._leased(session, link_id)
            run_row = await session.get(AdInsightSyncRun, run_id)
            if run_row is not None:
                run_row.status = outcome
                run_row.rows_upserted += rows_total
                run_row.calls += self.graph.calls - calls_before
                run_row.throttle = throttle.as_dict()
                run_row.error_code = error
                run_row.finished_at = self.clock() if outcome != "pending" else None
            if link_row is None:
                await session.commit()
                return "lease-lost"
            if outcome == "succeeded":
                link_row.insights_synced_through = plan.date_to
                link_row.last_sync_at = self.clock()
                interval = await self._interval(session, link_row)
                if throttle.exceeded(float(settings.ADS_INSIGHTS_THROTTLE_PCT)):
                    backoff = metrics.backoff_seconds(throttle)
                    link_row.throttle_until = self.clock() + timedelta(seconds=backoff)
                    interval = max(interval, backoff)
                await self._finish(session, link_row, state="ok", error=None, delay=interval)
                from app.services import ads_campaigns

                await ads_campaigns.enforce_spend_guard(
                    session, user_id=link_row.user_id, organization_id=link_row.organization_id,
                    graph=self.graph, now=self.clock(),
                )
                self.synced += 1
            elif outcome == "throttled":
                backoff = metrics.backoff_seconds(throttle)
                link_row.throttle_until = self.clock() + timedelta(seconds=backoff)
                await self._finish(session, link_row, state="throttled", error=error, delay=backoff)
                self.throttled += 1
            elif outcome == "pending":
                await self._finish(session, link_row, state="report_pending", error=None, delay=60)
            elif outcome == "reconnect":
                await self._finish(session, link_row, state="reconnect", error=error, delay=RECONNECT_RETRY_SECONDS)
                self.failed += 1
            else:
                await self._finish(session, link_row, state="error", error=error, delay=ERROR_RETRY_SECONDS)
                self.failed += 1
            accounts.audit(
                session,
                organization_id=link_row.organization_id,
                user_id=link_row.user_id,
                action="ads.insights.synced",
                resource_type="ad_account_link",
                resource_id=link_row.id,
                details={
                    "outcome": outcome,
                    "mode": plan.mode,
                    "date_from": plan.date_from.isoformat(),
                    "date_to": plan.date_to.isoformat(),
                    "rows": rows_total,
                    "error": error,
                    "throttle": throttle.as_dict(),
                },
            )
            await session.commit()
        return outcome

    async def _open_run(
        self, session: AsyncSession, link: AdAccountLink, plan: SyncPlan, now: datetime
    ) -> AdInsightSyncRun:
        # Resume an unfinished async report run for the same window.
        pending = await session.scalar(
            select(AdInsightSyncRun)
            .where(
                AdInsightSyncRun.link_id == link.id,
                AdInsightSyncRun.status == "pending",
                AdInsightSyncRun.date_from == plan.date_from,
                AdInsightSyncRun.date_to == plan.date_to,
            )
            .order_by(AdInsightSyncRun.started_at.desc())
            .limit(1)
        )
        if pending is not None:
            pending.status = "running"
            return pending
        run = AdInsightSyncRun(
            link_id=link.id,
            organization_id=link.organization_id,
            status="running",
            mode=plan.mode,
            date_from=plan.date_from,
            date_to=plan.date_to,
            report_run_ids={},
            rows_upserted=0,
            calls=0,
            throttle={},
            started_at=now,
        )
        session.add(run)
        await session.flush()
        return run

    async def _interval(self, session: AsyncSession, link: AdAccountLink) -> int:
        live = await session.scalar(
            select(
                exists().where(
                    and_(AdCampaign.link_id == link.id, AdCampaign.status == "active")
                )
            )
        )
        if live:
            return int(settings.ADS_INSIGHTS_ACTIVE_SYNC_INTERVAL_SECONDS)
        return int(settings.ADS_INSIGHTS_SYNC_INTERVAL_SECONDS)

    async def _finish(
        self, session: AsyncSession, link: AdAccountLink, *, state: str, error: str | None, delay: int
    ) -> None:
        link.sync_state = state
        link.sync_error = error
        link.next_sync_at = self.clock() + timedelta(seconds=max(30, int(delay)))
        link.lease_owner = None
        link.lease_expires_at = None
        link.version += 1
        await session.flush()

    async def _fetch(
        self,
        auth: AdsAuth,
        link: AdAccountLink,
        run_id: str,
        plan: SyncPlan,
        level: str,
        breakdown: str,
    ) -> list[dict[str, Any]]:
        worst = metrics.Throttle()

        def on_page(throttle: metrics.Throttle) -> None:
            nonlocal worst
            if throttle.usage_pct >= worst.usage_pct or throttle.retry_after_seconds > worst.retry_after_seconds:
                worst = throttle

        if plan.mode == "sync":
            rows = await self.graph.insights(
                auth,
                link.ad_account_id,
                level=level,
                date_from=plan.date_from,
                date_to=plan.date_to,
                breakdown=breakdown,
                on_page=on_page,
            )
        else:
            key = f"{level}:{breakdown}"
            async with self.session_factory() as session:
                run = await session.get(AdInsightSyncRun, run_id)
                report_id = str((run.report_run_ids or {}).get(key) or "") if run else ""
                if not report_id:
                    report_id = await self.graph.start_report(
                        auth,
                        link.ad_account_id,
                        level=level,
                        date_from=plan.date_from,
                        date_to=plan.date_to,
                        breakdown=breakdown,
                    )
                    if run is not None:
                        run.report_run_ids = {**dict(run.report_run_ids or {}), key: report_id}
                    await session.commit()
            done = await self.graph.wait_report(
                auth, report_id, attempts=self.report_poll_attempts, interval=self.report_poll_interval
            )
            if not done:
                raise ReportPending(key)
            rows = await self.graph.report_rows(auth, report_id)
        if worst.exceeded(float(settings.ADS_INSIGHTS_THROTTLE_PCT)):
            # Store these rows, then stop before the next job's first call.
            self._pending_throttle = worst
        return rows

    async def _ingest(
        self,
        auth: AdsAuth,
        link_id: str,
        run_id: str,
        plan: SyncPlan,
        level: str,
        breakdown: str,
    ) -> tuple[int, metrics.Throttle | None]:
        async with self.session_factory() as session:
            link = await session.get(AdAccountLink, link_id)
            if link is None or link.lease_owner != self.worker_id:
                raise AdsGraphError("ads-insights-lease-lost")
            currency = link.currency
            snapshot = link
        self._pending_throttle = None
        raw_rows = await self._fetch(auth, snapshot, run_id, plan, level, breakdown)
        fetched_at = self.clock()
        parsed: list[dict[str, Any]] = []
        for raw in raw_rows:
            try:
                row = metrics.parse_insight_row(raw, level=level, breakdown=breakdown)
            except metrics.MetricError:
                continue
            if not plan.date_from <= row["day"] <= plan.date_to:
                continue
            parsed.append(
                {
                    **row,
                    "id": uuid_str(),
                    "link_id": link_id,
                    "organization_id": snapshot.organization_id,
                    "user_id": snapshot.user_id,
                    "currency": currency,
                    "fetched_at": fetched_at,
                    "created_at": fetched_at,
                    "updated_at": fetched_at,
                }
            )
        async with self.session_factory() as session:
            for start in range(0, len(parsed), UPSERT_BATCH):
                await session.execute(upsert_statement(parsed[start : start + UPSERT_BATCH]))
            # The whole window was re-read: anything older in it is gone at Meta.
            await session.execute(
                delete(AdInsightDaily).where(
                    AdInsightDaily.link_id == link_id,
                    AdInsightDaily.level == level,
                    AdInsightDaily.breakdown == breakdown,
                    AdInsightDaily.day >= plan.date_from,
                    AdInsightDaily.day <= plan.date_to,
                    AdInsightDaily.fetched_at < fetched_at,
                )
            )
            await session.commit()
        return len(parsed), self._pending_throttle

    # --- loop ------------------------------------------------------------------------

    async def run_once(self) -> int:
        if self.ready is None:
            await self.preflight()
        if not self.ready:
            return 0
        self.last_run_at = self.clock()
        ids = await self.claim_due()
        for link_id in ids:
            try:
                await self.sync_link(link_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.failed += 1
                logger.error("Ads insights sync failed", link_id=link_id, error_type=type(exc).__name__)
                await self._release_after_crash(link_id)
        return len(ids)

    async def _release_after_crash(self, link_id: str) -> None:
        async with self.session_factory() as session:
            link = await self._leased(session, link_id)
            if link is not None:
                await self._finish(session, link, state="error", error="ads-insights-crashed", delay=ERROR_RETRY_SECONDS)
            await session.commit()

    def health(self) -> dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "synced": self.synced,
            "throttled": self.throttled,
            "failed": self.failed,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
        }
