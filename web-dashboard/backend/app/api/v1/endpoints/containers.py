"""Truthful production component inventory and fail-closed runtime controls."""

from __future__ import annotations

from typing import Any

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services import operations_assurance
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def _items(session: AsyncSession) -> list[dict[str, Any]]:
    return await operations_assurance.service_inventory(session)


@router.get("")
async def list_containers(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
    server_id: str | None = None,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    rows = await _items(session)
    if status:
        rows = [item for item in rows if item["status"] == status]
    if server_id:
        rows = [item for item in rows if item["server"] == server_id]
    return rows[skip : skip + limit]


@router.get("/{container_id}")
async def get_container(
    container_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    item = next((row for row in await _items(session) if row["id"] == container_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Runtime component not found")
    return item


async def _blocked_control(
    *,
    container_id: str,
    action: str,
    actor: UserRecord,
    session: AsyncSession,
) -> None:
    item = next((row for row in await _items(session) if row["id"] == container_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Runtime component not found")
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="runtime.control.denied",
            resource_type="runtime_component",
            resource_id=container_id,
            details={
                "requested_action": action,
                "status": "blocked",
                "reason": item["control_reason"],
            },
        )
    )
    await session.commit()
    raise HTTPException(
        status_code=409,
        detail={
            "code": "DIRECT_RUNTIME_CONTROL_NOT_DELEGATED",
            "message": item["control_reason"],
            "component": container_id,
            "requested_action": action,
        },
    )


@router.post("/{container_id}/start")
async def start_container(
    container_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    await _blocked_control(container_id=container_id, action="start", actor=actor, session=session)


@router.post("/{container_id}/stop")
async def stop_container(
    container_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    await _blocked_control(container_id=container_id, action="stop", actor=actor, session=session)


@router.post("/{container_id}/restart")
async def restart_container(
    container_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    await _blocked_control(container_id=container_id, action="restart", actor=actor, session=session)


@router.get("/{container_id}/logs")
async def get_container_logs(
    container_id: str,
    tail: int = Query(100, ge=1, le=500),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if next((row for row in await _items(session) if row["id"] == container_id), None) is None:
        raise HTTPException(status_code=404, detail="Runtime component not found")
    rows = list(
        (
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.action.in_({"monitoring.log", "operations.observation"}),
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(tail)
            )
        ).all()
    )
    visible = []
    for row in rows:
        details = row.details or {}
        service = str(details.get("service", "runtime"))
        if container_id not in {service, "backend", "runtime-node"} and service != container_id:
            continue
        visible.append(
            {
                "id": row.id,
                "timestamp": operations_assurance.iso(row.created_at),
                "level": details.get("level", "info"),
                "service": service,
                "message": details.get("message", row.action),
                "trace_id": details.get("trace_id"),
            }
        )
    return {"component_id": container_id, "logs": visible[:tail], "source": "durable-audit-ledger"}
