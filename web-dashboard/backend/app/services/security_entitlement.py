"""Security Lab access resolution: Super Owner, Owner grants, and top-plan subscriptions.

Owner decision 2026-11-04: website security scanning is available only to
subscribers on the highest subscription plan; the Super Owner always has access
and ``SecurityAccessGrant`` rows remain the Owner override.

Resolution order (first match wins):

1. ``Super Owner`` role -> ``owner``.
2. An active, unexpired ``SecurityAccessGrant`` -> the granted level.
3. An active subscription (``active``/``trialing``, period not ended, billing
   account not suspended) on an *entitled* plan -> ``subscriber``.

A plan is entitled when (in order of precedence) its code is listed in the
Owner policy ``subscription_access.plan_codes``; else when the billing plan
carries the ``subscription_access.entitlement`` flag (default
``security.web_scanning``; the internal ``*`` wildcard does not count); else,
when no active plan carries the flag, the top-ranked active plan, ranked by its
highest enabled monthly-equivalent price. No database id is ever hardcoded.

Subscriber access is scoped to the subscriber's own verified external targets
and bounded by the configurable usage limits below. Losing the subscription
removes the ability to start new scans; existing reports remain readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    BillingAccount,
    BillingPlan,
    BillingPrice,
    BillingSubscription,
    SecurityScan,
    SecurityTarget,
    User,
)
from app.services import security_fabric

ACTIVE_SUBSCRIPTION_STATUSES = ("active", "trialing")
ACTIVE_ACCOUNT_STATUSES = ("active", "trial")
ACTIVE_SCAN_STATES = ("queued", "running")

PLAN_REQUIRED = "SECURITY_PLAN_REQUIRED"
LAB_DISABLED = "SECURITY_LAB_DISABLED"
PROFILE_NOT_ALLOWED = "SECURITY_PROFILE_NOT_ALLOWED"
TARGET_LIMIT = "SECURITY_TARGET_LIMIT_REACHED"
MONTHLY_SCAN_LIMIT = "SECURITY_MONTHLY_SCAN_LIMIT_REACHED"
CONCURRENT_SCAN_LIMIT = "SECURITY_CONCURRENT_SCAN_LIMIT_REACHED"
REVERIFY_FAILED = "SECURITY_TARGET_REVERIFICATION_FAILED"


class SecurityLabError(PermissionError):
    """A user-facing Security Lab refusal with a stable machine-readable code.

    It subclasses ``PermissionError`` so callers that predate structured codes
    still fail closed; the public endpoints translate it into ``detail.code``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 403,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = dict(extra or {})

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


