"""Durable provider-neutral Production Studio API for Phase 29H."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Project,
    ProjectEvent,
    ProjectStudioAttachment,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    StudioSafetyReview,
    Workspace,
    uuid_str,
)
from app.services import production_studio
from app.services.production_studio import DEPARTMENTS
from app.services.studio_worker import StudioWorker
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

Department = Literal[
    "text",
    "website",
    "code",
    "ui-ux",
    "three-d",
    "audio",
    "video",
    "animation",
    "advertising",
    "documentary",
    "image",
    "branding",
]

# Compatibility exports retained for established tests and package consumers.
StudioRequestAlias = production_studio.StudioSpec
_department_files = production_studio.department_files
_readme = production_studio._readme
_slug = production_studio.slug


def _now() -> datetime:
    return datetime.now(UTC)


class StudioRequest(BaseModel):
    department: Department
    title: str = Field(min_length=2, max_length=160)
    brief: str = Field(min_length=8, max_length=12_000)
    language: str = Field(default="en-US", min_length=2, max_length=35)
    style: str = Field(default="modern", min_length=2, max_length=120)
    target: str | None = Field(default=None, max_length=240)
    programming_language: str | None = Field(default=None, max_length=40)
    workspace_id: str | None = None
    project_id: str | None = None


class StudioRevisionRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    brief: str = Field(min_length=8, max_length=12_000)
    language: str | None = Field(default=None, min_length=2, max_length=35)
    style: str | None = Field(default=None, min_length=2, max_length=120)
    target: str | None = Field(default=None, max_length=240)
    programming_language: str | None = Field(default=None, max_length=40)
    change_note: str = Field(min_length=2, max_length=2000)


class StudioAttachmentRequest(BaseModel):
    project_id: str


async def _validate_scope(
    session: AsyncSession,
    actor: UserRecord,
    *,
    workspace_id: str | None,
    project_id: str | None,
) -> tuple[str | None, str | None]:
    normalized_workspace = workspace_id
    normalized_project = project_id
    if project_id:
        project = await session.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        normalized_workspace = project.workspace_id
    if normalized_workspace:
        workspace = await session.scalar(
            select(Workspace).where(
                Workspace.id == normalized_workspace,
                Workspace.organization_id == actor.organization_id,
                Workspace.status == "active",
            )
        )
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    return normalized_workspace, normalized_project


async def _enqueue_job(
    data: StudioRequest,
    actor: UserRecord,
    session: AsyncSession,
    *,
    revision_of_asset_id: str | None = None,
    change_note: str | None = None,
) -> StudioJob:
    workspace_id, project_id = await _validate_scope(
        session,
        actor,
        workspace_id=data.workspace_id,
        project_id=data.project_id,
    )
    job = StudioJob(
        id=uuid_str(),
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        project_id=project_id,
        requested_by_id=actor.id,
        revision_of_asset_id=revision_of_asset_id,
        department=data.department,
        output_kind=production_studio.ASSET_TYPES[data.department],
        title=data.title.strip(),
        brief=data.brief.strip(),
        language=data.language.strip(),
        style=data.style.strip(),
        target=(data.target or "").strip() or None,
        programming_language=(data.programming_language or "").strip() or None,
        change_note=(change_note or "").strip() or None,
        provider_mode="provider_neutral",
        provider=None,
        model=None,
        status="queued",
        progress=0,
        safety_status="pending",
        request_metadata={
            "external_processing_confirmed": False,
            "external_requests": 0,
            "external_tokens": 0,
            "external_cost_usd": 0,
        },
        max_attempts=3,
    )
    session.add(job)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="studio.job.queued",
            resource_type="studio_job",
            resource_id=job.id,
            details={
                "department": job.department,
                "provider_mode": job.provider_mode,
                "project_id": job.project_id,
                "revision_of_asset_id": revision_of_asset_id,
            },
        )
    )
    await session.commit()
    await session.refresh(job)
    return job


async def _job_or_404(
    session: AsyncSession, actor: UserRecord, job_id: str, *, lock: bool = False
) -> StudioJob:
    statement = select(StudioJob).where(
        StudioJob.id == job_id,
        StudioJob.organization_id == actor.organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Studio job not found")
    return item


async def _asset_or_404(
    session: AsyncSession, actor: UserRecord, asset_id: str, *, lock: bool = False
) -> StudioAsset:
    statement = select(StudioAsset).where(
        StudioAsset.id == asset_id,
        StudioAsset.organization_id == actor.organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Studio asset not found")
    return item


async def _asset_snapshot(
    session: AsyncSession, item: StudioAsset
) -> dict[str, Any]:
    project_ids = list(
        (
            await session.scalars(
                select(ProjectStudioAttachment.project_id).where(
                    ProjectStudioAttachment.asset_id == item.id,
                    ProjectStudioAttachment.status == "active",
                )
            )
        ).all()
    )
    return production_studio.asset_snapshot(item, attached_projects=project_ids)


@router.get("/departments")
async def departments() -> dict[str, object]:
    return {
        "departments": DEPARTMENTS,
        "count": len(DEPARTMENTS),
        "provider_mode": "provider_neutral",
        "provider_activation_batch": "29J",
    }


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    data: StudioRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    job = await _enqueue_job(data, actor, session)
    return production_studio.job_snapshot(job)


@router.get("/jobs")
async def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    department: str | None = None,
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    statement = select(StudioJob).where(
        StudioJob.organization_id == actor.organization_id
    )
    if status_filter:
        statement = statement.where(StudioJob.status == status_filter)
    if department:
        statement = statement.where(StudioJob.department == department)
    if project_id:
        statement = statement.where(StudioJob.project_id == project_id)
    rows = (
        await session.scalars(
            statement.order_by(StudioJob.created_at.desc()).limit(limit)
        )
    ).all()
    return [production_studio.job_snapshot(item) for item in rows]


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return production_studio.job_snapshot(
        await _job_or_404(session, actor, job_id)
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    job = await _job_or_404(session, actor, job_id, lock=True)
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Only queued or running jobs can be cancelled")
    job.status = "cancelled"
    job.progress = 100
    job.cancelled_at = _now()
    job.completed_at = _now()
    job.lease_token = None
    job.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="studio.job.cancelled",
            resource_type="studio_job",
            resource_id=job.id,
            details={"status": "cancelled"},
        )
    )
    await session.commit()
    return production_studio.job_snapshot(job)


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    job = await _job_or_404(session, actor, job_id, lock=True)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    job.status = "queued"
    job.progress = 0
    job.attempts = 0
    job.safety_status = "pending"
    job.safety_findings = []
    job.error_code = None
    job.error_message = None
    job.completed_at = None
    job.cancelled_at = None
    job.lease_token = None
    job.version += 1
    await session.commit()
    return production_studio.job_snapshot(job)


@router.get("/assets")
async def list_assets(
    status_filter: str | None = Query(default="active", alias="status"),
    department: str | None = None,
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    statement = select(StudioAsset).where(
        StudioAsset.organization_id == actor.organization_id
    )
    if status_filter:
        statement = statement.where(StudioAsset.status == status_filter)
    if department:
        statement = statement.where(StudioAsset.department == department)
    if project_id:
        attachment_ids = select(ProjectStudioAttachment.asset_id).where(
            ProjectStudioAttachment.project_id == project_id,
            ProjectStudioAttachment.organization_id == actor.organization_id,
            ProjectStudioAttachment.status == "active",
        )
        statement = statement.where(
            (StudioAsset.project_id == project_id) | StudioAsset.id.in_(attachment_ids)
        )
    rows = (
        await session.scalars(
            statement.order_by(StudioAsset.created_at.desc()).limit(limit)
        )
    ).all()
    return [await _asset_snapshot(session, item) for item in rows]


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await _asset_snapshot(
        session, await _asset_or_404(session, actor, asset_id)
    )


@router.get("/assets/{asset_id}/download")
async def download_asset(
    asset_id: str,
    revision: int | None = Query(default=None, ge=1),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id)
    filename = asset.filename
    media_type = asset.media_type
    path = asset.storage_path
    checksum = asset.checksum
    size_bytes = asset.size_bytes
    if revision is not None:
        item = await session.scalar(
            select(StudioAssetRevision).where(
                StudioAssetRevision.asset_id == asset.id,
                StudioAssetRevision.organization_id == actor.organization_id,
                StudioAssetRevision.revision_number == revision,
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Studio asset revision not found")
        filename = item.filename
        media_type = item.media_type
        path = item.storage_path
        checksum = item.checksum
        size_bytes = item.size_bytes
    try:
        verified = production_studio.verify_artifact(path, checksum, size_bytes)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        verified,
        media_type=media_type,
        filename=filename,
        headers={
            "Cache-Control": "private, no-store",
            "X-AIONEX-Checksum-SHA256": checksum,
            "X-AIONEX-Provider-Mode": "provider_neutral",
        },
    )


@router.get("/assets/{asset_id}/revisions")
async def list_revisions(
    asset_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id)
    rows = (
        await session.scalars(
            select(StudioAssetRevision)
            .where(StudioAssetRevision.asset_id == asset.id)
            .order_by(StudioAssetRevision.revision_number.desc())
        )
    ).all()
    return [production_studio.revision_snapshot(item) for item in rows]


@router.post("/assets/{asset_id}/revisions", status_code=status.HTTP_202_ACCEPTED)
async def create_revision(
    asset_id: str,
    data: StudioRevisionRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id)
    original = await session.get(StudioJob, asset.job_id)
    if original is None:
        raise HTTPException(status_code=409, detail="Original Studio job is unavailable")
    request = StudioRequest(
        department=asset.department,  # type: ignore[arg-type]
        title=data.title or asset.title,
        brief=data.brief,
        language=data.language or original.language,
        style=data.style or original.style,
        target=data.target if data.target is not None else original.target,
        programming_language=(
            data.programming_language
            if data.programming_language is not None
            else original.programming_language
        ),
        workspace_id=original.workspace_id,
        project_id=asset.project_id or original.project_id,
    )
    job = await _enqueue_job(
        request,
        actor,
        session,
        revision_of_asset_id=asset.id,
        change_note=data.change_note,
    )
    return production_studio.job_snapshot(job)


@router.get("/assets/{asset_id}/safety")
async def list_safety_reviews(
    asset_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id)
    rows = (
        await session.scalars(
            select(StudioSafetyReview)
            .where(StudioSafetyReview.asset_id == asset.id)
            .order_by(StudioSafetyReview.reviewed_at.desc())
        )
    ).all()
    return [production_studio.safety_snapshot(item) for item in rows]


@router.post("/assets/{asset_id}/attach", status_code=status.HTTP_201_CREATED)
async def attach_asset(
    asset_id: str,
    data: StudioAttachmentRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id)
    project = await session.scalar(
        select(Project).where(
            Project.id == data.project_id,
            Project.organization_id == actor.organization_id,
            Project.status != "deleted",
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    item = await session.scalar(
        select(ProjectStudioAttachment).where(
            ProjectStudioAttachment.project_id == project.id,
            ProjectStudioAttachment.asset_id == asset.id,
        )
    )
    if item is None:
        item = ProjectStudioAttachment(
            id=uuid_str(),
            organization_id=actor.organization_id,
            project_id=project.id,
            asset_id=asset.id,
            attached_by_id=actor.id,
            status="active",
        )
        session.add(item)
    else:
        item.status = "active"
        item.attached_by_id = actor.id
    if asset.project_id is None:
        asset.project_id = project.id
    session.add(
        ProjectEvent(
            id=uuid_str(),
            organization_id=actor.organization_id,
            project_id=project.id,
            actor_id=actor.id,
            event_type="studio.asset.attached",
            summary=f"Studio asset attached: {asset.title}",
            details={"asset_id": asset.id, "revision": asset.current_revision},
            created_at=_now(),
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Studio asset is already attached") from exc
    return production_studio.attachment_snapshot(item)


@router.delete("/assets/{asset_id}/attach/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_asset(
    asset_id: str,
    project_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id)
    item = await session.scalar(
        select(ProjectStudioAttachment)
        .where(
            ProjectStudioAttachment.asset_id == asset.id,
            ProjectStudioAttachment.project_id == project_id,
            ProjectStudioAttachment.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Studio attachment not found")
    item.status = "detached"
    session.add(
        ProjectEvent(
            id=uuid_str(),
            organization_id=actor.organization_id,
            project_id=project_id,
            actor_id=actor.id,
            event_type="studio.asset.detached",
            summary=f"Studio asset detached: {asset.title}",
            details={"asset_id": asset.id},
            created_at=_now(),
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/assets/{asset_id}/archive")
async def archive_asset(
    asset_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id, lock=True)
    asset.status = "archived"
    asset.archived_at = _now()
    await session.commit()
    return await _asset_snapshot(session, asset)


@router.post("/assets/{asset_id}/restore")
async def restore_asset(
    asset_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id, lock=True)
    asset.status = "active"
    asset.archived_at = None
    await session.commit()
    return await _asset_snapshot(session, asset)


@router.get("/statistics")
async def statistics(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    job_count_rows = (
        await session.execute(
            select(StudioJob.status, func.count(StudioJob.id))
            .where(StudioJob.organization_id == actor.organization_id)
            .group_by(StudioJob.status)
        )
    ).all()
    job_counts: dict[str, int] = {
        str(status): int(count) for status, count in job_count_rows
    }
    asset_count = int(
        await session.scalar(
            select(func.count(StudioAsset.id)).where(
                StudioAsset.organization_id == actor.organization_id,
                StudioAsset.status == "active",
            )
        )
        or 0
    )
    return {
        "jobs": {str(key): int(value) for key, value in job_counts.items()},
        "active_assets": asset_count,
        "provider_mode": "provider_neutral",
        "external_requests": 0,
        "provider_activation_batch": "29J",
    }


@router.post("/generate")
async def generate_artifact_compatibility(
    data: StudioRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Create a durable job and return the completed ZIP for older clients."""
    job = await _enqueue_job(data, actor, session)
    worker = StudioWorker()
    claim = await worker.claim_by_id(job.id)
    if claim is None:
        raise HTTPException(status_code=409, detail="Studio job could not be claimed")
    await worker.execute(*claim)
    async with get_db_context() as verification_session:
        completed = await verification_session.get(StudioJob, job.id)
        if completed is None:
            raise HTTPException(status_code=500, detail="Studio job disappeared")
        if completed.status == "blocked":
            raise HTTPException(status_code=422, detail="Studio safety policy blocked this request")
        if completed.status != "completed":
            raise HTTPException(status_code=500, detail="Studio job did not complete")
        asset = await verification_session.scalar(
            select(StudioAsset).where(StudioAsset.job_id == job.id)
        )
        if asset is None:
            raise HTTPException(status_code=500, detail="Studio asset was not created")
        verified = production_studio.verify_artifact(
            asset.storage_path, asset.checksum, asset.size_bytes
        )
        return FileResponse(
            verified,
            media_type=asset.media_type,
            filename=asset.filename,
            headers={
                "Cache-Control": "private, no-store",
                "X-AIONEX-Job-ID": job.id,
                "X-AIONEX-Asset-ID": asset.id,
                "X-AIONEX-Provider-Mode": "provider_neutral",
            },
        )


class _DatabaseContext:
    def __init__(self) -> None:
        from app.db.base import SessionLocal

        self._factory = SessionLocal
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self.session = self._factory()
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        assert self.session is not None
        await self.session.close()


def get_db_context() -> _DatabaseContext:
    return _DatabaseContext()
