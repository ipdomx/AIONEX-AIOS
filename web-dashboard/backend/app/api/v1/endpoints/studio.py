"""Durable provider-neutral Production Studio API for Phase 29H."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any, Literal

from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    MediaAssetGraph,
    MediaAssetNode,
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
from app.services import media_graph_runtime
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec, output_profile
from app.services.media_storage import (
    LocalMediaObjectStore,
    MediaStorageError,
    media_object_store,
    media_object_store_for_backend,
)
from app.services.production_studio import DEPARTMENTS
from app.services.studio_worker import StudioWorker
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, RedirectResponse
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

class MediaGraphNodeRequest(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    node_type: str = Field(min_length=1, max_length=40)
    media_type: str | None = Field(default=None, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)
    prompt_metadata: dict[str, Any] = Field(default_factory=dict)
    rights_metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    scene_metadata: dict[str, Any] = Field(default_factory=dict)
    timeline_metadata: dict[str, Any] = Field(default_factory=dict)


class MediaGraphEdgeRequest(BaseModel):
    parent: str = Field(min_length=1, max_length=160)
    child: str = Field(min_length=1, max_length=160)
    dependency_type: str = Field(default="input", min_length=1, max_length=40)
    ordinal: int = Field(default=0, ge=0, le=10000)


class MediaGraphCreateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    asset_kind: Literal["image", "audio", "video", "animation", "3d", "mixed"] = "video"
    output_profile: str = Field(default="video-mp4-h264", min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)
    nodes: list[MediaGraphNodeRequest] = Field(min_length=1, max_length=100)
    edges: list[MediaGraphEdgeRequest] = Field(default_factory=list, max_length=300)
    rights_metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class MediaGraphRevisionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    node_parameter_updates: dict[str, dict[str, Any]] = Field(min_length=1, max_length=100)



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
    revision_metadata: dict[str, Any] = dict(asset.asset_metadata or {})
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
        revision_metadata = dict(item.revision_metadata or {})
    media_output = revision_metadata.get("media_graph_output")
    if isinstance(media_output, dict):
        storage_backend = str(media_output.get("storage_backend") or "").strip().lower()
        storage_key = str(media_output.get("storage_key") or path).strip()
        if not storage_backend or not storage_key:
            raise HTTPException(status_code=409, detail="Rendered media storage metadata is incomplete")
        try:
            store = media_object_store_for_backend(storage_backend)
            if isinstance(store, LocalMediaObjectStore):
                verified = store.verified_path(
                    storage_key, checksum=checksum, size_bytes=size_bytes
                )
                return FileResponse(
                    verified,
                    media_type=media_type,
                    filename=filename,
                    headers={
                        "Cache-Control": "private, no-store",
                        "X-AIONEX-Checksum-SHA256": checksum,
                        "X-AIONEX-Media-Graph": str(media_output.get("graph_id") or ""),
                    },
                )
            url = store.presigned_get(
                storage_key,
                filename=filename,
                content_type=media_type,
                expires_seconds=900,
                inline=False,
            )
        except MediaStorageError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not url:
            raise HTTPException(status_code=409, detail="Rendered media download is unavailable")
        return RedirectResponse(
            url=url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={
                "Cache-Control": "private, no-store",
                "X-AIONEX-Checksum-SHA256": checksum,
            },
        )
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

_ALLOWED_MEDIA_OPERATIONS = frozenset({"render_scene", "assemble", "transcode", "render_image", "render_audio"})


def _media_node_spec(data: MediaGraphNodeRequest) -> MediaNodeSpec:
    parameters = dict(data.parameters)
    operation = str(parameters.get("operation") or "").strip().lower()
    if operation and operation not in _ALLOWED_MEDIA_OPERATIONS:
        raise HTTPException(status_code=422, detail="Unsupported media render operation")
    hardware = str(parameters.get("hardware_adapter") or "software").strip().lower()
    if hardware != "software":
        raise HTTPException(status_code=422, detail="Hardware media adapter requires an operator-governed policy")
    profile_id = str(parameters.get("output_profile") or "").strip()
    if profile_id:
        try:
            output_profile(profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Unknown media output profile") from exc
    return MediaNodeSpec(
        key=data.key,
        node_type=data.node_type,
        media_type=data.media_type,
        parameters=parameters,
        prompt_metadata=dict(data.prompt_metadata),
        rights_metadata=dict(data.rights_metadata),
        provenance=tuple(data.provenance),
        scene_metadata=dict(data.scene_metadata),
        timeline_metadata=dict(data.timeline_metadata),
    )


async def _media_graph_or_404(
    session: AsyncSession, actor: UserRecord, graph_id: str, *, lock: bool = False
) -> MediaAssetGraph:
    statement = select(MediaAssetGraph).where(
        MediaAssetGraph.id == graph_id,
        MediaAssetGraph.organization_id == actor.organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    graph = await session.scalar(statement)
    if graph is None:
        raise HTTPException(status_code=404, detail="Media graph not found")
    return graph


@router.post("/assets/{asset_id}/media-graphs", status_code=status.HTTP_202_ACCEPTED)
async def create_asset_media_graph(
    asset_id: str,
    data: MediaGraphCreateRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    asset = await _asset_or_404(session, actor, asset_id)
    original = await session.get(StudioJob, asset.job_id)
    if original is None or original.organization_id != actor.organization_id:
        raise HTTPException(status_code=409, detail="Original Studio job is unavailable")
    try:
        spec = MediaGraphSpec(
            title=data.title or asset.title,
            asset_kind=data.asset_kind,
            nodes=tuple(_media_node_spec(item) for item in data.nodes),
            edges=tuple(
                MediaEdgeSpec(
                    parent=item.parent,
                    child=item.child,
                    dependency_type=item.dependency_type,
                    ordinal=item.ordinal,
                )
                for item in data.edges
            ),
            output_profile=data.output_profile,
            rights_metadata=dict(data.rights_metadata),
            provenance=tuple(data.provenance),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    graph = await media_graph_runtime.create_media_graph(
        session,
        scope=media_graph_runtime.MediaGraphScope(
            organization_id=actor.organization_id,
            created_by_id=actor.id,
            workspace_id=original.workspace_id,
            project_id=asset.project_id or original.project_id,
            studio_job_id=original.id,
            studio_asset_id=asset.id,
        ),
        spec=spec,
        idempotency_key=data.idempotency_key,
    )
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="media.graph.created",
            resource_type="media_asset_graph",
            resource_id=graph.id,
            details={
                "studio_asset_id": asset.id,
                "graph_version": graph.graph_version,
                "output_profile": graph.output_profile,
                "node_count": len(spec.nodes),
            },
        )
    )
    await session.commit()
    await session.refresh(graph)
    return await media_graph_runtime.media_graph_snapshot(session, graph)


@router.get("/assets/{asset_id}/media-graphs")
async def list_asset_media_graphs(
    asset_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    await _asset_or_404(session, actor, asset_id)
    graphs = list(
        (
            await session.scalars(
                select(MediaAssetGraph)
                .where(
                    MediaAssetGraph.studio_asset_id == asset_id,
                    MediaAssetGraph.organization_id == actor.organization_id,
                )
                .order_by(MediaAssetGraph.graph_version.desc(), MediaAssetGraph.created_at.desc())
            )
        ).all()
    )
    return [await media_graph_runtime.media_graph_snapshot(session, item) for item in graphs]


@router.get("/media-graphs/{graph_id}")
async def get_media_graph(
    graph_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await media_graph_runtime.media_graph_snapshot(
        session, await _media_graph_or_404(session, actor, graph_id)
    )


@router.post("/media-graphs/{graph_id}/revisions", status_code=status.HTTP_202_ACCEPTED)
async def revise_media_graph(
    graph_id: str,
    data: MediaGraphRevisionRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    graph = await _media_graph_or_404(session, actor, graph_id)
    if graph.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed media graphs can be revised")
    for update in data.node_parameter_updates.values():
        operation = str(update.get("operation") or "").strip().lower()
        if operation and operation not in _ALLOWED_MEDIA_OPERATIONS:
            raise HTTPException(status_code=422, detail="Unsupported media render operation")
        hardware = str(update.get("hardware_adapter") or "software").strip().lower()
        if hardware != "software":
            raise HTTPException(status_code=422, detail="Hardware media adapter requires an operator-governed policy")
    try:
        revised, affected = await media_graph_runtime.create_partial_media_revision(
            session,
            graph=graph,
            created_by_id=actor.id,
            node_parameter_updates=data.node_parameter_updates,
            idempotency_key=data.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="media.graph.revised",
            resource_type="media_asset_graph",
            resource_id=revised.id,
            details={"source_graph_id": graph.id, "affected_nodes": list(affected)},
        )
    )
    await session.commit()
    await session.refresh(revised)
    return await media_graph_runtime.media_graph_snapshot(session, revised)


@router.get("/media-graphs/{graph_id}/output")
async def get_media_graph_output(
    graph_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    graph = await _media_graph_or_404(session, actor, graph_id)
    if graph.status != "completed":
        raise HTTPException(status_code=409, detail="Media graph is not completed")
    final_node_id = str((graph.graph_metadata or {}).get("final_node_id") or "")
    node = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.graph_id == graph.id,
            MediaAssetNode.organization_id == actor.organization_id,
            MediaAssetNode.id == final_node_id,
            MediaAssetNode.status == "completed",
        )
    )
    if node is None or not node.storage_key or not node.checksum or not node.media_type:
        raise HTTPException(status_code=409, detail="Rendered media output is unavailable")
    store = media_object_store()
    profile = output_profile(graph.output_profile)
    filename = f"{production_studio.slug(graph.title)}-v{graph.graph_version}.{profile.extension}"
    try:
        url = store.presigned_get(
            node.storage_key,
            filename=filename,
            content_type=node.media_type,
            expires_seconds=900,
            inline=False,
        )
        if url:
            return {
                "mode": "presigned",
                "url": url,
                "filename": filename,
                "media_type": node.media_type,
                "checksum": node.checksum,
                "size_bytes": node.size_bytes,
            }
        body = store.get_bytes(
            node.storage_key,
            max_bytes=min(settings.MEDIA_MAX_OBJECT_BYTES, 256 * 1024 * 1024),
        )
    except MediaStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if hashlib.sha256(body).hexdigest() != node.checksum:
        raise HTTPException(status_code=409, detail="Rendered media checksum verification failed")
    return Response(
        content=body,
        media_type=node.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AIONEX-Checksum-SHA256": node.checksum,
            "Cache-Control": "private, no-store",
        },
    )
