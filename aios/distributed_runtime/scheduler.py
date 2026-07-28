from __future__ import annotations

from dataclasses import dataclass

from .models import RuntimeTask, TaskSpec, WorkerDescriptor
from .queue import InMemoryTaskQueue
from .registry import WorkerRegistry


@dataclass(slots=True, frozen=True)
class Assignment:
    task: RuntimeTask
    worker: WorkerDescriptor


class RuntimeScheduler:
    def __init__(self, queue: InMemoryTaskQueue, registry: WorkerRegistry) -> None:
        self._queue = queue
        self._registry = registry

    def submit(self, spec: TaskSpec) -> RuntimeTask:
        return self._queue.submit(RuntimeTask(spec=spec))

    def assign_next(self, queue_name: str = "default", lease_seconds: int = 30) -> Assignment | None:
        pending = [
            task
            for task in self._queue._tasks.values()
            if task.state.value == "pending" and task.spec.queue == queue_name
        ]
        if not pending:
            return None
        pending.sort(key=lambda task: (task.spec.priority, task.created_at, task.task_id))
        for task in pending:
            workers = self._registry.eligible(task)
            if not workers:
                continue
            worker = workers[0]
            leased = self._queue.lease(worker.worker_id, worker.queues, lease_seconds=lease_seconds)
            if leased is None:
                continue
            worker.active_tasks += 1
            return Assignment(task=leased, worker=worker)
        return None

    def complete(self, task_id: str, worker_id: str, result: object = None) -> RuntimeTask:
        task = self._queue.complete(task_id, worker_id, result)
        worker = self._registry.get(worker_id)
        worker.active_tasks = max(0, worker.active_tasks - 1)
        return task

    def fail(self, task_id: str, worker_id: str, error: str) -> RuntimeTask:
        task = self._queue.fail(task_id, worker_id, error)
        worker = self._registry.get(worker_id)
        worker.active_tasks = max(0, worker.active_tasks - 1)
        return task
