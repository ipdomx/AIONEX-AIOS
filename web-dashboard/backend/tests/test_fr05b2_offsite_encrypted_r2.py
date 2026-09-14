from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import offsite_backup
from app.services.backup_executor import BackupExecutionError
from app.services.three_d_asset_backup import ThreeDAssetSnapshot


class _Body(BytesIO):
    pass


class _Paginator:
    def __init__(self, client: "_FakeS3") -> None:
        self.client = client

    def paginate(self, *, Bucket: str, Prefix: str):
        del Bucket
        yield {
            "Contents": [
                {
                    "Key": key,
                    "LastModified": self.client.modified[key],
                }
                for key in sorted(self.client.objects)
                if key.startswith(Prefix)
            ]
        }


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.modified: dict[str, datetime] = {}
        self._sequence = 0

    def _store(self, key: str, payload: bytes, metadata: dict[str, str]) -> None:
        self._sequence += 1
        self.objects[key] = payload
        self.metadata[key] = metadata
        self.modified[key] = datetime(2026, 9, 14, tzinfo=UTC) + timedelta(
            seconds=self._sequence
        )

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]:
        del Bucket
        return {}

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, Any] | None = None,
    ) -> None:
        del bucket
        self._store(
            key,
            Path(filename).read_bytes(),
            dict((ExtraArgs or {}).get("Metadata") or {}),
        )

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        return {
            "ContentLength": len(self.objects[Key]),
            "Metadata": self.metadata.get(Key, {}),
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        return {"Body": _Body(self.objects[Key])}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        del bucket
        Path(filename).write_bytes(self.objects[key])

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return _Paginator(self)

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:
        del Bucket
        for item in Delete["Objects"]:
            key = item["Key"]
            self.objects.pop(key, None)
            self.metadata.pop(key, None)
            self.modified.pop(key, None)
        return {}


def _write_keyring(path: Path, key: bytes) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_key_id": "active-2026",
                "keys": {
                    "active-2026": {
                        "key_b64": base64.urlsafe_b64encode(key).decode().rstrip("="),
                        "status": "active",
                        "created_at": "2026-09-14T00:00:00Z",
                        "rotation_generation": 1,
                    }
                },
            }
        )
    )
    path.chmod(0o400)
    return path


def _config(
    tmp_path: Path,
    *,
    key: bytes = b"K" * 32,
    suffix: str = "primary",
    retention: int = 30,
    encryption_required: bool = True,
):
    credentials = tmp_path / f"r2-{suffix}.env"
    credentials.write_text(
        "R2_BACKUP_ENDPOINT=https://0123456789abcdef0123456789abcdef."
        "r2.cloudflarestorage.com\n"
        "R2_BACKUP_BUCKET=aionex-production-backups\n"
        "R2_BACKUP_ACCESS_KEY_ID=test-access\n"
        "R2_BACKUP_SECRET_ACCESS_KEY=test-secret\n"
    )
    credentials.chmod(0o400)
    keyring = _write_keyring(tmp_path / f"keyring-{suffix}.json", key)
    backup_dir = tmp_path / "restore-staging"
    backup_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        BACKUP_OFFSITE_ENABLED=True,
        BACKUP_OFFSITE_PREFIX="aionex-production",
        BACKUP_DIR=str(backup_dir),
        BACKUP_OFFSITE_SECRET_FILE=str(credentials),
        BACKUP_OFFSITE_RETENTION_COUNT=retention,
        BACKUP_OFFSITE_ENCRYPTION_REQUIRED=encryption_required,
        BACKUP_OFFSITE_ENCRYPTION_KEYRING_FILE=str(keyring),
    )


def _source_artifacts(tmp_path: Path) -> tuple[Path, ThreeDAssetSnapshot]:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    database = source / "database.dump"
    database.write_bytes(b"PGDMP-private-database-payload")
    snapshot_path = source / "platform-assets.tar"
    snapshot_path.write_bytes(b"private-platform-assets-payload")
    checksum, size = offsite_backup._sha256(snapshot_path)
    snapshot = ThreeDAssetSnapshot(
        location=str(snapshot_path),
        checksum=checksum,
        size_bytes=size,
        file_count=2,
        payload_bytes=23,
        roots={"media": {"files": 2, "payload_bytes": 23}},
    )
    return database, snapshot


