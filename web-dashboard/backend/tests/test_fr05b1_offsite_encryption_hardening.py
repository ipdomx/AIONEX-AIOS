from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import struct

import pytest

from app.services import offsite_encryption as encryption_module
from app.services.backup_executor import BackupExecutionError
from app.services.offsite_encryption import EncryptionContext, OffsiteEncryption, OffsiteEncryptionKeyring


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _keyring(path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "active_key_id": "primary-v2",
        "keys": {
            "primary-v2": {
                "key_b64": _b64url(bytes([7]) * 32),
                "status": "active",
                "created_at": "2026-09-13T00:00:00Z",
                "rotation_generation": 2,
            }
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


def test_keyring_rejects_hardlinks_duplicate_fields_and_unknown_fields(tmp_path: Path):
    original = _keyring(tmp_path / "keyring.json")
    hardlink = tmp_path / "keyring-hardlink.json"
    os.link(original, hardlink)
    with pytest.raises(BackupExecutionError, match="keyring is unavailable or unsafe"):
        OffsiteEncryptionKeyring(str(original))

    original.unlink()
    hardlink.unlink()
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":1,"schema_version":1,"active_key_id":"primary-v2","keys":{}}',
        encoding="utf-8",
    )
    duplicate.chmod(0o400)
    with pytest.raises(BackupExecutionError, match="keyring is unavailable or unsafe"):
        OffsiteEncryptionKeyring(str(duplicate))

    unknown = _keyring(tmp_path / "unknown.json")
    raw = json.loads(unknown.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    unknown.chmod(0o600)
    unknown.write_text(json.dumps(raw), encoding="utf-8")
    unknown.chmod(0o400)
    with pytest.raises(BackupExecutionError, match="keyring is unavailable or unsafe"):
        OffsiteEncryptionKeyring(str(unknown))


def test_source_symlinks_and_hardlinks_are_rejected(tmp_path: Path):
    cipher = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring.json")))
    source = tmp_path / "database.dump"
    source.write_bytes(b"sensitive")
    symlink = tmp_path / "database-link.dump"
    symlink.symlink_to(source)
    with pytest.raises(BackupExecutionError, match="unavailable or unsafe"):
        cipher.encrypt_file(symlink, tmp_path / "symlink.aex1", context=_context())

    hardlink = tmp_path / "database-hardlink.dump"
    os.link(source, hardlink)
    with pytest.raises(BackupExecutionError, match="unavailable or unsafe"):
        cipher.encrypt_file(source, tmp_path / "hardlink.aex1", context=_context())


def test_existing_destinations_are_never_overwritten(tmp_path: Path):
    cipher = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring.json")))
    source = tmp_path / "database.dump"
    source.write_bytes(b"sensitive" * 2048)
    encrypted = tmp_path / "database.dump.aex1"
    encrypted.write_bytes(b"keep-encrypted")
    with pytest.raises(BackupExecutionError, match="destination already exists"):
        cipher.encrypt_file(source, encrypted, context=_context())
    assert encrypted.read_bytes() == b"keep-encrypted"

    encrypted.unlink()
    cipher.encrypt_file(source, encrypted, context=_context())
    restored = tmp_path / "restored.dump"
    restored.write_bytes(b"keep-restored")
    with pytest.raises(BackupExecutionError, match="destination already exists"):
        cipher.decrypt_file(encrypted, restored, context=_context())
    assert restored.read_bytes() == b"keep-restored"


def test_changed_source_fails_closed_and_removes_private_stage(tmp_path: Path, monkeypatch):
    cipher = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring.json")))
    source = tmp_path / "database.dump"
    source.write_bytes(b"sensitive" * 2048)
    destination = tmp_path / "database.dump.aex1"

    original_hash_fd = encryption_module._hash_fd

    def wrong_evidence(descriptor: int) -> tuple[str, int]:
        _digest, size = original_hash_fd(descriptor)
        return "0" * 64, size

    monkeypatch.setattr(encryption_module, "_hash_fd", wrong_evidence)
    with pytest.raises(BackupExecutionError, match="changed during encryption"):
        cipher.encrypt_file(source, destination, context=_context())
    assert not destination.exists()
    assert list(tmp_path.glob(".database.dump.aex1.*.partial")) == []


def test_authentication_failure_never_publishes_plaintext_or_leaves_stage(tmp_path: Path):
    cipher = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring.json")))
    source = tmp_path / "database.dump"
    source.write_bytes(b"sensitive" * 4096)
    encrypted = tmp_path / "database.dump.aex1"
    cipher.encrypt_file(source, encrypted, context=_context())

    tampered = bytearray(encrypted.read_bytes())
    tampered[-1] ^= 1
    encrypted.write_bytes(tampered)
    restored = tmp_path / "restored.dump"
    with pytest.raises(BackupExecutionError, match="authentication failed"):
        cipher.decrypt_file(encrypted, restored, context=_context())
    assert not restored.exists()
    assert list(tmp_path.glob(".restored.dump.*.partial")) == []


def test_duplicate_header_fields_fail_before_plaintext_publication(tmp_path: Path):
    cipher = OffsiteEncryption(keyring_file=str(_keyring(tmp_path / "keyring.json")))
    header = (
        b'{"algorithm":"AES-256-GCM","algorithm":"AES-256-GCM",'
        b'"envelope_version":1,"key_id":"primary-v2","nonce":"AAAAAAAAAAAAAAAA",'
        b'"plaintext_sha256":"' + (b"0" * 64) + b'","plaintext_size_bytes":0}'
    )
    malformed = tmp_path / "duplicate-header.aex1"
    malformed.write_bytes(b"AIONEX-R2-ENC" + struct.pack(">I", len(header)) + header + (b"0" * 16))
    restored = tmp_path / "restored.dump"
    with pytest.raises(BackupExecutionError, match="header is invalid"):
        cipher.decrypt_file(malformed, restored, context=_context())
    assert not restored.exists()


def test_reportable_rotation_metadata_excludes_key_material(tmp_path: Path):
    metadata = OffsiteEncryptionKeyring(str(_keyring(tmp_path / "keyring.json"))).reportable_metadata()
    assert metadata == [
        {
            "key_id": "primary-v2",
            "status": "active",
            "created_at": "2026-09-13T00:00:00Z",
            "rotation_generation": 2,
        }
    ]
    serialized = json.dumps(metadata)
    assert "key_b64" not in serialized
    assert _b64url(bytes([7]) * 32) not in serialized
