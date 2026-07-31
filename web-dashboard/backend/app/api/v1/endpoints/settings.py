"""Authenticated, database-backed account and preference settings."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.auth import UserRecord, current_user, pwd_context
from app.core.config import settings
from app.db.base import get_db
from app.db.models import OwnerControlRecord, RefreshSession, User, uuid_str
from app.services.free_tier import (
    FREE_USER_ROLE_NAME,
    adjust_storage_usage,
    avatar_data_size,
    get_free_tier_status,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

DEFAULT_PREFERENCES: dict[str, Any] = {
    "language": "en",
    "timezone": "UTC",
    "theme": "dark",
    "email_notifications": True,
    "push_notifications": False,
}

_AVATAR_PATTERN = re.compile(
    r"^data:image/(?:png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=]+)$"
)
_MAX_AVATAR_BYTES = 2 * 1024 * 1024


class SettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    avatar: str | None = Field(default=None, max_length=3_000_000)
    language: str | None = Field(default=None, min_length=2, max_length=20)
    timezone: str | None = Field(default=None, min_length=2, max_length=80)
    theme: Literal["dark", "light", "system"] | None = None
    email_notifications: bool | None = None
    push_notifications: bool | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(
        min_length=settings.PASSWORD_MIN_LENGTH,
        max_length=256,
    )


async def _preference_record(session: AsyncSession, user_id: str) -> OwnerControlRecord:
    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == "user-settings",
            OwnerControlRecord.resource_id == user_id,
        )
    )
    if record is None:
        await session.execute(
            pg_insert(OwnerControlRecord)
            .values(
                id=uuid_str(),
                domain="user-settings",
                resource_id=user_id,
                status="active",
                enabled=True,
                payload=DEFAULT_PREFERENCES,
                version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        )
        record = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == "user-settings",
                OwnerControlRecord.resource_id == user_id,
            )
        )
        if record is None:
            raise HTTPException(
                status_code=503,
                detail="Account preferences could not be initialized",
            )
    return record


def _validated_avatar(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    match = _AVATAR_PATTERN.fullmatch(normalized)
    if match is None:
        raise HTTPException(
            status_code=422,
            detail="Profile image must be an uploaded PNG, JPEG, WebP, or GIF",
        )
    try:
        decoded = base64.b64decode(match.group(1), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Profile image is invalid") from exc
    if not decoded or len(decoded) > _MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Profile image must be no larger than 2 MB",
        )
    return normalized


async def _serialize_settings(
    session: AsyncSession, actor: UserRecord
) -> dict[str, Any]:
    record = await _preference_record(session, actor.id)
    user = await session.get(User, actor.id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")
    sessions = (
        await session.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == actor.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    ).all()
    return {
        "profile": {
            "id": actor.id,
            "name": actor.name,
            "email": actor.email,
            "role": actor.role,
            "organization": actor.organization_name,
            "avatar": user.avatar,
        },
        "preferences": record.payload,
        "security": {
            "mfa_policy_enabled": settings.MFA_ENABLED,
            "active_sessions": len(sessions),
            "password_min_length": settings.PASSWORD_MIN_LENGTH,
        },
        "free_tier": (
            await get_free_tier_status(session, actor)
            if actor.role == FREE_USER_ROLE_NAME
            else None
        ),
    }


@router.get("")
async def get_settings(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await _serialize_settings(session, actor)
    await session.commit()
    return result


@router.patch("")
async def update_settings(
    data: SettingsUpdate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await session.get(User, actor.id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")
    updates = data.model_dump(exclude_none=True)
    if actor.role == FREE_USER_ROLE_NAME:
        disallowed = set(updates) - {"avatar"}
        if disallowed:
            raise HTTPException(
                status_code=403,
                detail="Free users may only change their profile image or password",
            )
    if "name" in updates:
        user.name = str(updates.pop("name")).strip()
        actor.name = user.name
    if "avatar" in updates:
        next_avatar = _validated_avatar(str(updates.pop("avatar")))
        if actor.role == FREE_USER_ROLE_NAME:
            await adjust_storage_usage(
                session,
                actor,
                avatar_data_size(next_avatar) - avatar_data_size(user.avatar),
            )
        user.avatar = next_avatar
    record = await _preference_record(session, actor.id)
    if updates:
        record.payload = {**record.payload, **updates}
        record.version += 1
    await session.commit()
    return await _serialize_settings(session, actor)


@router.post("/password")
async def change_password(
    data: PasswordChange,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user = await session.get(User, actor.id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")
    if not pwd_context.verify(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if pwd_context.verify(data.new_password, user.password_hash):
        raise HTTPException(
            status_code=409,
            detail="New password must differ from the current password",
        )
    user.password_hash = pwd_context.hash(data.new_password)
    user.auth_version += 1
    sessions = (
        await session.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == actor.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    ).all()
    now = datetime.now(UTC)
    for item in sessions:
        item.revoked_at = now
    await session.commit()
    return {
        "message": (
            "Password changed successfully; active refresh sessions were revoked"
        )
    }


@router.delete("/sessions")
async def revoke_sessions(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    sessions = (
        await session.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == actor.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    ).all()
    now = datetime.now(UTC)
    for item in sessions:
        item.revoked_at = now
    await session.commit()
    return {"revoked": len(sessions)}
