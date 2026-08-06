"""Durable tenant incidents, acknowledgement, escalation, and resolution."""

from __future__ import annotations

from typing import Any, Literal

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import Alert
from app.services import communications
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class IncidentCreate(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    description: str = Field(min_length=2, max_length=20000)
    severity: Literal["info", "warning", "critical"] = "warning"
    source: str = Field(default="manual", min_length=2, max_length=120)
    details: dict[str, Any] = Field(default_factory=dict)


async def _incident(
    session: AsyncSession, actor: UserRecord, incident_id: str
) -> Alert:
    item = await session.scalar(
        select(Alert).where(
            Alert.id == incident_id,
            Alert.organization_id == actor.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return item


@router.get("")
async def list_incidents(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    severity: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("incidents:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Alert).where(Alert.organization_id == actor.organization_id)
    if status_filter:
        statement = statement.where(Alert.status == status_filter)
    if severity:
        statement = statement.where(Alert.severity == severity)
    rows = list(
        (
            await session.scalars(
                statement.order_by(Alert.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [communications.incident_snapshot(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_incident(
    data: IncidentCreate,
    actor: UserRecord = Depends(require_permissions("incidents:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item, notifications = await communications.create_incident(
            session,
            organization_id=actor.organization_id,
            title=data.title,
            description=data.description,
            severity=data.severity,
            source=data.source,
            actor_id=actor.id,
            details=data.details,
        )
        await session.commit()
        await session.refresh(item)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return communications.incident_snapshot(item)


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    actor: UserRecord = Depends(require_permissions("incidents:read")),
    session: AsyncSession = Depends(get_db),
):
    return communications.incident_snapshot(await _incident(session, actor, incident_id))


@router.post("/{incident_id}/acknowledge")
async def acknowledge_incident(
    incident_id: str,
    actor: UserRecord = Depends(require_permissions("incidents:write")),
    session: AsyncSession = Depends(get_db),
):
    item = await _incident(session, actor, incident_id)
    try:
        await communications.acknowledge_incident(session, actor, item)
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return communications.incident_snapshot(item)


@router.post("/{incident_id}/escalate")
async def escalate_incident(
    incident_id: str,
    actor: UserRecord = Depends(require_permissions("incidents:write")),
    session: AsyncSession = Depends(get_db),
):
    item = await _incident(session, actor, incident_id)
    try:
        item, notifications = await communications.escalate_incident(
            session, actor, item
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return communications.incident_snapshot(item)


@router.post("/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    actor: UserRecord = Depends(require_permissions("incidents:write")),
    session: AsyncSession = Depends(get_db),
):
    item = await _incident(session, actor, incident_id)
    await communications.resolve_incident(session, actor, item)
    await session.commit()
    return communications.incident_snapshot(item)
