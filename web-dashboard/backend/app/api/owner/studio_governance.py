"""Phase 36M Owner Studio governance API."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.services import studio_governance

router = APIRouter(prefix="/owner/studio-governance", tags=["Owner Studio Governance"])


class StudioCapabilityPolicyUpdate(BaseModel):
    enabled: bool = True
    eligible_plans: list[
        Literal["free", "starter", "professional", "enterprise"]
    ] = Field(min_length=1, max_length=4)
    daily_job_limit: int = Field(ge=1, le=10_000)
    max_concurrent_jobs: int = Field(ge=1, le=100)
    max_attempts: int = Field(ge=1, le=5)
    max_cost_usd: float = Field(default=0.0, ge=0, le=1_000)
    provider_mode: Literal["provider_neutral"] = "provider_neutral"
    moderation_mode: Literal["standard", "strict"] = "standard"


@router.get("")
async def studio_governance_snapshot(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    return {
        "provider_activation": "disabled-in-36m1",
        "capabilities": await studio_governance.owner_catalog(session),
    }


@router.patch("/{capability_id}")
async def update_studio_capability_policy(
    capability_id: str,
    data: StudioCapabilityPolicyUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await studio_governance.update_policy(
            session,
            actor=actor,
            capability_id=capability_id,
            enabled=data.enabled,
            payload=data.model_dump(exclude={"enabled"}),
        )
        await session.commit()
        return result
    except studio_governance.StudioGovernanceError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
