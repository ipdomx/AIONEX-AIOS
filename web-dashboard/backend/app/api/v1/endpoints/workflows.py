"""Workflow endpoints backed by the consolidated runtime store."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import new_id, runtime_store, utcnow

router = APIRouter()


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    trigger: str = "manual"
    steps: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = None
    status: Optional[str] = None
    trigger: Optional[str] = None
    steps: Optional[list[dict[str, Any]]] = None


def _visible(user: UserRecord):
    return [item for item in runtime_store.workflows.values() if not item.get("deleted") and item.get("organization_id") == user.organization_id]


@router.get("")
async def list_workflows(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    project_id: Optional[str] = None,
    user: UserRecord = Depends(current_user),
):
    workflows = _visible(user)
    if status_filter:
        workflows = [item for item in workflows if item.get("status") == status_filter]
    if project_id:
        workflows = [item for item in workflows if item.get("project_id") == project_id]
    workflows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return workflows[skip : skip + limit]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(data: WorkflowCreate, user: UserRecord = Depends(current_user)):
    if data.project_id:
        project = runtime_store.projects.get(data.project_id)
        if not project or project.get("deleted") or project.get("organization_id") != user.organization_id:
            raise HTTPException(status_code=404, detail="Project not found")
    workflow_id = new_id("workflow")
    workflow = {
        "id": workflow_id,
        "name": data.name.strip(),
        "description": data.description,
        "status": "draft",
        "organization_id": user.organization_id,
        "workspace_id": data.workspace_id,
        "project_id": data.project_id,
        "trigger": data.trigger,
        "steps": data.steps,
        "run_count": 0,
        "last_run_at": None,
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "deleted": False,
    }
    runtime_store.workflows[workflow_id] = workflow
    runtime_store.add_activity("workflow", "Workflow created", workflow["name"], user.id)
    return workflow


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, user: UserRecord = Depends(current_user)):
    workflow = runtime_store.workflows.get(workflow_id)
    if not workflow or workflow.get("deleted") or workflow.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: str, data: WorkflowUpdate, user: UserRecord = Depends(current_user)):
    workflow = await get_workflow(workflow_id, user)
    source = runtime_store.workflows[workflow_id]
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
    source.update(updates)
    source["updated_at"] = utcnow()
    runtime_store.add_activity("workflow", "Workflow updated", source["name"], user.id)
    return source


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: str, user: UserRecord = Depends(current_user)):
    workflow = await get_workflow(workflow_id, user)
    workflow["run_count"] = int(workflow.get("run_count", 0)) + 1
    workflow["last_run_at"] = utcnow()
    workflow["status"] = "active"
    workflow["updated_at"] = utcnow()
    runtime_store.add_activity("workflow", "Workflow executed", workflow["name"], user.id)
    return {"workflow": workflow, "run_id": new_id("run"), "status": "accepted"}


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str, user: UserRecord = Depends(current_user)):
    await get_workflow(workflow_id, user)
    runtime_store.workflows[workflow_id]["deleted"] = True
    runtime_store.workflows[workflow_id]["updated_at"] = utcnow()
    return {"message": "Workflow deleted successfully"}
