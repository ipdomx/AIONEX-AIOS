from __future__ import annotations

from collections import deque
from datetime import timedelta
from threading import RLock
from typing import Iterable

from .models import RuntimeTask, TaskState, utcnow


class InMemoryTaskQueue:
    """Deterministic queue suitable for tests and the first runtime bootstrap."""

    def __init__(self) -> None:
        self._tasks: dict[str, RuntimeTask] = {}
        self._pending: dict[str, deque[str]] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = RLock()

    def submit(self, task: RuntimeTask) -> RuntimeTask:
        with self._lock:
            key = task.spec.idempotency_key
            if key and key in self._idempotency:
                return self._tasks[self._idempotency[key]]
            self._tasks[task.task_id] = task
            self._pending.setdefault(task.spec.queue, deque()).append(task.task_id)
            if key:
                self._idempotency[key] = task.task_id
            return task

    def lease(self, worker_id: str, queues: Iterable[str], lease_seconds: int = 30) -> RuntimeTask | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        with self._lock:
            self.requeue_expired()
            candidates: list[RuntimeTask] = []
            for queue in queues:
                for task_id in list(self._pending.get(queue, ())):
                    task = self._tasks[task_id]
                    if task.state is TaskState.PENDING:
                        candidates.append(task)
            if not candidates:
                return None
            task = min(candidates, key=lambda item: (item.spec.priority, item.created_at, item.task_id))
            self._pending[task.spec.queue].remove(task.task_id)
            task.state = TaskState.LEASED
            task.leased_by = worker_id
            task.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
            task.attempts += 1
            task.updated_at = utcnow()
            return task

    def mark_running(self, task_id: str, worker_id: str) -> RuntimeTask:
        with self._lock:
            task = self._owned_task(task_id, worker_id)
            if task.state is not TaskState.LEASED:
                raise ValueError("task is not leased")
            task.state = TaskState.RUNNING
            task.updated_at = utcnow()
            return task

    def complete(self, task_id: str, worker_id: str, result: object = None) -> RuntimeTask:
        with self._lock:
            task = self._owned_task(task_id, worker_id)
            if task.state not in {TaskState.LEASED, TaskState.RUNNING}:
                raise ValueError("task cannot be completed")
            task.state = TaskState.SUCCEEDED
            task.result = result
            task.lease_expires_at = None
            task.updated_at = utcnow()
            return task

    def fail(self, task_id: str, worker_id: str, error: str) -> RuntimeTask:
        with self._lock:
            task = self._owned_task(task_id, worker_id)
            task.error = error
            task.leased_by = None
            task.lease_expires_at = None
            task.updated_at = utcnow()
            if task.attempts < task.spec.max_attempts:
                task.state = TaskState.PENDING
                self._pending.setdefault(task.spec.queue, deque()).append(task.task_id)
            else:
                task.state = TaskState.FAILED
            return task

    def requeue_expired(self) -> int:
        now = utcnow()
        count = 0
        for task in self._tasks.values():
            if task.state in {TaskState.LEASED, TaskState.RUNNING} and task.lease_expires_at and task.lease_expires_at <= now:
                task.leased_by = None
                task.lease_expires_at = None
                task.updated_at = now
                if task.attempts < task.spec.max_attempts:
                    task.state = TaskState.PENDING
                    self._pending.setdefault(task.spec.queue, deque()).append(task.task_id)
                else:
                    task.state = TaskState.FAILED
                    task.error = task.error or "lease expired"
                count += 1
        return count

    def get(self, task_id: str) -> RuntimeTask:
        return self._tasks[task_id]

    def _owned_task(self, task_id: str, worker_id: str) -> RuntimeTask:
        task = self._tasks[task_id]
        if task.leased_by != worker_id:
            raise PermissionError("worker does not own task lease")
        return task
