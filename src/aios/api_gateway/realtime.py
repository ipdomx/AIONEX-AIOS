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
        for retained in self._topics.values():
            for existing in retained:
                if (
                    existing.owner_id == event.owner_id
                    and existing.event_id == event.event_id
                ):
                    return existing
        self._topics[event.topic].append(event)
        return event

    def read(
        self,
        *,
        owner_id: str,
        topics: Iterable[str],
        after_event_id: str | None = None,
    ) -> list[RealtimeEvent]:
        events = sorted(
            (
                event
                for topic in topics
                for event in self._topics.get(topic, ())
                if event.owner_id == owner_id
            ),
            key=lambda event: (event.created_at, event.event_id),
        )
        if after_event_id is None:
            return events

        for index, event in enumerate(events):
            if event.event_id == after_event_id:
                return events[index + 1 :]
        return []
