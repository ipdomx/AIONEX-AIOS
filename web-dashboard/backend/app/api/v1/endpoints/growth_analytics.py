"""Authenticated GS-05 analytics and learning ledger endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_analytics_learning as analytics

router = APIRouter()


class ObservationCreate(BaseModel):
    subject_type: str = Field(min_length=1, max_length=48)
    subject_id: str = Field(min_length=1, max_length=160)
    provider: str | None = Field(default=None, max_length=40)
    source: str = Field(default="simulation", max_length=32)
    period_start: datetime
    period_end: datetime
    currency: str = Field(default="USD", min_length=3, max_length=3)
    impressions: int = Field(default=0, ge=0)
    reach: int = Field(default=0, ge=0)
    engagements: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    conversions: int = Field(default=0, ge=0)
    spend_minor: int = Field(default=0, ge=0)
    revenue_minor: int = Field(default=0, ge=0)
    followers_delta: int = 0
    extra_metrics: dict = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list, max_length=200)
    context: dict = Field(default_factory=dict)


def _http_error(exc: analytics.GrowthAnalyticsError) -> HTTPException:
    detail = str(exc)
    if detail == "observation-not-found":
        return HTTPException(status_code=404, detail=detail)
    if detail.startswith("access-denied:"):
        return HTTPException(status_code=403, detail=detail)
    if detail == "learning-recommendation-missing":
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.get("/observations")
async def list_observations(
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return {
            "items": await analytics.list_observations(session, actor, limit),
            "live_provider_call": False,
            "auto_optimization_allowed": False,
            "auto_replay_allowed": False,
        }
    except analytics.GrowthAnalyticsError as exc:
        raise _http_error(exc) from exc


@router.post("/observations", status_code=201)
async def record_observation(
    request: ObservationCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await analytics.record_observation(session, actor, request.model_dump())
        await session.commit()
        return analytics.public_observation(row)
    except analytics.GrowthAnalyticsError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/observations/{observation_id}/analyze", status_code=201)
async def analyze_observation(
    observation_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        learning, recommendation = await analytics.analyze_observation(
            session, actor, observation_id
        )
        await session.commit()
        return {
            "learning": analytics.public_learning(learning),
            "recommendation": analytics.public_recommendation(recommendation),
            "auto_optimization_allowed": False,
            "auto_replay_allowed": False,
        }
    except analytics.GrowthAnalyticsError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.get("/recommendations")
async def list_recommendations(
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return {
            "items": await analytics.list_recommendations(session, actor, limit),
            "auto_optimization_allowed": False,
            "auto_replay_allowed": False,
        }
    except analytics.GrowthAnalyticsError as exc:
        raise _http_error(exc) from exc


@router.get("/patterns")
async def list_patterns(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return {
            "items": await analytics.pattern_summary(session, actor),
            "failure_reason_taxonomy": analytics.FAILURE_REASON_TAXONOMY,
            "auto_optimization_allowed": False,
            "auto_replay_allowed": False,
        }
    except analytics.GrowthAnalyticsError as exc:
        raise _http_error(exc) from exc
