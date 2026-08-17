"""Owner-governed Project AI access policy for free/paid launch routing.

The platform provider pool remains owned by the protected platform organization;
consumer tenants receive only explicit routing entitlements. Provider credentials
never move into consumer organizations and user/plan policy never exposes them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AIProvider,
    BillingAccount,
    BillingPlan,
    Organization,
    OwnerControlRecord,
    User,
)
from app.services.project_execution_routing import ProjectAIProviderPolicy

PLAN_POLICY_DOMAIN = "project-ai-plan-policy"
USER_POLICY_DOMAIN = "project-ai-user-policy"
PLAN_FREE = "free"
PLAN_PAID = "paid"
SUPPORTED_ACCESS_CLASSES = frozenset({PLAN_FREE, PLAN_PAID})

# Guaranteed no external provider spend. This still requires current validated
# model evidence before the durable resolver will route any user request.
DEFAULT_FREE_POLICY: dict[str, Any] = {
    "enabled": True,
    "access_class": PLAN_FREE,
    "allowed_provider_models": ["ollama:gemma3:4b"],
    "max_project_cost_usd": 0.0,
    "offline_only": True,
    "privacy_mode": True,
    "max_fallbacks": 0,
}

# Paid routing is intentionally empty until the Owner approves current live model
# evidence. This prevents an old hard-coded model from silently becoming a launch
# default after providers change their model catalogue.
DEFAULT_PAID_POLICY: dict[str, Any] = {
    "enabled": True,
    "access_class": PLAN_PAID,
    "allowed_provider_models": [],
    "max_project_cost_usd": 1.0,
    "offline_only": False,
    "privacy_mode": False,
    "max_fallbacks": 1,
}


class ProjectAIAccessPolicyError(RuntimeError):
    """Project AI consumer access cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class ResolvedProjectAIAccess:
    organization_id: str
    user_id: str
    billing_plan_code: str
    access_class: Literal["free", "paid"]
    source: str
    policy: ProjectAIProviderPolicy
    max_fallbacks: int


def _normalize_model_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if ":" not in text or text.startswith(":") or text.endswith(":"):
        raise ProjectAIAccessPolicyError("provider model must be provider:model")
    provider, model = text.split(":", 1)
    if not provider or not model or model == "default":
        raise ProjectAIAccessPolicyError("provider model is not valid for live routing")
    return f"{provider}:{model}"


def _normalize_payload(raw: dict[str, Any], *, expected_class: str | None = None) -> dict[str, Any]:
    access_class = str(raw.get("access_class") or expected_class or "").strip().lower()
    if access_class not in SUPPORTED_ACCESS_CLASSES:
        raise ProjectAIAccessPolicyError("access_class must be free or paid")
    if expected_class and access_class != expected_class:
        raise ProjectAIAccessPolicyError("policy access class does not match its scope")
    models = sorted({_normalize_model_key(item) for item in (raw.get("allowed_provider_models") or [])})
    if access_class == PLAN_FREE and any(not item.startswith("ollama:") for item in models):
        raise ProjectAIAccessPolicyError("free policy may only use the local Ollama provider")
    cost = float(raw.get("max_project_cost_usd", 0.0 if access_class == PLAN_FREE else 1.0))
    if cost < 0 or cost > 1000:
        raise ProjectAIAccessPolicyError("max_project_cost_usd is outside the safe range")
    if access_class == PLAN_FREE and cost != 0:
        raise ProjectAIAccessPolicyError("free policy project cost must remain zero")
    max_fallbacks = int(raw.get("max_fallbacks", 0 if access_class == PLAN_FREE else 1))
    if not 0 <= max_fallbacks <= 4:
        raise ProjectAIAccessPolicyError("max_fallbacks must be between 0 and 4")
    return {
        "enabled": bool(raw.get("enabled", True)),
        "access_class": access_class,
        "allowed_provider_models": models,
        "max_project_cost_usd": cost,
        "offline_only": bool(raw.get("offline_only", access_class == PLAN_FREE)),
        "privacy_mode": bool(raw.get("privacy_mode", access_class == PLAN_FREE)),
        "max_fallbacks": max_fallbacks,
    }


