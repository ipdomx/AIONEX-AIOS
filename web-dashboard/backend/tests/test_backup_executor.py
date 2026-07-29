"""Unit contracts for durable PostgreSQL backup execution and worker claims."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import time
from datetime import UTC, datetime, timedelta
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
    is_managed_restore_database_name,
    restore_scratch_database_name,
)
from app.services.backup_worker import (
    BackupJobWorker,
    ClaimedJob,
    LeaseLostError,
    RESTORE_SCRATCH_DATABASES_KEY,
    retention_candidate_ids,
)
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

    artifact = await executor.create_backup("backup-record-1", "attempt-1")

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

    # Retrying the same lease reuses only that lease's immutable artifact.
    repeated = await executor.create_backup("backup-record-1", "attempt-1")
    assert repeated == artifact
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_reclaimed_attempt_cannot_overwrite_prior_attempt_artifact(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)

    first = await executor.create_backup("shared-backup", "lease-one")
    first_payload = Path(first.location).read_bytes()
    second = await executor.create_backup("shared-backup", "lease-two")

    assert first.location != second.location
    assert Path(first.location).read_bytes() == first_payload
    assert Path(second.location).is_file()
    assert len(runner.calls) == 2


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


def test_read_only_artifact_probe_never_mutates_the_backup_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = BackupExecutor(_settings(tmp_path), FakeRunner())
    backup_dir = tmp_path / "protected-backups"
    backup_dir.mkdir(mode=0o700)
    artifact_path = backup_dir / "backup-read-only.dump"
    payload = b"PGDMPread-only-artifact"
    artifact_path.write_bytes(payload)

    def writable_probe() -> Path:
        raise AssertionError("read-only verification requested write access")

    monkeypatch.setattr(executor, "_secure_backup_directory", writable_probe)
    verified = executor.verify_artifact(
        str(artifact_path),
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )

    assert verified.location == str(artifact_path)


def test_stale_partial_cleanup_is_lease_bounded_and_symlink_safe(
    tmp_path: Path,
) -> None:
    executor = BackupExecutor(_settings(tmp_path), FakeRunner())
    backup_dir = tmp_path / "protected-backups"
    backup_dir.mkdir(mode=0o700)
    stale = backup_dir / ".backup-stale.partial"
    fresh = backup_dir / ".backup-fresh.partial"
    unrelated = backup_dir / "keep-me.partial"
    target = backup_dir / "target.dump"
    stale.write_bytes(b"partial")
    fresh.write_bytes(b"partial")
    unrelated.write_bytes(b"partial")
    target.write_bytes(b"PGDMPprotected")
    symlink = backup_dir / ".backup-symlink.partial"
    symlink.symlink_to(target)
    old = time.time() - 3600
    os.utime(stale, (old, old))
    os.utime(symlink, (old, old), follow_symlinks=False)

    assert executor.cleanup_stale_partials(600) == 1
    assert not stale.exists()
    assert fresh.exists()
    assert unrelated.exists()
    assert symlink.is_symlink()
    assert target.exists()


@pytest.mark.asyncio
async def test_reclaimed_backup_removes_only_its_abandoned_partial(
    tmp_path: Path,
) -> None:
    backup_id = "reclaimed-backup-job"
    executor = BackupExecutor(_settings(tmp_path), FakeRunner())
    backup_dir = tmp_path / "protected-backups"
    backup_dir.mkdir(mode=0o700)
    stable_name = hashlib.sha256(backup_id.encode("utf-8")).hexdigest()[:24]
    abandoned = backup_dir / f".backup-{stable_name}-abandoned.partial"
    unrelated = backup_dir / ".backup-unrelated-abandoned.partial"
    abandoned.write_bytes(b"abandoned dump")
    unrelated.write_bytes(b"unrelated dump")

    assert executor.cleanup_backup_partials(backup_id) == 1
    artifact = await executor.create_backup(backup_id, "reclaimed-attempt")

    assert not abandoned.exists()
    assert unrelated.exists()
    assert Path(artifact.location).is_file()


def test_orphan_cleanup_waits_for_lease_and_preserves_referenced_artifacts(
    tmp_path: Path,
) -> None:
    executor = BackupExecutor(_settings(tmp_path), FakeRunner())
    backup_dir = tmp_path / "protected-backups"
    backup_dir.mkdir(mode=0o700)
    referenced = backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump"
    orphan = backup_dir / f"backup-{'c' * 24}-{'d' * 32}.dump"
    fresh = backup_dir / f"backup-{'e' * 24}-{'f' * 32}.dump"
    active_backup_id = "active-backup-job"
    active_attempt_token = "active-attempt-token"
    active = backup_dir / (
        "backup-"
        f"{hashlib.sha256(active_backup_id.encode()).hexdigest()[:24]}-"
        f"{hashlib.sha256(active_attempt_token.encode()).hexdigest()[:32]}.dump"
    )
    for artifact in (referenced, orphan, fresh, active):
        artifact.write_bytes(b"PGDMPartifact")
    old = time.time() - 3600
    os.utime(referenced, (old, old))
    os.utime(orphan, (old, old))
    os.utime(active, (old, old))

    assert (
        executor.cleanup_orphan_artifacts(
            {str(referenced)},
            600,
            {(active_backup_id, active_attempt_token)},
        )
        == 1
    )
    assert referenced.exists()
    assert not orphan.exists()
    assert fresh.exists()
    assert active.exists()


def test_retention_rejects_symlink_without_deleting_its_target(
    tmp_path: Path,
) -> None:
    executor = BackupExecutor(_settings(tmp_path), FakeRunner())
    backup_dir = tmp_path / "protected-backups"
    backup_dir.mkdir(mode=0o700)
    target = backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump"
    symlink = backup_dir / f"backup-{'c' * 24}-{'d' * 32}.dump"
    target.write_bytes(b"PGDMPprotected-target")
    symlink.symlink_to(target)

    with pytest.raises(BackupExecutionError, match="could not be removed safely"):
        executor.delete_artifact(str(symlink))

    assert symlink.is_symlink()
    assert target.read_bytes() == b"PGDMPprotected-target"


@pytest.mark.asyncio
async def test_restore_validation_uses_isolated_database_and_always_cleans_up(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)
    artifact = await executor.create_backup("backup-record-2", "attempt-2")
    runner.calls.clear()

    validation = await executor.validate_restore(
        artifact.location,
        artifact.checksum,
        "restore-run-1",
        "restore-attempt-1",
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
async def test_reclaimed_restore_attempt_uses_a_distinct_scratch_database(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)
    artifact = await executor.create_backup("backup-record-fenced", "backup-attempt")
    runner.calls.clear()

    await executor.validate_restore(
        artifact.location,
        artifact.checksum,
        "shared-restore-run",
        "stale-lease-token",
    )
    stale_scratch_database = next(
        call["command"][-1] for call in runner.calls if call["command"][0] == "createdb"
    )
    runner.calls.clear()

    await executor.validate_restore(
        artifact.location,
        artifact.checksum,
        "shared-restore-run",
        "winning-lease-token",
        stale_scratch_databases=(stale_scratch_database,),
    )
    winning_scratch_database = next(
        call["command"][-1] for call in runner.calls if call["command"][0] == "createdb"
    )

    assert stale_scratch_database != winning_scratch_database
    assert runner.calls[0]["command"][0] == "dropdb"
    assert runner.calls[0]["command"][-1] == stale_scratch_database


@pytest.mark.asyncio
async def test_restore_cleanup_rejects_non_worker_database_before_deletion(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)

    with pytest.raises(BackupExecutionError, match="not worker-managed"):
        await executor.validate_restore(
            str(tmp_path / "missing.dump"),
            "a" * 64,
            "restore-run-unmanaged",
            "restore-attempt-unmanaged",
            stale_scratch_databases=("postgres",),
        )

    assert runner.calls == []


@pytest.mark.asyncio
async def test_stale_restore_database_is_cleaned_before_artifact_validation(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)
    (tmp_path / "protected-backups").mkdir(mode=0o700)
    stale_database = restore_scratch_database_name(
        "restore-run-stale",
        "stale-attempt",
    )

    with pytest.raises(BackupExecutionError, match="backup artifact"):
        await executor.validate_restore(
            str(tmp_path / "missing.dump"),
            "a" * 64,
            "restore-run-stale",
            "winning-attempt",
            stale_scratch_databases=(stale_database,),
        )

    assert [call["command"][0] for call in runner.calls] == ["dropdb"]
    assert runner.calls[0]["command"][-1] == stale_database


@pytest.mark.asyncio
async def test_restore_failure_is_sanitized_and_scratch_database_is_removed(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = BackupExecutor(_settings(tmp_path), runner)
    artifact = await executor.create_backup("backup-record-3", "attempt-3")
    runner.calls.clear()
    runner.fail_operation = "PostgreSQL restore validation"

    with pytest.raises(BackupExecutionError) as failure:
        await executor.validate_restore(
            artifact.location,
            artifact.checksum,
            "restore-run-2",
            "restore-attempt-2",
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
    async def create_backup(
        self,
        backup_id: str,
        _attempt_token: str,
    ) -> BackupArtifact:
        assert backup_id == "backup-job-1"
        return BackupArtifact(
            location="/protected/backup.dump",
            checksum="a" * 64,
            size_bytes=128,
        )


@pytest.mark.asyncio
async def test_worker_atomically_claims_and_completes_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    async def skip_capacity(_backup_id: str) -> None:
        return None

    async def skip_retention(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(worker, "_ensure_capacity", skip_capacity)
    monkeypatch.setattr(worker, "_apply_retention", skip_retention)

    claimed = await worker.claim_backup()
    assert claimed is not None
    assert claimed.id == record.id
    assert claimed.lease_token == record.lease_token
    assert claimed.reclaimed is False
    assert record.status == "running"
    assert claim_session.commits == 1
    assert claim_session.statement._for_update_arg.skip_locked is True

    await worker.execute_backup(claimed)
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
    async def create_backup(
        self,
        _backup_id: str,
        _attempt_token: str,
    ) -> BackupArtifact:
        raise BackupExecutionError(
            "PostgreSQL backup",
            "PostgreSQL backup failed with PostgreSQL client exit code 1",
        )


@pytest.mark.asyncio
async def test_worker_persists_sanitized_backup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = BackupRecord(
        id="backup-job-2",
        kind="on-demand",
        scope="platform",
        status="running",
        lease_token="failure-lease",
    )
    failure_session = FakeSession([record])
    worker = BackupJobWorker(
        executor=FailingExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([failure_session]),  # type: ignore[arg-type]
    )

    async def skip_capacity(_backup_id: str) -> None:
        return None

    monkeypatch.setattr(worker, "_ensure_capacity", skip_capacity)

    await worker.execute_backup(ClaimedJob(record.id, "failure-lease", reclaimed=False))

    assert record.status == "failed"
    assert record.completed_at is not None
    failure_audit = next(
        item for item in failure_session.added if isinstance(item, AuditEvent)
    )
    assert failure_audit.action == "backup.worker.failed"
    assert "db-password" not in str(failure_audit.details)


class UnexpectedFailingExecutor:
    async def create_backup(
        self,
        _backup_id: str,
        _attempt_token: str,
    ) -> BackupArtifact:
        raise RuntimeError("postgresql://user:plaintext-secret@database/aionex")


@pytest.mark.asyncio
async def test_worker_sanitizes_unexpected_executor_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = BackupRecord(
        id="backup-job-3",
        kind="on-demand",
        scope="platform",
        status="running",
        lease_token="unexpected-lease",
    )
    failure_session = FakeSession([record])
    worker = BackupJobWorker(
        executor=UnexpectedFailingExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([failure_session]),  # type: ignore[arg-type]
    )

    async def skip_capacity(_backup_id: str) -> None:
        return None

    monkeypatch.setattr(worker, "_ensure_capacity", skip_capacity)

    await worker.execute_backup(
        ClaimedJob(record.id, "unexpected-lease", reclaimed=False)
    )

    assert record.status == "failed"
    failure_audit = next(
        item for item in failure_session.added if isinstance(item, AuditEvent)
    )
    assert failure_audit.details["reason"] == "PostgreSQL backup failed unexpectedly"
    assert "plaintext-secret" not in str(failure_audit.details)


@pytest.mark.asyncio
async def test_expired_lease_gets_new_token_and_is_marked_reclaimed() -> None:
    old_token = str(uuid4())
    record = BackupRecord(
        id="stale-backup",
        kind="scheduled",
        scope="platform",
        status="running",
        lease_token=old_token,
        updated_at=datetime.now(UTC) - timedelta(hours=2),
    )
    session = FakeSession([record])
    worker = BackupJobWorker(
        executor=FakeExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([session]),  # type: ignore[arg-type]
    )

    claim = await worker.claim_backup()

    assert claim is not None
    assert claim.reclaimed is True
    assert claim.lease_token != old_token
    assert record.lease_token == claim.lease_token


@pytest.mark.asyncio
async def test_repeated_restore_reclaims_persist_all_attempt_database_names() -> None:
    run = DisasterRecoveryRun(
        id="restore-reclaim-chain",
        operation="restore_validation",
        status="pending",
        details={"backup_id": "protected-backup"},
    )
    worker = BackupJobWorker(
        executor=FakeExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [FakeSession([run]), FakeSession([run]), FakeSession([run])]
        ),
    )
    claims = []

    for _ in range(3):
        claim = await worker.claim_restore_validation()
        assert claim is not None
        claims.append(claim)

    expected_databases = [
        restore_scratch_database_name(run.id, claim.lease_token) for claim in claims
    ]
    assert claims[0].reclaimed is False
    assert claims[0].stale_scratch_databases == ()
    assert claims[1].reclaimed is True
    assert claims[1].stale_scratch_databases == tuple(expected_databases[:1])
    assert claims[2].stale_scratch_databases == tuple(expected_databases[:2])
    assert run.details[RESTORE_SCRATCH_DATABASES_KEY] == expected_databases
    assert all(
        is_managed_restore_database_name(database_name)
        for database_name in expected_databases
    )
    persisted_details = str(run.details)
    assert all(claim.lease_token not in persisted_details for claim in claims)


@pytest.mark.asyncio
async def test_lease_heartbeat_is_fenced_by_current_token() -> None:
    record = BackupRecord(
        id="heartbeat-backup",
        kind="scheduled",
        scope="platform",
        status="running",
        lease_token="current-token",
        updated_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    renewed = FakeSession([record])
    lost = FakeSession([None])
    worker = BackupJobWorker(
        executor=FakeExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([renewed, lost]),  # type: ignore[arg-type]
    )
    claim = ClaimedJob(record.id, "current-token", reclaimed=False)
    previous = record.updated_at

    await worker._renew_lease(BackupRecord, claim)

    assert record.updated_at > previous
    assert renewed.commits == 1
    with pytest.raises(LeaseLostError):
        await worker._renew_lease(
            BackupRecord,
            ClaimedJob(record.id, "stale-token", reclaimed=True),
        )


@pytest.mark.asyncio
async def test_stale_worker_cannot_publish_or_overwrite_winning_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LateExecutor:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def create_backup(
            self,
            backup_id: str,
            attempt_token: str,
        ) -> BackupArtifact:
            assert backup_id == "fenced-backup"
            assert attempt_token == "stale-token"
            return BackupArtifact(
                location="/protected/stale-attempt.dump",
                checksum="c" * 64,
                size_bytes=256,
            )

        def delete_artifact(self, location: str) -> bool:
            self.deleted.append(location)
            return True

    executor = LateExecutor()
    finish_session = FakeSession([None])
    worker = BackupJobWorker(
        executor=executor,  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([finish_session]),  # type: ignore[arg-type]
    )

    async def skip_capacity(_backup_id: str) -> None:
        return None

    monkeypatch.setattr(worker, "_ensure_capacity", skip_capacity)
    await worker.execute_backup(
        ClaimedJob("fenced-backup", "stale-token", reclaimed=False)
    )

    assert finish_session.commits == 0
    assert executor.deleted == ["/protected/stale-attempt.dump"]


@pytest.mark.asyncio
async def test_low_capacity_blocks_pg_dump_after_safe_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CapacityExecutor:
        def __init__(self) -> None:
            self.dump_started = False

        def available_bytes(self) -> int:
            return 0

        async def create_backup(
            self,
            _backup_id: str,
            _attempt_token: str,
        ) -> BackupArtifact:
            self.dump_started = True
            raise AssertionError("pg_dump must not start without safe capacity")

    record = BackupRecord(
        id="capacity-backup",
        kind="scheduled",
        scope="platform",
        status="running",
        lease_token="capacity-token",
    )
    failure_session = FakeSession([record])
    executor = CapacityExecutor()
    worker = BackupJobWorker(
        executor=executor,  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([failure_session]),  # type: ignore[arg-type]
    )

    async def skip_retention(**_kwargs: object) -> None:
        return None

    async def database_size() -> int:
        return 1

    monkeypatch.setattr(worker, "_apply_retention", skip_retention)
    monkeypatch.setattr(worker, "_database_size_bytes", database_size)
    await worker.execute_backup(
        ClaimedJob(record.id, "capacity-token", reclaimed=False)
    )

    assert executor.dump_started is False
    assert record.status == "failed"


def test_retention_protects_scope_latest_active_dr_and_latest_validation() -> None:
    now = datetime.now(UTC)

    def backup(
        backup_id: str,
        scope: str,
        age_days: int,
    ) -> BackupRecord:
        completed_at = now - timedelta(days=age_days)
        return BackupRecord(
            id=backup_id,
            kind="scheduled",
            scope=scope,
            status="completed",
            location=f"/protected/{backup_id}.dump",
            checksum="d" * 64,
            size_bytes=128,
            completed_at=completed_at,
            created_at=completed_at,
        )

    backups = [
        backup("platform-latest", "platform", 1),
        backup("active-dr", "platform", 40),
        backup("validated-evidence", "platform", 50),
        backup("safe-old", "platform", 60),
        backup("regional-latest", "regional", 90),
    ]
    runs = [
        DisasterRecoveryRun(
            id="pending-dr",
            operation="test",
            status="pending",
            details={"backup_id": "active-dr"},
            created_at=now,
        ),
        DisasterRecoveryRun(
            id="validated-dr",
            operation="test",
            status="completed",
            details={"backup_id": "validated-evidence", "validated": True},
            completed_at=now,
            created_at=now,
        ),
    ]

    assert retention_candidate_ids(
        backups,
        runs,
        now=now,
        keep_count=2,
        keep_days=30,
    ) == ["safe-old"]
    assert retention_candidate_ids(
        backups,
        runs,
        now=now,
        keep_count=2,
        keep_days=30,
        pressure=True,
    ) == ["safe-old"]


@pytest.mark.asyncio
async def test_expiration_deletes_only_artifact_and_keeps_audit_metadata() -> None:
    class RetentionExecutor:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_artifact(self, location: str) -> bool:
            self.deleted.append(location)
            return True

    completed_at = datetime.now(UTC) - timedelta(days=45)
    record = BackupRecord(
        id="expired-backup",
        kind="scheduled",
        scope="platform",
        status="completed",
        location="/protected/expired.dump",
        checksum="e" * 64,
        size_bytes=4096,
        completed_at=completed_at,
    )
    expire_session = FakeSession([record, None])
    delete_session = FakeSession([record])
    executor = RetentionExecutor()
    worker = BackupJobWorker(
        executor=executor,  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [expire_session, delete_session]
        ),
    )

    await worker._delete_expired_artifact(record.id, reason="retention policy")

    assert record.status == "expired"
    assert record.location is None
    assert record.checksum == "e" * 64
    assert record.size_bytes == 4096
    assert record.completed_at == completed_at
    assert executor.deleted == ["/protected/expired.dump"]


@pytest.mark.asyncio
async def test_expiration_rechecks_active_recovery_reference_before_delete() -> None:
    class RetentionExecutor:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_artifact(self, location: str) -> bool:
            self.deleted.append(location)
            return True

    record = BackupRecord(
        id="active-recovery-backup",
        kind="scheduled",
        scope="platform",
        status="completed",
        location="/protected/active-recovery.dump",
        checksum="f" * 64,
        size_bytes=2048,
        completed_at=datetime.now(UTC) - timedelta(days=45),
    )
    session = FakeSession([record, "active-recovery-run"])
    executor = RetentionExecutor()
    worker = BackupJobWorker(
        executor=executor,  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([session]),  # type: ignore[arg-type]
    )

    await worker._delete_expired_artifact(record.id, reason="retention policy")

    assert record.status == "completed"
    assert record.location == "/protected/active-recovery.dump"
    assert session.commits == 0
    assert executor.deleted == []


@pytest.mark.asyncio
async def test_post_backup_retention_runs_after_the_lease_heartbeat_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = ClaimedJob("backup-job", "lease-token", reclaimed=False)
    worker = BackupJobWorker(
        executor=FakeExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([]),  # type: ignore[arg-type]
    )
    events: list[str] = []

    async def claim_backup() -> ClaimedJob:
        return claim

    async def run_with_heartbeat(
        _model: object,
        received_claim: ClaimedJob,
        _operation: object,
    ) -> None:
        assert received_claim == claim
        events.append("heartbeat-stopped")

    async def apply_retention(**_kwargs: object) -> None:
        events.append("retention")

    monkeypatch.setattr(worker, "claim_backup", claim_backup)
    monkeypatch.setattr(worker, "_run_with_heartbeat", run_with_heartbeat)
    monkeypatch.setattr(worker, "_apply_retention", apply_retention)

    assert await worker.run_once() is True
    assert events == ["heartbeat-stopped", "retention"]


class RestoreExecutor:
    def __init__(self) -> None:
        self.attempt_token: str | None = None

    async def validate_restore(
        self,
        location: str,
        checksum: str,
        validation_id: str,
        attempt_token: str,
        *,
        stale_scratch_databases: Sequence[str] = (),
        expected_size_bytes: int | None = None,
    ) -> RestoreValidation:
        assert location == "/protected/restore.dump"
        assert checksum == "b" * 64
        assert validation_id == "restore-job-1"
        self.attempt_token = attempt_token
        assert stale_scratch_databases == ()
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
    executor = RestoreExecutor()
    worker = BackupJobWorker(
        executor=executor,  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [claim_session, load_session, finish_session]
        ),
    )

    claimed = await worker.claim_restore_validation()
    assert claimed is not None
    assert claimed.id == run.id
    assert claimed.lease_token == run.lease_token
    assert run.status == "running"
    assert claim_session.statement._for_update_arg.skip_locked is True

    await worker.execute_restore_validation(claimed)

    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.details["backup_id"] == backup.id
    assert run.details["validated"] is True
    assert run.details["checksum"] == backup.checksum
    assert run.details["size_bytes"] == 512
    assert RESTORE_SCRATCH_DATABASES_KEY not in run.details
    assert executor.attempt_token == claimed.lease_token
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
        _attempt_token: str,
        *,
        stale_scratch_databases: Sequence[str] = (),
        expected_size_bytes: int | None = None,
    ) -> RestoreValidation:
        assert stale_scratch_databases == ()
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
        lease_token="restore-failure-lease",
    )
    load_session = FakeSession([run, backup])
    failure_session = FakeSession([run])
    worker = BackupJobWorker(
        executor=RestoreFailingExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory(  # type: ignore[arg-type]
            [load_session, failure_session]
        ),
    )

    await worker.execute_restore_validation(
        ClaimedJob(run.id, "restore-failure-lease", reclaimed=False)
    )

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
        self.partials_cleaned_with: int | None = None

    def verify_storage(self) -> None:
        self.storage_verified = True

    def verify_heartbeat(self) -> None:
        self.heartbeat_verified = True

    def cleanup_stale_partials(self, maximum_age_seconds: int) -> int:
        self.partials_cleaned_with = maximum_age_seconds
        return 0


@pytest.mark.asyncio
async def test_worker_preflight_checks_schema_storage_heartbeat_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class VersionProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"pg_dump (PostgreSQL) 16.10\n", b""

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
    assert executor.partials_cleaned_with is None


@pytest.mark.asyncio
@pytest.mark.parametrize("client_major", [15, 17])
async def test_worker_preflight_rejects_mismatched_pg_dump(
    monkeypatch: pytest.MonkeyPatch,
    client_major: int,
) -> None:
    class VersionProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return f"pg_dump (PostgreSQL) {client_major}.13\n".encode(), b""

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

    with pytest.raises(RuntimeError, match="major versions must match"):
        await worker.preflight()


@pytest.mark.asyncio
async def test_worker_startup_cleans_only_partials_older_than_the_job_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class VersionProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"pg_dump (PostgreSQL) 16.10\n", b""

        def kill(self) -> None:
            return None

    async def create_process(*_args: object, **_kwargs: object) -> VersionProcess:
        return VersionProcess()

    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    executor = PreflightExecutor()
    worker = BackupJobWorker(
        executor=executor,  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([FakeSession([160010, True])]),  # type: ignore[arg-type]
    )

    await worker.preflight()

    assert (
        executor.partials_cleaned_with == application_settings.BACKUP_JOB_LEASE_SECONDS
    )
    assert executor.heartbeat_verified is False


@pytest.mark.asyncio
async def test_worker_shutdown_drains_an_inflight_job_before_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = BackupJobWorker(
        executor=PreflightExecutor(),  # type: ignore[arg-type]
        session_factory=FakeSessionFactory([]),  # type: ignore[arg-type]
    )
    stop_event = asyncio.Event()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def preflight(*, require_heartbeat: bool = False) -> None:
        assert require_heartbeat is False

    async def heartbeat(event: asyncio.Event) -> None:
        await event.wait()

    async def run_once() -> bool:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(worker, "preflight", preflight)
    monkeypatch.setattr(worker, "_heartbeat_forever", heartbeat)
    monkeypatch.setattr(worker, "run_once", run_once)
    task = asyncio.create_task(worker.run_forever(stop_event))
    await started.wait()

    stop_event.set()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    await task

    assert calls == 1


def test_production_images_ship_worker_and_credential_gate_once() -> None:
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
    validation_workflow = (
        repository_root / ".github/workflows/final-validation.yml"
    ).read_text(encoding="utf-8")

    assert "FROM python:3.11-slim-bookworm" in dockerfile
    assert "https://www.postgresql.org/media/keys/ACCC4CF8.asc" in dockerfile
    assert "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8" in dockerfile
    assert (
        "deb [signed-by=/usr/share/keyrings/postgresql-pgdg.gpg] "
        "https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" in dockerfile
    )
    assert "postgresql-client-16" in dockerfile
    assert "postgresql-client-17" not in dockerfile
    assert "apt-key" not in dockerfile
    assert "install -d -m 0700 -o aionex -g aionex" in dockerfile
    for compose in (primary_compose, deploy_compose):
        assert "backup-worker:" in compose
        assert "postgres-credential-reconciler:" in compose
        assert compose.count("image: aionex-aios-backend:local") == 3
        assert "backup_data:/var/lib/aionex/backups" in compose
        assert 'command: ["python", "-m", "app.services.backup_worker"]' in compose
        assert 'command: ["python", "-m", "app.db.postgres_credentials"]' in compose
        assert (
            'test: ["CMD", "python", "-m", "app.services.backup_worker", '
            '"--healthcheck"]' in compose
        )

    health_probe = validation_workflow.index("docker inspect")
    worker_stop = validation_workflow.index('"${compose_args[@]}" stop backup-worker')
    round_trip = validation_workflow.index(
        "tests/test_backup_executor.py::"
        "test_live_postgres_worker_backup_and_restore_smoke"
    )
    assert health_probe < worker_stop < round_trip
    assert "pg_dump --version" in validation_workflow
    assert r"\(PostgreSQL\) 16(\.|$)" in validation_workflow
    assert "ps --status running -q backup-worker" in validation_workflow
    assert "-e RUN_LIVE_BACKUP_SMOKE=1" in validation_workflow
    assert '"${compose_args[@]}" run' in validation_workflow
    assert "--rm" in validation_workflow
    assert "--no-deps" in validation_workflow
    assert "backup-worker \\\n              python -m pytest" in validation_workflow


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
    backup = BackupRecord(
        id=f"bkp-{suffix}",
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
        assert await worker.run_once() is True
        assert await worker.claim_backup() is None
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

        assert await worker.run_once() is True
        assert await worker.claim_restore_validation() is None
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
