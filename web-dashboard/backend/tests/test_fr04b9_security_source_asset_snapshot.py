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


def _private_dir(path: Path, *, realtime: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if realtime:
        os.chmod(path, 0o2770)
    else:
        os.chmod(path, 0o700)
    return path


def _private_file(path: Path, payload: bytes, *, realtime: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if realtime:
        os.chmod(path.parent, 0o2770)
    else:
        os.chmod(path.parent, 0o700)
    path.write_bytes(payload)
    if realtime:
        os.chmod(path, 0o660)
    else:
        os.chmod(path, 0o600)
    return path


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        SECRET_KEY="unit-test-secret-key-with-at-least-32-characters",
        DATABASE_URL="postgresql+asyncpg://backup_user:db-password@database:5432/aionex_test",
        BACKUP_DIR=str(_private_dir(tmp_path / "backups")),
        BACKUP_THREE_D_ASSETS_ENABLED=True,
        BACKUP_PROJECT_EXECUTION_ASSETS_ENABLED=True,
        BACKUP_COURSE_PACKAGES_ENABLED=True,
        BACKUP_MEDIA_ASSETS_ENABLED=True,
        BACKUP_STUDIO_ASSETS_ENABLED=True,
        BACKUP_PORTAL_ASSETS_ENABLED=True,
        BACKUP_MOBILE_RELEASES_ENABLED=True,
        BACKUP_REALTIME_RECORDINGS_ENABLED=True,
        BACKUP_AUDIO_SONG_INGRESS_ENABLED=True,
        BACKUP_SECURITY_SOURCES_ENABLED=True,
        THREE_D_STORAGE_ROOT=str(_private_dir(tmp_path / "three-d-assets")),
        PROJECT_EXECUTION_OUTPUT_ROOT=str(_private_dir(tmp_path / "project-executions")),
        ACADEMY_COURSE_PACKAGE_ROOT=str(_private_dir(tmp_path / "course-packages")),
        MEDIA_STORAGE_ROOT=str(_private_dir(tmp_path / "media-assets")),
        STUDIO_ASSET_ROOT=str(_private_dir(tmp_path / "studio-assets")),
        PORTAL_ASSET_ROOT=str(_private_dir(tmp_path / "portal-assets")),
        MOBILE_RELEASE_ROOT=str(_private_dir(tmp_path / "mobile-releases")),
        REALTIME_RECORDING_ROOT=str(_private_dir(tmp_path / "realtime-recordings", realtime=True)),
        BACKUP_REALTIME_RECORDING_OWNER_UID=os.getuid(),
        BACKUP_REALTIME_RECORDING_GROUP_GID=os.getgid(),
        AUDIO_SONG_ARTIFACT_BRIDGE_ROOT=str(_private_dir(tmp_path / "audio-song-provider-ingress")),
        SECURITY_SOURCE_ROOT=str(_private_dir(tmp_path / "security-sources")),
    )


def test_security_sources_join_platform_asset_snapshot(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump",
        b"PGDMPdatabase",
    )
    _private_file(
        Path(config.SECURITY_SOURCE_ROOT) / "targets" / "app.py",
        b"print('secure')\n",
    )

    executor = ThreeDAssetSnapshotExecutor(config)
    snapshot = executor.create_snapshot(str(database))

    assert snapshot is not None
    assert snapshot.roots is not None
    assert snapshot.roots["security_source_data"] == {
        "file_count": 1,
        "payload_bytes": len(b"print('secure')\n"),
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
    assert "security_source_data/targets/app.py" in names


def test_security_source_snapshot_rejects_symlinks(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'c' * 24}-{'d' * 32}.dump",
        b"PGDMPdatabase",
    )
    target = _private_file(tmp_path / "outside.py", b"outside")
    link = Path(config.SECURITY_SOURCE_ROOT) / "targets" / "leak.py"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(link.parent, 0o700)
    link.symlink_to(target)

    with pytest.raises(BackupExecutionError, match="unsafe file"):
        ThreeDAssetSnapshotExecutor(config).create_snapshot(str(database))


def test_security_source_snapshot_rejects_group_or_world_permissions(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'e' * 24}-{'f' * 32}.dump",
        b"PGDMPdatabase",
    )
    public = _private_file(
        Path(config.SECURITY_SOURCE_ROOT) / "targets" / "public.py",
        b"public",
    )
    os.chmod(public, 0o640)

    with pytest.raises(BackupExecutionError, match="unsafe file permissions"):
        ThreeDAssetSnapshotExecutor(config).create_snapshot(str(database))


def test_backup_worker_mounts_security_sources_read_only() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    init = compose.split("\n  backup-asset-root-init:", 1)[1].split("\n\n  backup-worker:", 1)[0]
    backup = compose.split("\n  backup-worker:", 1)[1].split("\n\n  communication-worker:", 1)[0]
    assert "security_source_data:/var/lib/aionex/security-sources:rw" in init
    assert 'BACKUP_SECURITY_SOURCES_ENABLED: "true"' in backup
    assert "SECURITY_SOURCE_ROOT: /var/lib/aionex/security-sources" in backup
    assert "security_source_data:/var/lib/aionex/security-sources:ro" in backup
    assert "security_remediation_data" not in backup
    assert "security_tool_cache_data" not in backup
