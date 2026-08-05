from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ProposalState(str, Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPERIMENTING = "experimenting"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


@dataclass(slots=True)
class EvidenceItem:
    source: str
    claim: str
    confidence: float
    verified: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(slots=True)
class ImprovementProposal:
    proposal_id: str
    owner_id: str
    title: str
    hypothesis: str
    target_component: str
    risk_level: str
    expected_benefit: str
    state: ProposalState = ProposalState.DRAFT
    evidence: list[EvidenceItem] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, object] = field(default_factory=dict)
