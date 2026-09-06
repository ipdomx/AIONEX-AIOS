"""Governed Super Owner workflow for external activation boundaries."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services.external_activation_gates import (
    ExternalActivationEvidenceError,
    external_activation_snapshot,
    review_owner_evidence,
    submit_owner_evidence,
)

router = APIRouter(prefix="/owner/external-activation", tags=["owner-external-activation"])


class ExternalActivationEvidenceSubmit(BaseModel):
    evidence_reference: str = Field(min_length=1, max_length=500)
    evidence_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    issuer: str = Field(min_length=1, max_length=200)
    expires_at: datetime | None = None
    notes: str = Field(default="", max_length=2000)


class ExternalActivationEvidenceReview(BaseModel):
    decision: Literal["accepted", "rejected", "revoked"]
    review_note: str = Field(default="", max_length=2000)


def _evidence_error(exc: ExternalActivationEvidenceError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("")
async def owner_external_activation_snapshot(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del actor
    return await external_activation_snapshot(session)


@router.post("/{gate_id}/evidence", status_code=201)
async def owner_submit_external_activation_evidence(
    gate_id: str,
    data: ExternalActivationEvidenceSubmit,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        evidence = await submit_owner_evidence(
            session,
            gate_id=gate_id,
            actor_id=actor.id,
            evidence_reference=data.evidence_reference,
            evidence_sha256=data.evidence_sha256,
            issuer=data.issuer,
            expires_at=data.expires_at,
            notes=data.notes,
        )
    except ExternalActivationEvidenceError as exc:
        raise _evidence_error(exc) from exc
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="owner.external_activation.evidence.submitted",
            resource_type="external_activation_gate",
            resource_id=gate_id,
            details={
                "evidence_sha256": evidence.get("evidence_sha256"),
                "issuer": evidence.get("issuer"),
                "expires_at": evidence.get("expires_at"),
                "version": evidence.get("version"),
                "runtime_gate_override": False,
            },
        )
    )
    await session.commit()
    return {"gate_id": gate_id, "evidence": evidence}


@router.put("/{gate_id}/evidence/review")
async def owner_review_external_activation_evidence(
    gate_id: str,
    data: ExternalActivationEvidenceReview,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        evidence = await review_owner_evidence(
            session,
            gate_id=gate_id,
            actor_id=actor.id,
            decision=data.decision,
            review_note=data.review_note,
        )
    except ExternalActivationEvidenceError as exc:
        raise _evidence_error(exc) from exc
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="owner.external_activation.evidence.reviewed",
            resource_type="external_activation_gate",
            resource_id=gate_id,
            details={
                "decision": data.decision,
                "evidence_sha256": evidence.get("evidence_sha256"),
                "version": evidence.get("version"),
                "runtime_gate_override": False,
            },
        )
    )
    await session.commit()
    return {"gate_id": gate_id, "evidence": evidence}
