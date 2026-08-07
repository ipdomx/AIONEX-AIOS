"""Mobile and PWA release delivery registry for Phase 29H."""

from __future__ import annotations

from typing import Any

from app.core.auth import UserRecord, current_user, require_super_owner
from app.db.base import get_db
from app.db.models import MobileRelease, MobileReleaseArtifact, MobileValidationRun
from app.services import mobile_delivery
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def _release_rows(
    session: AsyncSession,
    *,
    platform: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    statement = select(MobileRelease)
    if platform:
        statement = statement.where(MobileRelease.platform == platform)
    releases = (
        await session.scalars(
            statement.order_by(MobileRelease.created_at.desc()).limit(limit)
        )
    ).all()
    rows: list[dict[str, Any]] = []
    for release in releases:
        artifacts = list(
            (
                await session.scalars(
                    select(MobileReleaseArtifact)
                    .where(MobileReleaseArtifact.release_id == release.id)
                    .order_by(MobileReleaseArtifact.artifact_type)
                )
            ).all()
        )
        validations = list(
            (
                await session.scalars(
                    select(MobileValidationRun)
                    .where(MobileValidationRun.release_id == release.id)
                    .order_by(MobileValidationRun.created_at)
                )
            ).all()
        )
        rows.append(mobile_delivery.release_snapshot(release, artifacts, validations))
    return rows


@router.get("/readiness")
async def readiness(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = await _release_rows(session, platform=None, limit=20)
    latest: dict[str, dict[str, Any]] = {}
    for item in rows:
        latest.setdefault(item["platform"], item)
    platforms = {}
    for platform in ("pwa", "android", "ios"):
        release = latest.get(platform)
        platforms[platform] = {
            "registered": release is not None,
            "status": release["status"] if release else "not_built",
            "version": release["version"] if release else None,
            "signing_status": release["signing_status"] if release else "unavailable",
            "publication_status": release["publication_status"] if release else "not_published",
            "validations_passed": bool(release) and all(
                item["status"] == "passed" for item in release["validations"]
            ),
        }
    return {
        "organization_id": actor.organization_id,
        "platforms": platforms,
        "pwa_host_deployment_deferred": True,
        "ai_vip_dns_changed": False,
        "store_publication_automatic": False,
        "provider_activation_batch": "29J",
    }


@router.get("/releases")
async def list_releases(
    platform: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    if platform and platform not in mobile_delivery.PLATFORMS:
        raise HTTPException(status_code=422, detail="Unsupported mobile platform")
    return await _release_rows(session, platform=platform, limit=limit)


@router.get("/releases/{release_id}")
async def get_release(
    release_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    release = await session.get(MobileRelease, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Mobile release not found")
    artifacts = list(
        (
            await session.scalars(
                select(MobileReleaseArtifact).where(
                    MobileReleaseArtifact.release_id == release.id
                )
            )
        ).all()
    )
    validations = list(
        (
            await session.scalars(
                select(MobileValidationRun).where(
                    MobileValidationRun.release_id == release.id
                )
            )
        ).all()
    )
    return mobile_delivery.release_snapshot(release, artifacts, validations)


@router.get("/releases/{release_id}/artifacts/{artifact_id}/download")
async def download_release_artifact(
    release_id: str,
    artifact_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    artifact = await session.scalar(
        select(MobileReleaseArtifact).where(
            MobileReleaseArtifact.id == artifact_id,
            MobileReleaseArtifact.release_id == release_id,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Mobile release artifact not found")
    try:
        path = mobile_delivery.verify_artifact(
            artifact.storage_path, artifact.checksum, artifact.size_bytes
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=artifact.filename,
        media_type=artifact.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-AIONEX-Checksum-SHA256": artifact.checksum,
            "X-AIONEX-Signed": "true" if artifact.signed else "false",
        },
    )
