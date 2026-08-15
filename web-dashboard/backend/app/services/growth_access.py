"""Owner-controlled Growth & Social capability access resolution."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import AuditEvent, Organization, OwnerControlRecord, User
from app.services import billing

MODULE = "growth-social"
OVERRIDE_DOMAIN = "growth-social-access"
MAX_LIMITS_BYTES = 4096
MAX_LIMITS_DEPTH = 4
MAX_LIMITS_ITEMS = 50
MAX_LIMIT_STRING = 500
_SENSITIVE_LIMIT_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "credential",
    "credential_ref",
}

CAPABILITIES: dict[str, dict[str, Any]] = {
    "campaign.research": {"default_entitlements": ["growth.campaign.research"]},
    "campaign.simulation": {"default_entitlements": ["growth.campaign.simulation"]},
    "social.accounts": {"default_entitlements": ["growth.social.accounts"]},
    "content.publish": {
        "default_entitlements": ["growth.content.publish"],
        "approval_default": True,
    },
    "inbox.manage": {"default_entitlements": ["growth.inbox.manage"]},
    "analytics.read": {"default_entitlements": ["growth.analytics.read"]},
    "leads.manage": {
        "default_entitlements": ["growth.leads.manage"],
        "approval_default": True,
    },
    "ads.manage": {
        "default_entitlements": ["growth.ads.manage"],
        "approval_default": True,
    },
    "automations.manage": {
        "default_entitlements": ["growth.automations.manage"],
        "approval_default": True,
    },
    "exports.create": {"default_entitlements": ["growth.exports.create"]},
    "integrations.manage": {
        "default_entitlements": ["growth.integrations.manage"],
        "approval_default": True,
    },
    "teams.manage": {"default_entitlements": ["growth.teams.manage"]},
    "reports.manage": {"default_entitlements": ["growth.reports.manage"]},
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


def _require_super_owner(owner: UserRecord) -> None:
    if owner.role != "Super Owner":
        raise ValueError("super-owner-required")


def _safe_subject_id(value: str) -> str:
    clean = str(value or "").strip()
    if (
        not clean
        or len(clean) > 160
        or ":" in clean
        or any(ord(character) < 32 for character in clean)
    ):
        raise ValueError("invalid-subject-id")
    return clean


def _normalized_limit_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _limit_key_is_sensitive(value: object) -> bool:
    normalized = _normalized_limit_key(value)
    return (
        normalized in _SENSITIVE_LIMIT_KEYS
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
        or normalized.endswith("_api_key")
        or normalized.endswith("_private_key")
    )


def _validate_limit_value(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_LIMITS_DEPTH:
        raise ValueError("limits-too-deep")
    if isinstance(value, dict):
        if len(value) > MAX_LIMITS_ITEMS:
            raise ValueError("limits-too-many-items")
        safe: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ValueError("invalid-limit-key")
            if _limit_key_is_sensitive(raw_key):
                raise ValueError("credential-material-forbidden-in-limits")
            safe[raw_key] = _validate_limit_value(item, depth=depth + 1)
        return safe
    if isinstance(value, list):
        if len(value) > MAX_LIMITS_ITEMS:
            raise ValueError("limits-too-many-items")
        return [_validate_limit_value(item, depth=depth + 1) for item in value]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > 9_000_000_000_000_000_000:
            raise ValueError("limit-number-too-large")
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > 1_000_000_000_000_000.0:
            raise ValueError("invalid-limit-number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_LIMIT_STRING:
            raise ValueError("limit-string-too-long")
        lowered = value.lower()
        if re.search(r"\bbearer\s+[^\s]{8,}", lowered) or re.search(
            r"\b(?:token|secret|password|api[_-]?key)\s*[:=]\s*[^\s]{4,}",
            lowered,
        ):
            raise ValueError("credential-material-forbidden-in-limits")
        return value
    raise ValueError("unsupported-limit-value")


def _safe_limits(limits: dict[str, Any] | None) -> dict[str, Any]:
    if limits is None:
        return {}
    if not isinstance(limits, dict):
        raise ValueError("limits-must-be-object")
    safe = _validate_limit_value(limits)
    encoded = json.dumps(
        safe, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    if len(encoded.encode("utf-8")) > MAX_LIMITS_BYTES:
        raise ValueError("limits-too-large")
    return safe


async def _validate_override_subject(
    session: AsyncSession, scope: str, subject_id: str
) -> None:
    if scope == "user":
        exists = await session.scalar(select(User.id).where(User.id == subject_id))
    else:
        exists = await session.scalar(
            select(Organization.id).where(Organization.id == subject_id)
        )
    if not exists:
        raise ValueError("subject-not-found")


def _resource_id(scope: str, subject_id: str, capability: str) -> str:
    return f"{scope}:{subject_id}:{capability}"


async def _override(
    session: AsyncSession, scope: str, subject_id: str, capability: str
) -> OwnerControlRecord | None:
    return await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == OVERRIDE_DOMAIN,
            OwnerControlRecord.resource_id
            == _resource_id(scope, subject_id, capability),
        )
    )


async def effective_access(
    session: AsyncSession,
    actor: UserRecord,
    capability: str,
) -> GrowthAccessDecision:
    definition = CAPABILITIES.get(capability)
    if definition is None:
        return GrowthAccessDecision(
            capability, False, "catalog", "unknown-capability", False, {}
        )

    if actor.status not in {"active", "online"}:
        return GrowthAccessDecision(
            capability, False, "account", "user-inactive", False, {}
        )

    context = await billing.billing_context(session, actor.organization_id)
    account = context["account"]
    if account.status not in billing.ACTIVE_ACCOUNT_STATUSES:
        return GrowthAccessDecision(
            capability, False, "billing", "account-suspended", False, {}
        )

    user_override = await _override(session, "user", actor.id, capability)
    org_override = await _override(
        session, "organization", actor.organization_id, capability
    )
    chosen = user_override or org_override
    if chosen is not None:
        payload = dict(chosen.payload or {})
        allowed = bool(chosen.enabled and payload.get("allowed", True))
        try:
            safe_limits = _safe_limits(payload.get("limits") or {})
        except ValueError:
            if allowed:
                return GrowthAccessDecision(
                    capability,
                    False,
                    "owner-override",
                    "owner-override-invalid-limits",
                    True,
                    {},
                )
            safe_limits = {}
        return GrowthAccessDecision(
            capability,
            allowed,
            "owner-override",
            "owner-grant" if allowed else "owner-deny",
            bool(
                payload.get(
                    "approval_required", definition.get("approval_default", False)
                )
            ),
            safe_limits,
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
    _require_super_owner(owner)
    if scope not in {"user", "organization"}:
        raise ValueError("unsupported-scope")
    if capability not in CAPABILITIES:
        raise ValueError("unknown-capability")
    subject_id = _safe_subject_id(subject_id)
    await _validate_override_subject(session, scope, subject_id)
    safe_limits = _safe_limits(limits)
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
        "limits": safe_limits,
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
                "limits": safe_limits,
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
        safe_limits,
    )


async def clear_owner_override(
    session: AsyncSession,
    owner: UserRecord,
    *,
    scope: str,
    subject_id: str,
    capability: str,
) -> bool:
    _require_super_owner(owner)
    if scope not in {"user", "organization"}:
        raise ValueError("unsupported-scope")
    if capability not in CAPABILITIES:
        raise ValueError("unknown-capability")
    subject_id = _safe_subject_id(subject_id)
    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == OVERRIDE_DOMAIN,
            OwnerControlRecord.resource_id
            == _resource_id(scope, subject_id, capability),
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
            details={
                "scope": scope,
                "subject_id": subject_id,
                "capability": capability,
            },
        )
    )
    await session.flush()
    return True


async def list_owner_overrides(
    session: AsyncSession, owner: UserRecord, *, limit: int = 500
) -> dict[str, Any]:
    _require_super_owner(owner)
    rows = list(
        await session.scalars(
            select(OwnerControlRecord)
            .where(OwnerControlRecord.domain == OVERRIDE_DOMAIN)
            .order_by(OwnerControlRecord.updated_at.desc())
            .limit(max(1, min(500, int(limit))))
        )
    )

    parsed: list[dict[str, Any]] = []
    invalid_records = 0
    user_ids: set[str] = set()
    organization_ids: set[str] = set()
    for row in rows:
        payload = dict(row.payload or {})
        scope = str(payload.get("scope") or "").strip()
        subject_id = str(payload.get("subject_id") or "").strip()
        capability = str(payload.get("capability") or "").strip()
        try:
            subject_id = _safe_subject_id(subject_id)
        except ValueError:
            invalid_records += 1
            continue
        if (
            scope not in {"user", "organization"}
            or capability not in CAPABILITIES
            or row.resource_id != _resource_id(scope, subject_id, capability)
        ):
            invalid_records += 1
            continue

        limits_redacted = False
        try:
            safe_limits = _safe_limits(payload.get("limits") or {})
        except ValueError:
            safe_limits = {}
            limits_redacted = True

        if scope == "user":
            user_ids.add(subject_id)
        else:
            organization_ids.add(subject_id)
        parsed.append(
            {
                "record_id": row.id,
                "scope": scope,
                "subject_id": subject_id,
                "capability": capability,
                "allowed": bool(row.enabled and payload.get("allowed", True)),
                "approval_required": bool(payload.get("approval_required", False)),
                "limits": safe_limits,
                "limits_redacted": limits_redacted,
                "record_enabled": bool(row.enabled),
                "version": int(row.version or 1),
                "updated_at": row.updated_at,
            }
        )

    users: dict[str, dict[str, Any]] = {}
    if user_ids:
        user_rows = (
            await session.execute(
                select(
                    User.id, User.name, User.email, User.status, User.deleted_at
                ).where(User.id.in_(user_ids))
            )
        ).all()
        users = {
            row.id: {
                "name": row.name,
                "detail": row.email,
                "status": "deleted" if row.deleted_at is not None else row.status,
            }
            for row in user_rows
        }

    organizations: dict[str, dict[str, Any]] = {}
    if organization_ids:
        organization_rows = (
            await session.execute(
                select(Organization.id, Organization.name, Organization.status).where(
                    Organization.id.in_(organization_ids)
                )
            )
        ).all()
        organizations = {
            row.id: {"name": row.name, "detail": None, "status": row.status}
            for row in organization_rows
        }

    items: list[dict[str, Any]] = []
    for item in parsed:
        subject = (
            users.get(item["subject_id"])
            if item["scope"] == "user"
            else organizations.get(item["subject_id"])
        )
        items.append(
            {
                **item,
                "subject_name": subject.get("name") if subject else None,
                "subject_detail": subject.get("detail") if subject else None,
                "subject_status": subject.get("status") if subject else "missing",
            }
        )

    return {
        "items": items,
        "invalid_records": invalid_records,
        "provider_write_executed": False,
        "provider_spend_executed": False,
        "raw_credentials_returned": False,
    }


async def snapshot(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    decisions = [
        await effective_access(session, actor, capability)
        for capability in CAPABILITIES
    ]
    return {
        "module": MODULE,
        "user_id": actor.id,
        "organization_id": actor.organization_id,
        "capabilities": [decision.as_dict() for decision in decisions],
    }
