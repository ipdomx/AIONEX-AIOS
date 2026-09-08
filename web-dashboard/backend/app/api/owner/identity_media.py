"""Super Owner Identity Media access governance."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.services import identity_media_access

router = APIRouter(prefix="/owner/identity-media", tags=["Owner Identity Media"])

RealIdentityBasis = Literal["self", "consented_person", "licensed_public_figure"]


def _default_identity_bases() -> list[RealIdentityBasis]:
    return ["self", "consented_person"]


class IdentityMediaAccessUpdate(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    operation: Literal[
        "voice_clone",
        "voice_transform",
        "face_reenactment",
        "face_swap",
        "talking_head",
        "lip_sync",
        "avatar_generation",
    ]
    allowed: bool
    identity_bases: list[RealIdentityBasis] = Field(
        default_factory=_default_identity_bases, min_length=1, max_length=3
    )
    subject_scope: Literal["any", "exact"] = "any"
    subject_reference: str | None = Field(default=None, max_length=200)
    note: str = Field(default="", max_length=1000)


class IdentityMediaRequestReview(BaseModel):
    decision: Literal["approved", "denied", "revoked"]
    review_note: str = Field(default="", max_length=1000)


@router.get("")
async def snapshot(
    query: str = Query(default="", max_length=160),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return {
        "operations": list(identity_media_access.OPERATIONS),
        "runtime_ready_operations": sorted(identity_media_access.RUNTIME_READY_OPERATIONS),
        "policy": {
            "fictional_inspired": "direct_when_runtime_ready",
            "real_person": "super_owner_approval_plus_rights_evidence",
            "licensed_public_figure": "super_owner_approval_plus_licensed_catalog_authority",
            "owner_can_grant_deny_revoke_per_user": True,
            "owner_grant_is_legal_license": False,
        },
        "access": await identity_media_access.list_owner_access(
            session, actor, search=query
        ),
        "pending_requests": await identity_media_access.list_owner_requests(
            session, actor, status="pending"
        ),
        "raw_credentials_returned": False,
    }


@router.get("/users")
async def users(
    query: str = Query(default="", max_length=160),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return {
        "users": await identity_media_access.search_users(
            session, actor, query=query, limit=30
        )
    }


@router.put("/access")
async def put_access(
    data: IdentityMediaAccessUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await identity_media_access.set_owner_access(
            session,
            actor,
            user_id=data.user_id,
            operation=data.operation,
            allowed=data.allowed,
            identity_bases=data.identity_bases,
            subject_scope=data.subject_scope,
            subject_reference=data.subject_reference,
            note=data.note,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/access/{user_id}/{operation}")
async def delete_access(
    user_id: str,
    operation: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        cleared = await identity_media_access.clear_owner_access(
            session,
            actor,
            user_id=user_id,
            operation=operation,
        )
        await session.commit()
        return {"cleared": cleared, "user_id": user_id, "operation": operation}
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/requests")
async def requests(
    status: Literal["pending", "approved", "denied", "revoked"] | None = None,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return {
        "requests": await identity_media_access.list_owner_requests(
            session, actor, status=status
        )
    }


@router.put("/requests/{request_id}")
async def review_request(
    request_id: str,
    data: IdentityMediaRequestReview,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await identity_media_access.review_access_request(
            session,
            actor,
            request_id=request_id,
            decision=data.decision,
            review_note=data.review_note,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
