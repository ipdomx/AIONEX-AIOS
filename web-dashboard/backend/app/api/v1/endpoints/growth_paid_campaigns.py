from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import GrowthPaidCampaign, GrowthPaidDecision
from app.services import growth_paid_campaigns as paid

router = APIRouter()


class CampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=80)
    brief_id: str | None = None
    currency: str = "USD"
    total_budget_minor: int = Field(gt=0)
    daily_budget_cap_minor: int = Field(gt=0)
    stop_loss_policy: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class AdSetRequest(BaseModel):
    name: str
    provider: str
    audience: dict = Field(default_factory=dict)
    placements: list[str] = Field(default_factory=list)
    bid_strategy: str = "lowest_cost"
    daily_budget_cap_minor: int = Field(gt=0)


class CreativeRequest(BaseModel):
    name: str
    format: str = "image"
    headline: str = ""
    body: str = ""
    media_refs: list[str] = Field(default_factory=list)
    destination_url: str | None = None
    utm: dict = Field(default_factory=dict)
    approved: bool = False


class AdRequest(BaseModel):
    name: str
    ad_set_id: str
    creative_id: str


class ExperimentRequest(BaseModel):
    name: str
    hypothesis: str
    variant_ad_ids: list[str]
    primary_metric: str = "conversion_rate"


def _status(exc: Exception) -> int:
    text = str(exc)
    if text.startswith("access-denied:"):
        return 403
    if text.endswith("not-found"):
        return 404
    return 400


@router.get("")
async def list_campaigns(
    actor: UserRecord = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    try:
        await paid._require(session, actor)
    except paid.GrowthPaidCampaignError as exc:
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    rows = (
        await session.scalars(
            select(GrowthPaidCampaign)
            .where(GrowthPaidCampaign.organization_id == actor.organization_id)
            .order_by(GrowthPaidCampaign.created_at.desc())
        )
    ).all()
    return {"items": [paid.public_campaign(r) for r in rows]}


@router.post("", status_code=201)
async def create_campaign(
    request: CampaignRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await paid.create_campaign(session, actor, request.model_dump())
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return paid.public_campaign(row)


@router.post("/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await paid.approve_campaign(session, actor, campaign_id)
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return paid.public_campaign(row)


@router.post("/{campaign_id}/ad-sets", status_code=201)
async def add_ad_set(
    campaign_id: str,
    request: AdSetRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await paid.add_ad_set(session, actor, campaign_id, request.model_dump())
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return {
        "id": row.id,
        "provider": row.provider,
        "daily_budget_cap_minor": row.daily_budget_cap_minor,
    }


@router.post("/{campaign_id}/creatives", status_code=201)
async def add_creative(
    campaign_id: str,
    request: CreativeRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await paid.add_creative(session, actor, campaign_id, request.model_dump())
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return {"id": row.id, "approval_status": row.approval_status, "status": row.status}


@router.post("/{campaign_id}/ads", status_code=201)
async def add_ad(
    campaign_id: str,
    request: AdRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await paid.add_ad(session, actor, campaign_id, request.model_dump())
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return {"id": row.id, "status": row.status}


@router.post("/{campaign_id}/experiments", status_code=201)
async def create_experiment(
    campaign_id: str,
    request: ExperimentRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await paid.create_experiment(
            session, actor, campaign_id, request.model_dump()
        )
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return {"id": row.id, "allocation": row.allocation, "status": row.status}


@router.post("/{campaign_id}/simulate")
async def simulate_campaign(
    campaign_id: str,
    days: int = Query(default=3, ge=1, le=30),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        sim, decision = await paid.simulate_launch(
            session, actor, campaign_id, days=days
        )
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return {
        "simulation_id": sim.id,
        "decision": decision.action,
        "reason_codes": decision.reason_codes,
        "metrics": decision.metrics,
        "approval_required": True,
        "owner_approval_required": True,
        "aios_advice_only": True,
        "budget_assessment": decision.metrics.get("budget_assessment", {}),
        "automatic_execution_allowed": False,
        "real_spend_allowed": False,
        "live_provider_call": False,
        "live_campaign_mutation": False,
    }


@router.get("/{campaign_id}/decisions")
async def decisions(
    campaign_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        await paid._campaign(session, actor, campaign_id)
    except paid.GrowthPaidCampaignError as exc:
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    rows = (
        await session.scalars(
            select(GrowthPaidDecision)
            .where(GrowthPaidDecision.campaign_id == campaign_id)
            .order_by(GrowthPaidDecision.created_at.desc())
        )
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "reason_codes": r.reason_codes,
                "metrics": r.metrics,
                "approval_required": True,
                "automatic_execution_allowed": False,
                "real_spend_allowed": False,
            }
            for r in rows
        ]
    }
