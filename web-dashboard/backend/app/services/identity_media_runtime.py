"""Durable identity-media execution authority.

Provider submissions are exactly-once at the application boundary. Ambiguous
submission state is terminal for automatic execution and requires operator review.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.phase36_identity_media import IdentityMediaDecision
from app.db.models import AuditEvent, IdentityMediaExecution, uuid_str


class IdentityMediaExecutionError(RuntimeError):
    """Durable identity-media execution cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class IdentityMediaClaim:
    execution_id: str
    claim_key: str
    fencing_value: int
    mode: str


def _now() -> datetime:
    return datetime.now(UTC)


def _cost_authorization(approved_max_cost_usd: float) -> tuple[float, str]:
    """Represent a user-authorized provider ceiling without inventing provider pricing.

    Replicate does not expose a per-request dollar estimate through the model contract
    used here.  The approved value is therefore an authorization ceiling, not an
    asserted estimate or actual charge.
    """
    maximum = float(approved_max_cost_usd)
    if maximum <= 0 or maximum > 25.0:
        raise IdentityMediaExecutionError(
            "identity media cost authorization is outside the launch range"
        )
    return maximum, "user_authorized_ceiling_provider_price_unverified"


def public_execution(row: IdentityMediaExecution) -> dict[str, Any]:
    return {
        "execution_id": row.id,
        "project_id": row.project_id,
        "operation": row.operation,
        "identity_basis": row.identity_basis,
        "provider_access": row.provider_access,
        "provider": row.provider,
        "model": row.model,
        "status": row.status,
        "provider_state": row.provider_state,
        "subject_reference": row.subject_reference,
        "named_real_person_reference": row.named_real_person_reference,
        "rights_evidence_present": row.rights_evidence_sha256 is not None,
        "license_reference_present": row.license_reference is not None,
        "synthetic_media_disclosure_accepted": row.synthetic_media_disclosure_accepted,
        "commercial_use_requested": row.commercial_use_requested,
        "commercial_use_authorized": row.commercial_use_authorized,
        "claims_real_identity": row.claims_real_identity,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "estimated_cost_usd": None,
        "max_cost_authorization_usd": row.max_cost_usd,
        "cost_basis": row.cost_basis,
        "actual_cost_usd": row.actual_cost_usd,
        "output_ready": bool(row.output_storage_key and row.output_checksum_sha256),
        "output_media_type": row.output_media_type,
        "output_size_bytes": row.output_size_bytes,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "provider_job_id_returned": False,
        "secondary_provider_job_id_returned": False,
        "raw_credentials_returned": False,
    }


async def create_execution(
    session: AsyncSession,
    *,
    organization_id: str,
    requested_by_id: str,
    project_id: str | None,
    idempotency_key: str,
    decision: IdentityMediaDecision,
    input_storage_keys: dict[str, str],
    input_checksums: dict[str, str],
    request_payload: dict[str, Any],
    model: str,
    approved_max_cost_usd: float,
) -> IdentityMediaExecution:
    key = str(idempotency_key or "").strip()
    if not 8 <= len(key) <= 160:
        raise IdentityMediaExecutionError("identity media idempotency key is invalid")
    existing = await session.scalar(
        select(IdentityMediaExecution).where(
            IdentityMediaExecution.organization_id == organization_id,
            IdentityMediaExecution.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.requested_by_id != requested_by_id:
            raise IdentityMediaExecutionError("identity media idempotency scope conflict")
        return existing
    max_cost, cost_basis = _cost_authorization(approved_max_cost_usd)
    row = IdentityMediaExecution(
        id=uuid_str(),
        organization_id=organization_id,
        project_id=project_id,
        requested_by_id=requested_by_id,
        operation=decision.operation,
        identity_basis=decision.identity_basis,
        provider_access=decision.provider_access,
        provider="replicate",
        model=model,
        status="planned",
        provider_state="not_started",
        idempotency_key=key,
        subject_reference=decision.subject_reference,
        named_real_person_reference=decision.named_real_person_reference,
        rights_evidence_sha256=decision.rights_evidence_sha256,
        license_reference=decision.license_reference,
        synthetic_media_disclosure_accepted=True,
        commercial_use_requested=decision.commercial_use_authorized is not None,
        commercial_use_authorized=bool(decision.commercial_use_authorized),
        claims_real_identity=bool(decision.real_person_identity and decision.named_real_person_reference),
        request_payload=dict(request_payload),
        input_storage_keys=dict(input_storage_keys),
        input_checksums=dict(input_checksums),
        provider_metadata={},
        attempts=0,
        max_attempts=1,
        polls=0,
        max_polls=240,
        estimated_cost_usd=0.0,
        max_cost_usd=max_cost,
        actual_cost_usd=None,
        cost_basis=cost_basis,
        version=1,
    )
    session.add(row)
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=requested_by_id,
            action="identity_media.execution.planned",
            resource_type="identity_media_execution",
            resource_id=row.id,
            details={
                "operation": row.operation,
                "identity_basis": row.identity_basis,
                "provider": row.provider,
                "model": row.model,
                "rights_evidence_present": row.rights_evidence_sha256 is not None,
                "license_reference_present": row.license_reference is not None,
                "estimated_cost_usd": None,
                "max_cost_usd": max_cost,
                "cost_basis": cost_basis,
            },
        )
    )
    await session.flush()
    return row


