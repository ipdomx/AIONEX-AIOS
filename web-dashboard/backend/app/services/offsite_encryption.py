"""Client-side authenticated encryption contract for off-site backups.

The data-encryption key is mounted separately from the R2 credential file and is
never persisted in backup metadata.  The envelope uses AES-256-GCM with a fresh
nonce per object and authenticates a small, non-secret context string as AAD.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.services.backup_executor import BackupExecutionError

_MAGIC = b"AIONEX-R2-AESGCM-v1\x00"
_NONCE_BYTES = 12
_TAG_BYTES = 16
_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class EncryptedArtifact:
    location: str
    sha256: str
    size_bytes: int
    plaintext_sha256: str
    plaintext_size_bytes: int
    key_id: str
    algorithm: str = "AES-256-GCM"
    envelope_version: int = 1


class OffsiteEncryption:
    def __init__(self, *, key_file: str, key_id: str) -> None:
        self.key_id = key_id
        self._key = self._read_key(Path(key_file))

    @staticmethod
    def _read_key(path: Path) -> bytes:
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise OSError("encryption key is not a regular file")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("encryption key grants group/other permissions")
            raw = path.read_bytes().strip()
            if len(raw) == 32:
                key = raw
            else:
                try:
                    key = base64.b64decode(raw, validate=True)
                except ValueError as exc:
                    raise OSError("encryption key is not raw or base64") from exc
            if len(key) != 32:
                raise OSError("encryption key is not 256 bits")
            return key
        except OSError as exc:
            raise BackupExecutionError(
                "off-site encryption configuration",
                "The private off-site encryption key is unavailable or unsafe",
                status_code=503,
            ) from exc

    def encrypt_file(self, source: Path, destination: Path, *, aad: bytes) -> EncryptedArtifact:
        nonce = os.urandom(_NONCE_BYTES)
        plaintext_digest = hashlib.sha256()
        encrypted_digest = hashlib.sha256()
        plaintext_size = 0
        try:
            source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                metadata = os.fstat(source_fd)
                if not stat.S_ISREG(metadata.st_mode):
                    raise OSError("source is not a regular file")
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                destination_fd = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    encryptor = Cipher(algorithms.AES(self._key), modes.GCM(nonce)).encryptor()
                    encryptor.authenticate_additional_data(aad)
                    header = _MAGIC + nonce
                    os.write(destination_fd, header)
                    encrypted_digest.update(header)
                    with os.fdopen(source_fd, "rb", closefd=False) as stream:
                        for chunk in iter(lambda: stream.read(_CHUNK), b""):
                            plaintext_digest.update(chunk)
                            plaintext_size += len(chunk)
                            ciphertext = encryptor.update(chunk)
                            if ciphertext:
                                os.write(destination_fd, ciphertext)
                                encrypted_digest.update(ciphertext)
                    final = encryptor.finalize()
                    if final:
                        os.write(destination_fd, final)
                        encrypted_digest.update(final)
                    os.write(destination_fd, encryptor.tag)
                    encrypted_digest.update(encryptor.tag)
                    os.fsync(destination_fd)
                finally:
                    os.close(destination_fd)
            finally:
                os.close(source_fd)
            encrypted_size = destination.stat().st_size
            return EncryptedArtifact(
                location=str(destination),
                sha256=encrypted_digest.hexdigest(),
                size_bytes=encrypted_size,
                plaintext_sha256=plaintext_digest.hexdigest(),
                plaintext_size_bytes=plaintext_size,
                key_id=self.key_id,
            )
        except FileExistsError as exc:
            raise BackupExecutionError("off-site encryption", "Encrypted staging path already exists", status_code=409) from exc
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise BackupExecutionError("off-site encryption", "Backup artifact could not be encrypted safely", status_code=503) from exc

    def decrypt_file(self, source: Path, destination: Path, *, aad: bytes) -> tuple[str, int]:
        try:
            raw_size = source.stat().st_size
            minimum = len(_MAGIC) + _NONCE_BYTES + _TAG_BYTES
            if raw_size < minimum:
                raise BackupExecutionError("off-site decryption", "Encrypted backup envelope is truncated", status_code=409)
            with source.open("rb") as stream:
                magic = stream.read(len(_MAGIC))
                nonce = stream.read(_NONCE_BYTES)
                if magic != _MAGIC:
                    raise BackupExecutionError("off-site decryption", "Encrypted backup envelope is invalid", status_code=409)
                stream.seek(-_TAG_BYTES, os.SEEK_END)
                tag = stream.read(_TAG_BYTES)
                ciphertext_size = raw_size - len(_MAGIC) - _NONCE_BYTES - _TAG_BYTES
                stream.seek(len(_MAGIC) + _NONCE_BYTES)
                destination_fd = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                digest = hashlib.sha256()
                size = 0
                try:
                    decryptor = Cipher(algorithms.AES(self._key), modes.GCM(nonce, tag)).decryptor()
                    decryptor.authenticate_additional_data(aad)
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
            return digest.hexdigest(), size
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
        except (OSError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            raise BackupExecutionError("off-site decryption", "Encrypted backup could not be decrypted safely", status_code=503) from exc
