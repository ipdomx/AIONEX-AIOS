from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .models import DeliveryChannel, Notification, NotificationPriority, NotificationStatus


class NotificationProvider(Protocol):
    channel: DeliveryChannel

    def send(self, notification: Notification) -> str:
        """Deliver a notification and return the external delivery identifier."""


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    notification_id: str
    channel: DeliveryChannel
    external_id: str
    delivered_at: datetime


class NotificationRouter:
    def __init__(self) -> None:
        self._providers: dict[DeliveryChannel, NotificationProvider] = {}
        self._receipts: dict[str, list[DeliveryReceipt]] = defaultdict(list)

    def register(self, provider: NotificationProvider) -> None:
        self._providers[provider.channel] = provider

    def dispatch(self, notification: Notification) -> tuple[DeliveryReceipt, ...]:
        notification.status = NotificationStatus.DISPATCHING
        receipts: list[DeliveryReceipt] = []
        try:
            for channel in notification.channels:
                provider = self._providers.get(channel)
                if provider is None:
                    raise LookupError(f"No provider registered for channel: {channel.value}")
                if channel is DeliveryChannel.WHATSAPP and notification.target.audience.value != "owner":
                    raise PermissionError("WhatsApp delivery is restricted to owner notifications")
                external_id = provider.send(notification)
                receipt = DeliveryReceipt(
                    notification_id=notification.notification_id,
                    channel=channel,
                    external_id=external_id,
                    delivered_at=datetime.now(timezone.utc),
                )
                self._receipts[notification.notification_id].append(receipt)
                receipts.append(receipt)
            notification.status = NotificationStatus.DELIVERED
            return tuple(receipts)
        except Exception:
            notification.status = NotificationStatus.FAILED
            raise

    def receipts_for(self, notification_id: str) -> tuple[DeliveryReceipt, ...]:
        return tuple(self._receipts.get(notification_id, ()))


class EscalationPolicy:
    def channels_for(self, notification: Notification) -> tuple[DeliveryChannel, ...]:
        channels = list(notification.channels)
        if notification.priority is NotificationPriority.CRITICAL:
            for channel in (DeliveryChannel.IN_APP, DeliveryChannel.EMAIL, DeliveryChannel.PUSH):
                if channel not in channels:
                    channels.append(channel)
            if notification.target.audience.value == "owner" and DeliveryChannel.WHATSAPP not in channels:
                channels.append(DeliveryChannel.WHATSAPP)
        return tuple(channels)
