from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from .models import TaskRecord, TaskState, WorkerState
from .store import ExecutionFabricStore


TaskHandler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class WorkerAgent:
    """Leased worker that processes only explicitly registered task handlers."""

    def __init__(
        self,
        store: ExecutionFabricStore,
        worker_id: str,
        capabilities: Sequence[str],
        *,
        handlers: Mapping[str, TaskHandler],
        max_concurrency: int = 1,
        heartbeat_timeout: float = 30.0,
        lease_seconds: float = 30.0,
        retry_delay_seconds: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        normalized = tuple(sorted({item.strip().lower() for item in capabilities if item.strip()}))
        if not normalized:
            raise ValueError("at least one capability is required")
        if not handlers:
            raise ValueError("at least one task handler is required")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if heartbeat_timeout <= 0 or lease_seconds <= 0:
            raise ValueError("heartbeat and lease timeouts must be positive")
        self.store = store
        self.worker_id = worker_id
        self.capabilities = normalized
        self.handlers = dict(handlers)
        self.max_concurrency = int(max_concurrency)
        self.heartbeat_timeout = float(heartbeat_timeout)
        self.lease_seconds = float(lease_seconds)
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self.metadata = dict(metadata or {})
        self.started = False
        self.processed_task_ids: list[str] = []

    def start(self) -> None:
        self.store.register_worker(
            self.worker_id,
            self.capabilities,
            max_concurrency=self.max_concurrency,
            metadata=self.metadata,
        )
        self.started = True

    def stop(self, *, failed: bool = False) -> None:
        if self.started:
            self.store.set_worker_state(
                self.worker_id,
                WorkerState.FAILED if failed else WorkerState.OFFLINE,
            )
        self.started = False

    async def run_once(self) -> TaskRecord | None:
        if not self.started:
            self.start()
        self.store.heartbeat_worker(self.worker_id)
        self.store.recover_expired_leases()
        task = self.store.claim_task(
            self.worker_id,
            lease_seconds=self.lease_seconds,
            heartbeat_timeout=self.heartbeat_timeout,
        )
        if task is None:
            return None

        handler = self.handlers.get(task.name)
        if handler is None:
            failed = self.store.fail_task(
                task.task_id,
                self.worker_id,
                f"no handler registered for task {task.name}",
                retry_delay_seconds=self.retry_delay_seconds,
            )
            self.processed_task_ids.append(task.task_id)
            return failed

        try:
            produced = handler(dict(task.payload))
            if inspect.isawaitable(produced):
                produced = await produced
            if not isinstance(produced, dict):
                raise TypeError("task handler must return a dictionary")
            produced = dict(produced)
            produced.setdefault("worker_id", self.worker_id)
            produced.setdefault("task_id", task.task_id)
            completed = self.store.complete_task(
                task.task_id,
                self.worker_id,
                produced,
            )
            self.processed_task_ids.append(task.task_id)
            return completed
        except asyncio.CancelledError:
            self.store.fail_task(
                task.task_id,
                self.worker_id,
                "worker execution was cancelled",
                retry_delay_seconds=self.retry_delay_seconds,
            )
            raise
        except BaseException as exc:
            failed = self.store.fail_task(
                task.task_id,
                self.worker_id,
                f"{type(exc).__name__}: {str(exc)[:800]}",
                retry_delay_seconds=self.retry_delay_seconds,
            )
            self.processed_task_ids.append(task.task_id)
            return failed

    async def run_until_idle(
        self,
        *,
        max_cycles: int = 1000,
        idle_rounds: int = 2,
        idle_sleep_seconds: float = 0.0,
    ) -> int:
        if max_cycles < 1 or idle_rounds < 1:
            raise ValueError("cycle limits must be positive")
        processed = 0
        idle = 0
        for _ in range(max_cycles):
            task = await self.run_once()
            if task is None:
                idle += 1
                if idle >= idle_rounds:
                    break
                if idle_sleep_seconds > 0:
                    await asyncio.sleep(idle_sleep_seconds)
                continue
            processed += 1
            idle = 0
        return processed


async def drive_workers_until_terminal(
    store: ExecutionFabricStore,
    workers: Sequence[WorkerAgent],
    execution_id: str,
    *,
    max_rounds: int = 1000,
    idle_round_limit: int = 5,
) -> tuple[TaskRecord, ...]:
    """Round-robin workers until all execution tasks are terminal or no progress is possible."""
    if not workers:
        raise ValueError("at least one worker is required")
    if max_rounds < 1 or idle_round_limit < 1:
        raise ValueError("round limits must be positive")
    for worker in workers:
        if not worker.started:
            worker.start()

    idle_rounds = 0
    for _ in range(max_rounds):
        tasks = store.list_tasks(execution_id)
        if tasks and all(
            task.state in {TaskState.SUCCEEDED, TaskState.DEAD_LETTER, TaskState.CANCELLED}
            for task in tasks
        ):
            return tasks

        before = tuple((task.task_id, task.state, task.attempts) for task in tasks)
        for worker in workers:
            await worker.run_once()
        store.recover_expired_leases(now=time.time())
        after_tasks = store.list_tasks(execution_id)
        after = tuple((task.task_id, task.state, task.attempts) for task in after_tasks)
        if after == before:
            idle_rounds += 1
            if idle_rounds >= idle_round_limit:
                break
        else:
            idle_rounds = 0

    tasks = store.list_tasks(execution_id)
    if tasks and all(
        task.state in {TaskState.SUCCEEDED, TaskState.DEAD_LETTER, TaskState.CANCELLED}
        for task in tasks
    ):
        return tasks
    unfinished = [task.task_id for task in tasks if task.state not in {TaskState.SUCCEEDED, TaskState.DEAD_LETTER, TaskState.CANCELLED}]
    raise RuntimeError(f"execution fabric stalled with unfinished tasks: {unfinished}")
