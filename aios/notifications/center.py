from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .models import Notification, NotificationAudience, NotificationPriority, NotificationTarget
from .router import EscalationPolicy, NotificationRouter


@dataclass(slots=True)
class NotificationCenter:
    router: NotificationRouter
    escalation_policy: EscalationPolicy = field(default_factory=EscalationPolicy)
    _notifications: dict[str, Notification] = field(default_factory=dict)

    def publish(self, notification: Notification) -> Notification:
        notification.channels = self.escalation_policy.channels_for(notification)
        self._notifications[notification.notification_id] = notification
        self.router.dispatch(notification)
        return notification

    def create(
        self,
        *,
        topic: str,
        title: str,
        message: str,
        target: NotificationTarget,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        channels: tuple = (),
        metadata: dict | None = None,
    ) -> Notification:
        notification = Notification(
            topic=topic,
            title=title,
            message=message,
            target=target,
            priority=priority,
            channels=channels or Notification.__dataclass_fields__["channels"].default,
            metadata=metadata or {},
        )
        return self.publish(notification)

    def get(self, notification_id: str) -> Notification:
        return self._notifications[notification_id]

    def for_target(self, target_id: str) -> tuple[Notification, ...]:
        return tuple(
            item for item in self._notifications.values() if item.target.target_id == target_id
        )

    def owner_event(
        self,
        *,
        owner_id: str,
        topic: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.HIGH,
        metadata: dict | None = None,
    ) -> Notification:
        return self.create(
            topic=topic,
            title=title,
            message=message,
            target=NotificationTarget(NotificationAudience.OWNER, owner_id),
            priority=priority,
            metadata=metadata,
        )

    def unresolved(self) -> tuple[Notification, ...]:
        return tuple(
            item
            for item in self._notifications.values()
            if item.acknowledged_at is None
        )
