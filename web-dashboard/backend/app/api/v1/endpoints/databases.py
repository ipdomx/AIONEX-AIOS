"""Live PostgreSQL/Redis inventory and governed database operations."""

from __future__ import annotations

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent, BackupRecord
from app.services import operations_assurance
from app.services.backup_executor import acquire_enqueue_lock
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def _rows(session: AsyncSession) -> list[dict]:
    return [await operations_assurance.database_snapshot(session), await operations_assurance.redis_snapshot()]


@router.get("")
async def list_databases(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    type: str | None = None,
    status: str | None = None,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    rows = await _rows(session)
    if type:
        rows = [row for row in rows if row["type"] == type]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return rows[skip : skip + limit]


@router.get("/{db_id}")
async def get_database(
    db_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    row = next((item for item in await _rows(session) if item["id"] == db_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Database not found")
    return row


@router.post("/{db_id}/backup", status_code=202)
async def backup_database(
    db_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if db_id != "postgres-primary":
        raise HTTPException(status_code=409, detail="Only the governed PostgreSQL data store supports application backup")
    await acquire_enqueue_lock(session, "backup:platform")
    active = await session.scalar(
        select(BackupRecord.id)
        .where(
            BackupRecord.scope == "platform",
            BackupRecord.status.in_({"pending", "running"}),
        )
        .limit(1)
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="A platform backup is already queued or running")
    record = BackupRecord(kind="database", scope="platform", status="pending")
    session.add(record)
    await session.flush()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="database.backup.requested",
            resource_type="backup",
            resource_id=record.id,
            details={"database_id": db_id, "scope": "platform"},
        )
    )
    await session.commit()
    return {"backup_id": record.id, "database_id": db_id, "status": record.status}


@router.get("/{db_id}/queries")
async def get_slow_queries(
    db_id: str,
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    if db_id == "redis-primary":
        return {"database_id": db_id, "supported": False, "reason": "Redis query text is intentionally not collected", "queries": []}
    if db_id != "postgres-primary":
        raise HTTPException(status_code=404, detail="Database not found")
    if session.get_bind().dialect.name != "postgresql":
        return {"database_id": db_id, "supported": False, "reason": "PostgreSQL runtime statistics unavailable", "queries": []}
    rows = (
        await session.execute(
            text(
                "SELECT pid, state, wait_event_type, wait_event, "
                "EXTRACT(EPOCH FROM (clock_timestamp()-query_start))*1000 AS duration_ms "
                "FROM pg_stat_activity "
                "WHERE datname=current_database() AND pid<>pg_backend_pid() AND query_start IS NOT NULL "
                "ORDER BY duration_ms DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return {
        "database_id": db_id,
        "supported": True,
        "query_text_collected": False,
        "queries": [
            {
                "pid": int(row["pid"]),
                "state": row["state"],
                "wait_event_type": row["wait_event_type"],
                "wait_event": row["wait_event"],
                "duration_ms": round(float(row["duration_ms"] or 0.0), 2),
            }
            for row in rows
        ],
    }
