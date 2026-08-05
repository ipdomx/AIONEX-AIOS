from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    event_id: str
    topic: str
    owner_id: str
    payload: dict[str, object]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RealtimeHub:
    def __init__(self, *, max_events_per_topic: int = 500) -> None:
        if max_events_per_topic <= 0:
            raise ValueError("max_events_per_topic must be positive")
        self._max_events_per_topic = max_events_per_topic
        self._topics: dict[str, deque[RealtimeEvent]] = defaultdict(
            lambda: deque(maxlen=self._max_events_per_topic)
        )

    def publish(self, event: RealtimeEvent) -> RealtimeEvent:
        self._topics[event.topic].append(event)
        return event

    def read(
        self,
        *,
        owner_id: str,
        topics: Iterable[str],
        after_event_id: str | None = None,
    ) -> list[RealtimeEvent]:
        events: list[RealtimeEvent] = []
        found_cursor = after_event_id is None
        for topic in topics:
            for event in self._topics.get(topic, ()):
                if event.owner_id != owner_id:
                    continue
                if not found_cursor:
                    if event.event_id == after_event_id:
                        found_cursor = True
                    continue
                events.append(event)
        return sorted(events, key=lambda event: event.created_at)
