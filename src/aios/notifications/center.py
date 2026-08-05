from __future__ import annotations

import json
from pathlib import Path

from .models import (
    Audience,
    Channel,
    DeliveryChannel,
    DeliveryNotification,
    Notification,
    NotificationAudience,
    NotificationPriority,
    NotificationTarget,
    Severity,
)
from .router import EscalationPolicy, NotificationRouter


class NotificationCenter:
    """Unified notification center preserving both public API generations."""

    def __init__(
        self,
        router_or_owner: NotificationRouter | str,
        audit_path: str | Path | None = None,
        escalation_policy: EscalationPolicy | None = None,
    ) -> None:
        self._notifications: dict[str, DeliveryNotification] = {}
        if isinstance(router_or_owner, NotificationRouter):
            self.owner_id: str | None = router_or_owner.owner_id
            self.router = router_or_owner
            self.audit_path: Path | None = None
            self.escalation_policy = escalation_policy or EscalationPolicy()
            self._mode = "provider"
        else:
            self.owner_id = str(router_or_owner)
            self.router = NotificationRouter(self.owner_id)
            self.audit_path = Path(audit_path) if audit_path is not None else None
            if self.audit_path is not None:
                self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            self.escalation_policy = escalation_policy or EscalationPolicy()
            self._mode = "policy"

    # Consent-aware runtime API.
    def configure(
        self,
        recipient_id: str,
        channels: set[Channel],
        push_consent: bool = False,
    ) -> None:
        from .models import Preference

        self.router.set_preference(
            Preference(recipient_id, channels, push_consent)
        )

    def notify(self, notification: Notification) -> tuple[Channel, ...]:
        channels = self.router.route(notification)
        if self.audit_path is not None:
            record = {
                "id": notification.notification_id,
                "tenant": notification.tenant_id,
                "audience": notification.audience.value,
                "recipient": notification.recipient_id,
                "project": notification.project_id,
                "subject": notification.subject,
                "severity": notification.severity.value,
                "channels": [item.value for item in channels],
            }
            with self.audit_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return channels

    def project_question(
        self,
        tenant_id: str,
        user_id: str,
        project_id: str,
        question: str,
    ) -> tuple[Channel, ...]:
        return self.notify(
            Notification(
                tenant_id,
                Audience.USER,
                user_id,
                "Project input required",
                question,
                Severity.ACTION_REQUIRED,
                project_id,
            )
        )

    def workforce_event(
        self,
        tenant_id: str,
        recipient_id: str,
        subject: str,
        body: str,
        project_id: str | None = None,
    ) -> tuple[Channel, ...]:
        channels = self.notify(
            Notification(
                tenant_id,
                Audience.WORKFORCE,
                recipient_id,
                subject,
                body,
                Severity.INFO,
                project_id,
            )
        )
        self._owner_runtime_event(
            tenant_id,
            f"Workforce activity: {subject}",
            f"{recipient_id}: {body}",
            Severity.INFO,
            project_id,
        )
        return channels

    def _owner_runtime_event(
        self,
        tenant_id: str,
        subject: str,
        body: str,
        severity: Severity = Severity.INFO,
        project_id: str | None = None,
    ) -> tuple[Channel, ...]:
        if self.owner_id is None:
            raise RuntimeError("runtime owner ID is not configured")
        return self.notify(
            Notification(
                tenant_id,
                Audience.OWNER,
                self.owner_id,
                subject,
                body,
                severity,
                project_id,
            )
        )

    # Provider-backed Phase 11 compatibility API.
    def publish(self, notification: DeliveryNotification) -> DeliveryNotification:
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
        channels: tuple[DeliveryChannel, ...] = (),
        metadata: dict | None = None,
    ) -> DeliveryNotification:
        notification = DeliveryNotification(
            topic=topic,
            title=title,
            message=message,
            target=target,
            priority=priority,
            channels=channels or (DeliveryChannel.IN_APP,),
            metadata=metadata or {},
        )
        return self.publish(notification)

    def get(self, notification_id: str) -> DeliveryNotification:
        return self._notifications[notification_id]

    def for_target(self, target_id: str) -> tuple[DeliveryNotification, ...]:
        return tuple(
            item
            for item in self._notifications.values()
            if item.target.target_id == target_id
        )

    def unresolved(self) -> tuple[DeliveryNotification, ...]:
        return tuple(
            item
            for item in self._notifications.values()
            if item.acknowledged_at is None
        )

    def owner_event(self, *args, **kwargs):
        """Dispatch either the runtime or provider-backed owner-event contract."""
        if "owner_id" in kwargs or "topic" in kwargs or "title" in kwargs:
            owner_id = str(kwargs.pop("owner_id"))
            topic = str(kwargs.pop("topic"))
            title = str(kwargs.pop("title"))
            message = str(kwargs.pop("message"))
            priority = kwargs.pop("priority", NotificationPriority.HIGH)
            metadata = kwargs.pop("metadata", None)
            if kwargs:
                raise TypeError(f"unexpected owner_event arguments: {sorted(kwargs)}")
            return self.create(
                topic=topic,
                title=title,
                message=message,
                target=NotificationTarget(NotificationAudience.OWNER, owner_id),
                priority=priority,
                metadata=metadata,
            )
        return self._owner_runtime_event(*args, **kwargs)
