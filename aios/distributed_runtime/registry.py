from __future__ import annotations

from datetime import timedelta
from threading import RLock

from .models import WorkerDescriptor, WorkerState, utcnow


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerDescriptor] = {}
        self._lock = RLock()

    def register(self, worker: WorkerDescriptor) -> WorkerDescriptor:
        with self._lock:
            if worker.worker_id in self._workers:
                raise ValueError(f"worker already registered: {worker.worker_id}")
            worker.state = WorkerState.HEALTHY
            worker.last_heartbeat_at = utcnow()
            self._workers[worker.worker_id] = worker
            return worker

    def heartbeat(self, worker_id: str, *, active_tasks: int | None = None) -> WorkerDescriptor:
        with self._lock:
            worker = self._workers[worker_id]
            if active_tasks is not None:
                if active_tasks < 0 or active_tasks > worker.max_concurrency:
                    raise ValueError("active_tasks is outside worker capacity")
                worker.active_tasks = active_tasks
            worker.last_heartbeat_at = utcnow()
            if worker.state not in {WorkerState.DRAINING, WorkerState.OFFLINE}:
                worker.state = WorkerState.HEALTHY
            return worker

    def mark_draining(self, worker_id: str) -> WorkerDescriptor:
        with self._lock:
            worker = self._workers[worker_id]
            worker.state = WorkerState.DRAINING
            return worker

    def expire_stale(self, heartbeat_timeout_seconds: int = 60) -> list[str]:
        if heartbeat_timeout_seconds < 1:
            raise ValueError("heartbeat timeout must be positive")
        threshold = utcnow() - timedelta(seconds=heartbeat_timeout_seconds)
        expired: list[str] = []
        with self._lock:
            for worker in self._workers.values():
                if worker.last_heartbeat_at < threshold and worker.state is not WorkerState.OFFLINE:
                    worker.state = WorkerState.OFFLINE
                    expired.append(worker.worker_id)
        return expired

    def eligible(self, task) -> list[WorkerDescriptor]:
        with self._lock:
            return sorted(
                (worker for worker in self._workers.values() if worker.can_run(task)),
                key=lambda worker: (worker.active_tasks / worker.max_concurrency, worker.worker_id),
            )

    def get(self, worker_id: str) -> WorkerDescriptor:
        return self._workers[worker_id]

    def all(self) -> tuple[WorkerDescriptor, ...]:
        return tuple(self._workers.values())
