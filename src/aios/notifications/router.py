from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .models import (
    Audience,
    Channel,
    DeliveryChannel,
    DeliveryNotification,
    Notification,
    NotificationPriority,
    NotificationStatus,
    Preference,
    Severity,
)


class NotificationPolicyError(PermissionError):
    pass


class NotificationProvider(Protocol):
    channel: DeliveryChannel

    def send(self, notification: DeliveryNotification) -> str:
        """Deliver a notification and return the external delivery identifier."""


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    notification_id: str
    channel: DeliveryChannel
    external_id: str
    delivered_at: datetime


class NotificationRouter:
    """Unified router for consent-aware routing and provider-backed delivery."""

    def __init__(self, owner_id: str | None = None) -> None:
        self.owner_id = owner_id
        self.preferences: dict[str, Preference] = {}
        self.outbox: dict[Channel, list[Notification]] = defaultdict(list)
        self.audit: list[dict[str, object]] = []
        self._providers: dict[DeliveryChannel, NotificationProvider] = {}
        self._receipts: dict[str, list[DeliveryReceipt]] = defaultdict(list)

    # Modern consent-aware routing API.
    def set_preference(self, preference: Preference) -> None:
        self.preferences[preference.recipient_id] = preference

    def _channels(self, notification: Notification) -> set[Channel]:
        preference = self.preferences.get(
            notification.recipient_id,
            Preference(notification.recipient_id, {Channel.IN_APP}),
        )
        channels = set(preference.allowed_channels)
        if not preference.push_consent:
            channels.discard(Channel.PUSH)
        if Channel.WHATSAPP in channels and (
            notification.audience != Audience.OWNER
            or notification.recipient_id != self.owner_id
        ):
            channels.discard(Channel.WHATSAPP)
        if (
            notification.severity in {Severity.CRITICAL, Severity.EMERGENCY}
            and notification.audience == Audience.OWNER
        ):
            channels.update({Channel.IN_APP, Channel.EMAIL, Channel.BOT})
            if notification.recipient_id == self.owner_id:
                channels.add(Channel.WHATSAPP)
        return channels

    def route(self, notification: Notification) -> tuple[Channel, ...]:
        if (
            notification.audience == Audience.OWNER
            and notification.recipient_id != self.owner_id
        ):
            raise NotificationPolicyError("owner-audience-recipient-mismatch")
        channels = tuple(sorted(self._channels(notification), key=lambda item: item.value))
        for channel in channels:
            self.outbox[channel].append(notification)
        self.audit.append(
            {
                "notification_id": notification.notification_id,
                "recipient": notification.recipient_id,
                "channels": [item.value for item in channels],
                "severity": notification.severity.value,
            }
        )
        return channels

    # Provider-backed compatibility API.
    def register(self, provider: NotificationProvider) -> None:
        self._providers[provider.channel] = provider

    def dispatch(
        self, notification: DeliveryNotification
    ) -> tuple[DeliveryReceipt, ...]:
        notification.status = NotificationStatus.DISPATCHING
        receipts: list[DeliveryReceipt] = []
        try:
            for channel in notification.channels:
                provider = self._providers.get(channel)
                if provider is None:
                    raise LookupError(
                        f"No provider registered for channel: {channel.value}"
                    )
                if (
                    channel is DeliveryChannel.WHATSAPP
                    and notification.target.audience.value != "owner"
                ):
                    raise PermissionError(
                        "WhatsApp delivery is restricted to owner notifications"
                    )
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
    def channels_for(
        self, notification: DeliveryNotification
    ) -> tuple[DeliveryChannel, ...]:
        channels = list(notification.channels)
        if notification.priority is NotificationPriority.CRITICAL:
            for channel in (
                DeliveryChannel.IN_APP,
                DeliveryChannel.EMAIL,
                DeliveryChannel.PUSH,
            ):
                if channel not in channels:
                    channels.append(channel)
            if (
                notification.target.audience.value == "owner"
                and DeliveryChannel.WHATSAPP not in channels
            ):
                channels.append(DeliveryChannel.WHATSAPP)
        return tuple(channels)
