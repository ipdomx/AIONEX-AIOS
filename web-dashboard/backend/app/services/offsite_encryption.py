"""Hardened versioned client-side encryption for off-site backup objects.

FR-05B1 implements only the cryptographic envelope and keyring parser. R2
transport wiring remains a later FR-05B slice. Plaintext is never published to
its requested restore path before authentication and evidence verification.
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

from app.services.backup_executor import BackupExecutionError

_MAGIC = b"AIONEX-R2-ENC"
_ENVELOPE_VERSION = 1
_ALGORITHM = "AES-256-GCM"
_NONCE_BYTES = 12
_TAG_BYTES = 16
_HEADER_LENGTH_BYTES = 4
_MAX_HEADER_BYTES = 8192
_MAX_KEYRING_BYTES = 1024 * 1024
_CHUNK = 1024 * 1024
_ALLOWED_KEY_STATES = {"active", "decrypt_only"}
_ALLOWED_OBJECT_ROLES = {"database", "platform_asset_snapshot", "manifest"}
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BACKUP_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def _operation_error(operation: str, message: str, *, status_code: int = 503) -> BackupExecutionError:
    return BackupExecutionError(operation, message, status_code=status_code)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _b64url_decode(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("empty base64url value")
    try:
        padding = "=" * (-len(value) % 4)
        return base64.b64decode(
            (value + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("invalid base64url value") from exc


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid key timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("key timestamp must include a timezone")
    return value


def _validate_key_id(value: Any) -> str:
    if not isinstance(value, str) or _KEY_ID.fullmatch(value) is None:
        raise ValueError("invalid key identifier")
    return value


def _validate_context(context: EncryptionContext) -> None:
    if not isinstance(context, EncryptionContext):
        raise _operation_error(
            "off-site encryption",
            "Backup encryption context is invalid",
            status_code=409,
        )
    if _BACKUP_ID.fullmatch(context.backup_id) is None:
        raise _operation_error(
            "off-site encryption",
            "Backup identifier is invalid",
            status_code=409,
        )
    if context.object_role not in _ALLOWED_OBJECT_ROLES:
        raise _operation_error(
            "off-site encryption",
            "Backup object role is invalid",
            status_code=409,
        )
    key = context.r2_object_key
    if not isinstance(key, str) or not key or len(key) > 1024 or "\x00" in key:
        raise _operation_error(
            "off-site encryption",
            "Backup object key is invalid",
            status_code=409,
        )


def _validate_sha256(value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("invalid plaintext checksum")
    return value


def _validate_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid plaintext size")
    return value


def _close_quietly(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        return


def _open_regular_read(path: Path, *, operation: str, public_message: str) -> int:
    descriptor: int | None = None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("unsafe source file")
        return descriptor
    except OSError as exc:
        _close_quietly(descriptor)
        raise _operation_error(operation, public_message) from exc


def _hash_fd(descriptor: int) -> tuple[str, int]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(descriptor, _CHUNK)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest(), size


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _read_exact(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _open_destination_directory(destination: Path, *, operation: str) -> tuple[int, str]:
    name = destination.name
    if not name or name in {".", ".."}:
        raise _operation_error(operation, "Backup destination is invalid", status_code=409)
    descriptor: int | None = None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(destination.parent, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("destination parent is not a directory")
        return descriptor, name
    except OSError as exc:
        _close_quietly(descriptor)
        raise _operation_error(operation, "Backup destination directory is unavailable") from exc


def _create_private_temporary(directory_fd: int, final_name: str, *, operation: str) -> tuple[str, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    for _ in range(16):
        temporary_name = f".{final_name}.{secrets.token_hex(12)}.partial"
        try:
            descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
            os.fchmod(descriptor, 0o600)
            return temporary_name, descriptor
        except FileExistsError:
            continue
        except OSError as exc:
            raise _operation_error(operation, "Private backup staging file could not be created") from exc
    raise _operation_error(operation, "Private backup staging path is unavailable")


def _unlink_quietly(directory_fd: int | None, name: str | None) -> None:
    if directory_fd is None or name is None:
        return
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        return
    except OSError:
        return


def _publish_no_replace(
    directory_fd: int,
    temporary_name: str,
    final_name: str,
    *,
    operation: str,
) -> None:
    try:
        os.link(
            temporary_name,
            final_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileExistsError as exc:
        raise _operation_error(operation, "Backup destination already exists", status_code=409) from exc
    except OSError as exc:
        raise _operation_error(operation, "Verified backup output could not be published safely") from exc
    try:
        os.unlink(temporary_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except OSError as exc:
        raise _operation_error(operation, "Verified backup output cleanup did not complete") from exc


class OffsiteEncryptionKeyring:
    """Strict parser for the operator-owned FR-05 backup-encryption keyring."""

    def __init__(self, path: str) -> None:
        self._records, self.active_key_id = self._load(Path(path))

    @staticmethod
    def _load(path: Path) -> tuple[dict[str, _KeyRecord], str]:
        descriptor: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("keyring is not a regular file")
            if metadata.st_nlink != 1:
                raise OSError("keyring is hard-linked")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("keyring grants group/other permissions")
            if metadata.st_size < 2 or metadata.st_size > _MAX_KEYRING_BYTES:
                raise ValueError("keyring size is invalid")
            payload = _read_exact(descriptor, metadata.st_size + 1)
            if len(payload) != metadata.st_size:
                raise OSError("keyring changed while being read")
            raw = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
            )
            if not isinstance(raw, dict) or set(raw) != {
                "schema_version",
                "active_key_id",
                "keys",
            }:
                raise ValueError("unsupported keyring schema")
            if raw["schema_version"] != 1:
                raise ValueError("unsupported keyring schema version")
            active_key_id = _validate_key_id(raw["active_key_id"])
            keys = raw["keys"]
            if not isinstance(keys, dict) or not keys or len(keys) > 1024:
                raise ValueError("keyring has invalid keys")
            records: dict[str, _KeyRecord] = {}
            for raw_key_id, item in keys.items():
                key_id = _validate_key_id(raw_key_id)
                if not isinstance(item, dict):
                    raise ValueError("invalid key record")
                required = {"key_b64", "status", "created_at"}
                allowed = required | {"rotation_generation"}
                if not required.issubset(item) or not set(item).issubset(allowed):
                    raise ValueError("invalid key record schema")
                status_value = item["status"]
                if not isinstance(status_value, str) or status_value not in _ALLOWED_KEY_STATES:
                    raise ValueError("invalid key lifecycle state")
                created_at = _validate_timestamp(item["created_at"])
                key = _b64url_decode(item["key_b64"])
                if len(key) != 32:
                    raise ValueError("key is not 256 bits")
                generation = item.get("rotation_generation")
                if generation is not None and (
                    isinstance(generation, bool)
                    or not isinstance(generation, int)
                    or generation < 1
                ):
                    raise ValueError("rotation generation is invalid")
                records[key_id] = _KeyRecord(
                    key_id=key_id,
                    key=key,
                    status=status_value,
                    created_at=created_at,
                    rotation_generation=generation,
                )
            active_records = [record for record in records.values() if record.status == "active"]
            active = records.get(active_key_id)
            if len(active_records) != 1 or active is None or active.status != "active":
                raise ValueError("keyring must contain exactly one selected active key")
            return records, active_key_id
        except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
            raise _operation_error(
                "off-site encryption configuration",
                "The private backup-encryption keyring is unavailable or unsafe",
            ) from exc
        finally:
            _close_quietly(descriptor)

    def active(self) -> _KeyRecord:
        return self._records[self.active_key_id]

    def for_decryption(self, key_id: str) -> _KeyRecord:
        try:
            validated_key_id = _validate_key_id(key_id)
        except ValueError as exc:
            raise _operation_error(
                "off-site decryption",
                "The encrypted backup references an invalid key identifier",
                status_code=409,
            ) from exc
        record = self._records.get(validated_key_id)
        if record is None:
            raise _operation_error(
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
                **header,
            }
        )

    @staticmethod
    def _header(record: _KeyRecord, nonce: bytes, checksum: str, size: int) -> dict[str, Any]:
        return {
            "algorithm": _ALGORITHM,
            "envelope_version": _ENVELOPE_VERSION,
            "key_id": record.key_id,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
            "plaintext_sha256": checksum,
            "plaintext_size_bytes": size,
        }

    @staticmethod
    def _validate_header(header: Any) -> dict[str, Any]:
        expected = {
            "algorithm",
            "envelope_version",
            "key_id",
            "nonce",
            "plaintext_sha256",
            "plaintext_size_bytes",
        }
        if not isinstance(header, dict) or set(header) != expected:
            raise _operation_error(
                "off-site decryption",
                "Encrypted backup header schema is invalid",
                status_code=409,
            )
        if header["algorithm"] != _ALGORITHM or header["envelope_version"] != _ENVELOPE_VERSION:
            raise _operation_error(
                "off-site decryption",
                "Encrypted backup envelope version is unsupported",
                status_code=409,
            )
        try:
            _validate_key_id(header["key_id"])
            nonce = _b64url_decode(header["nonce"])
            _validate_sha256(header["plaintext_sha256"])
            _validate_size(header["plaintext_size_bytes"])
        except (ValueError, TypeError) as exc:
            raise _operation_error(
                "off-site decryption",
                "Encrypted backup header fields are invalid",
                status_code=409,
            ) from exc
        if len(nonce) != _NONCE_BYTES:
            raise _operation_error(
                "off-site decryption",
                "Encrypted backup nonce is invalid",
                status_code=409,
            )
        return header

    def encrypt_file(
        self,
        source: Path,
        destination: Path,
        *,
        context: EncryptionContext,
    ) -> EncryptedArtifact:
        _validate_context(context)
        source_path = Path(source)
        destination_path = Path(destination)
        source_fd: int | None = None
        directory_fd: int | None = None
        temporary_fd: int | None = None
        temporary_name: str | None = None
        try:
            source_fd = _open_regular_read(
                source_path,
                operation="off-site encryption",
                public_message="Backup artifact is unavailable or unsafe",
            )
            plaintext_sha256, plaintext_size = _hash_fd(source_fd)
            record = self._keyring.active()
            nonce = os.urandom(_NONCE_BYTES)
            header = self._header(record, nonce, plaintext_sha256, plaintext_size)
            header_bytes = _canonical_json(header)
            prefix = _MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
            directory_fd, final_name = _open_destination_directory(
                destination_path,
                operation="off-site encryption",
            )
            temporary_name, temporary_fd = _create_private_temporary(
                directory_fd,
                final_name,
                operation="off-site encryption",
            )
            encryptor = Cipher(algorithms.AES(record.key), modes.GCM(nonce)).encryptor()
            encryptor.authenticate_additional_data(self._aad(context, header))
            ciphertext_digest = hashlib.sha256()
            ciphertext_size = 0
            _write_all(temporary_fd, prefix)
            ciphertext_digest.update(prefix)
            ciphertext_size += len(prefix)
            actual_digest = hashlib.sha256()
            actual_size = 0
            while True:
                chunk = os.read(source_fd, _CHUNK)
                if not chunk:
                    break
                actual_digest.update(chunk)
                actual_size += len(chunk)
                encrypted = encryptor.update(chunk)
                if encrypted:
                    _write_all(temporary_fd, encrypted)
                    ciphertext_digest.update(encrypted)
                    ciphertext_size += len(encrypted)
            if (
                actual_digest.hexdigest() != plaintext_sha256
                or actual_size != plaintext_size
            ):
                raise _operation_error(
                    "off-site encryption",
                    "Backup artifact changed during encryption",
                    status_code=409,
                )
            final = encryptor.finalize()
            if final:
                _write_all(temporary_fd, final)
                ciphertext_digest.update(final)
                ciphertext_size += len(final)
            tag = encryptor.tag
            _write_all(temporary_fd, tag)
            ciphertext_digest.update(tag)
            ciphertext_size += len(tag)
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            _publish_no_replace(
                directory_fd,
                temporary_name,
                final_name,
                operation="off-site encryption",
            )
            temporary_name = None
            return EncryptedArtifact(
                location=str(destination_path),
                ciphertext_sha256=ciphertext_digest.hexdigest(),
                ciphertext_size_bytes=ciphertext_size,
                plaintext_sha256=plaintext_sha256,
                plaintext_size_bytes=plaintext_size,
                key_id=record.key_id,
            )
        except BackupExecutionError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise _operation_error(
                "off-site encryption",
                "Backup artifact could not be encrypted safely",
            ) from exc
        finally:
            _close_quietly(temporary_fd)
            _unlink_quietly(directory_fd, temporary_name)
            _close_quietly(directory_fd)
            _close_quietly(source_fd)

    def decrypt_file(
        self,
        source: Path,
        destination: Path,
        *,
        context: EncryptionContext,
    ) -> tuple[str, int, str]:
        _validate_context(context)
        source_path = Path(source)
        destination_path = Path(destination)
        source_fd: int | None = None
        directory_fd: int | None = None
        temporary_fd: int | None = None
        temporary_name: str | None = None
        try:
            source_fd = _open_regular_read(
                source_path,
                operation="off-site decryption",
                public_message="Encrypted backup artifact is unavailable or unsafe",
            )
            raw_size = os.fstat(source_fd).st_size
            if _read_exact(source_fd, len(_MAGIC)) != _MAGIC:
                raise _operation_error(
                    "off-site decryption",
                    "Encrypted backup envelope is invalid",
                    status_code=409,
                )
            raw_header_size = _read_exact(source_fd, _HEADER_LENGTH_BYTES)
            if len(raw_header_size) != _HEADER_LENGTH_BYTES:
                raise _operation_error(
                    "off-site decryption",
                    "Encrypted backup envelope is truncated",
                    status_code=409,
                )
            header_size = struct.unpack(">I", raw_header_size)[0]
            if not 1 <= header_size <= _MAX_HEADER_BYTES:
                raise _operation_error(
                    "off-site decryption",
                    "Encrypted backup header is invalid",
                    status_code=409,
                )
            header_bytes = _read_exact(source_fd, header_size)
            if len(header_bytes) != header_size:
                raise _operation_error(
                    "off-site decryption",
                    "Encrypted backup envelope is truncated",
                    status_code=409,
                )
            try:
                header = json.loads(
                    header_bytes.decode("utf-8"),
                    object_pairs_hook=_reject_duplicate_pairs,
                )
            except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise _operation_error(
                    "off-site decryption",
                    "Encrypted backup header is invalid",
                    status_code=409,
                ) from exc
            header = self._validate_header(header)
            record = self._keyring.for_decryption(header["key_id"])
            nonce = _b64url_decode(header["nonce"])
            ciphertext_start = len(_MAGIC) + _HEADER_LENGTH_BYTES + header_size
            ciphertext_size = raw_size - ciphertext_start - _TAG_BYTES
            if ciphertext_size < 0:
                raise _operation_error(
                    "off-site decryption",
                    "Encrypted backup envelope is truncated",
                    status_code=409,
                )
            tag = os.pread(source_fd, _TAG_BYTES, raw_size - _TAG_BYTES)
            if len(tag) != _TAG_BYTES:
                raise _operation_error(
                    "off-site decryption",
                    "Encrypted backup authentication tag is missing",
                    status_code=409,
                )
            os.lseek(source_fd, ciphertext_start, os.SEEK_SET)
            directory_fd, final_name = _open_destination_directory(
                destination_path,
                operation="off-site decryption",
            )
            temporary_name, temporary_fd = _create_private_temporary(
                directory_fd,
                final_name,
                operation="off-site decryption",
            )
            decryptor = Cipher(
                algorithms.AES(record.key),
                modes.GCM(nonce, tag),
            ).decryptor()
            decryptor.authenticate_additional_data(self._aad(context, header))
            digest = hashlib.sha256()
            size = 0
            remaining = ciphertext_size
            while remaining:
                chunk = os.read(source_fd, min(_CHUNK, remaining))
                if not chunk:
                    raise _operation_error(
                        "off-site decryption",
                        "Encrypted backup envelope is truncated",
                        status_code=409,
                    )
                remaining -= len(chunk)
                plaintext = decryptor.update(chunk)
                if plaintext:
                    _write_all(temporary_fd, plaintext)
                    digest.update(plaintext)
                    size += len(plaintext)
            final = decryptor.finalize()
            if final:
                _write_all(temporary_fd, final)
                digest.update(final)
                size += len(final)
            expected_checksum = _validate_sha256(header["plaintext_sha256"])
            expected_size = _validate_size(header["plaintext_size_bytes"])
            if digest.hexdigest() != expected_checksum or size != expected_size:
                raise _operation_error(
                    "off-site decryption",
                    "Decrypted backup does not match authenticated plaintext evidence",
                    status_code=409,
                )
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            _publish_no_replace(
                directory_fd,
                temporary_name,
                final_name,
                operation="off-site decryption",
            )
            temporary_name = None
            return digest.hexdigest(), size, record.key_id
        except InvalidTag as exc:
            raise _operation_error(
                "off-site decryption",
                "Encrypted backup authentication failed; the key is wrong or the object is corrupted",
                status_code=409,
            ) from exc
        except BackupExecutionError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise _operation_error(
                "off-site decryption",
                "Encrypted backup could not be decrypted safely",
            ) from exc
        finally:
            _close_quietly(temporary_fd)
            _unlink_quietly(directory_fd, temporary_name)
            _close_quietly(directory_fd)
            _close_quietly(source_fd)
