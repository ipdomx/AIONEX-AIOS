from __future__ import annotations

import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    def __init__(self, requests_per_minute: int = 60, concurrent_requests: int = 8) -> None:
        if requests_per_minute <= 0 or concurrent_requests <= 0:
            raise ValueError("rate limits must be positive")
        self.requests_per_minute = requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(concurrent_requests)

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self._semaphore.acquire()
        async with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] >= 60:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.requests_per_minute:
                await asyncio.sleep(max(0.0, 60 - (now - self._timestamps[0])))
            self._timestamps.append(time.monotonic())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._semaphore.release()
