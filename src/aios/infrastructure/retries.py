from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.05
    maximum_delay: float = 1.0
    retry_exceptions: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        last: BaseException | None = None
        for attempt in range(max(1, self.attempts)):
            try:
                return await operation()
            except self.retry_exceptions as exc:
                last = exc
                if attempt + 1 >= self.attempts:
                    raise
                await asyncio.sleep(min(self.maximum_delay, self.base_delay * (2 ** attempt)))
        assert last is not None
        raise last
