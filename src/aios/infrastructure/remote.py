from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .connections import ConnectionManager


class RemoteJobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class RemoteJob:
    profile: str
    capability: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: RemoteJobState = RemoteJobState.PENDING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None


class RemoteExecutionManager:
    def __init__(self, connections: ConnectionManager, *, concurrency: int = 4) -> None:
        self.connections = connections
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._jobs: dict[str, RemoteJob] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def get(self, job_id: str) -> RemoteJob:
        return self._jobs[job_id]

    async def submit(self, profile: str, capability: str, payload: dict[str, Any] | None = None,
                     *, wait: bool = True) -> RemoteJob:
        job = RemoteJob(profile, capability, dict(payload or {}))
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job))
        self._tasks[job.id] = task
        if wait:
            await task
        return job

    async def _run(self, job: RemoteJob) -> None:
        async with self._semaphore:
            if job.state == RemoteJobState.CANCELLED:
                return
            job.state = RemoteJobState.RUNNING
            job.started_at = time.time()
            try:
                job.result = await self.connections.execute(job.profile, job.capability, job.payload)
                job.state = RemoteJobState.SUCCEEDED
            except asyncio.CancelledError:
                job.state = RemoteJobState.CANCELLED
                raise
            except Exception as exc:
                job.error = str(exc)
                job.state = RemoteJobState.FAILED
            finally:
                job.finished_at = time.time()
                self._tasks.pop(job.id, None)

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs[job_id]
        task = self._tasks.get(job_id)
        if task and not task.done():
            job.state = RemoteJobState.CANCELLED
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return True
        return False

    async def close(self) -> None:
        for job_id in tuple(self._tasks):
            await self.cancel(job_id)
