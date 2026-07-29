"""Organization-scoped reporting endpoints backed by the relational database."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import AuditEvent, Project, Report, Workspace

router = APIRouter()


class ReportCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    type: str = "operations"
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    summary: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_report(
    report: Report,
    workspace_id: str | None,
    generated_by: str | None,
) -> dict[str, Any]:
    return {
        "id": report.id,
        "name": report.name,
        "type": report.type,
        "organization_id": report.organization_id,
        "workspace_id": workspace_id,
        "project_id": report.project_id,
        "status": report.status,
        "generated_by": generated_by,
        "summary": report.summary,
        "metrics": report.metrics or {},
        "created_at": _iso(report.created_at),
        "updated_at": _iso(report.updated_at),
    }


def _report_statement(organization_id: str):
    return (
        select(Report, Project.workspace_id)
        .outerjoin(
            Project,
            and_(
                Project.id == Report.project_id,
                Project.organization_id == Report.organization_id,
            ),
        )
        .where(Report.organization_id == organization_id)
    )


async def _report_metadata(
    session: AsyncSession,
    organization_id: str,
    report_ids: list[str],
) -> dict[str, tuple[str | None, str | None]]:
    if not report_ids:
        return {}
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.resource_type == "report",
                AuditEvent.resource_id.in_(report_ids),
                AuditEvent.action == "report.create",
            )
            .order_by(AuditEvent.created_at)
        )
    ).all()
    metadata: dict[str, tuple[str | None, str | None]] = {}
    for event in events:
        if event.resource_id is None or event.resource_id in metadata:
            continue
        details = event.details or {}
        workspace_id = details.get("workspace_id")
        metadata[event.resource_id] = (
            event.user_id,
            str(workspace_id) if workspace_id else None,
        )
    return metadata


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
    report: Report,
    workspace_id: str | None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="report.create",
        resource_type="report",
        resource_id=report.id,
        details={"name": report.name, "workspace_id": workspace_id},
    )


@router.get("")
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    report_type: Optional[str] = Query(None, alias="type"),
    project_id: Optional[str] = None,
    actor: UserRecord = Depends(require_permissions("reports:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = _report_statement(actor.organization_id)
    if report_type:
        statement = statement.where(Report.type == report_type)
    if project_id:
        statement = statement.where(Report.project_id == project_id)
    rows = (
        await session.execute(
            statement.order_by(Report.created_at.desc()).offset(skip).limit(limit)
        )
    ).all()
    metadata = await _report_metadata(
        session,
        actor.organization_id,
        [report.id for report, _ in rows],
    )
    return [
        _serialize_report(
            report,
            project_workspace_id or metadata.get(report.id, (None, None))[1],
            metadata.get(report.id, (None, None))[0],
        )
        for report, project_workspace_id in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_report(
    data: ReportCreate,
    actor: UserRecord = Depends(require_permissions("reports:write")),
    session: AsyncSession = Depends(get_db),
):
    project: Project | None = None
    if data.project_id:
        project = await _project(session, data.project_id, actor.organization_id)
        if data.workspace_id and data.workspace_id != project.workspace_id:
            raise HTTPException(
                status_code=422,
                detail="Report workspace does not match the selected project",
            )
    workspace_id = data.workspace_id or (project.workspace_id if project else None)
    if workspace_id:
        await _validate_workspace(session, workspace_id, actor.organization_id)

    report = Report(
        organization_id=actor.organization_id,
        project_id=project.id if project else None,
        name=data.name.strip(),
        type=data.type,
        status="ready",
        summary=data.summary,
        metrics=data.metrics,
    )
    session.add(report)
    await session.flush()
    session.add(_audit(actor, report, workspace_id))
    await session.commit()
    row = (
        await session.execute(
            _report_statement(actor.organization_id).where(Report.id == report.id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=500,
            detail="Created report could not be loaded",
        )
    stored, project_workspace_id = row
    return _serialize_report(
        stored,
        project_workspace_id or workspace_id,
        actor.id,
    )


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    actor: UserRecord = Depends(require_permissions("reports:read")),
    session: AsyncSession = Depends(get_db),
):
    row = (
        await session.execute(
            _report_statement(actor.organization_id).where(Report.id == report_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report, project_workspace_id = row
    generated_by, audit_workspace_id = (
        await _report_metadata(
            session,
            actor.organization_id,
            [report.id],
        )
    ).get(report.id, (None, None))
    return _serialize_report(
        report,
        project_workspace_id or audit_workspace_id,
        generated_by,
    )
