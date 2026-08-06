"""Organization-scoped workflow endpoints backed by the relational database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import AuditEvent, Project, Workflow, WorkflowRun, Workspace
from app.services import work_management

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


class WorkflowRunCreate(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_workflow(workflow: Workflow) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "status": workflow.status,
        "organization_id": workflow.organization_id,
        "workspace_id": workflow.workspace_id,
        "project_id": workflow.project_id,
        "trigger": workflow.trigger,
        "steps": workflow.steps or [],
        "run_count": workflow.run_count,
        "last_run_at": _iso(workflow.last_run_at),
        "archived_at": _iso(workflow.archived_at),
        "version": workflow.version,
        "created_at": _iso(workflow.created_at),
        "updated_at": _iso(workflow.updated_at),
        "deleted": workflow.status == "deleted",
    }


def _workflow_statement(organization_id: str):
    return select(Workflow).where(
        Workflow.organization_id == organization_id,
        Workflow.status != "deleted",
    )


async def _workflow_row(
    session: AsyncSession,
    workflow_id: str,
    organization_id: str,
):
    return await session.scalar(
        _workflow_statement(organization_id).where(Workflow.id == workflow_id)
    )


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


async def _validate_workspace(
    session: AsyncSession,
    workspace_id: str,
    organization_id: str,
) -> None:
    workspace = await session.scalar(
        select(Workspace.id).where(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
            Workspace.status != "deleted",
        )
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")


def _audit(
    actor: UserRecord,
    action: str,
    workflow: Workflow,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="workflow",
        resource_id=workflow.id,
        details={"name": workflow.name, **(details or {})},
    )


@router.get("")
async def list_workflows(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    project_id: Optional[str] = None,
    actor: UserRecord = Depends(require_permissions("workflows:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = _workflow_statement(actor.organization_id)
    if status_filter:
        statement = statement.where(Workflow.status == status_filter)
    if project_id:
        statement = statement.where(Workflow.project_id == project_id)
    workflows = (
        await session.scalars(
            statement.order_by(Workflow.created_at.desc()).offset(skip).limit(limit)
        )
    ).all()
    return [_serialize_workflow(workflow) for workflow in workflows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate,
    actor: UserRecord = Depends(require_permissions("workflows:write")),
    session: AsyncSession = Depends(get_db),
):
    normalized_name = data.name.strip()
    if len(normalized_name) < 2:
        raise HTTPException(status_code=422, detail="Workflow name is required")
    project: Project | None = None
    if data.project_id:
        project = await _project(session, data.project_id, actor.organization_id)
        if data.workspace_id and data.workspace_id != project.workspace_id:
            raise HTTPException(
                status_code=422,
                detail="Workflow workspace does not match the selected project",
            )
    workspace_id = data.workspace_id or (project.workspace_id if project else None)
    if workspace_id:
        await _validate_workspace(
            session,
            workspace_id,
            actor.organization_id,
        )

    workflow = Workflow(
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        project_id=project.id if project else None,
        name=normalized_name,
        description=data.description,
        status="draft",
        trigger=data.trigger,
        steps=data.steps,
        run_count=0,
        version=1,
    )
    session.add(workflow)
    await session.flush()
    session.add(
        _audit(
            actor,
            "workflow.create",
            workflow,
            {"workspace_id": workspace_id},
        )
    )
    await session.commit()
    row = await _workflow_row(session, workflow.id, actor.organization_id)
    if row is None:
        raise HTTPException(
            status_code=500,
            detail="Created workflow could not be loaded",
        )
    return _serialize_workflow(row)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    actor: UserRecord = Depends(require_permissions("workflows:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _workflow_row(session, workflow_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _serialize_workflow(row)


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    data: WorkflowUpdate,
    actor: UserRecord = Depends(require_permissions("workflows:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _workflow_row(session, workflow_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    workflow = row
    updates = data.model_dump(exclude_unset=True)
    changed_fields = sorted(updates)
    for field in ("name", "status", "trigger", "steps"):
        if field in updates and updates[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"Workflow {field} cannot be null",
            )
    if updates.get("status") == "deleted":
        raise HTTPException(
            status_code=422,
            detail="Use the delete endpoint to delete a workflow",
        )
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if len(updates["name"]) < 2:
            raise HTTPException(status_code=422, detail="Workflow name is required")
    for field in ("name", "description", "status", "trigger", "steps"):
        if field in updates:
            setattr(workflow, field, updates[field])
    workflow.version += 1
    session.add(
        _audit(
            actor,
            "workflow.update",
            workflow,
            {"fields": changed_fields},
        )
    )
    await session.commit()
    refreshed = await _workflow_row(session, workflow.id, actor.organization_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _serialize_workflow(refreshed)


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    data: WorkflowRunCreate | None = None,
    actor: UserRecord = Depends(require_permissions("workflows:write")),
    session: AsyncSession = Depends(get_db),
):
    workflow = await session.scalar(
        select(Workflow)
        .where(
            Workflow.id == workflow_id,
            Workflow.organization_id == actor.organization_id,
            Workflow.status != "deleted",
        )
        .with_for_update()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    run = await work_management.execute_workflow(
        session,
        actor,
        workflow,
        input_payload=data.input if data else {},
    )
    await session.commit()
    return {
        "run_id": run.id,
        "status": "accepted",
        "run_status": run.status,
        "run": work_management.workflow_run_snapshot(run),
        "workflow": _serialize_workflow(workflow),
    }


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    actor: UserRecord = Depends(require_permissions("workflows:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _workflow_row(session, workflow_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    workflow = row
    workflow.status = "deleted"
    session.add(_audit(actor, "workflow.delete", workflow))
    await session.commit()
    return {"message": "Workflow deleted successfully"}


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("workflows:read")),
    session: AsyncSession = Depends(get_db),
):
    workflow = await _workflow_row(session, workflow_id, actor.organization_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    rows = list(
        (
            await session.scalars(
                select(WorkflowRun)
                .where(
                    WorkflowRun.workflow_id == workflow.id,
                    WorkflowRun.organization_id == actor.organization_id,
                )
                .order_by(WorkflowRun.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [work_management.workflow_run_snapshot(item) for item in rows]


@router.get("/{workflow_id}/runs/{run_id}")
async def get_workflow_run(
    workflow_id: str,
    run_id: str,
    actor: UserRecord = Depends(require_permissions("workflows:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.organization_id == actor.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return work_management.workflow_run_snapshot(item)


@router.post("/{workflow_id}/runs/{run_id}/cancel")
async def cancel_workflow_run(
    workflow_id: str,
    run_id: str,
    actor: UserRecord = Depends(require_permissions("workflows:write")),
    session: AsyncSession = Depends(get_db),
):
    item = await session.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    try:
        await work_management.cancel_workflow_run(session, actor, item)
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return work_management.workflow_run_snapshot(item)


@router.post("/{workflow_id}/archive")
async def archive_workflow(
    workflow_id: str,
    actor: UserRecord = Depends(require_permissions("workflows:write")),
    session: AsyncSession = Depends(get_db),
):
    workflow = await session.scalar(
        select(Workflow)
        .where(
            Workflow.id == workflow_id,
            Workflow.organization_id == actor.organization_id,
            Workflow.status != "deleted",
        )
        .with_for_update()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    workflow.status = "archived"
    workflow.archived_at = datetime.now(UTC)
    workflow.version += 1
    session.add(
        _audit(
            actor,
            "workflow.archive",
            workflow,
            {"version": workflow.version},
        )
    )
    await session.commit()
    return _serialize_workflow(workflow)
