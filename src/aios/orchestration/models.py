from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

class TaskState(StrEnum):
    PLANNED='planned'; READY='ready'; RUNNING='running'; REVIEW='review'; REWORK='rework'; COMPLETE='complete'; BLOCKED='blocked'

@dataclass(slots=True, frozen=True)
class WorkContract:
    contract_id: str
    producer: str
    consumer: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    acceptance: tuple[str, ...]
    version: str = '1.0'

@dataclass(slots=True)
class OrchestratedTask:
    title: str
    department: str
    required_skills: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    state: TaskState = TaskState.PLANNED
    id: str = field(default_factory=lambda: str(uuid4()))

@dataclass(slots=True, frozen=True)
class IntegrationVerdict:
    approved: bool
    score: float
    findings: tuple[str, ...]
    required_actions: tuple[str, ...]

@dataclass(slots=True, frozen=True)
class DeliveryVerdict:
    approved: bool
    score: float
    missing_evidence: tuple[str, ...]
    rationale: str
