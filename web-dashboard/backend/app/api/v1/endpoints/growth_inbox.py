from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_unified_inbox as inbox

router = APIRouter()


class SimulatedEventPayload(BaseModel):
    provider: str
    external_thread_ref: str
    external_message_ref: str
    thread_type: str
    message_type: str | None = None
    body: str
    account_id: str | None = None
    participant_ref: str | None = None
    participant_name: str | None = None
    author_ref: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class TogglePayload(BaseModel):
    value: bool


class AssignPayload(BaseModel):
    assignee_id: str | None = None


class LeadLinkPayload(BaseModel):
    lead_id: str | None = None


class NotePayload(BaseModel):
    body: str


class ReplyDraftPayload(BaseModel):
    body: str
    template_key: str | None = None
    ai_suggested: bool = False


class StatusPayload(BaseModel):
    status: str


def _code(exc: Exception) -> int:
    detail = str(exc)
    if detail.startswith("access-denied:"):
        return status.HTTP_403_FORBIDDEN
    if detail.endswith("not-found"):
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


@router.get("")
async def threads(
    status_filter: str | None = Query(default=None, alias="status"),
    provider: str | None = None,
    q: str | None = None,
    starred: bool | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        rows = await inbox.list_threads(
            session,
            actor,
            status=status_filter,
            provider=provider,
            query=q,
            starred=starred,
            limit=limit,
        )
        return {
            "items": [inbox.public_thread(row) for row in rows],
            "live_provider_call": False,
        }
    except inbox.GrowthInboxError as exc:
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/simulate-inbound")
async def simulate_inbound(
    payload: SimulatedEventPayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        thread, message, created = await inbox.ingest_simulated_event(
            session, actor, payload.model_dump()
        )
        await session.commit()
        return {
            "thread": inbox.public_thread(thread),
            "message": inbox.public_message(message),
            "thread_created": created,
        }
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.get("/{thread_id}/messages")
async def messages(
    thread_id: str,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        rows = await inbox.list_messages(session, actor, thread_id)
        return {
            "items": [inbox.public_message(row) for row in rows],
            "external_send_allowed": False,
        }
    except inbox.GrowthInboxError as exc:
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/{thread_id}/read")
async def read_state(
    thread_id: str,
    payload: TogglePayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        row = await inbox.mark_read(session, actor, thread_id, payload.value)
        await session.commit()
        return inbox.public_thread(row)
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/{thread_id}/star")
async def star(
    thread_id: str,
    payload: TogglePayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        row = await inbox.set_starred(session, actor, thread_id, payload.value)
        await session.commit()
        return inbox.public_thread(row)
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/{thread_id}/assign")
async def assign(
    thread_id: str,
    payload: AssignPayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        row = await inbox.assign_thread(session, actor, thread_id, payload.assignee_id)
        await session.commit()
        return inbox.public_thread(row)
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/{thread_id}/lead")
async def link_lead(
    thread_id: str,
    payload: LeadLinkPayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        row = await inbox.link_lead(session, actor, thread_id, payload.lead_id)
        await session.commit()
        return inbox.public_thread(row)
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/{thread_id}/notes")
async def note(
    thread_id: str,
    payload: NotePayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        row = await inbox.add_note(session, actor, thread_id, payload.body)
        await session.commit()
        return {"id": row.id, "thread_id": row.thread_id, "body": row.body}
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/{thread_id}/reply-drafts")
async def reply_draft(
    thread_id: str,
    payload: ReplyDraftPayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        row = await inbox.create_quick_reply_draft(
            session,
            actor,
            thread_id,
            body=payload.body,
            template_key=payload.template_key,
            ai_suggested=payload.ai_suggested,
        )
        await session.commit()
        return inbox.public_quick_reply(row)
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc


@router.post("/{thread_id}/status")
async def thread_status(
    thread_id: str,
    payload: StatusPayload,
    session: AsyncSession = Depends(get_db),
    actor: UserRecord = Depends(current_user),
) -> dict[str, Any]:
    try:
        row = await inbox.close_thread(session, actor, thread_id, payload.status)
        await session.commit()
        return inbox.public_thread(row)
    except inbox.GrowthInboxError as exc:
        await session.rollback()
        raise HTTPException(status_code=_code(exc), detail=str(exc)) from exc
