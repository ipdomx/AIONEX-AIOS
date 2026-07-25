from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping
from uuid import uuid4


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingState(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


@dataclass(frozen=True)
class SecurityFinding:
    title: str
    category: str
    severity: Severity
    location: str
    evidence: str
    remediation: tuple[str, ...]
    verification: tuple[str, ...]
    confidence: float = 1.0
    metadata: Mapping[str, object] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class RiskSummary:
    score: float
    grade: str
    counts: Mapping[str, int]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class SecurityAssessment:
    project: str
    root: str
    authorized: bool
    findings: tuple[SecurityFinding, ...]
    risk: RiskSummary
    remediation_plan: tuple[str, ...]
    verification_plan: tuple[str, ...]
