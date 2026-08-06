"""Tenant-scoped durable notification center and delivery receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.core.auth import UserRecord, current_user, require_permissions
from app.db.base import get_db
from app.db.models import Notification, NotificationDelivery, User
from app.services import communications
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class NotificationCreate(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=160)
    event_key: str = Field(default="notification.manual", min_length=2, max_length=160)
    category: str = Field(default="system", min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    message: str = Field(min_length=1, max_length=10000)
    severity: Literal["info", "success", "warning", "critical"] = "info"
    user_id: str | None = None
    channels: list[Literal["in_app", "email", "push", "telegram", "whatsapp"]] | None = None
    source_type: str | None = Field(default=None, max_length=80)
    source_id: str | None = Field(default=None, max_length=160)
    correlation_id: str | None = Field(default=None, max_length=160)
    dedupe_key: str | None = Field(default=None, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class NotificationUpdate(BaseModel):
    read: bool | None = None
    archived: bool | None = None


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    archived: bool = Query(False),
    category: str | None = Query(default=None, max_length=80),
    severity: str | None = Query(default=None, max_length=32),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("notifications:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Notification).where(
        Notification.organization_id == actor.organization_id,
        Notification.recipient_id == actor.id,
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    statement = statement.where(
        Notification.archived_at.is_not(None)
        if archived
        else Notification.archived_at.is_(None)
    )
    if category:
        statement = statement.where(Notification.category == category.strip().lower())
    if severity:
        statement = statement.where(Notification.severity == severity.strip().lower())
    rows = list(
        (
            await session.scalars(
                statement.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
            )
        ).all()
    )
    ids = [row.id for row in rows]
    delivery_rows = (
        list(
            (
                await session.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id.in_(ids)
                    )
                )
            ).all()
        )
        if ids
        else []
    )
    deliveries: dict[str, list[dict[str, Any]]] = {}
    for delivery in delivery_rows:
        deliveries.setdefault(delivery.notification_id, []).append(
            communications.delivery_snapshot(delivery)
        )
    return [
        {
            **communications.notification_snapshot(row),
            "deliveries": deliveries.get(row.id, []),
        }
        for row in rows
    ]


@router.post("", status_code=201)
async def create_notification(
    data: NotificationCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    recipient_id = data.user_id or actor.id
    if (
        recipient_id != actor.id
        and "*" not in actor.permissions
        and "notifications:write" not in actor.permissions
    ):
        raise HTTPException(
            status_code=403,
            detail="Notification delivery to another user requires notification write permission",
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
    try:
        notification = await communications.create_notification(
            session,
            recipient,
            event_key=(data.type or data.event_key).strip(),
            category=data.category,
            title=data.title,
            message=data.message,
            severity=data.severity,
            audience="user",
            channels=data.channels,
            source_type=data.source_type,
            source_id=data.source_id,
            correlation_id=data.correlation_id,
            dedupe_key=data.dedupe_key,
            payload=data.payload,
            actor_id=actor.id,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    delivery_rows = list(
        (
            await session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.notification_id == notification.id)
                .order_by(NotificationDelivery.channel)
            )
        ).all()
    )
    await communications.publish_realtime(notification)
    return {
        **communications.notification_snapshot(notification),
        "deliveries": [
            communications.delivery_snapshot(row) for row in delivery_rows
        ],
    }


@router.get("/{notification_id}")
async def get_notification(
    notification_id: str,
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
    delivery_rows = list(
        (
            await session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.notification_id == notification.id)
                .order_by(NotificationDelivery.channel)
            )
        ).all()
    )
    return {
        **communications.notification_snapshot(notification),
        "deliveries": [communications.delivery_snapshot(row) for row in delivery_rows],
    }


@router.patch("/{notification_id}")
async def update_notification(
    notification_id: str,
    data: NotificationUpdate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    notification = await session.scalar(
        select(Notification)
        .where(
            Notification.id == notification_id,
            Notification.organization_id == actor.organization_id,
            Notification.recipient_id == actor.id,
        )
        .with_for_update()
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    current = datetime.now(UTC)
    if data.read is not None:
        notification.read_at = current if data.read else None
    if data.archived is not None:
        notification.archived_at = current if data.archived else None
    await session.commit()
    return communications.notification_snapshot(notification)


@router.post("/mark-all-read")
async def mark_all_read(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = list(
        (
            await session.scalars(
                select(Notification).where(
                    Notification.organization_id == actor.organization_id,
                    Notification.recipient_id == actor.id,
                    Notification.read_at.is_(None),
                    Notification.archived_at.is_(None),
                )
            )
        ).all()
    )
    read_at = datetime.now(UTC)
    for row in rows:
        row.read_at = read_at
    await session.commit()
    return {"updated": len(rows)}


@router.get("/{notification_id}/deliveries")
async def list_notification_deliveries(
    notification_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    notification = await session.scalar(
        select(Notification.id).where(
            Notification.id == notification_id,
            Notification.organization_id == actor.organization_id,
            Notification.recipient_id == actor.id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    rows = list(
        (
            await session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.notification_id == notification_id)
                .order_by(NotificationDelivery.channel)
            )
        ).all()
    )
    return [communications.delivery_snapshot(row) for row in rows]


@router.post("/deliveries/{delivery_id}/acknowledge")
async def acknowledge_delivery(
    delivery_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    delivery = await session.scalar(
        select(NotificationDelivery)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(
            NotificationDelivery.id == delivery_id,
            Notification.organization_id == actor.organization_id,
            Notification.recipient_id == actor.id,
        )
        .with_for_update()
    )
    if delivery is None:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    try:
        await communications.acknowledge_delivery(
            session, delivery, actor_id=actor.id
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return communications.delivery_snapshot(delivery)


@router.post("/deliveries/{delivery_id}/retry")
async def retry_delivery(
    delivery_id: str,
    actor: UserRecord = Depends(require_permissions("notifications:write")),
    session: AsyncSession = Depends(get_db),
):
    delivery = await session.scalar(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.id == delivery_id,
            NotificationDelivery.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if delivery is None:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    try:
        await communications.retry_delivery(session, delivery, actor_id=actor.id)
        await session.commit()
    except communications.ProviderNotConfigured as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Delivery provider is not configured") from exc
    except (communications.PermanentDeliveryError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return communications.delivery_snapshot(delivery)
