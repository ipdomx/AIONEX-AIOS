"""Authenticated GS-03 managed social account registry endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_social_accounts as social_accounts

router = APIRouter()


class SocialAccountCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    account_kind: str = Field(min_length=1, max_length=48)
    external_account_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=240)
    public_handle: str | None = Field(default=None, max_length=255)
    workspace_id: str | None = None
    credential_ref: str | None = Field(default=None, max_length=320)
    token_expires_at: datetime | None = None
    provider_metadata: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class TeamAssignment(BaseModel):
    team_id: str | None = None


def _http_error(exc: social_accounts.GrowthSocialAccountError) -> HTTPException:
    detail = str(exc)
    if detail == "account-not-found":
        return HTTPException(status_code=404, detail=detail)
    if detail.startswith("access-denied:"):
        return HTTPException(status_code=403, detail=detail)
    if detail in {"account-already-registered"}:
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.get("/providers/capabilities")
async def provider_capability_matrix(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        payload = await social_accounts.capability_matrix(session, actor)
        await session.commit()
        return payload
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.get("/accounts")
async def list_managed_social_accounts(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return {
            "items": await social_accounts.list_accounts(session, actor),
            "live_provider_calls_allowed": False,
        }
    except social_accounts.GrowthSocialAccountError as exc:
        raise _http_error(exc) from exc


@router.post("/accounts", status_code=201)
async def register_managed_social_account(
    request: SocialAccountCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await social_accounts.register_account(
            session, actor, request.model_dump()
        )
        await session.commit()
        items = await social_accounts.list_accounts(session, actor)
        return next(item for item in items if item["id"] == row.id)
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/accounts/{account_id}/pause")
async def pause_managed_social_account(
    account_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        payload = await social_accounts.pause_account(session, actor, account_id)
        await session.commit()
        return payload
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/accounts/{account_id}/resume")
async def resume_managed_social_account(
    account_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        payload = await social_accounts.resume_account(session, actor, account_id)
        await session.commit()
        return payload
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.delete("/accounts/{account_id}")
async def disconnect_managed_social_account(
    account_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        payload = await social_accounts.disconnect_account(session, actor, account_id)
        await session.commit()
        return payload
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.put("/accounts/{account_id}/team")
async def assign_managed_social_account_team(
    account_id: str,
    request: TeamAssignment,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        payload = await social_accounts.assign_team(
            session, actor, account_id, request.team_id
        )
        await session.commit()
        return payload
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/accounts/{account_id}/health/simulate")
async def simulate_managed_social_account_health(
    account_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        payload = await social_accounts.simulate_health(session, actor, account_id)
        await session.commit()
        return payload
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/accounts/{account_id}/capabilities/{capability}/simulate")
async def simulate_managed_social_account_capability(
    account_id: str,
    capability: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        payload = await social_accounts.simulate_capability(
            session, actor, account_id, capability
        )
        await session.commit()
        return payload
    except social_accounts.GrowthSocialAccountError as exc:
        await session.rollback()
        raise _http_error(exc) from exc
