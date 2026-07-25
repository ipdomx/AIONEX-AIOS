from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class RoleLevel(StrEnum):
    SPECIALIST = 'specialist'
    ENGINEER = 'engineer'
    MANAGER = 'manager'
    CHIEF_ENGINEER = 'chief_engineer'


class WorkStatus(StrEnum):
    PLANNED = 'planned'
    IN_PROGRESS = 'in_progress'
    REVIEW = 'review'
    REWORK = 'rework'
    COMPLETE = 'complete'
    BLOCKED = 'blocked'


@dataclass(slots=True, frozen=True)
class CompetencyProfile:
    domains: tuple[str, ...]
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    experience_score: float = 0.75
    quality_score: float = 0.75
    security_score: float = 0.75
    reliability_score: float = 0.75

    @property
    def aggregate(self) -> float:
        return round((self.experience_score + self.quality_score + self.security_score + self.reliability_score) / 4, 4)


@dataclass(slots=True, frozen=True)
class DigitalWorker:
    worker_id: str
    name: str
    role: RoleLevel
    department: str
    competency: CompetencyProfile
    authority: tuple[str, ...] = ()


@dataclass(slots=True)
class Deliverable:
    title: str
    department: str
    acceptance_criteria: tuple[str, ...]
    evidence: dict[str, Any] = field(default_factory=dict)
    status: WorkStatus = WorkStatus.PLANNED
    owner_id: str | None = None
    reviewer_id: str | None = None
    defects: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def completeness(self) -> float:
        if not self.acceptance_criteria:
            return 0.0
        passed = self.evidence.get('passed_criteria', [])
        return min(1.0, len(set(passed)) / len(self.acceptance_criteria))


@dataclass(slots=True, frozen=True)
class DepartmentDecision:
    department: str
    approved: bool
    score: float
    findings: tuple[str, ...]
    required_actions: tuple[str, ...]
    manager_id: str


@dataclass(slots=True, frozen=True)
class ChiefReview:
    project: str
    approved: bool
    readiness_score: float
    department_decisions: tuple[DepartmentDecision, ...]
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    rationale: str
    reviewed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
