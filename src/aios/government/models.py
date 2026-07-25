from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned_for_revision"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class GovernanceCase:
    case_id: str
    title: str
    action: str
    proposer: str
    evidence: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    requires_owner_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class GovernanceDecision:
    case_id: str
    verdict: Verdict
    rationale: str
    conditions: tuple[str, ...] = ()
    reviewers: tuple[str, ...] = ()
    owner_approval_required: bool = False
    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
