from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class MobileNotification:
    notification_id: str
    user_id: str
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    project_id: str | None = None
    category: str = "general"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, str] = field(default_factory=dict)


class MobileNotificationCenter:
    def __init__(self) -> None:
        self._notifications: dict[str, MobileNotification] = {}
        self._read: set[str] = set()

    def publish(self, notification: MobileNotification) -> MobileNotification:
        if not notification.notification_id.strip():
            raise ValueError("notification_id is required")
        if not notification.user_id.strip() or not notification.title.strip():
            raise ValueError("user_id and title are required")
        self._notifications[notification.notification_id] = notification
        return notification

    def mark_read(self, notification_id: str) -> None:
        if notification_id not in self._notifications:
            raise LookupError(f"notification not found: {notification_id}")
        self._read.add(notification_id)

    def list_for_user(self, user_id: str, unread_only: bool = False) -> list[MobileNotification]:
        items = [item for item in self._notifications.values() if item.user_id == user_id]
        if unread_only:
            items = [item for item in items if item.notification_id not in self._read]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def unread_count(self, user_id: str) -> int:
        return len(self.list_for_user(user_id, unread_only=True))
