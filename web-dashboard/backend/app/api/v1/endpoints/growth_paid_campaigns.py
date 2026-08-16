from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import (
    GrowthPaidCampaign,
    GrowthPaidDecision,
    GrowthPaidLiveExecution,
)
from app.services import growth_paid_campaigns as paid

router = APIRouter()


class CampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    objective: Literal["sales", "leads", "traffic", "awareness"]
    social_account_id: str = Field(min_length=1, max_length=36)
    brief_id: str | None = None
    total_budget_minor: int = Field(gt=0)
    daily_budget_cap_minor: int = Field(gt=0)
    stop_loss_policy: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class AdSetRequest(BaseModel):
    name: str
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


class CampaignPreparationRequest(BaseModel):
    campaign_name: str = Field(min_length=1, max_length=240)
    objective: Literal["sales", "leads", "traffic", "awareness"]
    social_account_id: str = Field(min_length=1, max_length=36)
    total_budget_minor: int = Field(gt=0)
    daily_budget_cap_minor: int = Field(gt=0)
    max_cpa_minor: int | None = Field(default=None, gt=0)
    min_roas: float | None = Field(default=None, gt=0)
    target_countries: list[str] = Field(min_length=1, max_length=25)
    placements: list[str] = Field(default_factory=lambda: ["feed"])
    bid_strategy: str = Field(default="lowest_cost", min_length=1, max_length=48)
    ad_set_name: str | None = Field(default=None, max_length=240)
    creative_name: str | None = Field(default=None, max_length=240)
    creative_format: str = Field(default="image", min_length=1, max_length=40)
    headline: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=4000)
    destination_url: str | None = Field(default=None, max_length=2048)
    utm: dict = Field(default_factory=dict)
    ad_name: str | None = Field(default=None, max_length=240)
    days: int = Field(default=3, ge=1, le=30)


def _delivery_stage(
    campaign: GrowthPaidCampaign,
    execution: GrowthPaidLiveExecution | None = None,
) -> str:
    if execution is not None and execution.manual_review_required:
        return "manual_review"
    if execution is not None:
        if execution.status == "paused_ready":
            return "paused_on_meta"
        if execution.status in {"prepared", "authorized", "executing"}:
            return "provider_preparation"
    if dict(campaign.campaign_metadata or {}).get("live_execution_plan"):
        return "live_plan_ready"
    if campaign.approval_status == "approved":
        return "owner_approved"
    if campaign.approval_status in {"pending_owner", "awaiting_owner_approval"}:
        return "awaiting_owner"
    return "aios_analysis"


def _user_campaign_payload(
    campaign: GrowthPaidCampaign,
    execution: GrowthPaidLiveExecution | None = None,
) -> dict:
    payload = paid.public_campaign(campaign)
    payload.update(
        {
            "delivery_stage": _delivery_stage(campaign, execution),
            "live_plan_prepared": bool(
                dict(campaign.campaign_metadata or {}).get("live_execution_plan")
            ),
            "provider_prepared": bool(
                execution is not None and execution.status == "paused_ready"
            ),
            "manual_review_required": bool(
                execution is not None and execution.manual_review_required
            ),
            "spend_executed": bool(execution is not None and execution.spend_executed),
            "automatic_execution_allowed": False,
        }
    )
    return payload


def _status(exc: Exception) -> int:
    text = str(exc)
    if text.startswith("access-denied:") or text.startswith("campaigns-unavailable:"):
        return 403
    if text.endswith("not-found"):
        return 404
    return 400


@router.post("/prepare-and-simulate", status_code=201)
async def prepare_and_simulate_campaign(
    request: CampaignPreparationRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        binding = await paid.resolve_linked_ad_account(
            session, actor, request.social_account_id
        )
        payload = request.model_dump(exclude={"social_account_id"})
        payload.update(
            {
                "linked_ad_account_id": binding["id"],
                "provider": binding["provider"],
                "currency": binding["currency"],
            }
        )
        result = await paid.prepare_and_simulate_campaign(session, actor, payload)
        await session.commit()
        campaign = result["campaign"]
        decision = result["decision"]
        simulation = result["simulation"]
        return {
            "campaign": _user_campaign_payload(campaign),
            "ad_set_id": result["ad_set"].id,
            "creative_id": result["creative"].id,
            "ad_id": result["ad"].id,
            "simulation_id": simulation.id,
            "decision": decision.action,
            "reason_codes": decision.reason_codes,
            "metrics": decision.metrics,
            "budget_assessment": decision.metrics.get("budget_assessment", {}),
            "owner_approval_required": True,
            "aios_advice_only": True,
            "automatic_execution_allowed": False,
            "real_spend_allowed": False,
            "live_provider_call": False,
            "live_campaign_mutation": False,
        }
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc


@router.get("/readiness")
async def paid_campaign_readiness(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await paid.campaign_readiness(session, actor)


@router.get("")
async def list_campaigns(
    actor: UserRecord = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    readiness = await paid.campaign_readiness(session, actor)
    if not readiness["campaigns_visible"]:
        detail = f"campaigns-unavailable:{readiness['reason']}"
        raise HTTPException(status_code=403, detail=detail)
    rows = (
        await session.scalars(
            select(GrowthPaidCampaign)
            .where(GrowthPaidCampaign.organization_id == actor.organization_id)
            .order_by(GrowthPaidCampaign.created_at.desc())
        )
    ).all()
    execution_rows = (
        await session.scalars(
            select(GrowthPaidLiveExecution)
            .where(GrowthPaidLiveExecution.organization_id == actor.organization_id)
            .order_by(GrowthPaidLiveExecution.created_at.desc())
        )
    ).all()
    latest_execution: dict[str, GrowthPaidLiveExecution] = {}
    for execution in execution_rows:
        latest_execution.setdefault(execution.campaign_id, execution)
    return {
        "items": [
            _user_campaign_payload(row, latest_execution.get(row.id)) for row in rows
        ]
    }


@router.post("", status_code=201)
async def create_campaign(
    request: CampaignRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        binding = await paid.resolve_linked_ad_account(
            session, actor, request.social_account_id
        )
        payload = request.model_dump(exclude={"social_account_id"})
        metadata = dict(payload.get("metadata") or {})
        metadata.update(
            {
                "linked_ad_account_id": binding["id"],
                "linked_ad_account_provider": binding["provider"],
                "linked_ad_account_currency": binding["currency"],
            }
        )
        payload["metadata"] = metadata
        payload["currency"] = binding["currency"]
        row = await paid.create_campaign(session, actor, payload)
        await session.commit()
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc
    return _user_campaign_payload(row)


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
