from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class WorkerState(StrEnum):
    ONLINE = "online"
    DRAINING = "draining"
    OFFLINE = "offline"
    FAILED = "failed"


class TaskState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATES = frozenset(
    {TaskState.SUCCEEDED, TaskState.DEAD_LETTER, TaskState.CANCELLED}
)


@dataclass(frozen=True, slots=True)
class WorkerRecord:
    worker_id: str
    capabilities: tuple[str, ...]
    max_concurrency: int
    current_load: int
    state: WorkerState
    heartbeat_at: float
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    execution_id: str
    name: str
    capability: str
    payload: dict[str, Any]
    priority: int
    state: TaskState
    attempts: int
    max_attempts: int
    available_at: float
    lease_owner: str | None
    lease_expires_at: float | None
    result: dict[str, Any] | None
    error: str | None
    idempotency_key: str
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class DeadLetterRecord:
    task_id: str
    execution_id: str
    name: str
    capability: str
    payload: dict[str, Any]
    attempts: int
    final_error: str
    failed_at: float


@dataclass(frozen=True, slots=True)
class ProjectCycleResult:
    execution_id: str
    output_directory: Path
    manifest_path: Path
    report_path: Path
    approved: bool
    readiness_score: float
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    tasks_total: int
    tasks_succeeded: int
    tasks_dead_lettered: int
    workers_used: tuple[str, ...]
    total_duration: float
