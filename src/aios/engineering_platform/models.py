from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence
from uuid import uuid4


class ProjectSize(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    CRITICAL = "critical"


class GateState(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class EngineeringRequirement:
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    priority: int = 50
    tags: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class EngineeringTask:
    title: str
    department: str
    required_skills: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ProjectBlueprint:
    project: str
    objective: str
    size: ProjectSize
    requirements: tuple[EngineeringRequirement, ...]
    tasks: tuple[EngineeringTask, ...]
    languages: tuple[str, ...]
    services: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(frozen=True)
class AuditFinding:
    category: str
    severity: str
    title: str
    evidence: str
    remediation: tuple[str, ...]
    verification: tuple[str, ...]


@dataclass(frozen=True)
class GateResult:
    gate: str
    state: GateState
    score: float
    missing: tuple[str, ...] = ()
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryDecision:
    approved: bool
    readiness_score: float
    gates: tuple[GateResult, ...]
    blockers: tuple[str, ...]
    rework_plan: tuple[str, ...]
