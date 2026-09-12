from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from app.services import offsite_backup


class _Body(BytesIO):
    pass


class _Paginator:
    def __init__(self, client):
        self.client = client
    def paginate(self, *, Bucket, Prefix):
        contents = [
            {"Key": key, "LastModified": datetime.now(UTC)}
            for key in sorted(self.client.objects)
            if key.startswith(Prefix)
        ]
        yield {"Contents": contents}


class _FakeS3:
    def __init__(self):
        self.objects = {}
        self.metadata = {}
    def head_bucket(self, *, Bucket): return {}
    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[key] = Path(filename).read_bytes()
        self.metadata[key] = dict((ExtraArgs or {}).get("Metadata") or {})
    def head_object(self, *, Bucket, Key):
        return {"ContentLength": len(self.objects[Key]), "Metadata": self.metadata.get(Key, {})}
    def get_object(self, *, Bucket, Key): return {"Body": _Body(self.objects[Key])}
    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.objects[Key] = bytes(Body)
        self.metadata[Key] = dict(kwargs.get("Metadata") or {})
        return {}
    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key])
    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator(self)
    def delete_objects(self, *, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)
        return {}


def _config(tmp_path: Path, credentials: Path):
    return SimpleNamespace(
        BACKUP_OFFSITE_ENABLED=True,
        BACKUP_OFFSITE_PREFIX="aionex-production",
        BACKUP_DIR=str(tmp_path / "backups"),
        BACKUP_OFFSITE_SECRET_FILE=str(credentials),
        BACKUP_OFFSITE_RETENTION_COUNT=30,
    )


def test_r2_replication_full_readback_and_restore_staging(tmp_path, monkeypatch):
    endpoint = "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
    credentials = tmp_path / "r2.env"
    credentials.write_text(
        "R2_BACKUP_ENDPOINT=" + endpoint + "\n"
        "R2_BACKUP_BUCKET=aionex-production-backups\n"
        "R2_BACKUP_ACCESS_KEY_ID=test-access\n"
        "R2_BACKUP_SECRET_ACCESS_KEY=test-secret\n"
    )
    credentials.chmod(0o400)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    database = backup_dir / "backup-0123456789abcdef01234567-0123456789abcdef0123456789abcdef.dump"
    database.write_bytes(b"PGDMP-test-database")
    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    replicator = offsite_backup.OffsiteBackupReplicator(_config(tmp_path, credentials))
    replicator.preflight()
    checksum, size = offsite_backup._sha256(database)
    evidence = replicator.replicate(
        backup_id="12345678-1234-1234-1234-123456789abc",
        database_location=str(database),
        database_checksum=checksum,
        database_size=size,
        snapshot=None,
    )
    assert evidence["database"]["sha256"] == checksum
    assert evidence["manifest"]["key"].endswith("/manifest.json")
    staged = replicator.download_for_validation(
        evidence,
        validation_id="87654321-4321-4321-4321-cba987654321",
        attempt_token="attempt-token",
    )
    assert Path(staged.database_location).read_bytes() == database.read_bytes()
    replicator.cleanup_validation(staged.database_location, staged.snapshot_location)
    assert not Path(staged.database_location).exists()


def test_r2_credentials_reject_group_readable_file(tmp_path):
    credentials = tmp_path / "r2.env"
    credentials.write_text("R2_BACKUP_ENDPOINT=https://x.r2.cloudflarestorage.com\n")
    credentials.chmod(0o440)
    try:
        offsite_backup.OffsiteBackupReplicator._credentials(credentials)
    except Exception as exc:
        assert "private R2 backup credential file" in str(exc)
    else:
        raise AssertionError("unsafe credential permissions were accepted")


def test_production_r2_secret_uses_root_only_source_and_private_runtime_copy():
    root = Path(__file__).resolve().parents[3]
    entrypoint = (root / "web-dashboard/backend/scripts/docker-entrypoint.sh").read_text()
    example = (root / "deploy/production/.env.production.example").read_text()
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        compose = (root / relative).read_text()
        start = compose.index("  backup-worker:")
        end = compose.find("\n  communication-worker:", start)
        block = compose[start:] if end < 0 else compose[start:end]
        assert "AIOS_R2_BACKUP_SECRET_SOURCE: /run/operator-secrets/r2-backup-source.env" in block
        assert "/root/.config/aionex/r2-backup/credentials.env" in block
        assert ":/run/operator-secrets/r2-backup-source.env:ro" in block
        assert ":/run/operator-secrets/r2-backup.env:ro" not in block
    assert 'r2_secret_source="${AIOS_R2_BACKUP_SECRET_SOURCE:-}"' in entrypoint
    assert 'r2_secret_runtime="$runtime_dir/r2-backup.env"' in entrypoint
    assert 'install -m 0400 -o aionex -g aionex "$r2_secret_source" "$r2_secret_runtime"' in entrypoint
    assert 'export BACKUP_OFFSITE_SECRET_FILE="$r2_secret_runtime"' in entrypoint
    assert "BACKUP_OFFSITE_SECRET_FILE=/run/aionex/r2-backup.env" in example


def test_r2_replication_includes_media_snapshot(tmp_path, monkeypatch):
    from app.services.file_tree_snapshot import FileTreeSnapshot

    endpoint = "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
    credentials = tmp_path / "r2-media.env"
    credentials.write_text(
        "R2_BACKUP_ENDPOINT=" + endpoint + "\n"
        "R2_BACKUP_BUCKET=aionex-production-backups\n"
        "R2_BACKUP_ACCESS_KEY_ID=test-access\n"
        "R2_BACKUP_SECRET_ACCESS_KEY=test-secret\n"
    )
    credentials.chmod(0o400)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    database = backup_dir / "backup-0123456789abcdef01234567-0123456789abcdef0123456789abcdef.dump"
    database.write_bytes(b"PGDMP-test-database")
    media = backup_dir / "backup-0123456789abcdef01234567-0123456789abcdef0123456789abcdef.media-assets.tar"
    media.write_bytes(b"media-snapshot")
    fake = _FakeS3()
    monkeypatch.setattr(offsite_backup.boto3, "client", lambda *args, **kwargs: fake)
    replicator = offsite_backup.OffsiteBackupReplicator(_config(tmp_path, credentials))
    checksum, size = offsite_backup._sha256(database)
    media_checksum, media_size = offsite_backup._sha256(media)
    evidence = replicator.replicate(
        backup_id="12345678-1234-1234-1234-123456789abc",
        database_location=str(database),
        database_checksum=checksum,
        database_size=size,
        snapshot=None,
        media_snapshot=FileTreeSnapshot(
            location=str(media),
            checksum=media_checksum,
            size_bytes=media_size,
            file_count=2,
            payload_bytes=123,
        ),
    )
    assert evidence["media_snapshot"]["sha256"] == media_checksum
    assert evidence["media_snapshot"]["key"].endswith("/media-assets.tar")
    staged = replicator.download_for_validation(
        evidence,
        validation_id="87654321-4321-4321-4321-cba987654321",
        attempt_token="media-attempt-token",
    )
    assert staged.media_snapshot_location is not None
    assert Path(staged.media_snapshot_location).read_bytes() == media.read_bytes()
    replicator.cleanup_validation(
        staged.database_location,
        staged.snapshot_location,
        staged.media_snapshot_location,
    )
