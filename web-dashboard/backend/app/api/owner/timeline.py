"""Unified Owner timeline projected from existing runtime and audit records."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user
from app.core.identity_store import identity_store
from app.core.production_runtime import production_runtime
from app.core.runtime_store import runtime_store

router = APIRouter(prefix="/owner/timeline", tags=["owner-timeline"])

TimelineCategory = Literal[
    "project", "user", "security", "approval", "service", "incident"
]
TimelineSeverity = Literal["info", "warning", "critical"]


class OwnerTimelineEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    occurred_at: str = Field(alias="occurredAt")
    actor: str
    category: TimelineCategory
    action: str
    target: str
    severity: TimelineSeverity
    details: str


class OwnerTimeline(BaseModel):
    events: list[OwnerTimelineEvent]


def _normalized_role(role: str) -> str:
    return " ".join(role.strip().lower().replace("_", " ").replace("-", " ").split())


def _is_super_owner(actor: UserRecord) -> bool:
    return _normalized_role(actor.role) == "super owner"


def _actor_name(actor_id: object, current_actor: UserRecord) -> str:
    identifier = str(actor_id or "").strip()
    if identifier == current_actor.id:
        return current_actor.name
    identity_user = identity_store.users.get(identifier)
    if identity_user:
        return identity_user.name
    return identifier or "system"


def _category(*values: object) -> TimelineCategory:
    searchable = " ".join(str(value or "").strip().lower() for value in values)
    if any(token in searchable for token in ("security", "auth", "session", "threat")):
        return "security"
    if any(
        token in searchable
        for token in ("incident", "alert", "outage", "failure", "failover")
    ):
        return "incident"
    if any(
        token in searchable
        for token in ("approval", "approve", "reject", "release decision")
    ):
        return "approval"
    if any(
        token in searchable
        for token in (
            "user",
            "role",
            "permission",
            "organization",
            "identity",
            "staff",
        )
    ):
        return "user"
    if any(
        token in searchable for token in ("project", "task", "workflow", "workspace")
    ):
        return "project"
    return "service"


def _severity(*values: object) -> TimelineSeverity:
    searchable = " ".join(str(value or "").strip().lower() for value in values)
    if any(
        token in searchable
        for token in ("critical", "fatal", "error", "failed", "failure", "high")
    ):
        return "critical"
    if any(
        token in searchable
        for token in (
            "warning",
            "warn",
            "medium",
            "blocked",
            "rejected",
            "deactivate",
            "delete",
        )
    ):
        return "warning"
    return "info"


def _metadata_details(metadata: object, fallback: str) -> str:
    if isinstance(metadata, dict) and metadata:
        return json.dumps(metadata, sort_keys=True, default=str)
    return fallback


def _identity_event_visible(event: dict, actor: UserRecord) -> bool:
    if _is_super_owner(actor):
        return True
    metadata = event.get("metadata")
    organization_id = (
        metadata.get("organization_id") if isinstance(metadata, dict) else None
    )
    return (
        event.get("actor_user_id") == actor.id
        or organization_id == actor.organization_id
    )


def _append_runtime_events(
    events: list[OwnerTimelineEvent],
    actor: UserRecord,
) -> None:
    for event in runtime_store.activities:
        if not _is_super_owner(actor) and event.get("user_id") != actor.id:
            continue
        event_id = event.get("id")
        occurred_at = event.get("timestamp")
        if not event_id or not occurred_at:
            continue
        action = str(event.get("title") or event.get("type") or "Runtime activity")
        target = str(event.get("description") or action)
        events.append(
            OwnerTimelineEvent(
                id=f"runtime:{event_id}",
                occurred_at=str(occurred_at),
                actor=_actor_name(event.get("user_id") or event.get("user"), actor),
                category=_category(event.get("type"), action, target),
                action=action,
                target=target,
                severity=_severity(event.get("type"), action, target),
                details=str(event.get("description") or action),
            )
        )


def _append_identity_events(
    events: list[OwnerTimelineEvent],
    actor: UserRecord,
) -> None:
    for event in identity_store.audit_events:
        if not _identity_event_visible(event, actor):
            continue
        event_id = event.get("id")
        occurred_at = event.get("timestamp")
        if not event_id or not occurred_at:
            continue
        action = str(event.get("action") or "identity.change")
        resource_type = str(event.get("resource_type") or "identity")
        target = str(event.get("resource_id") or resource_type)
        events.append(
            OwnerTimelineEvent(
                id=f"identity:{event_id}",
                occurred_at=str(occurred_at),
                actor=_actor_name(event.get("actor_user_id"), actor),
                category=_category(resource_type, action),
                action=action,
                target=target,
                severity=_severity(action, resource_type),
                details=_metadata_details(
                    event.get("metadata"),
                    f"{action} {resource_type} {target}",
                ),
            )
        )


def _append_ai_events(
    events: list[OwnerTimelineEvent],
    actor: UserRecord,
) -> None:
    for job in ai_runtime.jobs.values():
        if not _is_super_owner(actor) and job.organization_id != actor.organization_id:
            continue
        occurred_at = job.completed_at or job.started_at or job.created_at
        if not job.id or not occurred_at:
            continue
        action = f"AI job {job.status}"
        events.append(
            OwnerTimelineEvent(
                id=f"ai-job:{job.id}",
                occurred_at=occurred_at,
                actor=job.agent_id,
                category="incident" if job.status == "failed" else "service",
                action=action,
                target=job.id,
                severity="critical" if job.status == "failed" else "info",
                details=job.error or job.result or job.prompt,
            )
        )

    for notification in ai_runtime.notifications.values():
        if (
            not _is_super_owner(actor)
            and notification.organization_id != actor.organization_id
        ):
            continue
        if not notification.id or not notification.created_at:
            continue
        events.append(
            OwnerTimelineEvent(
                id=f"notification:{notification.id}",
                occurred_at=notification.created_at,
                actor=_actor_name(notification.user_id, actor),
                category=_category(notification.type, notification.title),
                action=notification.title,
                target=notification.type,
                severity=_severity(notification.severity, notification.type),
                details=notification.message,
            )
        )


def _append_production_events(
    events: list[OwnerTimelineEvent],
    actor: UserRecord,
) -> None:
    if not _is_super_owner(actor):
        return

    for event in production_runtime.audit_events:
        event_id = event.get("id")
        occurred_at = event.get("timestamp")
        if not event_id or not occurred_at:
            continue
        action = str(event.get("action") or "runtime.audit")
        target = str(event.get("resource") or "runtime")
        events.append(
            OwnerTimelineEvent(
                id=f"production-audit:{event_id}",
                occurred_at=str(occurred_at),
                actor=_actor_name(event.get("actor"), actor),
                category=_category(action, target),
                action=action,
                target=target,
                severity=_severity(action, event.get("metadata")),
                details=_metadata_details(event.get("metadata"), f"{action} {target}"),
            )
        )

    for event in production_runtime.security_events:
        event_id = event.get("id")
        occurred_at = event.get("timestamp")
        if not event_id or not occurred_at:
            continue
        event_type = str(event.get("type") or "security.event")
        risk_level = event.get("risk_level")
        target = str(event.get("user_id") or event.get("ip") or "platform")
        events.append(
            OwnerTimelineEvent(
                id=f"security:{event_id}",
                occurred_at=str(occurred_at),
                actor=_actor_name(event.get("user_id"), actor),
                category="security",
                action=event_type,
                target=target,
                severity=_severity(risk_level, event.get("result")),
                details=f"Result: {event.get('result')}; risk score: {event.get('risk_score')}",
            )
        )

    for alert in production_runtime.alerts.values():
        if not alert.id or not alert.created_at:
            continue
        events.append(
            OwnerTimelineEvent(
                id=f"alert:{alert.id}",
                occurred_at=alert.created_at,
                actor=alert.source,
                category="incident",
                action=alert.title,
                target=alert.source,
                severity=_severity(alert.severity),
                details=alert.description,
            )
        )

    for log in production_runtime.logs:
        event_id = log.get("id")
        occurred_at = log.get("timestamp")
        if not event_id or not occurred_at:
            continue
        service = str(log.get("service") or "runtime")
        message = str(log.get("message") or "")
        events.append(
            OwnerTimelineEvent(
                id=f"log:{event_id}",
                occurred_at=str(occurred_at),
                actor=service,
                category=_category(log.get("level"), service, message),
                action=f"{str(log.get('level') or 'info').lower()} log",
                target=service,
                severity=_severity(log.get("level"), message),
                details=message,
            )
        )


def build_owner_timeline(actor: UserRecord) -> OwnerTimeline:
    events: list[OwnerTimelineEvent] = []
    _append_runtime_events(events, actor)
    _append_identity_events(events, actor)
    _append_ai_events(events, actor)
    _append_production_events(events, actor)
    events.sort(key=lambda event: event.occurred_at, reverse=True)
    return OwnerTimeline(events=events[:250])


@router.get("", response_model=OwnerTimeline)
def get_owner_timeline(
    actor: UserRecord = Depends(current_user),
) -> OwnerTimeline:
    return build_owner_timeline(actor)