@dataclass(frozen=True)
class SecurityAccess:
    level: str | None
    source: str | None
    plan_code: str | None = None
    entitled_plan_codes: tuple[str, ...] = ()
    entitlement_basis: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def granted(self) -> bool:
        return self.level is not None

    @property
    def is_subscriber(self) -> bool:
        return self.source == "subscription"

    @property
    def is_owner(self) -> bool:
        return self.level == "owner"

    def profiles(self) -> list[str]:
        return [
            profile
            for profile in security_fabric.PROFILE_RANK
            if security_fabric.profile_allowed(self.level, profile)
        ]

    def plan_required(self) -> SecurityLabError:
        return SecurityLabError(
            PLAN_REQUIRED,
            "Website security scanning is included only in the highest subscription plan",
            extra={"entitled_plans": list(self.entitled_plan_codes)},
        )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def month_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    current = moment or security_fabric.now()
    start = current.astimezone(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def _monthly_equivalent(price: BillingPrice) -> float | None:
    if not price.enabled or price.amount_minor is None or price.amount_minor <= 0:
        return None
    return float(price.amount_minor) / float(max(int(price.months or 1), 1))


async def top_ranked_plan_codes(session: AsyncSession) -> list[str]:
    """Return the active plan code(s) with the highest monthly-equivalent price.

    Prices in a plan's default currency are preferred so one plan's foreign
    currency price cannot outrank another by unit alone. Ties return every tied
    plan so the Owner is never surprised by an arbitrary tie-break.
    """

    plans = list(
        (await session.scalars(select(BillingPlan).where(BillingPlan.status == "active"))).all()
    )
    if not plans:
        return []
    by_id = {plan.id: plan for plan in plans}
    prices = list(
        (
            await session.scalars(
                select(BillingPrice).where(BillingPrice.plan_id.in_(list(by_id)))
            )
        ).all()
    )
    ranking: dict[str, float] = {}
    for price in prices:
        plan = by_id[price.plan_id]
        value = _monthly_equivalent(price)
        if value is None or price.currency != plan.default_currency:
            continue
        ranking[plan.code] = max(ranking.get(plan.code, 0.0), value)
    if not ranking:
        return []
    best = max(ranking.values())
    return sorted(code for code, value in ranking.items() if value == best)


async def entitled_plans(
    session: AsyncSession, settings: dict[str, Any]
) -> tuple[list[str], str]:
    explicit = [str(code) for code in settings.get("plan_codes") or []]
    if explicit:
        return sorted(set(explicit)), "policy_plan_codes"
    flag = str(settings.get("entitlement") or "")
    plans = list(
        (await session.scalars(select(BillingPlan).where(BillingPlan.status == "active"))).all()
    )
    flagged = sorted(
        plan.code for plan in plans if flag and flag in list(plan.entitlements or [])
    )
    if flagged:
        return flagged, "plan_entitlement"
    return await top_ranked_plan_codes(session), "top_ranked_plan"


async def active_subscription_plan(
    session: AsyncSession, organization_id: str
) -> BillingPlan | None:
    """Return the plan of the organization's current paid subscription, if any."""

    account = await session.scalar(
        select(BillingAccount).where(BillingAccount.organization_id == organization_id)
    )
    if account is not None and account.status not in ACTIVE_ACCOUNT_STATUSES:
        return None
    rows = list(
        (
            await session.scalars(
                select(BillingSubscription)
                .where(
                    BillingSubscription.organization_id == organization_id,
                    BillingSubscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES),
                )
                .order_by(BillingSubscription.created_at.desc())
            )
        ).all()
    )
    moment = security_fabric.now()
    for subscription in rows:
        period_end = _as_utc(subscription.current_period_end)
        if period_end is not None and period_end <= moment:
            continue
        plan = await session.get(BillingPlan, subscription.plan_id)
        if plan is not None:
            return plan
    return None


async def resolve_access(
    session: AsyncSession,
    actor: UserRecord,
    *,
    policy: dict[str, Any] | None = None,
) -> SecurityAccess:
    if policy is None:
        policy = await security_fabric.get_policy(session)
    settings = dict(policy.get("subscription_access") or {})
    # Owner and explicit Owner grants never touch billing state.
    level = await security_fabric.access_level(session, actor)
    if level is not None:
        return SecurityAccess(
            level=level,
            source="owner" if level == "owner" else "grant",
            settings=settings,
        )
    if not settings.get("enabled", True):
        return SecurityAccess(level=None, source=None, settings=settings)
    codes, basis = await entitled_plans(session, settings)
    plan = await active_subscription_plan(session, actor.organization_id)
    if plan is not None and plan.code in codes:
        return SecurityAccess(
            level="subscriber",
            source="subscription",
            plan_code=plan.code,
            entitled_plan_codes=tuple(codes),
            entitlement_basis=basis,
            settings=settings,
        )
    return SecurityAccess(
        level=None,
        source=None,
        plan_code=plan.code if plan is not None else None,
        entitled_plan_codes=tuple(codes),
        entitlement_basis=basis,
        settings=settings,
    )


async def lock_actor(session: AsyncSession, actor: UserRecord) -> None:
    """Serialize a subscriber's quota-consuming requests on their user row."""

    await session.execute(
        select(User.id).where(User.id == actor.id).with_for_update()
    )


