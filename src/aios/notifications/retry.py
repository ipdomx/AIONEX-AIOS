from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class RetryRecord:
    delivery_id: str
    attempts: int = 0
    max_attempts: int = 3
    next_attempt_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dead_lettered: bool = False
    last_error: str | None = None


class NotificationRetryManager:
    def __init__(self, *, base_delay_seconds: int = 30) -> None:
        if base_delay_seconds <= 0:
            raise ValueError("base delay must be positive")
        self._base_delay_seconds = base_delay_seconds
        self._records: dict[str, RetryRecord] = {}

    def register_failure(self, delivery_id: str, error: str, *, max_attempts: int = 3) -> RetryRecord:
        record = self._records.setdefault(
            delivery_id,
            RetryRecord(delivery_id=delivery_id, max_attempts=max_attempts),
        )
        if record.dead_lettered:
            return record
        record.attempts += 1
        record.last_error = error
        if record.attempts >= record.max_attempts:
            record.dead_lettered = True
            return record
        delay = self._base_delay_seconds * (2 ** (record.attempts - 1))
        record.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        return record

    def mark_success(self, delivery_id: str) -> None:
        self._records.pop(delivery_id, None)

    def due(self, now: datetime | None = None) -> list[RetryRecord]:
        current = now or datetime.now(timezone.utc)
        return [
            record
            for record in self._records.values()
            if not record.dead_lettered and record.next_attempt_at <= current
        ]

    def dead_letters(self) -> list[RetryRecord]:
        return [record for record in self._records.values() if record.dead_lettered]
