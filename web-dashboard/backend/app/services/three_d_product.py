"""Phase 34D product-layer admission, snapshots, notifications and cost/quota logic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    BillingAccount,
    Project,
    ProjectMembership,
    ThreeDArtifact,
    ThreeDGenerationJob,
)
from app.services import billing, communications
from app.services.three_d_resilience import assert_provider_available, spend_snapshot
from app.services.three_d_policy import (
    get_three_d_policy,
    get_three_d_policy_for_update,
    three_d_access_allowed,
)

ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "needs_clarification"}


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def month_start(moment: datetime | None = None) -> datetime:
    value = (moment or now()).astimezone(UTC)
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def day_start(moment: datetime | None = None) -> datetime:
    value = (moment or now()).astimezone(UTC)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def image_suffix(content_type: str) -> str:
    value = content_type.strip().lower()
    return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
        value, "img"
    )


def validate_image_payload(content_type: str, body: bytes, max_bytes: int) -> None:
    if not body:
        raise HTTPException(
            status_code=422,
            detail={"code": "THREE_D_IMAGE_EMPTY", "message": "Source image is empty"},
        )
    if len(body) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "THREE_D_IMAGE_TOO_LARGE",
                "message": "Source image exceeds the Owner-defined size limit",
                "max_bytes": max_bytes,
            },
        )
    content_type = content_type.strip().lower()
    signatures = {
        "image/png": body.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": body.startswith(b"\xff\xd8\xff"),
        "image/webp": len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP",
    }
    if content_type not in signatures or not signatures[content_type]:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "THREE_D_IMAGE_UNSUPPORTED",
                "message": "Upload a valid PNG, JPEG, or WebP source image",
            },
        )


async def project_for_actor(
    session: AsyncSession, actor: UserRecord, project_id: str, *, write: bool
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.organization_id == actor.organization_id,
            Project.status != "deleted",
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    elevated = "*" in actor.permissions or actor.role == "Owner"
    member = project.owner_id == actor.id
    if not member:
        member = bool(
            await session.scalar(
                select(ProjectMembership.id).where(
                    ProjectMembership.project_id == project.id,
                    ProjectMembership.organization_id == actor.organization_id,
                    ProjectMembership.user_id == actor.id,
                    ProjectMembership.status == "active",
                )
            )
        )
    if not elevated and not member:
        raise HTTPException(
            status_code=403, detail="Project membership is required for 3D generation"
        )
    required = "projects:write" if write else "projects:read"
    if "*" not in actor.permissions and required not in actor.permissions:
        raise HTTPException(status_code=403, detail=f"Missing permission: {required}")
    return project


async def _billing_access(
    session: AsyncSession, actor: UserRecord
) -> tuple[dict[str, Any], str, list[str]]:
    context = await billing.billing_context(session, actor.organization_id)
    account: BillingAccount = context["account"]
    if account.status not in billing.ACTIVE_ACCOUNT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Organization billing access is suspended",
        )
    plan = context.get("plan")
    plan_code = (
        str(getattr(plan, "code", None) or actor.organization_plan or "")
        .strip()
        .lower()
    )
    entitlements = list(context.get("entitlements") or [])
    return context, plan_code, entitlements


def _effective_monthly_quota(policy: dict[str, Any], context: dict[str, Any]) -> int:
    owner_limit = int(policy["monthly_jobs_per_user"])
    raw_plan_limit = dict(context.get("limits") or {}).get("3d_generations")
    if raw_plan_limit is None:
        return owner_limit
    try:
        plan_limit = int(raw_plan_limit)
    except (TypeError, ValueError):
        return owner_limit
    if plan_limit < 0:
        return owner_limit
    return min(owner_limit, plan_limit)


async def access_snapshot(
    session: AsyncSession,
    actor: UserRecord,
    *,
    lock_policy: bool = False,
) -> dict[str, Any]:
    policy = await (
        get_three_d_policy_for_update(session)
        if lock_policy
        else get_three_d_policy(session)
    )
    context, plan_code, entitlements = await _billing_access(session, actor)
    allowed = three_d_access_allowed(
        policy,
        user_id=actor.id,
        plan_code=plan_code,
        entitlements=entitlements,
    )
    monthly_used = int(
        await session.scalar(
            select(func.count(ThreeDGenerationJob.id)).where(
                ThreeDGenerationJob.organization_id == actor.organization_id,
                ThreeDGenerationJob.requested_by_id == actor.id,
                ThreeDGenerationJob.created_at >= month_start(),
                ThreeDGenerationJob.status.in_(
                    {"queued", "running", "cancel_requested", "completed"}
                ),
            )
        )
        or 0
    )
    active = int(
        await session.scalar(
            select(func.count(ThreeDGenerationJob.id)).where(
                ThreeDGenerationJob.organization_id == actor.organization_id,
                ThreeDGenerationJob.requested_by_id == actor.id,
                ThreeDGenerationJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )
    quota = _effective_monthly_quota(policy, context)
    return {
        "eligible": allowed,
        "plan_code": plan_code,
        "required_entitlement": policy["required_entitlement"],
        "monthly_quota": quota,
        "monthly_used": monthly_used,
        "monthly_remaining": max(0, quota - monthly_used),
        "active_jobs": active,
        "max_concurrent_jobs": policy["max_concurrent_jobs_per_user"],
        "max_input_megabytes": policy["max_input_megabytes"],
        "max_texture_size": policy["max_texture_size"],
        "compression_policy": policy["compression_policy"],
        "signed_url_ttl_seconds": policy["signed_url_ttl_seconds"],
        "owner_managed": True,
        "service_enabled": policy["enabled"],
    }


async def enforce_admission(
    session: AsyncSession, actor: UserRecord
) -> tuple[dict[str, Any], dict[str, Any]]:
    await assert_provider_available(session)
    snapshot = await access_snapshot(session, actor, lock_policy=True)
    policy = await get_three_d_policy(session)
    if not snapshot["eligible"]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "THREE_D_ACCESS_NOT_GRANTED",
                "message": "3D access is controlled by the Super Owner and the highest eligible plan",
            },
        )
    if snapshot["monthly_used"] >= snapshot["monthly_quota"]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "THREE_D_MONTHLY_QUOTA_REACHED",
                "allowed": snapshot["monthly_quota"],
                "used": snapshot["monthly_used"],
            },
        )
    if snapshot["active_jobs"] >= snapshot["max_concurrent_jobs"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "THREE_D_CONCURRENCY_LIMIT",
                "allowed": snapshot["max_concurrent_jobs"],
                "active": snapshot["active_jobs"],
            },
        )
    estimated = float(settings.THREE_D_GPU_COST_PER_SECOND_USD) * int(
        policy["max_runtime_seconds"]
    )
    if estimated > float(policy["max_estimated_job_cost_usd"]):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "THREE_D_JOB_COST_BLOCKED",
                "estimated_usd": round(estimated, 6),
            },
        )
    spend = await spend_snapshot(session)
    daily = float(spend["daily_usd"])
    monthly = float(spend["monthly_usd"])
    if daily + estimated > float(policy["daily_spend_limit_usd"]):
        raise HTTPException(
            status_code=402, detail={"code": "THREE_D_DAILY_SPEND_BLOCKED"}
        )
    if monthly + estimated > float(policy["monthly_spend_limit_usd"]):
        raise HTTPException(
            status_code=402, detail={"code": "THREE_D_MONTHLY_SPEND_BLOCKED"}
        )
    snapshot["reserved_estimated_cost_usd"] = round(estimated, 6)
    snapshot["daily_spend_usd"] = round(daily, 6)
    snapshot["monthly_spend_usd"] = round(monthly, 6)
    return policy, snapshot


def job_snapshot(
    job: ThreeDGenerationJob, artifact: ThreeDArtifact | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": job.id,
        "project_id": job.project_id,
        "workspace_id": job.workspace_id,
        "organization_id": job.organization_id,
        "requested_by_id": job.requested_by_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "provider": job.provider,
        "provider_job_id": job.provider_job_id,
        "trace_id": job.trace_id,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "estimated_cost_usd": round(float(job.estimated_cost_usd or 0.0), 6),
        "metering_status": job.metering_status,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": iso(job.created_at),
        "updated_at": iso(job.updated_at),
        "started_at": iso(job.started_at),
        "cancel_requested_at": iso(job.cancel_requested_at),
        "cancelled_at": iso(job.cancelled_at),
        "completed_at": iso(job.completed_at),
        "has_artifact": artifact is not None and artifact.status == "ready",
        "artifact": None,
    }
    if artifact is not None:
        result["artifact"] = {
            "id": artifact.id,
            "filename": artifact.filename,
            "media_type": artifact.media_type,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.checksum,
            "status": artifact.status,
            "metadata": artifact.artifact_metadata or {},
            "expires_at": iso(artifact.expires_at),
        }
    return result


async def job_with_artifact(
    session: AsyncSession,
    job_id: str,
    organization_id: str,
    project_id: str,
    *,
    lock: bool = False,
) -> tuple[ThreeDGenerationJob, ThreeDArtifact | None]:
    stmt = select(ThreeDGenerationJob).where(
        ThreeDGenerationJob.id == job_id,
        ThreeDGenerationJob.organization_id == organization_id,
        ThreeDGenerationJob.project_id == project_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    job = await session.scalar(stmt)
    if job is None:
        raise HTTPException(status_code=404, detail="3D generation job not found")
    artifact = await session.scalar(
        select(ThreeDArtifact).where(ThreeDArtifact.job_id == job.id)
    )
    return job, artifact


async def notify_job(
    session: AsyncSession,
    job: ThreeDGenerationJob,
    *,
    event_key: str,
    title: str,
    message: str,
    severity: str = "info",
    include_owner: bool = False,
    actor_id: str | None = None,
) -> list[Any]:
    payload = {
        "project_id": job.project_id,
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
    }
    rows = await communications.notify_audience(
        session,
        organization_id=job.organization_id,
        audience="user",
        explicit_user_ids=[job.requested_by_id],
        event_key=event_key,
        category="three-d",
        title=title,
        message=message,
        severity=severity,
        source_type="three_d_generation_job",
        source_id=job.id,
        correlation_id=job.id,
        dedupe_prefix=f"{event_key}:{job.id}",
        payload=payload,
        actor_id=actor_id,
    )
    if include_owner:
        rows += await communications.notify_audience(
            session,
            organization_id=job.organization_id,
            audience="owner",
            event_key=event_key,
            category="three-d",
            title=title,
            message=message,
            severity=severity,
            source_type="three_d_generation_job",
            source_id=job.id,
            correlation_id=job.id,
            dedupe_prefix=f"owner:{event_key}:{job.id}",
            payload=payload,
            actor_id=actor_id,
        )
    return rows


def audit_job(
    job: ThreeDGenerationJob,
    action: str,
    *,
    actor_id: str | None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=job.organization_id,
        user_id=actor_id,
        action=action,
        resource_type="three_d_generation_job",
        resource_id=job.id,
        details={
            "project_id": job.project_id,
            "status": job.status,
            "stage": job.stage,
            **(details or {}),
        },
    )


def provider_error_requires_clarification(message: str) -> bool:
    value = message.lower()
    markers = (
        "unidentifiedimageerror",
        "cannot identify image",
        "invalid image",
        "image decode",
        "source image",
        "input image",
    )
    return any(marker in value for marker in markers)
