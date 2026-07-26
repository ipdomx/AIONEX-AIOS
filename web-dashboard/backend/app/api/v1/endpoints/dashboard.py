"""Dashboard endpoints backed by live consolidated runtime state."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import runtime_store

router = APIRouter()


def _visible(collection: dict, user: UserRecord, include_deleted: bool = False):
    return [
        item
        for item in collection.values()
        if item.get("organization_id") == user.organization_id
        and (include_deleted or not item.get("deleted"))
    ]


@router.get("/stats")
async def get_dashboard_stats(user: UserRecord = Depends(current_user)):
    projects = _visible(runtime_store.projects, user)
    tasks = _visible(runtime_store.tasks, user)
    workflows = _visible(runtime_store.workflows, user)
    meetings = _visible(runtime_store.meetings, user)
    workspaces = _visible(runtime_store.workspaces, user)
    reports = _visible(runtime_store.reports, user, include_deleted=True)
    return {
        "total_workspaces": len(workspaces),
        "total_projects": len(projects),
        "active_projects": sum(1 for item in projects if item.get("status") == "active"),
        "total_tasks": len(tasks),
        "completed_tasks": sum(1 for item in tasks if item.get("status") == "done"),
        "in_progress_tasks": sum(1 for item in tasks if item.get("status") == "in_progress"),
        "todo_tasks": sum(1 for item in tasks if item.get("status") == "todo"),
        "total_workflows": len(workflows),
        "active_workflows": sum(1 for item in workflows if item.get("status") == "active"),
        "total_meetings": len(meetings),
        "pending_meetings": sum(1 for item in meetings if item.get("status") == "pending_approval"),
        "total_reports": len(reports),
        "average_project_progress": round(sum(int(item.get("progress", 0)) for item in projects) / len(projects), 2) if projects else 0,
        "activity_count": len(runtime_store.activities),
    }


@router.get("/activity")
async def get_recent_activity(limit: int = Query(20, ge=1, le=100), user: UserRecord = Depends(current_user)):
    visible_names = {item.get("name") for item in _visible(runtime_store.projects, user)}
    return [
        item
        for item in runtime_store.activities
        if item.get("user_id") == user.id or any(name and name in item.get("description", "") for name in visible_names)
    ][:limit]


@router.get("/charts")
async def get_dashboard_charts(user: UserRecord = Depends(current_user)):
    projects = _visible(runtime_store.projects, user)
    tasks = _visible(runtime_store.tasks, user)
    workflows = _visible(runtime_store.workflows, user)
    return {
        "project_status": {
            "labels": ["planning", "active", "paused", "completed"],
            "data": [sum(1 for item in projects if item.get("status") == status) for status in ["planning", "active", "paused", "completed"]],
        },
        "task_status": {
            "labels": ["todo", "in_progress", "review", "done"],
            "data": [sum(1 for item in tasks if item.get("status") == status) for status in ["todo", "in_progress", "review", "done"]],
        },
        "workflow_runs": {
            "labels": [item.get("name", item.get("id")) for item in workflows],
            "data": [int(item.get("run_count", 0)) for item in workflows],
        },
        "project_progress": {
            "labels": [item.get("name", item.get("id")) for item in projects],
            "data": [int(item.get("progress", 0)) for item in projects],
        },
    }
