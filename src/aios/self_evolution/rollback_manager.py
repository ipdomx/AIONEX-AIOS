from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RollbackState(str, Enum):
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class RollbackRecord:
    rollback_id: str
    owner_id: str
    experiment_id: str
    plan: str
    state: RollbackState = RollbackState.READY
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class RollbackManager:
    def __init__(self) -> None:
        self._records: dict[str, RollbackRecord] = {}

    def register(self, record: RollbackRecord) -> RollbackRecord:
        if not record.plan.strip():
            raise ValueError("rollback plan must not be empty")
        if record.rollback_id in self._records:
            raise ValueError(f"duplicate rollback: {record.rollback_id}")
        self._records[record.rollback_id] = record
        return record

    def start(self, rollback_id: str, owner_id: str) -> RollbackRecord:
        record = self._require_owner(rollback_id, owner_id)
        if record.state is not RollbackState.READY:
            raise RuntimeError("rollback is not ready")
        record.state = RollbackState.EXECUTING
        record.started_at = datetime.now(timezone.utc)
        return record

    def complete(self, rollback_id: str, owner_id: str) -> RollbackRecord:
        record = self._require_owner(rollback_id, owner_id)
        if record.state is not RollbackState.EXECUTING:
            raise RuntimeError("rollback is not executing")
        record.state = RollbackState.COMPLETED
        record.completed_at = datetime.now(timezone.utc)
        return record

    def fail(self, rollback_id: str, owner_id: str, error: str) -> RollbackRecord:
        record = self._require_owner(rollback_id, owner_id)
        record.state = RollbackState.FAILED
        record.error = error
        record.completed_at = datetime.now(timezone.utc)
        return record

    def _require_owner(self, rollback_id: str, owner_id: str) -> RollbackRecord:
        record = self._records[rollback_id]
        if record.owner_id != owner_id:
            raise PermissionError("rollback is not owned by this owner")
        return record
