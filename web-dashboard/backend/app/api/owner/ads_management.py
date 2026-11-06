"""Super Owner policy for P4 Meta Ads: entitlement, activation and spend caps."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services import ads_entitlement as entitlement

router = APIRouter(prefix="/owner/ads", tags=["Owner Meta Ads"])


class UserCap(BaseModel):
    daily_cap_minor: int = Field(ge=0, le=entitlement.MAX_MONEY_MINOR)
    lifetime_cap_minor: int = Field(ge=0, le=entitlement.MAX_MONEY_MINOR)


class AdsPolicyUpdate(BaseModel):
    enabled: bool | None = None
    entitlement: str | None = Field(default=None, min_length=1, max_length=120)
    plan_codes: list[str] | None = Field(default=None, max_length=20)
    activation_enabled: bool | None = None
    daily_cap_minor: int | None = Field(default=None, ge=0, le=entitlement.MAX_MONEY_MINOR)
    lifetime_cap_minor: int | None = Field(default=None, ge=0, le=entitlement.MAX_MONEY_MINOR)
    user_caps: dict[str, UserCap] | None = None
    max_ad_accounts_per_user: int | None = Field(default=None, ge=1, le=50)
    max_active_campaigns_per_user: int | None = Field(default=None, ge=0, le=100)
    max_recommendation_runs_per_day: int | None = Field(default=None, ge=0, le=500)


@router.get("/policy")
async def get_policy(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"policy": await entitlement.get_policy(session), "live_verified": False}


@router.patch("/policy")
async def patch_policy(
    data: AdsPolicyUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)
    try:
        policy = await entitlement.update_policy(session, updates)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="owner.ads.policy_updated",
            resource_type="owner_control_record",
            resource_id=entitlement.POLICY_DOMAIN,
            details={"ads_management": "p4", "fields": sorted(updates)},
        )
    )
    await session.commit()
    return {"policy": policy, "live_verified": False}
