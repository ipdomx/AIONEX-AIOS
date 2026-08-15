"""Super Owner GS-12 controlled live-pilot API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.services import growth_controlled_pilots as pilots

router = APIRouter(
    prefix="/owner/growth-social/pilots", tags=["Owner Growth Live Pilots"]
)


class PilotCreateInput(BaseModel):
    organization_id: str | None = Field(default=None, max_length=36)
    provider: Literal["meta", "telegram"]
    provider_scope: str = Field(min_length=1, max_length=80)
    scope_ref: str | None = Field(default=None, max_length=255)
    mode: Literal["read_only", "live_spend"]
    owner_approval_reference: str = Field(min_length=1, max_length=240)
    expires_at: datetime | None = None


class PilotControlsInput(BaseModel):
    legal_policy_acknowledged: bool | None = None
    legal_policy_reference: str | None = Field(default=None, max_length=500)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    max_total_budget_minor: int | None = None
    max_daily_budget_minor: int | None = None
    max_cpa_minor: int | None = None
    min_roas: float | None = None
    expires_at: datetime | None = None


class PilotDisarmInput(BaseModel):
    reason: str = Field(default="owner-disarm", min_length=1, max_length=240)


def _error(exc: pilots.GrowthControlledPilotError) -> HTTPException:
    message = str(exc)
    if message == "pilot-not-found":
        return HTTPException(status_code=404, detail=message)
    if message.startswith("pilot-not-ready:"):
        return HTTPException(status_code=409, detail=message)
    if message in {"pilot-is-terminal", "launch-authorization-only-for-live-spend"}:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.get("")
async def list_pilots(
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    rows = await pilots.list_pilots(session, actor, limit=limit)
    return {
        "items": [pilots.public_pilot(row) for row in rows],
        "provider_write_executed": False,
        "provider_spend_executed": False,
    }


@router.post("", status_code=201)
async def create_pilot(
    data: PilotCreateInput,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await pilots.create_pilot(session, actor, data.model_dump())
        await session.commit()
        await session.refresh(row)
        return pilots.public_pilot(row)
    except pilots.GrowthControlledPilotError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/{pilot_id}/readiness")
async def pilot_readiness(
    pilot_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await pilots.readiness(session, actor, pilot_id)
    except pilots.GrowthControlledPilotError as exc:
        raise _error(exc) from exc


@router.patch("/{pilot_id}/controls")
async def configure_pilot_controls(
    pilot_id: str,
    data: PilotControlsInput,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await pilots.configure_controls(
            session,
            actor,
            pilot_id,
            data.model_dump(exclude_unset=True),
        )
        await session.commit()
        await session.refresh(row)
        return pilots.public_pilot(row)
    except pilots.GrowthControlledPilotError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/{pilot_id}/validate-read-only")
async def validate_read_only_pilot(
    pilot_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await pilots.validate_read_only_live(session, actor, pilot_id)
        await session.commit()
        await session.refresh(row)
        return pilots.public_pilot(row)
    except pilots.GrowthControlledPilotError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/{pilot_id}/authorize-launch")
async def authorize_pilot_launch(
    pilot_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await pilots.authorize_launch(session, actor, pilot_id)
        await session.commit()
        await session.refresh(row)
        return pilots.public_pilot(row)
    except pilots.GrowthControlledPilotError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/{pilot_id}/arm")
async def arm_pilot(
    pilot_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await pilots.arm_pilot(session, actor, pilot_id)
        await session.commit()
        await session.refresh(row)
        return pilots.public_pilot(row)
    except pilots.GrowthControlledPilotError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/{pilot_id}/disarm")
async def disarm_pilot(
    pilot_id: str,
    data: PilotDisarmInput,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await pilots.disarm_pilot(session, actor, pilot_id, reason=data.reason)
        await session.commit()
        await session.refresh(row)
        return pilots.public_pilot(row)
    except pilots.GrowthControlledPilotError as exc:
        await session.rollback()
        raise _error(exc) from exc
