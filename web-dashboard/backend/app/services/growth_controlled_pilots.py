"""GS-12 controlled live-pilot safety gate and read-only validation runtime."""

from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthControlledPilot,
    GrowthSocialProviderCapability,
    Organization,
)
from app.services import (
    growth_meta_connector,
    growth_meta_owned_connector,
    growth_telegram_connector,
)

PILOT_MODES = {"read_only", "live_spend"}
SUPPORTED_PROVIDERS = {"meta", "telegram"}
SUPPORTED_SCOPES = {
    ("meta", "read_only"): {"owned_assets", "sandbox"},
    ("telegram", "read_only"): {"owner_bots"},
    ("meta", "live_spend"): {"managed_ad_account"},
}
READ_ONLY_CAPABILITIES = {"meta": "ads_read", "telegram": "account.read"}
READ_ONLY_STATES = {
    "meta": {"read_only_verified", "sandbox_verified"},
    "telegram": {"read_only_verified"},
}
LIVE_SPEND_CAPABILITY = "ads.manage"
LIVE_WRITE_VERIFICATION_STATE = "live_write_verified"
DEFAULT_EXPIRY_HOURS = 24
MAX_EXPIRY_DAYS = 7
MAX_MONEY_MINOR = 9_000_000_000_000_000_000
MAX_ROAS = 1_000_000.0


