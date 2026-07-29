"""Unit contracts for durable PostgreSQL backup execution and worker claims."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import pytest
from app.core.config import Settings, settings as application_settings
from app.db.base import SessionLocal
from app.db.models import AuditEvent, BackupRecord, DisasterRecoveryRun
from app.services.backup_executor import (
    BackupArtifact,
    BackupExecutionError,
    BackupExecutor,
    AsyncPostgresCommandRunner,
    RestoreValidation,
)
from app.services.backup_worker import BackupJobWorker
from sqlalchemy import BigInteger, delete


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        SECRET_KEY="unit-test-secret-key-with-at-least-32-characters",
        DATABASE_URL=(
            "postgresql+asyncpg://backup_user:db-password@database:5432/aionex"
        ),
        BACKUP_DIR=str(tmp_path / "protected-backups"),
        BACKUP_TIMEOUT_SECONDS=30,
        BACKUP_VALIDATION_TIMEOUT_SECONDS=30,
        BACKUP_CLEANUP_TIMEOUT_SECONDS=10,
        BACKUP_JOB_LEASE_SECONDS=180,
    )


class FakeRunner:
    def __init__(self, fail_operation: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_operation = fail_operation

    async def run(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str],
        timeout_seconds: int,
        operation: str,
    ) -> None:
        self.calls.append(
            {
                "command": list(command),
                "environment": dict(environment),
                "timeout": timeout_seconds,
                "operation": operation,
            }
        )
        if command[0] == "pg_dump":
            output_path = Path(command[command.index("--file") + 1])
            output_path.write_bytes(b"PGDMPunit-test-custom-archive")
        if operation == self.fail_operation:
            raise BackupExecutionError(operation, f"{operation} failed safely")


@pytest.mark.asyncio
async def test_backup_is_atomic_private_checksumming_and_secret_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "must-not-reach-subprocess")
    monkeypatch.setenv("SMTP_PASSWORD", "must-not-reach-subprocess")
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)

    artifact = await executor.create_backup("backup-record-1")

    path = Path(artifact.location)
    payload = path.read_bytes()
    assert payload.startswith(b"PGDMP")
    assert artifact.checksum == hashlib.sha256(payload).hexdigest()
    assert artifact.size_bytes == len(payload)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob("*.partial"))

    call = runner.calls[0]
    assert call["command"][0] == "pg_dump"
    assert "db-password" not in " ".join(call["command"])
    assert call["environment"]["PGPASSWORD"] == "db-password"
    assert "SECRET_KEY" not in call["environment"]
    assert "SMTP_PASSWORD" not in call["environment"]

    # Retrying a stale durable job reuses the already finalized immutable
    # artifact instead of creating a duplicate dump.
    repeated = await executor.create_backup("backup-record-1")
    assert repeated == artifact
    assert len(runner.calls) == 1


def test_artifact_probe_checks_live_path_size_and_checksum(tmp_path: Path) -> None:
    executor = BackupExecutor(_settings(tmp_path), FakeRunner())
    backup_dir = tmp_path / "protected-backups"
    backup_dir.mkdir(mode=0o700)
    artifact_path = backup_dir / "backup-probe.dump"
    payload = b"PGDMPartifact-integrity-probe"
    artifact_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()

    cheap_probe = executor.verify_artifact(
        str(artifact_path),
        checksum,
        len(payload),
        verify_checksum=False,
    )
    assert cheap_probe.size_bytes == len(payload)
    assert cheap_probe.checksum == checksum

    full_probe = executor.verify_artifact(
        str(artifact_path),
        checksum,
        len(payload),
    )
    assert full_probe.checksum == checksum

    with pytest.raises(BackupExecutionError, match="size"):
        executor.verify_artifact(
            str(artifact_path),
            checksum,
            len(payload) + 1,
            verify_checksum=False,
        )

    artifact_path.write_bytes(b"PGDMPartifact-integrity-pr0be")
    with pytest.raises(BackupExecutionError, match="checksum"):
        executor.verify_artifact(
            str(artifact_path),
            checksum,
            len(payload),
        )

    outside = tmp_path / "outside.dump"
    outside.write_bytes(payload)
    with pytest.raises(BackupExecutionError, match="protected backup"):
        executor.verify_artifact(str(outside), checksum, len(payload))


@pytest.mark.asyncio
async def test_restore_validation_uses_isolated_database_and_always_cleans_up(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)
    artifact = await executor.create_backup("backup-record-2")
    runner.calls.clear()

    validation = await executor.validate_restore(
        artifact.location,
        artifact.checksum,
        "restore-run-1",
    )

    assert validation.restored is True
    assert [call["command"][0] for call in runner.calls] == [
        "dropdb",
        "createdb",
        "pg_restore",
        "psql",
        "dropdb",
    ]
    scratch_names = [
        call["command"][-1]
        for call in runner.calls
        if call["command"][0] in {"dropdb", "createdb"}
    ]
    assert len(set(scratch_names)) == 1
    assert scratch_names[0].startswith("aionex_restore_")
    psql = next(
        call["command"] for call in runner.calls if call["command"][0] == "psql"
    )
    assert "ON_ERROR_STOP=1" in psql
    assert "RAISE EXCEPTION" in psql[-1]
    assert all("db-password" not in " ".join(call["command"]) for call in runner.calls)


@pytest.mark.asyncio
async def test_restore_failure_is_sanitized_and_scratch_database_is_removed(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)
    artifact = await executor.create_backup("backup-record-3")
    runner.calls.clear()
    runner.fail_operation = "PostgreSQL restore validation"

    with pytest.raises(BackupExecutionError) as failure:
        await executor.validate_restore(
            artifact.location,
            artifact.checksum,
            "restore-run-2",
        )

    assert failure.value.public_message == "PostgreSQL restore validation failed safely"
    assert [call["command"][0] for call in runner.calls][-1] == "dropdb"


@pytest.mark.asyncio
async def test_subprocess_is_terminated_when_worker_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CancellableProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.started = asyncio.Event()
            self.terminated = False
            self.communicate_calls = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                self.started.set()
                await asyncio.Event().wait()
            return b"", b""

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    process = CancellableProcess()

    async def create_process(*_args: object, **_kwargs: object) -> CancellableProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    task = asyncio.create_task(
        AsyncPostgresCommandRunner().run(
            ["pg_dump", "--version"],
            environment={},
            timeout_seconds=30,
            operation="PostgreSQL backup",
        )
    )
    await process.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.terminated is True
    assert process.communicate_calls == 2


class FakeSession:
    def __init__(self, scalar_results: list[Any]) -> None:
        self.scalar_results = scalar_results
        self.added: list[Any] = []
        self.commits = 0
        self.statement: Any = None

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(self, statement: Any) -> Any:
        self.statement = statement
        return self.scalar_results.pop(0)

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


class FakeSessionFactory:
    def __init__(self, sessions: list[FakeSession]) -> None:
        self.sessions = sessions

    def __call__(self) -> FakeSession:
        return self.sessions.pop(0)


class FakeExecutor:
    async def create_backup(self, backup_id: str) -> BackupArtifact:
        assert backup_id == "backup-job-1"
        return BackupArtifact(
            location="/protected/backup.dump",
            checksum="a" * 64,
            size_bytes=128,
        )


@pytest.mark.asyncio
async def test_worker_atomically_claims_and_completes_backup() -> None:
    record = BackupRecord(
        id="backup-job-1",
        kind="on-demand",
        scope="platform",
        status="pending",
    )
    claim_session = FakeSession([record])
    finish_session = FakeSession([record])
    worker = BackupJobWorker(
        executor=FakeExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [claim_session, finish_session]
        ),
    )

    claimed = await worker.claim_backup()
    assert claimed == record.id
    assert record.status == "running"
    assert claim_session.commits == 1
    assert claim_session.statement._for_update_arg.skip_locked is True

    await worker.execute_backup(record.id)
    assert record.status == "completed"
    assert record.location == "/protected/backup.dump"
    assert record.checksum == "a" * 64
    assert record.size_bytes == 128
    assert record.completed_at is not None
    assert finish_session.commits == 1
    assert any(
        isinstance(item, AuditEvent) and item.action == "backup.worker.completed"
        for item in finish_session.added
    )


class FailingExecutor:
    async def create_backup(self, _backup_id: str) -> BackupArtifact:
        raise BackupExecutionError(
            "PostgreSQL backup",
            "PostgreSQL backup failed with PostgreSQL client exit code 1",
        )


@pytest.mark.asyncio
async def test_worker_persists_sanitized_backup_failure() -> None:
    record = BackupRecord(
        id="backup-job-2",
        kind="on-demand",
        scope="platform",
        status="running",
    )
    failure_session = FakeSession([record])
    worker = BackupJobWorker(
        executor=FailingExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([failure_session]),  # type: ignore[arg-type]
    )

    await worker.execute_backup(record.id)

    assert record.status == "failed"
    assert record.completed_at is not None
    failure_audit = next(
        item for item in failure_session.added if isinstance(item, AuditEvent)
    )
    assert failure_audit.action == "backup.worker.failed"
    assert "db-password" not in str(failure_audit.details)


class UnexpectedFailingExecutor:
    async def create_backup(self, _backup_id: str) -> BackupArtifact:
        raise RuntimeError("postgresql://user:plaintext-secret@database/aionex")


@pytest.mark.asyncio
async def test_worker_sanitizes_unexpected_executor_failure() -> None:
    record = BackupRecord(
        id="backup-job-3",
        kind="on-demand",
        scope="platform",
        status="running",
    )
    failure_session = FakeSession([record])
    worker = BackupJobWorker(
        executor=UnexpectedFailingExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([failure_session]),  # type: ignore[arg-type]
    )

    await worker.execute_backup(record.id)

    assert record.status == "failed"
    failure_audit = next(
        item for item in failure_session.added if isinstance(item, AuditEvent)
    )
    assert failure_audit.details["reason"] == "PostgreSQL backup failed unexpectedly"
    assert "plaintext-secret" not in str(failure_audit.details)


class RestoreExecutor:
    async def validate_restore(
        self,
        location: str,
        checksum: str,
        validation_id: str,
        *,
        expected_size_bytes: int | None = None,
    ) -> RestoreValidation:
        assert location == "/protected/restore.dump"
        assert checksum == "b" * 64
        assert validation_id == "restore-job-1"
        assert expected_size_bytes == 512
        return RestoreValidation(
            checksum=checksum,
            size_bytes=512,
        )


@pytest.mark.asyncio
async def test_worker_claims_dr_drill_and_persists_completed_restore_evidence() -> None:
    backup = BackupRecord(
        id="protected-backup-1",
        kind="on-demand",
        scope="platform",
        status="completed",
        location="/protected/restore.dump",
        checksum="b" * 64,
        size_bytes=512,
    )
    run = DisasterRecoveryRun(
        id="restore-job-1",
        operation="test",
        status="pending",
        details={"backup_id": backup.id, "requested_by": "owner-1"},
    )
    claim_session = FakeSession([run])
    load_session = FakeSession([run, backup])
    finish_session = FakeSession([run])
    worker = BackupJobWorker(
        executor=RestoreExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [claim_session, load_session, finish_session]
        ),
    )

    claimed = await worker.claim_restore_validation()
    assert claimed == run.id
    assert run.status == "running"
    assert claim_session.statement._for_update_arg.skip_locked is True

    await worker.execute_restore_validation(run.id)

    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.details["backup_id"] == backup.id
    assert run.details["validated"] is True
    assert run.details["checksum"] == backup.checksum
    assert run.details["size_bytes"] == 512
    completed_audit = next(
        item for item in finish_session.added if isinstance(item, AuditEvent)
    )
    assert completed_audit.action == "dr.worker.completed"
    assert completed_audit.details["operation"] == "test"
    assert completed_audit.details["backup_id"] == backup.id


class RestoreFailingExecutor:
    async def validate_restore(
        self,
        _location: str,
        _checksum: str,
        _validation_id: str,
        *,
        expected_size_bytes: int | None = None,
    ) -> RestoreValidation:
        assert expected_size_bytes == 512
        raise BackupExecutionError(
            "PostgreSQL restore validation",
            "PostgreSQL restore validation failed with PostgreSQL client exit code 1",
        )


@pytest.mark.asyncio
async def test_worker_persists_failed_restore_validation_evidence() -> None:
    backup = BackupRecord(
        id="protected-backup-2",
        kind="on-demand",
        scope="platform",
        status="completed",
        location="/protected/restore.dump",
        checksum="b" * 64,
        size_bytes=512,
    )
    run = DisasterRecoveryRun(
        id="restore-job-2",
        operation="restore_validation",
        status="running",
        details={"backup_id": backup.id, "requested_by": "owner-1"},
    )
    load_session = FakeSession([run, backup])
    failure_session = FakeSession([run])
    worker = BackupJobWorker(
        executor=RestoreFailingExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [load_session, failure_session]
        ),
    )

    await worker.execute_restore_validation(run.id)

    assert run.status == "failed"
    assert run.completed_at is not None
    assert run.details["validated"] is False
    assert run.details["backup_id"] == backup.id
    failure_audit = next(
        item for item in failure_session.added if isinstance(item, AuditEvent)
    )
    assert failure_audit.action == "dr.worker.failed"
    assert failure_audit.details["backup_id"] == backup.id


class PreflightExecutor:
    def __init__(self) -> None:
        self.storage_verified = False
        self.heartbeat_verified = False

    def verify_storage(self) -> None:
        self.storage_verified = True

    def verify_heartbeat(self) -> None:
        self.heartbeat_verified = True


@pytest.mark.asyncio
async def test_worker_preflight_checks_schema_storage_heartbeat_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class VersionProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"pg_dump (PostgreSQL) 17.10\n", b""

        def kill(self) -> None:
            return None

    async def create_process(*_args: object, **_kwargs: object) -> VersionProcess:
        return VersionProcess()

    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    executor = PreflightExecutor()
    preflight_session = FakeSession([160010, True])
    worker = BackupJobWorker(
        executor=executor,  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([preflight_session]),  # type: ignore[arg-type]
    )

    await worker.preflight(require_heartbeat=True)

    assert executor.storage_verified is True
    assert executor.heartbeat_verified is True


@pytest.mark.asyncio
async def test_worker_preflight_rejects_older_pg_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class VersionProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"pg_dump (PostgreSQL) 15.13\n", b""

        def kill(self) -> None:
            return None

    async def create_process(*_args: object, **_kwargs: object) -> VersionProcess:
        return VersionProcess()

    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    worker = BackupJobWorker(
        executor=PreflightExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [FakeSession([160010, True])]
        ),
    )

    with pytest.raises(RuntimeError, match="older than"):
        await worker.preflight()


def test_production_images_and_stacks_ship_the_backup_worker_once() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    web_root = backend_root.parent
    repository_root = web_root.parent
    dockerfile = (backend_root / "Dockerfile").read_text(encoding="utf-8")
    primary_compose = (web_root / "docker-compose.production.yml").read_text(
        encoding="utf-8"
    )
    deploy_compose = (
        repository_root / "deploy/production/docker-compose.production.yml"
    ).read_text(encoding="utf-8")

    assert "FROM python:3.11-slim-trixie" in dockerfile
    assert "postgresql-client-17" in dockerfile
    assert "install -d -m 0700 -o aionex -g aionex" in dockerfile
    for compose in (primary_compose, deploy_compose):
        assert "backup-worker:" in compose
        assert compose.count("image: aionex-aios-backend:local") == 2
        assert "backup_data:/var/lib/aionex/backups" in compose
        assert 'command: ["python", "-m", "app.services.backup_worker"]' in compose
        assert (
            'test: ["CMD", "python", "-m", "app.services.backup_worker", '
            '"--healthcheck"]' in compose
        )


def test_backup_size_schema_supports_archives_larger_than_two_gibibytes() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    migration = (
        backend_root / "alembic/versions/20260729_0003_owner_runtime_safety.py"
    ).read_text(encoding="utf-8")

    assert isinstance(BackupRecord.__table__.c.size_bytes.type, BigInteger)
    assert '"backup_records",\n                "size_bytes"' in migration
    assert "type_=sa.BigInteger()" in migration
    assert "2_147_483_647" in migration


@pytest.mark.asyncio
async def test_live_postgres_worker_backup_and_restore_smoke() -> None:
    if os.getenv("RUN_LIVE_BACKUP_SMOKE") != "1":
        pytest.skip("Live PostgreSQL backup smoke is enabled only in CI")

    suffix = uuid4().hex
    backup_id = f"bkp-{suffix}"
    backup = BackupRecord(
        id=backup_id,
        kind="ci-smoke",
        scope=f"ci-smoke-{suffix}",
        status="pending",
    )
    async with SessionLocal() as session:
        session.add(backup)
        await session.commit()

    worker = BackupJobWorker(
        executor=BackupExecutor(application_settings),
        session_factory=SessionLocal,
    )
    artifact_path: Path | None = None
    run_id = f"rst-{suffix}"
    try:
        assert await worker.claim_backup() == backup.id
        assert await worker.claim_backup() is None
        await worker.execute_backup(backup.id)
        async with SessionLocal() as session:
            completed_backup = await session.get(BackupRecord, backup.id)
            assert completed_backup is not None
            assert completed_backup.status == "completed"
            assert completed_backup.location
            assert completed_backup.checksum
            assert completed_backup.size_bytes and completed_backup.size_bytes > 0
            artifact_path = Path(completed_backup.location)
            session.add(
                DisasterRecoveryRun(
                    id=run_id,
                    operation="restore_validation",
                    status="pending",
                    details={"backup_id": backup.id, "requested_by": "ci-smoke"},
                )
            )
            await session.commit()

        assert await worker.claim_restore_validation() == run_id
        assert await worker.claim_restore_validation() is None
        await worker.execute_restore_validation(run_id)
        async with SessionLocal() as session:
            completed_run = await session.get(DisasterRecoveryRun, run_id)
            assert completed_run is not None
            assert completed_run.status == "completed"
            assert completed_run.details["validated"] is True
            assert completed_run.details["backup_id"] == backup.id
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(AuditEvent).where(
                    AuditEvent.resource_id.in_({backup.id, run_id})
                )
            )
            await session.execute(
                delete(DisasterRecoveryRun).where(DisasterRecoveryRun.id == run_id)
            )
            await session.execute(
                delete(BackupRecord).where(BackupRecord.id == backup.id)
            )
            await session.commit()
        if artifact_path is not None:
            artifact_path.unlink(missing_ok=True)
