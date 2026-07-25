from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class VoteChoice(StrEnum):
    APPROVE = "approve"
    CONDITIONAL = "conditional"
    REJECT = "reject"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


class DecisionStatus(StrEnum):
    APPROVED = "approved"
    CONDITIONAL = "conditional"
    REJECTED = "rejected"
    ESCALATED = "escalated"


@dataclass(slots=True, frozen=True)
class Proposal:
    title: str
    description: str
    project: str | None = None
    risk_level: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(slots=True, frozen=True)
class CellOpinion:
    cell_id: str
    summary: str
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    conditions: tuple[str, ...]
    confidence: float
    vote: VoteChoice
    weight: float


@dataclass(slots=True, frozen=True)
class DecisionOutcome:
    proposal_id: str
    status: DecisionStatus
    score: float
    confidence: float
    quorum_reached: bool
    round_number: int
    opinions: tuple[CellOpinion, ...]
    conditions: tuple[str, ...]
    risks: tuple[str, ...]
    human_approval_required: bool
    rationale: str
    decided_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
