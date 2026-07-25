from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class AssignmentState(StrEnum):
    QUEUED = 'queued'
    ASSIGNED = 'assigned'
    IN_PROGRESS = 'in_progress'
    REVIEW = 'review'
    REWORK = 'rework'
    COMPLETED = 'completed'
    BLOCKED = 'blocked'
    CANCELLED = 'cancelled'


@dataclass(slots=True, frozen=True)
class WorkRequest:
    project_id: str
    title: str
    required_skills: tuple[str, ...]
    ministry_id: str
    acceptance_criteria: tuple[str, ...]
    priority: int = 50
    risk: str = 'normal'
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(slots=True)
class Assignment:
    request: WorkRequest
    employee_id: str
    reviewer_id: str | None = None
    state: AssignmentState = AssignmentState.ASSIGNED
    evidence: dict[str, Any] = field(default_factory=dict)
    defects: list[str] = field(default_factory=list)
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None

    @property
    def completeness(self) -> float:
        required = set(self.request.acceptance_criteria)
        passed = set(self.evidence.get('passed_criteria', ()))
        if not required:
            return 0.0
        return round(len(required.intersection(passed)) / len(required), 4)


@dataclass(slots=True, frozen=True)
class PerformanceEvent:
    employee_id: str
    assignment_id: str
    outcome: str
    quality_score: float
    notes: str = ''
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
