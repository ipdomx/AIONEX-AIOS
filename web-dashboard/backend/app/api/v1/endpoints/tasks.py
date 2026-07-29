"""Organization-scoped task endpoints backed by the relational database."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import AuditEvent, Project, Task, User, Workspace

router = APIRouter()


class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: Optional[str] = None
    priority: str = "medium"
    assignee_id: Optional[str] = None
    project_id: Optional[str] = None
    workspace_id: Optional[str] = None
    organization_id: Optional[str] = None
    due_date: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[datetime] = None
    tags: Optional[List[str]] = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_task(
    task: Task,
    assignee_name: str | None,
    project_name: str | None,
) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "assignee_id": task.assignee_id,
        "assignee": assignee_name,
        "project_id": task.project_id,
        "project": project_name,
        "workspace_id": task.workspace_id,
        "organization_id": task.organization_id,
        "due_date": _iso(task.due_date),
        "tags": task.tags or [],
        "comments": [],
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
        "deleted": task.status == "deleted",
    }


def _task_statement(organization_id: str):
    return (
        select(Task, User.name, Project.name)
        .outerjoin(
            User,
            and_(
                User.id == Task.assignee_id,
                User.organization_id == Task.organization_id,
            ),
        )
        .outerjoin(
            Project,
            and_(
                Project.id == Task.project_id,
                Project.organization_id == Task.organization_id,
            ),
        )
        .where(
            Task.organization_id == organization_id,
            Task.status != "deleted",
        )
    )


async def _task_row(
    session: AsyncSession,
    task_id: str,
    organization_id: str,
):
    return (
        await session.execute(
            _task_statement(organization_id).where(Task.id == task_id)
        )
    ).one_or_none()


async def _project(
    session: AsyncSession,
    project_id: str,
    organization_id: str,
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.organization_id == organization_id,
            Project.status != "deleted",
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _workspace(
    session: AsyncSession,
    workspace_id: str,
    organization_id: str,
) -> Workspace:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
            Workspace.status != "deleted",
        )
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def _assignee(
    session: AsyncSession,
    assignee_id: str,
    organization_id: str,
) -> User:
    assignee = await session.scalar(
        select(User).where(
            User.id == assignee_id,
            User.organization_id == organization_id,
            User.deleted_at.is_(None),
        )
    )
    if assignee is None:
        raise HTTPException(status_code=404, detail="Task assignee not found")
    return assignee


def _audit(
    actor: UserRecord,
    action: str,
    task: Task,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="task",
        resource_id=task.id,
        details={"title": task.title, **(details or {})},
    )


@router.get("")
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
    actor: UserRecord = Depends(require_permissions("tasks:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = _task_statement(actor.organization_id)
    if status_filter:
        statement = statement.where(Task.status == status_filter)
    if priority:
        statement = statement.where(Task.priority == priority)
    if assignee_id:
        statement = statement.where(Task.assignee_id == assignee_id)
    if project_id:
        statement = statement.where(Task.project_id == project_id)
    if search:
        statement = statement.where(Task.title.ilike(f"%{search.strip()}%"))
    rows = (
        await session.execute(
            statement.order_by(Task.created_at.desc()).offset(skip).limit(limit)
        )
    ).all()
    return [
        _serialize_task(task, assignee, project) for task, assignee, project in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreate,
    actor: UserRecord = Depends(require_permissions("tasks:write")),
    session: AsyncSession = Depends(get_db),
):
    normalized_title = data.title.strip()
    if len(normalized_title) < 2:
        raise HTTPException(status_code=422, detail="Task title is required")
    if data.organization_id and data.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Organization scope violation")

    project: Project | None = None
    if data.project_id:
        project = await _project(session, data.project_id, actor.organization_id)
        if data.workspace_id and data.workspace_id != project.workspace_id:
            raise HTTPException(
                status_code=422,
                detail="Task workspace does not match the selected project",
            )
    workspace_id = data.workspace_id or (project.workspace_id if project else None)
    if workspace_id:
        await _workspace(session, workspace_id, actor.organization_id)

    assignee = await _assignee(
        session,
        data.assignee_id or actor.id,
        actor.organization_id,
    )
    task = Task(
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        project_id=project.id if project else None,
        assignee_id=assignee.id,
        title=normalized_title,
        description=data.description,
        status="todo",
        priority=data.priority,
        due_date=data.due_date,
        tags=data.tags,
    )
    session.add(task)
    await session.flush()
    session.add(_audit(actor, "task.create", task))
    await session.commit()
    row = await _task_row(session, task.id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Created task could not be loaded")
    return _serialize_task(*row)


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    actor: UserRecord = Depends(require_permissions("tasks:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _task_row(session, task_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _serialize_task(*row)


@router.put("/{task_id}")
async def update_task(
    task_id: str,
    data: TaskUpdate,
    actor: UserRecord = Depends(require_permissions("tasks:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _task_row(session, task_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task = row[0]
    updates = data.model_dump(exclude_unset=True)
    changed_fields = sorted(updates)
    for field in ("title", "status", "priority", "tags"):
        if field in updates and updates[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"Task {field} cannot be null",
            )
    if updates.get("status") == "deleted":
        raise HTTPException(
            status_code=422,
            detail="Use the delete endpoint to delete a task",
        )
    if "title" in updates:
        updates["title"] = updates["title"].strip()
        if len(updates["title"]) < 2:
            raise HTTPException(status_code=422, detail="Task title is required")
    if "assignee_id" in updates and updates["assignee_id"] is not None:
        await _assignee(
            session,
            updates["assignee_id"],
            actor.organization_id,
        )
    for field in (
        "title",
        "description",
        "status",
        "priority",
        "assignee_id",
        "due_date",
        "tags",
    ):
        if field in updates:
            setattr(task, field, updates[field])
    session.add(_audit(actor, "task.update", task, {"fields": changed_fields}))
    await session.commit()
    refreshed = await _task_row(session, task.id, actor.organization_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _serialize_task(*refreshed)


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    actor: UserRecord = Depends(require_permissions("tasks:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _task_row(session, task_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task = row[0]
    task.status = "deleted"
    session.add(_audit(actor, "task.delete", task))
    await session.commit()
    return {"message": "Task deleted successfully"}
