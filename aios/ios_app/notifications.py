from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class IOSNotification:
    notification_id: str
    owner_id: str
    title: str
    body: str
    topic: str
    read: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IOSNotificationCenter:
    def __init__(self) -> None:
        self._notifications: dict[str, IOSNotification] = {}

    def publish(self, notification: IOSNotification) -> IOSNotification:
        if notification.notification_id in self._notifications:
            raise ValueError("duplicate notification")
        self._notifications[notification.notification_id] = notification
        return notification

    def list_for_owner(self, owner_id: str, *, unread_only: bool = False) -> list[IOSNotification]:
        result = [n for n in self._notifications.values() if n.owner_id == owner_id]
        if unread_only:
            result = [n for n in result if not n.read]
        return sorted(result, key=lambda n: n.created_at, reverse=True)

    def mark_read(self, notification_id: str, owner_id: str) -> IOSNotification:
        notification = self._notifications[notification_id]
        if notification.owner_id != owner_id:
            raise PermissionError("notification belongs to another owner")
        notification.read = True
        return notification
