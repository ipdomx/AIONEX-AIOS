"""Enterprise operations integration backed by live health and recovery data."""

from datetime import UTC, datetime
from typing import Any, Literal

from app.api.owner.control_plane import (
    _backup_artifact_ready,
    _health_items,
    _run_audited_mutation,
)
from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import BackupRecord, DisasterRecoveryRun
from app.services.backup_executor import acquire_enqueue_lock
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(
    prefix="/owner/operations-integration",
    tags=["owner-operations-integration"],
)


class OperationsTarget(BaseModel):
    id: str
    name: str
    category: str
    status: Literal["healthy", "degraded", "offline"]
    readiness: int
    details: str
    last_checked_at: str


class OperationsSnapshot(BaseModel):
    generated_at: str
    completion: int
    targets: list[OperationsTarget]


class OperationsCommand(BaseModel):
    action: Literal["validate", "recover"]


async def _snapshot(session: AsyncSession) -> OperationsSnapshot:
    health = await _health_items(session)
    latest_backup = await session.scalar(
        select(BackupRecord)
        .where(
            BackupRecord.status == "completed",
            BackupRecord.location.is_not(None),
            BackupRecord.checksum.is_not(None),
            BackupRecord.size_bytes.is_not(None),
            BackupRecord.size_bytes > 0,
        )
        .order_by(BackupRecord.completed_at.desc())
        .limit(1)
    )
    backup_ready = await _backup_artifact_ready(
        latest_backup,
        verify_checksum=False,
    )
    now = datetime.now(UTC).isoformat()
    targets = [
        OperationsTarget(
            id=item["id"],
            name=item["name"],
            category="operations",
            status=(
                "healthy"
                if item["status"] == "healthy"
                else (
                    "degraded"
                    if item["status"] in {"degraded", "warning"}
                    else "offline"
                )
            ),
            readiness=(
                100
                if item["status"] == "healthy"
                else 60 if item["status"] in {"degraded", "warning"} else 0
            ),
            details=item["detail"],
            last_checked_at=now,
        )
        for item in health
    ]
    targets.append(
        OperationsTarget(
            id="backup",
            name="Backup & Restore",
            category="resilience",
            status="healthy" if backup_ready else "degraded",
            readiness=100 if backup_ready else 50,
            details=(
                "The latest completed backup artifact is available."
                if backup_ready
                else (
                    "No completed backup artifact passed live storage " "verification."
                )
            ),
            last_checked_at=now,
        )
    )
    completion = round(sum(item.readiness for item in targets) / max(1, len(targets)))
    return OperationsSnapshot(
        generated_at=now,
        completion=completion,
        targets=targets,
    )


@router.get("", response_model=OperationsSnapshot)
async def get_operations_integration(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> OperationsSnapshot:
    return await _snapshot(session)


@router.post("/{target_id}/command", response_model=OperationsSnapshot)
async def run_operations_command(
    target_id: str,
    command: OperationsCommand,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> OperationsSnapshot:
    async def execute(_audit: object) -> dict[str, Any]:
        snapshot = await _snapshot(session)
        if not any(item.id == target_id for item in snapshot.targets):
            raise HTTPException(
                status_code=404,
                detail="Operations target not found",
            )
        recovery_request: DisasterRecoveryRun | None = None
        if command.action == "recover":
            if target_id != "backup":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This dependency has no automated recovery executor; "
                        "use its controlled infrastructure runbook"
                    ),
                )
            await acquire_enqueue_lock(session, "restore-validation")
            active_run = await session.scalar(
                select(DisasterRecoveryRun.id)
                .where(
                    DisasterRecoveryRun.status.in_({"pending", "running"}),
                    DisasterRecoveryRun.operation.in_({"restore_validation", "test"}),
                )
                .limit(1)
            )
            if active_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A restore validation or disaster-recovery drill is "
                        "already queued or running"
                    ),
                )
            backup = await session.scalar(
                select(BackupRecord)
                .where(
                    BackupRecord.status == "completed",
                    BackupRecord.location.is_not(None),
                    BackupRecord.checksum.is_not(None),
                    BackupRecord.size_bytes.is_not(None),
                    BackupRecord.size_bytes > 0,
                )
                .order_by(BackupRecord.completed_at.desc())
                .limit(1)
            )
            if backup is None:
                raise HTTPException(
                    status_code=409,
                    detail="A protected completed backup is required for recovery",
                )
            if not await _backup_artifact_ready(backup, verify_checksum=False):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The latest backup artifact is missing or failed live "
                        "readiness verification"
                    ),
                )
            recovery_request = DisasterRecoveryRun(
                operation="test",
                status="pending",
                details={
                    "backup_id": backup.id,
                    "dry_run": True,
                    "requested_by": actor.id,
                },
            )
            session.add(recovery_request)
            await session.flush()
        return {
            "health_rechecked": command.action != "recover",
            "recovery_request_id": (
                recovery_request.id if recovery_request is not None else None
            ),
        }

    await _run_audited_mutation(
        session,
        actor=actor,
        domain="operations-integration",
        resource_id=target_id,
        action=command.action,
        request=command.model_dump(mode="json"),
        mutation=execute,
    )
    return await _snapshot(session)
