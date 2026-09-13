import os
from pathlib import Path

import pytest
from app.core.config import Settings
from app.services.backup_executor import BackupExecutionError
from app.services.three_d_asset_backup import ThreeDAssetSnapshotExecutor


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _private_file(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_bytes(payload)
    os.chmod(path, 0o600)
    return path


def test_asset_snapshot_rejects_hard_linked_files(tmp_path: Path) -> None:
    source = _private_dir(tmp_path / "three-d-assets")
    backup_dir = _private_dir(tmp_path / "backups")
    database = _private_file(
        backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump",
        b"PGDMPdatabase",
    )
    original = _private_file(source / "mesh.glb", b"mesh")
    hardlink = source / "mesh-copy.glb"
    os.link(original, hardlink)
    os.chmod(hardlink, 0o600)

    config = Settings(
        SECRET_KEY="unit-test-secret-key-with-at-least-32-characters",
        DATABASE_URL="postgresql+asyncpg://backup_user:db-password@database:5432/aionex_test",
        BACKUP_DIR=str(backup_dir),
        BACKUP_THREE_D_ASSETS_ENABLED=True,
        THREE_D_STORAGE_ROOT=str(source),
    )

    with pytest.raises(BackupExecutionError, match="unsafe hard-linked file"):
        ThreeDAssetSnapshotExecutor(config).create_snapshot(str(database))
