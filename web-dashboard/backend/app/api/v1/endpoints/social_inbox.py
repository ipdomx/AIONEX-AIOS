"""P3 unified inbox API under /api/v1/social/inbox (roadmap 3.6).

Every route requires the signed-in portal user and only reads or acts on
conversations of that user's own OAuth-connected accounts. Replies, comment
moderation and webhook subscription call the Graph API; a DM reply outside
Meta's 24-hour window is refused with ``messaging-window-closed``. The AI
suggestion is charged to the plan quota and is never sent by itself. No
response contains a token.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import social as social_api
from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import social_ai_assist as ai_assist
from app.services import social_inbox as inbox
from app.services.social_connectors import SocialConnectorError
from app.services.social_meta_inbox import REPLY_MAX

router = APIRouter()


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: bool | None = None
    status: Literal["open", "pending", "closed"] | None = None
    assigned_to_id: str | None = Field(default=None, min_length=36, max_length=36)
    unassign: bool = False


class ReplyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=REPLY_MAX)


class SuggestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["ar", "en", "fr", "de", "es", "tr"] = "ar"
    tone: Literal["friendly", "professional", "playful", "inspiring", "promotional"] = "friendly"
    external_processing_confirmed: bool = False


class VisibilityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: bool


def _fail(exc: SocialConnectorError):
    return social_api._error(exc)


async def _limit(actor: UserRecord, action: str) -> None:
    # Resolved through the module so tests can replace the Redis limiter.
    await social_api.enforce_rate_limit(actor, action)


@router.get("/inbox/status")
async def inbox_status(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await inbox.readiness(session, actor)


@router.post("/inbox/accounts/{account_id}/subscribe")
async def subscribe_account(
    account_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "inbox_subscribe")
    try:
        result = await inbox.subscribe_account(session, actor, account_id)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.get("/inbox/conversations")
async def list_conversations(
    response: Response,
    platform: Literal["facebook", "instagram"] | None = Query(default=None),
    channel: Literal["comment", "dm"] | None = Query(default=None),
    unread: bool | None = Query(default=None),
    status_filter: Literal["open", "pending", "closed"] | None = Query(default=None, alias="status"),
    before: datetime | None = Query(default=None),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await inbox.list_conversations(
            session,
            actor,
            platform=platform,
            channel=channel,
            unread=unread,
            status=status_filter,
            before=before,
        )
    except SocialConnectorError as exc:
        raise _fail(exc) from exc


@router.get("/inbox/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    response: Response,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await inbox.get_conversation(session, actor, conversation_id)
    except SocialConnectorError as exc:
        raise _fail(exc) from exc


@router.patch("/inbox/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await inbox.update_conversation(
            session,
            actor,
            conversation_id,
            read=payload.read,
            status=payload.status,
            assigned_to_id=payload.assigned_to_id,
            unassign=payload.unassign,
        )
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.post("/inbox/conversations/{conversation_id}/reply")
async def reply(
    conversation_id: str,
    payload: ReplyPayload,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "inbox_reply")
    try:
        result = await inbox.reply(session, actor, conversation_id, payload.text)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.post("/inbox/conversations/{conversation_id}/suggest")
async def suggest_reply(
    conversation_id: str,
    payload: SuggestPayload,
    response: Response,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "inbox_suggest")
    response.headers["Cache-Control"] = "no-store"
    try:
        row, history = await inbox.suggestion_context(session, actor, conversation_id)
        return await ai_assist.suggest_reply(
            session,
            actor,
            channel=row.channel,
            platform=row.provider,
            history=history,
            language=payload.language,
            tone=payload.tone,
            external_processing_confirmed=payload.external_processing_confirmed,
        )
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.post("/inbox/messages/{message_id}/visibility")
async def set_visibility(
    message_id: str,
    payload: VisibilityPayload,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "inbox_moderate")
    try:
        result = await inbox.set_message_hidden(session, actor, message_id, payload.hidden)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc
