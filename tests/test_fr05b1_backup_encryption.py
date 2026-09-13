from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "web-dashboard" / "backend" / "app" / "services" / "backup_encryption.py"
SPEC = importlib.util.spec_from_file_location("fr05_backup_encryption", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
backup_encryption = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup_encryption
SPEC.loader.exec_module(backup_encryption)

BACKUP_ID = "12345678-1234-1234-1234-123456789abc"
OBJECT_KEY = "aionex-production/12345678-1234-1234-1234-123456789abc/database.dump.aex1"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _keyring_file(tmp_path: Path, *, active: bytes, old: bytes | None = None) -> Path:
    keys = {
        "bk-active": {
            "key_b64": _b64(active),
            "status": "active",
            "created_at": "2026-09-13T00:00:00Z",
        }
    }
    if old is not None:
        keys["bk-old"] = {
            "key_b64": _b64(old),
            "status": "decrypt_only",
            "created_at": "2026-09-01T00:00:00Z",
        }
    path = tmp_path / "keyring.json"
    path.write_text(
        json.dumps({"schema_version": 1, "active_key_id": "bk-active", "keys": keys}),
        encoding="utf-8",
    )
    path.chmod(0o400)
    return path


def _evidence(path: Path) -> tuple[str, int]:
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def test_streaming_envelope_round_trip_and_private_outputs(tmp_path: Path) -> None:
    keyring = backup_encryption.BackupEncryptionKeyring.load(
        _keyring_file(tmp_path, active=b"A" * 32)
    )
    plaintext = tmp_path / "database.dump"
    plaintext.write_bytes((b"PGDMP-aionex-test-" * 100_000) + b"end")
    checksum, size = _evidence(plaintext)
    encrypted = tmp_path / "database.dump.aex1"
    evidence = backup_encryption.encrypt_file(
        plaintext,
        encrypted,
        backup_id=BACKUP_ID,
        object_role="database",
        r2_object_key=OBJECT_KEY,
        expected_plaintext_sha256=checksum,
        expected_plaintext_size_bytes=size,
        keyring=keyring,
    )
    assert evidence.key_id == "bk-active"
    assert evidence.algorithm == "AES-256-GCM"
    assert evidence.envelope_version == 1
    assert evidence.plaintext_sha256 == checksum
    assert evidence.plaintext_size_bytes == size
    assert evidence.ciphertext_sha256 != checksum
    assert encrypted.read_bytes() != plaintext.read_bytes()
    assert encrypted.stat().st_mode & 0o077 == 0

    restored = tmp_path / "restored.dump"
    result = backup_encryption.decrypt_file(
        encrypted,
        restored,
        backup_id=BACKUP_ID,
        object_role="database",
        r2_object_key=OBJECT_KEY,
        keyring=keyring,
    )
    assert result.plaintext_sha256 == checksum
    assert result.plaintext_size_bytes == size
    assert restored.read_bytes() == plaintext.read_bytes()
    assert restored.stat().st_mode & 0o077 == 0


def test_wrong_key_fails_closed_without_plaintext_output(tmp_path: Path) -> None:
    good = backup_encryption.BackupEncryptionKeyring.load(
        _keyring_file(tmp_path, active=b"A" * 32)
    )
    plaintext = tmp_path / "asset.tar"
    plaintext.write_bytes(b"platform-assets" * 4096)
    checksum, size = _evidence(plaintext)
    encrypted = tmp_path / "asset.tar.aex1"
    backup_encryption.encrypt_file(
        plaintext,
        encrypted,
        backup_id=BACKUP_ID,
        object_role="platform_asset_snapshot",
        r2_object_key=OBJECT_KEY.replace("database.dump", "platform-assets.tar"),
        expected_plaintext_sha256=checksum,
        expected_plaintext_size_bytes=size,
        keyring=good,
    )
    wrong_path = tmp_path / "wrong-keyring.json"
    wrong_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_key_id": "bk-active",
                "keys": {
                    "bk-active": {
                        "key_b64": _b64(b"B" * 32),
                        "status": "active",
                        "created_at": "2026-09-13T00:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    wrong_path.chmod(0o400)
    wrong = backup_encryption.BackupEncryptionKeyring.load(wrong_path)
    output = tmp_path / "wrong-restored.tar"
    with pytest.raises(backup_encryption.BackupEncryptionError, match="authentication failed"):
        backup_encryption.decrypt_file(
            encrypted,
            output,
            backup_id=BACKUP_ID,
            object_role="platform_asset_snapshot",
            r2_object_key=OBJECT_KEY.replace("database.dump", "platform-assets.tar"),
            keyring=wrong,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".*.partial"))


def test_tampered_ciphertext_fails_closed_before_output_is_accepted(tmp_path: Path) -> None:
    keyring = backup_encryption.BackupEncryptionKeyring.load(
        _keyring_file(tmp_path, active=b"C" * 32)
    )
    plaintext = tmp_path / "manifest.json"
    plaintext.write_bytes(b'{"backup_id":"synthetic","roots":11}')
    checksum, size = _evidence(plaintext)
    encrypted = tmp_path / "manifest.json.aex1"
    manifest_key = OBJECT_KEY.replace("database.dump", "manifest.json")
    backup_encryption.encrypt_file(
        plaintext,
        encrypted,
        backup_id=BACKUP_ID,
        object_role="manifest",
        r2_object_key=manifest_key,
        expected_plaintext_sha256=checksum,
        expected_plaintext_size_bytes=size,
        keyring=keyring,
    )
    payload = bytearray(encrypted.read_bytes())
    payload[-17] ^= 0x01
    encrypted.write_bytes(payload)
    output = tmp_path / "tampered-restored.json"
    with pytest.raises(backup_encryption.BackupEncryptionError, match="authentication failed"):
        backup_encryption.decrypt_file(
            encrypted,
            output,
            backup_id=BACKUP_ID,
            object_role="manifest",
            r2_object_key=manifest_key,
            keyring=keyring,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".*.partial"))


def test_aad_prevents_ciphertext_swap_between_object_keys(tmp_path: Path) -> None:
    keyring = backup_encryption.BackupEncryptionKeyring.load(
        _keyring_file(tmp_path, active=b"D" * 32)
    )
    plaintext = tmp_path / "database.dump"
    plaintext.write_bytes(b"db-evidence")
    checksum, size = _evidence(plaintext)
    encrypted = tmp_path / "database.dump.aex1"
    backup_encryption.encrypt_file(
        plaintext,
        encrypted,
        backup_id=BACKUP_ID,
        object_role="database",
        r2_object_key=OBJECT_KEY,
        expected_plaintext_sha256=checksum,
        expected_plaintext_size_bytes=size,
        keyring=keyring,
    )
    output = tmp_path / "swapped.dump"
    with pytest.raises(backup_encryption.BackupEncryptionError, match="authentication failed"):
        backup_encryption.decrypt_file(
            encrypted,
            output,
            backup_id=BACKUP_ID,
            object_role="database",
            r2_object_key=OBJECT_KEY + ".swapped",
            keyring=keyring,
        )
    assert not output.exists()


def test_decrypt_only_generation_can_restore_old_ciphertext(tmp_path: Path) -> None:
    old_path = _keyring_file(tmp_path, active=b"O" * 32)
    old_ring = backup_encryption.BackupEncryptionKeyring.load(old_path)
    plaintext = tmp_path / "old.dump"
    plaintext.write_bytes(b"old-retained-generation")
    checksum, size = _evidence(plaintext)
    encrypted = tmp_path / "old.dump.aex1"
    backup_encryption.encrypt_file(
        plaintext,
        encrypted,
        backup_id=BACKUP_ID,
        object_role="database",
        r2_object_key=OBJECT_KEY,
        expected_plaintext_sha256=checksum,
        expected_plaintext_size_bytes=size,
        keyring=old_ring,
    )

    rotated_path = tmp_path / "rotated.json"
    rotated_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_key_id": "bk-new",
                "keys": {
                    "bk-new": {
                        "key_b64": _b64(b"N" * 32),
                        "status": "active",
                        "created_at": "2026-09-13T01:00:00Z",
                    },
                    "bk-active": {
                        "key_b64": _b64(b"O" * 32),
                        "status": "decrypt_only",
                        "created_at": "2026-09-13T00:00:00Z",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    rotated_path.chmod(0o400)
    rotated = backup_encryption.BackupEncryptionKeyring.load(rotated_path)
    output = tmp_path / "old-restored.dump"
    restored = backup_encryption.decrypt_file(
        encrypted,
        output,
        backup_id=BACKUP_ID,
        object_role="database",
        r2_object_key=OBJECT_KEY,
        keyring=rotated,
    )
    assert restored.key_id == "bk-active"
    assert output.read_bytes() == plaintext.read_bytes()


def test_keyring_rejects_group_readable_hardlink_and_invalid_active_contract(tmp_path: Path) -> None:
    path = _keyring_file(tmp_path, active=b"K" * 32)
    path.chmod(0o440)
    with pytest.raises(backup_encryption.BackupEncryptionError, match="keyring is unavailable or unsafe"):
        backup_encryption.BackupEncryptionKeyring.load(path)

    path.chmod(0o400)
    hardlink = tmp_path / "keyring-hardlink.json"
    hardlink.hardlink_to(path)
    with pytest.raises(backup_encryption.BackupEncryptionError, match="keyring is unavailable or unsafe"):
        backup_encryption.BackupEncryptionKeyring.load(path)
    hardlink.unlink()

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_key_id": "bk-active",
                "keys": {
                    "bk-active": {
                        "key_b64": _b64(b"K" * 32),
                        "status": "decrypt_only",
                        "created_at": "2026-09-13T00:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    invalid.chmod(0o400)
    with pytest.raises(backup_encryption.BackupEncryptionError, match="keyring is unavailable or unsafe"):
        backup_encryption.BackupEncryptionKeyring.load(invalid)


def test_plaintext_evidence_mismatch_removes_ciphertext_output(tmp_path: Path) -> None:
    keyring = backup_encryption.BackupEncryptionKeyring.load(
        _keyring_file(tmp_path, active=b"E" * 32)
    )
    plaintext = tmp_path / "database.dump"
    plaintext.write_bytes(b"stable-plaintext")
    checksum, size = _evidence(plaintext)
    output = tmp_path / "mismatch.aex1"
    with pytest.raises(backup_encryption.BackupEncryptionError, match="changed during encryption"):
        backup_encryption.encrypt_file(
            plaintext,
            output,
            backup_id=BACKUP_ID,
            object_role="database",
            r2_object_key=OBJECT_KEY,
            expected_plaintext_sha256=checksum,
            expected_plaintext_size_bytes=size + 1,
            keyring=keyring,
        )
    assert not output.exists()


def test_fr05b1_directly_pins_cryptography_without_wiring_r2_yet() -> None:
    requirements = (ROOT / "web-dashboard/backend/requirements-runtime.txt").read_text()
    offsite = (ROOT / "web-dashboard/backend/app/services/offsite_backup.py").read_text()
    assert "cryptography==50.0.1" in requirements.splitlines()
    assert "backup_encryption" not in offsite
    assert "AIONEX-R2-ENC" not in offsite
