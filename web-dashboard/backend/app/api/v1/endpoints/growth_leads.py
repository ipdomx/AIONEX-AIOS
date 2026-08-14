"""Authenticated GS-06 compliant lead intelligence endpoints."""

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_lead_intelligence as leads

router = APIRouter()


class LeadUpsertRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=240)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)
    company_name: str | None = Field(default=None, max_length=240)
    country_code: str | None = Field(default=None, max_length=2)
    source_type: str
    collection_method: str
    source_ref: str | None = Field(default=None, max_length=500)
    source_metadata: dict = Field(default_factory=dict)
    attributes: dict = Field(default_factory=dict)
    retention_until: datetime | None = None


class ConsentRequest(BaseModel):
    purpose: str
    lawful_basis: str
    captured_at: datetime | None = None
    expires_at: datetime | None = None
    evidence: dict = Field(default_factory=dict)


class SuppressionRequest(BaseModel):
    channel: str
    reason: str = Field(default="user-opt-out", max_length=120)


class EligibilityRequest(BaseModel):
    purpose: str
    channel: str


def _code(exc: Exception) -> int:
    text = str(exc)
    if text.startswith("access-denied:"):
        return 403
    if text.endswith("not-found"):
        return 404
    return 400


@router.get("")
async def list_leads(
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        items = await leads.list_leads(session, actor, limit)
    except leads.GrowthLeadError as exc:
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc
    return {
        "items": items,
        "unauthorized_scraping_allowed": False,
        "outbound_outreach_allowed": False,
        "live_audience_upload_allowed": False,
        "live_provider_call": False,
    }


@router.post("", status_code=201)
async def upsert_lead(
    request: LeadUpsertRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row, created = await leads.upsert_lead(session, actor, request.model_dump())
        await session.commit()
    except leads.GrowthLeadError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc
    return {"lead": leads.public_lead(row), "created": created}


@router.post("/{lead_id}/lawful-basis", status_code=201)
async def set_lawful_basis(
    lead_id: str,
    request: ConsentRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await leads.set_consent(session, actor, lead_id, request.model_dump())
        await session.commit()
    except leads.GrowthLeadError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc
    return {
        "id": row.id,
        "lead_id": row.lead_id,
        "purpose": row.purpose,
        "lawful_basis": row.lawful_basis,
        "status": row.status,
        "expires_at": row.expires_at,
    }


@router.post("/{lead_id}/suppress", status_code=201)
async def suppress_lead(
    lead_id: str,
    request: SuppressionRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await leads.suppress(
            session, actor, lead_id, request.channel, request.reason
        )
        await session.commit()
    except leads.GrowthLeadError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc
    return {
        "lead_id": row.lead_id,
        "channel": row.channel,
        "reason": row.reason,
        "active": row.active,
    }


@router.post("/lawful-basis/{consent_id}/withdraw")
async def withdraw_lawful_basis(
    consent_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await leads.withdraw_consent(session, actor, consent_id)
        await session.commit()
    except leads.GrowthLeadError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc
    return {"id": row.id, "status": row.status, "withdrawn_at": row.withdrawn_at}


@router.post("/{lead_id}/eligibility")
async def evaluate_eligibility(
    lead_id: str,
    request: EligibilityRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await leads.eligibility(
            session, actor, lead_id, purpose=request.purpose, channel=request.channel
        )
        await session.commit()
    except leads.GrowthLeadError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc
    return result
