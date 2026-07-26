"""Projects endpoints backed by the consolidated runtime store."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import new_id, runtime_store, utcnow

router = APIRouter()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or new_id("project")


def _visible_projects(user: UserRecord):
    return [
        project
        for project in runtime_store.projects.values()
        if not project.get("deleted") and project.get("organization_id") == user.organization_id
    ]


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
    user: UserRecord = Depends(current_user),
):
    projects = _visible_projects(user)
    if status_filter:
        projects = [item for item in projects if item.get("status") == status_filter]
    if priority:
        projects = [item for item in projects if item.get("priority") == priority]
    if workspace_id:
        projects = [item for item in projects if item.get("workspace_id") == workspace_id]
    if search:
        needle = search.lower()
        projects = [item for item in projects if needle in item.get("name", "").lower()]
    projects.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return projects[skip : skip + limit]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, user: UserRecord = Depends(current_user)):
    if data.organization_id and data.organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Organization scope violation")
    workspace = runtime_store.workspaces.get(data.workspace_id)
    if not workspace or workspace.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    project_id = new_id("project")
    project = {
        "id": project_id,
        "name": data.name.strip(),
        "slug": _slugify(data.name),
        "description": data.description,
        "status": "planning",
        "priority": data.priority,
        "progress": 0,
        "workspace_id": data.workspace_id,
        "workspace": workspace["name"],
        "organization_id": user.organization_id,
        "organization": user.organization_name,
        "owner_id": data.owner_id or user.id,
        "owner": user.name,
        "team": [{"id": user.id, "name": user.name, "role": user.role}],
        "team_count": 1,
        "task_count": 0,
        "start_date": data.start_date.isoformat() if data.start_date else None,
        "end_date": data.end_date.isoformat() if data.end_date else None,
        "tags": data.tags,
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "deleted": False,
    }
    runtime_store.projects[project_id] = project
    runtime_store.add_activity("project", "Project created", project["name"], user.id)
    return project


@router.get("/{project_id}")
async def get_project(project_id: str, user: UserRecord = Depends(current_user)):
    project = runtime_store.projects.get(project_id)
    if not project or project.get("deleted") or project.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    tasks = [
        task for task in runtime_store.tasks.values()
        if not task.get("deleted") and task.get("project_id") == project_id
    ]
    detail = dict(project)
    detail["tasks"] = {
        "total": len(tasks),
        "completed": sum(1 for item in tasks if item.get("status") == "done"),
        "in_progress": sum(1 for item in tasks if item.get("status") == "in_progress"),
        "todo": sum(1 for item in tasks if item.get("status") == "todo"),
    }
    return detail


@router.put("/{project_id}")
async def update_project(project_id: str, data: ProjectUpdate, user: UserRecord = Depends(current_user)):
    project = runtime_store.projects.get(project_id)
    if not project or project.get("deleted") or project.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        updates["slug"] = _slugify(updates["name"])
    if "end_date" in updates and updates["end_date"] is not None:
        updates["end_date"] = updates["end_date"].isoformat()
    project.update(updates)
    project["updated_at"] = utcnow()
    runtime_store.add_activity("project", "Project updated", project["name"], user.id)
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: str, user: UserRecord = Depends(current_user)):
    project = runtime_store.projects.get(project_id)
    if not project or project.get("deleted") or project.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    project["deleted"] = True
    project["updated_at"] = utcnow()
    runtime_store.add_activity("project", "Project deleted", project["name"], user.id)
    return {"message": "Project deleted successfully"}


@router.get("/{project_id}/tasks")
async def get_project_tasks(project_id: str, limit: int = Query(20, ge=1, le=100), user: UserRecord = Depends(current_user)):
    await get_project(project_id, user)
    tasks = [
        task for task in runtime_store.tasks.values()
        if not task.get("deleted") and task.get("project_id") == project_id
    ]
    return tasks[:limit]


@router.get("/{project_id}/activity")
async def get_project_activity(project_id: str, limit: int = Query(20, ge=1, le=100), user: UserRecord = Depends(current_user)):
    project = await get_project(project_id, user)
    return [
        item for item in runtime_store.activities
        if project["name"] in item.get("description", "") or project_id in item.get("description", "")
    ][:limit]
