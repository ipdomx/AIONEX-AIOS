from __future__ import annotations
import time, uuid
from typing import Any, Awaitable, Callable, Dict, Optional
from .checkpoints import CheckpointManager
from .scheduler import DistributedScheduler, ScheduledTask, TaskStatus
from .workers import WorkerRegistry, WorkerStatus

RecoveryHandler = Callable[[ScheduledTask, Dict[str, Any]], Awaitable[Any]]

class DistributedRecoveryManager:
    def __init__(self, workers: WorkerRegistry, scheduler: DistributedScheduler, checkpoints: CheckpointManager):
        self.workers = workers
        self.scheduler = scheduler
        self.checkpoints = checkpoints
        self.handlers: Dict[str, RecoveryHandler] = {}
        self.operations: Dict[str, dict] = {}

    async def register_handler(self, task_name: str, handler: RecoveryHandler) -> None:
        self.handlers[task_name] = handler

    async def recover_task(self, task_id: str) -> dict:
        operation_id = uuid.uuid4().hex
        started = time.time()
        task = self.scheduler.tasks[task_id]
        record = await self.checkpoints.latest(task_id)
        state: Dict[str, Any] = {}
        if record is not None:
            state = (await self.checkpoints.load(record.checkpoint_id)).get("state", {})
        handler = self.handlers.get(task.name)
        status, error, result = "SUCCESS", None, None
        try:
            if handler is not None:
                result = await handler(task, state)
                task.result = result
                task.status = TaskStatus.SUCCEEDED
                task.error = None
            else:
                task.status = TaskStatus.PENDING
                task.assigned_worker = None
                await self.scheduler.queue.put((task.priority, time.time(), task.task_id))
                status = "REQUEUED"
        except Exception as exc:
            status, error = "FAILED", str(exc)
            task.status, task.error = TaskStatus.FAILED, error
        operation = {"operation_id": operation_id, "task_id": task_id, "checkpoint_id": record.checkpoint_id if record else None, "status": status, "error": error, "result": result, "duration_seconds": time.time()-started}
        self.operations[operation_id] = operation
        return operation

    async def recover_failed_workers(self) -> list[dict]:
        results = []
        failed_ids = {worker.worker_id for worker in self.workers.workers.values() if worker.status in {WorkerStatus.OFFLINE, WorkerStatus.FAILED}}
        for task in list(self.scheduler.tasks.values()):
            if task.assigned_worker in failed_ids and task.status in {TaskStatus.ASSIGNED, TaskStatus.RUNNING, TaskStatus.RETRYING}:
                results.append(await self.recover_task(task.task_id))
        return results

    async def summary(self) -> dict:
        values = list(self.operations.values())
        return {"total": len(values), "successful": sum(v["status"] == "SUCCESS" for v in values), "requeued": sum(v["status"] == "REQUEUED" for v in values), "failed": sum(v["status"] == "FAILED" for v in values)}
