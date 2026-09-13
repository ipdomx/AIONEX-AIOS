"""Versioned client-side authenticated encryption for off-site backup objects.

FR-05B1 adds the cryptographic envelope and keyring parser only.  R2 wiring stays
in ``offsite_backup.py`` for the next slice.  Key material is loaded from a
separate root-managed keyring and is never returned in evidence or logs.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.services.backup_executor import BackupExecutionError

_MAGIC = b"AIONEX-R2-ENC"
_ENVELOPE_VERSION = 1
_ALGORITHM = "AES-256-GCM"
_NONCE_BYTES = 12
_TAG_BYTES = 16
_CHUNK = 1024 * 1024
_ALLOWED_KEY_STATES = {"active", "decrypt_only"}


@dataclass(frozen=True, slots=True)
class EncryptionContext:
    backup_id: str
    object_role: str
    r2_object_key: str


@dataclass(frozen=True, slots=True)
class EncryptedArtifact:
    location: str
    ciphertext_sha256: str
    ciphertext_size_bytes: int
    plaintext_sha256: str
    plaintext_size_bytes: int
    key_id: str
    algorithm: str = _ALGORITHM
    envelope_version: int = _ENVELOPE_VERSION


@dataclass(frozen=True, slots=True)
class _KeyRecord:
    key_id: str
    key: bytes
    status: str
    created_at: str
    rotation_generation: int | None = None


def _b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("empty base64url key")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode((value + padding).encode("ascii"), altchars=b"-_", validate=True)


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _plaintext_evidence(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("source is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(_CHUNK), b""):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


class OffsiteEncryptionKeyring:
    """Strict parser for the operator-owned FR-05 backup-encryption keyring."""

    def __init__(self, path: str) -> None:
        self._records, self.active_key_id = self._load(Path(path))

    @staticmethod
    def _load(path: Path) -> tuple[dict[str, _KeyRecord], str]:
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise OSError("keyring is not a regular file")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("keyring grants group/other permissions")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                raise ValueError("unsupported keyring schema")
            active_key_id = raw.get("active_key_id")
            keys = raw.get("keys")
            if not isinstance(active_key_id, str) or not active_key_id:
                raise ValueError("active key id is missing")
            if not isinstance(keys, dict) or not keys:
                raise ValueError("keyring has no keys")
            records: dict[str, _KeyRecord] = {}
            for key_id, item in keys.items():
                if not isinstance(key_id, str) or not key_id or not isinstance(item, dict):
                    raise ValueError("invalid key record")
                status = item.get("status")
                created_at = item.get("created_at")
                if status not in _ALLOWED_KEY_STATES or not isinstance(created_at, str) or not created_at:
                    raise ValueError("invalid key lifecycle metadata")
                key_b64 = item.get("key_b64")
                if not isinstance(key_b64, str):
                    raise ValueError("key material is missing")
                key = _b64url_decode(key_b64)
                if len(key) != 32:
                    raise ValueError("key is not 256 bits")
                generation = item.get("rotation_generation")
                if generation is not None and (not isinstance(generation, int) or generation < 1):
                    raise ValueError("rotation generation is invalid")
                records[key_id] = _KeyRecord(key_id, key, status, created_at, generation)
            active = records.get(active_key_id)
            if active is None or active.status != "active":
                raise ValueError("active key id does not reference an active key")
            active_records = [record for record in records.values() if record.status == "active"]
            if len(active_records) != 1:
                raise ValueError("keyring must contain exactly one active key")
            return records, active_key_id
        except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
            raise BackupExecutionError(
                "off-site encryption configuration",
                "The private backup-encryption keyring is unavailable or unsafe",
                status_code=503,
            ) from exc

    def active(self) -> _KeyRecord:
        return self._records[self.active_key_id]

    def for_decryption(self, key_id: str) -> _KeyRecord:
        record = self._records.get(key_id)
        if record is None:
            raise BackupExecutionError(
                "off-site decryption",
                "The encryption key required by this retained backup is unavailable",
                status_code=409,
            )
        return record

    def reportable_metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "key_id": record.key_id,
                "status": record.status,
                "created_at": record.created_at,
                "rotation_generation": record.rotation_generation,
            }
            for record in sorted(self._records.values(), key=lambda item: item.key_id)
        ]


class OffsiteEncryption:
    def __init__(self, *, keyring_file: str) -> None:
        self._keyring = OffsiteEncryptionKeyring(keyring_file)

    @staticmethod
    def _aad(context: EncryptionContext, header: dict[str, Any]) -> bytes:
        return _canonical_json(
            {
                "backup_id": context.backup_id,
                "object_role": context.object_role,
                "r2_object_key": context.r2_object_key,
                "envelope_version": header["envelope_version"],
                "algorithm": header["algorithm"],
                "key_id": header["key_id"],
                "plaintext_sha256": header["plaintext_sha256"],
                "plaintext_size_bytes": header["plaintext_size_bytes"],
            }
        )

    def encrypt_file(self, source: Path, destination: Path, *, context: EncryptionContext) -> EncryptedArtifact:
        plaintext_sha256, plaintext_size = _plaintext_evidence(source)
        record = self._keyring.active()
        nonce = os.urandom(_NONCE_BYTES)
        header = {
            "envelope_version": _ENVELOPE_VERSION,
            "algorithm": _ALGORITHM,
            "key_id": record.key_id,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
            "plaintext_sha256": plaintext_sha256,
            "plaintext_size_bytes": plaintext_size,
        }
        header_bytes = _canonical_json(header)
        aad = self._aad(context, header)
        ciphertext_digest = hashlib.sha256()
        try:
            source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                destination_fd = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    encryptor = Cipher(algorithms.AES(record.key), modes.GCM(nonce)).encryptor()
                    encryptor.authenticate_additional_data(aad)
                    prefix = _MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
                    os.write(destination_fd, prefix)
                    ciphertext_digest.update(prefix)
                    with os.fdopen(source_fd, "rb", closefd=False) as stream:
                        for chunk in iter(lambda: stream.read(_CHUNK), b""):
                            encrypted = encryptor.update(chunk)
                            if encrypted:
                                os.write(destination_fd, encrypted)
                                ciphertext_digest.update(encrypted)
                    final = encryptor.finalize()
                    if final:
                        os.write(destination_fd, final)
                        ciphertext_digest.update(final)
                    os.write(destination_fd, encryptor.tag)
                    ciphertext_digest.update(encryptor.tag)
                    os.fsync(destination_fd)
                finally:
                    os.close(destination_fd)
            finally:
                os.close(source_fd)
            return EncryptedArtifact(
                location=str(destination),
                ciphertext_sha256=ciphertext_digest.hexdigest(),
                ciphertext_size_bytes=destination.stat().st_size,
                plaintext_sha256=plaintext_sha256,
                plaintext_size_bytes=plaintext_size,
                key_id=record.key_id,
            )
        except FileExistsError as exc:
            raise BackupExecutionError("off-site encryption", "Encrypted staging path already exists", status_code=409) from exc
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise BackupExecutionError("off-site encryption", "Backup artifact could not be encrypted safely", status_code=503) from exc

    def decrypt_file(self, source: Path, destination: Path, *, context: EncryptionContext) -> tuple[str, int, str]:
        try:
            raw_size = source.stat().st_size
            with source.open("rb") as stream:
                if stream.read(len(_MAGIC)) != _MAGIC:
                    raise BackupExecutionError("off-site decryption", "Encrypted backup envelope is invalid", status_code=409)
                header_size_raw = stream.read(4)
                if len(header_size_raw) != 4:
                    raise BackupExecutionError("off-site decryption", "Encrypted backup envelope is truncated", status_code=409)
                header_size = struct.unpack(">I", header_size_raw)[0]
                if header_size < 2 or header_size > 16_384:
                    raise BackupExecutionError("off-site decryption", "Encrypted backup header is invalid", status_code=409)
                header_bytes = stream.read(header_size)
                header = json.loads(header_bytes)
                if (
                    header.get("envelope_version") != _ENVELOPE_VERSION
                    or header.get("algorithm") != _ALGORITHM
                    or not isinstance(header.get("key_id"), str)
                ):
                    raise BackupExecutionError("off-site decryption", "Encrypted backup envelope version is unsupported", status_code=409)
                nonce = _b64url_decode(header.get("nonce"))
                if len(nonce) != _NONCE_BYTES:
                    raise BackupExecutionError("off-site decryption", "Encrypted backup nonce is invalid", status_code=409)
                record = self._keyring.for_decryption(header["key_id"])
                ciphertext_start = len(_MAGIC) + 4 + header_size
                ciphertext_size = raw_size - ciphertext_start - _TAG_BYTES
                if ciphertext_size < 0:
                    raise BackupExecutionError("off-site decryption", "Encrypted backup envelope is truncated", status_code=409)
                stream.seek(-_TAG_BYTES, os.SEEK_END)
                tag = stream.read(_TAG_BYTES)
                stream.seek(ciphertext_start)
                destination_fd = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                digest = hashlib.sha256()
                size = 0
                try:
                    decryptor = Cipher(algorithms.AES(record.key), modes.GCM(nonce, tag)).decryptor()
                    decryptor.authenticate_additional_data(self._aad(context, header))
                    remaining = ciphertext_size
                    while remaining:
                        chunk = stream.read(min(_CHUNK, remaining))
                        if not chunk:
                            raise BackupExecutionError("off-site decryption", "Encrypted backup envelope is truncated", status_code=409)
                        remaining -= len(chunk)
                        plaintext = decryptor.update(chunk)
                        if plaintext:
                            os.write(destination_fd, plaintext)
                            digest.update(plaintext)
                            size += len(plaintext)
                    final = decryptor.finalize()
                    if final:
                        os.write(destination_fd, final)
                        digest.update(final)
                        size += len(final)
                    os.fsync(destination_fd)
                finally:
                    os.close(destination_fd)
            if digest.hexdigest() != header.get("plaintext_sha256") or size != header.get("plaintext_size_bytes"):
                destination.unlink(missing_ok=True)
                raise BackupExecutionError(
                    "off-site decryption",
                    "Decrypted backup does not match authenticated plaintext evidence",
                    status_code=409,
                )
            return digest.hexdigest(), size, record.key_id
        except InvalidTag as exc:
            destination.unlink(missing_ok=True)
            raise BackupExecutionError(
                "off-site decryption",
                "Encrypted backup authentication failed; the key is wrong or the object is corrupted",
                status_code=409,
            ) from exc
        except BackupExecutionError:
            destination.unlink(missing_ok=True)
            raise
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError) as exc:
            destination.unlink(missing_ok=True)
            raise BackupExecutionError("off-site decryption", "Encrypted backup could not be decrypted safely", status_code=503) from exc
