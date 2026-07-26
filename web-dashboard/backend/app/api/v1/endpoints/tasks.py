"""Tasks endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter()

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    assignee_id: Optional[str] = None
    project_id: Optional[str] = None
    workspace_id: Optional[str] = None
    organization_id: str
    due_date: Optional[datetime] = None
    tags: List[str] = []

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[datetime] = None
    tags: Optional[List[str]] = None


@router.get("")
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
):
    """List all tasks."""
    return [
        {
            "id": f"task-{i}",
            "title": f"Task {i}",
            "status": "done" if i % 5 == 0 else "in_progress" if i % 5 == 1 else "review" if i % 5 == 2 else "todo",
            "priority": "urgent" if i % 4 == 0 else "high" if i % 4 == 1 else "medium",
            "assignee": "Alex Chen" if i % 2 == 0 else "Sarah Johnson",
            "project": "Data Pipeline v2" if i % 3 == 0 else "AI Model Training",
            "due_date": "2024-02-01T00:00:00Z",
            "tags": ["bug"] if i % 2 == 0 else ["feature"],
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(limit)
    ]

@router.post("", status_code=201)
async def create_task(data: TaskCreate):
    """Create new task."""
    return {"id": "new-task-id", "message": "Task created successfully"}

@router.get("/{task_id}")
async def get_task(task_id: str):
    """Get task by ID."""
    return {
        "id": task_id,
        "title": "Fix Authentication Bug",
        "description": "Critical bug in auth middleware",
        "status": "in_progress",
        "priority": "urgent",
        "assignee": {"id": "user-1", "name": "Alex Chen"},
        "project": {"id": "project-1", "name": "Data Pipeline v2"},
        "due_date": "2024-02-01T00:00:00Z",
        "estimated_hours": 8,
        "actual_hours": 5.5,
        "tags": ["bug", "critical", "auth"],
        "comments": [
            {"id": "comment-1", "user": "Alex Chen", "text": "Working on it", "created_at": "2024-01-15T10:00:00Z"},
        ],
        "created_at": "2024-01-01T00:00:00Z",
    }

@router.put("/{task_id}")
async def update_task(task_id: str, data: TaskUpdate):
    """Update task."""
    return {"id": task_id, "message": "Task updated successfully"}

@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """Delete task."""
    return {"message": "Task deleted successfully"}
