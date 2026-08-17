"""Super Owner controls for Project AI free/paid/user provider consumption."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services.provider_credit_alerts import (
    ProviderCreditPolicyError,
    configure_provider_credit,
    provider_credit_snapshot,
)
from app.services.project_ai_access_policy import (
    ProjectAIAccessPolicyError,
    disable_user_policy,
    project_ai_access_owner_snapshot,
    set_plan_policy,
    set_user_policy,
)

router = APIRouter(prefix="/owner/project-ai", tags=["owner-project-ai"])


class ProjectAIAccessPolicyUpdate(BaseModel):
    access_class: Literal["free", "paid"] | None = None
    enabled: bool | None = None
    allowed_provider_models: list[str] | None = Field(default=None, max_length=64)
    max_project_cost_usd: float | None = Field(default=None, ge=0, le=1000)
    offline_only: bool | None = None
    privacy_mode: bool | None = None
    max_fallbacks: int | None = Field(default=None, ge=0, le=4)


def _error(exc: ProjectAIAccessPolicyError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/access")
async def owner_project_ai_access(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del actor
    return await project_ai_access_owner_snapshot(session)


@router.put("/access/plans/{access_class}")
async def owner_set_project_ai_plan_policy(
    access_class: Literal["free", "paid"],
    data: ProjectAIAccessPolicyUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)
    updates["access_class"] = access_class
    try:
        policy = await set_plan_policy(session, access_class=access_class, payload=updates)
    except ProjectAIAccessPolicyError as exc:
        raise _error(exc) from exc
    session.add(AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="owner.project_ai.plan_policy.updated",
        resource_type="project_ai_plan_policy",
        resource_id=access_class,
        details={"fields": sorted(updates)},
    ))
    await session.commit()
    return {"policy": policy}


@router.put("/access/users/{user_id}")
async def owner_set_project_ai_user_policy(
    user_id: str,
    data: ProjectAIAccessPolicyUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)
    if "access_class" not in updates:
        raise HTTPException(status_code=422, detail="access_class is required for a user override")
    try:
        policy = await set_user_policy(session, user_id=user_id, payload=updates)
    except ProjectAIAccessPolicyError as exc:
        raise _error(exc) from exc
    session.add(AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="owner.project_ai.user_policy.updated",
        resource_type="project_ai_user_policy",
        resource_id=user_id,
        details={"fields": sorted(updates)},
    ))
    await session.commit()
    return {"user_id": user_id, "policy": policy}


@router.delete("/access/users/{user_id}")
async def owner_clear_project_ai_user_policy(
    user_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    changed = await disable_user_policy(session, user_id=user_id)
    session.add(AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="owner.project_ai.user_policy.cleared",
        resource_type="project_ai_user_policy",
        resource_id=user_id,
        details={"changed": changed},
    ))
    await session.commit()
    return {"user_id": user_id, "changed": changed}


class ProjectAIProviderFinanceUpdate(BaseModel):
    funded_credit_usd: float = Field(ge=0, le=1_000_000)
    low_balance_threshold_usd: float = Field(ge=0, le=1_000_000)
    critical_balance_threshold_usd: float = Field(ge=0, le=1_000_000)
    enabled: bool = True


@router.get("/providers/{provider_id}/finance")
async def owner_project_ai_provider_finance(
    provider_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del actor
    try:
        snapshot = await provider_credit_snapshot(session, provider_id=provider_id)
    except ProviderCreditPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return snapshot.public()


@router.put("/providers/{provider_id}/finance")
async def owner_set_project_ai_provider_finance(
    provider_id: str,
    data: ProjectAIProviderFinanceUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        snapshot = await configure_provider_credit(
            session,
            provider_id=provider_id,
            funded_credit_usd=data.funded_credit_usd,
            low_balance_threshold_usd=data.low_balance_threshold_usd,
            critical_balance_threshold_usd=data.critical_balance_threshold_usd,
            enabled=data.enabled,
        )
    except ProviderCreditPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.add(AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="owner.project_ai.provider_finance.updated",
        resource_type="ai_provider",
        resource_id=provider_id,
        details={
            "funded_credit_usd": data.funded_credit_usd,
            "low_balance_threshold_usd": data.low_balance_threshold_usd,
            "critical_balance_threshold_usd": data.critical_balance_threshold_usd,
            "enabled": data.enabled,
        },
    ))
    await session.commit()
    return snapshot.public()
