from __future__ import annotations

from dataclasses import dataclass, field

from .models import NotificationChannel


@dataclass(slots=True)
class NotificationPreferences:
    recipient_id: str
    enabled_channels: set[NotificationChannel] = field(default_factory=set)
    muted_topics: set[str] = field(default_factory=set)
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None

    def allows(self, channel: NotificationChannel, topic: str | None = None) -> bool:
        if channel not in self.enabled_channels:
            return False
        if topic and topic in self.muted_topics:
            return False
        return True


class NotificationPreferenceStore:
    def __init__(self) -> None:
        self._preferences: dict[str, NotificationPreferences] = {}

    def save(self, preferences: NotificationPreferences) -> NotificationPreferences:
        self._preferences[preferences.recipient_id] = preferences
        return preferences

    def get(self, recipient_id: str) -> NotificationPreferences | None:
        return self._preferences.get(recipient_id)
