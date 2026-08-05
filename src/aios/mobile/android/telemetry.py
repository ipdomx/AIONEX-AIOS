from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TelemetryLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class MobileTelemetryEvent:
    event_id: str
    owner_id: str
    device_id: str
    name: str
    level: TelemetryLevel
    attributes: dict[str, object] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AndroidTelemetryCollector:
    def __init__(self, max_events_per_device: int = 500) -> None:
        if max_events_per_device <= 0:
            raise ValueError("max events must be positive")
        self._max = max_events_per_device
        self._events: dict[str, list[MobileTelemetryEvent]] = {}

    def record(self, event: MobileTelemetryEvent) -> MobileTelemetryEvent:
        bucket = self._events.setdefault(event.device_id, [])
        if any(item.event_id == event.event_id for item in bucket):
            return next(item for item in bucket if item.event_id == event.event_id)
        bucket.append(event)
        bucket.sort(key=lambda item: item.occurred_at)
        if len(bucket) > self._max:
            del bucket[: len(bucket) - self._max]
        return event

    def list_for_owner(self, owner_id: str) -> list[MobileTelemetryEvent]:
        events = [
            event
            for bucket in self._events.values()
            for event in bucket
            if event.owner_id == owner_id
        ]
        return sorted(events, key=lambda event: event.occurred_at, reverse=True)

    def error_count(self, owner_id: str) -> int:
        return sum(
            1
            for event in self.list_for_owner(owner_id)
            if event.level is TelemetryLevel.ERROR
        )
