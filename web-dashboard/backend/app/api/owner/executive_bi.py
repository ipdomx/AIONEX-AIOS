"""Executive BI adapter over the shared dashboard runtime stores."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user
from app.core.identity_store import identity_store
from app.core.runtime_store import runtime_store

router = APIRouter(prefix="/owner/executive", tags=["owner-executive-bi"])

MetricStatus = Literal["good", "watch", "critical"]
InsightSeverity = Literal["info", "warning", "critical"]


class ExecutiveMetric(BaseModel):
    id: str
    label: str
    value: float
    unit: str
    trend: float
    status: MetricStatus


class ExecutiveInsight(BaseModel):
    id: str
    title: str
    summary: str
    severity: InsightSeverity
    recommendation: str


class OwnerExecutiveSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: str = Field(alias="generatedAt")
    metrics: list[ExecutiveMetric]
    insights: list[ExecutiveInsight]


def _is_super_owner(actor: UserRecord) -> bool:
    normalized = " ".join(
        actor.role.strip().lower().replace("_", " ").replace("-", " ").split()
    )
    return normalized == "super owner"


def _in_scope(organization_id: object, actor: UserRecord) -> bool:
    return _is_super_owner(actor) or str(organization_id or "") == actor.organization_id


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def build_executive_snapshot(actor: UserRecord) -> OwnerExecutiveSnapshot:
    """Build an executive view from current operational records.

    Trend values remain zero because the shared stores currently keep no historical
    KPI series. Returning zero is explicit and avoids inventing growth data.
    """

    projects = [
        row
        for row in runtime_store.projects.values()
        if not row.get("deleted") and _in_scope(row.get("organization_id"), actor)
    ]
    tasks = [
        row
        for row in runtime_store.tasks.values()
        if not row.get("deleted") and _in_scope(row.get("organization_id"), actor)
    ]
    providers = [
        row
        for row in ai_runtime.providers.values()
        if _in_scope(row.organization_id, actor)
    ]
    notifications = [
        row
        for row in ai_runtime.notifications.values()
        if _in_scope(row.organization_id, actor)
    ]
    organizations = [
        row for row in identity_store.organizations.values() if _in_scope(row.id, actor)
    ]

    active_projects = sum(
        1
        for row in projects
        if str(row.get("status") or "").lower()
        in {"active", "running", "online", "in_progress"}
    )
    completed_tasks = sum(
        1
        for row in tasks
        if str(row.get("status") or "").lower()
        in {"completed", "complete", "done", "released"}
    )
    task_completion = _percentage(completed_tasks, len(tasks))
    available_providers = sum(
        1
        for row in providers
        if row.enabled and row.status in {"connected", "active", "online"}
    )
    provider_availability = _percentage(available_providers, len(providers))
    critical_notifications = sum(
        1
        for row in notifications
        if not row.read and row.severity in {"critical", "emergency", "error"}
    )
    active_organizations = sum(
        1 for row in organizations if row.status in {"active", "online"}
    )

    metrics = [
        ExecutiveMetric(
            id="active-projects",
            label="Active projects",
            value=float(active_projects),
            unit="projects",
            trend=0,
            status="good" if active_projects else "watch",
        ),
        ExecutiveMetric(
            id="task-completion",
            label="Task completion",
            value=task_completion,
            unit="%",
            trend=0,
            status=(
                "good"
                if task_completion >= 80
                else "watch" if task_completion >= 50 else "critical"
            ),
        ),
        ExecutiveMetric(
            id="provider-availability",
            label="Provider availability",
            value=provider_availability,
            unit="%",
            trend=0,
            status=(
                "good"
                if provider_availability >= 95
                else "watch" if provider_availability >= 75 else "critical"
            ),
        ),
        ExecutiveMetric(
            id="critical-notifications",
            label="Unresolved critical notifications",
            value=float(critical_notifications),
            unit="open",
            trend=0,
            status=(
                "good"
                if critical_notifications == 0
                else "watch" if critical_notifications <= 2 else "critical"
            ),
        ),
        ExecutiveMetric(
            id="active-organizations",
            label="Active organizations",
            value=float(active_organizations),
            unit="organizations",
            trend=0,
            status="good" if active_organizations else "critical",
        ),
    ]

    recommendations = {
        "active-projects": "Review project intake and activation status.",
        "task-completion": "Review blocked and unfinished tasks before the next release gate.",
        "provider-availability": "Restore or replace unavailable AI providers.",
        "critical-notifications": "Resolve critical notifications and record the owner decision.",
        "active-organizations": "Restore an active organization before accepting new work.",
    }
    insights = [
        ExecutiveInsight(
            id=f"{metric.id}-attention",
            title=f"{metric.label} requires attention",
            summary=f"Current observed value: {metric.value:g} {metric.unit}.",
            severity="critical" if metric.status == "critical" else "warning",
            recommendation=recommendations[metric.id],
        )
        for metric in metrics
        if metric.status != "good"
    ]

    return OwnerExecutiveSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        metrics=metrics,
        insights=insights,
    )


@router.get("", response_model=OwnerExecutiveSnapshot)
def get_owner_executive_snapshot(
    actor: UserRecord = Depends(current_user),
) -> OwnerExecutiveSnapshot:
    return build_executive_snapshot(actor)
