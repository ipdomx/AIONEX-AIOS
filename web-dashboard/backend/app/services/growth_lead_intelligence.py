"""GS-06 compliant lead intelligence and audience eligibility."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthLeadConsent,
    GrowthLeadProvenance,
    GrowthLeadRecord,
    GrowthLeadSuppression,
)
from app.services import growth_access

UNAUTHORIZED_SCRAPING_ALLOWED = False
OUTBOUND_OUTREACH_ALLOWED = False
LIVE_AUDIENCE_UPLOAD_ALLOWED = False
LIVE_PROVIDER_CALL_ALLOWED = False

SOURCE_TYPES = {
    "first_party_form",
    "crm_import",
    "provider_lead_form",
    "customer_upload",
    "public_business_contact",
    "manual_entry",
}
COLLECTION_METHODS = {
    "consented_form",
    "owner_authorized_import",
    "provider_authorized_event",
    "manual_verified_entry",
    "lawful_public_business_source",
}
LAWFUL_BASES = {"consent", "contract", "legal_obligation", "legitimate_interest"}
PURPOSES = {"marketing", "sales", "support", "customer_service"}
CHANNELS = {"email", "sms", "phone", "social", "all"}


class GrowthLeadError(RuntimeError):
    """Fail-closed GS-06 error."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    if "@" not in text or len(text) > 320:
        raise GrowthLeadError("invalid-email")
    return text


def _normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    raw = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if raw.startswith("+"):
        digits = "+" + "".join(ch for ch in raw[1:] if ch.isdigit())
    else:
        digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    if len(digits.replace("+", "")) < 7 or len(digits.replace("+", "")) > 18:
        raise GrowthLeadError("invalid-phone")
    return digits


def dedupe_fingerprint(
    email: str | None, phone: str | None, company_name: str | None
) -> str:
    if not email and not phone:
        raise GrowthLeadError("email-or-phone-required")
    canonical = "|".join(
        [
            email or "",
            phone or "",
            (company_name or "").strip().lower(),
        ]
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type="growth_lead",
            resource_id=resource_id,
            details={
                "unauthorized_scraping_allowed": False,
                "outbound_outreach_allowed": False,
                "live_audience_upload_allowed": False,
                "live_provider_call": False,
                **dict(details or {}),
            },
        )
    )


async def _require(session: AsyncSession, actor: UserRecord) -> None:
    decision = await growth_access.effective_access(session, actor, "leads.manage")
    if not decision.allowed:
        raise GrowthLeadError(f"access-denied:{decision.reason}")


def _validate_source(source_type: str, collection_method: str) -> None:
    if source_type not in SOURCE_TYPES:
        raise GrowthLeadError("unsupported-source-type")
    if collection_method not in COLLECTION_METHODS:
        raise GrowthLeadError("unsupported-collection-method")
    if (
        source_type == "public_business_contact"
        and collection_method != "lawful_public_business_source"
    ):
        raise GrowthLeadError("public-business-source-requires-lawful-method")


