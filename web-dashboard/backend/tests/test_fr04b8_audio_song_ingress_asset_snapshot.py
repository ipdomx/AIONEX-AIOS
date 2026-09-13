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
        DATABASE_URL="postgresql+asyncpg://u@localhost:5432/aionex_test",
        BACKUP_DIR=str(_private_dir(tmp_path / "backups")),
        BACKUP_AUDIO_SONG_INGRESS_ENABLED=True,
        THREE_D_STORAGE_ROOT=str(_private_dir(tmp_path / "three-d-assets")),
        AUDIO_SONG_ARTIFACT_BRIDGE_ROOT=str(_private_dir(tmp_path / "audio-song-provider-ingress")),
    )


def test_audio_song_ingress_joins_platform_asset_snapshot(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump",
        b"PGDMPdatabase",
    )
    _private_file(
        Path(config.AUDIO_SONG_ARTIFACT_BRIDGE_ROOT) / "tenant-a" / "provider-output.wav",
        b"audio-provider-output",
    )

    executor = ThreeDAssetSnapshotExecutor(config)
    snapshot = executor.create_snapshot(str(database))

    assert snapshot is not None
    assert snapshot.roots is not None
    assert snapshot.roots["audio_song_ingress_data"] == {
        "file_count": 1,
        "payload_bytes": len(b"audio-provider-output"),
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
    assert "audio_song_ingress_data/tenant-a/provider-output.wav" in names


def test_audio_song_ingress_snapshot_rejects_symlinks(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    backup_dir = Path(config.BACKUP_DIR)
    database = _private_file(
        backup_dir / f"backup-{'c' * 24}-{'d' * 32}.dump",
        b"PGDMPdatabase",
    )
    target = _private_file(tmp_path / "outside.wav", b"outside")
    link = Path(config.AUDIO_SONG_ARTIFACT_BRIDGE_ROOT) / "tenant-a" / "leak.wav"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(link.parent, 0o700)
    link.symlink_to(target)

    with pytest.raises(BackupExecutionError, match="unsafe file"):
        ThreeDAssetSnapshotExecutor(config).create_snapshot(str(database))


def test_backup_worker_mounts_audio_song_ingress_read_only() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    init = compose.split("\n  backup-asset-root-init:", 1)[1].split("\n\n  backup-worker:", 1)[0]
    backup = compose.split("\n  backup-worker:", 1)[1].split("\n\n  communication-worker:", 1)[0]
    assert "audio_song_ingress_data:/var/lib/aionex/audio-song-provider-ingress:rw" in init
    assert 'BACKUP_AUDIO_SONG_INGRESS_ENABLED: "true"' in backup
    assert "AUDIO_SONG_ARTIFACT_BRIDGE_ROOT: /var/lib/aionex/audio-song-provider-ingress" in backup
    assert "audio_song_ingress_data:/var/lib/aionex/audio-song-provider-ingress:ro" in backup
    assert "project_npm_cache_data" not in backup


def test_audio_song_ingress_entrypoint_accepts_prepared_read_only_root() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "Unable to prepare private audio song ingress root" in entrypoint
    assert "Private audio song ingress root is not owned or permissioned correctly" in entrypoint
    assert "audio_song_ingress_meta" in entrypoint
