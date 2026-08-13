"""Subscription and storage lifecycle alerts for users and the platform owner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    BillingAccount,
    OwnerControlRecord,
    Report,
    StudioAssetRevision,
    ThreeDArtifact,
    User,
)
from app.services import communications

FREE_TIER_ACCOUNT_DOMAIN = "free-tier-account"
SUBSCRIPTION_WINDOWS = ((1, "1d"), (7, "7d"))
STORAGE_THRESHOLDS = ((95, "95"), (80, "80"))


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def owner_alert_channels() -> list[str]:
    """Return one durable external Owner channel plus in-app delivery.

    Telegram is preferred when the protected bot has exactly one allowlisted
    Owner identity, because that identity can be bound deterministically to the
    Super Owner notification endpoint. Email is the safe fallback because the
    communications service can derive the account email endpoint automatically.
    WhatsApp remains available through explicit endpoint configuration, but it is
    not guessed here. Sending every configured external channel for every alert
    creates duplicate noise and causes avoidable retries when one provider is
    temporarily unhealthy.
    """

    readiness = {item["id"]: item for item in communications.channel_readiness()}
    telegram_ready = bool((readiness.get("telegram") or {}).get("ready"))
    allowed_telegram = [
        str(value).strip()
        for value in settings.AIOS_TELEGRAM_ALLOWED_USERS
        if str(value).strip()
    ]
    if telegram_ready and len(allowed_telegram) == 1:
        return ["in_app", "telegram"]
    if bool((readiness.get("email") or {}).get("ready")):
        return ["in_app", "email"]
    if bool((readiness.get("whatsapp") or {}).get("ready")):
        return ["in_app", "whatsapp"]
    return ["in_app"]


async def organization_storage_usage_bytes(
    session: AsyncSession, organization_id: str
) -> int:
    report_bytes = int(
        await session.scalar(
            select(func.coalesce(func.sum(Report.size_bytes), 0)).where(
                Report.organization_id == organization_id,
                Report.size_bytes.is_not(None),
            )
        )
        or 0
    )
    # StudioAsset points at the current revision path, so revisions are the
    # physical retained files and must be counted once rather than double-counted.
    studio_bytes = int(
        await session.scalar(
            select(func.coalesce(func.sum(StudioAssetRevision.size_bytes), 0)).where(
                StudioAssetRevision.organization_id == organization_id,
                StudioAssetRevision.status != "deleted",
            )
        )
        or 0
    )
    three_d_bytes = int(
        await session.scalar(
            select(func.coalesce(func.sum(ThreeDArtifact.size_bytes), 0)).where(
                ThreeDArtifact.organization_id == organization_id,
                ThreeDArtifact.status.notin_({"expired", "deleted"}),
            )
        )
        or 0
    )
    user_ids = list(
        (
            await session.scalars(
                select(User.id).where(
                    User.organization_id == organization_id,
                    User.deleted_at.is_(None),
                )
            )
        ).all()
    )
    free_bytes = 0
    if user_ids:
        records = list(
            (
                await session.scalars(
                    select(OwnerControlRecord).where(
                        OwnerControlRecord.domain == FREE_TIER_ACCOUNT_DOMAIN,
                        OwnerControlRecord.resource_id.in_(user_ids),
                    )
                )
            ).all()
        )
        free_bytes = sum(
            max(0, int((record.payload or {}).get("storage_bytes_used", 0) or 0))
            for record in records
        )
    return max(0, report_bytes + studio_bytes + three_d_bytes + free_bytes)


async def _notify_subscription(
    session: AsyncSession,
    account: BillingAccount,
    *,
    end: datetime,
    window_days: int,
    label: str,
) -> list:
    date_key = end.date().isoformat()
    message = (
        f"Your AIONEX subscription period ends on {date_key}. "
        "Review renewal or billing settings before access is affected."
    )
    user_notifications = await communications.notify_audience(
        session,
        organization_id=account.organization_id,
        audience="organization",
        event_key=f"billing.subscription.expiring_{label}",
        category="billing",
        title="Subscription ending soon",
        message=message,
        severity="warning" if window_days > 1 else "critical",
        channels=["in_app"],
        source_type="billing_account",
        source_id=account.id,
        correlation_id=account.id,
        dedupe_prefix=f"subscription-expiry:{account.id}:{date_key}:{label}:user",
        payload={"current_period_end": end.isoformat(), "window_days": window_days},
    )
    owner_notifications = await communications.notify_audience(
        session,
        organization_id=account.organization_id,
        audience="platform_owner",
        event_key=f"billing.subscription.expiring_{label}",
        category="billing",
        title="Customer subscription ending soon",
        message=(
            f"Organization {account.organization_id} subscription period ends on "
            f"{date_key}."
        ),
        severity="warning" if window_days > 1 else "critical",
        channels=owner_alert_channels(),
        source_type="billing_account",
        source_id=account.id,
        correlation_id=account.id,
        dedupe_prefix=f"subscription-expiry:{account.id}:{date_key}:{label}:owner",
        payload={"organization_id": account.organization_id, "current_period_end": end.isoformat()},
        respect_preferences=False,
    )
    return [*user_notifications, *owner_notifications]


async def _notify_storage(
    session: AsyncSession,
    account: BillingAccount,
    *,
    used: int,
    limit: int,
    threshold: int,
    label: str,
) -> list:
    percent = round(used / limit * 100, 1)
    month_key = _now().strftime("%Y-%m")
    user_notifications = await communications.notify_audience(
        session,
        organization_id=account.organization_id,
        audience="organization",
        event_key=f"storage.capacity.near_{label}",
        category="quota",
        title="Storage space is running low",
        message=(
            f"Your AIONEX storage is {percent}% full ({used} of {limit} bytes). "
            "Free space or review your plan before the limit is reached."
        ),
        severity="warning" if threshold < 95 else "critical",
        channels=["in_app"],
        source_type="billing_account",
        source_id=account.id,
        correlation_id=account.id,
        dedupe_prefix=f"storage:{account.id}:{limit}:{label}:{month_key}:user",
        payload={"used_bytes": used, "limit_bytes": limit, "percent": percent},
    )
    owner_notifications = await communications.notify_audience(
        session,
        organization_id=account.organization_id,
        audience="platform_owner",
        event_key=f"storage.capacity.near_{label}",
        category="quota",
        title="Customer storage threshold reached",
        message=(
            f"Organization {account.organization_id} storage is {percent}% full "
            f"({used} of {limit} bytes)."
        ),
        severity="warning" if threshold < 95 else "critical",
        channels=owner_alert_channels(),
        source_type="billing_account",
        source_id=account.id,
        correlation_id=account.id,
        dedupe_prefix=f"storage:{account.id}:{limit}:{label}:{month_key}:owner",
        payload={"organization_id": account.organization_id, "used_bytes": used, "limit_bytes": limit, "percent": percent},
        respect_preferences=False,
    )
    return [*user_notifications, *owner_notifications]


async def run_account_lifecycle_alerts(session: AsyncSession) -> list:
    current = _now()
    notifications: list = []
    accounts = list(
        (
            await session.scalars(
                select(BillingAccount).where(BillingAccount.status.in_({"active", "trialing"}))
            )
        ).all()
    )
    for account in accounts:
        end_candidates = [
            value for value in (_utc(account.current_period_end), _utc(account.trial_ends_at)) if value
        ]
        if end_candidates:
            end = min(end_candidates)
            if end > current:
                remaining = end - current
                for window_days, label in SUBSCRIPTION_WINDOWS:
                    if remaining <= timedelta(days=window_days):
                        notifications.extend(
                            await _notify_subscription(
                                session,
                                account,
                                end=end,
                                window_days=window_days,
                                label=label,
                            )
                        )
                        break
        try:
            storage_limit = int((account.limits or {}).get("storage_bytes") or 0)
        except (TypeError, ValueError):
            storage_limit = 0
        if storage_limit <= 0:
            continue
        used = await organization_storage_usage_bytes(session, account.organization_id)
        if used <= 0:
            continue
        percent = used / storage_limit * 100
        for threshold, label in STORAGE_THRESHOLDS:
            if percent >= threshold:
                notifications.extend(
                    await _notify_storage(
                        session,
                        account,
                        used=used,
                        limit=storage_limit,
                        threshold=threshold,
                        label=label,
                    )
                )
                break
    return notifications
