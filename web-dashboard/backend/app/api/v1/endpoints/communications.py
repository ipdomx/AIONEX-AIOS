"""Authenticated communication endpoints, preferences, and delivery history."""

from __future__ import annotations

from typing import Literal

from app.core.auth import UserRecord, current_user, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent, CommunicationEndpoint, Notification, NotificationDelivery
from app.services import communications
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class EndpointCreate(BaseModel):
    channel: Literal["email", "push", "telegram", "whatsapp"]
    address: str = Field(min_length=1, max_length=2048)
    label: str = Field(default="Primary", min_length=1, max_length=120)


class PreferenceUpdate(BaseModel):
    category: str = Field(default="*", min_length=1, max_length=80)
    enabled: bool = True
    channels: list[Literal["in_app", "email", "push", "telegram", "whatsapp"]]
    minimum_severity: Literal["info", "success", "warning", "critical"] = "info"
    quiet_hours_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_hours_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    digest_mode: Literal["immediate", "hourly", "daily"] = "immediate"


@router.get("/channels")
async def channels(
    _actor: UserRecord = Depends(current_user),
):
    return communications.channel_readiness()


@router.get("/endpoints")
async def endpoints(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = await communications.list_endpoints(session, actor)
    return [communications.endpoint_snapshot(row) for row in rows]


@router.post("/endpoints", status_code=status.HTTP_201_CREATED)
async def register_endpoint(
    data: EndpointCreate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        endpoint = await communications.register_endpoint(
            session,
            actor,
            channel=data.channel,
            address=data.address,
            label=data.label,
            # Telegram and WhatsApp require owner/provider verification before use.
            verified=data.channel in {"email", "push"},
        )
        await session.commit()
        await session.refresh(endpoint)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return communications.endpoint_snapshot(endpoint)


@router.delete("/endpoints/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        endpoint = await communications.delete_endpoint(session, actor, endpoint_id)
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return communications.endpoint_snapshot(endpoint)


@router.get("/preferences")
async def preferences(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = await communications.get_preferences(session, actor)
    await session.commit()
    return [communications.preference_snapshot(row) for row in rows]


@router.put("/preferences")
async def update_preferences(
    data: PreferenceUpdate,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        preference = await communications.update_preference(
            session,
            actor,
            category=data.category,
            enabled=data.enabled,
            channels=data.channels,
            minimum_severity=data.minimum_severity,
            quiet_hours_start=data.quiet_hours_start,
            quiet_hours_end=data.quiet_hours_end,
            timezone=data.timezone,
            digest_mode=data.digest_mode,
        )
        await session.commit()
        await session.refresh(preference)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return communications.preference_snapshot(preference)


@router.get("/deliveries")
async def delivery_history(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    channel: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    statement = (
        select(NotificationDelivery)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(
            Notification.organization_id == actor.organization_id,
            Notification.recipient_id == actor.id,
        )
    )
    if status_filter:
        statement = statement.where(NotificationDelivery.status == status_filter)
    if channel:
        statement = statement.where(NotificationDelivery.channel == channel)
    rows = list(
        (
            await session.scalars(
                statement.order_by(NotificationDelivery.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [communications.delivery_snapshot(row) for row in rows]


@router.get("/owner/overview")
async def owner_overview(
    _actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    # The private channel still enforces Super Owner before this router is reached;
    # the explicit permission keeps this contract safe in direct ASGI tests too.
    return await communications.delivery_statistics(session)


@router.get("/owner/deliveries")
async def owner_deliveries(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    channel: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    _actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    statement = select(NotificationDelivery)
    if status_filter:
        statement = statement.where(NotificationDelivery.status == status_filter)
    if channel:
        statement = statement.where(NotificationDelivery.channel == channel)
    rows = list(
        (
            await session.scalars(
                statement.order_by(NotificationDelivery.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [communications.delivery_snapshot(row) for row in rows]


@router.post("/owner/endpoints/{endpoint_id}/verify")
async def owner_verify_endpoint(
    endpoint_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    endpoint = await session.scalar(
        select(CommunicationEndpoint)
        .where(
            CommunicationEndpoint.id == endpoint_id,
            CommunicationEndpoint.organization_id == actor.organization_id,
            CommunicationEndpoint.status == "active",
        )
        .with_for_update()
    )
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Communication endpoint not found")
    endpoint.verified_at = communications.now()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="communication.endpoint.verified",
            resource_type="communication_endpoint",
            resource_id=endpoint.id,
            details={"channel": endpoint.channel},
        )
    )
    await session.commit()
    return communications.endpoint_snapshot(endpoint)
