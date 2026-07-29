"""Durable PostgreSQL backup and disaster-recovery execution endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent, BackupRecord, DisasterRecoveryRun
from app.services.backup_executor import acquire_enqueue_lock
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _artifact_ready(record: BackupRecord) -> bool:
    return bool(
        record.status == "completed"
        and record.location
        and record.checksum
        and record.size_bytes
        and record.size_bytes > 0
    )


def _serialize_backup(record: BackupRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.kind,
        "kind": record.kind,
        "scope": record.scope,
        "status": record.status,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "completed_at": _iso(record.completed_at),
        "checksum": record.checksum,
        "size_bytes": record.size_bytes or 0,
        "artifact_ready": _artifact_ready(record),
    }


def _serialize_run(record: DisasterRecoveryRun) -> dict[str, Any]:
    return {
        "id": record.id,
        "operation": record.operation,
        "status": record.status,
        "region": record.region,
        "details": record.details or {},
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "completed_at": _iso(record.completed_at),
    }


def _audit(
    actor: UserRecord,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    )


async def _dr_status(session: AsyncSession) -> dict[str, Any]:
    runs = (
        await session.scalars(
            select(DisasterRecoveryRun)
            .order_by(DisasterRecoveryRun.created_at.desc())
            .limit(100)
        )
    ).all()
    completed_mode_run = next(
        (
            run
            for run in runs
            if run.status == "completed" and run.operation in {"failover", "failback"}
        ),
        None,
    )
    completed_test = next(
        (run for run in runs if run.status == "completed" and run.operation == "test"),
        None,
    )
    requested_test = next((run for run in runs if run.operation == "test"), None)
    latest = runs[0] if runs else None
    mode = (
        "failover"
        if completed_mode_run is not None and completed_mode_run.operation == "failover"
        else "standby"
    )
    return {
        "mode": mode,
        "last_test_at": (
            _iso(completed_test.completed_at or completed_test.updated_at)
            if completed_test is not None
            else None
        ),
        "last_test_requested_at": (
            _iso(requested_test.created_at) if requested_test is not None else None
        ),
        "rpo_minutes": 15,
        "rto_minutes": 60,
        "latest_run": _serialize_run(latest) if latest is not None else None,
    }


@router.get("")
async def list_backups(
    scope: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    statement = select(BackupRecord)
    if scope:
        statement = statement.where(BackupRecord.scope == scope)
    if status:
        statement = statement.where(BackupRecord.status == status)
    rows = (
        await session.scalars(
            statement.order_by(BackupRecord.created_at.desc()).limit(limit)
        )
    ).all()
    return [_serialize_backup(row) for row in rows]


@router.post("", status_code=202)
async def create_backup(
    name: str,
    scope: str = "platform",
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    kind = name.strip()
    normalized_scope = scope.strip()
    if (
        not kind
        or not normalized_scope
        or len(kind) > 80
        or len(normalized_scope) > 160
    ):
        raise HTTPException(
            status_code=422,
            detail="Backup name or scope is empty or exceeds its supported length",
        )
    await acquire_enqueue_lock(session, f"backup:{normalized_scope}")
    active = await session.scalar(
        select(BackupRecord.id)
        .where(
            BackupRecord.scope == normalized_scope,
            BackupRecord.status.in_({"pending", "running"}),
        )
        .limit(1)
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="A backup is already queued or running for this scope",
        )
    record = BackupRecord(
        kind=kind,
        scope=normalized_scope,
        status="pending",
    )
    session.add(record)
    await session.flush()
    session.add(
        _audit(
            actor,
            "backup.requested",
            "backup",
            record.id,
            {"kind": record.kind, "scope": record.scope},
        )
    )
    await session.commit()
    return _serialize_backup(record)


async def _enqueue_restore_validation(
    *,
    backup_id: str | None,
    operation: str,
    actor: UserRecord,
    session: AsyncSession,
    region: str | None = None,
) -> tuple[BackupRecord, DisasterRecoveryRun]:
    # Retention uses the same transaction-scoped advisory lock before it locks a
    # BackupRecord row. Keep that order here as well, then re-read the durable
    # record under the lock so an artifact cannot be expired between selection
    # and enqueue.
    await acquire_enqueue_lock(session, "restore-validation")

    if backup_id is None:
        backup_statement = (
            select(BackupRecord)
            .where(
                BackupRecord.status == "completed",
                BackupRecord.completed_at.is_not(None),
                BackupRecord.location.is_not(None),
                BackupRecord.checksum.is_not(None),
                BackupRecord.size_bytes.is_not(None),
                BackupRecord.size_bytes > 0,
            )
            .order_by(BackupRecord.completed_at.desc())
            .limit(1)
        )
    else:
        backup_statement = select(BackupRecord).where(BackupRecord.id == backup_id)

    backup = await session.scalar(backup_statement.with_for_update())
    if backup is None:
        if backup_id is not None:
            raise HTTPException(status_code=404, detail="Backup not found")
        raise HTTPException(
            status_code=409,
            detail="A completed backup is required for a disaster-recovery drill",
        )
    if not _artifact_ready(backup):
        raise HTTPException(
            status_code=409,
            detail="Only a completed backup with a protected artifact can be validated",
        )

    active = await session.scalar(
        select(DisasterRecoveryRun.id)
        .where(
            DisasterRecoveryRun.status.in_({"pending", "running"}),
            DisasterRecoveryRun.operation.in_({"restore_validation", "test"}),
        )
        .limit(1)
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "A restore validation or disaster-recovery drill is already "
                "queued or running"
            ),
        )
    run = DisasterRecoveryRun(
        operation=operation,
        status="pending",
        region=region,
        details={
            "backup_id": backup.id,
            "dry_run": True,
            "requested_by": actor.id,
        },
    )
    session.add(run)
    await session.flush()
    session.add(
        _audit(
            actor,
            f"dr.{operation}.requested",
            "disaster_recovery_run",
            run.id,
            {"backup_id": backup.id},
        )
    )
    await session.commit()
    return backup, run


@router.post("/{backup_id}/restore", status_code=202)
async def restore_backup(
    backup_id: str,
    dry_run: bool = True,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if not dry_run:
        raise HTTPException(
            status_code=409,
            detail=(
                "Live in-place restore is intentionally unavailable from the API; "
                "validate the artifact first, then use the controlled restore.sh "
                "--owner-backup-id runbook"
            ),
        )
    backup, run = await _enqueue_restore_validation(
        backup_id=backup_id,
        operation="restore_validation",
        actor=actor,
        session=session,
    )
    return {
        "backup_id": backup.id,
        "run_id": run.id,
        "status": run.status,
        "dry_run": True,
        "timestamp": _iso(run.created_at),
    }


@router.get("/dr/status")
async def disaster_recovery_status(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await _dr_status(session)


@router.post("/dr/test", status_code=202)
async def test_disaster_recovery(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    _, run = await _enqueue_restore_validation(
        backup_id=None,
        operation="test",
        actor=actor,
        session=session,
    )
    return {
        "status": run.status,
        "run": _serialize_run(run),
        **(await _dr_status(session)),
    }


@router.post("/dr/failover")
async def failover(
    confirm: bool = False,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if not confirm:
        raise HTTPException(status_code=409, detail="Explicit confirmation is required")
    raise HTTPException(
        status_code=501,
        detail="Automated infrastructure failover is not configured",
    )


@router.post("/dr/failback")
async def failback(
    confirm: bool = False,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if not confirm:
        raise HTTPException(status_code=409, detail="Explicit confirmation is required")
    raise HTTPException(
        status_code=501,
        detail="Automated infrastructure failback is not configured",
    )
