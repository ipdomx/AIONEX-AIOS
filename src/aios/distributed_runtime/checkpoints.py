from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    checkpoint_id: str
    task_id: str
    worker_id: str
    sequence: int
    state: dict[str, Any]
    created_at: datetime = field(default_factory=_utcnow)


class CheckpointStore:
    """Thread-safe in-memory checkpoint store with monotonic task sequences."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[str, list[Checkpoint]] = {}

    def save(self, *, task_id: str, worker_id: str, state: dict[str, Any]) -> Checkpoint:
        if not task_id or not worker_id:
            raise ValueError("task_id and worker_id are required")
        with self._lock:
            sequence = len(self._items.get(task_id, [])) + 1
            checkpoint = Checkpoint(
                checkpoint_id=str(uuid4()),
                task_id=task_id,
                worker_id=worker_id,
                sequence=sequence,
                state=dict(state),
            )
            self._items.setdefault(task_id, []).append(checkpoint)
            return checkpoint

    def latest(self, task_id: str) -> Checkpoint | None:
        with self._lock:
            checkpoints = self._items.get(task_id, [])
            return checkpoints[-1] if checkpoints else None

    def history(self, task_id: str) -> tuple[Checkpoint, ...]:
        with self._lock:
            return tuple(self._items.get(task_id, []))
