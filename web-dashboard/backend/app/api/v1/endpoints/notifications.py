"""Authenticated notification center backed by the relational database."""

from datetime import UTC, datetime
from typing import Any

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user, require_permissions
from app.db.base import get_db
from app.db.models import Notification, User
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "organization_id": notification.organization_id,
        "user_id": notification.recipient_id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "severity": notification.severity,
        "read": notification.read_at is not None,
        "created_at": _iso(notification.created_at),
        "updated_at": _iso(notification.updated_at),
    }


class NotificationCreate(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    message: str = Field(min_length=1)
    severity: str = Field(default="info", min_length=1, max_length=32)
    user_id: str | None = None


class NotificationUpdate(BaseModel):
    read: bool = True


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    actor: UserRecord = Depends(require_permissions("notifications:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Notification).where(
        Notification.organization_id == actor.organization_id,
        Notification.recipient_id == actor.id,
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    rows = (
        await session.scalars(statement.order_by(Notification.created_at.desc()))
    ).all()
    return [_serialize(row) for row in rows]


@router.post("", status_code=201)
async def create_notification(
    data: NotificationCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    recipient_id = data.user_id or actor.id
    if recipient_id != actor.id and "*" not in actor.permissions:
        raise HTTPException(
            status_code=403,
            detail="Only platform operators can notify another user",
        )
    recipient = await session.scalar(
        select(User).where(
            User.id == recipient_id,
            User.organization_id == actor.organization_id,
            User.deleted_at.is_(None),
        )
    )
    if recipient is None:
        raise HTTPException(status_code=404, detail="Notification recipient not found")
    notification = Notification(
        organization_id=actor.organization_id,
        recipient_id=recipient.id,
        type=data.type.strip(),
        title=data.title.strip(),
        message=data.message.strip(),
        severity=data.severity.strip(),
        payload={},
    )
    session.add(notification)
    await session.commit()
    item = _serialize(notification)
    await ai_runtime.hub.publish(
        actor.organization_id,
        {"type": "notification.created", "notification": item},
    )
    return item


@router.patch("/{notification_id}")
async def update_notification(
    notification_id: str,
    data: NotificationUpdate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    notification = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.organization_id == actor.organization_id,
            Notification.recipient_id == actor.id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = datetime.now(UTC) if data.read else None
    await session.commit()
    return _serialize(notification)


@router.post("/mark-all-read")
async def mark_all_read(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = (
        await session.scalars(
            select(Notification).where(
                Notification.organization_id == actor.organization_id,
                Notification.recipient_id == actor.id,
                Notification.read_at.is_(None),
            )
        )
    ).all()
    read_at = datetime.now(UTC)
    for row in rows:
        row.read_at = read_at
    await session.commit()
    return {"updated": len(rows)}
