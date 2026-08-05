"""Super Owner portal presentation, pricing, publication, and asset controls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.services.portal_cms import (delete_portal_asset, get_portal_snapshot,
                                     publish_portal_draft,
                                     replace_portal_draft, reset_portal_draft,
                                     rollback_portal_publication,
                                     save_portal_asset)

router = APIRouter(prefix="/owner/portal", tags=["owner-portal"])


class PortalDraftReplacement(BaseModel):
    configuration: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def owner_portal_snapshot(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    snapshot = await get_portal_snapshot(session)
    await session.commit()
    return snapshot


@router.put("/draft")
async def owner_replace_portal_draft(
    data: PortalDraftReplacement,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    draft = await replace_portal_draft(
        session,
        data.configuration,
        actor_id=actor.id,
        organization_id=actor.organization_id,
    )
    await session.commit()
    return {"draft": draft}


@router.post("/publish")
async def owner_publish_portal(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    published = await publish_portal_draft(
        session,
        actor_id=actor.id,
        organization_id=actor.organization_id,
    )
    await session.commit()
    return {"published": published}


@router.post("/rollback/{version}")
async def owner_rollback_portal(
    version: int,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    published = await rollback_portal_publication(
        session,
        version,
        actor_id=actor.id,
        organization_id=actor.organization_id,
    )
    await session.commit()
    return {"published": published}


@router.post("/reset-draft")
async def owner_reset_portal_draft(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    draft = await reset_portal_draft(
        session,
        actor_id=actor.id,
        organization_id=actor.organization_id,
    )
    await session.commit()
    return {"draft": draft}


@router.post("/assets", status_code=201)
async def owner_upload_portal_asset(
    asset: UploadFile = File(...),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    result = await save_portal_asset(
        session,
        asset,
        actor_id=actor.id,
        organization_id=actor.organization_id,
    )
    await session.commit()
    return result


@router.delete("/assets/{asset_id}", status_code=204)
async def owner_delete_portal_asset(
    asset_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    await delete_portal_asset(
        session,
        asset_id,
        actor_id=actor.id,
        organization_id=actor.organization_id,
    )
    await session.commit()
    return None
