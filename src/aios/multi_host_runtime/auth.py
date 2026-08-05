from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


HOST_HEADER = "X-AIOS-Host"
TIMESTAMP_HEADER = "X-AIOS-Timestamp"
NONCE_HEADER = "X-AIOS-Nonce"
SIGNATURE_HEADER = "X-AIOS-Signature"


class MultiHostAuthenticationError(PermissionError):
    """Raised when a multi-host request cannot be authenticated safely."""


@dataclass(frozen=True, slots=True)
class VerifiedHostRequest:
    host_id: str
    timestamp: int
    nonce: str
    body_sha256: str


class HostRequestAuthenticator:
    """Per-host HMAC authentication layered on top of mutual TLS."""

    def __init__(self, host_id: str, secret: bytes, *, maximum_clock_skew_seconds: int = 30) -> None:
        if not host_id.strip():
            raise ValueError("host_id is required")
        if len(secret) < 32:
            raise ValueError("host authentication secret must contain at least 32 bytes")
        if not 1 <= int(maximum_clock_skew_seconds) <= 300:
            raise ValueError("maximum clock skew must be between 1 and 300 seconds")
        self.host_id = host_id.strip()
        self._secret = bytes(secret)
        self.maximum_clock_skew_seconds = int(maximum_clock_skew_seconds)

    @classmethod
    def from_file(
        cls,
        host_id: str,
        path: str | Path,
        *,
        maximum_clock_skew_seconds: int = 30,
    ) -> "HostRequestAuthenticator":
        secret_path = Path(path)
        if not secret_path.is_file() or secret_path.is_symlink():
            raise ValueError("host secret must be a regular file")
        raw = secret_path.read_bytes().strip()
        if len(raw) >= 64:
            try:
                decoded = bytes.fromhex(raw.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                decoded = raw
        else:
            decoded = raw
        return cls(
            host_id,
            decoded,
            maximum_clock_skew_seconds=maximum_clock_skew_seconds,
        )

    @staticmethod
    def body_digest(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()

    @staticmethod
    def canonical(
        host_id: str,
        method: str,
        path: str,
        timestamp: int,
        nonce: str,
        body_sha256: str,
    ) -> bytes:
        return (
            f"{host_id}\n{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_sha256}"
        ).encode("utf-8")

    def sign(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        timestamp: int | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        issued_at = int(timestamp if timestamp is not None else time.time())
        request_nonce = nonce or secrets.token_hex(16)
        if not request_nonce or len(request_nonce) > 128:
            raise ValueError("request nonce is invalid")
        digest = self.body_digest(body)
        signature = hmac.new(
            self._secret,
            self.canonical(
                self.host_id,
                method,
                path,
                issued_at,
                request_nonce,
                digest,
            ),
            hashlib.sha256,
        ).hexdigest()
        return {
            HOST_HEADER: self.host_id,
            TIMESTAMP_HEADER: str(issued_at),
            NONCE_HEADER: request_nonce,
            SIGNATURE_HEADER: signature,
        }

    def verify(
        self,
        headers: Mapping[str, str],
        method: str,
        path: str,
        body: bytes = b"",
        *,
        now: int | None = None,
    ) -> VerifiedHostRequest:
        host_id = str(headers.get(HOST_HEADER, "")).strip()
        timestamp_raw = str(headers.get(TIMESTAMP_HEADER, "")).strip()
        nonce = str(headers.get(NONCE_HEADER, "")).strip()
        signature = str(headers.get(SIGNATURE_HEADER, "")).strip().lower()
        if host_id != self.host_id or not timestamp_raw or not nonce or not signature:
            raise MultiHostAuthenticationError("host authentication headers are invalid")
        if len(nonce) > 128:
            raise MultiHostAuthenticationError("host request nonce is invalid")
        try:
            timestamp = int(timestamp_raw)
        except ValueError as exc:
            raise MultiHostAuthenticationError("host timestamp is invalid") from exc
        current = int(now if now is not None else time.time())
        if abs(current - timestamp) > self.maximum_clock_skew_seconds:
            raise MultiHostAuthenticationError("host request timestamp is stale")
        digest = self.body_digest(body)
        expected = hmac.new(
            self._secret,
            self.canonical(host_id, method, path, timestamp, nonce, digest),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise MultiHostAuthenticationError("host request signature is invalid")
        return VerifiedHostRequest(host_id, timestamp, nonce, digest)

    def __repr__(self) -> str:
        return (
            f"HostRequestAuthenticator(host_id={self.host_id!r}, secret='[REDACTED]', "
            f"maximum_clock_skew_seconds={self.maximum_clock_skew_seconds})"
        )


def certificate_sha256(der_certificate: bytes) -> str:
    if not der_certificate:
        raise ValueError("peer certificate is required")
    return hashlib.sha256(der_certificate).hexdigest()
