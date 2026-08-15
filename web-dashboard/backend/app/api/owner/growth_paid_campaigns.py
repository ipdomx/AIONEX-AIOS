"""Super Owner approval API for paid Growth/Social campaigns."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import GrowthPaidCampaign, Organization, User
from app.services import growth_paid_campaigns as paid

router = APIRouter(
    prefix="/owner/growth-social/paid-campaigns",
    tags=["Owner Growth Paid Campaigns"],
)


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
    return {
        "items": [
            {
                **paid.public_campaign(row),
                "organization_name": organizations.get(row.organization_id, ""),
                "created_by_name": users.get(row.created_by_id, ""),
                "latest_budget_assessment": (
                    dict(row.campaign_metadata or {}).get("latest_budget_assessment")
                    or {}
                ),
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
