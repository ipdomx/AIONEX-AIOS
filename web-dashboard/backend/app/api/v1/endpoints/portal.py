"""Public read-only portal configuration and asset endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import get_db
from app.services.portal_cms import get_portal_asset, get_published_portal

router = APIRouter()


@router.get("/published")
async def published_portal_configuration(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    payload = await get_published_portal(session)
    await session.commit()
    etag = f'"{payload.pop("etag")}"'
    if request.headers.get("if-none-match") == etag:
        response.status_code = 304
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = (
            f"public, max-age={settings.PORTAL_PUBLIC_CACHE_SECONDS}, "
            "stale-while-revalidate=300"
        )
        return None
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = (
        f"public, max-age={settings.PORTAL_PUBLIC_CACHE_SECONDS}, "
        "stale-while-revalidate=300"
    )
    response.headers["Vary"] = "Accept-Encoding"
    return payload


@router.get("/assets/{asset_id}")
async def public_portal_asset(
    asset_id: str,
    session: AsyncSession = Depends(get_db),
):
    asset = await get_portal_asset(session, asset_id)
    await session.commit()
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": f'"{asset["sha256"]}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": f'inline; filename="{asset["asset_id"]}.{asset["extension"]}"',
    }
    return FileResponse(
        asset["resolved_path"],
        media_type=asset["media_type"],
        headers=headers,
    )
