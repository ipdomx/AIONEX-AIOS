"""Super Owner policy, exception and conversation control; every edit is audited."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.services import conversation_governance as governance

router = APIRouter(prefix="/owner/conversation-governance", tags=["Owner Conversation Governance"])


class PolicyUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    values: dict[str, Any]


class PolicyReset(BaseModel):
    expected_version: int = Field(ge=1)


class ConversationAction(BaseModel):
    action: Literal["pause", "resume", "close"]
    user_id: str
    note: str = Field(default="", max_length=500)


@router.get("")
async def get_governance(actor: UserRecord = Depends(require_super_owner),
                         session: AsyncSession = Depends(get_db)):
    directory = await governance.owner_directory(session, actor)
    return {**directory, "defaults": governance.DEFAULTS, "policies": await governance.policy_records(session),
            "precedence": "global -> plan -> user; any disabled layer denies access",
            "credit_unit": "one accepted user turn; not currency",
            "existing_entitlement_and_billing_caps_remain": True,
            "already_dispatched_provider_work_recalled": False}


@router.put("/policies/{scope}/{identifier}")
async def put_policy(scope: str, identifier: str, data: PolicyUpdate,
                      actor: UserRecord = Depends(require_super_owner),
                      session: AsyncSession = Depends(get_db)):
    try:
        result = await governance.update_policy(session, actor, scope=scope, identifier=identifier,
                                                values=data.values, expected_version=data.expected_version)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


@router.post("/policies/{scope}/{identifier}/reset")
async def reset_policy(scope: str, identifier: str, data: PolicyReset,
                        actor: UserRecord = Depends(require_super_owner),
                        session: AsyncSession = Depends(get_db)):
    try:
        result = await governance.reset_policy(session, actor, scope=scope, identifier=identifier,
                                               expected_version=data.expected_version)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


@router.get("/conversations")
async def conversations(user_id: str | None = None,
                         actor: UserRecord = Depends(require_super_owner),
                         session: AsyncSession = Depends(get_db)):
    return await governance.owner_conversations(session, actor, user_id=user_id)


@router.get("/users/{user_id}")
async def user_policy(user_id: str, actor: UserRecord = Depends(require_super_owner),
                       session: AsyncSession = Depends(get_db)):
    target = await governance.owner_target_actor(session, actor, user_id)
    return await governance.usage_snapshot(session, target, owner=actor)


@router.post("/conversations/{conversation_id}")
async def control_conversation(conversation_id: str, data: ConversationAction,
                                actor: UserRecord = Depends(require_super_owner),
                                session: AsyncSession = Depends(get_db)):
    try:
        target = await governance.owner_target_actor(session, actor, data.user_id)
        result = await governance.change_thread(session, target, conversation_id,
                                                action=data.action, owner=actor, note=data.note)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
