"""Durable tenant-scoped support requests and private conversations."""

from __future__ import annotations

from typing import Any, Literal

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import SupportMessage, SupportRequest
from app.services import communications
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class SupportRequestCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=240)
    message: str = Field(min_length=10, max_length=10000)
    category: Literal["general", "technical", "billing", "security", "account", "project"] = "general"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    context: dict[str, Any] = Field(default_factory=dict)


class SupportMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    visibility: Literal["requester", "internal"] = "requester"


class SupportStatusUpdate(BaseModel):
    status: Literal["open", "in_progress", "waiting_user", "resolved", "closed"]
    assigned_to_id: str | None = None


def _can_manage(actor: UserRecord) -> bool:
    return "*" in actor.permissions or "support:manage" in actor.permissions


async def _ticket(
    session: AsyncSession,
    actor: UserRecord,
    request_id: str,
    *,
    for_update: bool = False,
) -> SupportRequest:
    statement = select(SupportRequest).where(SupportRequest.id == request_id)
    if actor.role != "Super Owner" and "*" not in actor.permissions:
        statement = statement.where(SupportRequest.organization_id == actor.organization_id)
    if not _can_manage(actor):
        statement = statement.where(SupportRequest.requester_id == actor.id)
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Support request not found")
    return item


@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def create_request(
    data: SupportRequestCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        ticket, notifications = await communications.create_support_request(
            session,
            actor,
            subject=data.subject,
            message=data.message,
            category=data.category,
            priority=data.priority,
            request_metadata={"context": data.context},
        )
        await session.commit()
        await session.refresh(ticket)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return communications.support_snapshot(ticket, messages=1)


@router.get("/requests")
async def list_requests(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    statement = (
        select(SupportRequest, func.count(SupportMessage.id))
        .outerjoin(
            SupportMessage, SupportMessage.support_request_id == SupportRequest.id
        )
        .group_by(SupportRequest.id)
        .order_by(SupportRequest.updated_at.desc())
        .limit(limit)
    )
    if actor.role != "Super Owner" and "*" not in actor.permissions:
        statement = statement.where(SupportRequest.organization_id == actor.organization_id)
    if not _can_manage(actor):
        statement = statement.where(SupportRequest.requester_id == actor.id)
    if status_filter:
        statement = statement.where(SupportRequest.status == status_filter)
    rows = (await session.execute(statement)).all()
    return [
        communications.support_snapshot(ticket, messages=int(count or 0))
        for ticket, count in rows
    ]


@router.get("/requests/{request_id}")
async def get_request(
    request_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    ticket = await _ticket(session, actor, request_id)
    statement = select(SupportMessage).where(
        SupportMessage.support_request_id == ticket.id
    )
    if not _can_manage(actor):
        statement = statement.where(SupportMessage.visibility == "requester")
    messages = list(
        (
            await session.scalars(statement.order_by(SupportMessage.created_at))
        ).all()
    )
    return {
        **communications.support_snapshot(ticket, messages=len(messages)),
        "messages": [communications.support_message_snapshot(item) for item in messages],
    }


@router.post("/requests/{request_id}/messages", status_code=status.HTTP_201_CREATED)
async def add_message(
    request_id: str,
    data: SupportMessageCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    ticket = await _ticket(session, actor, request_id, for_update=True)
    manager = _can_manage(actor)
    try:
        message, notifications = await communications.add_support_message(
            session,
            actor,
            ticket,
            message=data.message,
            visibility=data.visibility,
            manager=manager,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return communications.support_message_snapshot(message)


@router.patch("/requests/{request_id}")
async def update_request(
    request_id: str,
    data: SupportStatusUpdate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    ticket = await _ticket(session, actor, request_id, for_update=True)
    if not _can_manage(actor) and data.status not in {"open", "closed"}:
        raise HTTPException(
            status_code=403, detail="support:manage is required for this status"
        )
    if not _can_manage(actor) and data.assigned_to_id is not None:
        raise HTTPException(
            status_code=403, detail="support:manage is required to assign requests"
        )
    try:
        await communications.update_support_status(
            session,
            actor,
            ticket,
            status=data.status,
            assigned_to_id=data.assigned_to_id,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return communications.support_snapshot(ticket)
