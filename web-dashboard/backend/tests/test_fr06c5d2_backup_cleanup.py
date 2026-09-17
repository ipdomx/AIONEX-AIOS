"""Focused cleanup uncertainty regressions with no database or external work."""
from __future__ import annotations

import asyncio
import errno
import hashlib
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import backup_executor as backup
from app.services import offsite_backup as offsite
from app.services import three_d_asset_backup as three_d


_PRIVATE_DETAIL = "synthetic-private-cleanup-detail"


@pytest.fixture(autouse=True)
def deny_unmocked_external_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unmocked external work is forbidden in cleanup tests")

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("Unmocked asynchronous external work is forbidden")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_async)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_async)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(offsite.boto3, "client", forbidden)
    monkeypatch.setattr(backup.AsyncPostgresCommandRunner, "run", forbidden_async)
    monkeypatch.setattr(AsyncSession, "execute", forbidden_async)
    monkeypatch.setattr(AsyncSession, "scalar", forbidden_async)


def _config(tmp_path):
    backup_dir = tmp_path / "backups"
    source_dir = tmp_path / "three-d"
    backup_dir.mkdir(mode=0o700)
    source_dir.mkdir(mode=0o700)
    # Explicit configuration avoids loading environment-backed Settings or any
    # credential files. The synthetic database address is never contacted.
    return SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://test_user:test_password@invalid.test/aionex_test",
        BACKUP_DIR=str(backup_dir),
        BACKUP_TIMEOUT_SECONDS=30,
        BACKUP_VALIDATION_TIMEOUT_SECONDS=30,
        BACKUP_CLEANUP_TIMEOUT_SECONDS=10,
        BACKUP_WORKER_HEARTBEAT_SECONDS=10,
        BACKUP_THREE_D_ASSETS_ENABLED=True,
        THREE_D_STORAGE_ROOT=str(source_dir),
        PROJECT_EXECUTION_OUTPUT_ROOT=str(tmp_path / "unused-project-output"),
    )


class _Runner:
    def __init__(self, *, failure=None, fail_at=None, cleanup_failure=None):
        self.failure = failure
        self.fail_at = fail_at
        self.cleanup_failure = cleanup_failure
        self.calls = []

    async def run(self, command, *, environment, timeout_seconds, operation):
        del environment, timeout_seconds
        self.calls.append((command[0], operation))
        if command[0] == "pg_dump":
            Path(command[command.index("--file") + 1]).write_bytes(
                b"PGDMP-small-test-archive"
            )
        if operation == "Restore validation cleanup" and self.cleanup_failure is not None:
            raise self.cleanup_failure
        if operation == self.fail_at and self.failure is not None:
            raise self.failure


def _archive(config):
    path = Path(config.BACKUP_DIR) / ("backup-" + "a" * 24 + "-" + "b" * 32 + ".dump")
    payload = b"PGDMP-small-restore-test-archive"
    path.write_bytes(payload)
    path.chmod(0o600)
    return path, hashlib.sha256(payload).hexdigest(), len(payload)


def _snapshot_source(config):
    path = Path(config.THREE_D_STORAGE_ROOT) / "mesh.glb"
    path.write_bytes(b"small-private-mesh")
    path.chmod(0o600)


