from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,)

    def execute(self, operation: Callable[[], T]) -> T:
        if self.attempts < 1:
            raise ValueError("attempts must be positive")
        last_error: BaseException | None = None
        for _ in range(self.attempts):
            try:
                return operation()
            except self.retryable_exceptions as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout_seconds: float = 30.0) -> None:
        if failure_threshold < 1 or recovery_timeout_seconds <= 0:
            raise ValueError("invalid circuit breaker configuration")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.state = CircuitState.CLOSED
        self.failures = 0
        self._opened_at: float | None = None

    def _refresh(self) -> None:
        if self.state is CircuitState.OPEN and self._opened_at is not None:
            if monotonic() - self._opened_at >= self.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN

    def allow_request(self) -> bool:
        self._refresh()
        return self.state is not CircuitState.OPEN

    def record_success(self) -> None:
        self.failures = 0
        self._opened_at = None
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self._opened_at = monotonic()

    def execute(self, operation: Callable[[], T]) -> T:
        if not self.allow_request():
            raise RuntimeError("circuit breaker is open")
        try:
            result = operation()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result
