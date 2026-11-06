"""P3 publish/schedule worker: real Graph publishing of due post targets.

Pickup is lease-based: due ``pending``/``retry_wait`` targets are claimed with
``FOR UPDATE SKIP LOCKED``, marked ``publishing`` with a lease owner and
expiry, and an attempt row is written, all in one committed transaction
before any provider call.

Never twice: right before the one Graph call that makes content visible the
worker commits ``dispatch_started_at`` (guarded by its lease). A target whose
lease expired after that point is never replayed; it fails with
``publish-outcome-unknown`` so the user can check the live account. Transient
Graph errors (rate limits, ``is_transient``, unreachable before sending)
retry with exponential backoff up to the post's retry policy; permanent
errors fail at once; an expired or revoked token marks the account as
needing reconnect. A post becomes ``published`` only with a Graph id for
every non-canceled target.

The same worker runs the unified-inbox poll fallback (roadmap 3.6,
``social_inbox_backfill``) every ``SOCIAL_INBOX_POLL_SECONDS`` when
``SOCIAL_INBOX_POLL_ENABLED`` is set; a failed poll never blocks publishing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    SocialPost,
    SocialPostAttempt,
    SocialPostTarget,
)
from app.services import social_connectors as framework
from app.services import social_media_access as media_access
from app.services import social_posts as posts
from app.services import social_publishing_rules as rules
from app.services.social_connections import CONNECTED_VIA
from app.services.social_connectors import SocialConnectorError
from app.services.social_inbox_backfill import REQUIRED_TABLES as INBOX_TABLES
from app.services.social_inbox_backfill import InboxBackfill
from app.services.social_meta_publisher import (
    GraphPublishError,
    MetaPublisher,
    PublishMedia,
    PublishRequest,
    PublishResult,
)

logger = get_logger(__name__)
WORKER_NAME = "social-publish-worker"
CLAIM_LIMIT = 4
_REQUIRED_TABLES = (
    "social_posts",
    "social_post_targets",
    "social_post_attempts",
    "social_media_uploads",
    "growth_social_accounts",
)

SessionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Claim:
    target_id: str
    attempt_number: int


class LeaseLost(RuntimeError):
    """The target's lease moved to another worker; stop before any commit call."""


class _Hooks:
    def __init__(self, worker: "SocialPublishWorker", claim: Claim) -> None:
        self._worker = worker
        self._claim = claim

    async def before_commit(self) -> None:
        await self._worker.mark_dispatch_started(self._claim)

    async def container_created(self, container_id: str) -> None:
        await self._worker.record_container(self._claim, container_id)


class SocialPublishWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        publisher: MetaPublisher | None = None,
        lease_seconds: int | None = None,
        clock: Callable[[], datetime] = _now,
        ads_job: Any | None = None,
        inbox_backfill: InboxBackfill | None = None,
    ) -> None:
        self.session_factory: SessionFactory = session_factory or SessionLocal
        self.publisher = publisher or MetaPublisher()
        self.lease_seconds = int(lease_seconds or settings.SOCIAL_PUBLISH_LEASE_SECONDS)
        self.clock = clock
        self.worker_id = f"{WORKER_NAME}:{uuid4()}"
        self.stop_event = asyncio.Event()
        self.health_path = Path(settings.SOCIAL_PUBLISH_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.published = 0
        self.failed = 0
        self.errors = 0
        # P4: the Meta Ads insights job (``ads_insights.InsightsJob``) runs in
        # this worker's loop on its own tick.
        self.ads_job = ads_job
        self._ads_next_tick = 0.0
        self.inbox_backfill = inbox_backfill

    # --- readiness -------------------------------------------------------------------

    async def preflight(self) -> None:
        async with self.session_factory() as session:
            tables = _REQUIRED_TABLES + (INBOX_TABLES if self.inbox_backfill else ())
            checks = " AND ".join(f"to_regclass('{name}') IS NOT NULL" for name in tables)
            ready = bool(await session.scalar(text(f"SELECT {checks}")))
            if not ready:
                raise RuntimeError("Social publish worker database schema is not current")

    # --- lease pickup ----------------------------------------------------------------

    async def _lock_post_then_target(
        self, session: AsyncSession, target_id: str
    ) -> tuple[SocialPost | None, SocialPostTarget | None]:
        """Lock order is always post, then target (the API uses the same order)."""

        probe = await session.get(SocialPostTarget, target_id)
        if probe is None:
            return None, None
        post = await session.scalar(
            select(SocialPost)
            .where(SocialPost.id == probe.post_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        target = await session.scalar(
            select(SocialPostTarget)
            .where(SocialPostTarget.id == target_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return post, target

    async def recover_stale(self) -> int:
        """Settle targets whose lease expired. Never replays a started dispatch."""

        now = self.clock()
        recovered = 0
        async with self.session_factory() as session:
            stale_ids = list(
                (
                    await session.scalars(
                        select(SocialPostTarget.id)
                        .where(
                            SocialPostTarget.status == "publishing",
                            SocialPostTarget.lease_expires_at.is_not(None),
                            SocialPostTarget.lease_expires_at < now,
                        )
                        .order_by(SocialPostTarget.lease_expires_at)
                        .limit(50)
                    )
                ).all()
            )
            await session.rollback()
        for target_id in stale_ids:
            async with self.session_factory() as session:
                post, target = await self._lock_post_then_target(session, target_id)
                expiry = _aware(target.lease_expires_at) if target is not None else None
                if target is None or target.status != "publishing" or expiry is None or expiry >= now:
                    await session.rollback()
                    continue
                attempt = await self._attempt(session, target.id, target.attempts)
                if target.dispatch_started_at is not None:
                    self._fail(
                        target,
                        "publish-outcome-unknown",
                        "the worker stopped after the publish request was sent",
                    )
                    outcome = "unknown"
                elif target.attempts >= target.max_attempts:
                    self._fail(target, "worker-lease-expired", "the worker stopped before publishing")
                    outcome = "failed"
                else:
                    target.status = "retry_wait"
                    target.next_attempt_at = now
                    target.lease_owner = None
                    target.lease_expires_at = None
                    target.version += 1
                    outcome = "abandoned"
                if attempt is not None and attempt.finished_at is None:
                    attempt.outcome = outcome
                    attempt.error_code = (
                        "worker-lease-expired" if outcome == "abandoned" else target.error_code
                    )
                    attempt.finished_at = now
                if post is not None:
                    await self._refresh_post(session, post, now)
                await session.commit()
                recovered += 1
        return recovered

    async def claim_due(self, limit: int = CLAIM_LIMIT) -> list[Claim]:
        now = self.clock()
        claims: list[Claim] = []
        post_ids: set[str] = set()
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(SocialPostTarget)
                    .join(SocialPost, SocialPost.id == SocialPostTarget.post_id)
                    .where(
                        SocialPostTarget.status.in_(("pending", "retry_wait")),
                        SocialPostTarget.next_attempt_at.is_not(None),
                        SocialPostTarget.next_attempt_at <= now,
                        SocialPostTarget.dispatch_started_at.is_(None),
                        or_(
                            SocialPostTarget.lease_expires_at.is_(None),
                            SocialPostTarget.lease_expires_at < now,
                        ),
                        SocialPost.status.in_(("scheduled", "publishing")),
                    )
                    .order_by(SocialPostTarget.next_attempt_at, SocialPostTarget.id)
                    .limit(limit)
                    .with_for_update(of=SocialPostTarget, skip_locked=True)
                )
            ).all()
            for target in rows:
                target.status = "publishing"
                target.lease_owner = self.worker_id
                target.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                target.attempts += 1
                target.last_attempt_at = now
                target.version += 1
                session.add(
                    SocialPostAttempt(
                        target_id=target.id,
                        organization_id=target.organization_id,
                        attempt_number=target.attempts,
                        worker=self.worker_id[:64],
                        outcome="running",
                        transient=False,
                        started_at=now,
                    )
                )
                claims.append(Claim(target.id, target.attempts))
                post_ids.add(target.post_id)
            # The claim is durable before any provider I/O starts.
            await session.commit()
        if post_ids:
            # Separate transaction: no target lock is held while a post row is
            # locked here, so this never deadlocks with an API cancel.
            async with self.session_factory() as session:
                await session.execute(
                    update(SocialPost)
                    .where(SocialPost.id.in_(sorted(post_ids)), SocialPost.status == "scheduled")
                    .values(status="publishing", version=SocialPost.version + 1)
                )
                await session.commit()
        return claims

    # --- dispatch guard --------------------------------------------------------------

    async def _guarded_update(self, claim: Claim, values: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                update(SocialPostTarget)
                .where(
                    SocialPostTarget.id == claim.target_id,
                    SocialPostTarget.lease_owner == self.worker_id,
                    SocialPostTarget.status == "publishing",
                    SocialPostTarget.attempts == claim.attempt_number,
                )
                .values(**values)
            )
            if int(getattr(result, "rowcount", 0) or 0) != 1:
                await session.rollback()
                raise LeaseLost(claim.target_id)
            await session.commit()

    async def mark_dispatch_started(self, claim: Claim) -> None:
        await self._guarded_update(claim, {"dispatch_started_at": self.clock()})

    async def record_container(self, claim: Claim, container_id: str) -> None:
        await self._guarded_update(claim, {"container_id": container_id[:64]})

    # --- processing ------------------------------------------------------------------

    async def _prepare(self, claim: Claim) -> tuple[PublishRequest | None, str | None]:
        """Return the publish request, or a permanent failure code."""

        async with self.session_factory() as session:
            target = await session.get(SocialPostTarget, claim.target_id)
            if target is None or target.lease_owner != self.worker_id:
                raise LeaseLost(claim.target_id)
            post = await session.get(SocialPost, target.post_id)
            if post is None:
                return None, "post-not-found"
            account = None
            if target.account_id:
                account = await session.scalar(
                    select(GrowthSocialAccount).where(
                        GrowthSocialAccount.id == target.account_id,
                        GrowthSocialAccount.organization_id == target.organization_id,
                        GrowthSocialAccount.created_by_id == target.user_id,
                        GrowthSocialAccount.connected_via == CONNECTED_VIA,
                    )
                )
            if account is None or account.status == "revoked" or not account.token_ciphertext:
                return None, "account-disconnected"
            if account.status != "active":
                return None, "account-reconnect-required"
            try:
                resolved = await media_access.resolve_media(
                    session,
                    organization_id=post.organization_id,
                    user_id=post.user_id,
                    refs=[str(item.get("ref")) for item in post.media or [] if isinstance(item, dict)],
                )
            except SocialConnectorError as exc:
                return None, exc.code
            overrides = dict(target.overrides or {})
            content = posts.target_content(post, target.provider, overrides, [m.info for m in resolved])
            issues = rules.validate_target(content)
            errors = [item["code"] for item in issues if item["severity"] == "error"]
            if errors:
                return None, f"validation-failed:{errors[0]}"[:120]
            try:
                token = framework.open_token(account.token_ciphertext)
                media = [PublishMedia(kind=m.info.kind, url=media_access.public_url(m)) for m in resolved]
            except SocialConnectorError as exc:
                return None, exc.code
            return (
                PublishRequest(
                    provider=target.provider,
                    external_id=account.external_account_id,
                    access_token=token,
                    post_type=post.post_type,
                    caption=content.caption,
                    link_url=post.link_url,
                    media=media,
                    share_to_feed=content.share_to_feed,
                ),
                None,
            )

    async def process(self, claim: Claim) -> str:
        try:
            request, failure = await self._prepare(claim)
        except LeaseLost:
            return "lease-lost"
        result: PublishResult | None = None
        error: GraphPublishError | None = None
        if request is not None:
            try:
                result = await self.publisher.publish(request, hooks=_Hooks(self, claim))
            except LeaseLost:
                return "lease-lost"
            except GraphPublishError as exc:
                error = exc
        else:
            error = GraphPublishError(failure or "publish-prepare-failed")
            if failure in {"account-reconnect-required", "account-disconnected"}:
                error = GraphPublishError(failure, token_expired=failure == "account-reconnect-required")
        return await self.finalize(claim, result, error)

    async def finalize(
        self, claim: Claim, result: PublishResult | None, error: GraphPublishError | None
    ) -> str:
        now = self.clock()
        async with self.session_factory() as session:
            post, target = await self._lock_post_then_target(session, claim.target_id)
            if (
                target is None
                or target.lease_owner != self.worker_id
                or target.status != "publishing"
                or target.attempts != claim.attempt_number
            ):
                await session.rollback()
                return "lease-lost"
            attempt = await self._attempt(session, target.id, claim.attempt_number)
            outcome: str
            if result is not None:
                target.status = "published"
                target.remote_post_id = result.remote_post_id[:128]
                target.permalink = result.permalink
                if result.container_id:
                    target.container_id = result.container_id[:64]
                target.published_at = now
                target.error_code = None
                target.error_message = None
                target.next_attempt_at = None
                outcome = "published"
                self.published += 1
            elif error is not None and error.token_expired:
                self._fail(target, "account-reconnect-required", error.message or error.code)
                await self._mark_reconnect(session, target, error.code)
                outcome = "failed"
            elif error is not None and error.ambiguous:
                self._fail(target, "publish-outcome-unknown", error.message or error.code)
                outcome = "unknown"
            elif error is not None and error.transient and target.attempts < target.max_attempts:
                policy = dict(post.retry_policy or {}) if post is not None else {}
                target.status = "retry_wait"
                target.next_attempt_at = now + posts.backoff_delay(policy, target.attempts)
                # A transient Graph error means nothing was created; the guard resets.
                target.dispatch_started_at = None
                target.error_code = error.code
                target.error_message = error.message or None
                outcome = "retry_scheduled"
            else:
                code = error.code if error is not None else "publish-failed"
                self._fail(target, code, error.message if error is not None else "")
                outcome = "failed"
            if outcome != "published" and outcome != "retry_scheduled":
                self.failed += 1
            target.lease_owner = None
            target.lease_expires_at = None
            target.version += 1
            if attempt is not None:
                attempt.outcome = outcome
                attempt.transient = bool(error is not None and error.transient)
                attempt.error_code = None if result is not None else (error.code if error else None)
                attempt.error_message = None if result is not None else (error.message[:500] if error and error.message else None)
                attempt.remote_post_id = result.remote_post_id[:128] if result is not None else None
                attempt.finished_at = now
            session.add(
                AuditEvent(
                    organization_id=target.organization_id,
                    user_id=target.user_id,
                    action=f"social.post.target_{outcome}",
                    resource_type="social_post_target",
                    resource_id=target.id,
                    details={
                        "publishing": "p3",
                        "post_id": target.post_id,
                        "provider": target.provider,
                        "attempt": claim.attempt_number,
                        "remote_post_id": target.remote_post_id,
                        "error_code": target.error_code,
                    },
                )
            )
            if post is not None:
                await self._refresh_post(session, post, now)
            await session.commit()
        return outcome

    @staticmethod
    def _fail(target: SocialPostTarget, code: str, message: str) -> None:
        target.status = "failed"
        target.error_code = code[:120]
        target.error_message = (" ".join(str(message or "").split())[:500]) or None
        target.next_attempt_at = None
        target.lease_owner = None
        target.lease_expires_at = None
        target.version += 1

    @staticmethod
    async def _attempt(
        session: AsyncSession, target_id: str, number: int
    ) -> SocialPostAttempt | None:
        return await session.scalar(
            select(SocialPostAttempt).where(
                SocialPostAttempt.target_id == target_id,
                SocialPostAttempt.attempt_number == number,
            )
        )

    @staticmethod
    async def _mark_reconnect(session: AsyncSession, target: SocialPostTarget, reason: str) -> None:
        if not target.account_id:
            return
        account = await session.scalar(
            select(GrowthSocialAccount)
            .where(
                GrowthSocialAccount.id == target.account_id,
                GrowthSocialAccount.organization_id == target.organization_id,
            )
            .with_for_update()
        )
        if account is None or account.status == "revoked":
            return
        account.status = "expired"
        account.health_state = "expired"
        account.health_reasons = ["token-expired-reconnect-required", reason[:120]]
        account.last_health_at = _now()
        account.version += 1
        session.add(
            AuditEvent(
                organization_id=target.organization_id,
                user_id=target.user_id,
                action="social.account.reconnect_required",
                resource_type="growth_social_account",
                resource_id=account.id,
                details={"publishing": "p3", "provider": account.provider, "reason": reason[:120]},
            )
        )

    @staticmethod
    async def _refresh_post(session: AsyncSession, post: SocialPost, now: datetime) -> None:
        await session.flush()
        statuses = list(
            (
                await session.scalars(
                    select(SocialPostTarget.status).where(SocialPostTarget.post_id == post.id)
                )
            ).all()
        )
        status = posts.aggregate_status(post, statuses)
        if status != post.status:
            post.status = status
            post.version += 1
            if status in {"published", "partially_failed"} and post.published_at is None:
                post.published_at = now
            if status == "canceled" and post.canceled_at is None:
                post.canceled_at = now

    # --- loop ------------------------------------------------------------------------

    async def run_once(self) -> int:
        if self.stop_event.is_set():
            return 0
        await self.recover_stale()
        claims = await self.claim_due()
        if claims:
            outcomes = await asyncio.gather(
                *(self.process(claim) for claim in claims), return_exceptions=True
            )
            for claim, outcome in zip(claims, outcomes):
                if isinstance(outcome, BaseException):
                    self.errors += 1
                    logger.error(
                        "Social publish target failed unexpectedly",
                        target_id=claim.target_id,
                        error_type=type(outcome).__name__,
                    )
        await self._run_ads_job()
        await self.run_inbox_backfill()
        self.cycles += 1
        self.write_health("running")
        return len(claims)

    async def _run_ads_job(self) -> None:
        if self.ads_job is None or time.monotonic() < self._ads_next_tick:
            return
        self._ads_next_tick = time.monotonic() + float(settings.ADS_INSIGHTS_TICK_SECONDS)
        try:
            await self.ads_job.run_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors += 1
            logger.error("Ads insights job failed", error_type=type(exc).__name__)

    async def run_inbox_backfill(self) -> int:
        if self.inbox_backfill is None or self.stop_event.is_set():
            return 0
        try:
            return await self.inbox_backfill.run_if_due()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors += 1
            logger.error("Social inbox poll cycle failed", error_type=type(exc).__name__)
            return 0

    async def run_forever(self) -> None:
        await self.preflight()
        self.write_health("running")
        while not self.stop_event.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                logger.error("Social publish worker cycle failed", error_type=type(exc).__name__)
                processed = 0
                self.write_health("degraded")
            if processed == 0:
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(), timeout=settings.SOCIAL_PUBLISH_WORKER_POLL_SECONDS
                    )
                except TimeoutError:
                    continue
        self.write_health("stopped")

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker": WORKER_NAME,
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "published": self.published,
            "failed": self.failed,
            "errors": self.errors,
            "ads_insights": self.ads_job.health() if self.ads_job is not None else None,
            "inbox_poll_enabled": self.inbox_backfill is not None,
            "inbox_stored": self.inbox_backfill.stored if self.inbox_backfill else 0,
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)


def healthcheck(path: str | Path, *, maximum_age_seconds: float | None = None) -> int:
    limit = maximum_age_seconds or max(120.0, settings.SOCIAL_PUBLISH_WORKER_POLL_SECONDS * 6.0)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        healthy = payload.get("status") == "running" and 0 <= age <= limit + settings.SOCIAL_PUBLISH_LEASE_SECONDS
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        healthy = False
    return 0 if healthy else 1


async def async_main() -> int:
    ads_job = None
    if settings.ADS_INSIGHTS_WORKER_ENABLED:
        from app.services.ads_insights import InsightsJob

        ads_job = InsightsJob()
    backfill = InboxBackfill(SessionLocal) if settings.SOCIAL_INBOX_POLL_ENABLED else None
    worker = SocialPublishWorker(inbox_backfill=backfill, ads_job=ads_job)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop_event.set)
        except NotImplementedError:
            logger.debug("Social publish signal handler is unavailable")
    await worker.run_forever()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck(settings.SOCIAL_PUBLISH_WORKER_HEALTH_FILE)
    setup_logging()
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.error("Social publish worker startup failed", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
