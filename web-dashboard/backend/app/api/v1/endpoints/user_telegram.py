"""Authenticated public-user Telegram linking endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import user_telegram_auth

router = APIRouter()


@router.get("/status")
async def telegram_user_status(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await user_telegram_auth.status_snapshot(session, actor)


@router.post("/link-challenge")
async def create_telegram_user_link_challenge(
    response: Response,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    result = await user_telegram_auth.issue_link_challenge(session, actor)
    await session.commit()
    return result


@router.delete("/link")
async def revoke_telegram_user_link(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    changed = await user_telegram_auth.revoke_link(session, actor)
    await session.commit()
    return {"revoked": changed}
