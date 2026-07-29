"""Owner realtime snapshot assembled from live AI and production runtime state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user
from app.core.production_runtime import production_runtime
from app.core.runtime_store import runtime_store

router = APIRouter(prefix="/owner/realtime", tags=["owner-realtime"])

MetricStatus = Literal["healthy", "warning", "critical"]
EventSeverity = Literal["info", "warning", "critical"]


class OwnerRealtimeMetric(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    value: float
    unit: str
    status: MetricStatus
    updated_at: str = Field(alias="updatedAt")


class OwnerRealtimeEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    message: str
    severity: EventSeverity
    created_at: str = Field(alias="createdAt")


class OwnerRealtimeSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: str = Field(alias="generatedAt")
    metrics: list[OwnerRealtimeMetric]
    events: list[OwnerRealtimeEvent]


def _normalized_role(role: str) -> str:
    return " ".join(role.strip().lower().replace("_", " ").replace("-", " ").split())


def _is_super_owner(actor: UserRecord) -> bool:
    return _normalized_role(actor.role) == "super owner"


def _count_status(value: int, *, warning: int, critical: int) -> MetricStatus:
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "healthy"


def _percent_status(value: float) -> MetricStatus:
    if value >= 90:
        return "critical"
    if value >= 75:
        return "warning"
    return "healthy"


def _latency_status(value: float) -> MetricStatus:
    if value >= 2000:
        return "critical"
    if value >= 500:
        return "warning"
    return "healthy"


def _event_severity(value: object) -> EventSeverity:
    normalized = str(value or "").strip().lower()
    if normalized in {"critical", "error", "fatal", "high"}:
        return "critical"
    if normalized in {"warning", "warn", "medium"}:
        return "warning"
    return "info"


def build_owner_realtime_snapshot(actor: UserRecord) -> OwnerRealtimeSnapshot:
    now = datetime.now(timezone.utc).isoformat()
    jobs = [
        job
        for job in ai_runtime.jobs.values()
        if _is_super_owner(actor) or job.organization_id == actor.organization_id
    ]
    agents = [
        agent
        for agent in ai_runtime.agents.values()
        if _is_super_owner(actor) or agent.organization_id == actor.organization_id
    ]
    providers = [
        provider
        for provider in ai_runtime.providers.values()
        if _is_super_owner(actor) or provider.organization_id == actor.organization_id
    ]

    active_workers = sum(
        1 for agent in agents if agent.status not in {"error", "offline", "disabled"}
    )
    queued_jobs = sum(1 for job in jobs if job.status == "queued")
    running_jobs = sum(1 for job in jobs if job.status == "running")
    failed_jobs = sum(1 for job in jobs if job.status == "failed")
    error_rate = round((failed_jobs / len(jobs)) * 100, 2) if jobs else 0.0
    average_latency = (
        round(sum(provider.latency for provider in providers) / len(providers), 2)
        if providers
        else 0.0
    )

    metrics = [
        OwnerRealtimeMetric(
            id="active-workers",
            label="Active AI workers",
            value=active_workers,
            unit="workers",
            status="healthy" if active_workers else "critical",
            updated_at=now,
        ),
        OwnerRealtimeMetric(
            id="queued-jobs",
            label="Queued AI jobs",
            value=queued_jobs,
            unit="jobs",
            status=_count_status(queued_jobs, warning=20, critical=100),
            updated_at=now,
        ),
        OwnerRealtimeMetric(
            id="running-jobs",
            label="Running AI jobs",
            value=running_jobs,
            unit="jobs",
            status="healthy",
            updated_at=now,
        ),
        OwnerRealtimeMetric(
            id="provider-latency",
            label="Provider latency",
            value=average_latency,
            unit="ms",
            status=_latency_status(average_latency),
            updated_at=max(
                (provider.last_used or provider.created_at for provider in providers),
                default=now,
            ),
        ),
        OwnerRealtimeMetric(
            id="job-error-rate",
            label="AI job error rate",
            value=error_rate,
            unit="%",
            status=(
                "critical"
                if error_rate >= 20
                else "warning" if error_rate >= 5 else "healthy"
            ),
            updated_at=now,
        ),
        OwnerRealtimeMetric(
            id="connected-clients",
            label="Realtime clients",
            value=ai_runtime.hub.connected_count(
                None if _is_super_owner(actor) else actor.organization_id
            ),
            unit="clients",
            status="healthy",
            updated_at=now,
        ),
    ]

    if _is_super_owner(actor):
        for name, samples in sorted(production_runtime.metrics.items()):
            if not samples:
                continue
            latest = samples[-1]
            value = float(latest.get("value") or 0)
            metrics.append(
                OwnerRealtimeMetric(
                    id=f"runtime-{name}",
                    label=f"Runtime {name}",
                    value=value,
                    unit="%",
                    status=_percent_status(value),
                    updated_at=str(latest.get("timestamp") or now),
                )
            )
        active_alerts = [
            alert
            for alert in production_runtime.alerts.values()
            if alert.status != "resolved"
        ]
        metrics.append(
            OwnerRealtimeMetric(
                id="active-alerts",
                label="Active production alerts",
                value=len(active_alerts),
                unit="alerts",
                status=(
                    "critical"
                    if any(alert.severity == "critical" for alert in active_alerts)
                    else "warning" if active_alerts else "healthy"
                ),
                updated_at=now,
            )
        )

    events: list[OwnerRealtimeEvent] = []
    for job in jobs:
        events.append(
            OwnerRealtimeEvent(
                id=f"ai-job:{job.id}",
                source=job.agent_id,
                message=f"AI job {job.id} is {job.status}",
                severity="critical" if job.status == "failed" else "info",
                created_at=job.completed_at or job.started_at or job.created_at,
            )
        )
    for notification in ai_runtime.notifications.values():
        if (
            not _is_super_owner(actor)
            and notification.organization_id != actor.organization_id
        ):
            continue
        events.append(
            OwnerRealtimeEvent(
                id=f"notification:{notification.id}",
                source=notification.type,
                message=notification.message,
                severity=_event_severity(notification.severity),
                created_at=notification.created_at,
            )
        )
    for activity in runtime_store.activities:
        if not _is_super_owner(actor) and activity.get("user_id") != actor.id:
            continue
        events.append(
            OwnerRealtimeEvent(
                id=f"runtime:{activity['id']}",
                source=str(activity.get("type") or "runtime"),
                message=str(activity.get("title") or activity.get("description") or ""),
                severity="info",
                created_at=str(activity.get("timestamp") or now),
            )
        )

    if _is_super_owner(actor):
        for alert in production_runtime.alerts.values():
            events.append(
                OwnerRealtimeEvent(
                    id=f"alert:{alert.id}",
                    source=alert.source,
                    message=alert.title,
                    severity=_event_severity(alert.severity),
                    created_at=alert.created_at,
                )
            )
        for log in production_runtime.logs:
            events.append(
                OwnerRealtimeEvent(
                    id=f"log:{log['id']}",
                    source=str(log.get("service") or "runtime"),
                    message=str(log.get("message") or ""),
                    severity=_event_severity(log.get("level")),
                    created_at=str(log.get("timestamp") or now),
                )
            )

    events.sort(key=lambda event: event.created_at, reverse=True)
    return OwnerRealtimeSnapshot(
        generated_at=now,
        metrics=metrics,
        events=events[:100],
    )


@router.get("", response_model=OwnerRealtimeSnapshot)
def get_owner_realtime(
    actor: UserRecord = Depends(current_user),
) -> OwnerRealtimeSnapshot:
    return build_owner_realtime_snapshot(actor)
