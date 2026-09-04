"""Read-only Super Owner view of external activation boundaries."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.services.external_activation_gates import external_activation_snapshot

router = APIRouter(prefix="/owner/external-activation", tags=["owner-external-activation"])


@router.get("")
async def owner_external_activation_snapshot(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del actor
    return await external_activation_snapshot(session)
