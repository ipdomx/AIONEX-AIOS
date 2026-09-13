"""Versioned client-side encryption primitives for off-site backup artifacts.

This module is intentionally independent from the R2 transport. FR-05B first proves
that encryption, authentication, key rotation and failure behaviour are correct in
isolation; later slices wire the resulting ciphertext into the existing off-site
replication pipeline.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_MAGIC = b"AIONEX-R2-ENC"
_ENVELOPE_VERSION = 1
_ALGORITHM = "AES-256-GCM"
_NONCE_BYTES = 12
_TAG_BYTES = 16
_HEADER_LENGTH_BYTES = 4
_MAX_HEADER_BYTES = 8192
_CHUNK = 1024 * 1024
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BACKUP_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_ROLES = {"database", "platform_asset_snapshot", "manifest"}
_ALLOWED_KEY_STATES = {"active", "decrypt_only"}


class BackupEncryptionError(RuntimeError):
    """Fail-closed backup encryption/decryption error without secret material."""


@dataclass(frozen=True, slots=True)
class BackupEncryptionKey:
    key_id: str
    key: bytes
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class BackupEncryptionKeyring:
    active_key_id: str
    keys: dict[str, BackupEncryptionKey]

    @property
    def active_key(self) -> BackupEncryptionKey:
        try:
            key = self.keys[self.active_key_id]
        except KeyError as exc:
            raise BackupEncryptionError("backup encryption active key is unavailable") from exc
        if key.status != "active":
            raise BackupEncryptionError("backup encryption active key is not active")
        return key

    def decryption_key(self, key_id: str) -> BackupEncryptionKey:
        try:
            return self.keys[key_id]
        except KeyError as exc:
            raise BackupEncryptionError("required backup decryption key is unavailable") from exc

    @classmethod
    def load(cls, path: Path | str) -> "BackupEncryptionKeyring":
        keyring_path = Path(path)
        try:
            metadata = keyring_path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise OSError("keyring is not a regular file")
            if metadata.st_nlink != 1:
                raise OSError("keyring is hard-linked")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("keyring grants group/other permissions")
            payload = json.loads(
                keyring_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
            )
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "active_key_id",
                "keys",
            }:
                raise ValueError("keyring schema is invalid")
            if payload["schema_version"] != 1:
                raise ValueError("keyring schema version is unsupported")
            active_key_id = _validate_key_id(payload["active_key_id"])
            raw_keys = payload["keys"]
            if not isinstance(raw_keys, dict) or not raw_keys:
                raise ValueError("keyring keys are invalid")
            keys: dict[str, BackupEncryptionKey] = {}
            active_count = 0
            for raw_id, raw_entry in raw_keys.items():
                key_id = _validate_key_id(raw_id)
                if not isinstance(raw_entry, dict) or set(raw_entry) != {
                    "key_b64",
                    "status",
                    "created_at",
                }:
                    raise ValueError("keyring key entry is invalid")
                status = str(raw_entry["status"])
                if status not in _ALLOWED_KEY_STATES:
                    raise ValueError("keyring key state is invalid")
                created_at = _validate_timestamp(raw_entry["created_at"])
                key = _decode_key(raw_entry["key_b64"])
                keys[key_id] = BackupEncryptionKey(key_id, key, status, created_at)
                active_count += int(status == "active")
            if active_count != 1 or active_key_id not in keys or keys[active_key_id].status != "active":
                raise ValueError("keyring active-key contract is invalid")
            return cls(active_key_id=active_key_id, keys=keys)
        except BackupEncryptionError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BackupEncryptionError("backup encryption keyring is unavailable or unsafe") from exc


@dataclass(frozen=True, slots=True)
class EncryptedBackupArtifact:
    location: str
    key_id: str
    envelope_version: int
    algorithm: str
    plaintext_sha256: str
    plaintext_size_bytes: int
    ciphertext_sha256: str
    ciphertext_size_bytes: int


@dataclass(frozen=True, slots=True)
class DecryptedBackupArtifact:
    location: str
    key_id: str
    plaintext_sha256: str
    plaintext_size_bytes: int


def encrypt_file(
    source: Path | str,
    destination: Path | str,
    *,
    backup_id: str,
    object_role: str,
    r2_object_key: str,
    expected_plaintext_sha256: str,
    expected_plaintext_size_bytes: int,
    keyring: BackupEncryptionKeyring,
) -> EncryptedBackupArtifact:
    """Encrypt one regular file into the versioned AIONEX R2 envelope."""
    source_path = Path(source)
    destination_path = Path(destination)
    _validate_regular_source(source_path)
    _validate_binding(backup_id, object_role, r2_object_key)
    checksum = _validate_sha256(expected_plaintext_sha256)
    size = _validate_size(expected_plaintext_size_bytes)
    key = keyring.active_key
    nonce = os.urandom(_NONCE_BYTES)
    header = _header(key.key_id, nonce, checksum, size)
    header_bytes = _canonical_json(header)
    aad = _associated_data(
        backup_id=backup_id,
        object_role=object_role,
        r2_object_key=r2_object_key,
        header=header,
    )
    encryptor = Cipher(algorithms.AES(key.key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    digest = hashlib.sha256()
    actual_size = 0
    _ensure_destination_parent(destination_path)
    try:
        with source_path.open("rb") as source_stream, destination_path.open("xb") as output:
            os.chmod(destination_path, 0o600)
            output.write(_MAGIC)
            output.write(struct.pack(">I", len(header_bytes)))
            output.write(header_bytes)
            for chunk in iter(lambda: source_stream.read(_CHUNK), b""):
                digest.update(chunk)
                actual_size += len(chunk)
                output.write(encryptor.update(chunk))
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
        if digest.hexdigest() != checksum or actual_size != size:
            raise BackupEncryptionError("backup plaintext changed during encryption")
        ciphertext_sha256, ciphertext_size = _sha256_regular(destination_path)
        return EncryptedBackupArtifact(
            location=str(destination_path),
            key_id=key.key_id,
            envelope_version=_ENVELOPE_VERSION,
            algorithm=_ALGORITHM,
            plaintext_sha256=checksum,
            plaintext_size_bytes=size,
            ciphertext_sha256=ciphertext_sha256,
            ciphertext_size_bytes=ciphertext_size,
        )
    except Exception as exc:
        destination_path.unlink(missing_ok=True)
        if isinstance(exc, BackupEncryptionError):
            raise
        raise BackupEncryptionError("backup artifact encryption failed") from exc


def decrypt_file(
    source: Path | str,
    destination: Path | str,
    *,
    backup_id: str,
    object_role: str,
    r2_object_key: str,
    keyring: BackupEncryptionKeyring,
) -> DecryptedBackupArtifact:
    """Authenticate and decrypt an envelope, publishing plaintext only after verification."""
    source_path = Path(source)
    destination_path = Path(destination)
    _validate_regular_source(source_path)
    _validate_binding(backup_id, object_role, r2_object_key)
    _ensure_destination_parent(destination_path)
    temporary_path = _private_temporary_path(destination_path)
    try:
        with source_path.open("rb") as source_stream:
            header, body_offset, ciphertext_bytes, tag = _read_envelope(source_stream, source_path)
            key = keyring.decryption_key(str(header["key_id"]))
            nonce = _decode_nonce(header["nonce"])
            aad = _associated_data(
                backup_id=backup_id,
                object_role=object_role,
                r2_object_key=r2_object_key,
                header=header,
            )
            decryptor = Cipher(algorithms.AES(key.key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(aad)
            source_stream.seek(body_offset)
            remaining = ciphertext_bytes
            digest = hashlib.sha256()
            plaintext_size = 0
            with temporary_path.open("xb") as output:
                os.chmod(temporary_path, 0o600)
                while remaining:
                    chunk = source_stream.read(min(_CHUNK, remaining))
                    if not chunk:
                        raise BackupEncryptionError("backup ciphertext is truncated")
                    remaining -= len(chunk)
                    plaintext = decryptor.update(chunk)
                    if plaintext:
                        digest.update(plaintext)
                        plaintext_size += len(plaintext)
                        output.write(plaintext)
                final = decryptor.finalize()
                if final:
                    digest.update(final)
                    plaintext_size += len(final)
                    output.write(final)
            expected_checksum = _validate_sha256(header["plaintext_sha256"])
            expected_size = _validate_size(header["plaintext_size_bytes"])
            if digest.hexdigest() != expected_checksum or plaintext_size != expected_size:
                raise BackupEncryptionError("decrypted backup plaintext evidence does not match envelope")
            _publish_private_temporary(temporary_path, destination_path)
            return DecryptedBackupArtifact(
                location=str(destination_path),
                key_id=key.key_id,
                plaintext_sha256=expected_checksum,
                plaintext_size_bytes=expected_size,
            )
    except InvalidTag as exc:
        temporary_path.unlink(missing_ok=True)
        raise BackupEncryptionError("backup ciphertext authentication failed") from exc
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        if isinstance(exc, BackupEncryptionError):
            raise
        raise BackupEncryptionError("backup artifact decryption failed") from exc


def _private_temporary_path(destination: Path) -> Path:
    for _ in range(8):
        candidate = destination.with_name(
            f".{destination.name}.{secrets.token_hex(8)}.partial"
        )
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise BackupEncryptionError("backup encryption temporary destination is unavailable")


def _publish_private_temporary(temporary: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise BackupEncryptionError("backup encryption destination already exists")
    os.replace(temporary, destination)


def _read_envelope(stream, source_path: Path) -> tuple[dict[str, Any], int, int, bytes]:
    magic = stream.read(len(_MAGIC))
    if magic != _MAGIC:
        raise BackupEncryptionError("backup encryption envelope magic is invalid")
    raw_header_size = stream.read(_HEADER_LENGTH_BYTES)
    if len(raw_header_size) != _HEADER_LENGTH_BYTES:
        raise BackupEncryptionError("backup encryption envelope header is truncated")
    header_size = struct.unpack(">I", raw_header_size)[0]
    if not 1 <= header_size <= _MAX_HEADER_BYTES:
        raise BackupEncryptionError("backup encryption envelope header length is invalid")
    header_bytes = stream.read(header_size)
    if len(header_bytes) != header_size:
        raise BackupEncryptionError("backup encryption envelope header is truncated")
    try:
        header = json.loads(header_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BackupEncryptionError("backup encryption envelope header is invalid") from exc
    _validate_header(header)
    body_offset = len(_MAGIC) + _HEADER_LENGTH_BYTES + header_size
    total_size = source_path.stat().st_size
    ciphertext_bytes = total_size - body_offset - _TAG_BYTES
    if ciphertext_bytes < 0:
        raise BackupEncryptionError("backup encryption envelope is truncated")
    stream.seek(total_size - _TAG_BYTES)
    tag = stream.read(_TAG_BYTES)
    if len(tag) != _TAG_BYTES:
        raise BackupEncryptionError("backup encryption authentication tag is missing")
    return header, body_offset, ciphertext_bytes, tag


def _header(key_id: str, nonce: bytes, plaintext_sha256: str, plaintext_size: int) -> dict[str, Any]:
    return {
        "algorithm": _ALGORITHM,
        "envelope_version": _ENVELOPE_VERSION,
        "key_id": key_id,
        "nonce": _b64url(nonce),
        "plaintext_sha256": plaintext_sha256,
        "plaintext_size_bytes": plaintext_size,
    }


def _validate_header(header: Any) -> None:
    if not isinstance(header, dict) or set(header) != {
        "algorithm",
        "envelope_version",
        "key_id",
        "nonce",
        "plaintext_sha256",
        "plaintext_size_bytes",
    }:
        raise BackupEncryptionError("backup encryption envelope header schema is invalid")
    if header["algorithm"] != _ALGORITHM or header["envelope_version"] != _ENVELOPE_VERSION:
        raise BackupEncryptionError("backup encryption envelope version is unsupported")
    _validate_key_id(header["key_id"])
    _decode_nonce(header["nonce"])
    _validate_sha256(header["plaintext_sha256"])
    _validate_size(header["plaintext_size_bytes"])


def _associated_data(*, backup_id: str, object_role: str, r2_object_key: str, header: dict[str, Any]) -> bytes:
    return _canonical_json(
        {
            "backup_id": backup_id,
            "object_role": object_role,
            "r2_object_key": r2_object_key,
            **header,
        }
    )


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _validate_binding(backup_id: str, object_role: str, r2_object_key: str) -> None:
    if not isinstance(backup_id, str) or not _BACKUP_ID.fullmatch(backup_id):
        raise BackupEncryptionError("backup identifier is invalid")
    if object_role not in _ALLOWED_ROLES:
        raise BackupEncryptionError("backup encryption object role is invalid")
    if not isinstance(r2_object_key, str) or not r2_object_key or len(r2_object_key) > 1024 or "\x00" in r2_object_key:
        raise BackupEncryptionError("backup encryption object key is invalid")


def _validate_regular_source(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BackupEncryptionError("backup artifact is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise BackupEncryptionError("backup artifact is not a safe regular file")


def _ensure_destination_parent(path: Path) -> None:
    if not path.parent.exists() or not path.parent.is_dir():
        raise BackupEncryptionError("backup encryption destination directory is unavailable")
    if path.exists() or path.is_symlink():
        raise BackupEncryptionError("backup encryption destination already exists")


def _validate_key_id(value: Any) -> str:
    if not isinstance(value, str) or not _KEY_ID.fullmatch(value):
        raise ValueError("backup encryption key identifier is invalid")
    return value


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("backup encryption key timestamp is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("backup encryption key timestamp must be timezone-aware")
    return value


def _validate_sha256(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise BackupEncryptionError("backup plaintext checksum evidence is invalid")
    return value


def _validate_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BackupEncryptionError("backup plaintext size evidence is invalid")
    return value


def _decode_key(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("backup encryption key material is invalid")
    try:
        key = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValueError("backup encryption key material is invalid") from exc
    if len(key) != 32:
        raise ValueError("backup encryption key must be 32 bytes")
    return key


def _decode_nonce(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise BackupEncryptionError("backup encryption nonce is invalid")
    try:
        nonce = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise BackupEncryptionError("backup encryption nonce is invalid") from exc
    if len(nonce) != _NONCE_BYTES:
        raise BackupEncryptionError("backup encryption nonce is invalid")
    return nonce


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _sha256_regular(path: Path) -> tuple[str, int]:
    _validate_regular_source(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result
