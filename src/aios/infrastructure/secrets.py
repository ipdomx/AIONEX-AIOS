from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from secrets import token_bytes
from time import time
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBackend(Protocol):
    def put(self, key: str, value: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def keys(self) -> tuple[str, ...]: ...


class InMemorySecretBackend:
    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def put(self, key: str, value: bytes) -> None:
        self._values[key] = value

    def get(self, key: str) -> bytes:
        try:
            return self._values[key]
        except KeyError as exc:
            raise KeyError(f"unknown secret: {key}") from exc

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._values))


@dataclass(frozen=True, slots=True)
class SecretMetadata:
    name: str
    created_at: float
    rotated_at: float | None = None
    version: int = 1


class SecretsVault:
    """Pluggable authenticated secret vault with legacy-record migration.

    New records use AES-256-GCM with an explicit version marker and per-record
    nonce. Records written by the pre-v2 SHA/XOR construction remain readable
    solely for migration and are transparently resealed with AES-GCM on read.
    """

    _V2_PREFIX = b"AIOSSV2\x00"
    _V2_AAD = b"aionex-infrastructure-secrets-v2"
    _NONCE_BYTES = 12

    def __init__(self, master_key: bytes, backend: SecretBackend | None = None) -> None:
        if len(master_key) < 16:
            raise ValueError("master key must be at least 16 bytes")
        self._key = sha256(master_key).digest()
        self._aead = AESGCM(self._key)
        self._backend = backend or InMemorySecretBackend()
        self._metadata: dict[str, SecretMetadata] = {}

    def _legacy_stream(self, nonce: bytes, size: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < size:
            output.extend(
                sha256(self._key + nonce + counter.to_bytes(8, "big")).digest()
            )
            counter += 1
        return bytes(output[:size])

    def _open_legacy(self, blob: bytes) -> str:
        if len(blob) < 48:
            raise ValueError("legacy secret record is malformed")
        nonce, tag, cipher = blob[:16], blob[16:48], blob[48:]
        expected = sha256(self._key + nonce + cipher).digest()
        if not compare_digest(tag, expected):
            raise ValueError("secret integrity check failed")
        stream = self._legacy_stream(nonce, len(cipher))
        try:
            return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("legacy secret record is invalid") from exc

    def _seal(self, value: str) -> bytes:
        nonce = token_bytes(self._NONCE_BYTES)
        ciphertext = self._aead.encrypt(
            nonce,
            value.encode("utf-8"),
            self._V2_AAD,
        )
        return self._V2_PREFIX + nonce + ciphertext

    def _open(self, blob: bytes) -> tuple[str, bool]:
        if blob.startswith(self._V2_PREFIX):
            payload = blob[len(self._V2_PREFIX) :]
            if len(payload) <= self._NONCE_BYTES:
                raise ValueError("secret record is malformed")
            nonce = payload[: self._NONCE_BYTES]
            ciphertext = payload[self._NONCE_BYTES :]
            try:
                plaintext = self._aead.decrypt(nonce, ciphertext, self._V2_AAD)
                return plaintext.decode("utf-8"), False
            except (InvalidTag, UnicodeDecodeError) as exc:
                raise ValueError("secret integrity check failed") from exc
        return self._open_legacy(blob), True

    def put(self, name: str, value: str) -> SecretMetadata:
        if not name or not value:
            raise ValueError("secret name and value are required")
        now = time()
        previous = self._metadata.get(name)
        metadata = SecretMetadata(
            name=name,
            created_at=previous.created_at if previous else now,
            rotated_at=now if previous else None,
            version=(previous.version + 1) if previous else 1,
        )
        self._backend.put(name, self._seal(value))
        self._metadata[name] = metadata
        return metadata

    def get(self, name: str) -> str:
        value, migrated = self._open(self._backend.get(name))
        if migrated:
            self._backend.put(name, self._seal(value))
        return value

    def delete(self, name: str) -> None:
        self._backend.delete(name)
        self._metadata.pop(name, None)

    def metadata(self, name: str) -> SecretMetadata:
        try:
            return self._metadata[name]
        except KeyError as exc:
            raise KeyError(f"unknown secret metadata: {name}") from exc

    def list(self) -> tuple[SecretMetadata, ...]:
        return tuple(self._metadata[name] for name in sorted(self._metadata))
