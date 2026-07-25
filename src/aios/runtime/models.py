from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

class WorkerState(StrEnum):
    ONLINE='online'; BUSY='busy'; DEGRADED='degraded'; OFFLINE='offline'

class TaskState(StrEnum):
    QUEUED='queued'; ASSIGNED='assigned'; RUNNING='running'; CHECKPOINTED='checkpointed'; COMPLETED='completed'; FAILED='failed'; REQUEUED='requeued'

@dataclass(slots=True)
class Worker:
    worker_id: str
    tenant_id: str
    capabilities: tuple[str, ...]
    cpu_cores: int=1
    memory_mb: int=512
    gpu: bool=False
    trust_score: float=0.5
    cost_per_hour: float=0.0
    state: WorkerState=WorkerState.ONLINE
    current_task: str | None=None

@dataclass(slots=True)
class DistributedTask:
    task_id: str
    tenant_id: str
    project_id: str
    capability: str
    payload: dict[str, Any]
    priority: int=3
    sensitivity: str='internal'
    state: TaskState=TaskState.QUEUED
    worker_id: str | None=None
    attempts: int=0
    checkpoint: dict[str, Any]=field(default_factory=dict)
    result: dict[str, Any]=field(default_factory=dict)
    failure_fingerprints: list[str]=field(default_factory=list)
