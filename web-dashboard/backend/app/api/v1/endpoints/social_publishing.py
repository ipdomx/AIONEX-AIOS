"""P3 publishing API under /api/v1/social: posts, calendar, media and AI assist.

Every route except the signed media bridge requires the signed-in portal user
and only ever touches that user's own posts, uploads and OAuth-connected
accounts. Publishing itself is done by ``social_publish_worker``; "publish
now" queues the post for immediate pickup and never reports success before
Graph returned an id. No response contains a token.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import social as social_api
from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import AuditEvent, SocialMediaUpload, StudioAsset
from app.services import social_ai_assist as ai_assist
from app.services import social_media_access as media_access
from app.services import social_posts as posts
from app.services.media_storage import MediaStorageError, media_object_store_for_backend
from app.services.social_connectors import SocialConnectorError
from app.services.social_publishing_rules import POST_TYPES

router = APIRouter()

PostType = Literal["text", "link", "image", "carousel", "video", "reel"]
if set(POST_TYPES) != {"text", "link", "image", "carousel", "video", "reel"}:
    raise RuntimeError("social publishing post types drifted from the API contract")


class TargetOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caption: str | None = Field(default=None, max_length=posts.CAPTION_MAX)
    share_to_feed: bool | None = None


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = Field(default=3, ge=1, le=5)
    backoff_seconds: int = Field(default=60, ge=30, le=3600)


class PostPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_type: PostType
    caption: str = Field(default="", max_length=posts.CAPTION_MAX)
    link_url: str | None = Field(default=None, max_length=2048)
    media: list[str] = Field(default_factory=list, max_length=media_access.MAX_MEDIA_PER_POST)
    account_ids: list[str] = Field(min_length=1, max_length=posts.MAX_TARGETS)
    overrides: dict[str, TargetOverride] = Field(default_factory=dict)
    timezone: str = Field(default="UTC", max_length=64)
    retry_policy: RetryPolicy | None = None
    client_idempotency_key: str | None = Field(default=None, max_length=80)

    def service_data(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"overrides", "retry_policy"})
        data["overrides"] = {
            key: value.model_dump(exclude_none=True) for key, value in self.overrides.items()
        }
        data["retry_policy"] = self.retry_policy.model_dump() if self.retry_policy else None
        return data


class SchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: datetime
    timezone: str | None = Field(default=None, max_length=64)


class AssistPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["draft", "improve", "hashtags"]
    text: str = Field(default="", max_length=5000)
    topic: str = Field(default="", max_length=1000)
    language: Literal["ar", "en", "fr", "de", "es", "tr"] = "ar"
    platforms: list[Literal["facebook", "instagram"]] = Field(default_factory=list, max_length=2)
    tone: Literal["friendly", "professional", "playful", "inspiring", "promotional"] = "friendly"
    external_processing_confirmed: bool = False


def _fail(exc: SocialConnectorError):
    return social_api._error(exc)


async def _limit(actor: UserRecord, action: str) -> None:
    # Resolved through the module so tests can replace the Redis limiter.
    await social_api.enforce_rate_limit(actor, action)


# --- posts and calendar -----------------------------------------------------------------


@router.get("/posts")
async def list_posts(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await posts.list_posts(session, actor, start=start, end=end, status=status_filter)
    except SocialConnectorError as exc:
        raise _fail(exc) from exc


@router.post("/posts/validate")
async def validate_post(
    payload: PostPayload,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "validate")
    try:
        return await posts.preview_post(session, actor, payload.service_data())
    except SocialConnectorError as exc:
        raise _fail(exc) from exc


@router.post("/posts", status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostPayload,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "post_write")
    try:
        result = await posts.create_draft(session, actor, payload.service_data())
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.get("/posts/{post_id}")
async def get_post(
    post_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await posts.get_post(session, actor, post_id)
    except SocialConnectorError as exc:
        raise _fail(exc) from exc


@router.patch("/posts/{post_id}")
async def update_post(
    post_id: str,
    payload: PostPayload,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "post_write")
    try:
        result = await posts.update_post(session, actor, post_id, payload.service_data())
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "post_write")
    try:
        result = await posts.delete_post(session, actor, post_id)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.post("/posts/{post_id}/schedule")
async def schedule_post(
    post_id: str,
    payload: SchedulePayload,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "publish")
    try:
        result = await posts.schedule_post(
            session, actor, post_id, scheduled_at=payload.scheduled_at, timezone_name=payload.timezone
        )
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.post("/posts/{post_id}/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_post(
    post_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "publish")
    try:
        result = await posts.publish_now(session, actor, post_id)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.post("/posts/{post_id}/cancel")
async def cancel_post(
    post_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "publish")
    try:
        result = await posts.cancel_post(session, actor, post_id)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


# --- media ------------------------------------------------------------------------------


@router.get("/media")
async def list_media(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    uploads = (
        await session.scalars(
            select(SocialMediaUpload)
            .where(
                SocialMediaUpload.organization_id == actor.organization_id,
                SocialMediaUpload.user_id == actor.id,
                SocialMediaUpload.status == "ready",
            )
            .order_by(SocialMediaUpload.created_at.desc())
            .limit(100)
        )
    ).all()
    studio = (
        await session.scalars(
            select(StudioAsset)
            .where(
                StudioAsset.organization_id == actor.organization_id,
                StudioAsset.created_by_id == actor.id,
                StudioAsset.status == "active",
            )
            .order_by(StudioAsset.created_at.desc())
            .limit(200)
        )
    ).all()
    allowed = {*media_access.IMAGE_TYPES, *media_access.VIDEO_TYPES}
    return {
        "uploads": [media_access.public_upload(row) for row in uploads],
        "studio": [
            media_access.public_studio_asset(row)
            for row in studio
            if str(row.media_type or "").split(";")[0].strip().lower() in allowed
        ][:100],
    }


@router.post("/media", status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "upload")
    body = await file.read(media_access.UPLOAD_VIDEO_MAX_BYTES + 1)
    try:
        if len(body) > media_access.UPLOAD_VIDEO_MAX_BYTES:
            raise SocialConnectorError("media-too-large", status_code=413)
        row = media_access.store_upload(
            organization_id=actor.organization_id,
            user_id=actor.id,
            body=body,
            filename=file.filename,
            declared_type=file.content_type,
        )
        session.add(row)
        session.add(
            AuditEvent(
                organization_id=actor.organization_id,
                user_id=actor.id,
                action="social.media.uploaded",
                resource_type="social_media_upload",
                resource_id=row.id,
                details={"publishing": "p3", "kind": row.kind, "size_bytes": row.size_bytes},
            )
        )
        await session.commit()
        return media_access.public_upload(row)
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc


@router.delete("/media/{media_id}")
async def delete_media(
    media_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "upload")
    row = await session.scalar(
        select(SocialMediaUpload).where(
            SocialMediaUpload.id == media_id,
            SocialMediaUpload.organization_id == actor.organization_id,
            SocialMediaUpload.user_id == actor.id,
            SocialMediaUpload.status == "ready",
        )
    )
    if row is None:
        raise _fail(SocialConnectorError("media-not-found", status_code=404))
    row.status = "deleted"
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="social.media.deleted",
            resource_type="social_media_upload",
            resource_id=row.id,
            details={"publishing": "p3"},
        )
    )
    await session.commit()
    try:
        media_object_store_for_backend(row.storage_backend).delete(row.storage_key)
    except MediaStorageError:
        # The row is already unusable; an orphaned object is left for storage hygiene.
        return {"id": media_id, "deleted": True, "object_removed": False}
    return {"id": media_id, "deleted": True, "object_removed": True}


@router.get("/media/public/{token}/{filename}", include_in_schema=False)
async def public_media(
    token: str,
    filename: str,
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Signed, short-lived bridge that lets Meta fetch one verified file."""

    try:
        path, media_type = await media_access.bridge_file(session, token, filename)
    except SocialConnectorError as exc:
        raise _fail(SocialConnectorError("media-not-found", status_code=404)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Content-Disposition": f'inline; filename="{filename}"',
            "Referrer-Policy": "no-referrer",
        },
    )


# --- AI assist --------------------------------------------------------------------------


@router.post("/ai/assist")
async def ai_assist_caption(
    payload: AssistPayload,
    response: Response,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _limit(actor, "ai_assist")
    response.headers["Cache-Control"] = "no-store"
    try:
        return await ai_assist.assist(
            session,
            actor,
            mode=payload.mode,
            text=payload.text,
            topic=payload.topic,
            language=payload.language,
            platforms=list(payload.platforms),
            tone=payload.tone,
            external_processing_confirmed=payload.external_processing_confirmed,
        )
    except SocialConnectorError as exc:
        await session.rollback()
        raise _fail(exc) from exc
