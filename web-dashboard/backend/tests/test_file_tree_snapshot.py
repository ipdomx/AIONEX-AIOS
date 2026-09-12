from __future__ import annotations

from pathlib import Path
import tarfile

import pytest

from app.services.backup_executor import BackupExecutionError
from app.services.file_tree_snapshot import FileTreeSnapshotExecutor


def _executor(tmp_path: Path) -> tuple[FileTreeSnapshotExecutor, Path, Path]:
    source = tmp_path / "media"
    source.mkdir(mode=0o700)
    nested = source / "org" / "project"
    nested.mkdir(parents=True, mode=0o755)
    nested.chmod(0o755)
    payload = nested / "clip.bin"
    payload.write_bytes(b"media-backup-payload")
    payload.chmod(0o600)
    backup = tmp_path / "backups"
    backup.mkdir(mode=0o700)
    database = backup / "backup-0123456789abcdef01234567-0123456789abcdef0123456789abcdef.dump"
    database.write_bytes(b"PGDMP")
    database.chmod(0o600)
    executor = FileTreeSnapshotExecutor(
        enabled=True,
        source_root=str(source),
        backup_dir=str(backup),
        slug="media-assets",
        manifest_kind="aionex-media-assets",
        label="media asset",
    )
    return executor, database, payload


def test_file_tree_snapshot_round_trip_and_manifest(tmp_path: Path) -> None:
    executor, database, payload = _executor(tmp_path)
    snapshot = executor.create_snapshot(str(database))
    assert snapshot is not None
    assert snapshot.file_count == 1
    assert snapshot.payload_bytes == len(payload.read_bytes())
    assert snapshot.location.endswith(".media-assets.tar")
    with tarfile.open(snapshot.location, "r:") as archive:
        assert set(archive.getnames()) == {"files/org/project/clip.bin", "manifest.json"}
    validated = executor.validate_snapshot(
        str(database),
        expected_checksum=snapshot.checksum,
        expected_size_bytes=snapshot.size_bytes,
        expected_file_count=1,
        expected_payload_bytes=snapshot.payload_bytes,
    )
    assert validated.checksum == snapshot.checksum


def test_file_tree_snapshot_rejects_tamper_and_symlink(tmp_path: Path) -> None:
    executor, database, _payload = _executor(tmp_path)
    snapshot = executor.create_snapshot(str(database))
    assert snapshot is not None
    with Path(snapshot.location).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(BackupExecutionError, match="checksum"):
        executor.validate_snapshot(str(database), expected_checksum=snapshot.checksum)

    source = tmp_path / "media"
    unsafe = source / "unsafe-link"
    unsafe.symlink_to(source / "org")
    with pytest.raises(BackupExecutionError, match="unsafe"):
        executor.source_size_bytes()
