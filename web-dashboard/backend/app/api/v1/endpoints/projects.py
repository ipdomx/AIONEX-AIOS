"""Projects endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter()

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    priority: str = "medium"
    workspace_id: str
    organization_id: str
    owner_id: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tags: List[str] = []

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    progress: Optional[int] = None
    end_date: Optional[datetime] = None
    tags: Optional[List[str]] = None

class ProjectResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    priority: str
    progress: int
    workspace: str
    owner: str
    team_count: int
    task_count: int
    start_date: Optional[str]
    end_date: Optional[str]
    created_at: str


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    priority: Optional[str] = None,
    workspace_id: Optional[str] = None,
    search: Optional[str] = None,
):
    """List all projects."""
    return [
        {
            "id": f"project-{i}",
            "name": f"Project {i}",
            "slug": f"project-{i}",
            "status": "active" if i % 3 == 0 else "planning",
            "priority": "high" if i % 2 == 0 else "medium",
            "progress": 25 + i * 5,
            "workspace": "Engineering",
            "owner": "Alex Chen",
            "team_count": 5 + i,
            "task_count": 20 + i * 3,
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-06-01T00:00:00Z" if i % 2 == 0 else None,
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(limit)
    ]

@router.post("", status_code=201)
async def create_project(data: ProjectCreate):
    """Create new project."""
    return {"id": "new-project-id", "message": "Project created successfully"}

@router.get("/{project_id}")
async def get_project(project_id: str):
    """Get project by ID."""
    return {
        "id": project_id,
        "name": "Data Pipeline v2",
        "slug": "data-pipeline-v2",
        "description": "Next generation data processing pipeline",
        "status": "active",
        "priority": "high",
        "progress": 67,
        "workspace": "Engineering",
        "organization": "AIONEX Corp",
        "owner": {"id": "user-1", "name": "Alex Chen"},
        "team": [
            {"id": "user-1", "name": "Alex Chen", "role": "Lead"},
            {"id": "user-2", "name": "Sarah Johnson", "role": "Engineer"},
        ],
        "tasks": {"total": 45, "completed": 30, "in_progress": 10, "todo": 5},
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-06-01T00:00:00Z",
        "tags": ["data", "pipeline", "v2"],
        "created_at": "2024-01-01T00:00:00Z",
    }

@router.put("/{project_id}")
async def update_project(project_id: str, data: ProjectUpdate):
    """Update project."""
    return {"id": project_id, "message": "Project updated successfully"}

@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """Delete project."""
    return {"message": "Project deleted successfully"}

@router.get("/{project_id}/tasks")
async def get_project_tasks(project_id: str, limit: int = 20):
    """Get project tasks."""
    return [
        {
            "id": f"task-{i}",
            "title": f"Task {i}",
            "status": "done" if i % 4 == 0 else "in_progress" if i % 3 == 0 else "todo",
            "priority": "high" if i % 2 == 0 else "medium",
            "assignee": "Alex Chen" if i % 2 == 0 else "Sarah Johnson",
            "due_date": "2024-02-01T00:00:00Z",
        }
        for i in range(limit)
    ]

@router.get("/{project_id}/activity")
async def get_project_activity(project_id: str, limit: int = 20):
    """Get project activity."""
    return [
        {
            "id": f"activity-{i}",
            "type": "commit" if i % 3 == 0 else "comment",
            "user": "Alex Chen",
            "description": f"Activity {i}",
            "timestamp": "2024-01-15T10:00:00Z",
        }
        for i in range(limit)
    ]
