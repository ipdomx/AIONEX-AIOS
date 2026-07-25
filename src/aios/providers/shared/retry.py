from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.05
    max_delay: float = 1.0
    retryable: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)


class RetryManager:
    def __init__(self, policy: RetryPolicy | None = None) -> None:
        self.policy = policy or RetryPolicy()

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        last: BaseException | None = None
        for attempt in range(1, max(1, self.policy.max_attempts) + 1):
            try:
                return await operation()
            except self.policy.retryable as exc:
                last = exc
                if attempt >= self.policy.max_attempts:
                    raise
                delay = min(self.policy.base_delay * (2 ** (attempt - 1)), self.policy.max_delay)
                await asyncio.sleep(delay)
        assert last is not None
        raise last
