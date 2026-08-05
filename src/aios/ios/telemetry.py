from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class IOSTelemetryEvent:
    event_id: str
    owner_id: str
    device_id: str
    name: str
    attributes: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IOSTelemetryService:
    def __init__(self) -> None:
        self._events: dict[str, IOSTelemetryEvent] = {}

    def record(self, event: IOSTelemetryEvent) -> IOSTelemetryEvent:
        if event.event_id in self._events:
            raise ValueError(f"duplicate telemetry event: {event.event_id}")
        self._events[event.event_id] = event
        return event

    def list_for_owner(self, owner_id: str, *, device_id: str | None = None) -> list[IOSTelemetryEvent]:
        events = [event for event in self._events.values() if event.owner_id == owner_id]
        if device_id is not None:
            events = [event for event in events if event.device_id == device_id]
        return sorted(events, key=lambda event: event.created_at)

    def get(self, event_id: str, owner_id: str) -> IOSTelemetryEvent:
        event = self._events[event_id]
        if event.owner_id != owner_id:
            raise PermissionError("telemetry event is not owned by this owner")
        return event
