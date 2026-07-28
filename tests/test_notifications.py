from __future__ import annotations

from dataclasses import dataclass

import pytest

from aios.notifications import (
    DeliveryChannel,
    NotificationAudience,
    NotificationCenter,
    NotificationPriority,
    NotificationRouter,
    NotificationTarget,
)


@dataclass
class FakeProvider:
    channel: DeliveryChannel

    def send(self, notification):
        return f"{self.channel.value}:{notification.notification_id}"


def build_center() -> NotificationCenter:
    router = NotificationRouter()
    for channel in DeliveryChannel:
        router.register(FakeProvider(channel))
    return NotificationCenter(router)


def test_user_notification_is_delivered():
    center = build_center()
    item = center.create(
        topic="project.completed",
        title="Project completed",
        message="Your project is ready.",
        target=NotificationTarget(NotificationAudience.USER, "user-1"),
    )
    assert item.status.value == "delivered"
    assert center.for_target("user-1") == (item,)


def test_critical_owner_notification_escalates_to_all_owner_channels():
    center = build_center()
    item = center.owner_event(
        owner_id="owner-1",
        topic="incident.critical",
        title="Critical incident",
        message="Immediate action is required.",
        priority=NotificationPriority.CRITICAL,
    )
    assert DeliveryChannel.WHATSAPP in item.channels
    assert DeliveryChannel.EMAIL in item.channels
    assert DeliveryChannel.PUSH in item.channels


def test_whatsapp_is_restricted_to_owner():
    center = build_center()
    with pytest.raises(PermissionError):
        center.create(
            topic="project.update",
            title="Update",
            message="Progress updated.",
            target=NotificationTarget(NotificationAudience.USER, "user-1"),
            channels=(DeliveryChannel.WHATSAPP,),
        )


def test_acknowledgement_removes_notification_from_unresolved():
    center = build_center()
    item = center.create(
        topic="clarification.required",
        title="Clarification required",
        message="Please answer the open question.",
        target=NotificationTarget(NotificationAudience.ORGANIZATION, "org-1"),
    )
    assert item in center.unresolved()
    item.acknowledge()
    assert item not in center.unresolved()
