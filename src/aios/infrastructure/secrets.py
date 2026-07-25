from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from secrets import token_bytes
from time import time
from typing import Protocol


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
    """Pluggable vault foundation. The default backend is process-local only."""

    def __init__(self, master_key: bytes, backend: SecretBackend | None = None) -> None:
        if len(master_key) < 16:
            raise ValueError("master key must be at least 16 bytes")
        self._key = sha256(master_key).digest()
        self._backend = backend or InMemorySecretBackend()
        self._metadata: dict[str, SecretMetadata] = {}

    def _stream(self, nonce: bytes, size: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < size:
            output.extend(sha256(self._key + nonce + counter.to_bytes(8, "big")).digest())
            counter += 1
        return bytes(output[:size])

    def _seal(self, value: str) -> bytes:
        raw = value.encode("utf-8")
        nonce = token_bytes(16)
        stream = self._stream(nonce, len(raw))
        cipher = bytes(a ^ b for a, b in zip(raw, stream))
        tag = sha256(self._key + nonce + cipher).digest()
        return nonce + tag + cipher

    def _open(self, blob: bytes) -> str:
        nonce, tag, cipher = blob[:16], blob[16:48], blob[48:]
        expected = sha256(self._key + nonce + cipher).digest()
        if not compare_digest(tag, expected):
            raise ValueError("secret integrity check failed")
        stream = self._stream(nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")

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
        return self._open(self._backend.get(name))

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
