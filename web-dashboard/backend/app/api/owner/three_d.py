"""Super Owner control surface for 3D access, cost, observability and recovery."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services.three_d_policy import get_three_d_policy, update_three_d_policy
from app.services.three_d_provider_policy import (
    HUNYUAN_QUARANTINED_IMAGE_DIGEST,
    HUNYUAN_RUNTIME_SECURITY_APPROVED,
)
from app.services.three_d_resilience import (
    cleanup_expired_three_d_data,
    operations_snapshot,
    prometheus_snapshot,
    reset_provider_circuit,
)
from app.services.three_d_storage import ThreeDObjectStore

router = APIRouter(prefix="/owner/3d", tags=["owner-3d"])


class ThreeDPolicyUpdate(BaseModel):
    enabled: bool | None = None
    allowed_plan_codes: list[str] | None = None
    required_entitlement: str | None = Field(default=None, min_length=1, max_length=120)
    allowed_user_ids: list[str] | None = None
    denied_user_ids: list[str] | None = None
    max_concurrent_jobs_per_user: int | None = Field(default=None, ge=1, le=4)
    max_runtime_seconds: int | None = Field(default=None, ge=60, le=3600)
    max_queue_seconds: int | None = Field(default=None, ge=10, le=1800)
    max_retries: int | None = Field(default=None, ge=0, le=3)
    max_estimated_job_cost_usd: float | None = Field(default=None, gt=0, le=100)
    daily_spend_limit_usd: float | None = Field(default=None, gt=0, le=10000)
    monthly_spend_limit_usd: float | None = Field(default=None, gt=0, le=100000)
    owner_alert_threshold_pct: int | None = Field(default=None, ge=1, le=100)
    monthly_jobs_per_user: int | None = Field(default=None, ge=1, le=1000)
    max_input_megabytes: int | None = Field(default=None, ge=1, le=50)
    max_texture_size: int | None = Field(default=None, ge=512, le=4096)
    artifact_retention_days: int | None = Field(default=None, ge=1, le=365)
    signed_url_ttl_seconds: int | None = Field(default=None, ge=60, le=3600)
    compression_policy: Literal["compat", "meshopt"] | None = None
    duplicate_window_seconds: int | None = Field(default=None, ge=30, le=86400)
    provider_failure_threshold: int | None = Field(default=None, ge=1, le=20)
    provider_circuit_open_seconds: int | None = Field(default=None, ge=30, le=3600)
    cleanup_interval_seconds: int | None = Field(default=None, ge=30, le=3600)
    cleanup_batch_size: int | None = Field(default=None, ge=1, le=1000)
    temporary_input_retention_hours: int | None = Field(default=None, ge=1, le=168)
    hunyuan_license_acknowledged: bool | None = None
    hunyuan_commercial_eligibility_attested: bool | None = None
    service_provider_legal_name_confirmed: bool | None = None
    hunyuan_excluded_country_codes: list[str] | None = None
    fallback_enabled: bool | None = None
    service_provider_legal_name: str | None = Field(
        default=None, min_length=1, max_length=200
    )
    third_party_terms_version: str | None = Field(
        default=None, min_length=1, max_length=120
    )


async def _snapshot(session: AsyncSession) -> dict[str, Any]:
    return {
        "policy": await get_three_d_policy(session),
        "operations": await operations_snapshot(session),
        "runtime_security": {
            "hunyuan3d": {
                "approved": HUNYUAN_RUNTIME_SECURITY_APPROVED,
                "quarantined_image_digest": HUNYUAN_QUARANTINED_IMAGE_DIGEST,
                "activation_requires_new_gpu_security_acceptance": (
                    not HUNYUAN_RUNTIME_SECURITY_APPROVED
                ),
            },
            "triposr": {"approved": True},
        },
    }


@router.get("")
async def owner_three_d_policy(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del actor
    result = await _snapshot(session)
    await session.commit()
    return result


@router.patch("")
async def patch_owner_three_d_policy(
    data: ThreeDPolicyUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)
    await update_three_d_policy(session, updates)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="owner.3d.update",
            resource_type="3d_service_policy",
            resource_id="default",
            details={"fields": sorted(updates)},
        )
    )
    await session.commit()
    result = await _snapshot(session)
    await session.commit()
    return result


@router.post("/circuit/reset")
async def reset_owner_three_d_circuit(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    for provider in ("hunyuan3d", "triposr"):
        await reset_provider_circuit(
            session,
            actor_id=actor.id,
            organization_id=actor.organization_id,
            provider=provider,
        )
    await session.commit()
    result = await _snapshot(session)
    await session.commit()
    return result


@router.post("/cleanup")
async def run_owner_three_d_cleanup(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await cleanup_expired_three_d_data(session, ThreeDObjectStore())
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="owner.3d.cleanup",
            resource_type="3d_service_policy",
            resource_id="default",
            details=result,
        )
    )
    await session.commit()
    snapshot = await _snapshot(session)
    await session.commit()
    return {**snapshot, "cleanup_result": result}


@router.get("/metrics")
async def owner_three_d_metrics(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> Response:
    del actor
    text = await prometheus_snapshot(session)
    return Response(content=text, media_type="text/plain; version=0.0.4; charset=utf-8")
