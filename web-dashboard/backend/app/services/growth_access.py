"""Owner-controlled Growth & Social capability access resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import AuditEvent, OwnerControlRecord
from app.services import billing

MODULE = "growth-social"
OVERRIDE_DOMAIN = "growth-social-access"

CAPABILITIES: dict[str, dict[str, Any]] = {
    "campaign.research": {"default_entitlements": ["growth.campaign.research"]},
    "campaign.simulation": {"default_entitlements": ["growth.campaign.simulation"]},
    "social.accounts": {"default_entitlements": ["growth.social.accounts"]},
    "content.publish": {"default_entitlements": ["growth.content.publish"], "approval_default": True},
    "inbox.manage": {"default_entitlements": ["growth.inbox.manage"]},
    "analytics.read": {"default_entitlements": ["growth.analytics.read"]},
    "leads.manage": {"default_entitlements": ["growth.leads.manage"], "approval_default": True},
    "ads.manage": {"default_entitlements": ["growth.ads.manage"], "approval_default": True},
    "automations.manage": {"default_entitlements": ["growth.automations.manage"], "approval_default": True},
    "exports.create": {"default_entitlements": ["growth.exports.create"]},
}


@dataclass(frozen=True)
class GrowthAccessDecision:
    capability: str
    allowed: bool
    source: str
    reason: str
    approval_required: bool
    limits: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "allowed": self.allowed,
            "source": self.source,
            "reason": self.reason,
            "approval_required": self.approval_required,
            "limits": self.limits,
        }


def _resource_id(scope: str, subject_id: str, capability: str) -> str:
    return f"{scope}:{subject_id}:{capability}"


async def _override(
    session: AsyncSession, scope: str, subject_id: str, capability: str
) -> OwnerControlRecord | None:
    return await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == OVERRIDE_DOMAIN,
            OwnerControlRecord.resource_id == _resource_id(scope, subject_id, capability),
        )
    )


async def effective_access(
    session: AsyncSession,
    actor: UserRecord,
    capability: str,
) -> GrowthAccessDecision:
    definition = CAPABILITIES.get(capability)
    if definition is None:
        return GrowthAccessDecision(capability, False, "catalog", "unknown-capability", False, {})

    if actor.status not in {"active", "online"}:
        return GrowthAccessDecision(capability, False, "account", "user-inactive", False, {})

    context = await billing.billing_context(session, actor.organization_id)
    account = context["account"]
    if account.status not in billing.ACTIVE_ACCOUNT_STATUSES:
        return GrowthAccessDecision(capability, False, "billing", "account-suspended", False, {})

    user_override = await _override(session, "user", actor.id, capability)
    org_override = await _override(session, "organization", actor.organization_id, capability)
    chosen = user_override or org_override
    if chosen is not None:
        payload = dict(chosen.payload or {})
        allowed = bool(chosen.enabled and payload.get("allowed", True))
        return GrowthAccessDecision(
            capability,
            allowed,
            "owner-override",
            "owner-grant" if allowed else "owner-deny",
            bool(payload.get("approval_required", definition.get("approval_default", False))),
            dict(payload.get("limits") or {}),
        )

    entitlements = set(str(item) for item in (context.get("entitlements") or []))
    required = set(definition.get("default_entitlements") or [])
    allowed = bool(required & entitlements)
    return GrowthAccessDecision(
        capability,
        allowed,
        "plan-entitlement",
        "entitled" if allowed else "not-entitled",
        bool(definition.get("approval_default", False)),
        {},
    )


async def set_owner_override(
    session: AsyncSession,
    owner: UserRecord,
    *,
    scope: str,
    subject_id: str,
    capability: str,
    allowed: bool,
    approval_required: bool = False,
    limits: dict[str, Any] | None = None,
) -> GrowthAccessDecision:
    if scope not in {"user", "organization"}:
        raise ValueError("unsupported-scope")
    if capability not in CAPABILITIES:
        raise ValueError("unknown-capability")
    resource_id = _resource_id(scope, subject_id, capability)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == OVERRIDE_DOMAIN,
            OwnerControlRecord.resource_id == resource_id,
        )
        .with_for_update()
    )
    payload = {
        "scope": scope,
        "subject_id": subject_id,
        "capability": capability,
        "allowed": bool(allowed),
        "approval_required": bool(approval_required),
        "limits": dict(limits or {}),
        "updated_by": owner.id,
    }
    if record is None:
        record = OwnerControlRecord(
            domain=OVERRIDE_DOMAIN,
            resource_id=resource_id,
            status="active",
            enabled=True,
            payload=payload,
            version=1,
        )
        session.add(record)
    else:
        record.status = "active"
        record.enabled = True
        record.payload = payload
        record.version += 1
    session.add(
        AuditEvent(
            organization_id=owner.organization_id,
            user_id=owner.id,
            action="growth.access.override",
            resource_type="growth_capability",
            resource_id=resource_id,
            details={
                "scope": scope,
                "subject_id": subject_id,
                "capability": capability,
                "allowed": bool(allowed),
                "approval_required": bool(approval_required),
                "limits": dict(limits or {}),
            },
        )
    )
    await session.flush()
    return GrowthAccessDecision(
        capability,
        bool(allowed),
        "owner-override",
        "owner-grant" if allowed else "owner-deny",
        bool(approval_required),
        dict(limits or {}),
    )


async def clear_owner_override(
    session: AsyncSession,
    owner: UserRecord,
    *,
    scope: str,
    subject_id: str,
    capability: str,
) -> bool:
    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == OVERRIDE_DOMAIN,
            OwnerControlRecord.resource_id == _resource_id(scope, subject_id, capability),
        )
    )
    if record is None:
        return False
    await session.delete(record)
    session.add(
        AuditEvent(
            organization_id=owner.organization_id,
            user_id=owner.id,
            action="growth.access.override_cleared",
            resource_type="growth_capability",
            resource_id=_resource_id(scope, subject_id, capability),
            details={"scope": scope, "subject_id": subject_id, "capability": capability},
        )
    )
    await session.flush()
    return True


async def snapshot(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    decisions = [await effective_access(session, actor, capability) for capability in CAPABILITIES]
    return {
        "module": MODULE,
        "user_id": actor.id,
        "organization_id": actor.organization_id,
        "capabilities": [decision.as_dict() for decision in decisions],
    }
