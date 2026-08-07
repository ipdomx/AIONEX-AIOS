"""Live server inventory with governed maintenance and fail-closed host controls."""

from __future__ import annotations

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent
from app.services import operations_assurance
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _node() -> dict:
    return operations_assurance.host_snapshot()


@router.get("")
async def list_servers(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
    search: str | None = None,
    actor: UserRecord = Depends(require_super_owner),
):
    del actor
    rows = [_node()]
    if status:
        rows = [row for row in rows if row["status"] == status]
    if search:
        needle = search.lower()
        rows = [row for row in rows if needle in f"{row['name']} {row['hostname']} {row['os']}".lower()]
    return rows[skip : skip + limit]


@router.post("", status_code=409)
async def create_server(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="server.registration.denied",
            resource_type="server",
            resource_id="runtime-node",
            details={"status": "blocked", "reason": "Remote host enrollment is not delegated to the application plane."},
        )
    )
    await session.commit()
    raise HTTPException(
        status_code=409,
        detail="Remote host enrollment requires the separately governed distributed-runtime batch.",
    )


@router.get("/{server_id}")
async def get_server(server_id: str, actor: UserRecord = Depends(require_super_owner)):
    del actor
    node = _node()
    if server_id != node["id"]:
        raise HTTPException(status_code=404, detail="Server not found")
    return node


@router.delete("/{server_id}")
async def delete_server(
    server_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if server_id != _node()["id"]:
        raise HTTPException(status_code=404, detail="Server not found")
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="server.delete.denied",
            resource_type="server",
            resource_id=server_id,
            details={"status": "blocked", "reason": "The production node is protected from application-level deletion."},
        )
    )
    await session.commit()
    raise HTTPException(status_code=409, detail="The production node cannot be deleted through the application API")


@router.get("/{server_id}/metrics")
async def get_server_metrics(
    server_id: str,
    hours: int = Query(24, ge=1, le=168),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    if server_id != _node()["id"]:
        raise HTTPException(status_code=404, detail="Server not found")
    from app.db.models import MetricSample
    from datetime import timedelta
    from sqlalchemy import select

    cutoff = operations_assurance.now() - timedelta(hours=hours)
    samples = list(
        (
            await session.scalars(
                select(MetricSample)
                .where(
                    MetricSample.resource == "runtime-node",
                    MetricSample.timestamp >= cutoff,
                )
                .order_by(MetricSample.timestamp)
            )
        ).all()
    )
    grouped: dict[str, list[dict]] = {"cpu": [], "memory": [], "disk": []}
    mapping = {
        "runtime.cpu.percent": "cpu",
        "runtime.memory.percent": "memory",
        "runtime.disk.percent": "disk",
    }
    for sample in samples:
        key = mapping.get(sample.name)
        if key:
            grouped[key].append({"timestamp": operations_assurance.iso(sample.timestamp), "value": sample.value})
    return grouped


@router.post("/{server_id}/reboot")
async def reboot_server(
    server_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if server_id != _node()["id"]:
        raise HTTPException(status_code=404, detail="Server not found")
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="server.reboot.denied",
            resource_type="server",
            resource_id=server_id,
            details={"status": "blocked", "reason": "Host reboot is intentionally outside the application privilege boundary."},
        )
    )
    await session.commit()
    raise HTTPException(status_code=409, detail="Host reboot is not delegated to the application container")


@router.post("/{server_id}/maintenance")
async def toggle_maintenance(
    server_id: str,
    enable: bool = True,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if server_id != _node()["id"]:
        raise HTTPException(status_code=404, detail="Server not found")
    record = await operations_assurance.maintenance_record(session)
    record.enabled = bool(enable)
    record.status = "maintenance" if enable else "active"
    record.payload = {
        **(record.payload or {}),
        "maintenance": bool(enable),
        "changed_by": actor.id,
        "changed_at": operations_assurance.iso(),
    }
    record.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="server.maintenance.updated",
            resource_type="server",
            resource_id=server_id,
            details={"maintenance": bool(enable), "version": record.version},
        )
    )
    await session.commit()
    return {
        "server_id": server_id,
        "maintenance": bool(enable),
        "status": record.status,
        "version": record.version,
    }
