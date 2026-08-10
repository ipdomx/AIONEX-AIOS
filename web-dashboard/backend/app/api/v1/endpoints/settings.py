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
from app.db.models import OwnerControlRecord, PasskeyCredential, RefreshSession, User, uuid_str
from app.services.account_security import mfa_status
from app.services.free_tier import (
    FREE_USER_ROLE_NAME,
    adjust_storage_usage,
    avatar_data_size,
    get_free_tier_status,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
    passkey_count = await session.scalar(
        select(func.count(PasskeyCredential.id)).where(
            PasskeyCredential.user_id == actor.id
        )
    )
    mfa = await mfa_status(session, actor.id)
    backup_codes_value = mfa.get("backup_codes_remaining", 0)
    backup_codes_remaining = (
        int(backup_codes_value)
        if isinstance(backup_codes_value, (str, int)) and not isinstance(backup_codes_value, bool)
        else 0
    )
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
            "mfa_enabled": bool(mfa["enabled"]),
            "mfa_backup_codes_remaining": backup_codes_remaining,
            "passkey_count": int(passkey_count or 0),
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


@router.get("/sessions")
async def list_sessions(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(RefreshSession)
                .where(RefreshSession.user_id == actor.id)
                .order_by(RefreshSession.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return [
        {
            "id": item.id,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
            "expires_at": item.expires_at.isoformat(),
            "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
            "active": item.revoked_at is None and item.expires_at > datetime.now(UTC),
            "ip_address": item.ip_address,
            "user_agent": item.user_agent,
        }
        for item in rows
    ]


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    record = await session.scalar(
        select(RefreshSession)
        .where(
            RefreshSession.id == session_id,
            RefreshSession.user_id == actor.id,
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        await session.commit()
    return {"revoked": True}


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
