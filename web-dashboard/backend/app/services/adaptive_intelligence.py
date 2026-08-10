"""Evidence-gated adaptive learning for AIONEX AIOS.

The fabric records experience aggressively but promotes knowledge conservatively.
No user statement, model output, scan observation, or generated rule becomes trusted
knowledge merely because it was observed. Promotion requires provenance, repeatable
evidence and an explicit verification boundary.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import LearningEvent
from app.services import knowledge_learning

ExperienceSource = Literal[
    "user",
    "owner",
    "project",
    "test",
    "security_scan",
    "verified_external",
    "system",
]

_SOURCE_QUALITY: dict[str, float] = {
    "user": 0.35,
    "owner": 0.70,
    "project": 0.65,
    "test": 0.90,
    "security_scan": 0.80,
    "verified_external": 0.80,
    "system": 0.60,
}


@dataclass(frozen=True)
class TrustAssessment:
    score: float
    promotable: bool
    reasons: tuple[str, ...]


def assess_experience_trust(
    *,
    source: ExperienceSource,
    evidence_count: int,
    direct_evidence: bool,
    successful_repetitions: int = 0,
    contradictions: int = 0,
    verified: bool = False,
) -> TrustAssessment:
    """Return a deterministic trust score without trusting source identity alone."""
    score = _SOURCE_QUALITY[source]
    reasons = [f"source:{source}"]
    if direct_evidence:
        score += 0.10
        reasons.append("direct-evidence")
    if evidence_count > 0:
        score += min(0.12, evidence_count * 0.03)
        reasons.append(f"evidence:{evidence_count}")
    if successful_repetitions > 0:
        score += min(0.12, successful_repetitions * 0.04)
        reasons.append(f"repeat:{successful_repetitions}")
    if verified:
        score += 0.12
        reasons.append("verified")
    if contradictions > 0:
        score -= min(0.50, contradictions * 0.18)
        reasons.append(f"contradictions:{contradictions}")
    score = round(max(0.0, min(1.0, score)), 4)
    promotable = verified and direct_evidence and evidence_count > 0 and score >= 0.80
    if not promotable:
        reasons.append("quarantine")
    return TrustAssessment(score=score, promotable=promotable, reasons=tuple(reasons))


async def record_experience(
    session: AsyncSession,
    actor: UserRecord,
    *,
    source: ExperienceSource,
    action: str,
    context: dict[str, Any],
    outcome: Literal["success", "failure", "partial", "unknown"],
    evidence: Sequence[str],
    lesson: str | None = None,
    project_id: str | None = None,
    error: str | None = None,
) -> LearningEvent:
    """Persist an experience in the existing tenant-scoped evidence ledger.

    Recorded events intentionally remain unverified. A separate verification action
    is required before they can be promoted into reusable lessons or security rules.
    """
    assessment = assess_experience_trust(
        source=source,
        evidence_count=len([value for value in evidence if value.strip()]),
        direct_evidence=bool(evidence),
        verified=False,
    )
    enriched_context = {
        **context,
        "adaptive_source": source,
        "candidate_trust": assessment.score,
        "promotion_state": "quarantine",
    }
    return await knowledge_learning.create_learning_event(
        session,
        actor,
        action=action,
        context=enriched_context,
        outcome=outcome,
        evidence=evidence,
        strategy="adaptive-evidence-gated",
        project_id=project_id,
        error=error,
        lesson=lesson,
    )


async def record_system_experience(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str | None,
    action: str,
    context: dict[str, Any],
    outcome: Literal["success", "failure", "partial", "unknown"],
    evidence: Sequence[str],
    project_id: str | None = None,
    lesson: str | None = None,
) -> LearningEvent:
    """Record worker-generated evidence without fabricating a UserRecord.

    Worker observations are quarantined exactly like user observations; verification
    is still required before lesson/rule promotion.
    """
    from app.db.models import AuditEvent, uuid_str
    fingerprint = knowledge_learning.sha256(knowledge_learning.canonical_json(context))
    item = LearningEvent(
        id=uuid_str(),
        organization_id=organization_id,
        project_id=project_id,
        created_by_id=user_id,
        action=action.strip(),
        context_fingerprint=fingerprint,
        outcome=outcome,
        evidence=list(dict.fromkeys(value.strip() for value in evidence if value.strip())),
        strategy="adaptive-worker-evidence-gated",
        lesson=(lesson or "").strip() or None,
        status="recorded",
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=user_id,
            action="learning.event.recorded",
            resource_type="learning_event",
            resource_id=item.id,
            details={"source": "system-worker", "outcome": outcome, "context_fingerprint": fingerprint, "evidence_count": len(item.evidence)},
        )
    )
    await session.flush()
    return item
