"""Owner notification-rule projection over the live notification runtime."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.ai_runtime import NotificationRecord, ai_runtime
from app.core.auth import UserRecord, current_user

router = APIRouter(
    prefix="/owner/notification-rules",
    tags=["owner-notification-runtime"],
)

NotificationChannel = Literal["in_app", "email", "push", "whatsapp"]
NotificationSeverity = Literal["info", "warning", "critical"]


class OwnerNotificationRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    event: str
    audience: str
    channels: list[NotificationChannel]
    enabled: bool
    severity: NotificationSeverity
    updated_at: str = Field(alias="updatedAt")


class NotificationRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str | None = None
    name: str | None = None
    event: str | None = None
    audience: str | None = None
    channels: list[NotificationChannel] | None = None
    enabled: bool | None = None
    severity: NotificationSeverity | None = None
    updated_at: str | None = Field(default=None, alias="updatedAt")


def _is_super_owner(actor: UserRecord) -> bool:
    normalized = " ".join(
        actor.role.strip().lower().replace("_", " ").replace("-", " ").split()
    )
    return normalized == "super owner"


def _in_scope(notification: NotificationRecord, actor: UserRecord) -> bool:
    return (
        _is_super_owner(actor) or notification.organization_id == actor.organization_id
    )


def _severity(records: list[NotificationRecord]) -> NotificationSeverity:
    observed = {record.severity.lower() for record in records}
    if observed.intersection({"critical", "emergency", "error"}):
        return "critical"
    if observed.intersection({"warning", "action_required"}):
        return "warning"
    return "info"


def _rule_name(event: str, records: list[NotificationRecord]) -> str:
    latest_title = next(
        (record.title.strip() for record in reversed(records) if record.title.strip()),
        "",
    )
    if latest_title:
        return latest_title
    return re.sub(r"[._-]+", " ", event).strip().title()


def build_notification_rules(actor: UserRecord) -> list[OwnerNotificationRule]:
    """Aggregate only event types observed by the live notification store."""

    grouped: dict[str, list[NotificationRecord]] = defaultdict(list)
    for notification in ai_runtime.notifications.values():
        if notification.type.strip() and _in_scope(notification, actor):
            grouped[notification.type].append(notification)

    rules: list[OwnerNotificationRule] = []
    for event, records in grouped.items():
        records.sort(key=lambda item: item.created_at)
        has_direct_recipient = any(record.user_id for record in records)
        rules.append(
            OwnerNotificationRule(
                id=event,
                name=_rule_name(event, records),
                event=event,
                audience="owner, recipient" if has_direct_recipient else "owner",
                channels=["in_app"],
                enabled=True,
                severity=_severity(records),
                updated_at=records[-1].created_at,
            )
        )
    return sorted(rules, key=lambda item: item.event)


@router.get("", response_model=list[OwnerNotificationRule])
def list_notification_rules(
    actor: UserRecord = Depends(current_user),
) -> list[OwnerNotificationRule]:
    return build_notification_rules(actor)


@router.patch("/{rule_id}", response_model=OwnerNotificationRule)
def update_notification_rule(
    rule_id: str,
    update: NotificationRuleUpdate,
    actor: UserRecord = Depends(current_user),
) -> OwnerNotificationRule:
    rules = {rule.id: rule for rule in build_notification_rules(actor)}
    if rule_id not in rules:
        raise HTTPException(status_code=404, detail="Notification rule not found")
    if not update.model_fields_set:
        return rules[rule_id]
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "The current notification runtime exposes observed delivery behavior "
            "but has no mutable rule registry"
        ),
    )
