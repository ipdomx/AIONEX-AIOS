"""Durable Phase 36K professional evidence and human-review authority."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    ProfessionalEvidenceCase,
    ProfessionalReviewDecision,
    Workspace,
    uuid_str,
)

CASE_MODES = frozenset(
    {"administrative", "education", "professional_assistance", "clinical_high_stakes"}
)
RESIDENCY_PROFILES: dict[str, dict[str, Any]] = {
    "tenant-default": {
        "residency": "tenant_default",
        "retention_days": 30,
        "certified": False,
        "requires_local_legal_validation": True,
    },
    "region-locked": {
        "residency": "region_locked",
        "retention_days": 30,
        "certified": False,
        "requires_local_legal_validation": True,
    },
    "country-locked": {
        "residency": "country_locked",
        "retention_days": 30,
        "certified": False,
        "requires_local_legal_validation": True,
    },
    "local-only": {
        "residency": "local_only",
        "retention_days": 7,
        "certified": False,
        "requires_local_legal_validation": True,
    },
}


def now() -> datetime:
    return datetime.now(UTC)


def _subject_hash(*, organization_id: str, raw_reference: str) -> str:
    reference = raw_reference.strip()
    if not 2 <= len(reference) <= 500:
        raise ValueError("Subject reference is outside the allowed range")
    key = hashlib.sha256(
        f"phase36k\0{organization_id}\0{settings.SECRET_KEY}".encode()
    ).digest()
    return hmac.new(key, reference.encode(), hashlib.sha256).hexdigest()


def _normalize_citations(
    citations: list[dict[str, Any]], *, high_stakes: bool
) -> tuple[list[dict[str, str]], str]:
    minimum = 2 if high_stakes else 1
    if not minimum <= len(citations) <= 64:
        raise ValueError(
            f"Professional evidence requires at least {minimum} citation(s)"
        )
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in citations:
        citation_id = str(row.get("citation_id") or "").strip()
        title = str(row.get("title") or "").strip()
        uri = str(row.get("uri") or "").strip()
        source_sha256 = str(row.get("source_sha256") or "").strip().lower()
        if not 2 <= len(citation_id) <= 80 or citation_id in seen:
            raise ValueError("Citation identifiers must be unique and bounded")
        if not 2 <= len(title) <= 400:
            raise ValueError("Citation title is outside the allowed range")
        if urlparse(uri).scheme not in {"https", "internal"}:
            raise ValueError("Citation URI must use https or internal scheme")
        if len(source_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in source_sha256
        ):
            raise ValueError("Citation source digest is invalid")
        seen.add(citation_id)
        normalized.append(
            {
                "citation_id": citation_id,
                "title": title,
                "uri": uri,
                "source_sha256": source_sha256,
            }
        )
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return normalized, hashlib.sha256(canonical.encode()).hexdigest()


def case_snapshot(item: ProfessionalEvidenceCase) -> dict[str, Any]:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "case_mode": item.case_mode,
        "purpose": item.purpose,
        "subject_ref_hash": item.subject_ref_hash,
        "request_summary": item.request_summary,
        "status": item.status,
        "residency_profile": item.residency_profile,
        "retention_until": item.retention_until.isoformat(),
        "retention_expired": item.retention_until <= now(),
        "citations": item.citations,
        "assistance": item.assistance,
        "evidence_digest": item.evidence_digest,
        "human_review_required": item.human_review_required,
        "autonomous_decision_allowed": item.autonomous_decision_allowed,
        "review_version": item.review_version,
        "closed_at": item.closed_at.isoformat() if item.closed_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def review_snapshot(item: ProfessionalReviewDecision) -> dict[str, Any]:
    return {
        "id": item.id,
        "case_id": item.case_id,
        "reviewer_id": item.reviewer_id,
        "decision": item.decision,
        "rationale": item.rationale,
        "evidence_digest": item.evidence_digest,
        "review_version": item.review_version,
        "metadata": item.decision_metadata,
        "created_at": item.created_at.isoformat(),
    }


async def create_case(
    session: AsyncSession,
    actor: UserRecord,
    *,
    workspace_id: str | None,
    case_mode: str,
    purpose: str,
    subject_reference: str,
    request_summary: str,
    direct_identifiers_removed: bool,
    residency_profile: str,
    retention_days: int | None,
    citations: list[dict[str, Any]],
) -> ProfessionalEvidenceCase:
    if case_mode not in CASE_MODES:
        raise ValueError("Unsupported professional case mode")
    if not direct_identifiers_removed:
        raise ValueError("Professional evidence requires a redacted request summary")
    if not 4 <= len(purpose.strip()) <= 2000:
        raise ValueError("Case purpose is outside the allowed range")
    if not 4 <= len(request_summary.strip()) <= 12000:
        raise ValueError("Redacted request summary is outside the allowed range")
    profile = RESIDENCY_PROFILES.get(residency_profile)
    if profile is None:
        raise ValueError("Unknown protected-data residency profile")
    if workspace_id:
        workspace = await session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.organization_id == actor.organization_id,
                Workspace.status == "active",
            )
        )
        if workspace is None:
            raise LookupError("Workspace is unavailable in the actor organization")
    days = int(retention_days or profile["retention_days"])
    if not 1 <= days <= 3650:
        raise ValueError("Retention must be between 1 and 3650 days")
    high_stakes = case_mode == "clinical_high_stakes"
    normalized_citations, evidence_digest = _normalize_citations(
        citations, high_stakes=high_stakes
    )
    item = ProfessionalEvidenceCase(
        id=uuid_str(),
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        created_by_id=actor.id,
        case_mode=case_mode,
        purpose=purpose.strip(),
        subject_ref_hash=_subject_hash(
            organization_id=actor.organization_id, raw_reference=subject_reference
        ),
        request_summary=request_summary.strip(),
        status="pending_review",
        residency_profile=residency_profile,
        retention_until=now() + timedelta(days=days),
        citations=normalized_citations,
        assistance={
            "kind": "evidence_packet",
            "citation_count": len(normalized_citations),
            "evidence_digest": evidence_digest,
            "review_state": "required" if high_stakes else "governed",
            "final_professional_decision": False,
            "compliance_claim": "configuration-profile-only-not-certification",
        },
        evidence_digest=evidence_digest,
        human_review_required=high_stakes,
        autonomous_decision_allowed=False,
        review_version=1,
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="professional.case.created",
            resource_type="professional_evidence_case",
            resource_id=item.id,
            details={
                "case_mode": case_mode,
                "residency_profile": residency_profile,
                "human_review_required": high_stakes,
                "evidence_digest": evidence_digest,
                "direct_identifiers_persisted": False,
            },
        )
    )
    await session.flush()
    return item


async def review_case(
    session: AsyncSession,
    actor: UserRecord,
    item: ProfessionalEvidenceCase,
    *,
    decision: str,
    rationale: str,
) -> ProfessionalReviewDecision:
    if item.organization_id != actor.organization_id:
        raise PermissionError("Professional case is outside the actor organization")
    if item.status == "closed":
        raise ValueError("Closed professional cases cannot be reviewed")
    if item.retention_until <= now():
        raise ValueError("Professional case retention window has expired")
    if decision not in {"approved", "rejected", "changes_requested"}:
        raise ValueError("Unsupported professional review decision")
    if not 4 <= len(rationale.strip()) <= 4000:
        raise ValueError("Review rationale is outside the allowed range")
    version = int(item.review_version or 1)
    existing = await session.scalar(
        select(ProfessionalReviewDecision).where(
            ProfessionalReviewDecision.case_id == item.id,
            ProfessionalReviewDecision.review_version == version,
        )
    )
    if existing is not None:
        raise ValueError("This professional case version already has a review decision")
    review = ProfessionalReviewDecision(
        id=uuid_str(),
        organization_id=actor.organization_id,
        case_id=item.id,
        reviewer_id=actor.id,
        decision=decision,
        rationale=rationale.strip(),
        evidence_digest=item.evidence_digest,
        review_version=version,
        decision_metadata={
            "human_review": True,
            "autonomous_decision": False,
            "case_mode": item.case_mode,
        },
        created_at=now(),
    )
    session.add(review)
    if decision == "changes_requested":
        item.status = "pending_review"
        item.review_version = version + 1
    else:
        item.status = decision
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="professional.case.reviewed",
            resource_type="professional_evidence_case",
            resource_id=item.id,
            details={
                "decision": decision,
                "review_version": version,
                "evidence_digest": item.evidence_digest,
                "human_review": True,
            },
        )
    )
    await session.flush()
    return review


async def close_case(
    session: AsyncSession, actor: UserRecord, item: ProfessionalEvidenceCase
) -> None:
    if item.organization_id != actor.organization_id:
        raise PermissionError("Professional case is outside the actor organization")
    if item.status not in {"approved", "rejected"}:
        raise ValueError("Only reviewed professional cases can be closed")
    item.status = "closed"
    item.closed_at = now()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="professional.case.closed",
            resource_type="professional_evidence_case",
            resource_id=item.id,
            details={"evidence_digest": item.evidence_digest},
        )
    )
    await session.flush()