async def upsert_lead(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> tuple[GrowthLeadRecord, bool]:
    await _require(session, actor)
    source_type = str(payload.get("source_type") or "").strip().lower()
    collection_method = str(payload.get("collection_method") or "").strip().lower()
    _validate_source(source_type, collection_method)
    email = _normalize_email(payload.get("email"))
    phone = _normalize_phone(payload.get("phone"))
    company_name = str(payload.get("company_name") or "").strip() or None
    fingerprint = dedupe_fingerprint(email, phone, company_name)
    row = await session.scalar(
        select(GrowthLeadRecord).where(
            GrowthLeadRecord.organization_id == actor.organization_id,
            GrowthLeadRecord.dedupe_fingerprint == fingerprint,
        )
    )
    created = row is None
    if row is None:
        retention_until = payload.get("retention_until")
        if retention_until is not None and not isinstance(retention_until, datetime):
            raise GrowthLeadError("invalid-retention-until")
        row = GrowthLeadRecord(
            organization_id=actor.organization_id,
            created_by_id=actor.id,
            display_name=(str(payload.get("display_name") or "").strip() or None),
            email_normalized=email,
            phone_normalized=phone,
            company_name=company_name,
            country_code=(
                str(payload.get("country_code") or "").strip().upper()[:2] or None
            ),
            dedupe_fingerprint=fingerprint,
            status="active",
            retention_until=retention_until,
            attributes=dict(payload.get("attributes") or {}),
        )
        session.add(row)
        await session.flush()
    provenance = GrowthLeadProvenance(
        organization_id=actor.organization_id,
        lead_id=row.id,
        source_type=source_type,
        source_ref=(str(payload.get("source_ref") or "").strip() or None),
        collection_method=collection_method,
        source_metadata=dict(payload.get("source_metadata") or {}),
    )
    session.add(provenance)
    _audit(
        session,
        actor,
        "growth.lead.created" if created else "growth.lead.deduped_source_added",
        row.id,
        {"source_type": source_type, "collection_method": collection_method},
    )
    await session.flush()
    return row, created


async def set_consent(
    session: AsyncSession, actor: UserRecord, lead_id: str, payload: dict[str, Any]
) -> GrowthLeadConsent:
    await _require(session, actor)
    lead = await session.scalar(
        select(GrowthLeadRecord).where(
            GrowthLeadRecord.id == lead_id,
            GrowthLeadRecord.organization_id == actor.organization_id,
        )
    )
    if lead is None:
        raise GrowthLeadError("lead-not-found")
    purpose = str(payload.get("purpose") or "").strip().lower()
    lawful_basis = str(payload.get("lawful_basis") or "").strip().lower()
    if purpose not in PURPOSES:
        raise GrowthLeadError("unsupported-purpose")
    if lawful_basis not in LAWFUL_BASES:
        raise GrowthLeadError("unsupported-lawful-basis")
    evidence = dict(payload.get("evidence") or {})
    if lawful_basis == "consent" and not evidence:
        raise GrowthLeadError("consent-evidence-required")
    row = await session.scalar(
        select(GrowthLeadConsent).where(
            GrowthLeadConsent.lead_id == lead.id,
            GrowthLeadConsent.purpose == purpose,
            GrowthLeadConsent.lawful_basis == lawful_basis,
        )
    )
    if row is None:
        row = GrowthLeadConsent(
            organization_id=actor.organization_id,
            lead_id=lead.id,
            purpose=purpose,
            lawful_basis=lawful_basis,
            status="active",
            captured_at=(
                payload.get("captured_at")
                if isinstance(payload.get("captured_at"), datetime)
                else _now()
            ),
            expires_at=(
                payload.get("expires_at")
                if isinstance(payload.get("expires_at"), datetime)
                else None
            ),
            evidence=evidence,
        )
        session.add(row)
    else:
        row.status = "active"
        row.withdrawn_at = None
        row.expires_at = (
            payload.get("expires_at")
            if isinstance(payload.get("expires_at"), datetime)
            else row.expires_at
        )
        row.evidence = evidence
    _audit(
        session,
        actor,
        "growth.lead.lawful_basis_set",
        lead.id,
        {"purpose": purpose, "lawful_basis": lawful_basis},
    )
    await session.flush()
    return row


async def suppress(
    session: AsyncSession, actor: UserRecord, lead_id: str, channel: str, reason: str
) -> GrowthLeadSuppression:
    await _require(session, actor)
    channel = channel.strip().lower()
    if channel not in CHANNELS:
        raise GrowthLeadError("unsupported-channel")
    lead = await session.scalar(
        select(GrowthLeadRecord).where(
            GrowthLeadRecord.id == lead_id,
            GrowthLeadRecord.organization_id == actor.organization_id,
        )
    )
    if lead is None:
        raise GrowthLeadError("lead-not-found")
    row = await session.scalar(
        select(GrowthLeadSuppression).where(
            GrowthLeadSuppression.organization_id == actor.organization_id,
            GrowthLeadSuppression.lead_id == lead.id,
            GrowthLeadSuppression.channel == channel,
        )
    )
    if row is None:
        row = GrowthLeadSuppression(
            organization_id=actor.organization_id,
            lead_id=lead.id,
            channel=channel,
            reason=reason.strip()[:120] or "user-opt-out",
            active=True,
            suppressed_at=_now(),
        )
        session.add(row)
    else:
        row.active = True
        row.reason = reason.strip()[:120] or row.reason
        row.suppressed_at = _now()
    _audit(
        session,
        actor,
        "growth.lead.suppressed",
        lead.id,
        {"channel": channel, "reason": row.reason},
    )
    await session.flush()
    return row


async def withdraw_consent(
    session: AsyncSession, actor: UserRecord, consent_id: str
) -> GrowthLeadConsent:
    await _require(session, actor)
    row = await session.scalar(
        select(GrowthLeadConsent).where(
            GrowthLeadConsent.id == consent_id,
            GrowthLeadConsent.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthLeadError("consent-not-found")
    row.status = "withdrawn"
    row.withdrawn_at = _now()
    _audit(
        session,
        actor,
        "growth.lead.consent_withdrawn",
        row.lead_id,
        {"purpose": row.purpose},
    )
    await session.flush()
    return row


async def eligibility(
    session: AsyncSession,
    actor: UserRecord,
    lead_id: str,
    *,
    purpose: str,
    channel: str,
) -> dict[str, Any]:
    await _require(session, actor)
    purpose = purpose.strip().lower()
    channel = channel.strip().lower()
    if purpose not in PURPOSES or channel not in CHANNELS - {"all"}:
        raise GrowthLeadError("unsupported-eligibility-dimension")
    lead = await session.scalar(
        select(GrowthLeadRecord).where(
            GrowthLeadRecord.id == lead_id,
            GrowthLeadRecord.organization_id == actor.organization_id,
        )
    )
    if lead is None:
        raise GrowthLeadError("lead-not-found")
    reasons: list[str] = []
    now = _now()
    if lead.status != "active":
        reasons.append("lead-inactive")
    if lead.retention_until is not None:
        retention = (
            lead.retention_until
            if lead.retention_until.tzinfo
            else lead.retention_until.replace(tzinfo=timezone.utc)
        )
        if retention <= now:
            reasons.append("retention-expired")
    suppressions = (
        await session.scalars(
            select(GrowthLeadSuppression).where(
                GrowthLeadSuppression.organization_id == actor.organization_id,
                GrowthLeadSuppression.lead_id == lead.id,
                GrowthLeadSuppression.active.is_(True),
            )
        )
    ).all()
    if any(item.channel in {channel, "all"} for item in suppressions):
        reasons.append("suppressed")
    consents = (
        await session.scalars(
            select(GrowthLeadConsent).where(
                GrowthLeadConsent.organization_id == actor.organization_id,
                GrowthLeadConsent.lead_id == lead.id,
                GrowthLeadConsent.purpose == purpose,
                GrowthLeadConsent.status == "active",
            )
        )
    ).all()
    active_basis = []
    for item in consents:
        if item.expires_at is not None:
            expiry = (
                item.expires_at
                if item.expires_at.tzinfo
                else item.expires_at.replace(tzinfo=timezone.utc)
            )
            if expiry <= now:
                continue
        active_basis.append(item.lawful_basis)
    if not active_basis:
        reasons.append("no-active-lawful-basis")
    if channel == "email" and not lead.email_normalized:
        reasons.append("email-missing")
    if channel in {"sms", "phone"} and not lead.phone_normalized:
        reasons.append("phone-missing")
    eligible = not reasons
    result = {
        "lead_id": lead.id,
        "purpose": purpose,
        "channel": channel,
        "eligible": eligible,
        "reason_codes": reasons or ["eligible-with-active-lawful-basis"],
        "lawful_bases": sorted(set(active_basis)),
        "unauthorized_scraping_allowed": False,
        "outbound_outreach_allowed": False,
        "live_audience_upload_allowed": False,
        "live_provider_call": False,
    }
    _audit(
        session,
        actor,
        "growth.lead.eligibility_evaluated",
        lead.id,
        {
            "purpose": purpose,
            "channel": channel,
            "eligible": eligible,
            "reason_codes": result["reason_codes"],
        },
    )
    await session.flush()
    return result


def public_lead(row: GrowthLeadRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "display_name": row.display_name,
        "email": row.email_normalized,
        "phone": row.phone_normalized,
        "company_name": row.company_name,
        "country_code": row.country_code,
        "status": row.status,
        "retention_until": row.retention_until,
        "attributes": dict(row.attributes or {}),
        "unauthorized_scraping_allowed": False,
        "outbound_outreach_allowed": False,
        "live_audience_upload_allowed": False,
        "live_provider_call": False,
    }


async def list_leads(
    session: AsyncSession, actor: UserRecord, limit: int = 100
) -> list[dict[str, Any]]:
    await _require(session, actor)
    rows = (
        await session.scalars(
            select(GrowthLeadRecord)
            .where(GrowthLeadRecord.organization_id == actor.organization_id)
            .order_by(GrowthLeadRecord.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).all()
    return [public_lead(row) for row in rows]
