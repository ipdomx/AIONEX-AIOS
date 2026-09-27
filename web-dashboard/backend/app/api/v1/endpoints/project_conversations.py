"""User-owned, project-scoped conversations with server-enforced Owner limits."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.services import conversation_governance as governance

router = APIRouter()


class ConversationCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=240)
    request_id: str = Field(min_length=8, max_length=128)


class MessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=50000)
    request_id: str = Field(min_length=8, max_length=128)
    agent_id: str = ""
    confirm_external_processing: bool = False


@router.get("/policy")
async def policy(actor: UserRecord = Depends(require_permissions("projects:write")),
                 session: AsyncSession = Depends(get_db)):
    return await governance.usage_snapshot(session, actor)


@router.get("/agents")
async def agents(actor: UserRecord = Depends(require_permissions("projects:write")),
                 session: AsyncSession = Depends(get_db)):
    return await governance.available_agents(session, actor)


@router.get("")
async def list_conversations(project_id: str | None = None,
                             actor: UserRecord = Depends(require_permissions("projects:write")),
                             session: AsyncSession = Depends(get_db)):
    return await governance.list_threads(session, actor, project_id)


@router.post("", status_code=201)
async def create_conversation(data: ConversationCreate,
                              actor: UserRecord = Depends(require_permissions("projects:write")),
                              session: AsyncSession = Depends(get_db)):
    try:
        result = await governance.create_thread(session, actor, **data.model_dump())
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


@router.get("/{conversation_id}/messages")
async def get_messages(conversation_id: str,
                       actor: UserRecord = Depends(require_permissions("projects:write")),
                       session: AsyncSession = Depends(get_db)):
    return await governance.messages(session, actor, conversation_id)


@router.post("/{conversation_id}/messages", status_code=202)
async def send_message(conversation_id: str, data: MessageCreate,
                       actor: UserRecord = Depends(require_permissions("projects:write")),
                       session: AsyncSession = Depends(get_db)):
    try:
        result = await governance.send_message(session, actor, conversation_id, **data.model_dump())
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


@router.post("/{conversation_id}/close")
async def close_conversation(conversation_id: str,
                             actor: UserRecord = Depends(require_permissions("projects:write")),
                             session: AsyncSession = Depends(get_db)):
    try:
        result = await governance.change_thread(session, actor, conversation_id, action="close")
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
