from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(order=True)
class QueueItem(Generic[T]):
    priority: int
    sequence: int
    operation: Callable[[], Awaitable[T]] = field(compare=False)
    future: asyncio.Future[T] = field(compare=False)


class QueueManager:
    def __init__(self, workers: int = 2) -> None:
        self.workers = max(1, workers)
        self._queue: asyncio.PriorityQueue[QueueItem] = asyncio.PriorityQueue()
        self._sequence = itertools.count()
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._loop = loop
            self._queue = asyncio.PriorityQueue()
            self._tasks = []
        self._tasks = [task for task in self._tasks if not task.done()]
        if not self._tasks:
            self._tasks = [asyncio.create_task(self._worker()) for _ in range(self.workers)]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def submit(self, operation: Callable[[], Awaitable[T]], priority: int = 100) -> T:
        await self.start()
        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        await self._queue.put(QueueItem(priority, next(self._sequence), operation, future))
        return await future

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                item.future.set_result(await item.operation())
            except Exception as exc:
                if not item.future.done():
                    item.future.set_exception(exc)
            finally:
                self._queue.task_done()


class RequestScheduler:
    def __init__(self, max_concurrency: int = 8) -> None:
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def run(self, operation: Callable[[], Awaitable[T]], timeout: float) -> T:
        async with self._semaphore:
            return await asyncio.wait_for(operation(), timeout=timeout)
