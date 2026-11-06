"""P4 ads analytics over stored Meta Insights (roadmap 4.3).

KPIs with period-over-period comparison, a daily trend, top and bottom
campaigns, audience/platform breakdowns and alerts (spend spike, CPA above
target, frequency fatigue). Every number comes from ``ad_insights_daily``
rows the insights worker stored; nothing is simulated. Reads are scoped to
the caller's organization and user.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import AdAccountLink, AdInsightDaily
from app.services import ads_accounts as accounts
from app.services import ads_entitlement as entitlement
from app.services import ads_metrics as metrics
from app.services.ads_accounts import AdsError
from app.services.ads_insights import account_today

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 14


def _row(item: AdInsightDaily) -> dict[str, Any]:
    return {
        "object_id": item.object_id,
        "object_name": item.object_name,
        "day": item.day,
        "breakdown": item.breakdown,
        "breakdown_value": item.breakdown_value,
        "spend": item.spend,
        "impressions": item.impressions,
        "reach": item.reach,
        "clicks": item.clicks,
        "link_clicks": item.link_clicks,
        "conversions": item.conversions,
        "conversion_value": item.conversion_value,
    }


async def load_rows(
    session: AsyncSession,
    link: AdAccountLink,
    *,
    level: str,
    date_from: date,
    date_to: date,
    breakdowns: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(AdInsightDaily).where(
        AdInsightDaily.link_id == link.id,
        AdInsightDaily.organization_id == link.organization_id,
        AdInsightDaily.user_id == link.user_id,
        AdInsightDaily.level == level,
        AdInsightDaily.day >= date_from,
        AdInsightDaily.day <= date_to,
    )
    stmt = stmt.where(AdInsightDaily.breakdown != "none") if breakdowns else stmt.where(
        AdInsightDaily.breakdown == "none"
    )
    return [_row(item) for item in (await session.scalars(stmt.limit(200_000))).all()]


def resolve_range(
    link: AdAccountLink, date_from: date | None, date_to: date | None, *, now: datetime | None = None
) -> tuple[date, date]:
    end = date_to or link.insights_synced_through or account_today(link.timezone_name, now or datetime.now(UTC))
    start = date_from or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise AdsError("analytics-range-invalid", status_code=422)
    if metrics.days_in(start, end) > MAX_RANGE_DAYS:
        raise AdsError("analytics-range-too-long", status_code=422)
    return start, end


async def dashboard(
    session: AsyncSession,
    actor: UserRecord,
    link_id: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    access = await entitlement.resolve_access(session, actor)
    access.require()
    link = await accounts.own_link(session, actor, link_id)
    return await build_dashboard(session, link, date_from=date_from, date_to=date_to)


async def build_dashboard(
    session: AsyncSession,
    link: AdAccountLink,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    start, end = resolve_range(link, date_from, date_to)
    previous_start, previous_end = metrics.previous_period(start, end)
    current = await load_rows(session, link, level="campaign", date_from=start, date_to=end)
    previous = await load_rows(
        session, link, level="campaign", date_from=previous_start, date_to=previous_end
    )
    breakdown_rows = await load_rows(
        session, link, level="campaign", date_from=start, date_to=end, breakdowns=True
    )
    alert_rows = await load_rows(
        session, link, level="campaign", date_from=end - timedelta(days=13), date_to=end
    )
    cpa_target = (
        metrics.to_major(link.cpa_target_minor, link.currency) if link.cpa_target_minor else None
    )
    return {
        "link": accounts.public_link(link),
        "currency": link.currency,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "previous_period": {"from": previous_start.isoformat(), "to": previous_end.isoformat()},
        "kpis": metrics.compare_kpis(current, previous),
        "trend": metrics.daily_trend(current, start, end),
        "campaigns": metrics.rank_campaigns(current),
        "breakdowns": metrics.breakdown_summary(breakdown_rows),
        "alerts": metrics.alerts(alert_rows, as_of=end, cpa_target=cpa_target),
        "has_data": bool(current),
        "synced_through": (
            link.insights_synced_through.isoformat() if link.insights_synced_through else None
        ),
        "data_source": "meta_insights",
        "simulated": False,
        "live_verified": False,
    }
