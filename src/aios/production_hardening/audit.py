from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    actor_id: str
    action: str
    resource: str
    outcome: str
    correlation_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, object] = field(default_factory=dict)


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> AuditEvent:
        if not event.event_id.strip() or not event.actor_id.strip():
            raise ValueError("event_id and actor_id are required")
        if not event.action.strip() or not event.resource.strip():
            raise ValueError("action and resource are required")
        if any(existing.event_id == event.event_id for existing in self._events):
            raise ValueError(f"duplicate audit event: {event.event_id}")
        self._events.append(event)
        return event

    def query(
        self,
        actor_id: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        correlation_id: str | None = None,
    ) -> list[AuditEvent]:
        events = self._events
        if actor_id is not None:
            events = [event for event in events if event.actor_id == actor_id]
        if action is not None:
            events = [event for event in events if event.action == action]
        if resource is not None:
            events = [event for event in events if event.resource == resource]
        if correlation_id is not None:
            events = [event for event in events if event.correlation_id == correlation_id]
        return list(events)

    def count(self) -> int:
        return len(self._events)
