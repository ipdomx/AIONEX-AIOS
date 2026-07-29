"""Authenticated, database-backed account and preference settings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.core.auth import UserRecord, current_user, pwd_context
from app.core.config import settings
from app.db.base import get_db
from app.db.models import OwnerControlRecord, RefreshSession, User, uuid_str
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


class SettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
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


async def _serialize_settings(
    session: AsyncSession, actor: UserRecord
) -> dict[str, Any]:
    record = await _preference_record(session, actor.id)
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
        },
        "preferences": record.payload,
        "security": {
            "mfa_policy_enabled": settings.MFA_ENABLED,
            "active_sessions": len(sessions),
            "password_min_length": settings.PASSWORD_MIN_LENGTH,
        },
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
    if "name" in updates:
        user.name = str(updates.pop("name")).strip()
        actor.name = user.name
    record = await _preference_record(session, actor.id)
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