async def usage(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    start, end = month_bounds()
    targets = int(
        await session.scalar(
            select(func.count(SecurityTarget.id)).where(
                SecurityTarget.organization_id == actor.organization_id,
                SecurityTarget.created_by_id == actor.id,
                SecurityTarget.kind == "external_authorized",
                SecurityTarget.status == "active",
            )
        )
        or 0
    )
    verified_targets = int(
        await session.scalar(
            select(func.count(SecurityTarget.id)).where(
                SecurityTarget.organization_id == actor.organization_id,
                SecurityTarget.created_by_id == actor.id,
                SecurityTarget.kind == "external_authorized",
                SecurityTarget.status == "active",
                SecurityTarget.authorization_status == "verified",
            )
        )
        or 0
    )
    scans_this_month = int(
        await session.scalar(
            select(func.count(SecurityScan.id)).where(
                SecurityScan.organization_id == actor.organization_id,
                SecurityScan.requested_by_id == actor.id,
                SecurityScan.created_at >= start,
                SecurityScan.created_at < end,
            )
        )
        or 0
    )
    active_scans = int(
        await session.scalar(
            select(func.count(SecurityScan.id)).where(
                SecurityScan.organization_id == actor.organization_id,
                SecurityScan.requested_by_id == actor.id,
                SecurityScan.status.in_(ACTIVE_SCAN_STATES),
            )
        )
        or 0
    )
    return {
        "targets": targets,
        "verified_targets": verified_targets,
        "scans_this_month": scans_this_month,
        "active_scans": active_scans,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }


def limits(access: SecurityAccess) -> dict[str, int] | None:
    if not access.is_subscriber:
        return None
    settings = access.settings
    return {
        "max_verified_targets": int(settings["max_verified_targets"]),
        "max_scans_per_month": int(settings["max_scans_per_month"]),
        "max_concurrent_scans": int(settings["max_concurrent_scans"]),
    }


def _limit_error(code: str, message: str, key: str, allowed: int, used: int) -> SecurityLabError:
    return SecurityLabError(
        code,
        message,
        status_code=429,
        extra={"limit": key, "allowed": allowed, "used": used},
    )


async def enforce_target_limit(
    session: AsyncSession,
    access: SecurityAccess,
    actor: UserRecord,
    *,
    origin: str | None = None,
    verifying: bool = False,
) -> None:
    """Bound a subscriber's target inventory.

    Registration counts every active target the subscriber owns (pending or
    verified), excluding the origin being re-registered; verification counts
    verified targets only so an existing pending row can still be verified.
    """

    bounds = limits(access)
    if bounds is None:
        return
    allowed = bounds["max_verified_targets"]
    await lock_actor(session, actor)
    stmt = select(func.count(SecurityTarget.id)).where(
        SecurityTarget.organization_id == actor.organization_id,
        SecurityTarget.created_by_id == actor.id,
        SecurityTarget.kind == "external_authorized",
        SecurityTarget.status == "active",
    )
    if verifying:
        stmt = stmt.where(SecurityTarget.authorization_status == "verified")
    if origin is not None:
        stmt = stmt.where(SecurityTarget.origin != origin)
    used = int(await session.scalar(stmt) or 0)
    if used >= allowed:
        raise _limit_error(
            TARGET_LIMIT,
            "Your plan's verified website limit has been reached; remove a site before adding another",
            "max_verified_targets",
            allowed,
            used,
        )


async def enforce_scan_limits(
    session: AsyncSession, access: SecurityAccess, actor: UserRecord
) -> None:
    bounds = limits(access)
    if bounds is None:
        return
    await lock_actor(session, actor)
    current = await usage(session, actor)
    if current["active_scans"] >= bounds["max_concurrent_scans"]:
        raise _limit_error(
            CONCURRENT_SCAN_LIMIT,
            "A scan is already running; wait for it to finish before starting another",
            "max_concurrent_scans",
            bounds["max_concurrent_scans"],
            current["active_scans"],
        )
    if current["scans_this_month"] >= bounds["max_scans_per_month"]:
        raise _limit_error(
            MONTHLY_SCAN_LIMIT,
            "Your plan's monthly scan allowance has been used",
            "max_scans_per_month",
            bounds["max_scans_per_month"],
            current["scans_this_month"],
        )


def subscriber_owns_target(
    access: SecurityAccess, actor: UserRecord, target: SecurityTarget
) -> bool:
    if not access.is_subscriber:
        return True
    return target.kind == "external_authorized" and target.created_by_id == actor.id


def privileged_inventory(access: SecurityAccess, actor: UserRecord) -> bool:
    """Owner and Owner-granted operators see the organization inventory."""

    return actor.role == "Super Owner" or access.source in {"owner", "grant"}
