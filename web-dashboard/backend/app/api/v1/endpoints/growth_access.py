"""Authenticated Growth & Social effective-access endpoints."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_access
router = APIRouter()

@router.get("/access")
async def access_snapshot(actor: UserRecord = Depends(current_user), session: AsyncSession = Depends(get_db)):
    return await growth_access.snapshot(session, actor)
