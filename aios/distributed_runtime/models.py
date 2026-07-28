from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskState(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerState(str, Enum):
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DRAINING = "draining"
    OFFLINE = "offline"


@dataclass(slots=True, frozen=True)
class TaskSpec:
    kind: str
    payload: Mapping[str, Any]
    queue: str = "default"
    priority: int = 100
    max_attempts: int = 3
    timeout_seconds: int = 300
    idempotency_key: str | None = None
    required_capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("task kind is required")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")


@dataclass(slots=True)
class RuntimeTask:
    spec: TaskSpec
    task_id: str = field(default_factory=lambda: str(uuid4()))
    state: TaskState = TaskState.PENDING
    attempts: int = 0
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    leased_by: str | None = None
    lease_expires_at: datetime | None = None
    result: Any = None
    error: str | None = None


@dataclass(slots=True)
class WorkerDescriptor:
    worker_id: str
    capabilities: frozenset[str]
    queues: frozenset[str] = field(default_factory=lambda: frozenset({"default"}))
    max_concurrency: int = 1
    state: WorkerState = WorkerState.STARTING
    active_tasks: int = 0
    registered_at: datetime = field(default_factory=utcnow)
    last_heartbeat_at: datetime = field(default_factory=utcnow)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id is required")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")

    @property
    def available_slots(self) -> int:
        return max(0, self.max_concurrency - self.active_tasks)

    def can_run(self, task: RuntimeTask) -> bool:
        return (
            self.state is WorkerState.HEALTHY
            and self.available_slots > 0
            and task.spec.queue in self.queues
            and task.spec.required_capabilities.issubset(self.capabilities)
        )
