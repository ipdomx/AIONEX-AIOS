"""Organization-scoped workspace endpoints backed by the relational database."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import AuditEvent, Project, User, Workspace
from app.services.billing import enforce_limit
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-") or "workspace"


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
        statement = select(Workspace.id).where(
            Workspace.organization_id == organization_id,
            Workspace.slug == candidate,
        )
        if exclude_id is not None:
            statement = statement.where(Workspace.id != exclude_id)
        if await session.scalar(statement) is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def _serialize(
    workspace: Workspace, project_count: int | None = None
) -> dict[str, Any]:
    item = {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "organization_id": workspace.organization_id,
        "description": workspace.description,
        "status": workspace.status,
        "created_at": _iso(workspace.created_at),
        "updated_at": _iso(workspace.updated_at),
        "deleted": workspace.status == "deleted",
    }
    if project_count is not None:
        item["project_count"] = project_count
    return item


async def _get_workspace(
    session: AsyncSession, workspace_id: str, organization_id: str
) -> Workspace | None:
    return await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
            Workspace.status != "deleted",
        )
    )


def _audit(
    actor: UserRecord,
    action: str,
    workspace: Workspace,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="workspace",
        resource_id=workspace.id,
        details={"name": workspace.name, **(details or {})},
    )


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = None
    status: Optional[str] = None


@router.get("")
async def list_workspaces(
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    rows = (
        await session.scalars(
            select(Workspace)
            .where(
                Workspace.organization_id == actor.organization_id,
                Workspace.status != "deleted",
            )
            .order_by(Workspace.created_at.desc())
        )
    ).all()
    return [_serialize(item) for item in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreate,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    current_workspaces = int(
        await session.scalar(
            select(func.count(Workspace.id)).where(
                Workspace.organization_id == actor.organization_id,
                Workspace.status != "deleted",
            )
        )
        or 0
    )
    await enforce_limit(
        session, actor.organization_id, "workspaces", current_workspaces
    )
    workspace = Workspace(
        organization_id=actor.organization_id,
        name=data.name.strip(),
        slug=await _unique_slug(session, actor.organization_id, data.name),
        description=data.description,
        status="active",
    )
    try:
        session.add(workspace)
        await session.flush()
        session.add(_audit(actor, "workspace.create", workspace))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="A workspace with this name already exists"
        ) from exc
    return _serialize(workspace)


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace(session, workspace_id, actor.organization_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    project_count = await session.scalar(
        select(func.count(Project.id)).where(
            Project.workspace_id == workspace.id,
            Project.organization_id == actor.organization_id,
            Project.status != "deleted",
        )
    )
    return _serialize(workspace, int(project_count or 0))


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    data: WorkspaceUpdate,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace(session, workspace_id, actor.organization_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    updates = data.model_dump(exclude_unset=True)
    for field in ("name", "status"):
        if field in updates and updates[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"Workspace {field} cannot be null",
            )
    if updates.get("status") == "deleted":
        raise HTTPException(
            status_code=422,
            detail="Use the delete endpoint to delete a workspace",
        )
    if "name" in updates:
        workspace.name = updates.pop("name").strip()
        workspace.slug = await _unique_slug(
            session,
            actor.organization_id,
            workspace.name,
            exclude_id=workspace.id,
        )
    for field in ("description", "status"):
        if field in updates:
            setattr(workspace, field, updates[field])
    session.add(
        _audit(actor, "workspace.update", workspace, {"fields": sorted(updates)})
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="A workspace with this name already exists"
        ) from exc
    return _serialize(workspace)


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    workspace = await _get_workspace(session, workspace_id, actor.organization_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    project_id = await session.scalar(
        select(Project.id)
        .where(
            Project.workspace_id == workspace.id,
            Project.organization_id == actor.organization_id,
            Project.status != "deleted",
        )
        .limit(1)
    )
    if project_id is not None:
        raise HTTPException(
            status_code=409, detail="Workspace contains active projects"
        )
    assigned_user_id = await session.scalar(
        select(User.id)
        .where(
            User.workspace_id == workspace.id,
            User.deleted_at.is_(None),
        )
        .limit(1)
    )
    if assigned_user_id is not None:
        raise HTTPException(
            status_code=409, detail="Workspace is assigned to active users"
        )
    workspace.status = "deleted"
    session.add(_audit(actor, "workspace.delete", workspace))
    await session.commit()
    return {"message": "Workspace deleted successfully"}
