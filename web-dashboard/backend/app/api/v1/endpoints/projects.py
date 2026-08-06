"""Organization-scoped project endpoints backed by the relational database."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import AuditEvent, Project, Task, User, Workspace
from app.services.billing import enforce_limit
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "project"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _unique_slug(
    session: AsyncSession,
    organization_id: str,
    name: str,
    *,
    exclude_id: str | None = None,
) -> str:
    base = _slugify(name)
    candidate = base
    suffix = 2
    while True:
        statement = select(Project.id).where(
            Project.organization_id == organization_id,
            Project.slug == candidate,
        )
        if exclude_id is not None:
            statement = statement.where(Project.id != exclude_id)
        if await session.scalar(statement) is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def _serialize_project(
    project: Project,
    workspace_name: str,
    owner_name: str,
    task_count: int,
    *,
    organization_name: str,
) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "status": project.status,
        "priority": project.priority,
        "progress": project.progress,
        "workspace_id": project.workspace_id,
        "workspace": workspace_name,
        "organization_id": project.organization_id,
        "organization": organization_name,
        "owner_id": project.owner_id,
        "owner": owner_name,
        "team": [{"id": project.owner_id, "name": owner_name, "role": "Owner"}],
        "team_count": 1,
        "task_count": task_count,
        "start_date": _iso(project.start_date),
        "end_date": _iso(project.end_date),
        "tags": project.tags or [],
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
        "deleted": project.status == "deleted",
    }


async def _project_row(
    session: AsyncSession,
    project_id: str,
    organization_id: str,
    *,
    include_deleted: bool = False,
):
    task_count = (
        select(func.count(Task.id))
        .where(Task.project_id == Project.id, Task.status != "deleted")
        .correlate(Project)
        .scalar_subquery()
    )
    statement = (
        select(Project, Workspace.name, User.name, task_count)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .join(User, User.id == Project.owner_id)
        .where(
            Project.id == project_id,
            Project.organization_id == organization_id,
        )
    )
    if not include_deleted:
        statement = statement.where(Project.status != "deleted")
    return (await session.execute(statement)).one_or_none()


def _audit(
    actor: UserRecord,
    action: str,
    project: Project,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="project",
        resource_id=project.id,
        details={"name": project.name, **(details or {})},
    )


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: Optional[str] = None
    priority: str = "medium"
    workspace_id: str
    organization_id: Optional[str] = None
    owner_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    end_date: Optional[datetime] = None
    tags: Optional[List[str]] = None


@router.get("")
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    workspace_id: Optional[str] = None,
    search: Optional[str] = None,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    task_count = (
        select(func.count(Task.id))
        .where(Task.project_id == Project.id, Task.status != "deleted")
        .correlate(Project)
        .scalar_subquery()
    )
    statement = (
        select(Project, Workspace.name, User.name, task_count)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .join(User, User.id == Project.owner_id)
        .where(
            Project.organization_id == actor.organization_id,
            Project.status != "deleted",
        )
    )
    if status_filter:
        statement = statement.where(Project.status == status_filter)
    if priority:
        statement = statement.where(Project.priority == priority)
    if workspace_id:
        statement = statement.where(Project.workspace_id == workspace_id)
    if search:
        statement = statement.where(Project.name.ilike(f"%{search.strip()}%"))
    rows = (
        await session.execute(
            statement.order_by(Project.created_at.desc()).offset(skip).limit(limit)
        )
    ).all()
    return [
        _serialize_project(
            project,
            workspace_name,
            owner_name,
            int(count or 0),
            organization_name=actor.organization_name,
        )
        for project, workspace_name, owner_name, count in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    if data.organization_id and data.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Organization scope violation")
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == data.workspace_id,
            Workspace.organization_id == actor.organization_id,
            Workspace.status != "deleted",
        )
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    owner_id = data.owner_id or actor.id
    owner = await session.scalar(
        select(User).where(
            User.id == owner_id,
            User.organization_id == actor.organization_id,
            User.deleted_at.is_(None),
        )
    )
    if owner is None:
        raise HTTPException(status_code=404, detail="Project owner not found")
    current_projects = int(
        await session.scalar(
            select(func.count(Project.id)).where(
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        or 0
    )
    await enforce_limit(session, actor.organization_id, "projects", current_projects)
    project = Project(
        organization_id=actor.organization_id,
        workspace_id=workspace.id,
        owner_id=owner.id,
        name=data.name.strip(),
        slug=await _unique_slug(session, actor.organization_id, data.name),
        description=data.description,
        status="planning",
        priority=data.priority,
        progress=0,
        tags=data.tags,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    try:
        session.add(project)
        await session.flush()
        session.add(_audit(actor, "project.create", project))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="A project with this name already exists"
        ) from exc
    row = await _project_row(session, project.id, actor.organization_id)
    if row is None:
        raise HTTPException(
            status_code=500, detail="Created project could not be loaded"
        )
    stored, workspace_name, owner_name, count = row
    return _serialize_project(
        stored,
        workspace_name,
        owner_name,
        int(count or 0),
        organization_name=actor.organization_name,
    )


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _project_row(session, project_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project, workspace_name, owner_name, count = row
    detail = _serialize_project(
        project,
        workspace_name,
        owner_name,
        int(count or 0),
        organization_name=actor.organization_name,
    )
    task_statuses = (
        await session.execute(
            select(Task.status, func.count(Task.id))
            .where(Task.project_id == project.id, Task.status != "deleted")
            .group_by(Task.status)
        )
    ).all()
    counts = {task_status: int(total) for task_status, total in task_statuses}
    detail["tasks"] = {
        "total": sum(counts.values()),
        "completed": counts.get("done", 0),
        "in_progress": counts.get("in_progress", 0),
        "todo": counts.get("todo", 0),
    }
    return detail


@router.put("/{project_id}")
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _project_row(session, project_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = row[0]
    updates = data.model_dump(exclude_unset=True)
    for field in ("name", "status", "priority", "progress", "tags"):
        if field in updates and updates[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"Project {field} cannot be null",
            )
    if updates.get("status") == "deleted":
        raise HTTPException(
            status_code=422,
            detail="Use the delete endpoint to delete a project",
        )
    if "name" in updates:
        project.name = updates.pop("name").strip()
        project.slug = await _unique_slug(
            session,
            actor.organization_id,
            project.name,
            exclude_id=project.id,
        )
    for field in ("description", "status", "priority", "progress", "end_date", "tags"):
        if field in updates:
            setattr(project, field, updates[field])
    session.add(_audit(actor, "project.update", project, {"fields": sorted(updates)}))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="A project with this name already exists"
        ) from exc
    refreshed = await _project_row(session, project.id, actor.organization_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Project not found")
    stored, workspace_name, owner_name, count = refreshed
    return _serialize_project(
        stored,
        workspace_name,
        owner_name,
        int(count or 0),
        organization_name=actor.organization_name,
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _project_row(session, project_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = row[0]
    project.status = "deleted"
    session.add(_audit(actor, "project.delete", project))
    await session.commit()
    return {"message": "Project deleted successfully"}


@router.get("/{project_id}/tasks")
async def get_project_tasks(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _project_row(session, project_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = row[0]
    rows = (
        await session.execute(
            select(Task, User.name)
            .outerjoin(User, User.id == Task.assignee_id)
            .where(
                Task.project_id == project.id,
                Task.organization_id == actor.organization_id,
                Task.status != "deleted",
            )
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "assignee_id": task.assignee_id,
            "assignee": assignee_name,
            "project_id": task.project_id,
            "project": project.name,
            "workspace_id": task.workspace_id,
            "organization_id": task.organization_id,
            "due_date": _iso(task.due_date),
            "tags": task.tags or [],
            "comments": [],
            "created_at": _iso(task.created_at),
            "updated_at": _iso(task.updated_at),
            "deleted": False,
        }
        for task, assignee_name in rows
    ]


@router.get("/{project_id}/activity")
async def get_project_activity(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _project_row(session, project_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.organization_id == actor.organization_id,
                AuditEvent.resource_type == "project",
                AuditEvent.resource_id == project_id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": event.id,
            "type": "project",
            "title": event.action,
            "description": event.details.get("name", project_id),
            "user_id": event.user_id,
            "user": event.user_id,
            "timestamp": _iso(event.created_at),
        }
        for event in events
    ]
