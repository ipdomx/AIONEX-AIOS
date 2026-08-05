from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class Severity(StrEnum):
    INFO = "info"
    ACTION_REQUIRED = "action_required"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class Channel(StrEnum):
    IN_APP = "in_app"
    PUSH = "push"
    BOT = "bot"
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class Audience(StrEnum):
    USER = "user"
    ORGANIZATION = "organization"
    WORKFORCE = "workforce"
    OWNER = "owner"


@dataclass(slots=True, frozen=True)
class Notification:
    tenant_id: str
    audience: Audience
    recipient_id: str
    subject: str
    body: str
    severity: Severity = Severity.INFO
    project_id: str | None = None
    action_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    notification_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(slots=True)
class Preference:
    recipient_id: str
    allowed_channels: set[Channel]
    push_consent: bool = False
    quiet_hours: tuple[int, int] | None = None


# Compatibility contract retained for the Phase 11 delivery-provider API.
class NotificationAudience(StrEnum):
    USER = "user"
    ORGANIZATION = "organization"
    OWNER = "owner"
    INTERNAL_ROLE = "internal_role"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DeliveryChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"
    WHATSAPP = "whatsapp"


# Later Phase 11 batches used this public name for the same channel set.
NotificationChannel = DeliveryChannel


class NotificationStatus(StrEnum):
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
class DeliveryNotification:
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