class GrowthControlledPilotError(RuntimeError):
    """Fail-closed GS-12 validation or authorization error."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_owner(actor: UserRecord) -> None:
    if actor.role != "Super Owner":
        raise GrowthControlledPilotError("super-owner-required")


def _safe_reference(
    value: str | None, *, max_length: int, required: bool = False
) -> str | None:
    clean = str(value or "").strip()
    if required and not clean:
        raise GrowthControlledPilotError("reference-required")
    if not clean:
        return None
    if len(clean) > max_length:
        raise GrowthControlledPilotError("reference-too-long")
    lowered = clean.lower()
    if any(
        marker in lowered
        for marker in ("token=", "secret=", "password=", "bearer ", "api_key=")
    ):
        raise GrowthControlledPilotError("raw-credential-material-forbidden")
    return clean


def _normalize_expiry(value: datetime | None) -> datetime:
    now = _now()
    if value is None:
        return now + timedelta(hours=DEFAULT_EXPIRY_HOURS)
    expiry = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if expiry <= now:
        raise GrowthControlledPilotError("pilot-expiry-must-be-future")
    if expiry > now + timedelta(days=MAX_EXPIRY_DAYS):
        raise GrowthControlledPilotError("pilot-expiry-exceeds-7-days")
    return expiry


def _safe_currency(value: str | None) -> str | None:
    if value is None:
        return None
    currency = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise GrowthControlledPilotError("invalid-currency")
    return currency


def _positive_or_none(value: int | None, name: str) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    if parsed <= 0:
        raise GrowthControlledPilotError(f"{name}-must-be-positive")
    if parsed > MAX_MONEY_MINOR:
        raise GrowthControlledPilotError(f"{name}-too-large")
    return parsed


def _positive_float_or_none(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise GrowthControlledPilotError(f"{name}-must-be-positive-and-finite")
    if parsed > MAX_ROAS:
        raise GrowthControlledPilotError(f"{name}-too-large")
    return parsed


def _public_pilot(row: GrowthControlledPilot) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "provider": row.provider,
        "provider_scope": row.provider_scope,
        "scope_ref": row.scope_ref,
        "mode": row.mode,
        "capability": row.capability,
        "status": row.status,
        "owner_approved": row.owner_approved_at is not None,
        "owner_approved_at": row.owner_approved_at,
        "owner_approval_reference": row.owner_approval_reference,
        "legal_policy_acknowledged": bool(row.legal_policy_acknowledged),
        "legal_policy_reference": row.legal_policy_reference,
        "currency": row.currency,
        "max_total_budget_minor": row.max_total_budget_minor,
        "max_daily_budget_minor": row.max_daily_budget_minor,
        "max_cpa_minor": row.max_cpa_minor,
        "min_roas": row.min_roas,
        "launch_authorized": bool(row.launch_authorized),
        "expires_at": row.expires_at,
        "armed_at": row.armed_at,
        "disarmed_at": row.disarmed_at,
        "live_provider_mutation_allowed": bool(row.live_provider_mutation_allowed),
        "real_spend_allowed": bool(row.real_spend_allowed),
        "automatic_execution_allowed": False,
        "blocked_reasons": list(row.blocked_reasons or []),
        "evidence": dict(row.evidence or {}),
        "version": row.version,
    }


def public_pilot(row: GrowthControlledPilot) -> dict[str, Any]:
    return _public_pilot(row)


async def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    pilot: GrowthControlledPilot,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type="growth_controlled_pilot",
            resource_id=pilot.id,
            details={
                "pilot_mode": pilot.mode,
                "provider": pilot.provider,
                "capability": pilot.capability,
                "live_provider_mutation_allowed": bool(
                    pilot.live_provider_mutation_allowed
                ),
                "real_spend_allowed": bool(pilot.real_spend_allowed),
                **dict(details or {}),
            },
        )
    )


async def _pilot(
    session: AsyncSession, actor: UserRecord, pilot_id: str, *, lock: bool = False
) -> GrowthControlledPilot:
    _require_owner(actor)
    stmt = select(GrowthControlledPilot).where(GrowthControlledPilot.id == pilot_id)
    if lock:
        stmt = stmt.with_for_update()
    row = await session.scalar(stmt)
    if row is None:
        raise GrowthControlledPilotError("pilot-not-found")
    return row


async def create_pilot(
    session: AsyncSession,
    actor: UserRecord,
    payload: dict[str, Any],
) -> GrowthControlledPilot:
    _require_owner(actor)
    provider = str(payload.get("provider") or "").strip().lower()
    mode = str(payload.get("mode") or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise GrowthControlledPilotError("unsupported-provider")
    if mode not in PILOT_MODES:
        raise GrowthControlledPilotError("unsupported-pilot-mode")
    if mode == "live_spend" and provider != "meta":
        raise GrowthControlledPilotError("live-spend-provider-not-supported")

    organization_id = payload.get("organization_id")
    if mode == "live_spend" and not organization_id:
        raise GrowthControlledPilotError("live-spend-organization-required")
    if organization_id:
        organization = await session.scalar(
            select(Organization).where(
                Organization.id == str(organization_id),
                Organization.status == "active",
            )
        )
        if organization is None:
            raise GrowthControlledPilotError("organization-not-found-or-inactive")
        organization_id = organization.id

    provider_scope = _safe_reference(
        payload.get("provider_scope"), max_length=80, required=True
    )
    if provider_scope not in SUPPORTED_SCOPES.get((provider, mode), set()):
        raise GrowthControlledPilotError("unsupported-provider-scope")
    scope_ref = _safe_reference(payload.get("scope_ref"), max_length=255)
    if mode == "live_spend" and not scope_ref:
        raise GrowthControlledPilotError("live-spend-scope-reference-required")
    approval_reference = _safe_reference(
        payload.get("owner_approval_reference"), max_length=240, required=True
    )
    capability = (
        READ_ONLY_CAPABILITIES[provider]
        if mode == "read_only"
        else LIVE_SPEND_CAPABILITY
    )
    now = _now()
    row = GrowthControlledPilot(
        organization_id=organization_id,
        created_by_id=actor.id,
        provider=provider,
        provider_scope=provider_scope or "",
        scope_ref=scope_ref,
        mode=mode,
        capability=capability,
        status="owner_approved",
        owner_approved_by_id=actor.id,
        owner_approved_at=now,
        owner_approval_reference=approval_reference,
        legal_policy_acknowledged=False,
        launch_authorized=False,
        expires_at=_normalize_expiry(payload.get("expires_at")),
        live_provider_mutation_allowed=False,
        real_spend_allowed=False,
        evidence={
            "gs12_phase_approved": True,
            "approval_source": "explicit-super-owner-operation",
            "provider_write_invoked": False,
            "provider_spend_invoked": False,
        },
        blocked_reasons=[],
        version=1,
    )
    session.add(row)
    await session.flush()
    await _audit(
        session,
        actor,
        "growth.pilot.created",
        row,
        {
            "organization_id": row.organization_id,
            "provider_scope": row.provider_scope,
            "owner_approval_reference": row.owner_approval_reference,
        },
    )
    await session.flush()
    return row


async def list_pilots(
    session: AsyncSession, actor: UserRecord, *, limit: int = 100
) -> list[GrowthControlledPilot]:
    _require_owner(actor)
    rows = await session.scalars(
        select(GrowthControlledPilot)
        .order_by(GrowthControlledPilot.created_at.desc())
        .limit(max(1, min(500, int(limit))))
    )
    return list(rows)


async def configure_controls(
    session: AsyncSession,
    actor: UserRecord,
    pilot_id: str,
    payload: dict[str, Any],
) -> GrowthControlledPilot:
    row = await _pilot(session, actor, pilot_id, lock=True)
    if row.status in {"revoked", "completed"}:
        raise GrowthControlledPilotError("pilot-is-terminal")

    if "legal_policy_acknowledged" in payload:
        acknowledged = bool(payload.get("legal_policy_acknowledged"))
        row.legal_policy_acknowledged = acknowledged
        if acknowledged:
            row.legal_policy_reference = _safe_reference(
                payload.get("legal_policy_reference"), max_length=500, required=True
            )
            row.legal_acknowledged_by_id = actor.id
            row.legal_acknowledged_at = _now()
        else:
            row.legal_policy_reference = None
            row.legal_acknowledged_by_id = None
            row.legal_acknowledged_at = None

    if "currency" in payload:
        row.currency = _safe_currency(payload.get("currency"))
    if "max_total_budget_minor" in payload:
        row.max_total_budget_minor = _positive_or_none(
            payload.get("max_total_budget_minor"), "max-total-budget"
        )
    if "max_daily_budget_minor" in payload:
        row.max_daily_budget_minor = _positive_or_none(
            payload.get("max_daily_budget_minor"), "max-daily-budget"
        )
    if "max_cpa_minor" in payload:
        row.max_cpa_minor = _positive_or_none(payload.get("max_cpa_minor"), "max-cpa")
    if "min_roas" in payload:
        row.min_roas = _positive_float_or_none(payload.get("min_roas"), "min-roas")
    if "expires_at" in payload:
        row.expires_at = _normalize_expiry(payload.get("expires_at"))

    if (
        row.max_total_budget_minor is not None
        and row.max_daily_budget_minor is not None
        and row.max_daily_budget_minor > row.max_total_budget_minor
    ):
        raise GrowthControlledPilotError("daily-budget-exceeds-total-budget")
    if (
        row.max_total_budget_minor is not None
        and row.max_cpa_minor is not None
        and row.max_cpa_minor > row.max_total_budget_minor
    ):
        raise GrowthControlledPilotError("max-cpa-exceeds-total-budget")

    # Any control change invalidates a prior launch authorization/arm.
    row.launch_authorized = False
    row.launch_authorized_by_id = None
    row.launch_authorized_at = None
    row.armed_at = None
    row.live_provider_mutation_allowed = False
    row.real_spend_allowed = False
    row.status = "controls_configured"
    row.version += 1
    await _audit(
        session,
        actor,
        "growth.pilot.controls_configured",
        row,
        {
            "legal_policy_acknowledged": bool(row.legal_policy_acknowledged),
            "budget_configured": bool(
                row.max_total_budget_minor and row.max_daily_budget_minor
            ),
            "stop_loss_configured": bool(row.max_cpa_minor and row.min_roas),
            "launch_authorization_reset": True,
        },
    )
    await session.flush()
    return row


async def _provider_capability(
    session: AsyncSession, row: GrowthControlledPilot
) -> GrowthSocialProviderCapability | None:
    return await session.scalar(
        select(GrowthSocialProviderCapability).where(
            GrowthSocialProviderCapability.provider == row.provider,
            GrowthSocialProviderCapability.capability == row.capability,
        )
    )


async def readiness(
    session: AsyncSession,
    actor: UserRecord,
    pilot_id: str,
    *,
    require_launch_authorization: bool = True,
) -> dict[str, Any]:
    row = await _pilot(session, actor, pilot_id)
    reasons: list[str] = []
    now = _now()

    owner_gate = bool(row.owner_approved_at and row.owner_approved_by_id)
    if not owner_gate:
        reasons.append("owner-approval-missing")

    expiry_gate = True
    if row.expires_at is None:
        expiry_gate = False
        reasons.append("pilot-expiry-missing")
    else:
        expiry = (
            row.expires_at
            if row.expires_at.tzinfo
            else row.expires_at.replace(tzinfo=timezone.utc)
        )
        if expiry <= now:
            expiry_gate = False
            reasons.append("pilot-expired")

    organization_gate = True
    if row.organization_id:
        organization_gate = bool(
            await session.scalar(
                select(Organization.id).where(
                    Organization.id == row.organization_id,
                    Organization.status == "active",
                )
            )
        )
        if not organization_gate:
            reasons.append("organization-inactive-or-missing")
    elif row.mode == "live_spend":
        organization_gate = False
        reasons.append("live-spend-organization-required")

    provider_scope_gate = row.provider_scope in SUPPORTED_SCOPES.get(
        (row.provider, row.mode), set()
    )
    if not provider_scope_gate:
        reasons.append("provider-scope-unsupported")
    if row.mode == "live_spend" and not row.scope_ref:
        provider_scope_gate = False
        reasons.append("live-spend-scope-reference-required")

    provider_row = await _provider_capability(session, row)
    provider_gate = False
    execution_adapter_gate = row.mode == "read_only"
    provider_state = provider_row.verification_state if provider_row else "missing"
    provider_evidence = dict(provider_row.evidence or {}) if provider_row else {}

    if row.mode == "read_only":
        scope_evidence_gate = False
        if row.provider == "meta" and row.provider_scope == "owned_assets":
            scope_evidence_gate = bool(
                provider_row
                and (
                    provider_row.verification_state == "read_only_verified"
                    or provider_evidence.get("gs09_meta_owned_read_only")
                )
            )
        elif row.provider == "meta" and row.provider_scope == "sandbox":
            scope_evidence_gate = bool(
                provider_row
                and (
                    provider_row.verification_state == "sandbox_verified"
                    or provider_evidence.get("gs09_meta_sandbox")
                )
            )
        elif row.provider == "telegram" and row.provider_scope == "owner_bots":
            scope_evidence_gate = bool(
                provider_row and provider_row.verification_state == "read_only_verified"
            )
        provider_gate = bool(
            provider_scope_gate
            and scope_evidence_gate
            and provider_row
            and provider_row.mutation_class == "read"
            and provider_row.verification_state in READ_ONLY_STATES[row.provider]
        )
        if not provider_gate:
            reasons.append("provider-read-only-capability-unverified")
    else:
        provider_gate = bool(
            provider_row
            and provider_row.mutation_class == "write"
            and provider_row.verification_state == LIVE_WRITE_VERIFICATION_STATE
            and provider_evidence.get("mutation_allowed") is True
            and provider_evidence.get("spend_allowed") is True
        )
        if not provider_gate:
            reasons.append("provider-write-capability-unverified")
        execution_adapter_gate = bool(
            provider_evidence.get("execution_adapter_verified") is True
        )
        if not execution_adapter_gate:
            reasons.append("provider-live-execution-adapter-unverified")

    legal_gate = row.mode == "read_only" or bool(
        row.legal_policy_acknowledged
        and row.legal_policy_reference
        and row.legal_acknowledged_at
        and row.legal_acknowledged_by_id
    )
    if not legal_gate:
        reasons.append("legal-policy-acknowledgement-missing")

    budget_gate = row.mode == "read_only" or bool(
        row.currency
        and row.max_total_budget_minor
        and row.max_daily_budget_minor
        and row.max_daily_budget_minor <= row.max_total_budget_minor
    )
    if not budget_gate:
        reasons.append("budget-controls-missing")

    stop_loss_gate = row.mode == "read_only" or bool(
        row.max_cpa_minor
        and row.min_roas
        and row.max_cpa_minor > 0
        and row.min_roas > 0
    )
    if not stop_loss_gate:
        reasons.append("stop-loss-controls-missing")

    launch_gate = row.mode == "read_only" or bool(row.launch_authorized)
    if row.mode == "live_spend" and require_launch_authorization and not launch_gate:
        reasons.append("launch-authorization-missing")

    effective_reasons = list(dict.fromkeys(reasons))
    ready = not effective_reasons
    return {
        "pilot_id": row.id,
        "mode": row.mode,
        "provider": row.provider,
        "capability": row.capability,
        "provider_verification_state": provider_state,
        "owner_gate": owner_gate,
        "organization_gate": organization_gate,
        "provider_scope_gate": provider_scope_gate,
        "provider_gate": provider_gate,
        "execution_adapter_gate": execution_adapter_gate,
        "legal_gate": legal_gate,
        "budget_gate": budget_gate,
        "stop_loss_gate": stop_loss_gate,
        "expiry_gate": expiry_gate,
        "launch_gate": launch_gate,
        "ready_to_arm": ready,
        "blocked_reasons": effective_reasons,
        "live_provider_mutation_allowed": bool(row.live_provider_mutation_allowed),
        "real_spend_allowed": bool(row.real_spend_allowed),
        "automatic_execution_allowed": False,
    }


async def authorize_launch(
    session: AsyncSession, actor: UserRecord, pilot_id: str
) -> GrowthControlledPilot:
    row = await _pilot(session, actor, pilot_id, lock=True)
    if row.mode != "live_spend":
        raise GrowthControlledPilotError("launch-authorization-only-for-live-spend")
    check = await readiness(
        session,
        actor,
        pilot_id,
        require_launch_authorization=False,
    )
    if check["blocked_reasons"]:
        raise GrowthControlledPilotError(
            "pilot-not-ready:" + ",".join(check["blocked_reasons"])
        )
    row.launch_authorized = True
    row.launch_authorized_by_id = actor.id
    row.launch_authorized_at = _now()
    row.status = "launch_authorized"
    row.live_provider_mutation_allowed = False
    row.real_spend_allowed = False
    row.version += 1
    await _audit(
        session,
        actor,
        "growth.pilot.launch_authorized",
        row,
        {"authorization_does_not_execute_provider_call": True},
    )
    await session.flush()
    return row


async def arm_pilot(
    session: AsyncSession, actor: UserRecord, pilot_id: str
) -> GrowthControlledPilot:
    row = await _pilot(session, actor, pilot_id, lock=True)
    check = await readiness(session, actor, pilot_id, require_launch_authorization=True)
    if check["blocked_reasons"]:
        row.blocked_reasons = list(check["blocked_reasons"])
        row.live_provider_mutation_allowed = False
        row.real_spend_allowed = False
        await session.flush()
        raise GrowthControlledPilotError(
            "pilot-not-ready:" + ",".join(check["blocked_reasons"])
        )

    row.blocked_reasons = []
    row.armed_at = _now()
    row.disarmed_at = None
    if row.mode == "read_only":
        row.status = "read_only_armed"
        row.live_provider_mutation_allowed = False
        row.real_spend_allowed = False
    else:
        row.status = "armed"
        row.live_provider_mutation_allowed = True
        row.real_spend_allowed = True
    row.version += 1
    await _audit(
        session,
        actor,
        "growth.pilot.armed",
        row,
        {"provider_call_executed": False},
    )
    await session.flush()
    return row


async def disarm_pilot(
    session: AsyncSession,
    actor: UserRecord,
    pilot_id: str,
    *,
    reason: str = "owner-disarm",
) -> GrowthControlledPilot:
    row = await _pilot(session, actor, pilot_id, lock=True)
    clean_reason = (
        _safe_reference(reason, max_length=240, required=True) or "owner-disarm"
    )
    row.status = "disarmed"
    row.disarmed_at = _now()
    row.armed_at = None
    row.launch_authorized = False
    row.launch_authorized_by_id = None
    row.launch_authorized_at = None
    row.live_provider_mutation_allowed = False
    row.real_spend_allowed = False
    row.blocked_reasons = [clean_reason]
    row.version += 1
    await _audit(
        session,
        actor,
        "growth.pilot.disarmed",
        row,
        {"reason": clean_reason},
    )
    await session.flush()
    return row


def _safe_validation_evidence(
    provider: str, provider_scope: str, raw: dict[str, Any]
) -> dict[str, Any]:
    common: dict[str, Any] = {
        "provider_call_allowed": bool(raw.get("provider_call_allowed", True)),
        "mutation_allowed": False,
        "spend_allowed": False,
        "send_allowed": False,
        "raw_secret_persisted": False,
    }
    if provider == "meta" and provider_scope == "owned_assets":
        common.update(
            {
                "scope": "owned_assets",
                "verification_state": "read_only_verified",
                "ad_accounts_count": int(raw.get("ad_accounts_count", 0)),
                "active_ad_accounts_count": int(raw.get("active_ad_accounts_count", 0)),
                "result_page_truncated": bool(raw.get("result_page_truncated", False)),
            }
        )
    elif provider == "meta" and provider_scope == "sandbox":
        common.update(
            {
                "scope": "sandbox",
                "verification_state": "sandbox_verified",
                "currency": str(raw.get("currency") or "")[:3],
                "timezone": str(raw.get("timezone") or "")[:80],
                "account_status": str(raw.get("account_status") or "")[:40],
            }
        )
    elif provider == "telegram" and provider_scope == "owner_bots":
        common.update(
            {
                "scope": "owner_bots",
                "verification_state": "read_only_verified",
                "bot_credentials_count": int(raw.get("bot_credentials_count", 0)),
                "verified_bot_count": int(raw.get("verified_bot_count", 0)),
            }
        )
    else:
        raise GrowthControlledPilotError("unsupported-read-only-provider-scope")
    return common


async def validate_read_only_live(
    session: AsyncSession, actor: UserRecord, pilot_id: str
) -> GrowthControlledPilot:
    row = await _pilot(session, actor, pilot_id, lock=True)
    if row.mode != "read_only":
        raise GrowthControlledPilotError(
            "read-only-validation-requires-read-only-pilot"
        )
    check = await readiness(
        session, actor, pilot_id, require_launch_authorization=False
    )
    if check["blocked_reasons"]:
        raise GrowthControlledPilotError(
            "pilot-not-ready:" + ",".join(check["blocked_reasons"])
        )

    if row.provider == "meta" and row.provider_scope == "owned_assets":
        raw = await asyncio.to_thread(
            growth_meta_owned_connector.probe_meta_owned_assets_read_only
        )
    elif row.provider == "meta" and row.provider_scope == "sandbox":
        raw = await asyncio.to_thread(
            growth_meta_connector.probe_meta_sandbox_read_only
        )
    elif row.provider == "telegram" and row.provider_scope == "owner_bots":
        raw = await asyncio.to_thread(
            growth_telegram_connector.probe_telegram_bots_read_only
        )
    else:
        raise GrowthControlledPilotError("unsupported-read-only-provider-scope")

    safe = _safe_validation_evidence(row.provider, row.provider_scope, dict(raw))
    evidence = dict(row.evidence or {})
    evidence["read_only_live_validation"] = safe
    evidence["read_only_live_validated_at"] = _now().isoformat()
    evidence["provider_write_invoked"] = False
    evidence["provider_spend_invoked"] = False
    row.evidence = evidence
    row.status = "read_only_validated"
    row.live_provider_mutation_allowed = False
    row.real_spend_allowed = False
    row.blocked_reasons = []
    row.version += 1
    await _audit(
        session,
        actor,
        "growth.pilot.read_only_live_validated",
        row,
        safe,
    )
    await session.flush()
    return row
