from __future__ import annotations
import asyncio, time, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional
from .workers import WorkerRegistry

class TaskStatus(str, Enum):
    PENDING="PENDING"; ASSIGNED="ASSIGNED"; RUNNING="RUNNING"; SUCCEEDED="SUCCEEDED"; FAILED="FAILED"; CANCELLED="CANCELLED"; RETRYING="RETRYING"

@dataclass
class ScheduledTask:
    task_id: str
    name: str
    payload: Dict[str, Any]
    capability: Optional[str] = None
    priority: int = 100
    max_retries: int = 3
    attempts: int = 0
    status: TaskStatus = TaskStatus.PENDING
    assigned_worker: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

TaskHandler = Callable[[ScheduledTask], Awaitable[Any]]

class DistributedScheduler:
    def __init__(self, workers: WorkerRegistry):
        self.workers = workers
        self.tasks: Dict[str, ScheduledTask] = {}
        self.handlers: Dict[str, TaskHandler] = {}
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.lock = asyncio.Lock()
        self.running = False
        self._loop_task: Optional[asyncio.Task] = None

    async def register_handler(self, name: str, handler: TaskHandler) -> None:
        self.handlers[name] = handler

    async def submit(self, name: str, payload: Optional[Dict[str, Any]] = None, capability: Optional[str] = None, priority: int = 100, max_retries: int = 3) -> ScheduledTask:
        task = ScheduledTask(uuid.uuid4().hex, name, payload or {}, capability, priority, max_retries)
        async with self.lock:
            self.tasks[task.task_id] = task
        await self.queue.put((priority, task.created_at, task.task_id))
        return task

    async def cancel(self, task_id: str) -> ScheduledTask:
        async with self.lock:
            task = self.tasks[task_id]
            if task.status not in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
                task.status = TaskStatus.CANCELLED
                task.updated_at = time.time()
            return task

    async def _execute(self, task: ScheduledTask) -> None:
        worker = await self.workers.select(task.capability)
        if worker is None:
            await self.queue.put((task.priority, time.time(), task.task_id))
            await asyncio.sleep(0.05)
            return
        handler = self.handlers.get(task.name)
        if handler is None:
            task.status, task.error = TaskStatus.FAILED, f"No handler registered for {task.name}"
            task.updated_at = time.time()
            return
        task.assigned_worker = worker.worker_id
        task.status = TaskStatus.RUNNING
        task.attempts += 1
        worker.current_load += 1
        task.updated_at = time.time()
        try:
            task.result = await handler(task)
            task.status = TaskStatus.SUCCEEDED
            task.error = None
        except Exception as exc:
            task.error = str(exc)
            if task.attempts <= task.max_retries:
                task.status = TaskStatus.RETRYING
                await self.queue.put((task.priority, time.time(), task.task_id))
            else:
                task.status = TaskStatus.FAILED
        finally:
            worker.current_load = max(0, worker.current_load-1)
            task.updated_at = time.time()

    async def run_once(self) -> bool:
        try:
            _, _, task_id = self.queue.get_nowait()
        except asyncio.QueueEmpty:
            return False
        task = self.tasks[task_id]
        if task.status == TaskStatus.CANCELLED:
            return True
        await self._execute(task)
        return True

    async def _worker_loop(self) -> None:
        try:
            while self.running:
                processed = await self.run_once()
                if not processed:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            return

    async def start(self) -> None:
        if not self.running:
            self.running = True
            self._loop_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        self.running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def summary(self) -> dict:
        async with self.lock:
            values = list(self.tasks.values())
            return {"total": len(values), **{status.value.lower(): sum(t.status == status for t in values) for status in TaskStatus}}