def default_plan_policy(access_class: str) -> dict[str, Any]:
    if access_class == PLAN_FREE:
        return _normalize_payload(dict(DEFAULT_FREE_POLICY), expected_class=PLAN_FREE)
    if access_class == PLAN_PAID:
        return _normalize_payload(dict(DEFAULT_PAID_POLICY), expected_class=PLAN_PAID)
    raise ProjectAIAccessPolicyError("unsupported Project AI plan access class")


async def _record(
    session: AsyncSession,
    *,
    domain: str,
    resource_id: str,
) -> OwnerControlRecord | None:
    return await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == domain,
            OwnerControlRecord.resource_id == resource_id,
            OwnerControlRecord.status == "active",
            OwnerControlRecord.enabled.is_(True),
        )
    )


async def get_plan_policy(session: AsyncSession, access_class: str) -> dict[str, Any]:
    access_class = access_class.strip().lower()
    base = default_plan_policy(access_class)
    record = await _record(session, domain=PLAN_POLICY_DOMAIN, resource_id=access_class)
    if record is None:
        return base
    return _normalize_payload({**base, **dict(record.payload or {})}, expected_class=access_class)


async def get_user_override(session: AsyncSession, user_id: str) -> dict[str, Any] | None:
    record = await _record(session, domain=USER_POLICY_DOMAIN, resource_id=user_id)
    if record is None:
        return None
    return _normalize_payload(dict(record.payload or {}))


async def _billing_plan_code(
    session: AsyncSession,
    organization: Organization,
) -> tuple[str, str]:
    account = await session.scalar(
        select(BillingAccount).where(BillingAccount.organization_id == organization.id)
    )
    if account is None or account.status not in {"active", "trialing"}:
        if organization.plan.strip().lower() == PLAN_FREE and organization.status == "active":
            return PLAN_FREE, PLAN_FREE
        raise ProjectAIAccessPolicyError("organization billing access is not active")
    plan = await session.get(BillingPlan, account.plan_id) if account.plan_id else None
    plan_code = str(plan.code if plan else organization.plan or "").strip().lower()
    access_class = PLAN_FREE if plan_code == PLAN_FREE else PLAN_PAID
    return plan_code or access_class, access_class


async def resolve_project_ai_access(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
) -> ResolvedProjectAIAccess:
    organization = await session.get(Organization, organization_id)
    user = await session.get(User, user_id)
    if organization is None or user is None or user.organization_id != organization_id:
        raise ProjectAIAccessPolicyError("Project AI consumer scope is invalid")
    if organization.status not in {"active", "trial"} or user.status not in {"active", "online"}:
        raise ProjectAIAccessPolicyError("Project AI consumer is not active")
    plan_code, access_class = await _billing_plan_code(session, organization)
    selected = await get_plan_policy(session, access_class)
    source = f"plan:{access_class}"
    override = await get_user_override(session, user_id)
    if override is not None:
        selected = override
        source = f"user:{user_id}"
    if not selected["enabled"]:
        raise ProjectAIAccessPolicyError("Project AI access is disabled by Owner policy")
    model_keys = frozenset(selected["allowed_provider_models"])
    if not model_keys:
        raise ProjectAIAccessPolicyError("Owner policy has no approved provider models")
    providers = frozenset(item.split(":", 1)[0] for item in model_keys)
    if selected["access_class"] == PLAN_FREE and providers != {"ollama"}:
        raise ProjectAIAccessPolicyError("free Project AI access must remain local-only")
    policy = ProjectAIProviderPolicy(
        allowed_providers=providers,
        allowed_provider_models=model_keys,
        provider_scope_organization_id=settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID,
        offline_only=bool(selected["offline_only"]),
        privacy_mode=bool(selected["privacy_mode"]),
        max_total_estimated_cost_usd=float(selected["max_project_cost_usd"]),
    )
    return ResolvedProjectAIAccess(
        organization_id=organization_id,
        user_id=user_id,
        billing_plan_code=plan_code,
        access_class=selected["access_class"],
        source=source,
        policy=policy,
        max_fallbacks=int(selected["max_fallbacks"]),
    )


async def set_plan_policy(
    session: AsyncSession,
    *,
    access_class: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    access_class = access_class.strip().lower()
    base = default_plan_policy(access_class)
    normalized = _normalize_payload({**base, **payload}, expected_class=access_class)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == PLAN_POLICY_DOMAIN,
            OwnerControlRecord.resource_id == access_class,
        )
        .with_for_update()
    )
    if record is None:
        record = OwnerControlRecord(
            domain=PLAN_POLICY_DOMAIN,
            resource_id=access_class,
            status="active",
            enabled=True,
            payload=normalized,
            version=1,
        )
        session.add(record)
    else:
        record.status = "active"
        record.enabled = True
        record.payload = normalized
        record.version += 1
    await session.flush()
    return normalized


