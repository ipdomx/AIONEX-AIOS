"""Super Owner approval API for paid Growth/Social campaigns."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import (
    GrowthPaidAd,
    GrowthPaidAdSet,
    GrowthPaidCampaign,
    GrowthPaidCreative,
    Organization,
    User,
)
from app.services import growth_paid_campaigns as paid
from app.services import growth_paid_live_plan as live_plan
from app.services import growth_paid_live_execution as live_execution

router = APIRouter(
    prefix="/owner/growth-social/paid-campaigns",
    tags=["Owner Growth Paid Campaigns"],
)


class LivePlanInput(BaseModel):
    pilot_id: str = Field(min_length=1, max_length=36)
    creative_identity_ref: str | None = Field(default=None, max_length=96)


class LivePlanPrepareInput(BaseModel):
    pilot_id: str = Field(min_length=1, max_length=36)
    creative_identity_ref: str = Field(min_length=1, max_length=96)


class LiveExecutionRunInput(BaseModel):
    plan_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    confirmation: str = Field(min_length=1, max_length=80)


def _plan_error(exc: live_plan.GrowthPaidLivePlanError) -> HTTPException:
    message = str(exc)
    if message in {"campaign-not-found", "pilot-not-found"}:
        return HTTPException(status_code=404, detail=message)
    if message.startswith("live-plan-not-compilable:"):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


def _execution_error(exc: live_execution.GrowthPaidLiveExecutionError) -> HTTPException:
    message = str(exc)
    if message in {"campaign-not-found", "pilot-not-found", "live-execution-not-found"}:
        return HTTPException(status_code=404, detail=message)
    if (
        "manual-review" in message
        or "runtime-authorization-denied" in message
        or "prepared-live-plan" in message
        or "binding" in message
    ):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


def _error(exc: paid.GrowthPaidCampaignError) -> HTTPException:
    message = str(exc)
    if message == "campaign-not-found":
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.get("")
async def list_paid_campaigns_for_owner(
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(GrowthPaidCampaign)
    if status:
        stmt = stmt.where(GrowthPaidCampaign.approval_status == status)
    rows = list(
        await session.scalars(
            stmt.order_by(GrowthPaidCampaign.created_at.desc()).limit(limit)
        )
    )
    organization_ids = {row.organization_id for row in rows}
    user_ids = {row.created_by_id for row in rows}
    organizations = (
        {
            row.id: row.name
            for row in (
                await session.scalars(
                    select(Organization).where(Organization.id.in_(organization_ids))
                )
            ).all()
        }
        if organization_ids
        else {}
    )
    users = (
        {
            row.id: row.name
            for row in (
                await session.scalars(select(User).where(User.id.in_(user_ids)))
            ).all()
        }
        if user_ids
        else {}
    )
    campaign_ids = {row.id for row in rows}
    ad_sets = (
        list(
            await session.scalars(
                select(GrowthPaidAdSet).where(
                    GrowthPaidAdSet.campaign_id.in_(campaign_ids)
                )
            )
        )
        if campaign_ids
        else []
    )
    creatives = (
        list(
            await session.scalars(
                select(GrowthPaidCreative).where(
                    GrowthPaidCreative.campaign_id.in_(campaign_ids)
                )
            )
        )
        if campaign_ids
        else []
    )
    ads = (
        list(
            await session.scalars(
                select(GrowthPaidAd).where(GrowthPaidAd.campaign_id.in_(campaign_ids))
            )
        )
        if campaign_ids
        else []
    )
    ad_sets_by_campaign: dict[str, list[GrowthPaidAdSet]] = {}
    creatives_by_campaign: dict[str, list[GrowthPaidCreative]] = {}
    ads_by_campaign: dict[str, list[GrowthPaidAd]] = {}
    for ad_set_row in ad_sets:
        ad_sets_by_campaign.setdefault(ad_set_row.campaign_id, []).append(ad_set_row)
    for creative_row in creatives:
        creatives_by_campaign.setdefault(creative_row.campaign_id, []).append(
            creative_row
        )
    for ad_row in ads:
        ads_by_campaign.setdefault(ad_row.campaign_id, []).append(ad_row)

    def configuration_summary(campaign_id: str) -> dict[str, object]:
        campaign_ad_sets = ad_sets_by_campaign.get(campaign_id, [])
        campaign_creatives = creatives_by_campaign.get(campaign_id, [])
        campaign_ads = ads_by_campaign.get(campaign_id, [])
        countries: set[str] = set()
        placements: set[str] = set()
        providers: set[str] = set()
        for ad_set in campaign_ad_sets:
            providers.add(ad_set.provider)
            placements.update(str(item) for item in (ad_set.placements or []))
            audience = dict(ad_set.audience or {})
            values = audience.get("countries")
            if isinstance(values, list):
                countries.update(str(item) for item in values)
        return {
            "providers": sorted(providers),
            "target_countries": sorted(countries),
            "placements": sorted(placements),
            "ad_set_count": len(campaign_ad_sets),
            "creative_count": len(campaign_creatives),
            "ad_count": len(campaign_ads),
            "creatives": [
                {
                    "format": row.format,
                    "headline": row.headline,
                    "body": row.body,
                    "destination_url": row.destination_url,
                }
                for row in campaign_creatives[:5]
            ],
            "truncated": len(campaign_creatives) > 5,
            "raw_provider_ids_returned": False,
            "raw_credentials_returned": False,
        }

    return {
        "items": [
            {
                **paid.public_campaign(row),
                "organization_id": row.organization_id,
                "organization_name": organizations.get(row.organization_id, ""),
                "created_by_name": users.get(row.created_by_id, ""),
                "latest_budget_assessment": (
                    dict(row.campaign_metadata or {}).get("latest_budget_assessment")
                    or {}
                ),
                "configuration_summary": configuration_summary(row.id),
                "created_at": row.created_at,
                "approved_at": row.approved_at,
            }
            for row in rows
        ],
        "owner_approval_required": True,
        "automatic_execution_allowed": False,
        "real_spend_allowed": False,
    }


@router.post("/{campaign_id}/approve")
async def owner_approve_paid_campaign(
    campaign_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await paid.approve_campaign(session, actor, campaign_id)
        await session.commit()
        await session.refresh(row)
        return paid.public_campaign(row)
    except paid.GrowthPaidCampaignError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/{campaign_id}/live-plan/evaluate")
async def evaluate_paid_campaign_live_plan(
    campaign_id: str,
    data: LivePlanInput,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await live_plan.evaluate_live_plan(
            session,
            actor,
            campaign_id,
            data.pilot_id,
            creative_identity_ref=data.creative_identity_ref,
        )
    except live_plan.GrowthPaidLivePlanError as exc:
        raise _plan_error(exc) from exc


@router.post("/{campaign_id}/live-plan/prepare")
async def prepare_paid_campaign_live_plan(
    campaign_id: str,
    data: LivePlanPrepareInput,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await live_plan.prepare_live_plan(
            session,
            actor,
            campaign_id,
            data.pilot_id,
            creative_identity_ref=data.creative_identity_ref,
        )
        await session.commit()
        return result
    except live_plan.GrowthPaidLivePlanError as exc:
        await session.rollback()
        raise _plan_error(exc) from exc


@router.get("/{campaign_id}/live-plan/validate")
async def validate_paid_campaign_live_plan(
    campaign_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await live_plan.validate_prepared_plan(session, actor, campaign_id)
    except live_plan.GrowthPaidLivePlanError as exc:
        raise _plan_error(exc) from exc


@router.get("/{campaign_id}/live-execution")
async def get_paid_campaign_live_execution(
    campaign_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await live_execution.get_execution(session, actor, campaign_id)
    except live_execution.GrowthPaidLiveExecutionError as exc:
        raise _execution_error(exc) from exc


@router.post("/{campaign_id}/live-execution/prepare")
async def prepare_paid_campaign_live_execution(
    campaign_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await live_execution.prepare_execution(session, actor, campaign_id)
        await session.commit()
        return result
    except live_execution.GrowthPaidLiveExecutionError as exc:
        await session.rollback()
        raise _execution_error(exc) from exc


@router.post("/{campaign_id}/live-execution/{execution_id}/execute-paused")
async def execute_paid_campaign_paused_graph(
    campaign_id: str,
    execution_id: str,
    data: LiveExecutionRunInput,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await live_execution.execute_paused_plan(
            session,
            actor,
            campaign_id,
            execution_id,
            plan_digest=data.plan_digest,
            confirmation=data.confirmation,
        )
    except live_execution.GrowthPaidLiveExecutionError as exc:
        await session.rollback()
        raise _execution_error(exc) from exc
