"""Durable database-backed worker for backup and restore-validation jobs."""

from __future__ import annotations

import asyncio
import re
import shutil
import signal
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AuditEvent, BackupRecord, DisasterRecoveryRun
from app.services.backup_executor import (
    BackupExecutionError,
    BackupExecutor,
    acquire_enqueue_lock,
    get_backup_executor,
    restore_scratch_database_name,
)
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
MAINTENANCE_INTERVAL_SECONDS = 300
RESTORE_SCRATCH_DATABASES_KEY = "_restore_scratch_databases"


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


class LeaseLostError(RuntimeError):
    """The durable job was reclaimed and this worker must stop publishing."""


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    lease_token: str
    reclaimed: bool
    stale_scratch_databases: tuple[str, ...] = ()


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def retention_candidate_ids(
    backups: list[BackupRecord],
    recovery_runs: list[DisasterRecoveryRun],
    *,
    now: datetime,
    keep_count: int,
    keep_days: int,
    current_backup_id: str | None = None,
    pressure: bool = False,
) -> list[str]:
    """Choose oldest safe artifacts without deleting audit evidence."""

    completed = [
        record for record in backups if record.status == "completed" and record.location
    ]
    protected = {current_backup_id} if current_backup_id else set()
    by_scope: dict[str, list[BackupRecord]] = {}
    for record in completed:
        by_scope.setdefault(record.scope, []).append(record)
    for records in by_scope.values():
        records.sort(
            key=lambda item: _as_utc(item.completed_at or item.created_at),
            reverse=True,
        )
        if records:
            protected.add(records[0].id)

    validated_runs = []
    for run in recovery_runs:
        backup_id = str((run.details or {}).get("backup_id", "")).strip()
        if not backup_id:
            continue
        if run.status in {"pending", "running"}:
            protected.add(backup_id)
        if run.status == "completed" and (run.details or {}).get("validated") is True:
            validated_runs.append(run)
            if _as_utc(run.completed_at or run.updated_at or run.created_at) >= (
                now - timedelta(hours=24)
            ):
                protected.add(backup_id)
    if validated_runs:
        latest_validation = max(
            validated_runs,
            key=lambda item: _as_utc(
                item.completed_at or item.updated_at or item.created_at
            ),
        )
        protected.add(str((latest_validation.details or {})["backup_id"]))

    cutoff = now - timedelta(days=keep_days)
    candidates: list[BackupRecord] = []
    for records in by_scope.values():
        for index, record in enumerate(records):
            if record.id in protected:
                continue
            completed_at = _as_utc(record.completed_at or record.created_at)
            if pressure or index >= keep_count or completed_at < cutoff:
                candidates.append(record)
    candidates.sort(key=lambda item: _as_utc(item.completed_at or item.created_at))
    return [record.id for record in candidates]


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
        self._next_maintenance_at = 0.0

    @property
    def _stale_before(self) -> datetime:
        return _now() - timedelta(seconds=settings.BACKUP_JOB_LEASE_SECONDS)

    @staticmethod
    def _uses_database_clock(session: AsyncSession) -> bool:
        get_bind = getattr(session, "get_bind", None)
        if not callable(get_bind):
            return False
        bind = get_bind()
        return getattr(getattr(bind, "dialect", None), "name", None) == "postgresql"

    def _lease_timestamp(self, session: AsyncSession) -> Any:
        return func.now() if self._uses_database_clock(session) else _now()

    def _lease_stale_before(self, session: AsyncSession) -> Any:
        if self._uses_database_clock(session):
            return func.now() - timedelta(seconds=settings.BACKUP_JOB_LEASE_SECONDS)
        return self._stale_before

    async def claim_backup(self) -> ClaimedJob | None:
        """Claim one pending or safely expired backup job with SKIP LOCKED."""

        async with self._session_factory() as session:
            record = await session.scalar(
                select(BackupRecord)
                .where(
                    or_(
                        BackupRecord.status == "pending",
                        and_(
                            BackupRecord.status == "running",
                            BackupRecord.updated_at < self._lease_stale_before(session),
                        ),
                    )
                )
                .order_by(BackupRecord.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            reclaimed = record.status == "running"
            lease_token = str(uuid4())
            record.status = "running"
            record.lease_token = lease_token
            record.updated_at = self._lease_timestamp(session)
            session.add(
                _system_audit(
                    "backup.worker.claimed",
                    "backup",
                    record.id,
                    {"status": "running", "reclaimed": reclaimed},
                )
            )
            await session.commit()
            return ClaimedJob(record.id, lease_token, reclaimed)

    async def claim_restore_validation(self) -> ClaimedJob | None:
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
                            DisasterRecoveryRun.updated_at
                            < self._lease_stale_before(session),
                        ),
                    ),
                )
                .order_by(DisasterRecoveryRun.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            reclaimed = record.status == "running"
            lease_token = str(uuid4())
            scratch_database = restore_scratch_database_name(
                record.id,
                lease_token,
            )
            details = dict(record.details or {})
            persisted_scratch_databases = details.get(
                RESTORE_SCRATCH_DATABASES_KEY,
                [],
            )
            scratch_databases = (
                [
                    value
                    for value in persisted_scratch_databases
                    if isinstance(value, str)
                ]
                if isinstance(persisted_scratch_databases, list)
                else []
            )
            if scratch_database not in scratch_databases:
                scratch_databases.append(scratch_database)
            details[RESTORE_SCRATCH_DATABASES_KEY] = scratch_databases
            record.details = details
            record.status = "running"
            record.lease_token = lease_token
            record.updated_at = self._lease_timestamp(session)
            session.add(
                _system_audit(
                    "dr.worker.claimed",
                    "disaster_recovery_run",
                    record.id,
                    {
                        "status": "running",
                        "operation": record.operation,
                        "backup_id": (record.details or {}).get("backup_id"),
                        "reclaimed": reclaimed,
                    },
                )
            )
            await session.commit()
            return ClaimedJob(
                record.id,
                lease_token,
                reclaimed,
                tuple(
                    database_name
                    for database_name in scratch_databases
                    if database_name != scratch_database
                ),
            )

    async def _renew_lease(self, model: Any, claim: ClaimedJob) -> None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(model)
                .where(
                    model.id == claim.id,
                    model.status == "running",
                    model.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if record is None:
                raise LeaseLostError(f"Lease for {claim.id} was lost")
            record.updated_at = self._lease_timestamp(session)
            await session.commit()

    async def _heartbeat_lease(
        self,
        model: Any,
        claim: ClaimedJob,
        stop_event: asyncio.Event,
    ) -> None:
        interval = min(
            settings.BACKUP_WORKER_HEARTBEAT_SECONDS,
            max(1, settings.BACKUP_JOB_LEASE_SECONDS // 3),
        )
        while not stop_event.is_set():
            await self._wait_for_stop(stop_event, interval)
            if stop_event.is_set():
                return
            await self._renew_lease(model, claim)

    async def _run_with_heartbeat(
        self,
        model: Any,
        claim: ClaimedJob,
        operation: Callable[[ClaimedJob], Any],
    ) -> None:
        stop_event = asyncio.Event()
        operation_task = asyncio.create_task(operation(claim))
        heartbeat_task = asyncio.create_task(
            self._heartbeat_lease(model, claim, stop_event)
        )
        try:
            done, _ = await asyncio.wait(
                {operation_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done and not operation_task.done():
                error = heartbeat_task.exception()
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                if error is not None:
                    raise error
                raise LeaseLostError(f"Lease heartbeat for {claim.id} stopped")
            await operation_task
        finally:
            stop_event.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

    async def _database_size_bytes(self) -> int:
        async with self._session_factory() as session:
            return int(
                await session.scalar(
                    text("SELECT pg_database_size(current_database())")
                )
            )

    async def _delete_expired_artifact(
        self,
        backup_id: str,
        *,
        reason: str,
    ) -> None:
        location: str | None = None
        async with self._session_factory() as session:
            await acquire_enqueue_lock(session, "restore-validation")
            record = await session.scalar(
                select(BackupRecord)
                .where(BackupRecord.id == backup_id)
                .with_for_update()
            )
            if record is None or record.status not in {"completed", "expired"}:
                return
            protected_reference = await session.scalar(
                select(DisasterRecoveryRun.id)
                .where(
                    DisasterRecoveryRun.details["backup_id"].as_string() == backup_id,
                    or_(
                        DisasterRecoveryRun.status.in_({"pending", "running"}),
                        and_(
                            DisasterRecoveryRun.status == "completed",
                            DisasterRecoveryRun.completed_at
                            >= self._lease_timestamp(session) - timedelta(hours=24),
                            DisasterRecoveryRun.details["validated"]
                            .as_boolean()
                            .is_(True),
                        ),
                    ),
                )
                .limit(1)
            )
            if protected_reference is not None:
                return
            if record.status == "completed":
                record.status = "expired"
                session.add(
                    _system_audit(
                        "backup.worker.expired",
                        "backup",
                        record.id,
                        {
                            "status": "expired",
                            "reason": reason,
                            "checksum": record.checksum,
                            "size_bytes": record.size_bytes,
                        },
                    )
                )
            location = record.location
            await session.commit()

        if not location:
            return
        await asyncio.to_thread(self._executor.delete_artifact, location)
        async with self._session_factory() as session:
            record = await session.scalar(
                select(BackupRecord)
                .where(
                    BackupRecord.id == backup_id,
                    BackupRecord.status == "expired",
                    BackupRecord.location == location,
                )
                .with_for_update()
            )
            if record is None:
                return
            # Keep checksum, byte size, timestamps, and audit rows as durable
            # evidence while removing only the no-longer-present path.
            record.location = None
            session.add(
                _system_audit(
                    "backup.worker.artifact_deleted",
                    "backup",
                    record.id,
                    {"status": "expired", "reason": reason},
                )
            )
            await session.commit()

    async def _apply_retention(
        self,
        *,
        current_backup_id: str | None,
        pressure: bool,
        required_free_bytes: int | None = None,
    ) -> None:
        async with self._session_factory() as session:
            referenced_locations = {
                str(location)
                for location in (
                    await session.scalars(
                        select(BackupRecord.location).where(
                            BackupRecord.location.is_not(None)
                        )
                    )
                ).all()
                if location
            }
            expired = list(
                (
                    await session.scalars(
                        select(BackupRecord).where(
                            BackupRecord.status == "expired",
                            BackupRecord.location.is_not(None),
                        )
                    )
                ).all()
            )
            active_attempts = {
                (record.id, str(record.lease_token))
                for record in (
                    await session.scalars(
                        select(BackupRecord).where(
                            BackupRecord.status == "running",
                            BackupRecord.lease_token.is_not(None),
                        )
                    )
                ).all()
                if record.lease_token
            }
        await asyncio.to_thread(
            self._executor.cleanup_orphan_artifacts,
            referenced_locations,
            settings.BACKUP_JOB_LEASE_SECONDS,
            active_attempts,
        )
        for record in expired:
            await self._delete_expired_artifact(
                record.id,
                reason="retention recovery",
            )

        async with self._session_factory() as session:
            backups = list(
                (
                    await session.scalars(
                        select(BackupRecord).where(
                            BackupRecord.status == "completed",
                            BackupRecord.location.is_not(None),
                        )
                    )
                ).all()
            )
            recovery_runs = list(
                (await session.scalars(select(DisasterRecoveryRun))).all()
            )

        candidates = retention_candidate_ids(
            backups,
            recovery_runs,
            now=_now(),
            keep_count=settings.BACKUP_RETENTION_COUNT,
            keep_days=settings.BACKUP_RETENTION_DAYS,
            current_backup_id=current_backup_id,
            pressure=pressure,
        )
        reason = "low storage capacity" if pressure else "retention policy"
        for backup_id in candidates:
            await self._delete_expired_artifact(backup_id, reason=reason)
            if required_free_bytes is not None and (
                await asyncio.to_thread(self._executor.available_bytes)
                >= required_free_bytes
            ):
                break

    async def _ensure_capacity(self, backup_id: str) -> None:
        await self._apply_retention(
            current_backup_id=backup_id,
            pressure=False,
        )
        required_free_bytes = (
            await self._database_size_bytes() + settings.BACKUP_MIN_FREE_BYTES
        )
        free_bytes = await asyncio.to_thread(self._executor.available_bytes)
        if free_bytes < required_free_bytes:
            await self._apply_retention(
                current_backup_id=backup_id,
                pressure=True,
                required_free_bytes=required_free_bytes,
            )
            free_bytes = await asyncio.to_thread(self._executor.available_bytes)
        if free_bytes < required_free_bytes:
            raise BackupExecutionError(
                "backup capacity check",
                "The protected backup volume does not have enough safe free space",
                status_code=507,
            )

    async def execute_backup(self, claim: ClaimedJob) -> None:
        try:
            if claim.reclaimed:
                await asyncio.to_thread(
                    self._executor.cleanup_backup_partials,
                    claim.id,
                )
            await self._ensure_capacity(claim.id)
            artifact = await self._executor.create_backup(
                claim.id,
                claim.lease_token,
            )
        except asyncio.CancelledError:
            raise
        except BackupExecutionError as exc:
            await self._finish_backup_failure(claim, exc)
            return
        except Exception:
            await self._finish_backup_failure(
                claim,
                BackupExecutionError(
                    "PostgreSQL backup",
                    "PostgreSQL backup failed unexpectedly",
                ),
            )
            return

        async with self._session_factory() as session:
            record = await session.scalar(
                select(BackupRecord)
                .where(
                    BackupRecord.id == claim.id,
                    BackupRecord.status == "running",
                    BackupRecord.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if record is None:
                await asyncio.to_thread(
                    self._executor.delete_artifact,
                    artifact.location,
                )
                return
            record.status = "completed"
            record.lease_token = None
            record.location = artifact.location
            record.checksum = artifact.checksum
            record.size_bytes = artifact.size_bytes
            record.completed_at = _now()
            session.add(
                _system_audit(
                    "backup.worker.completed",
                    "backup",
                    claim.id,
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
        claim: ClaimedJob,
        exc: BackupExecutionError,
    ) -> None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(BackupRecord)
                .where(
                    BackupRecord.id == claim.id,
                    BackupRecord.status == "running",
                    BackupRecord.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if record is None:
                return
            record.status = "failed"
            record.lease_token = None
            record.completed_at = _now()
            session.add(
                _system_audit(
                    "backup.worker.failed",
                    "backup",
                    claim.id,
                    {
                        "status": "failed",
                        "operation": exc.operation,
                        "reason": exc.public_message,
                    },
                )
            )
            await session.commit()

    async def execute_restore_validation(self, claim: ClaimedJob) -> None:
        backup: BackupRecord | None = None
        operation = "restore validation"
        try:
            async with self._session_factory() as session:
                run = await session.scalar(
                    select(DisasterRecoveryRun).where(
                        DisasterRecoveryRun.id == claim.id,
                        DisasterRecoveryRun.status == "running",
                        DisasterRecoveryRun.lease_token == claim.lease_token,
                    )
                )
                if run is None:
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
                claim.id,
                claim.lease_token,
                stale_scratch_databases=claim.stale_scratch_databases,
                expected_size_bytes=backup.size_bytes,
            )
        except asyncio.CancelledError:
            raise
        except BackupExecutionError as exc:
            await self._finish_restore_failure(claim, operation, exc)
            return
        except Exception:
            await self._finish_restore_failure(
                claim,
                operation,
                BackupExecutionError(
                    "restore validation",
                    "Restore validation failed unexpectedly",
                ),
            )
            return

        async with self._session_factory() as session:
            await acquire_enqueue_lock(session, "restore-validation")
            run = await session.scalar(
                select(DisasterRecoveryRun)
                .where(
                    DisasterRecoveryRun.id == claim.id,
                    DisasterRecoveryRun.status == "running",
                    DisasterRecoveryRun.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if run is None:
                return
            run.status = "completed"
            run.lease_token = None
            run.completed_at = _now()
            details = dict(run.details or {})
            details.pop(RESTORE_SCRATCH_DATABASES_KEY, None)
            run.details = {
                **details,
                "validated": validation.restored,
                "checksum": validation.checksum,
                "size_bytes": validation.size_bytes,
            }
            session.add(
                _system_audit(
                    "dr.worker.completed",
                    "disaster_recovery_run",
                    claim.id,
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
        claim: ClaimedJob,
        operation: str,
        exc: BackupExecutionError,
    ) -> None:
        async with self._session_factory() as session:
            await acquire_enqueue_lock(session, "restore-validation")
            run = await session.scalar(
                select(DisasterRecoveryRun)
                .where(
                    DisasterRecoveryRun.id == claim.id,
                    DisasterRecoveryRun.status == "running",
                    DisasterRecoveryRun.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if run is None:
                return
            run.status = "failed"
            run.lease_token = None
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
                    claim.id,
                    {
                        "status": "failed",
                        "operation": operation,
                        "backup_id": (run.details or {}).get("backup_id"),
                        "reason": exc.public_message,
                    },
                )
            )
            await session.commit()

    async def _enqueue_scheduled_backup_if_due(self) -> bool:
        """Queue one protected platform backup when the production schedule is due."""
        if not settings.BACKUP_SCHEDULE_ENABLED:
            return False
        async with self._session_factory() as session:
            await acquire_enqueue_lock(session, "scheduled-platform-backup")
            active = await session.scalar(
                select(BackupRecord.id)
                .where(
                    BackupRecord.scope == "platform",
                    BackupRecord.status.in_({"pending", "running"}),
                )
                .limit(1)
            )
            if active is not None:
                return False
            latest = await session.scalar(
                select(BackupRecord.completed_at)
                .where(
                    BackupRecord.scope == "platform",
                    BackupRecord.status == "completed",
                    BackupRecord.completed_at.is_not(None),
                )
                .order_by(BackupRecord.completed_at.desc())
                .limit(1)
            )
            if latest is not None and _as_utc(latest) > _now() - timedelta(
                hours=settings.BACKUP_SCHEDULE_INTERVAL_HOURS
            ):
                return False
            record = BackupRecord(
                kind="scheduled-production",
                scope="platform",
                status="pending",
            )
            session.add(record)
            await session.flush()
            session.add(
                _system_audit(
                    "backup.schedule.queued",
                    "backup",
                    record.id,
                    {
                        "scope": "platform",
                        "interval_hours": settings.BACKUP_SCHEDULE_INTERVAL_HOURS,
                    },
                )
            )
            await session.commit()
            return True

    async def run_once(self) -> bool:
        backup = await self.claim_backup()
        if backup is not None:
            await self._run_with_heartbeat(
                BackupRecord,
                backup,
                self.execute_backup,
            )
            await self._apply_retention(
                current_backup_id=backup.id,
                pressure=False,
            )
            self._next_maintenance_at = (
                asyncio.get_running_loop().time() + MAINTENANCE_INTERVAL_SECONDS
            )
            return True
        recovery_run = await self.claim_restore_validation()
        if recovery_run is not None:
            await self._run_with_heartbeat(
                DisasterRecoveryRun,
                recovery_run,
                self.execute_restore_validation,
            )
            return True
        now = asyncio.get_running_loop().time()
        if now < self._next_maintenance_at:
            return False
        self._next_maintenance_at = now + MAINTENANCE_INTERVAL_SECONDS
        await self._enqueue_scheduled_backup_if_due()
        await self._apply_retention(
            current_backup_id=None,
            pressure=False,
        )
        return True

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
                        ") AND EXISTS ("
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'backup_records' "
                        "AND column_name = 'lease_token'"
                        ") AND EXISTS ("
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'disaster_recovery_runs' "
                        "AND column_name = 'lease_token'"
                        ")"
                    )
                )
            )
        server_major = server_version_num // 10000
        if client_major != server_major:
            raise RuntimeError(
                "PostgreSQL backup client and database server major versions "
                "must match"
            )
        if not schema_ready:
            raise RuntimeError("Backup worker database schema is not current")

        self._executor.verify_storage()
        if not require_heartbeat:
            self._executor.cleanup_stale_partials(
                settings.BACKUP_JOB_LEASE_SECONDS,
            )
        if require_heartbeat:
            self._executor.verify_heartbeat()

    @staticmethod
    async def _wait_for_stop(stop_event: asyncio.Event, timeout: int) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
        except TimeoutError:
            return

    async def _heartbeat_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            self._executor.write_heartbeat()
            await self._wait_for_stop(
                stop_event,
                settings.BACKUP_WORKER_HEARTBEAT_SECONDS,
            )

    async def _process_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
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
                await self._wait_for_stop(
                    stop_event,
                    settings.BACKUP_WORKER_POLL_SECONDS,
                )

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        await self.preflight()
        stop_event = stop_event or asyncio.Event()
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._heartbeat_forever(stop_event))
            tasks.create_task(self._process_forever(stop_event))


async def _main(*, healthcheck: bool = False) -> None:
    worker = BackupJobWorker()
    if healthcheck:
        await worker.preflight(require_heartbeat=True)
        return

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for termination_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(termination_signal, stop_event.set)
            installed_signals.append(termination_signal)
        except NotImplementedError:  # pragma: no cover - non-POSIX fallback
            continue
    try:
        await worker.run_forever(stop_event)
    finally:
        for termination_signal in installed_signals:
            loop.remove_signal_handler(termination_signal)


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