async def set_user_policy(
    session: AsyncSession,
    *,
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise ProjectAIAccessPolicyError("user was not found")
    normalized = _normalize_payload(payload)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == USER_POLICY_DOMAIN,
            OwnerControlRecord.resource_id == user_id,
        )
        .with_for_update()
    )
    if record is None:
        record = OwnerControlRecord(
            domain=USER_POLICY_DOMAIN,
            resource_id=user_id,
            status="active",
            enabled=True,
            payload=normalized,
            version=1,
        )
        session.add(record)
    else:
        record.status = "active"
        record.enabled = True
        record.payload = normalized
        record.version += 1
    await session.flush()
    return normalized


async def disable_user_policy(session: AsyncSession, *, user_id: str) -> bool:
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == USER_POLICY_DOMAIN,
            OwnerControlRecord.resource_id == user_id,
        )
        .with_for_update()
    )
    if record is None:
        return False
    record.enabled = False
    record.status = "disabled"
    record.version += 1
    await session.flush()
    return True


async def project_ai_access_owner_snapshot(session: AsyncSession) -> dict[str, Any]:
    platform_org_id = settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID
    providers = list(
        (
            await session.scalars(
                select(AIProvider)
                .where(AIProvider.organization_id == platform_org_id)
                .order_by(AIProvider.type, AIProvider.id)
            )
        ).all()
    )
    provider_rows: list[dict[str, Any]] = []
    for provider in providers:
        config = dict(provider.config or {})
        raw_models = config.get("validated_models")
        models = []
        if isinstance(raw_models, list):
            for row in raw_models:
                if isinstance(row, dict) and str(row.get("model") or "").strip():
                    models.append({
                        "model": str(row.get("model")),
                        "expires_at": row.get("expires_at"),
                        "local": bool(row.get("local", False)),
                        "policy_ref": row.get("policy_ref"),
                    })
        provider_rows.append({
            "id": provider.id,
            "type": provider.type,
            "status": provider.status,
            "enabled": bool(config.get("enabled", True)),
            "validated_models": sorted(models, key=lambda item: item["model"]),
        })
    overrides = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == USER_POLICY_DOMAIN,
                    OwnerControlRecord.status == "active",
                    OwnerControlRecord.enabled.is_(True),
                )
                .order_by(OwnerControlRecord.resource_id)
            )
        ).all()
    )
    overrides_by_user = {
        row.resource_id: _normalize_payload(dict(row.payload or {})) for row in overrides
    }
    user_rows = list(
        (
            await session.execute(
                select(User, Organization.name, Organization.plan, BillingPlan.code)
                .join(Organization, Organization.id == User.organization_id)
                .outerjoin(
                    BillingAccount, BillingAccount.organization_id == User.organization_id
                )
                .outerjoin(BillingPlan, BillingPlan.id == BillingAccount.plan_id)
                .where(
                    User.deleted_at.is_(None),
                    User.status.in_({"active", "online"}),
                )
                .order_by(User.email.asc(), User.id.asc())
                .limit(1000)
            )
        ).all()
    )
    users: list[dict[str, Any]] = []
    for user, organization_name, organization_plan, billing_plan_code in user_rows:
        plan_code = str(billing_plan_code or organization_plan or "").strip().lower()
        users.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "organization_id": user.organization_id,
                "organization_name": organization_name,
                "plan": plan_code,
                "access_class": PLAN_FREE if plan_code == PLAN_FREE else PLAN_PAID,
                "override_active": user.id in overrides_by_user,
            }
        )
    return {
        "platform_provider_organization_id": platform_org_id,
        "plan_policies": {
            PLAN_FREE: await get_plan_policy(session, PLAN_FREE),
            PLAN_PAID: await get_plan_policy(session, PLAN_PAID),
        },
        "user_overrides": [
            {"user_id": user_id, "policy": policy}
            for user_id, policy in sorted(overrides_by_user.items())
        ],
        "users": users,
        "providers": provider_rows,
    }
