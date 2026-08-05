from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .domain import MissionControlSnapshot


def build_owner_overview(snapshot: MissionControlSnapshot) -> dict[str, Any]:
    total_projects = len(snapshot.projects)
    failed_projects = sum(1 for project in snapshot.projects if project.failed_tasks > 0)
    blocked_projects = sum(1 for project in snapshot.projects if project.blocked_tasks > 0)
    critical_incidents = sum(1 for incident in snapshot.incidents if incident.severity == "critical")
    open_incidents = sum(1 for incident in snapshot.incidents if incident.status not in {"resolved", "closed"})
    total_cost_minor = sum(project.cost_minor for project in snapshot.projects)
    risk_average = (
        sum(project.risk_score for project in snapshot.projects) / total_projects
        if total_projects
        else 0.0
    )
    progress_average = (
        sum(project.progress_percent for project in snapshot.projects) / total_projects
        if total_projects
        else 0.0
    )

    return {
        "generated_at": snapshot.generated_at.isoformat(),
        "summary": {
            "projects": total_projects,
            "failed_projects": failed_projects,
            "blocked_projects": blocked_projects,
            "open_incidents": open_incidents,
            "critical_incidents": critical_incidents,
            "pending_approvals": len(snapshot.pending_approvals),
            "active_workers": snapshot.active_workers,
            "unhealthy_workers": snapshot.unhealthy_workers,
            "queued_tasks": snapshot.queued_tasks,
            "running_tasks": snapshot.running_tasks,
            "completed_tasks_24h": snapshot.completed_tasks_24h,
            "failed_tasks_24h": snapshot.failed_tasks_24h,
            "project_progress_average": round(progress_average, 2),
            "project_risk_average": round(risk_average, 3),
            "total_cost_minor": total_cost_minor,
        },
        "projects": [asdict(project) for project in snapshot.projects],
        "incidents": [asdict(incident) for incident in snapshot.incidents],
        "approvals": [asdict(approval) for approval in snapshot.pending_approvals],
    }
