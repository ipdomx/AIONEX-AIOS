from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AutonomyLevel(str, Enum):
    ADVISORY = "advisory"
    SUPERVISED = "supervised"
    CONTROLLED = "controlled"


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class AutonomyPolicy:
    policy_id: str
    scope: str
    level: AutonomyLevel
    allowed_actions: frozenset[str]
    requires_owner_approval: bool = True
    max_risk_score: float = 0.25
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AutonomousDecision:
    decision_id: str
    policy_id: str
    action: str
    rationale: str
    risk_score: float
    evidence: list[str] = field(default_factory=list)
    status: DecisionStatus = DecisionStatus.PROPOSED
    proposed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_by: str | None = None
    executed_at: datetime | None = None
    rollback_reference: str | None = None
