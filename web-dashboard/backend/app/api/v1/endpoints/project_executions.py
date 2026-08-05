"""Durable user project execution endpoints for the single-server pilot."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.core.auth import UserRecord, require_permissions
from app.core.config import settings
from app.db.base import get_db
from app.db.models import AuditEvent, Project, ProjectExecution
from app.services.free_tier import consume_assistant_response, consume_user_message
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class ProjectExecutionStart(BaseModel):
    confirm_external_processing: bool
    mode: Literal["planning"] = "planning"
    objective: str | None = Field(default=None, min_length=10, max_length=6000)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _public_result(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    allowed = {
        "success",
        "status",
        "provider",
        "model",
        "artifacts_count",
        "requests_count",
        "retries_count",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "calculated_cost",
        "budget_cap",
        "total_duration",
        "approved",
        "readiness_score",
        "blocking_findings",
        "rework_plan",
        "comparison",
        "fallback_used",
        "production_modified",
        "recovered_from_existing_evidence",
    }
    return {key: summary[key] for key in allowed if key in summary}


def serialize_project_execution(record: ProjectExecution) -> dict[str, Any]:
    return {
        "id": record.id,
        "project_id": record.project_id,
        "workspace_id": record.workspace_id,
        "organization_id": record.organization_id,
        "requested_by_id": record.requested_by_id,
        "mode": record.mode,
        "provider": record.provider,
        "model": record.model,
        "status": record.status,
        "stage": record.stage,
        "progress": record.progress,
        "budget_cap_usd": record.budget_cap_usd,
        "calculated_cost_usd": record.calculated_cost_usd,
        "requests_count": record.requests_count,
        "retries_count": record.retries_count,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "total_tokens": record.total_tokens,
        "approved": record.approved,
        "readiness_score": record.readiness_score,
        "result": _public_result(record.result_summary),
        "error_code": record.error_code,
        "error_message": record.error_message,
        "evidence_available": bool(record.evidence_path),
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "started_at": _iso(record.started_at),
        "completed_at": _iso(record.completed_at),
    }


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


@router.post(
    "/{project_id}/executions",
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_project_execution(
    project_id: str,
    data: ProjectExecutionStart,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    if not settings.PROJECT_EXECUTION_ENABLED:
        raise HTTPException(status_code=503, detail="Project execution is disabled")
    if data.confirm_external_processing is not True:
        raise HTTPException(
            status_code=422,
            detail=(
                "Explicit confirmation is required before project data is sent "
                "to the configured external AI provider"
            ),
        )
    project = await _project(session, project_id, actor.organization_id)
    objective = (data.objective or project.description or project.name).strip()
    if len(objective) < 10:
        raise HTTPException(
            status_code=422,
            detail="Add a clear project description before starting the AI planning cycle",
        )

    existing = await session.scalar(
        select(ProjectExecution)
        .where(
            ProjectExecution.project_id == project.id,
            ProjectExecution.organization_id == actor.organization_id,
        )
        .order_by(ProjectExecution.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROJECT_EXECUTION_ALREADY_EXISTS",
                "message": "This project already has an execution record.",
                "execution": serialize_project_execution(existing),
            },
        )

    await consume_user_message(session, actor, characters=len(objective))
    await consume_assistant_response(session, actor)

    record = ProjectExecution(
        organization_id=actor.organization_id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        requested_by_id=actor.id,
        mode=data.mode,
        provider="openai",
        status="queued",
        stage="queued",
        progress=0,
        objective=objective,
        external_processing_confirmed=True,
        budget_cap_usd=float(settings.PROJECT_EXECUTION_BUDGET_CAP_USD),
        result_summary={},
        attempts=0,
        max_attempts=1,
    )
    session.add(record)
    try:
        await session.flush()
        project.status = "planning"
        project.progress = max(project.progress, 1)
        session.add(
            AuditEvent(
                organization_id=actor.organization_id,
                user_id=actor.id,
                action="project.execution.queued",
                resource_type="project_execution",
                resource_id=record.id,
                details={
                    "project_id": project.id,
                    "mode": data.mode,
                    "provider": "openai",
                    "budget_cap_usd": record.budget_cap_usd,
                    "external_processing_confirmed": True,
                },
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A project execution is already queued or running",
        ) from exc
    await session.refresh(record)
    return serialize_project_execution(record)


@router.get("/{project_id}/executions")
async def list_project_executions(
    project_id: str,
    limit: int = Query(10, ge=1, le=50),
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    await _project(session, project_id, actor.organization_id)
    records = (
        await session.scalars(
            select(ProjectExecution)
            .where(
                ProjectExecution.project_id == project_id,
                ProjectExecution.organization_id == actor.organization_id,
            )
            .order_by(ProjectExecution.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [serialize_project_execution(record) for record in records]


@router.get("/{project_id}/executions/{execution_id}")
async def get_project_execution(
    project_id: str,
    execution_id: str,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    record = await session.scalar(
        select(ProjectExecution).where(
            ProjectExecution.id == execution_id,
            ProjectExecution.project_id == project_id,
            ProjectExecution.organization_id == actor.organization_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Project execution not found")
    return serialize_project_execution(record)
