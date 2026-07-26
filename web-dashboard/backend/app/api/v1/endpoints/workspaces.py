"""Workspace endpoints backed by the consolidated runtime store."""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import new_id, runtime_store, utcnow

router = APIRouter()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-") or new_id("workspace")


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = None
    status: Optional[str] = None


@router.get("")
async def list_workspaces(user: UserRecord = Depends(current_user)):
    return [item for item in runtime_store.workspaces.values() if item.get("organization_id") == user.organization_id and not item.get("deleted")]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(data: WorkspaceCreate, user: UserRecord = Depends(current_user)):
    workspace_id = new_id("workspace")
    workspace = {
        "id": workspace_id,
        "name": data.name.strip(),
        "slug": _slugify(data.name),
        "organization_id": user.organization_id,
        "description": data.description,
        "status": "active",
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "deleted": False,
    }
    runtime_store.workspaces[workspace_id] = workspace
    runtime_store.add_activity("workspace", "Workspace created", workspace["name"], user.id)
    return workspace


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str, user: UserRecord = Depends(current_user)):
    workspace = runtime_store.workspaces.get(workspace_id)
    if not workspace or workspace.get("deleted") or workspace.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    result = dict(workspace)
    result["project_count"] = sum(1 for item in runtime_store.projects.values() if not item.get("deleted") and item.get("workspace_id") == workspace_id)
    return result


@router.put("/{workspace_id}")
async def update_workspace(workspace_id: str, data: WorkspaceUpdate, user: UserRecord = Depends(current_user)):
    workspace = await get_workspace(workspace_id, user)
    source = runtime_store.workspaces[workspace_id]
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        updates["slug"] = _slugify(updates["name"])
    source.update(updates)
    source["updated_at"] = utcnow()
    return source


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: str, user: UserRecord = Depends(current_user)):
    await get_workspace(workspace_id, user)
    if any(not item.get("deleted") and item.get("workspace_id") == workspace_id for item in runtime_store.projects.values()):
        raise HTTPException(status_code=409, detail="Workspace contains active projects")
    runtime_store.workspaces[workspace_id]["deleted"] = True
    runtime_store.workspaces[workspace_id]["updated_at"] = utcnow()
    return {"message": "Workspace deleted successfully"}
