"""Operational reporting endpoints backed by the consolidated runtime store."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import new_id, runtime_store, utcnow

router = APIRouter()


class ReportCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    type: str = "operations"
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    summary: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    report_type: Optional[str] = Query(None, alias="type"),
    project_id: Optional[str] = None,
    user: UserRecord = Depends(current_user),
):
    reports = [item for item in runtime_store.reports.values() if item.get("organization_id") == user.organization_id]
    if report_type:
        reports = [item for item in reports if item.get("type") == report_type]
    if project_id:
        reports = [item for item in reports if item.get("project_id") == project_id]
    reports.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return reports[skip : skip + limit]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_report(data: ReportCreate, user: UserRecord = Depends(current_user)):
    if data.project_id:
        project = runtime_store.projects.get(data.project_id)
        if not project or project.get("deleted") or project.get("organization_id") != user.organization_id:
            raise HTTPException(status_code=404, detail="Project not found")
    report_id = new_id("report")
    report = {
        "id": report_id,
        "name": data.name.strip(),
        "type": data.type,
        "organization_id": user.organization_id,
        "workspace_id": data.workspace_id,
        "project_id": data.project_id,
        "status": "ready",
        "generated_by": user.id,
        "summary": data.summary,
        "metrics": data.metrics,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    runtime_store.reports[report_id] = report
    runtime_store.add_activity("report", "Report generated", report["name"], user.id)
    return report


@router.get("/{report_id}")
async def get_report(report_id: str, user: UserRecord = Depends(current_user)):
    report = runtime_store.reports.get(report_id)
    if not report or report.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
