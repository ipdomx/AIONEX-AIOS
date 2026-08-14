"""Authenticated GS-04 content operations endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_content_operations as content_ops

router = APIRouter()


class ContentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content_type: str = Field(default="text", min_length=1, max_length=40)
    base_text: str = Field(default="", max_length=100_000)
    link_url: str | None = Field(default=None, max_length=4000)
    media_refs: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    project_id: str | None = None
    content_metadata: dict = Field(default_factory=dict)


class ContentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    base_text: str | None = Field(default=None, max_length=100_000)
    link_url: str | None = Field(default=None, max_length=4000)
    media_refs: list[str] | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=100)
    content_metadata: dict | None = None


class VariantCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    account_id: str | None = None
    text: str | None = Field(default=None, max_length=100_000)
    link_url: str | None = Field(default=None, max_length=4000)
    media_refs: list[str] | None = Field(default=None, max_length=100)
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    mentions: list[str] = Field(default_factory=list, max_length=100)
    platform_overrides: dict = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=2000)


class ScheduleCreate(BaseModel):
    scheduled_for: datetime
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    recurrence: str = Field(default="none", max_length=32)
    priority: int = Field(default=50, ge=0, le=100)


class QueueSimulationRequest(BaseModel):
    now: datetime | None = None
    limit: int = Field(default=100, ge=1, le=100)


class ScheduleSimulationRequest(BaseModel):
    now: datetime | None = None


class RecycleRequest(BaseModel):
    scheduled_for: datetime


def _http_error(exc: content_ops.GrowthContentError) -> HTTPException:
    detail = str(exc)
    if detail in {"content-not-found", "variant-not-found", "schedule-not-found"}:
        return HTTPException(status_code=404, detail=detail)
    if detail.startswith("access-denied:") or detail in {
        "approval-role-required",
        "approval-required",
    }:
        return HTTPException(status_code=403, detail=detail)
    if detail in {
        "schedule-not-queued",
        "only-queued-schedule-can-cancel",
        "approval-not-pending",
        "archived-content-is-read-only",
    }:
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.get("")
async def list_content(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return {
            "items": await content_ops.list_content(session, actor),
            "live_publish_allowed": False,
        }
    except content_ops.GrowthContentError as exc:
        raise _http_error(exc) from exc


@router.post("", status_code=201)
async def create_content(
    request: ContentCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.create_content(session, actor, request.model_dump())
        await session.commit()
        return content_ops._public_item(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.get("/queue")
async def queue_snapshot(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return {
            "items": await content_ops.queue_snapshot(session, actor),
            "live_publish_allowed": False,
        }
    except content_ops.GrowthContentError as exc:
        raise _http_error(exc) from exc


@router.get("/{content_id}")
async def get_content(
    content_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await content_ops.item_with_variants(session, actor, content_id)
    except content_ops.GrowthContentError as exc:
        raise _http_error(exc) from exc


@router.patch("/{content_id}")
async def update_content(
    content_id: str,
    request: ContentUpdate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.update_content(
            session,
            actor,
            content_id,
            request.model_dump(exclude_unset=True),
        )
        await session.commit()
        return content_ops._public_item(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/{content_id}/variants", status_code=201)
async def create_variant(
    content_id: str,
    request: VariantCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.create_variant(
            session, actor, content_id, request.model_dump()
        )
        await session.commit()
        return content_ops._public_variant(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.get("/variants/{variant_id}/preview")
async def preview_variant(
    variant_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await content_ops.preview_variant(session, actor, variant_id)
    except content_ops.GrowthContentError as exc:
        raise _http_error(exc) from exc


@router.post("/{content_id}/approval/request")
async def request_approval(
    content_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.request_approval(session, actor, content_id)
        await session.commit()
        return content_ops._public_item(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/{content_id}/approval/decision")
async def decide_approval(
    content_id: str,
    request: ApprovalDecision,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.decide_approval(
            session,
            actor,
            content_id,
            approved=request.approved,
            note=request.note,
        )
        await session.commit()
        return content_ops._public_item(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/variants/{variant_id}/schedules", status_code=201)
async def schedule_variant(
    variant_id: str,
    request: ScheduleCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.schedule_variant(
            session, actor, variant_id, request.model_dump()
        )
        await session.commit()
        return content_ops._public_schedule(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/queue/simulate-due")
async def simulate_due_queue(
    request: QueueSimulationRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        items = await content_ops.simulate_due_queue(
            session,
            actor,
            now=request.now,
            limit=request.limit,
        )
        await session.commit()
        return {"items": items, "live_publish_allowed": False}
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/schedules/{schedule_id}/simulate", status_code=201)
async def simulate_schedule(
    schedule_id: str,
    request: ScheduleSimulationRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.simulate_schedule(
            session, actor, schedule_id, now=request.now
        )
        await session.commit()
        return content_ops._public_simulation(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/schedules/{schedule_id}/recycle", status_code=201)
async def recycle_schedule(
    schedule_id: str,
    request: RecycleRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.recycle_schedule(
            session,
            actor,
            schedule_id,
            request.scheduled_for,
        )
        await session.commit()
        return content_ops._public_schedule(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.delete("/schedules/{schedule_id}")
async def cancel_schedule(
    schedule_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        row = await content_ops.cancel_schedule(session, actor, schedule_id)
        await session.commit()
        return content_ops._public_schedule(row)
    except content_ops.GrowthContentError as exc:
        await session.rollback()
        raise _http_error(exc) from exc
