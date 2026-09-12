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
        THREE_D_STORAGE_ROOT=str(_private_dir(tmp_path / "three-d-assets")),
        PROJECT_EXECUTION_OUTPUT_ROOT=str(_private_dir(tmp_path / "project-executions")),
        ACADEMY_COURSE_PACKAGE_ROOT=str(_private_dir(tmp_path / "course-packages")),
    )


def test_project_execution_and_course_packages_join_platform_asset_snapshot(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump",
        b"PGDMPdatabase",
    )
    _private_file(
        Path(config.PROJECT_EXECUTION_OUTPUT_ROOT) / "execution-1" / "output.txt",
        b"project-output",
    )
    _private_file(
        Path(config.ACADEMY_COURSE_PACKAGE_ROOT) / "course-1" / "manifest.json",
        b"{\"course\":true}",
    )

    executor = ThreeDAssetSnapshotExecutor(config)
    snapshot = executor.create_snapshot(str(database))
    assert snapshot is not None
    assert snapshot.roots is not None
    assert snapshot.roots["project_execution_data"] == {
        "file_count": 1,
        "payload_bytes": len(b"project-output"),
    }
    assert snapshot.roots["course_package_data"] == {
        "file_count": 1,
        "payload_bytes": len(b"{\"course\":true}"),
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
    assert manifest["kind"] == "aionex-platform-asset-roots"
    names = {item["path"] for item in manifest["files"]}
    assert "project_execution_data/execution-1/output.txt" in names
    assert "course_package_data/course-1/manifest.json" in names


def test_project_execution_snapshot_rejects_symlinks(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'c' * 24}-{'d' * 32}.dump",
        b"PGDMPdatabase",
    )
    target = _private_file(tmp_path / "outside.txt", b"outside")
    link = Path(config.PROJECT_EXECUTION_OUTPUT_ROOT) / "execution-1" / "leak.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(link.parent, 0o700)
    link.symlink_to(target)

    with pytest.raises(BackupExecutionError, match="unsafe file"):
        ThreeDAssetSnapshotExecutor(config).create_snapshot(str(database))


def test_backup_worker_mounts_project_execution_and_course_packages_read_only() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    backup = compose.split("\n  backup-worker:", 1)[1].split("\n\n  communication-worker:", 1)[0]
    assert 'BACKUP_PROJECT_EXECUTION_ASSETS_ENABLED: "true"' in backup
    assert 'BACKUP_COURSE_PACKAGES_ENABLED: "true"' in backup
    assert "PROJECT_EXECUTION_OUTPUT_ROOT: /var/lib/aionex/project-executions" in backup
    assert "ACADEMY_COURSE_PACKAGE_ROOT: /var/lib/aionex/course-packages" in backup
    assert "project_execution_data:/var/lib/aionex/project-executions:ro" in backup
    assert "course_package_data:/var/lib/aionex/course-packages:ro" in backup
    assert "project_npm_cache_data" not in backup
