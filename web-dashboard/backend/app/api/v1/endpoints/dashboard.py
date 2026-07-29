"""Dashboard endpoints backed by organization-scoped relational state."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user, require_permissions
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Meeting,
    Project,
    Report,
    Task,
    User,
    Workflow,
    Workspace,
)

router = APIRouter()


async def _count(session: AsyncSession, model_id, *criteria) -> int:
    value = await session.scalar(select(func.count(model_id)).where(*criteria))
    return int(value or 0)


def _activity_item(event: AuditEvent, user_name: str | None) -> dict[str, Any]:
    details = event.details or {}
    description = next(
        (
            str(details[key])
            for key in ("description", "name", "title", "message")
            if details.get(key)
        ),
        (f"{event.resource_type or 'resource'} " f"{event.resource_id or ''}").strip(),
    )
    return {
        "id": event.id,
        "type": event.resource_type or event.action.split(".", 1)[0],
        "title": event.action.replace(".", " ").replace("_", " ").title(),
        "description": description,
        "user_id": event.user_id,
        "user": user_name or event.user_id,
        "timestamp": event.created_at.isoformat(),
    }


@router.get("/stats")
async def get_dashboard_stats(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    organization_id = actor.organization_id
    project_scope = (
        Project.organization_id == organization_id,
        Project.status != "deleted",
    )
    task_scope = (
        Task.organization_id == organization_id,
        Task.status != "deleted",
    )
    workflow_scope = (
        Workflow.organization_id == organization_id,
        Workflow.status != "deleted",
    )
    meeting_scope = (
        Meeting.organization_id == organization_id,
        Meeting.status != "deleted",
    )
    average_progress = await session.scalar(
        select(func.avg(Project.progress)).where(*project_scope)
    )
    return {
        "total_workspaces": await _count(
            session,
            Workspace.id,
            Workspace.organization_id == organization_id,
            Workspace.status != "deleted",
        ),
        "total_projects": await _count(session, Project.id, *project_scope),
        "active_projects": await _count(
            session,
            Project.id,
            *project_scope,
            Project.status == "active",
        ),
        "total_tasks": await _count(session, Task.id, *task_scope),
        "completed_tasks": await _count(
            session,
            Task.id,
            *task_scope,
            Task.status == "done",
        ),
        "in_progress_tasks": await _count(
            session,
            Task.id,
            *task_scope,
            Task.status == "in_progress",
        ),
        "todo_tasks": await _count(
            session,
            Task.id,
            *task_scope,
            Task.status == "todo",
        ),
        "total_workflows": await _count(
            session,
            Workflow.id,
            *workflow_scope,
        ),
        "active_workflows": await _count(
            session,
            Workflow.id,
            *workflow_scope,
            Workflow.status == "active",
        ),
        "total_meetings": await _count(session, Meeting.id, *meeting_scope),
        "pending_meetings": await _count(
            session,
            Meeting.id,
            *meeting_scope,
            Meeting.status == "pending_approval",
        ),
        "total_reports": await _count(
            session,
            Report.id,
            Report.organization_id == organization_id,
        ),
        "average_project_progress": (
            round(float(average_progress), 2) if average_progress is not None else 0
        ),
        "activity_count": await _count(
            session,
            AuditEvent.id,
            AuditEvent.organization_id == organization_id,
        ),
    }


@router.get("/activity")
async def get_recent_activity(
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("audit:read")),
    session: AsyncSession = Depends(get_db),
):
    rows = (
        await session.execute(
            select(AuditEvent, User.name)
            .outerjoin(User, User.id == AuditEvent.user_id)
            .where(AuditEvent.organization_id == actor.organization_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_activity_item(event, user_name) for event, user_name in rows]


@router.get("/charts")
async def get_dashboard_charts(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    project_statuses = (
        await session.execute(
            select(Project.status, func.count(Project.id))
            .where(
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
            .group_by(Project.status)
        )
    ).all()
    task_statuses = (
        await session.execute(
            select(Task.status, func.count(Task.id))
            .where(
                Task.organization_id == actor.organization_id,
                Task.status != "deleted",
            )
            .group_by(Task.status)
        )
    ).all()
    workflows = (
        await session.scalars(
            select(Workflow)
            .where(
                Workflow.organization_id == actor.organization_id,
                Workflow.status != "deleted",
            )
            .order_by(Workflow.created_at)
        )
    ).all()
    projects = (
        await session.scalars(
            select(Project)
            .where(
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
            .order_by(Project.created_at)
        )
    ).all()
    project_counts = {
        item_status: int(total) for item_status, total in project_statuses
    }
    task_counts = {item_status: int(total) for item_status, total in task_statuses}
    project_labels = ["planning", "active", "paused", "completed"]
    task_labels = ["todo", "in_progress", "review", "done"]
    return {
        "project_status": {
            "labels": project_labels,
            "data": [
                project_counts.get(item_status, 0) for item_status in project_labels
            ],
        },
        "task_status": {
            "labels": task_labels,
            "data": [task_counts.get(item_status, 0) for item_status in task_labels],
        },
        "workflow_runs": {
            "labels": [workflow.name for workflow in workflows],
            "data": [workflow.run_count for workflow in workflows],
        },
        "project_progress": {
            "labels": [project.name for project in projects],
            "data": [project.progress for project in projects],
        },
    }
