from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


class NotificationAudience(str, Enum):
    USER = "user"
    ORGANIZATION = "organization"
    OWNER = "owner"
    INTERNAL_ROLE = "internal_role"


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DeliveryChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"
    WHATSAPP = "whatsapp"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    DELIVERED = "delivered"
    FAILED = "failed"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True, slots=True)
class NotificationTarget:
    audience: NotificationAudience
    target_id: str
    role: str | None = None


@dataclass(slots=True)
class Notification:
    topic: str
    title: str
    message: str
    target: NotificationTarget
    priority: NotificationPriority = NotificationPriority.NORMAL
    channels: tuple[DeliveryChannel, ...] = (DeliveryChannel.IN_APP,)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    notification_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: NotificationStatus = NotificationStatus.PENDING
    acknowledged_at: datetime | None = None

    def acknowledge(self) -> None:
        self.status = NotificationStatus.ACKNOWLEDGED
        self.acknowledged_at = datetime.now(timezone.utc)