async def arm_execution(
    session: AsyncSession,
    *,
    organization_id: str,
    execution_id: str,
) -> IdentityMediaExecution:
    row = await session.scalar(
        select(IdentityMediaExecution)
        .where(
            IdentityMediaExecution.id == execution_id,
            IdentityMediaExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise IdentityMediaExecutionError("identity media execution not found")
    if row.status == "queued":
        return row
    if row.status != "planned":
        raise IdentityMediaExecutionError("only a planned identity media execution may be armed")
    row.status = "queued"
    row.provider_state = "not_started"
    row.armed_at = _now()
    row.available_at = _now()
    row.version += 1
    await session.flush()
    return row


async def claim_next(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
) -> IdentityMediaClaim | None:
    now = _now()
    row = await session.scalar(
        select(IdentityMediaExecution)
        .where(
            IdentityMediaExecution.status.in_(("queued", "provider_running")),
            or_(
                IdentityMediaExecution.available_at.is_(None),
                IdentityMediaExecution.available_at <= now,
            ),
            or_(
                IdentityMediaExecution.lease_expires_at.is_(None),
                IdentityMediaExecution.lease_expires_at <= now,
            ),
        )
        .order_by(IdentityMediaExecution.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        return None
    mode = "submit" if row.status == "queued" and not row.provider_job_id else "poll"
    if mode == "submit":
        if row.attempts >= row.max_attempts:
            row.status = "failed"
            row.error_code = "identity_media_attempt_limit"
            row.error_message = "Identity media submission attempt limit reached"
            row.completed_at = now
            row.version += 1
            await session.flush()
            return None
        row.attempts += 1
    claim_value = str(uuid4())
    row.lease_token = claim_value
    row.lease_owner = worker_id
    row.lease_expires_at = now + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
    row.fencing_token += 1
    row.started_at = row.started_at or now
    row.version += 1
    await session.flush()
    return IdentityMediaClaim(row.id, claim_value, row.fencing_token, mode)


async def load_claim(
    session: AsyncSession,
    claim: IdentityMediaClaim,
) -> IdentityMediaExecution | None:
    return await session.scalar(
        select(IdentityMediaExecution).where(
            IdentityMediaExecution.id == claim.execution_id,
            IdentityMediaExecution.lease_token == claim.claim_key,
            IdentityMediaExecution.fencing_token == claim.fencing_value,
        )
    )


async def record_primary_submission(
    session: AsyncSession,
    claim: IdentityMediaClaim,
    *,
    provider_job_id: str,
    provider_state: str,
    provider_metadata: dict[str, Any] | None = None,
    poll_after_seconds: int = 3,
) -> None:
    row = await load_claim(session, claim)
    if row is None:
        raise IdentityMediaExecutionError("identity media lease lost")
    if row.provider_job_id and row.provider_job_id != provider_job_id:
        raise IdentityMediaExecutionError("identity media provider job identity changed")
    row.provider_job_id = provider_job_id
    row.provider_state = provider_state
    row.provider_metadata = dict(provider_metadata or {})
    row.provider_submitted_at = row.provider_submitted_at or _now()
    row.status = "provider_running"
    row.available_at = _now() + timedelta(seconds=max(1, poll_after_seconds))
    row.lease_token = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.version += 1
    await session.flush()


async def record_secondary_submission(
    session: AsyncSession,
    claim: IdentityMediaClaim,
    *,
    provider_job_id: str,
    provider_state: str,
    provider_metadata: dict[str, Any] | None = None,
    poll_after_seconds: int = 3,
) -> None:
    row = await load_claim(session, claim)
    if row is None:
        raise IdentityMediaExecutionError("identity media lease lost")
    if row.secondary_provider_job_id and row.secondary_provider_job_id != provider_job_id:
        raise IdentityMediaExecutionError("identity media secondary provider job identity changed")
    row.secondary_provider_job_id = provider_job_id
    row.provider_state = provider_state
    row.provider_metadata = {**(row.provider_metadata or {}), **dict(provider_metadata or {})}
    row.status = "provider_running"
    row.available_at = _now() + timedelta(seconds=max(1, poll_after_seconds))
    row.lease_token = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.version += 1
    await session.flush()


async def release_for_poll(
    session: AsyncSession,
    claim: IdentityMediaClaim,
    *,
    provider_state: str,
    metrics: dict[str, Any] | None = None,
    poll_after_seconds: int = 3,
) -> None:
    row = await load_claim(session, claim)
    if row is None:
        raise IdentityMediaExecutionError("identity media lease lost")
    row.provider_state = provider_state
    row.polls += 1
    if row.polls >= row.max_polls:
        row.status = "failed"
        row.error_code = "identity_media_poll_limit"
        row.error_message = "Identity media provider polling limit reached"
        row.completed_at = _now()
    else:
        row.status = "provider_running"
        row.available_at = _now() + timedelta(seconds=max(1, poll_after_seconds))
    if metrics:
        row.provider_metadata = {**(row.provider_metadata or {}), "metrics": dict(metrics)}
    row.lease_token = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.version += 1
    await session.flush()


async def fail_execution(
    session: AsyncSession,
    claim: IdentityMediaClaim,
    *,
    code: str,
    message: str,
    needs_review: bool = False,
) -> None:
    row = await load_claim(session, claim)
    if row is None:
        return
    row.status = "needs_review" if needs_review else "failed"
    row.error_code = str(code or "identity_media_failure")[:120]
    row.error_message = str(message or "Identity media execution failed")[:1000]
    row.completed_at = _now()
    row.lease_token = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.version += 1
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=row.requested_by_id,
            action="identity_media.execution.needs_review" if needs_review else "identity_media.execution.failed",
            resource_type="identity_media_execution",
            resource_id=row.id,
            details={"code": row.error_code, "operation": row.operation, "provider": row.provider},
        )
    )
    await session.flush()


async def complete_execution(
    session: AsyncSession,
    claim: IdentityMediaClaim,
    *,
    storage_backend: str,
    storage_key: str,
    checksum: str,
    size_bytes: int,
    media_type: str,
    actual_cost_usd: float | None,
    provider_metadata: dict[str, Any] | None = None,
) -> None:
    row = await load_claim(session, claim)
    if row is None:
        raise IdentityMediaExecutionError("identity media lease lost")
    if len(checksum) != 64:
        raise IdentityMediaExecutionError("identity media output checksum invalid")
    if actual_cost_usd is not None and actual_cost_usd > row.max_cost_usd + 1e-9:
        # Store the output, but force operator review rather than claiming successful bounded spend.
        row.status = "needs_review"
        row.error_code = "identity_media_cost_exceeded"
        row.error_message = "Provider-reported cost exceeded the approved cap"
    else:
        row.status = "completed"
    row.provider_state = "succeeded"
    row.output_storage_backend = storage_backend
    row.output_storage_key = storage_key
    row.output_checksum_sha256 = checksum
    row.output_size_bytes = int(size_bytes)
    row.output_media_type = media_type
    row.actual_cost_usd = actual_cost_usd
    if provider_metadata:
        row.provider_metadata = {**(row.provider_metadata or {}), **provider_metadata}
    row.completed_at = _now()
    row.lease_token = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.version += 1
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=row.requested_by_id,
            action="identity_media.execution.completed" if row.status == "completed" else "identity_media.execution.needs_review",
            resource_type="identity_media_execution",
            resource_id=row.id,
            details={
                "operation": row.operation,
                "provider": row.provider,
                "model": row.model,
                "output_checksum_sha256": checksum,
                "output_size_bytes": size_bytes,
                "actual_cost_usd": actual_cost_usd,
            },
        )
    )
    await session.flush()
