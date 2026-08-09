"""Super Owner control surface for 3D access, cost and recovery policy."""
from __future__ import annotations
from typing import Any, Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services.three_d_policy import get_three_d_policy, update_three_d_policy
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

@router.get("")
async def owner_three_d_policy(actor: UserRecord = Depends(require_super_owner), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    del actor
    policy = await get_three_d_policy(session); await session.commit()
    return {"policy": policy}

@router.patch("")
async def patch_owner_three_d_policy(data: ThreeDPolicyUpdate, actor: UserRecord = Depends(require_super_owner), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)
    policy = await update_three_d_policy(session, updates)
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id, action="owner.3d.update", resource_type="3d_service_policy", resource_id="default", details={"fields": sorted(updates)}))
    await session.commit()
    return {"policy": policy}
