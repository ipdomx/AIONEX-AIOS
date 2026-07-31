"""Super Owner controls for free-user quotas and registration telemetry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services.free_tier import (
    get_free_tier_policy,
    list_free_accounts,
    update_free_tier_policy,
)

router = APIRouter(prefix="/owner/free-tier", tags=["owner-free-tier"])


class FreeTierPolicyUpdate(BaseModel):
    enabled: bool | None = None
    project_limit: int | None = Field(default=None, ge=1, le=100)
    monthly_user_message_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    monthly_assistant_response_limit: int | None = Field(
        default=None,
        ge=1,
        le=1_000_000,
    )
    storage_limit_bytes: int | None = Field(
        default=None,
        ge=1024 * 1024,
        le=10 * 1024 * 1024 * 1024,
    )
    max_message_characters: int | None = Field(default=None, ge=128, le=200_000)
    registrations_per_ip_per_day: int | None = Field(default=None, ge=1, le=1000)
    minimum_age: int | None = Field(default=None, ge=13, le=100)
    require_phone_verification: bool | None = None
    require_device_signals: bool | None = None
    one_account_per_network: bool | None = None
    one_account_per_device: bool | None = None
    telemetry_retention_days: int | None = Field(default=None, ge=1, le=3650)
    consent_version: str | None = Field(default=None, min_length=4, max_length=80)
    require_country: bool | None = None
    require_cookie_consent: bool | None = None


@router.get("")
async def get_owner_free_tier(
    limit: int = Query(100, ge=1, le=500),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del actor
    policy = await get_free_tier_policy(session)
    accounts = await list_free_accounts(session, limit=limit)
    await session.commit()
    return {
        "policy": policy,
        "accounts": accounts,
        "account_count": len(accounts),
    }


@router.patch("")
async def patch_owner_free_tier(
    data: FreeTierPolicyUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)
    policy = await update_free_tier_policy(session, updates)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="owner.free_tier.update",
            resource_type="free_tier_policy",
            resource_id="default",
            details={"fields": sorted(updates)},
        )
    )
    await session.commit()
    return {
        "policy": policy,
        "accounts": await list_free_accounts(session, limit=100),
    }
