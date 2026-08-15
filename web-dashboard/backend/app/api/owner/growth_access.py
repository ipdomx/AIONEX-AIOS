"""Super Owner controls for Growth & Social capabilities."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.services import growth_access, growth_meta_target_discovery

router = APIRouter(prefix="/owner/growth-social", tags=["Owner Growth & Social"])


class OverrideInput(BaseModel):
    scope: Literal["user", "organization"]
    subject_id: str = Field(min_length=1, max_length=160)
    capability: str = Field(min_length=1, max_length=120)
    allowed: bool
    approval_required: bool = False
    limits: dict[str, Any] = Field(default_factory=dict)


@router.get("/capabilities")
async def capabilities(_actor: UserRecord = Depends(require_super_owner)):
    return [{"id": key, **value} for key, value in growth_access.CAPABILITIES.items()]


@router.get("/meta-targets")
async def meta_targets(_actor: UserRecord = Depends(require_super_owner)):
    try:
        return await asyncio.to_thread(
            growth_meta_target_discovery.probe_meta_owned_targets_read_only
        )
    except growth_meta_target_discovery.MetaTargetDiscoveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/access")
async def access_overrides(
    limit: int = Query(default=500, ge=1, le=500),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await growth_access.list_owner_overrides(session, actor, limit=limit)


@router.put("/access")
async def set_access(
    data: OverrideInput,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await growth_access.set_owner_override(
            session, actor, **data.model_dump()
        )
        await session.commit()
        return result.as_dict()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/access")
async def clear_access(
    scope: Literal["user", "organization"],
    subject_id: str,
    capability: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        changed = await growth_access.clear_owner_override(
            session,
            actor,
            scope=scope,
            subject_id=subject_id,
            capability=capability,
        )
        await session.commit()
        return {"cleared": changed}
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
