"""Security and integrity contracts for local 3D companion backups."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import time

import pytest

from app.core.config import Settings
from app.services.backup_executor import BackupExecutionError
from app.services.three_d_asset_backup import ThreeDAssetSnapshotExecutor


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    backup_dir = tmp_path / "backups"
    source_dir = tmp_path / "three-d"
    backup_dir.mkdir(mode=0o700)
    source_dir.mkdir(mode=0o700)
    os.chmod(backup_dir, 0o700)
    os.chmod(source_dir, 0o700)
    return Settings(
        SECRET_KEY="test-only-secret-key-with-at-least-32-characters",
        DATABASE_URL="postgresql+asyncpg://user:pass@database:5432/aionex_test",
        BACKUP_DIR=str(backup_dir),
        BACKUP_THREE_D_ASSETS_ENABLED=enabled,
        THREE_D_STORAGE_ROOT=str(source_dir),
    )


def _database_artifact(config: Settings) -> Path:
    path = Path(config.BACKUP_DIR) / f"backup-{'a' * 24}-{'b' * 32}.dump"
    path.write_bytes(b"PGDMP-test-database-artifact")
    os.chmod(path, 0o600)
    return path


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_bytes(payload)
    os.chmod(path, 0o600)


def test_snapshot_round_trip_is_private_hashed_and_isolated(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    source = Path(config.THREE_D_STORAGE_ROOT)
    _write_private(source / "tenant-a" / "mesh.glb", b"glb-payload")
    _write_private(source / "tenant-a" / "texture.webp", b"texture-payload")
    database = _database_artifact(config)
    executor = ThreeDAssetSnapshotExecutor(config)

    estimated = executor.estimated_snapshot_bytes()
    snapshot = executor.create_snapshot(str(database))

    assert snapshot is not None
    assert snapshot.file_count == 2
    assert snapshot.payload_bytes == len(b"glb-payloadtexture-payload")
    assert snapshot.size_bytes > snapshot.payload_bytes
    assert estimated >= snapshot.size_bytes
    snapshot_path = Path(snapshot.location)
    assert stat.S_IMODE(snapshot_path.stat().st_mode) == 0o600

    validated = executor.validate_snapshot(
        str(database),
        expected_checksum=snapshot.checksum,
        expected_size_bytes=snapshot.size_bytes,
        expected_file_count=snapshot.file_count,
        expected_payload_bytes=snapshot.payload_bytes,
    )
    assert validated == snapshot
    assert not list(Path(config.BACKUP_DIR).glob(".three-d-restore-*"))


def test_snapshot_tamper_fails_durable_checksum(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    _write_private(Path(config.THREE_D_STORAGE_ROOT) / "mesh.glb", b"original")
    database = _database_artifact(config)
    executor = ThreeDAssetSnapshotExecutor(config)
    snapshot = executor.create_snapshot(str(database))
    assert snapshot is not None

    path = Path(snapshot.location)
    payload = bytearray(path.read_bytes())
    payload[-1] ^= 0x01
    path.write_bytes(payload)
    os.chmod(path, 0o600)

    with pytest.raises(BackupExecutionError, match="checksum"):
        executor.validate_snapshot(
            str(database),
            expected_checksum=snapshot.checksum,
            expected_size_bytes=snapshot.size_bytes,
            expected_file_count=snapshot.file_count,
            expected_payload_bytes=snapshot.payload_bytes,
        )


def test_snapshot_rejects_symlink_and_world_readable_assets(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    source = Path(config.THREE_D_STORAGE_ROOT)
    outside = tmp_path / "outside.glb"
    outside.write_bytes(b"outside")
    (source / "linked.glb").symlink_to(outside)
    executor = ThreeDAssetSnapshotExecutor(config)

    with pytest.raises(BackupExecutionError, match="unsafe file"):
        executor.source_size_bytes()

    (source / "linked.glb").unlink()
    insecure = source / "insecure.glb"
    insecure.write_bytes(b"insecure")
    os.chmod(insecure, 0o644)
    with pytest.raises(BackupExecutionError, match="unsafe file permissions"):
        executor.source_size_bytes()


def test_orphan_snapshot_cleanup_waits_for_lease_window(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    _write_private(Path(config.THREE_D_STORAGE_ROOT) / "mesh.glb", b"mesh")
    database = _database_artifact(config)
    executor = ThreeDAssetSnapshotExecutor(config)
    snapshot = executor.create_snapshot(str(database))
    assert snapshot is not None
    database.unlink()

    snapshot_path = Path(snapshot.location)
    now = time.time()
    os.utime(snapshot_path, (now, now))
    assert executor.cleanup_orphan_snapshots(60) == 0
    assert snapshot_path.exists()

    old = now - 120
    os.utime(snapshot_path, (old, old))
    assert executor.cleanup_orphan_snapshots(60) == 1
    assert not snapshot_path.exists()


def test_disabled_policy_never_requires_source_or_specific_snapshot_cleanup(
    tmp_path: Path,
) -> None:
    config = _settings(tmp_path, enabled=False)
    executor = ThreeDAssetSnapshotExecutor(config)
    assert executor.enabled is False
    assert executor.source_size_bytes() == 0
    assert executor.estimated_snapshot_bytes() == 0
    assert executor.delete_snapshot("/not/a/worker/artifact.dump") is False
