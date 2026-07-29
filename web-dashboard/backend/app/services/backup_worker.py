"""Durable database-backed worker for backup and restore-validation jobs."""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AuditEvent, BackupRecord, DisasterRecoveryRun
from app.services.backup_executor import (
    BackupExecutionError,
    BackupExecutor,
    get_backup_executor,
)
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _now() -> datetime:
    return datetime.now(UTC)


def _system_audit(
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> AuditEvent:
    return AuditEvent(
        organization_id=None,
        user_id=None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )


class BackupJobWorker:
    """Claim jobs atomically and persist terminal execution evidence."""

    def __init__(
        self,
        *,
        executor: BackupExecutor | None = None,
        session_factory: SessionFactory = SessionLocal,
    ) -> None:
        self._executor = executor or get_backup_executor()
        self._session_factory = session_factory

    @property
    def _stale_before(self) -> datetime:
        return _now() - timedelta(seconds=settings.BACKUP_JOB_LEASE_SECONDS)

    async def claim_backup(self) -> str | None:
        """Claim one pending or safely expired backup job with SKIP LOCKED."""

        async with self._session_factory() as session:
            record = await session.scalar(
                select(BackupRecord)
                .where(
                    or_(
                        BackupRecord.status == "pending",
                        and_(
                            BackupRecord.status == "running",
                            BackupRecord.updated_at < self._stale_before,
                        ),
                    )
                )
                .order_by(BackupRecord.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            record.status = "running"
            record.updated_at = _now()
            session.add(
                _system_audit(
                    "backup.worker.claimed",
                    "backup",
                    record.id,
                    {"status": "running"},
                )
            )
            await session.commit()
            return record.id

    async def claim_restore_validation(self) -> str | None:
        """Claim one durable restore-validation or DR-drill job."""

        async with self._session_factory() as session:
            record = await session.scalar(
                select(DisasterRecoveryRun)
                .where(
                    DisasterRecoveryRun.operation.in_({"restore_validation", "test"}),
                    or_(
                        DisasterRecoveryRun.status == "pending",
                        and_(
                            DisasterRecoveryRun.status == "running",
                            DisasterRecoveryRun.updated_at < self._stale_before,
                        ),
                    ),
                )
                .order_by(DisasterRecoveryRun.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            record.status = "running"
            record.updated_at = _now()
            session.add(
                _system_audit(
                    "dr.worker.claimed",
                    "disaster_recovery_run",
                    record.id,
                    {
                        "status": "running",
                        "operation": record.operation,
                        "backup_id": (record.details or {}).get("backup_id"),
                    },
                )
            )
            await session.commit()
            return record.id

    async def execute_backup(self, backup_id: str) -> None:
        try:
            artifact = await self._executor.create_backup(backup_id)
        except asyncio.CancelledError:
            raise
        except BackupExecutionError as exc:
            await self._finish_backup_failure(backup_id, exc)
            return
        except Exception:
            await self._finish_backup_failure(
                backup_id,
                BackupExecutionError(
                    "PostgreSQL backup",
                    "PostgreSQL backup failed unexpectedly",
                ),
            )
            return

        async with self._session_factory() as session:
            record = await session.scalar(
                select(BackupRecord)
                .where(BackupRecord.id == backup_id)
                .with_for_update()
            )
            if record is None or record.status != "running":
                return
            record.status = "completed"
            record.location = artifact.location
            record.checksum = artifact.checksum
            record.size_bytes = artifact.size_bytes
            record.completed_at = _now()
            session.add(
                _system_audit(
                    "backup.worker.completed",
                    "backup",
                    backup_id,
                    {
                        "status": "completed",
                        "checksum": artifact.checksum,
                        "size_bytes": artifact.size_bytes,
                    },
                )
            )
            await session.commit()

    async def _finish_backup_failure(
        self,
        backup_id: str,
        exc: BackupExecutionError,
    ) -> None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(BackupRecord)
                .where(BackupRecord.id == backup_id)
                .with_for_update()
            )
            if record is None or record.status != "running":
                return
            record.status = "failed"
            record.completed_at = _now()
            session.add(
                _system_audit(
                    "backup.worker.failed",
                    "backup",
                    backup_id,
                    {
                        "status": "failed",
                        "operation": exc.operation,
                        "reason": exc.public_message,
                    },
                )
            )
            await session.commit()

    async def execute_restore_validation(self, run_id: str) -> None:
        backup: BackupRecord | None = None
        operation = "restore validation"
        try:
            async with self._session_factory() as session:
                run = await session.scalar(
                    select(DisasterRecoveryRun).where(DisasterRecoveryRun.id == run_id)
                )
                if run is None or run.status != "running":
                    return
                operation = run.operation
                backup_id = str((run.details or {}).get("backup_id", ""))
                backup = (
                    await session.scalar(
                        select(BackupRecord).where(
                            BackupRecord.id == backup_id,
                            BackupRecord.status == "completed",
                        )
                    )
                    if backup_id
                    else None
                )
            if backup is None or not backup.location or not backup.checksum:
                raise BackupExecutionError(
                    "restore validation",
                    "The selected completed backup has no protected artifact",
                    status_code=409,
                )
            validation = await self._executor.validate_restore(
                backup.location,
                backup.checksum,
                run_id,
                expected_size_bytes=backup.size_bytes,
            )
        except asyncio.CancelledError:
            raise
        except BackupExecutionError as exc:
            await self._finish_restore_failure(run_id, operation, exc)
            return
        except Exception:
            await self._finish_restore_failure(
                run_id,
                operation,
                BackupExecutionError(
                    "restore validation",
                    "Restore validation failed unexpectedly",
                ),
            )
            return

        async with self._session_factory() as session:
            run = await session.scalar(
                select(DisasterRecoveryRun)
                .where(DisasterRecoveryRun.id == run_id)
                .with_for_update()
            )
            if run is None or run.status != "running":
                return
            run.status = "completed"
            run.completed_at = _now()
            run.details = {
                **(run.details or {}),
                "validated": validation.restored,
                "checksum": validation.checksum,
                "size_bytes": validation.size_bytes,
            }
            session.add(
                _system_audit(
                    "dr.worker.completed",
                    "disaster_recovery_run",
                    run_id,
                    {
                        "status": "completed",
                        "operation": run.operation,
                        "backup_id": backup.id,
                        "checksum": validation.checksum,
                        "size_bytes": validation.size_bytes,
                    },
                )
            )
            await session.commit()

    async def _finish_restore_failure(
        self,
        run_id: str,
        operation: str,
        exc: BackupExecutionError,
    ) -> None:
        async with self._session_factory() as session:
            run = await session.scalar(
                select(DisasterRecoveryRun)
                .where(DisasterRecoveryRun.id == run_id)
                .with_for_update()
            )
            if run is None or run.status != "running":
                return
            run.status = "failed"
            run.completed_at = _now()
            run.details = {
                **(run.details or {}),
                "validated": False,
                "reason": exc.public_message,
            }
            session.add(
                _system_audit(
                    "dr.worker.failed",
                    "disaster_recovery_run",
                    run_id,
                    {
                        "status": "failed",
                        "operation": operation,
                        "backup_id": (run.details or {}).get("backup_id"),
                        "reason": exc.public_message,
                    },
                )
            )
            await session.commit()

    async def run_once(self) -> bool:
        backup_id = await self.claim_backup()
        if backup_id is not None:
            await self.execute_backup(backup_id)
            return True
        run_id = await self.claim_restore_validation()
        if run_id is not None:
            await self.execute_restore_validation(run_id)
            return True
        return False

    async def preflight(self, *, require_heartbeat: bool = False) -> None:
        """Verify database schema, storage, and client/server compatibility."""

        required_tools = ("pg_dump", "pg_restore", "createdb", "dropdb", "psql")
        missing = [tool for tool in required_tools if shutil.which(tool) is None]
        if missing:
            raise RuntimeError("Required PostgreSQL client utilities are unavailable")

        process = await asyncio.create_subprocess_exec(
            "pg_dump",
            "--version",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError("PostgreSQL client version probe timed out") from exc
        match = re.search(rb"PostgreSQL\)\s+(\d+)", stdout)
        if process.returncode != 0 or match is None:
            raise RuntimeError("PostgreSQL client version could not be determined")
        client_major = int(match.group(1))

        async with self._session_factory() as session:
            server_version_num = int(
                await session.scalar(text("SHOW server_version_num"))
            )
            schema_ready = bool(
                await session.scalar(
                    text(
                        "SELECT "
                        "to_regclass('backup_records') IS NOT NULL "
                        "AND to_regclass('disaster_recovery_runs') IS NOT NULL "
                        "AND EXISTS ("
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'backup_records' "
                        "AND column_name = 'size_bytes' "
                        "AND data_type = 'bigint'"
                        ")"
                    )
                )
            )
        if client_major < server_version_num // 10000:
            raise RuntimeError(
                "PostgreSQL backup client is older than the database server"
            )
        if not schema_ready:
            raise RuntimeError("Backup worker database schema is not current")

        self._executor.verify_storage()
        if require_heartbeat:
            self._executor.verify_heartbeat()

    async def _heartbeat_forever(self) -> None:
        while True:
            self._executor.write_heartbeat()
            await asyncio.sleep(settings.BACKUP_WORKER_HEARTBEAT_SECONDS)

    async def _process_forever(self) -> None:
        while True:
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Driver errors may contain a connection URL.  Log only the
                # exception class and retry after the normal poll interval.
                logger.error(
                    "Backup worker cycle failed",
                    error_type=type(exc).__name__,
                )
                processed = False
            if not processed:
                await asyncio.sleep(settings.BACKUP_WORKER_POLL_SECONDS)

    async def run_forever(self) -> None:
        await self.preflight()
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._heartbeat_forever())
            tasks.create_task(self._process_forever())


async def _main(*, healthcheck: bool = False) -> None:
    worker = BackupJobWorker()
    if healthcheck:
        await worker.preflight(require_heartbeat=True)
        return
    await worker.run_forever()


if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(_main(healthcheck="--healthcheck" in sys.argv[1:]))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error(
            "Backup worker startup or healthcheck failed",
            error_type=type(exc).__name__,
        )
        raise SystemExit(1) from None
