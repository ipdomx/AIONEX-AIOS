"""Durable endpoints for the complete governed user project lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
import zipfile

from app.core.auth import UserRecord, require_permissions
from app.core.config import settings
from app.db.base import get_db
from app.db.models import AuditEvent, Notification, Project, ProjectExecution
from app.services.free_tier import consume_assistant_response, consume_user_message
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class ProjectExecutionStart(BaseModel):
    confirm_external_processing: bool
    mode: Literal["full", "planning"] = "full"
    objective: str | None = Field(default=None, min_length=10, max_length=6000)


class ProjectExecutionApproval(BaseModel):
    confirm_owner_approval: bool
    note: str | None = Field(default=None, max_length=500)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_approval_receipt(path: Path, payload: dict[str, Any]) -> str:
    content = _canonical_json(payload)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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
        "phase",
        "mode",
        "governance",
        "workforce",
        "engineering_review",
        "security_review",
        "integration_review",
        "release_review",
        "delivery_package",
        "all_governance_layers_executed",
        "model_claims_used_as_execution_proof",
        "owner_approval",
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
            detail="Add a clear project description before starting the full governed project cycle",
        )

    existing = await session.scalar(
        select(ProjectExecution)
        .where(
            ProjectExecution.project_id == project.id,
            ProjectExecution.organization_id == actor.organization_id,
            ProjectExecution.status.in_(("queued", "running")),
        )
        .order_by(ProjectExecution.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROJECT_EXECUTION_ACTIVE",
                "message": "This project already has a queued or running execution.",
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
        mode="full" if data.mode == "planning" else data.mode,
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
                    "mode": "full" if data.mode == "planning" else data.mode,
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


@router.post("/{project_id}/executions/{execution_id}/approve")
async def approve_project_execution(
    project_id: str,
    execution_id: str,
    data: ProjectExecutionApproval,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    if data.confirm_owner_approval is not True:
        raise HTTPException(
            status_code=422,
            detail="Explicit Owner approval confirmation is required",
        )
    project = await _project(session, project_id, actor.organization_id)
    if actor.role != "Owner" or project.owner_id != actor.id:
        raise HTTPException(
            status_code=403,
            detail="The project Organization Owner must approve this release",
        )
    record = await session.scalar(
        select(ProjectExecution)
        .where(
            ProjectExecution.id == execution_id,
            ProjectExecution.project_id == project.id,
            ProjectExecution.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Project execution not found")
    if record.approved is True and record.stage == "approved":
        return serialize_project_execution(record)
    if record.status != "completed" or not record.evidence_path:
        raise HTTPException(
            status_code=409,
            detail="Only a completed governed execution can be approved",
        )
    summary = record.result_summary
    if not isinstance(summary, dict):
        raise HTTPException(status_code=409, detail="Execution result is invalid")
    release = summary.get("release_review")
    blockers = list(summary.get("blocking_findings") or [])
    other_blockers = [
        str(item)
        for item in blockers
        if str(item) != "owner approval is required"
    ]
    if (
        not isinstance(release, dict)
        or release.get("owner_approval_required") is not True
        or summary.get("all_governance_layers_executed") is not True
        or summary.get("model_claims_used_as_execution_proof") is not False
        or summary.get("fallback_used") is not False
        or summary.get("production_modified") is not False
        or other_blockers
    ):
        raise HTTPException(
            status_code=409,
            detail="Execution evidence still contains non-Owner release blockers",
        )

    raw_evidence_root = Path(record.evidence_path)
    raw_manifest_path = raw_evidence_root / "manifest.json"
    if raw_evidence_root.is_symlink() or raw_manifest_path.is_symlink():
        raise HTTPException(status_code=409, detail="Execution evidence is unsafe")
    try:
        allowed_root = Path(settings.PROJECT_EXECUTION_OUTPUT_ROOT).resolve(strict=True)
        evidence_root = raw_evidence_root.resolve(strict=True)
        manifest_path = raw_manifest_path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Execution evidence is unavailable",
        ) from exc
    if (
        evidence_root == allowed_root
        or allowed_root not in evidence_root.parents
        or not evidence_root.is_dir()
        or evidence_root not in manifest_path.parents
        or not manifest_path.is_file()
    ):
        raise HTTPException(status_code=409, detail="Execution evidence is unsafe")

    approval_path = evidence_root / "owner-approval.json"
    approved_at = datetime.now(UTC)
    receipt = {
        "schema_version": 1,
        "decision": "approved",
        "execution_id": record.id,
        "project_id": project.id,
        "organization_id": actor.organization_id,
        "approved_by_id": actor.id,
        "approved_by_role": actor.role,
        "approved_at": approved_at.isoformat(),
        "evidence_manifest": "manifest.json",
        "evidence_manifest_sha256": _sha256(manifest_path),
        "note": (data.note or "").strip() or None,
        "claim_boundary": (
            "Owner approval closes only the retained evidence package and does "
            "not assert unexecuted deployment, external integration, or store publication."
        ),
    }
    if approval_path.exists():
        if not approval_path.is_file() or approval_path.is_symlink():
            raise HTTPException(status_code=409, detail="Owner approval receipt is unsafe")
        try:
            existing = json.loads(approval_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Owner approval receipt is invalid",
            ) from exc
        if (
            not isinstance(existing, dict)
            or existing.get("decision") != "approved"
            or existing.get("execution_id") != record.id
            or existing.get("project_id") != project.id
            or existing.get("organization_id") != actor.organization_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Owner approval receipt does not match this execution",
            )
        receipt = existing
        receipt_sha256 = _sha256(approval_path)
        approved_at_text = str(existing.get("approved_at") or approved_at.isoformat())
    else:
        receipt_sha256 = _atomic_approval_receipt(approval_path, receipt)
        approved_at_text = approved_at.isoformat()

    updated = json.loads(json.dumps(summary))
    updated["status"] = "approved"
    updated["approved"] = True
    updated["blocking_findings"] = []
    updated["rework_plan"] = []
    updated["owner_approval"] = {
        "approved": True,
        "approved_by_id": actor.id,
        "approved_at": approved_at_text,
        "receipt": "owner-approval.json",
        "receipt_sha256": receipt_sha256,
    }
    updated_release = dict(updated.get("release_review") or {})
    updated_release.update(
        {
            "approved": True,
            "status": "approved",
            "owner_approved": True,
            "blocking_findings": [],
            "rework_plan": [],
        }
    )
    updated["release_review"] = updated_release
    governance = dict(updated.get("governance") or {})
    government = dict(governance.get("government") or {})
    government["owner_approved"] = True
    governance["government"] = government
    updated["governance"] = governance
    package = dict(updated.get("delivery_package") or {})
    package["owner_approval_receipt"] = "owner-approval.json"
    package["owner_approval_receipt_sha256"] = receipt_sha256
    updated["delivery_package"] = package

    record.approved = True
    record.stage = "approved"
    record.progress = 100
    record.result_summary = updated
    project.status = "completed"
    project.progress = 100
    session.add(
        Notification(
            organization_id=record.organization_id,
            recipient_id=record.requested_by_id,
            type="project.execution.owner_approved",
            title="Governed project release approved",
            message=(
                "The Organization Owner approved the retained evidence package. "
                "The final delivery archive is ready."
            ),
            severity="success",
            payload={
                "project_id": project.id,
                "execution_id": record.id,
                "approved": True,
                "receipt_sha256": receipt_sha256,
            },
        )
    )
    session.add(
        AuditEvent(
            organization_id=record.organization_id,
            user_id=actor.id,
            action="project.execution.owner_approved",
            resource_type="project_execution",
            resource_id=record.id,
            details={
                "project_id": project.id,
                "receipt_sha256": receipt_sha256,
                "evidence_manifest_sha256": receipt["evidence_manifest_sha256"],
                "remaining_blockers": 0,
            },
        )
    )
    await session.commit()
    await session.refresh(record)
    return serialize_project_execution(record)


@router.get("/{project_id}/executions/{execution_id}/download")
async def download_project_execution(
    project_id: str,
    execution_id: str,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    record = await session.scalar(
        select(ProjectExecution).where(
            ProjectExecution.id == execution_id,
            ProjectExecution.project_id == project_id,
            ProjectExecution.organization_id == actor.organization_id,
            ProjectExecution.status == "completed",
        )
    )
    if record is None or not record.evidence_path:
        raise HTTPException(
            status_code=404, detail="Completed project delivery package not found"
        )
    try:
        evidence_root = Path(record.evidence_path).resolve(strict=True)
        package_root = (evidence_root / "delivery-package").resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=409, detail="Project delivery package is unavailable"
        ) from exc
    if evidence_root not in package_root.parents or not package_root.is_dir():
        raise HTTPException(status_code=409, detail="Project delivery package is unsafe")

    files = [
        path
        for path in package_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    ]
    if not files or len(files) > 100:
        raise HTTPException(status_code=409, detail="Project delivery package is invalid")
    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Project delivery package is too large")

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            resolved = path.resolve(strict=True)
            if package_root not in resolved.parents:
                raise HTTPException(
                    status_code=409, detail="Project delivery file escapes package root"
                )
            bundle.write(resolved, resolved.relative_to(package_root))
        approval_path = evidence_root / "owner-approval.json"
        if approval_path.exists():
            if not approval_path.is_file() or approval_path.is_symlink():
                raise HTTPException(
                    status_code=409, detail="Owner approval receipt is unsafe"
                )
            if approval_path.stat().st_size > 64 * 1024:
                raise HTTPException(
                    status_code=409, detail="Owner approval receipt is invalid"
                )
            bundle.write(approval_path, "owner-approval.json")
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aionex-project-{project_id[:8]}-{execution_id[:8]}.zip"'
            ),
            "Cache-Control": "no-store",
            "X-AIONEX-Execution": execution_id,
        },
    )
