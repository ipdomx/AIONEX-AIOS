from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


AUTH_NODE_HEADER = "X-AIOS-Node"
AUTH_TIMESTAMP_HEADER = "X-AIOS-Timestamp"
AUTH_SIGNATURE_HEADER = "X-AIOS-Signature"


class ClusterAuthenticationError(PermissionError):
    """Raised when an inter-node request is missing, stale, or incorrectly signed."""


@dataclass(frozen=True, slots=True)
class VerifiedClusterIdentity:
    node_id: str
    timestamp: int
    body_sha256: str


class ClusterAuthenticator:
    """HMAC-SHA256 request authentication for the TLS-protected cluster API."""

    def __init__(self, secret: bytes, *, maximum_clock_skew_seconds: int = 30) -> None:
        if len(secret) < 32:
            raise ValueError("cluster authentication secret must contain at least 32 bytes")
        if not 1 <= int(maximum_clock_skew_seconds) <= 300:
            raise ValueError("maximum clock skew must be between 1 and 300 seconds")
        self._secret = bytes(secret)
        self.maximum_clock_skew_seconds = int(maximum_clock_skew_seconds)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        maximum_clock_skew_seconds: int = 30,
    ) -> "ClusterAuthenticator":
        secret_path = Path(path)
        if not secret_path.is_file() or secret_path.is_symlink():
            raise ValueError("cluster secret must be a regular file")
        raw = secret_path.read_bytes().strip()
        if len(raw) >= 64:
            try:
                decoded = bytes.fromhex(raw.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                decoded = raw
        else:
            decoded = raw
        return cls(decoded, maximum_clock_skew_seconds=maximum_clock_skew_seconds)

    @staticmethod
    def _body_digest(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()

    @staticmethod
    def _canonical(
        node_id: str,
        method: str,
        path: str,
        timestamp: int,
        body_sha256: str,
    ) -> bytes:
        return (
            f"{node_id}\n{method.upper()}\n{path}\n{timestamp}\n{body_sha256}"
        ).encode("utf-8")

    def sign(
        self,
        node_id: str,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        timestamp: int | None = None,
    ) -> dict[str, str]:
        if not node_id.strip():
            raise ValueError("node_id is required")
        issued_at = int(timestamp if timestamp is not None else time.time())
        body_sha256 = self._body_digest(body)
        signature = hmac.new(
            self._secret,
            self._canonical(node_id, method, path, issued_at, body_sha256),
            hashlib.sha256,
        ).hexdigest()
        return {
            AUTH_NODE_HEADER: node_id,
            AUTH_TIMESTAMP_HEADER: str(issued_at),
            AUTH_SIGNATURE_HEADER: signature,
        }

    def verify(
        self,
        headers: Mapping[str, str],
        method: str,
        path: str,
        body: bytes = b"",
        *,
        now: int | None = None,
    ) -> VerifiedClusterIdentity:
        node_id = str(headers.get(AUTH_NODE_HEADER, "")).strip()
        timestamp_raw = str(headers.get(AUTH_TIMESTAMP_HEADER, "")).strip()
        signature = str(headers.get(AUTH_SIGNATURE_HEADER, "")).strip().lower()
        if not node_id or not timestamp_raw or not signature:
            raise ClusterAuthenticationError("cluster authentication headers are required")
        try:
            timestamp = int(timestamp_raw)
        except ValueError as exc:
            raise ClusterAuthenticationError("cluster timestamp is invalid") from exc
        current = int(now if now is not None else time.time())
        if abs(current - timestamp) > self.maximum_clock_skew_seconds:
            raise ClusterAuthenticationError("cluster request timestamp is stale")
        body_sha256 = self._body_digest(body)
        expected = hmac.new(
            self._secret,
            self._canonical(node_id, method, path, timestamp, body_sha256),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ClusterAuthenticationError("cluster request signature is invalid")
        return VerifiedClusterIdentity(node_id, timestamp, body_sha256)

    def __repr__(self) -> str:
        return (
            "ClusterAuthenticator(secret='[REDACTED]', "
            f"maximum_clock_skew_seconds={self.maximum_clock_skew_seconds})"
        )
