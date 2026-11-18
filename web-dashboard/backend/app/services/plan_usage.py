"""Usage budgets for paid plans: projects, messages, responses and storage.

The Free plan keeps its own Owner policy in :mod:`app.services.free_tier`.
Paid plans read their limits from the billing catalogue that the Owner
publishes from Owner -> Portal -> Pricing (``BillingPlan.limits`` copied to the
organization's ``BillingAccount``). Limit keys are the same as the Free plan's
public policy:

``projects``, ``user_messages_per_month``, ``assistant_responses_per_month``,
``storage_bytes`` and ``max_message_characters``.

A missing, empty or negative limit means "unlimited" for that key. The Super
Owner (``*`` permission) is never limited. Usage counters live in a separate
``plan-usage-account`` record per user so the Owner's free-account list keeps
showing free users only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.auth import UserRecord
from app.db.models import OwnerControlRecord, Project, uuid_str
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

PLAN_USAGE_ACCOUNT_DOMAIN = "plan-usage-account"
PERIOD_DAYS = 30

# Public status key -> billing catalogue limit key.
LIMIT_KEYS: dict[str, str] = {
    "projects": "projects",
    "user_messages": "user_messages_per_month",
    "assistant_responses": "assistant_responses_per_month",
    "storage_bytes": "storage_bytes",
    "max_message_characters": "max_message_characters",
}
COUNTERS: dict[str, str] = {
    "user_messages": "user_messages_used",
    "assistant_responses": "assistant_responses_used",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def is_unlimited_actor(actor: UserRecord) -> bool:
    return "*" in set(actor.permissions or ())


def normalize_limit(value: Any) -> int | None:
    """Return the limit as an int, or ``None`` when it means unlimited."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


async def paid_plan_context(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    from app.services.billing import billing_context  # local: billing imports free_tier

    context = await billing_context(session, actor.organization_id)
    raw = dict(context.get("limits") or {})
    plan = context.get("plan")
    limits = (
        {key: None for key in LIMIT_KEYS}
        if is_unlimited_actor(actor)
        else {key: normalize_limit(raw.get(source)) for key, source in LIMIT_KEYS.items()}
    )
    return {
        "plan": (getattr(plan, "code", None) or actor.organization_plan or "").lower(),
        "plan_name": getattr(plan, "name", None) or actor.organization_plan,
        "limits": limits,
    }


def _new_period(now: datetime | None = None) -> dict[str, Any]:
    started = now or _now()
    return {
        "period_started_at": _iso(started),
        "period_ends_at": _iso(started + timedelta(days=PERIOD_DAYS)),
        "user_messages_used": 0,
        "assistant_responses_used": 0,
    }


def current_period(stored: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    now = _now()
    payload = {**_new_period(now), **(stored or {})}
    end = _parse(payload.get("period_ends_at"))
    if end is None or end <= now:
        return _new_period(now), True
    return payload, False


async def _usage_record(
    session: AsyncSession, user_id: str, *, lock: bool = False
) -> OwnerControlRecord:
    statement = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == PLAN_USAGE_ACCOUNT_DOMAIN,
        OwnerControlRecord.resource_id == user_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    record = await session.scalar(statement)
    if record is None:
        now = _now()
        await session.execute(
            pg_insert(OwnerControlRecord)
            .values(
                id=uuid_str(),
                domain=PLAN_USAGE_ACCOUNT_DOMAIN,
                resource_id=user_id,
                status="active",
                enabled=True,
                payload=_new_period(now),
                version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        )
        record = await session.scalar(statement)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plan usage state could not be initialized",
        )
    return record


def _limit_reached(label_ar: str, label_en: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "PLAN_LIMIT_REACHED",
            "message": (
                f"وصلت لحد باقتك الشهري ({label_ar}). رقِّ باقتك أو استنى بداية الفترة الجاية. — "
                f"You reached your plan's monthly {label_en} limit. Upgrade or wait for the next period."
            ),
        },
    )


async def consume_paid_counter(
    session: AsyncSession, actor: UserRecord, *, key: str, amount: int = 1
) -> None:
    """Count one message/response for a paid-plan user and enforce the plan limit."""
    if amount < 1:
        raise ValueError("Usage amount must be positive")
    context = await paid_plan_context(session, actor)
    limit = context["limits"].get(key)
    record = await _usage_record(session, actor.id, lock=True)
    payload, _ = current_period(record.payload)
    counter = COUNTERS[key]
    used = int(payload.get(counter, 0))
    if limit is not None and used + amount > limit:
        raise _limit_reached(
            "الرسائل" if key == "user_messages" else "الردود",
            "message" if key == "user_messages" else "response",
        )
    payload[counter] = used + amount
    record.payload = payload
    record.version += 1


async def assert_paid_message_length(
    session: AsyncSession, actor: UserRecord, *, characters: int
) -> None:
    context = await paid_plan_context(session, actor)
    maximum = context["limits"].get("max_message_characters")
    if maximum is not None and characters > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"Message length exceeds your plan's maximum of {maximum} characters",
        )


async def storage_limit_bytes(session: AsyncSession, actor: UserRecord) -> int | None:
    from app.services import free_tier

    if is_unlimited_actor(actor):
        return None
    if free_tier.is_free_actor(actor):
        policy = await free_tier.get_free_tier_policy(session)
        return normalize_limit(policy.get("storage_limit_bytes"))
    return (await paid_plan_context(session, actor))["limits"].get("storage_bytes")


async def assert_storage_available(
    session: AsyncSession, actor: UserRecord, incoming_bytes: int = 0
) -> None:
    """Refuse new files or file-producing work once the plan's storage is used up."""
    from app.services.lifecycle_alerts import organization_storage_usage_bytes

    limit = await storage_limit_bytes(session, actor)
    if limit is None:
        return
    used = await organization_storage_usage_bytes(session, actor.organization_id)
    incoming = max(0, int(incoming_bytes or 0))
    if used + incoming > limit or (incoming == 0 and used >= limit):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "STORAGE_LIMIT_REACHED",
                "allowed": limit,
                "used": used,
                "message": (
                    "مساحة التخزين في باقتك خلصت. امسح ملفات قديمة أو رقِّ باقتك. — "
                    "Your plan's storage is full. Delete old files or upgrade your plan."
                ),
            },
        )


async def paid_usage_status(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    from app.services.lifecycle_alerts import organization_storage_usage_bytes

    context = await paid_plan_context(session, actor)
    record = await _usage_record(session, actor.id)
    payload, _ = current_period(record.payload)
    projects = int(
        await session.scalar(
            select(func.count(Project.id)).where(
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        or 0
    )
    usage = {
        "projects": projects,
        "user_messages": int(payload.get("user_messages_used", 0)),
        "assistant_responses": int(payload.get("assistant_responses_used", 0)),
        "storage_bytes": await organization_storage_usage_bytes(session, actor.organization_id),
    }
    limits = context["limits"]
    return {
        "plan": context["plan"],
        "plan_name": context["plan_name"],
        "free_tier": False,
        "enabled": True,
        # ``None`` means unlimited for that key.
        "limits": limits,
        "usage": usage,
        "remaining": {
            key: (None if limits.get(key) is None else max(0, int(limits[key]) - int(value)))
            for key, value in usage.items()
        },
        "period_started_at": payload.get("period_started_at"),
        "period_ends_at": payload.get("period_ends_at"),
    }
