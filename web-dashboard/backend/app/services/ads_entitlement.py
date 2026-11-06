"""P4 Meta Ads access: the ``ads.manage`` plan entitlement and the Owner policy.

Resolution order (first match wins), following ``security_entitlement``:

1. ``Super Owner`` role -> ``owner``.
2. The Owner policy is disabled -> denied (``ads-disabled``).
3. A Growth & Social Owner override for the ``ads.manage`` capability
   (user, then organization) -> granted or denied as the Owner set it.
4. An active subscription (``active``/``trialing``, period not ended, billing
   account not suspended) whose plan code is listed in the policy
   ``plan_codes``, or whose plan carries the policy ``entitlement`` flag
   (default ``ads.manage``) or the legacy ``growth.ads.manage`` flag ->
   ``subscriber``.

The Owner policy (``owner_control_records`` domain ``ads-management``) also
holds the hard spend guard: the per-user daily and lifetime caps in the ad
account's minor currency units, optional per-user overrides, whether
activation is allowed at all, and per-user limits. No database id is ever
hardcoded and nothing here contacts a provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import OwnerControlRecord
from app.services import ads_metrics as metrics
from app.services import growth_access, security_entitlement

POLICY_DOMAIN = "ads-management"
POLICY_RESOURCE = "policy"
ENTITLEMENT = "ads.manage"
LEGACY_ENTITLEMENT = "growth.ads.manage"
PLAN_REQUIRED = "ADS_PLAN_REQUIRED"
ADS_DISABLED = "ADS_DISABLED"
MAX_USER_CAP_OVERRIDES = 500
MAX_MONEY_MINOR = 10_000_000_000

DEFAULT_POLICY: dict[str, Any] = {
    "enabled": True,
    "entitlement": ENTITLEMENT,
    "plan_codes": [],
    "activation_enabled": True,
    # Per-user caps, in the ad account currency's minor units.
    "daily_cap_minor": 5_000,
    "lifetime_cap_minor": 50_000,
    "user_caps": {},
    "max_ad_accounts_per_user": 5,
    "max_active_campaigns_per_user": 5,
    "max_recommendation_runs_per_day": 10,
}


class AdsAccessError(PermissionError):
    """A user-facing refusal with a stable machine-readable code."""

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
class AdsAccess:
    level: str | None
    source: str | None
    reason: str
    plan_code: str | None = None
    policy: dict[str, Any] = field(default_factory=dict)

    @property
    def granted(self) -> bool:
        return self.level is not None

    @property
    def is_owner(self) -> bool:
        return self.level == "owner"

    def require(self) -> None:
        if self.granted:
            return
        if self.reason == "ads-disabled":
            raise AdsAccessError(ADS_DISABLED, "Ads management is turned off by the Owner")
        raise AdsAccessError(
            PLAN_REQUIRED,
            "Ads management is not included in your current plan",
            extra={"entitlement": str(self.policy.get("entitlement") or ENTITLEMENT)},
        )

    def caps_for(self, user_id: str) -> metrics.Caps:
        override = dict((self.policy.get("user_caps") or {}).get(user_id) or {})
        return metrics.Caps(
            daily_minor=int(override.get("daily_cap_minor", self.policy["daily_cap_minor"])),
            lifetime_minor=int(
                override.get("lifetime_cap_minor", self.policy["lifetime_cap_minor"])
            ),
        )

    def public(self, user_id: str) -> dict[str, Any]:
        caps = self.caps_for(user_id)
        return {
            "allowed": self.granted,
            "level": self.level,
            "source": self.source,
            "reason": self.reason,
            "plan_code": self.plan_code,
            "entitlement": str(self.policy.get("entitlement") or ENTITLEMENT),
            "activation_enabled": bool(self.policy.get("activation_enabled")),
            "daily_cap_minor": caps.daily_minor,
            "lifetime_cap_minor": caps.lifetime_minor,
            "max_ad_accounts": int(self.policy["max_ad_accounts_per_user"]),
            "max_active_campaigns": int(self.policy["max_active_campaigns_per_user"]),
            "owner_token_fallback": self.is_owner,
            "live_verified": False,
        }


def _bounded(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _plan_codes(values: Any) -> list[str]:
    codes = sorted(
        {
            str(value).strip().lower().replace("_", "-").replace(" ", "-")
            for value in list(values or [])
            if str(value).strip()
        }
    )
    if len(codes) > 20:
        raise ValueError("too-many-plan-codes")
    return codes


def _user_caps(raw: Any, *, defaults: dict[str, Any]) -> dict[str, dict[str, int]]:
    if not isinstance(raw, dict):
        return {}
    if len(raw) > MAX_USER_CAP_OVERRIDES:
        raise ValueError("too-many-user-cap-overrides")
    caps: dict[str, dict[str, int]] = {}
    for user_id, value in raw.items():
        key = str(user_id).strip()
        if not key or len(key) > 36 or not isinstance(value, dict):
            raise ValueError("user-cap-override-invalid")
        caps[key] = {
            "daily_cap_minor": _bounded(
                value.get("daily_cap_minor"), defaults["daily_cap_minor"], 0, MAX_MONEY_MINOR
            ),
            "lifetime_cap_minor": _bounded(
                value.get("lifetime_cap_minor"), defaults["lifetime_cap_minor"], 0, MAX_MONEY_MINOR
            ),
        }
    return caps


def normalize_policy(raw: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_POLICY, **raw}
    entitlement = str(merged.get("entitlement") or "").strip()[:120] or ENTITLEMENT
    policy = {
        "enabled": bool(merged.get("enabled", True)),
        "entitlement": entitlement,
        "plan_codes": _plan_codes(merged.get("plan_codes")),
        "activation_enabled": bool(merged.get("activation_enabled", True)),
        "daily_cap_minor": _bounded(
            merged.get("daily_cap_minor"), DEFAULT_POLICY["daily_cap_minor"], 0, MAX_MONEY_MINOR
        ),
        "lifetime_cap_minor": _bounded(
            merged.get("lifetime_cap_minor"),
            DEFAULT_POLICY["lifetime_cap_minor"],
            0,
            MAX_MONEY_MINOR,
        ),
        "max_ad_accounts_per_user": _bounded(
            merged.get("max_ad_accounts_per_user"), DEFAULT_POLICY["max_ad_accounts_per_user"], 1, 50
        ),
        "max_active_campaigns_per_user": _bounded(
            merged.get("max_active_campaigns_per_user"),
            DEFAULT_POLICY["max_active_campaigns_per_user"],
            0,
            100,
        ),
        "max_recommendation_runs_per_day": _bounded(
            merged.get("max_recommendation_runs_per_day"),
            DEFAULT_POLICY["max_recommendation_runs_per_day"],
            0,
            500,
        ),
    }
    policy["user_caps"] = _user_caps(merged.get("user_caps"), defaults=policy)
    return policy


async def _record(session: AsyncSession, *, for_update: bool = False) -> OwnerControlRecord | None:
    stmt = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == POLICY_DOMAIN,
        OwnerControlRecord.resource_id == POLICY_RESOURCE,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def get_policy(session: AsyncSession) -> dict[str, Any]:
    record = await _record(session)
    if record is None:
        return normalize_policy({})
    policy = normalize_policy(dict(record.payload or {}))
    policy["enabled"] = bool(record.enabled and policy["enabled"])
    return policy


async def update_policy(session: AsyncSession, updates: dict[str, Any]) -> dict[str, Any]:
    record = await _record(session, for_update=True)
    current = normalize_policy(dict(record.payload or {})) if record is not None else normalize_policy({})
    merged = normalize_policy({**current, **updates})
    if record is None:
        record = OwnerControlRecord(
            domain=POLICY_DOMAIN,
            resource_id=POLICY_RESOURCE,
            status="active",
            enabled=bool(merged["enabled"]),
            payload=merged,
            version=1,
        )
        session.add(record)
    else:
        record.payload = merged
        record.enabled = bool(merged["enabled"])
        record.version += 1
    await session.flush()
    return merged


def plan_entitled(plan_code: str, plan_entitlements: list[str], policy: dict[str, Any]) -> bool:
    if policy["plan_codes"]:
        return plan_code in policy["plan_codes"]
    flags = {str(item) for item in plan_entitlements}
    return bool({policy["entitlement"], LEGACY_ENTITLEMENT} & flags)


async def resolve_access(
    session: AsyncSession, actor: UserRecord, *, policy: dict[str, Any] | None = None
) -> AdsAccess:
    if policy is None:
        policy = await get_policy(session)
    if actor.role == "Super Owner":
        return AdsAccess("owner", "owner", "owner", policy=policy)
    if not policy["enabled"]:
        return AdsAccess(None, None, "ads-disabled", policy=policy)
    decision = await growth_access.effective_access(session, actor, "ads.manage")
    if decision.source == "owner-override":
        if decision.allowed:
            return AdsAccess("grant", "grant", "owner-grant", policy=policy)
        return AdsAccess(None, None, "owner-deny", policy=policy)
    if decision.source in {"account", "billing"}:
        return AdsAccess(None, None, decision.reason, policy=policy)
    plan = await security_entitlement.active_subscription_plan(session, actor.organization_id)
    if plan is not None and plan_entitled(plan.code, list(plan.entitlements or []), policy):
        return AdsAccess("subscriber", "subscription", "entitled", plan.code, policy=policy)
    if decision.allowed and not policy["plan_codes"]:
        # The billing account itself carries the legacy growth.ads.manage flag.
        return AdsAccess(
            "subscriber",
            "subscription",
            "entitled",
            plan.code if plan is not None else None,
            policy=policy,
        )
    return AdsAccess(
        None,
        None,
        "not-entitled",
        plan.code if plan is not None else None,
        policy=policy,
    )
