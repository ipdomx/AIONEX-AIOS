import json
import os
import tarfile
from pathlib import Path

import pytest
from app.core.config import Settings
from app.services.backup_executor import BackupExecutionError
from app.services.three_d_asset_backup import ThreeDAssetSnapshotExecutor

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
ENTRYPOINT = ROOT / "web-dashboard" / "backend" / "scripts" / "docker-entrypoint.sh"


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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        SECRET_KEY="unit-test-secret-key-with-at-least-32-characters",
        DATABASE_URL="postgresql+asyncpg://backup_user:db-password@database:5432/aionex",
        BACKUP_DIR=str(_private_dir(tmp_path / "backups")),
        BACKUP_THREE_D_ASSETS_ENABLED=True,
        BACKUP_PROJECT_EXECUTION_ASSETS_ENABLED=True,
        BACKUP_COURSE_PACKAGES_ENABLED=True,
        BACKUP_MEDIA_ASSETS_ENABLED=True,
        THREE_D_STORAGE_ROOT=str(_private_dir(tmp_path / "three-d-assets")),
        PROJECT_EXECUTION_OUTPUT_ROOT=str(_private_dir(tmp_path / "project-executions")),
        ACADEMY_COURSE_PACKAGE_ROOT=str(_private_dir(tmp_path / "course-packages")),
        MEDIA_STORAGE_ROOT=str(_private_dir(tmp_path / "media-assets")),
    )


def test_media_assets_join_platform_asset_snapshot(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump",
        b"PGDMPdatabase",
    )
    _private_file(
        Path(config.MEDIA_STORAGE_ROOT) / "tenant-a" / "image.png",
        b"media-image",
    )
    _private_file(
        Path(config.MEDIA_STORAGE_ROOT) / "tenant-a" / "voice.wav",
        b"media-voice",
    )

    executor = ThreeDAssetSnapshotExecutor(config)
    snapshot = executor.create_snapshot(str(database))

    assert snapshot is not None
    assert snapshot.roots is not None
    assert snapshot.roots["media_asset_data"] == {
        "file_count": 2,
        "payload_bytes": len(b"media-imagemedia-voice"),
    }
    validated = executor.validate_snapshot(
        str(database),
        expected_checksum=snapshot.checksum,
        expected_size_bytes=snapshot.size_bytes,
        expected_file_count=snapshot.file_count,
        expected_payload_bytes=snapshot.payload_bytes,
    )
    assert validated.roots == snapshot.roots

    with tarfile.open(snapshot.location, mode="r:") as archive:
        manifest_member = archive.extractfile("manifest.json")
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read())
    names = {item["path"] for item in manifest["files"]}
    assert "media_asset_data/tenant-a/image.png" in names
    assert "media_asset_data/tenant-a/voice.wav" in names


def test_media_asset_snapshot_rejects_symlinks(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'c' * 24}-{'d' * 32}.dump",
        b"PGDMPdatabase",
    )
    target = _private_file(tmp_path / "outside.bin", b"outside")
    link = Path(config.MEDIA_STORAGE_ROOT) / "tenant-a" / "leak.bin"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(link.parent, 0o700)
    link.symlink_to(target)

    with pytest.raises(BackupExecutionError, match="unsafe file"):
        ThreeDAssetSnapshotExecutor(config).create_snapshot(str(database))


def test_backup_worker_mounts_media_assets_read_only() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    init = compose.split("\n  backup-asset-root-init:", 1)[1].split("\n\n  backup-worker:", 1)[0]
    backup = compose.split("\n  backup-worker:", 1)[1].split("\n\n  communication-worker:", 1)[0]
    assert "/var/lib/aionex/media-assets" in init
    assert "media_asset_data:/var/lib/aionex/media-assets:rw" in init
    assert 'BACKUP_MEDIA_ASSETS_ENABLED: "true"' in backup
    assert "MEDIA_STORAGE_ROOT: /var/lib/aionex/media-assets" in backup
    assert "media_asset_data:/var/lib/aionex/media-assets:ro" in backup
    assert "project_npm_cache_data" not in backup
    assert "studio_asset_data" not in backup
    assert "portal_asset_data" not in backup


def test_media_entrypoint_accepts_prepared_read_only_root() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "Private media asset root is not owned or permissioned correctly" in entrypoint
    assert "media_storage_meta" in entrypoint