def _replicate(
    replicator: offsite_backup.OffsiteBackupReplicator,
    backup_id: str,
    database: Path,
    snapshot: ThreeDAssetSnapshot | None,
) -> dict[str, Any]:
    checksum, size = offsite_backup._sha256(database)
    return replicator.replicate(
        backup_id=backup_id,
        database_location=str(database),
        database_checksum=checksum,
        database_size=size,
        snapshot=snapshot,
    )


def test_offsite_enablement_fails_closed_when_encryption_is_disabled(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, encryption_required=False)
    with pytest.raises(
        BackupExecutionError, match="Client-side encryption is required"
    ):
        offsite_backup.OffsiteBackupReplicator(config)


def test_encrypted_upload_readback_and_restore_contains_no_plaintext_or_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, snapshot = _source_artifacts(tmp_path)
    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    replicator = offsite_backup.OffsiteBackupReplicator(_config(tmp_path))

    backup_id = "12345678-1234-1234-1234-123456789abc"
    evidence = _replicate(replicator, backup_id, database, snapshot)

    assert evidence["schema_version"] == 2
    assert evidence["encryption_required"] is True
    assert sorted(fake.objects) == [
        f"aionex-production/{backup_id}/database.dump.aex1",
        f"aionex-production/{backup_id}/manifest.json.aex1",
        f"aionex-production/{backup_id}/platform-assets.tar.aex1",
    ]
    for key, payload in fake.objects.items():
        assert payload.startswith(b"AIONEX-R2-ENC")
        assert database.read_bytes() not in payload
        assert Path(snapshot.location).read_bytes() not in payload
        metadata = fake.metadata[key]
        assert metadata["aionex-envelope"] == "aex1"
        assert metadata["aionex-algorithm"] == "AES-256-GCM"
        assert "key_b64" not in json.dumps(metadata)
        assert "test-secret" not in json.dumps(metadata)

    serialized = json.dumps(evidence, sort_keys=True)
    assert "key_b64" not in serialized
    assert base64.urlsafe_b64encode(b"K" * 32).decode().rstrip("=") not in serialized

    staged = replicator.download_for_validation(
        evidence,
        validation_id="87654321-4321-4321-4321-cba987654321",
        attempt_token="attempt-token",
    )
    assert Path(staged.database_location).read_bytes() == database.read_bytes()
    assert staged.snapshot_location is not None
    assert (
        Path(staged.snapshot_location).read_bytes()
        == Path(snapshot.location).read_bytes()
    )
    replicator.cleanup_validation(staged.database_location, staged.snapshot_location)


def test_wrong_key_and_ciphertext_corruption_publish_no_plaintext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, _snapshot = _source_artifacts(tmp_path)
    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    original = offsite_backup.OffsiteBackupReplicator(_config(tmp_path))
    evidence = _replicate(
        original,
        "12345678-1234-1234-1234-123456789abc",
        database,
        None,
    )

    wrong_key = offsite_backup.OffsiteBackupReplicator(
        _config(tmp_path, key=b"W" * 32, suffix="wrong")
    )
    with pytest.raises(BackupExecutionError, match="authentication failed"):
        wrong_key.download_for_validation(
            evidence,
            validation_id="11111111-1111-1111-1111-111111111111",
            attempt_token="wrong-key",
        )

    database_key = evidence["database"]["key"]
    corrupted = bytearray(fake.objects[database_key])
    corrupted[len(corrupted) // 2] ^= 0x01
    fake.objects[database_key] = bytes(corrupted)
    with pytest.raises(BackupExecutionError, match="ciphertext validation"):
        original.download_for_validation(
            evidence,
            validation_id="22222222-2222-2222-2222-222222222222",
            attempt_token="corruption",
        )

    staging_root = tmp_path / "restore-staging"
    assert not list(staging_root.glob("backup-*.dump"))
    assert not list(staging_root.glob(".offsite-private-*"))


def test_encrypted_manifest_drives_retention_of_complete_prefixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, _snapshot = _source_artifacts(tmp_path)
    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    replicator = offsite_backup.OffsiteBackupReplicator(_config(tmp_path, retention=2))
    backup_ids = [
        "10000000-0000-0000-0000-000000000001",
        "20000000-0000-0000-0000-000000000002",
        "30000000-0000-0000-0000-000000000003",
    ]
    for backup_id in backup_ids:
        _replicate(replicator, backup_id, database, None)

    assert not any(f"/{backup_ids[0]}/" in key for key in fake.objects)
    assert any(f"/{backup_ids[1]}/manifest.json.aex1" in key for key in fake.objects)
    assert any(f"/{backup_ids[2]}/manifest.json.aex1" in key for key in fake.objects)


def test_explicit_schema_v1_legacy_restore_remains_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, _snapshot = _source_artifacts(tmp_path)
    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    replicator = offsite_backup.OffsiteBackupReplicator(_config(tmp_path))
    backup_id = "12345678-1234-1234-1234-123456789abc"
    key = f"aionex-production/{backup_id}/database.dump"
    checksum, size = offsite_backup._sha256(database)
    fake._store(key, database.read_bytes(), {"sha256": checksum})
    evidence = {
        "schema_version": 1,
        "backup_id": backup_id,
        "database": {"key": key, "sha256": checksum, "size_bytes": size},
        "three_d_snapshot": None,
    }

    staged = replicator.download_for_validation(
        evidence,
        validation_id="33333333-3333-3333-3333-333333333333",
        attempt_token="legacy",
    )
    assert Path(staged.database_location).read_bytes() == database.read_bytes()
    replicator.cleanup_validation(staged.database_location, None)


def test_backup_worker_validates_the_downloaded_snapshot_companion() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app/services/backup_worker.py"
    ).read_text()
    assert (
        "self._three_d_executor.validate_snapshot,\n"
        "                        offsite_artifacts.database_location,"
    ) in source


