"""Authenticated, project-scoped Phase 34D 3D generation API."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import ThreeDArtifact, ThreeDGenerationJob, uuid_str
from app.services import communications
from app.services.three_d_policy import get_three_d_policy
from app.services.three_d_resilience import (
    assert_provider_available,
    find_duplicate_job,
    normalize_idempotency_key,
    normalize_trace_id,
    request_fingerprint,
)
from app.services.three_d_product import (
    access_snapshot,
    audit_job,
    enforce_admission,
    image_suffix,
    job_snapshot,
    job_with_artifact,
    now,
    notify_job,
    project_for_actor,
    validate_image_payload,
)
from app.services.three_d_storage import GLB_MEDIA_TYPE, ThreeDObjectStore

router = APIRouter()


def _may_manage(
    actor: UserRecord, job: ThreeDGenerationJob, project_owner_id: str
) -> bool:
    return (
        actor.id == job.requested_by_id
        or actor.id == project_owner_id
        or actor.role == "Owner"
        or "*" in actor.permissions
    )


async def _publish(rows: list[object]) -> None:
    for row in rows:
        try:
            await communications.publish_realtime(row)  # type: ignore[arg-type]
        except Exception:
            continue


@router.get("/{project_id}/3d/access")
async def get_three_d_access(
    project_id: str,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    await project_for_actor(session, actor, project_id, write=False)
    snapshot = await access_snapshot(session, actor)
    await session.commit()
    return snapshot


@router.get("/{project_id}/3d/jobs")
async def list_three_d_jobs(
    project_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    await project_for_actor(session, actor, project_id, write=False)
    jobs = list(
        (
            await session.scalars(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.organization_id == actor.organization_id,
                    ThreeDGenerationJob.project_id == project_id,
                )
                .order_by(ThreeDGenerationJob.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    if not jobs:
        return []
    artifacts = list(
        (
            await session.scalars(
                select(ThreeDArtifact).where(
                    ThreeDArtifact.job_id.in_([item.id for item in jobs])
                )
            )
        ).all()
    )
    by_job = {item.job_id: item for item in artifacts}
    return [job_snapshot(item, by_job.get(item.id)) for item in jobs]


@router.post("/{project_id}/3d/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_three_d_job(
    project_id: str,
    image: Annotated[UploadFile, File(description="PNG, JPEG, or WebP source image")],
    seed: Annotated[int, Form(ge=0, le=2_147_483_647)] = 12345,
    texture_size: Annotated[int | None, Form(ge=512, le=4096)] = None,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
    idempotency_key_header: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=200)
    ] = None,
    trace_header: Annotated[
        str | None, Header(alias="X-Correlation-ID", max_length=160)
    ] = None,
):
    project = await project_for_actor(session, actor, project_id, write=True)
    initial = await access_snapshot(session, actor)
    if not initial["eligible"]:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "THREE_D_ACCESS_NOT_GRANTED",
                "message": "3D access is controlled by the Super Owner and the highest eligible plan",
            },
        )
    if initial["monthly_used"] >= initial["monthly_quota"]:
        raise HTTPException(
            status_code=402, detail={"code": "THREE_D_MONTHLY_QUOTA_REACHED"}
        )
    if initial["active_jobs"] >= initial["max_concurrent_jobs"]:
        raise HTTPException(
            status_code=409, detail={"code": "THREE_D_CONCURRENCY_LIMIT"}
        )
    max_bytes = int(initial["max_input_megabytes"]) * 1024 * 1024
    body = await image.read(max_bytes + 1)
    content_type = str(image.content_type or "").strip().lower()
    validate_image_payload(content_type, body, max_bytes)

    policy = await get_three_d_policy(session)
    selected_texture = min(
        int(texture_size or policy["max_texture_size"]),
        int(policy["max_texture_size"]),
    )
    from hashlib import sha256

    image_sha = sha256(body).hexdigest()
    fingerprint = request_fingerprint(
        organization_id=actor.organization_id,
        user_id=actor.id,
        project_id=project.id,
        image_sha256=image_sha,
        seed=seed,
        texture_size=selected_texture,
        compression_policy=policy["compression_policy"],
    )
    idempotency_namespace = f"{actor.organization_id}:{actor.id}:{project.id}"
    idempotency_key = normalize_idempotency_key(
        idempotency_key_header,
        fingerprint=fingerprint,
        namespace=idempotency_namespace,
        window_seconds=int(policy["duplicate_window_seconds"]),
    )
    duplicate = await find_duplicate_job(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        project_id=project.id,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        window_seconds=int(policy["duplicate_window_seconds"]),
    )
    if duplicate is not None:
        if (
            duplicate.request_fingerprint
            and duplicate.request_fingerprint != fingerprint
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "THREE_D_IDEMPOTENCY_CONFLICT",
                    "message": "The Idempotency-Key was already used for a different 3D request.",
                },
            )
        artifact = await session.scalar(
            select(ThreeDArtifact).where(ThreeDArtifact.job_id == duplicate.id)
        )
        await session.commit()
        return job_snapshot(duplicate, artifact)

    await assert_provider_available(session)
    job_id = uuid_str()
    trace_id = normalize_trace_id(trace_header)
    store = ThreeDObjectStore()
    key = store.input_key(
        actor.organization_id, project.id, job_id, image_suffix(content_type)
    )
    stored = store.put_bytes(
        key,
        body,
        content_type,
        metadata={
            "organization_id": actor.organization_id,
            "project_id": project.id,
            "job_id": job_id,
            "trace_id": trace_id,
        },
    )
    try:
        policy, admission = await enforce_admission(session, actor)
        job = ThreeDGenerationJob(
            id=job_id,
            organization_id=actor.organization_id,
            workspace_id=project.workspace_id,
            project_id=project.id,
            requested_by_id=actor.id,
            provider="runpod",
            status="queued",
            stage="queued",
            progress=0,
            input_object_key=stored.key,
            input_content_type=stored.content_type,
            input_size_bytes=stored.size_bytes,
            input_sha256=stored.sha256,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            trace_id=trace_id,
            request_options={
                "seed": seed,
                "texture_size": selected_texture,
                "compression_policy": policy["compression_policy"],
                "allow_shape_fallback": False,
            },
            estimated_cost_usd=float(admission["reserved_estimated_cost_usd"]),
            metering_status="pending",
            max_attempts=max(1, int(policy["max_retries"]) + 1),
        )
        session.add(job)
        session.add(
            audit_job(
                job,
                "3d.job.queued",
                actor_id=actor.id,
                details={
                    "input_size_bytes": stored.size_bytes,
                    "trace_id": trace_id,
                    "idempotent": True,
                },
            )
        )
        notifications = await notify_job(
            session,
            job,
            event_key="3d.job.queued",
            title="3D generation queued",
            message=f"{project.name}: your private source image has been accepted and queued for 3D generation.",
            include_owner=True,
            actor_id=actor.id,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        store.delete(key)
        duplicate = await find_duplicate_job(
            session,
            organization_id=actor.organization_id,
            user_id=actor.id,
            project_id=project.id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            window_seconds=int(policy["duplicate_window_seconds"]),
        )
        if duplicate is None:
            raise
        if (
            duplicate.request_fingerprint
            and duplicate.request_fingerprint != fingerprint
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "THREE_D_IDEMPOTENCY_CONFLICT"},
            )
        artifact = await session.scalar(
            select(ThreeDArtifact).where(ThreeDArtifact.job_id == duplicate.id)
        )
        return job_snapshot(duplicate, artifact)
    except Exception:
        await session.rollback()
        store.delete(key)
        raise
    await _publish(notifications)
    return job_snapshot(job)


@router.get("/{project_id}/3d/jobs/{job_id}")
async def get_three_d_job(
    project_id: str,
    job_id: str,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    await project_for_actor(session, actor, project_id, write=False)
    job, artifact = await job_with_artifact(
        session, job_id, actor.organization_id, project_id
    )
    return job_snapshot(job, artifact)


@router.post("/{project_id}/3d/jobs/{job_id}/cancel")
async def cancel_three_d_job(
    project_id: str,
    job_id: str,
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    project = await project_for_actor(session, actor, project_id, write=True)
    job, artifact = await job_with_artifact(
        session, job_id, actor.organization_id, project_id, lock=True
    )
    if not _may_manage(actor, job, project.owner_id):
        raise HTTPException(
            status_code=403,
            detail="Only the requester or project owner can cancel this 3D job",
        )
    if job.status not in {"queued", "running", "cancel_requested"}:
        raise HTTPException(
            status_code=409, detail="Only an active 3D job can be cancelled"
        )
    immediate_cancel = job.status == "queued" and not job.provider_job_id
    input_key = job.input_object_key if immediate_cancel else None
    if immediate_cancel:
        job.status = "cancelled"
        job.stage = "cancelled"
        job.progress = 100
        job.cancel_requested_at = now()
        job.cancelled_at = now()
        job.completed_at = now()
    else:
        job.status = "cancel_requested"
        job.stage = "cancelling"
        job.cancel_requested_at = now()
        job.progress = max(job.progress, 5)
    job.version += 1
    session.add(audit_job(job, "3d.job.cancel_requested", actor_id=actor.id))
    notifications = await notify_job(
        session,
        job,
        event_key="3d.job.cancel_requested",
        title="3D generation cancellation requested",
        message=f"{project.name}: cancellation is being applied safely.",
        include_owner=True,
        actor_id=actor.id,
    )
    await session.commit()
    if input_key:
        ThreeDObjectStore().delete(input_key)
    await _publish(notifications)
    return job_snapshot(job, artifact)


@router.post("/{project_id}/3d/jobs/{job_id}/clarify")
async def clarify_three_d_job(
    project_id: str,
    job_id: str,
    image: Annotated[
        UploadFile, File(description="Replacement PNG, JPEG, or WebP source image")
    ],
    actor: UserRecord = Depends(require_permissions("projects:write")),
    session: AsyncSession = Depends(get_db),
):
    project = await project_for_actor(session, actor, project_id, write=True)
    job, artifact = await job_with_artifact(
        session, job_id, actor.organization_id, project_id, lock=True
    )
    if not _may_manage(actor, job, project.owner_id):
        raise HTTPException(
            status_code=403,
            detail="Only the requester or project owner can clarify this 3D job",
        )
    if job.status != "needs_clarification":
        raise HTTPException(
            status_code=409, detail="This 3D job is not waiting for clarification"
        )
    snapshot = await access_snapshot(session, actor, lock_policy=True)
    if not snapshot["eligible"]:
        raise HTTPException(
            status_code=402, detail={"code": "THREE_D_ACCESS_NOT_GRANTED"}
        )
    if snapshot["active_jobs"] >= snapshot["max_concurrent_jobs"]:
        raise HTTPException(
            status_code=409, detail={"code": "THREE_D_CONCURRENCY_LIMIT"}
        )
    policy = await get_three_d_policy(session)
    max_bytes = int(policy["max_input_megabytes"]) * 1024 * 1024
    body = await image.read(max_bytes + 1)
    content_type = str(image.content_type or "").strip().lower()
    validate_image_payload(content_type, body, max_bytes)
    store = ThreeDObjectStore()
    old_key = job.input_object_key
    new_key = store.input_key(
        actor.organization_id, project.id, job.id, image_suffix(content_type)
    )
    stored = store.put_bytes(
        new_key,
        body,
        content_type,
        metadata={
            "organization_id": actor.organization_id,
            "project_id": project.id,
            "job_id": job.id,
        },
    )
    try:
        job.input_object_key = stored.key
        job.input_content_type = stored.content_type
        job.input_size_bytes = stored.size_bytes
        job.input_sha256 = stored.sha256
        job.status = "queued"
        job.stage = "queued"
        job.progress = 0
        job.provider_job_id = None
        job.provider_delay_ms = None
        job.provider_execution_ms = None
        job.error_code = None
        job.error_message = None
        job.lease_token = None
        job.attempts = 0
        job.max_attempts = max(1, int(policy["max_retries"]) + 1)
        job.completed_at = None
        job.cancel_requested_at = None
        job.cancelled_at = None
        job.version += 1
        session.add(
            audit_job(
                job,
                "3d.job.clarified",
                actor_id=actor.id,
                details={"input_size_bytes": stored.size_bytes},
            )
        )
        notifications = await notify_job(
            session,
            job,
            event_key="3d.job.clarified",
            title="3D source image updated",
            message=f"{project.name}: the replacement image was accepted and generation has been queued again.",
            include_owner=True,
            actor_id=actor.id,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        if new_key != old_key:
            store.delete(new_key)
        raise
    if old_key != new_key:
        store.delete(old_key)
    await _publish(notifications)
    return job_snapshot(job, artifact)


@router.get("/{project_id}/3d/jobs/{job_id}/artifact")
async def get_three_d_artifact_links(
    project_id: str,
    job_id: str,
    actor: UserRecord = Depends(require_permissions("projects:read")),
    session: AsyncSession = Depends(get_db),
):
    await project_for_actor(session, actor, project_id, write=False)
    job, artifact = await job_with_artifact(
        session, job_id, actor.organization_id, project_id
    )
    if job.status != "completed" or artifact is None or artifact.status != "ready":
        raise HTTPException(status_code=409, detail="3D artifact is not ready")
    if artifact.expires_at is not None:
        expires_at = artifact.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=now().tzinfo)
        if expires_at <= now():
            raise HTTPException(
                status_code=410, detail="3D artifact retention period has expired"
            )
    policy = await access_snapshot(session, actor)
    if not policy["eligible"]:
        raise HTTPException(
            status_code=402, detail={"code": "THREE_D_ACCESS_NOT_GRANTED"}
        )
    ttl = int(policy["signed_url_ttl_seconds"])
    store = ThreeDObjectStore()
    view_url = store.presigned_get(
        artifact.object_key,
        filename=artifact.filename,
        content_type=GLB_MEDIA_TYPE,
        expires_seconds=ttl,
        inline=True,
    )
    download_url = store.presigned_get(
        artifact.object_key,
        filename=artifact.filename,
        content_type=GLB_MEDIA_TYPE,
        expires_seconds=ttl,
        inline=False,
    )
    session.add(
        audit_job(
            job,
            "3d.artifact.links_issued",
            actor_id=actor.id,
            details={"artifact_id": artifact.id, "expires_in": ttl},
        )
    )
    await session.commit()
    return {
        "job_id": job.id,
        "artifact_id": artifact.id,
        "filename": artifact.filename,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.checksum,
        "view_url": view_url,
        "download_url": download_url,
        "expires_in": ttl,
        "expires_at": (now() + timedelta(seconds=ttl)).isoformat(),
    }
