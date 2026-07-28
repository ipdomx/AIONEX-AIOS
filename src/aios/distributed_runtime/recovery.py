from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .checkpoints import CheckpointStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecoverableQueue(Protocol):
    def release_expired_leases(self, *, now: datetime | None = None) -> int: ...

    def retry(self, task_id: str, *, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    task_id: str
    recovered: bool
    checkpoint_sequence: int | None
    reason: str
    decided_at: datetime


class RecoveryManager:
    """Coordinates lease recovery and checkpoint-aware task retries."""

    def __init__(self, *, queue: RecoverableQueue, checkpoints: CheckpointStore) -> None:
        self._queue = queue
        self._checkpoints = checkpoints

    def recover_expired_leases(self) -> int:
        return self._queue.release_expired_leases(now=_utcnow())

    def recover_task(self, task_id: str, *, reason: str) -> RecoveryDecision:
        checkpoint = self._checkpoints.latest(task_id)
        self._queue.retry(task_id, reason=reason)
        return RecoveryDecision(
            task_id=task_id,
            recovered=True,
            checkpoint_sequence=checkpoint.sequence if checkpoint else None,
            reason=reason,
            decided_at=_utcnow(),
        )
