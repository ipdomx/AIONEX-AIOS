from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.backup_executor import BackupExecutionError
from app.services.offsite_encryption import OffsiteEncryption


def _key(path: Path, byte: int = 7) -> Path:
    path.write_bytes(base64.b64encode(bytes([byte]) * 32) + b"\n")
    path.chmod(0o400)
    return path


def test_client_side_envelope_round_trip_and_plaintext_not_visible(tmp_path: Path):
    key = _key(tmp_path / "key")
    source = tmp_path / "database.dump"
    source.write_bytes((b"PGDMP-sensitive-tenant-data-" * 4096) + b"END")
    encrypted = tmp_path / "database.dump.aionexenc"
    restored = tmp_path / "restored.dump"
    cipher = OffsiteEncryption(key_file=str(key), key_id="primary-v1")
    evidence = cipher.encrypt_file(source, encrypted, aad=b"backup-id/database.dump")
    assert evidence.algorithm == "AES-256-GCM"
    assert evidence.key_id == "primary-v1"
    assert source.read_bytes()[:64] not in encrypted.read_bytes()
    checksum, size = cipher.decrypt_file(encrypted, restored, aad=b"backup-id/database.dump")
    assert restored.read_bytes() == source.read_bytes()
    assert checksum == evidence.plaintext_sha256
    assert size == evidence.plaintext_size_bytes


def test_wrong_key_and_corruption_fail_closed(tmp_path: Path):
    source = tmp_path / "assets.tar"
    source.write_bytes(b"asset-payload" * 4096)
    encrypted = tmp_path / "assets.aionexenc"
    first = OffsiteEncryption(key_file=str(_key(tmp_path / "key-a", 1)), key_id="primary-v1")
    first.encrypt_file(source, encrypted, aad=b"backup-id/assets")

    wrong = OffsiteEncryption(key_file=str(_key(tmp_path / "key-b", 2)), key_id="other-v1")
    with pytest.raises(BackupExecutionError, match="wrong or the object is corrupted"):
        wrong.decrypt_file(encrypted, tmp_path / "wrong.out", aad=b"backup-id/assets")
    assert not (tmp_path / "wrong.out").exists()

    data = bytearray(encrypted.read_bytes())
    data[len(data) // 2] ^= 0x01
    corrupt = tmp_path / "corrupt.aionexenc"
    corrupt.write_bytes(data)
    with pytest.raises(BackupExecutionError, match="wrong or the object is corrupted"):
        first.decrypt_file(corrupt, tmp_path / "corrupt.out", aad=b"backup-id/assets")
    assert not (tmp_path / "corrupt.out").exists()


def test_key_file_must_be_private_and_exactly_256_bits(tmp_path: Path):
    group_readable = _key(tmp_path / "group-key")
    group_readable.chmod(0o440)
    with pytest.raises(BackupExecutionError, match="private off-site encryption key"):
        OffsiteEncryption(key_file=str(group_readable), key_id="primary-v1")
    short = tmp_path / "short-key"
    short.write_bytes(base64.b64encode(b"too-short"))
    short.chmod(0o400)
    with pytest.raises(BackupExecutionError, match="private off-site encryption key"):
        OffsiteEncryption(key_file=str(short), key_id="primary-v1")


def test_production_contract_mounts_key_separately_from_r2_credentials():
    root = Path(__file__).resolve().parents[3]
    entrypoint = (root / "web-dashboard/backend/scripts/docker-entrypoint.sh").read_text()
    example = (root / "deploy/production/.env.production.example").read_text()
    compose = (root / "web-dashboard/docker-compose.production.yml").read_text()
    start = compose.index("  backup-worker:")
    end = compose.index("\n  communication-worker:", start)
    block = compose[start:end]
    assert "BACKUP_OFFSITE_ENCRYPTION_REQUIRED: \"true\"" in block
    assert "AIOS_R2_BACKUP_ENCRYPTION_KEY_SOURCE: /run/operator-secrets/r2-backup-encryption-key-source" in block
    assert "/root/.config/aionex/r2-backup/encryption.key" in block
    assert "/root/.config/aionex/r2-backup/credentials.env" in block
    assert "r2-backup-encryption-key-source:ro" in block
    assert "r2-backup-source.env:ro" in block
    assert 'install -m 0400 -o aionex -g aionex "$r2_encryption_key_source" "$r2_encryption_key_runtime"' in entrypoint
    assert "BACKUP_OFFSITE_ENCRYPTION_REQUIRED=true" in example
    assert "BACKUP_OFFSITE_ENCRYPTION_KEY_ID=primary-v1" in example
