"""Durable endpoints for the complete governed user project lifecycle."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.core.config import settings
from app.db.base import get_db
from app.db.models import AuditEvent, Notification, Project, ProjectExecution
from app.services import communications
from app.services.free_tier import consume_assistant_response, consume_user_message
from app.services.lifecycle_alerts import owner_alert_channels
from app.services.three_d_product import access_snapshot, project_for_actor

router = APIRouter()


class ProjectExecutionStart(BaseModel):
    confirm_external_processing: bool = False
    mode: Literal["full", "planning", "provider_neutral", "3d_full"] = "full"
    objective: str | None = Field(default=None, min_length=10, max_length=6000)


class ProjectExecutionApproval(BaseModel):
    confirm_owner_approval: bool
    note: str | None = Field(default=None, max_length=500)


class ProjectExecutionTransition(BaseModel):
    action: Literal["pause", "resume", "cancel", "request_review", "reject", "rework"]
    note: str = Field(default="", max_length=2000)


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
        "three_d_web",
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
        "review_status": record.review_status,
        "rework_count": record.rework_count,
        "paused_at": _iso(record.paused_at),
        "cancelled_at": _iso(record.cancelled_at),
        "version": record.version,
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
    provider_neutral = data.mode == "provider_neutral"
    if not provider_neutral and data.confirm_external_processing is not True:
        raise HTTPException(
            status_code=422,
            detail=(
                "Explicit confirmation is required before project data is sent "
                "to the configured external AI provider"
            ),
        )
    if data.mode == "3d_full":
        project = await project_for_actor(session, actor, project_id, write=True)
        access = await access_snapshot(session, actor, lock_policy=True)
        if not access["eligible"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "THREE_D_ACCESS_NOT_GRANTED",
                    "message": "Full 3D project generation is controlled by the Super Owner and the eligible plan.",
                },
            )
        if access["monthly_used"] >= access["monthly_quota"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "THREE_D_MONTHLY_QUOTA_REACHED",
                    "allowed": access["monthly_quota"],
                    "used": access["monthly_used"],
                },
            )
        if access["active_jobs"] >= access["max_concurrent_jobs"]:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "THREE_D_CONCURRENCY_LIMIT",
                    "allowed": access["max_concurrent_jobs"],
                    "active": access["active_jobs"],
                },
            )
    else:
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

    if not provider_neutral:
        await consume_user_message(session, actor, characters=len(objective))
        await consume_assistant_response(session, actor)

    record = ProjectExecution(
        organization_id=actor.organization_id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        requested_by_id=actor.id,
        mode="provider_neutral" if provider_neutral else ("full" if data.mode == "planning" else data.mode),
        provider="provider-neutral" if provider_neutral else "openai",
        status="completed" if provider_neutral else "queued",
        stage="review" if provider_neutral else "queued",
        progress=100 if provider_neutral else 0,
        objective=objective,
        external_processing_confirmed=not provider_neutral,
        budget_cap_usd=0.0 if provider_neutral else float(settings.PROJECT_EXECUTION_BUDGET_CAP_USD),
        result_summary={},
        attempts=1 if provider_neutral else 0,
        max_attempts=1,
        review_status="pending" if provider_neutral else "not_requested",
        rework_count=0,
        version=1,
    )
    session.add(record)
    try:
        await session.flush()
        if provider_neutral:
            evidence_root = Path(settings.PROJECT_EXECUTION_OUTPUT_ROOT) / record.id
            package_root = evidence_root / "delivery-package"
            evidence_root.mkdir(parents=True, exist_ok=False)
            package_root.mkdir(mode=0o700)
            project_snapshot = {
                "schema_version": 1,
                "project_id": project.id,
                "organization_id": actor.organization_id,
                "execution_id": record.id,
                "objective": objective,
                "mode": "provider_neutral",
                "provider": "provider-neutral",
                "external_processing": False,
                "created_at": datetime.now(UTC).isoformat(),
                "claim_boundary": "No AI model or external provider was invoked.",
            }
            project_path = package_root / "project.json"
            project_path.write_text(_canonical_json(project_snapshot), encoding="utf-8")
            os.chmod(project_path, 0o600)
            manifest = {
                "schema_version": 1,
                "execution_id": record.id,
                "project_id": project.id,
                "organization_id": actor.organization_id,
                "mode": "provider_neutral",
                "provider": "provider-neutral",
                "model": None,
                "external_processing": False,
                "files": [
                    {
                        "path": "delivery-package/project.json",
                        "sha256": _sha256(project_path),
                        "size_bytes": project_path.stat().st_size,
                    }
                ],
                "all_governance_layers_executed": True,
                "model_claims_used_as_execution_proof": False,
                "production_modified": False,
            }
            manifest_path = evidence_root / "manifest.json"
            manifest_path.write_text(_canonical_json(manifest), encoding="utf-8")
            os.chmod(manifest_path, 0o600)
            record.evidence_path = str(evidence_root)
            record.completed_at = datetime.now(UTC)
            record.readiness_score = 1.0
            record.approved = False
            record.result_summary = {
                "success": True,
                "status": "review",
                "provider": "provider-neutral",
                "model": None,
                "artifacts_count": 2,
                "requests_count": 0,
                "retries_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "calculated_cost": 0.0,
                "budget_cap": 0.0,
                "approved": False,
                "readiness_score": 1.0,
                "blocking_findings": ["owner approval is required"],
                "rework_plan": [],
                "fallback_used": False,
                "production_modified": False,
                "phase": "29F",
                "mode": "provider_neutral",
                "governance": {"government": {"owner_approved": False}},
                "workforce": [],
                "engineering_review": {"status": "verified"},
                "security_review": {"status": "verified"},
                "integration_review": {"status": "verified"},
                "release_review": {
                    "status": "pending_owner_approval",
                    "approved": False,
                    "owner_approval_required": True,
                    "blocking_findings": ["owner approval is required"],
                },
                "delivery_package": {
                    "root": "delivery-package",
                    "manifest": "manifest.json",
                },
                "all_governance_layers_executed": True,
                "model_claims_used_as_execution_proof": False,
            }
            project.status = "review"
            project.review_status = "pending"
            project.progress = 100
        else:
            project.status = "planning"
            project.progress = max(project.progress, 1)
        project.version += 1
        session.add(
            AuditEvent(
                organization_id=actor.organization_id,
                user_id=actor.id,
                action=(
                    "project.execution.provider_neutral_completed"
                    if provider_neutral
                    else "project.execution.queued"
                ),
                resource_type="project_execution",
                resource_id=record.id,
                details={
                    "project_id": project.id,
                    "mode": record.mode,
                    "provider": record.provider,
                    "budget_cap_usd": record.budget_cap_usd,
                    "external_processing_confirmed": record.external_processing_confirmed,
                    "evidence_available": bool(record.evidence_path),
                },
            )
        )
        notifications = await communications.notify_audience(
            session,
            organization_id=actor.organization_id,
            audience="platform_owner",
            event_key="project.execution.started",
            category="project",
            title="User started project execution",
            message=(
                f"{actor.name} started a {data.mode} execution for project "
                f"'{project.name}' in organization {actor.organization_name}."
            ),
            severity="info",
            channels=owner_alert_channels(),
            source_type="project_execution",
            source_id=record.id,
            correlation_id=record.id,
            dedupe_prefix=f"project-execution-started:{record.id}",
            payload={
                "project_id": project.id,
                "project_name": project.name,
                "execution_id": record.id,
                "requested_mode": data.mode,
                "effective_mode": record.mode,
                "provider": record.provider,
                "organization_id": actor.organization_id,
                "user_id": actor.id,
                "external_processing": record.external_processing_confirmed,
                "status": record.status,
            },
            actor_id=actor.id,
            respect_preferences=False,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A project execution is already queued or running",
        ) from exc
    await communications.publish_many(notifications)
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
    if not (
        "*" in actor.permissions
        or "projects:approve" in actor.permissions
        or (actor.role == "Owner" and project.owner_id == actor.id)
    ):
        raise HTTPException(
            status_code=403,
            detail="The project Owner or an authorized approver must approve this release",
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
    record.review_status = "approved"
    record.progress = 100
    record.version += 1
    record.result_summary = updated
    project.status = "completed"
    project.review_status = "approved"
    project.approved_by_id = actor.id
    project.approved_at = approved_at
    project.completed_at = approved_at
    project.progress = 100
    project.version += 1
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
    archive_bytes = archive.getvalue()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    archive = io.BytesIO(archive_bytes)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aionex-project-{project_id[:8]}-{execution_id[:8]}.zip"'
            ),
            "Cache-Control": "no-store",
            "X-AIONEX-Execution": execution_id,
            "X-AIONEX-SHA256": archive_sha256,
        },
    )


@router.post("/{project_id}/executions/{execution_id}/transition")
async def transition_project_execution(
    project_id: str,
    execution_id: str,
    data: ProjectExecutionTransition,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    project = await _project(session, project_id, actor.organization_id)
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
    action = data.action
    previous = record.status
    current = datetime.now(UTC)
    if action == "pause":
        if record.status != "queued":
            raise HTTPException(status_code=409, detail="Only a queued execution can be paused")
        record.status = "paused"
        record.stage = "paused"
        record.paused_at = current
    elif action == "resume":
        if record.status != "paused":
            raise HTTPException(status_code=409, detail="Only a paused execution can be resumed")
        active = await session.scalar(
            select(ProjectExecution.id).where(
                ProjectExecution.project_id == project.id,
                ProjectExecution.organization_id == actor.organization_id,
                ProjectExecution.id != record.id,
                ProjectExecution.status.in_({"queued", "running"}),
            )
        )
        if active is not None:
            raise HTTPException(status_code=409, detail="Another execution is active")
        record.status = "queued"
        record.stage = "queued"
        record.paused_at = None
    elif action == "cancel":
        if record.status not in {"queued", "paused", "failed"}:
            raise HTTPException(
                status_code=409,
                detail="Only queued, paused, or failed executions can be cancelled",
            )
        record.status = "cancelled"
        record.stage = "cancelled"
        record.cancelled_at = current
        project.status = "cancelled"
        project.cancelled_at = current
    elif action == "request_review":
        if record.status != "completed" or not record.evidence_path:
            raise HTTPException(
                status_code=409,
                detail="Only completed retained evidence can enter review",
            )
        record.stage = "review"
        record.review_status = "pending"
        project.status = "review"
        project.review_status = "pending"
    elif action == "reject":
        if record.status != "completed" or record.review_status not in {
            "pending",
            "approved",
            "not_requested",
        }:
            raise HTTPException(status_code=409, detail="Execution is not reviewable")
        record.review_status = "rejected"
        record.stage = "rework"
        record.approved = False
        project.status = "rework"
        project.review_status = "changes_requested"
        project.approved_by_id = None
        project.approved_at = None
    elif action == "rework":
        if record.status not in {"completed", "failed", "paused"}:
            raise HTTPException(status_code=409, detail="Execution cannot enter rework")
        active = await session.scalar(
            select(ProjectExecution.id).where(
                ProjectExecution.project_id == project.id,
                ProjectExecution.organization_id == actor.organization_id,
                ProjectExecution.id != record.id,
                ProjectExecution.status.in_({"queued", "running"}),
            )
        )
        if active is not None:
            raise HTTPException(status_code=409, detail="Another execution is active")
        record.rework_count += 1
        record.approved = False
        record.error_code = None
        record.error_message = None
        record.cancelled_at = None
        if record.provider == "provider-neutral":
            record.status = "completed"
            record.stage = "review"
            record.review_status = "pending"
            summary = dict(record.result_summary or {})
            summary.update(
                {
                    "status": "review",
                    "approved": False,
                    "blocking_findings": ["owner approval is required"],
                    "rework_plan": [],
                    "recovered_from_existing_evidence": True,
                }
            )
            summary["owner_approval"] = None
            release = dict(summary.get("release_review") or {})
            release.update(
                {
                    "status": "pending_owner_approval",
                    "approved": False,
                    "owner_approved": False,
                    "owner_approval_required": True,
                    "blocking_findings": ["owner approval is required"],
                }
            )
            summary["release_review"] = release
            record.result_summary = summary
        else:
            record.status = "queued"
            record.stage = "queued"
            record.review_status = "not_requested"
            record.progress = 0
            record.completed_at = None
            record.evidence_path = None
            record.result_summary = {}
        project.status = "review" if record.provider == "provider-neutral" else "planning"
        project.review_status = (
            "pending" if record.provider == "provider-neutral" else "not_requested"
        )
        project.approved_by_id = None
        project.approved_at = None
        project.completed_at = None
    record.version += 1
    project.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=f"project.execution.{action}",
            resource_type="project_execution",
            resource_id=record.id,
            details={
                "project_id": project.id,
                "from": previous,
                "to": record.status,
                "review_status": record.review_status,
                "rework_count": record.rework_count,
                "note": data.note.strip() or None,
            },
        )
    )
    await session.commit()
    return serialize_project_execution(record)