def test_source_change_between_precheck_and_encryption_is_never_uploaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, _snapshot = _source_artifacts(tmp_path)
    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    replicator = offsite_backup.OffsiteBackupReplicator(_config(tmp_path))
    encrypt_file = replicator.encryption.encrypt_file

    def mutate_before_encryption(source, destination, *, context):
        source.write_bytes(b"changed-after-replicator-precheck")
        return encrypt_file(source, destination, context=context)

    monkeypatch.setattr(replicator.encryption, "encrypt_file", mutate_before_encryption)
    checksum, size = offsite_backup._sha256(database)
    with pytest.raises(
        BackupExecutionError, match="changed before encrypted R2 upload"
    ):
        replicator.replicate(
            backup_id="12345678-1234-1234-1234-123456789abc",
            database_location=str(database),
            database_checksum=checksum,
            database_size=size,
            snapshot=None,
        )

    assert fake.objects == {}


def test_encrypted_restore_staging_matches_asset_companion_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings
    from app.services.three_d_asset_backup import ThreeDAssetSnapshotExecutor

    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    offsite_config = _config(tmp_path)

    asset_root = tmp_path / "three-d"
    asset_root.mkdir(mode=0o700)
    asset = asset_root / "mesh.glb"
    asset.write_bytes(b"private-mesh-payload")
    asset.chmod(0o600)

    database = (
        Path(offsite_config.BACKUP_DIR)
        / f"backup-{'a' * 24}-{'b' * 32}.dump"
    )
    database.write_bytes(b"PGDMP-private-database-payload")
    database.chmod(0o600)

    asset_config = Settings(
        SECRET_KEY="test-only-secret-key-with-at-least-32-characters",
        DATABASE_URL="postgresql+asyncpg://user:pass@database:5432/aionex_test",
        BACKUP_DIR=offsite_config.BACKUP_DIR,
        BACKUP_THREE_D_ASSETS_ENABLED=True,
        THREE_D_STORAGE_ROOT=str(asset_root),
    )
    asset_executor = ThreeDAssetSnapshotExecutor(asset_config)
    snapshot = asset_executor.create_snapshot(str(database))
    assert snapshot is not None

    replicator = offsite_backup.OffsiteBackupReplicator(offsite_config)
    evidence = _replicate(
        replicator,
        "12345678-1234-1234-1234-123456789abc",
        database,
        snapshot,
    )
    staged = replicator.download_for_validation(
        evidence,
        validation_id="44444444-4444-4444-4444-444444444444",
        attempt_token="asset-companion",
    )

    assert staged.snapshot_location is not None
    assert Path(staged.snapshot_location) == Path(
        staged.database_location
    ).with_suffix(".three-d.tar")
    validated = asset_executor.validate_snapshot(
        staged.database_location,
        expected_checksum=snapshot.checksum,
        expected_size_bytes=snapshot.size_bytes,
        expected_file_count=snapshot.file_count,
        expected_payload_bytes=snapshot.payload_bytes,
    )
    assert validated.location == staged.snapshot_location
    assert validated.file_count == 1
    assert validated.payload_bytes == len(b"private-mesh-payload")

    replicator.cleanup_validation(
        staged.database_location,
        staged.snapshot_location,
    )
    assert not Path(staged.database_location).exists()
    assert not Path(staged.snapshot_location).exists()
