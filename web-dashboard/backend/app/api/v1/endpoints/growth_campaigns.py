"""Authenticated GS-02 campaign intelligence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_campaign_intelligence as intelligence

router = APIRouter()


class CampaignBriefCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=80)
    product_summary: str = Field(min_length=1, max_length=8000)
    project_id: str | None = None
    target_markets: list[str] = Field(default_factory=list, max_length=50)
    audience_hypotheses: list[dict] = Field(default_factory=list, max_length=100)
    competitor_hypotheses: list[dict] = Field(default_factory=list, max_length=100)
    offer_hypotheses: list[dict] = Field(default_factory=list, max_length=100)
    channel_hypotheses: list[dict] = Field(default_factory=list, max_length=50)
    budget_minor: int = Field(default=0, ge=0, le=10_000_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    evidence: list[dict] = Field(default_factory=list, max_length=200)


class SimulationRequest(BaseModel):
    scenario: str = Field(
        default="expected", pattern="^(conservative|expected|upside)$"
    )


def _brief(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "objective": row.objective,
        "product_summary": row.product_summary,
        "project_id": row.project_id,
        "target_markets": row.target_markets,
        "audience_hypotheses": row.audience_hypotheses,
        "competitor_hypotheses": row.competitor_hypotheses,
        "offer_hypotheses": row.offer_hypotheses,
        "channel_hypotheses": row.channel_hypotheses,
        "budget_minor": row.budget_minor,
        "currency": row.currency,
        "evidence": row.evidence,
        "status": row.status,
        "version": row.version,
        "real_spend_allowed": False,
    }


def _simulation(row) -> dict:
    return {
        "id": row.id,
        "brief_id": row.brief_id,
        "scenario": row.scenario,
        "confidence": row.confidence,
        "estimated_reach_min": row.estimated_reach_min,
        "estimated_reach_max": row.estimated_reach_max,
        "estimated_clicks_min": row.estimated_clicks_min,
        "estimated_clicks_max": row.estimated_clicks_max,
        "estimated_conversions_min": row.estimated_conversions_min,
        "estimated_conversions_max": row.estimated_conversions_max,
        "estimated_cpa_minor": row.estimated_cpa_minor,
        "reason_codes": row.reason_codes,
        "assumptions": row.assumptions,
        "result": row.result,
        "real_spend_allowed": False,
    }


@router.get("/briefs")
async def list_campaign_briefs(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        rows = await intelligence.list_briefs(session, actor)
    except intelligence.GrowthCampaignError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"items": [_brief(row) for row in rows], "real_spend_allowed": False}


@router.post("/briefs", status_code=201)
async def create_campaign_brief(
    request: CampaignBriefCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await intelligence.create_brief(session, actor, request.model_dump())
        await session.commit()
    except intelligence.GrowthCampaignError as exc:
        await session.rollback()
        code = 403 if str(exc).startswith("access-denied:") else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return _brief(row)


@router.post("/briefs/{brief_id}/simulate", status_code=201)
async def simulate_campaign_brief(
    brief_id: str,
    request: SimulationRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await intelligence.simulate_brief(
            session, actor, brief_id, request.scenario
        )
        await session.commit()
    except intelligence.GrowthCampaignError as exc:
        await session.rollback()
        detail = str(exc)
        code = (
            404
            if detail == "brief-not-found"
            else 403 if detail.startswith("access-denied:") else 400
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    return _simulation(row)
