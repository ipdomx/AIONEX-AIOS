"""Runtime enforcement helpers for durable Owner control-plane policies."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OwnerControlRecord


async def require_owner_service_allowed(
    session: AsyncSession,
    service_id: str,
) -> None:
    """Block a governed service when the Owner has paused its use."""

    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == "services",
            OwnerControlRecord.resource_id == service_id.strip().lower(),
        )
    )
    if record is not None and (
        not record.enabled or record.status in {"paused", "suspended", "offline"}
    ):
        raise HTTPException(
            status_code=409,
            detail=f"{service_id} is blocked by the Owner service policy",
        )
