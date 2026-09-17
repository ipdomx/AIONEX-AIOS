"""Real PostgreSQL contracts for backup worker admission and cycle registration.

Each case owns a random schema in a delimited test-named database. Worker storage,
providers, subprocesses, and application lifecycle remain forbidden.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    AuditEvent,
    BackupRecord,
    DisasterRecoveryRun,
    HostMaintenanceWorkCycle,
    OwnerControlRecord,
)
from app.services import backup_worker as worker_module
from app.services.backup_executor import BackupCleanupIncomplete, BackupExecutionError
from app.services.backup_worker import BackupJobWorker
from app.services.host_maintenance_admission import (
    COVERAGE_SCHEMA_VERSION,
    COVERAGE_SCOPE,
    DOMAIN,
    RESOURCE_ID,
    SCHEMA_VERSION,
    SCOPE,
    HostMaintenanceUnavailable,
    close_admission,
    open_admission,
)
from app.services.host_maintenance_cycles import snapshot_backup_cycles


WAIT_SECONDS = 10


class ForbiddenIO:
    def __getattr__(self, name):
        raise AssertionError(f"database contracts must not perform runtime I/O: {name}")


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AuditEvent,
            BackupRecord,
            DisasterRecoveryRun,
            HostMaintenanceWorkCycle,
            OwnerControlRecord,
        )
    }
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return list(tables)
        tables = expanded


@pytest_asyncio.fixture
async def backup_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("backup maintenance contracts require PostgreSQL/asyncpg")
    database = (url.database or "").lower()
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])", database
    ) is None:
        raise RuntimeError("backup maintenance tests require an isolated test database")

    schema = f"fr06c5d2_backup_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {"search_path": schema, "application_name": schema}
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    operation_id = str(uuid4())
    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, tables=_required_tables()
                )
            )
        async with sessions() as session:
            session.add(
                OwnerControlRecord(
                    domain=DOMAIN,
                    resource_id=RESOURCE_ID,
                    status="open",
                    enabled=True,
                    version=2,
                    payload={
                        "schema_version": COVERAGE_SCHEMA_VERSION,
                        "scope": COVERAGE_SCOPE,
                        "generation": 2,
                        "operation_id": operation_id,
                        "reason": "isolated-backup-coverage",
                        "changed_at": datetime.now(UTC).isoformat(),
                        "full_host_closure": False,
                    },
                )
            )
            await session.commit()

        monkeypatch.setattr(settings, "BACKUP_JOB_LEASE_SECONDS", 120)
        monkeypatch.setattr(settings, "BACKUP_SCHEDULE_ENABLED", True)
        monkeypatch.setattr(settings, "BACKUP_AUTO_RESTORE_VALIDATION_ENABLED", True)
        monkeypatch.setattr(settings, "BACKUP_SCHEDULE_INTERVAL_HOURS", 24)

        def forbidden_factory(*_args, **_kwargs):
            raise AssertionError("worker must retain the explicit fake I/O dependencies")

        async def forbidden_subprocess(*_args, **_kwargs):
            raise AssertionError("database contracts must not launch subprocesses")

        for name in (
            "get_backup_executor",
            "ThreeDAssetSnapshotExecutor",
            "OffsiteBackupReplicator",
        ):
            monkeypatch.setattr(worker_module, name, forbidden_factory)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_subprocess)

        # Do not inject admission_check or cycle_service: their production
        # defaults must consume this explicitly isolated session factory.
        worker = BackupJobWorker(
            executor=ForbiddenIO(),
            three_d_executor=ForbiddenIO(),
            offsite_replicator=ForbiddenIO(),
            session_factory=sessions,
        )
        yield SimpleNamespace(
            worker=worker,
            sessions=sessions,
            engine=engine,
            operation_id=operation_id,
            application_name=schema,
        )
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


async def _close(case):
    return await close_admission(
        operation_id=case.operation_id,
        expected_generation=2,
        reason="isolated-backup-worker-close",
        session_factory=case.sessions,
    )


async def _reopen(case, closed):
    return await open_admission(
        operation_id=case.operation_id,
        expected_generation=closed.generation,
        reason="isolated-backup-worker-reopen",
        session_factory=case.sessions,
    )


async def _snapshot(case):
    async with case.sessions() as session:
        result = {}
        for model in (BackupRecord, DisasterRecoveryRun):
            records = list(
                (await session.scalars(select(model).order_by(model.id))).all()
            )
            result[model.__tablename__] = [
                {
                    column.key: getattr(record, column.key)
                    for column in inspect(model).column_attrs
                }
                for record in records
            ]
        result["audit_count"] = await session.scalar(
            select(func.count()).select_from(AuditEvent)
        )
        return result


async def _seed_job(case, kind, state):
    job_id = str(uuid4())
    old = datetime.now(UTC) - timedelta(hours=1)
    if kind == "backup":
        row = BackupRecord(
            id=job_id, kind="synthetic", scope="platform", status="pending"
        )
    else:
        row = DisasterRecoveryRun(
            id=job_id,
            operation=kind,
            status="pending",
            details={"backup_id": str(uuid4()), "dry_run": True},
        )
    if state == "recovery":
        row.status = "running"
        row.lease_token = str(uuid4())
        row.updated_at = old
    async with case.sessions() as session:
        session.add(row)
        await session.commit()
    return job_id


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["backup", "restore_validation", "test"])
@pytest.mark.parametrize("state", ["pending", "recovery"])
async def test_closed_claim_preserves_pending_and_recovery_then_reopens(
    backup_case, kind, state
):
    case = backup_case
    job_id = await _seed_job(case, kind, state)
    closed = await _close(case)
    before = await _snapshot(case)
    claim = (
        case.worker.claim_backup
        if kind == "backup"
        else case.worker.claim_restore_validation
    )

    assert await claim() is None
    assert await _snapshot(case) == before

    await _reopen(case, closed)
    accepted = await claim()
    assert accepted is not None and accepted.id == job_id
    assert accepted.reclaimed is (state == "recovery")
    assert await claim() is None
    model = BackupRecord if kind == "backup" else DisasterRecoveryRun
    async with case.sessions() as session:
        row = await session.get(model, job_id)
        assert row is not None
        assert row.status == "running" and row.lease_token == accepted.lease_token
        if kind != "backup":
            assert row.details["backup_id"]
            assert row.details["dry_run"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["backup", "restore-validation"])
async def test_closed_scheduler_creates_nothing_and_reopen_enqueues_once(
    backup_case, kind
):
    case = backup_case
    completed_id = str(uuid4())
    if kind == "restore-validation":
        async with case.sessions() as session:
            session.add(
                BackupRecord(
                    id=completed_id,
                    kind="scheduled-production",
                    scope="platform",
                    status="completed",
                    location="/synthetic/no-io-backup.dump",
                    checksum="a" * 64,
                    size_bytes=1,
                    completed_at=datetime.now(UTC) - timedelta(days=2),
                )
            )
            await session.commit()
        schedule = case.worker._enqueue_latest_scheduled_restore_validation_if_needed
    else:
        schedule = case.worker._enqueue_scheduled_backup_if_due

    closed = await _close(case)
    before = await _snapshot(case)
    assert await schedule() is False
    assert await _snapshot(case) == before

    await _reopen(case, closed)
    assert await schedule() is True
    assert await schedule() is False
    async with case.sessions() as session:
        if kind == "backup":
            records = list((await session.scalars(select(BackupRecord))).all())
            assert len(records) == 1
            assert records[0].status == "pending"
            assert records[0].kind == "scheduled-production"
        else:
            records = list((await session.scalars(select(DisasterRecoveryRun))).all())
            assert len(records) == 1
            assert records[0].status == "pending"
            assert records[0].operation == "restore_validation"
            assert records[0].details["backup_id"] == completed_id
            assert records[0].details["auto_enqueued"] is True


@pytest.mark.asyncio
async def test_legacy_project_only_authority_cannot_admit_backup_work(
    backup_case, monkeypatch
):
    case = backup_case
    await _seed_job(case, "backup", "pending")
    await _seed_job(case, "restore_validation", "pending")
    async with case.sessions() as session:
        record = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == DOMAIN,
                OwnerControlRecord.resource_id == RESOURCE_ID,
            )
        )
        assert record is not None
        record.version = 1
        record.payload = {
            "schema_version": SCHEMA_VERSION,
            "scope": SCOPE,
            "generation": 1,
            "operation_id": None,
            "reason": "migration-seed",
            "changed_at": None,
            "full_host_closure": False,
        }
        await session.commit()
    before = await _snapshot(case)

    async def forbidden_work():
        raise AssertionError("legacy project-only scope admitted backup cycle I/O")

    monkeypatch.setattr(case.worker, "_run_once_owned", forbidden_work)
    assert await case.worker.run_once() is False
    assert await case.worker.claim_backup() is None
    assert await case.worker.claim_restore_validation() is None
    assert await case.worker._enqueue_scheduled_backup_if_due() is False
    assert (
        await case.worker._enqueue_latest_scheduled_restore_validation_if_needed()
        is False
    )
    assert await _snapshot(case) == before
    async with case.sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(HostMaintenanceWorkCycle)
        ) == 0


@pytest.mark.asyncio
async def test_default_cycle_service_commits_owner_before_io_and_close_keeps_it(
    backup_case, monkeypatch
):
    case = backup_case
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_io():
        # A distinct connection must see the ownership commit before I/O begins.
        async with case.sessions() as session:
            owners = list(
                (await session.scalars(select(HostMaintenanceWorkCycle))).all()
            )
            assert len(owners) == 1
            assert owners[0].consumer == "backup_cycles"
            assert owners[0].state == "active"
            assert owners[0].admitted_generation == 2
        entered.set()
        await release.wait()
        return True

    monkeypatch.setattr(case.worker, "_run_once_owned", fake_io)
    task = asyncio.create_task(case.worker.run_once())
    try:
        await asyncio.wait_for(entered.wait(), timeout=WAIT_SECONDS)
        closed = await _close(case)
        async with case.sessions() as session:
            during = await snapshot_backup_cycles(
                session,
                operation_id=case.operation_id,
                expected_generation=closed.generation,
            )
        assert during.active_count == 1 and during.unfinished_count == 1
        assert not during.is_clear and not task.done()
        release.set()
        assert await asyncio.wait_for(task, timeout=WAIT_SECONDS) is True
        async with case.sessions() as session:
            after = await snapshot_backup_cycles(
                session,
                operation_id=case.operation_id,
                expected_generation=closed.generation,
            )
        assert after.is_clear and after.unfinished_count == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True), timeout=WAIT_SECONDS
        )


@pytest.mark.asyncio
async def test_backup_claim_shared_admission_blocks_close_until_commit(
    backup_case, monkeypatch
):
    case = backup_case
    job_id = await _seed_job(case, "backup", "pending")
    admitted = asyncio.Event()
    release_claim = asyncio.Event()
    claimant_pid = None
    real_guard = case.worker._admission_check

    async def held_guard(session, *, required_scope):
        nonlocal claimant_pid
        assert required_scope == "backup_cycles"
        allowed = await real_guard(session, required_scope=required_scope)
        if allowed:
            claimant_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            admitted.set()
            await release_claim.wait()
        return allowed

    async def wait_for_blocked_close():
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                async with case.sessions() as observer:
                    blocked = await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name = :application_name "
                            "AND :claimant_pid = ANY(pg_blocking_pids(pid))"
                        ),
                        {
                            "application_name": case.application_name,
                            "claimant_pid": claimant_pid,
                        },
                    )
                if blocked:
                    return
                await asyncio.sleep(0.01)

    monkeypatch.setattr(case.worker, "_admission_check", held_guard)
    claim_task = asyncio.create_task(case.worker.claim_backup())
    close_task = None
    try:
        await asyncio.wait_for(admitted.wait(), timeout=WAIT_SECONDS)
        close_task = asyncio.create_task(_close(case))
        await wait_for_blocked_close()
        assert not close_task.done()

        release_claim.set()
        accepted = await asyncio.wait_for(claim_task, timeout=WAIT_SECONDS)
        assert accepted is not None and accepted.id == job_id
        await asyncio.wait_for(close_task, timeout=WAIT_SECONDS)
        assert await case.worker.claim_backup() is None
    finally:
        release_claim.set()
        tasks = [task for task in (claim_task, close_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=WAIT_SECONDS
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_state", ["closed", "missing", "malformed", "legacy"])
async def test_readonly_preflight_accepts_closed_coverage_and_rejects_unready_authority(
    backup_case, monkeypatch, authority_state
):
    case = backup_case
    if authority_state == "closed":
        await _close(case)
    else:
        async with case.sessions() as session:
            authority = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == DOMAIN,
                    OwnerControlRecord.resource_id == RESOURCE_ID,
                )
            )
            assert authority is not None
            if authority_state == "missing":
                await session.delete(authority)
            elif authority_state == "malformed":
                authority.payload = {**authority.payload, "full_host_closure": True}
            else:
                authority.version = 1
                authority.payload = {
                    "schema_version": SCHEMA_VERSION,
                    "scope": SCOPE,
                    "generation": 1,
                    "operation_id": None,
                    "reason": "migration-seed",
                    "changed_at": None,
                    "full_host_closure": False,
                }
            await session.commit()

    async with case.sessions() as session:
        server_major = int(
            await session.scalar(text("SHOW server_version_num"))
        ) // 10000
    before = await _snapshot(case)
    heartbeat_checks = []

    class VersionProcess:
        returncode = 0

        async def communicate(self):
            return f"pg_dump (PostgreSQL) {server_major}.0".encode(), b""

        def kill(self):
            raise AssertionError("the synthetic version probe must not time out")

    async def fake_version_probe(*args, **_kwargs):
        assert args == ("pg_dump", "--version")
        return VersionProcess()

    def fake_which(name):
        assert name in {"pg_dump", "pg_restore", "createdb", "dropdb", "psql"}
        return f"/synthetic/{name}"

    def verify_heartbeat():
        heartbeat_checks.append("read-only")

    monkeypatch.setattr(worker_module.shutil, "which", fake_which)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_version_probe)
    monkeypatch.setattr(
        case.worker, "_executor", SimpleNamespace(verify_heartbeat=verify_heartbeat)
    )
    if authority_state == "closed":
        await case.worker.preflight(require_heartbeat=True)
        assert heartbeat_checks == ["read-only"]
    else:
        with pytest.raises(HostMaintenanceUnavailable):
            await case.worker.preflight(require_heartbeat=True)
        assert not heartbeat_checks

    assert await _snapshot(case) == before
    async with case.sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(HostMaintenanceWorkCycle)
        ) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_type",
    [BackupExecutionError, BackupCleanupIncomplete],
    ids=["settled-failure", "cleanup-incomplete"],
)
async def test_executor_failure_commit_releases_only_settled_cycle(
    backup_case, monkeypatch, failure_type
):
    case = backup_case
    job_id = await _seed_job(case, "backup", "pending")
    observations = []

    async def capacity(received_id, **_kwargs):
        assert received_id == job_id
        observations.append("capacity")

    async def fail_executor(received_id, lease_token):
        assert received_id == job_id and lease_token
        async with case.sessions() as session:
            owners = list(
                (await session.scalars(select(HostMaintenanceWorkCycle))).all()
            )
            assert len(owners) == 1 and owners[0].state == "active"
            row = await session.get(BackupRecord, job_id)
            assert row is not None and row.status == "running"
            assert row.lease_token == lease_token
        observations.append("executor-failed")
        raise failure_type("synthetic backup", "Synthetic controlled executor failure")

    async def schedule_restore():
        observations.append("schedule")
        return False

    async def retention(*, current_backup_id, pressure):
        assert current_backup_id == job_id and pressure is False
        async with case.sessions() as session:
            row = await session.get(BackupRecord, job_id)
            assert row is not None and row.status == "failed"
            assert row.lease_token is None and row.completed_at is not None
            assert await session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action == "backup.worker.failed",
                    AuditEvent.resource_id == job_id,
                )
            ) == 1
        observations.append("failure-committed-before-retention")

    monkeypatch.setattr(
        case.worker, "_executor", SimpleNamespace(create_backup=fail_executor)
    )
    monkeypatch.setattr(
        case.worker, "_three_d_executor", SimpleNamespace(enabled=False)
    )
    monkeypatch.setattr(case.worker, "_offsite", SimpleNamespace(enabled=False))
    monkeypatch.setattr(case.worker, "_ensure_capacity", capacity)
    monkeypatch.setattr(
        case.worker,
        "_enqueue_latest_scheduled_restore_validation_if_needed",
        schedule_restore,
    )
    monkeypatch.setattr(case.worker, "_apply_retention", retention)

    assert await asyncio.wait_for(
        case.worker.run_once(), timeout=WAIT_SECONDS
    ) is True
    assert observations == [
        "capacity",
        "executor-failed",
        "schedule",
        "failure-committed-before-retention",
    ]
    async with case.sessions() as session:
        owners = list(
            (await session.scalars(select(HostMaintenanceWorkCycle))).all()
        )
        if failure_type is BackupCleanupIncomplete:
            assert len(owners) == 1 and owners[0].state == "unresolved"
            assert owners[0].unresolved_reason == "backup-cleanup-incomplete"
        else:
            assert owners == []
