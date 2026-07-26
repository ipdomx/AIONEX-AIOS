"""Tasks endpoints backed by the consolidated runtime store."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import new_id, runtime_store, utcnow

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


def _visible_tasks(user: UserRecord):
    return [task for task in runtime_store.tasks.values() if not task.get("deleted") and task.get("organization_id") == user.organization_id]


@router.get("")
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
    user: UserRecord = Depends(current_user),
):
    tasks = _visible_tasks(user)
    if status_filter:
        tasks = [item for item in tasks if item.get("status") == status_filter]
    if priority:
        tasks = [item for item in tasks if item.get("priority") == priority]
    if assignee_id:
        tasks = [item for item in tasks if item.get("assignee_id") == assignee_id]
    if project_id:
        tasks = [item for item in tasks if item.get("project_id") == project_id]
    if search:
        needle = search.lower()
        tasks = [item for item in tasks if needle in item.get("title", "").lower()]
    tasks.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return tasks[skip : skip + limit]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, user: UserRecord = Depends(current_user)):
    if data.organization_id and data.organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Organization scope violation")
    project = runtime_store.projects.get(data.project_id) if data.project_id else None
    if project and (project.get("deleted") or project.get("organization_id") != user.organization_id):
        raise HTTPException(status_code=404, detail="Project not found")
    task_id = new_id("task")
    task = {
        "id": task_id,
        "title": data.title.strip(),
        "description": data.description,
        "status": "todo",
        "priority": data.priority,
        "assignee_id": data.assignee_id or user.id,
        "assignee": user.name,
        "project_id": data.project_id,
        "project": project.get("name") if project else None,
        "workspace_id": data.workspace_id or (project.get("workspace_id") if project else None),
        "organization_id": user.organization_id,
        "due_date": data.due_date.isoformat() if data.due_date else None,
        "tags": data.tags,
        "comments": [],
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "deleted": False,
    }
    runtime_store.tasks[task_id] = task
    if project:
        project["task_count"] = sum(1 for item in runtime_store.tasks.values() if not item.get("deleted") and item.get("project_id") == project["id"])
        project["updated_at"] = utcnow()
    runtime_store.add_activity("task", "Task created", task["title"], user.id)
    return task


@router.get("/{task_id}")
async def get_task(task_id: str, user: UserRecord = Depends(current_user)):
    task = runtime_store.tasks.get(task_id)
    if not task or task.get("deleted") or task.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}")
async def update_task(task_id: str, data: TaskUpdate, user: UserRecord = Depends(current_user)):
    task = runtime_store.tasks.get(task_id)
    if not task or task.get("deleted") or task.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    updates = data.model_dump(exclude_unset=True)
    if "title" in updates:
        updates["title"] = updates["title"].strip()
    if "due_date" in updates and updates["due_date"] is not None:
        updates["due_date"] = updates["due_date"].isoformat()
    task.update(updates)
    task["updated_at"] = utcnow()
    runtime_store.add_activity("task", "Task updated", task["title"], user.id)
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str, user: UserRecord = Depends(current_user)):
    task = runtime_store.tasks.get(task_id)
    if not task or task.get("deleted") or task.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    task["deleted"] = True
    task["updated_at"] = utcnow()
    runtime_store.add_activity("task", "Task deleted", task["title"], user.id)
    return {"message": "Task deleted successfully"}