def _fail_unlinks(monkeypatch, predicate):
    original = Path.unlink
    attempted = []

    def unlink(path, *args, **kwargs):
        if predicate(path):
            attempted.append(path)
            raise PermissionError(errno.EACCES, _PRIVATE_DETAIL, str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    return attempted


def _assert_incomplete(error, *private_paths):
    assert isinstance(error, backup.BackupCleanupIncomplete)
    assert isinstance(error, backup.BackupExecutionError)
    assert isinstance(error.status_code, int) and error.status_code >= 400
    public = " ".join((str(error), error.public_message, error.operation))
    assert _PRIVATE_DETAIL not in public
    assert all(str(path) not in public for path in private_paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_failure", [False, True])
async def test_backup_partial_unlink_failure_never_returns_settled_result(
    tmp_path, monkeypatch, primary_failure,
):
    config = _config(tmp_path)
    primary = backup.BackupExecutionError("PostgreSQL backup", "safe functional failure")
    runner = _Runner(
        failure=primary if primary_failure else None,
        fail_at="PostgreSQL backup",
    )
    executor = backup.BackupExecutor(config, runner)
    attempted = _fail_unlinks(
        monkeypatch,
        lambda path: path.parent == Path(config.BACKUP_DIR) and path.name.endswith(".partial"),
    )
    with pytest.raises(backup.BackupCleanupIncomplete) as caught:
        await executor.create_backup("cleanup-backup", "cleanup-attempt")
    assert len(attempted) == 1
    _assert_incomplete(caught.value, attempted[0])
    if primary_failure:
        assert attempted[0].is_file()
    else:
        # Publication succeeded, but the failed cleanup check must still prevent
        # a successful return that would let the owning cycle be declared done.
        assert list(Path(config.BACKUP_DIR).glob("backup-*.dump"))


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_failure", [False, True])
async def test_restore_final_drop_failure_is_incomplete_even_after_primary_error(tmp_path, primary_failure):
    config = _config(tmp_path)
    path, checksum, size = _archive(config)
    primary = backup.BackupExecutionError("PostgreSQL restore validation", "safe restore failure")
    cleanup = backup.BackupExecutionError("Restore validation cleanup", "safe drop failure")
    runner = _Runner(
        failure=primary if primary_failure else None,
        fail_at="PostgreSQL restore validation",
        cleanup_failure=cleanup,
    )
    executor = backup.BackupExecutor(config, runner)
    with pytest.raises(backup.BackupCleanupIncomplete) as caught:
        await executor.validate_restore(
            str(path), checksum, "cleanup-validation", "cleanup-attempt",
            expected_size_bytes=size,
        )
    assert runner.calls[-1] == ("dropdb", "Restore validation cleanup")
    assert runner.calls.count(("dropdb", "Restore validation cleanup")) == 1
    _assert_incomplete(caught.value, path)
    assert caught.value is not primary
    assert path.is_file()


@pytest.mark.parametrize("failed_names", [
    {"database.dump"}, {"snapshot.tar"}, {"database.dump", "snapshot.tar"},
])
def test_offsite_cleanup_attempts_both_paths_before_reporting_incomplete(
    tmp_path, monkeypatch, failed_names,
):
    paths = [tmp_path / "database.dump", tmp_path / "snapshot.tar"]
    for path in paths:
        path.write_bytes(b"downloaded-test-artifact")
    original = Path.unlink
    attempted = []

    def unlink(path, *args, **kwargs):
        if path in paths:
            attempted.append(path)
            if path.name in failed_names:
                raise PermissionError(errno.EACCES, _PRIVATE_DETAIL, str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(backup.BackupCleanupIncomplete) as caught:
        offsite.OffsiteBackupReplicator.cleanup_validation(paths[0], paths[1])
    assert attempted == paths
    _assert_incomplete(caught.value, *paths)
    for path in paths:
        assert path.exists() is (path.name in failed_names)


@pytest.mark.parametrize("primary_failure", [False, True])
def test_snapshot_partial_unlink_failure_never_returns_settled_result(
    tmp_path, monkeypatch, primary_failure,
):
    config = _config(tmp_path)
    path, _checksum, _size = _archive(config)
    _snapshot_source(config)
    executor = three_d.ThreeDAssetSnapshotExecutor(config)
    if primary_failure:
        def fail_archive(*_args, **_kwargs):
            raise backup.BackupExecutionError("3D asset backup", "safe archive failure")
        monkeypatch.setattr(three_d.tarfile, "open", fail_archive)
    attempted = _fail_unlinks(
        monkeypatch,
        lambda item: item.parent == Path(config.BACKUP_DIR)
        and ".three-d.tar." in item.name and item.name.endswith(".partial"),
    )
    with pytest.raises(backup.BackupCleanupIncomplete) as caught:
        executor.create_snapshot(str(path))
    assert len(attempted) == 1
    _assert_incomplete(caught.value, attempted[0])
    if primary_failure:
        assert attempted[0].is_file()
    else:
        assert list(Path(config.BACKUP_DIR).glob("backup-*.three-d.tar"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["backup", "restore"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_async_cancellation_is_preserved_when_final_cleanup_also_fails(
    tmp_path, monkeypatch, operation, cleanup_fails,
):
    config = _config(tmp_path)
    cancelled = asyncio.CancelledError("synthetic cancellation")
    attempted = []
    if operation == "backup":
        runner = _Runner(failure=cancelled, fail_at="PostgreSQL backup")
        if cleanup_fails:
            attempted = _fail_unlinks(
                monkeypatch,
                lambda path: path.parent == Path(config.BACKUP_DIR)
                and path.name.endswith(".partial"),
            )
        executor = backup.BackupExecutor(config, runner)
        call = executor.create_backup("cancelled-backup", "cancelled-attempt")
    else:
        path, checksum, size = _archive(config)
        runner = _Runner(
            failure=cancelled,
            fail_at="PostgreSQL restore validation",
            cleanup_failure=(
                backup.BackupExecutionError("Restore validation cleanup", "safe drop failure")
                if cleanup_fails else None
            ),
        )
        executor = backup.BackupExecutor(config, runner)
        call = executor.validate_restore(
            str(path), checksum, "cancelled-validation", "cancelled-attempt",
            expected_size_bytes=size,
        )
    with pytest.raises(asyncio.CancelledError) as caught:
        await call
    assert caught.value is cancelled
    assert _PRIVATE_DETAIL not in str(cancelled)
    assert _PRIVATE_DETAIL not in str(getattr(cancelled, "__notes__", []))
    if operation == "backup":
        if cleanup_fails:
            assert len(attempted) == 1 and attempted[0].is_file()
        else:
            assert not list(Path(config.BACKUP_DIR).glob("*.partial"))
    else:
        assert runner.calls[-1] == ("dropdb", "Restore validation cleanup")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["backup", "restore", "snapshot"])
async def test_functional_error_with_successful_cleanup_remains_ordinary(
    tmp_path, monkeypatch, operation,
):
    config = _config(tmp_path)
    primary = backup.BackupExecutionError(operation, "safe functional error", status_code=409)
    if operation == "backup":
        executor = backup.BackupExecutor(
            config, _Runner(failure=primary, fail_at="PostgreSQL backup"),
        )
        with pytest.raises(backup.BackupExecutionError) as caught:
            await executor.create_backup("failed-backup", "failed-attempt")
    elif operation == "restore":
        path, checksum, size = _archive(config)
        runner = _Runner(failure=primary, fail_at="PostgreSQL restore validation")
        executor = backup.BackupExecutor(config, runner)
        with pytest.raises(backup.BackupExecutionError) as caught:
            await executor.validate_restore(
                str(path), checksum, "failed-validation", "failed-attempt",
                expected_size_bytes=size,
            )
        assert runner.calls[-1] == ("dropdb", "Restore validation cleanup")
    else:
        path, _checksum, _size = _archive(config)
        _snapshot_source(config)

        def fail_archive(*_args, **_kwargs):
            raise primary

        monkeypatch.setattr(three_d.tarfile, "open", fail_archive)
        with pytest.raises(backup.BackupExecutionError) as caught:
            three_d.ThreeDAssetSnapshotExecutor(config).create_snapshot(str(path))
    assert caught.value is primary
    assert not isinstance(caught.value, backup.BackupCleanupIncomplete)
    assert caught.value.status_code == 409
    assert not list(Path(config.BACKUP_DIR).glob("*.partial"))


@pytest.mark.parametrize("snapshot_present", [False, True])
def test_offsite_successful_cleanup_is_idempotent_and_allows_missing_snapshot(tmp_path, snapshot_present):
    database = tmp_path / "database.dump"
    snapshot = tmp_path / "snapshot.tar" if snapshot_present else None
    database.write_bytes(b"database")
    if snapshot is not None:
        snapshot.write_bytes(b"snapshot")
    offsite.OffsiteBackupReplicator.cleanup_validation(database, snapshot)
    offsite.OffsiteBackupReplicator.cleanup_validation(database, snapshot)
    assert not database.exists()
    assert snapshot is None or not snapshot.exists()


def test_snapshot_interruption_is_preserved_when_partial_cleanup_fails(tmp_path, monkeypatch):
    config = _config(tmp_path)
    path, _checksum, _size = _archive(config)
    _snapshot_source(config)
    interrupted = asyncio.CancelledError("synthetic snapshot interruption")

    def interrupt_archive(*_args, **_kwargs):
        raise interrupted

    monkeypatch.setattr(three_d.tarfile, "open", interrupt_archive)
    attempted = _fail_unlinks(
        monkeypatch,
        lambda item: item.parent == Path(config.BACKUP_DIR)
        and ".three-d.tar." in item.name and item.name.endswith(".partial"),
    )
    with pytest.raises(asyncio.CancelledError) as caught:
        three_d.ThreeDAssetSnapshotExecutor(config).create_snapshot(str(path))
    assert caught.value is interrupted
    assert len(attempted) == 1 and attempted[0].is_file()
    assert _PRIVATE_DETAIL not in str(getattr(interrupted, "__notes__", []))
