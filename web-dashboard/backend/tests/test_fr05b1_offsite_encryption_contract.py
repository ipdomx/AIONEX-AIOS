from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.services.backup_executor import BackupExecutionError
from app.services.offsite_encryption import EncryptionContext, OffsiteEncryption, OffsiteEncryptionKeyring


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _keyring(path: Path, *, active_byte: int = 7, old_byte: int = 8) -> Path:
    payload = {
        "schema_version": 1,
        "active_key_id": "primary-v2",
        "keys": {
            "primary-v2": {
                "key_b64": _b64url(bytes([active_byte]) * 32),
                "status": "active",
                "created_at": "2026-09-13T00:00:00Z",
                "rotation_generation": 2,
            },
            "primary-v1": {
                "key_b64": _b64url(bytes([old_byte]) * 32),
                "status": "decrypt_only",
                "created_at": "2026-09-12T00:00:00Z",
                "rotation_generation": 1,
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o400)
    return path


def _context() -> EncryptionContext:
    return EncryptionContext(
        backup_id="12345678-1234-1234-1234-123456789abc",
        object_role="database",
        r2_object_key="aionex-production/123/database.dump.aex1",
    )


def test_streaming_envelope_round_trip_and_plaintext_not_visible(tmp_path: Path):
    source = tmp_path / "database.dump"
    source.write_bytes((b"PGDMP-sensitive-tenant-data-" * 4096) + b"END")
    encrypted = tmp_path / "database.dump.aex1"
    restored = tmp_path / "restored.dump"
    cipher = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring.json")))
    evidence = cipher.encrypt_file(source, encrypted, context=_context())
    assert evidence.algorithm == "AES-256-GCM"
    assert evidence.envelope_version == 1
    assert evidence.key_id == "primary-v2"
    assert encrypted.read_bytes().startswith(b"AIONEX-R2-ENC")
    assert source.read_bytes()[:64] not in encrypted.read_bytes()
    checksum, size, key_id = cipher.decrypt_file(encrypted, restored, context=_context())
    assert restored.read_bytes() == source.read_bytes()
    assert checksum == evidence.plaintext_sha256
    assert size == evidence.plaintext_size_bytes
    assert key_id == "primary-v2"


def test_wrong_key_tamper_and_aad_change_fail_closed(tmp_path: Path):
    source = tmp_path / "assets.tar"
    source.write_bytes(b"asset-payload" * 4096)
    encrypted = tmp_path / "assets.aex1"
    first = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring-a.json", active_byte=1)))
    first.encrypt_file(source, encrypted, context=_context())

    wrong = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring-b.json", active_byte=2)))
    with pytest.raises(BackupExecutionError, match="wrong or the object is corrupted"):
        wrong.decrypt_file(encrypted, tmp_path / "wrong.out", context=_context())
    assert not (tmp_path / "wrong.out").exists()

    changed_context = EncryptionContext(
        backup_id=_context().backup_id,
        object_role="platform_asset_snapshot",
        r2_object_key="aionex-production/123/platform-assets.tar.aex1",
    )
    with pytest.raises(BackupExecutionError, match="wrong or the object is corrupted"):
        first.decrypt_file(encrypted, tmp_path / "aad.out", context=changed_context)
    assert not (tmp_path / "aad.out").exists()

    data = bytearray(encrypted.read_bytes())
    data[len(data) // 2] ^= 0x01
    corrupt = tmp_path / "corrupt.aex1"
    corrupt.write_bytes(data)
    with pytest.raises(BackupExecutionError, match="wrong or the object is corrupted"):
        first.decrypt_file(corrupt, tmp_path / "corrupt.out", context=_context())
    assert not (tmp_path / "corrupt.out").exists()


def test_keyring_is_private_has_one_active_key_and_reports_no_secret_material(tmp_path: Path):
    path = _keyring(tmp_path / "keyring.json")
    keyring = OffsiteEncryptionKeyring(str(path))
    assert keyring.active_key_id == "primary-v2"
    assert keyring.active().status == "active"
    metadata = keyring.reportable_metadata()
    assert {item["status"] for item in metadata} == {"active", "decrypt_only"}
    assert "key_b64" not in json.dumps(metadata)

    path.chmod(0o440)
    with pytest.raises(BackupExecutionError, match="backup-encryption keyring"):
        OffsiteEncryptionKeyring(str(path))


def test_decrypt_only_key_remains_usable_for_retained_backup(tmp_path: Path):
    old_only = {
        "schema_version": 1,
        "active_key_id": "primary-v1",
        "keys": {
            "primary-v1": {
                "key_b64": _b64url(bytes([8]) * 32),
                "status": "active",
                "created_at": "2026-09-12T00:00:00Z",
                "rotation_generation": 1,
            }
        },
    }
    old_path = tmp_path / "old.json"
    old_path.write_text(json.dumps(old_only), encoding="utf-8")
    old_path.chmod(0o400)
    source = tmp_path / "db"
    source.write_bytes(b"retained-backup")
    encrypted = tmp_path / "db.aex1"
    OffsiteEncryption(keyring_file=str(old_path)).encrypt_file(source, encrypted, context=_context())

    rotated = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "rotated.json", active_byte=7, old_byte=8)))
    restored = tmp_path / "restored"
    _, _, key_id = rotated.decrypt_file(encrypted, restored, context=_context())
    assert restored.read_bytes() == source.read_bytes()
    assert key_id == "primary-v1"


def test_production_contract_mounts_keyring_separately_from_r2_credentials():
    root = Path(__file__).resolve().parents[3]
    entrypoint = (root / "web-dashboard/backend/scripts/docker-entrypoint.sh").read_text()
    example = (root / "deploy/production/.env.production.example").read_text()
    compose = (root / "web-dashboard/docker-compose.production.yml").read_text()
    start = compose.index("  backup-worker:")
    end = compose.index("\n  communication-worker:", start)
    block = compose[start:end]
    assert "BACKUP_OFFSITE_ENCRYPTION_REQUIRED: \"true\"" in block
    assert "AIOS_BACKUP_ENCRYPTION_KEYRING_SOURCE: /run/operator-secrets/backup-encryption/keyring.json" in block
    assert "/root/.config/aionex/backup-encryption/keyring.json" in block
    assert "/root/.config/aionex/r2-backup/credentials.env" in block
    assert "backup-encryption/keyring.json:ro" in block
    assert "r2-backup-source.env:ro" in block
    assert 'install -m 0400 -o aionex -g aionex "$backup_encryption_keyring_source" "$backup_encryption_keyring_runtime"' in entrypoint
    assert "BACKUP_OFFSITE_ENCRYPTION_REQUIRED=true" in example
    assert "BACKUP_OFFSITE_ENCRYPTION_KEYRING_FILE=/run/aionex/backup-encryption-keyring.json" in example
