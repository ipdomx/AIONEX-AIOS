from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .auth import ClusterAuthenticator


class ClusterClientError(ConnectionError):
    """Sanitized secure cluster client failure."""


@dataclass(frozen=True, slots=True)
class ClusterHTTPResponse:
    status_code: int
    payload: dict[str, Any]
    latency_ms: float
    tls_verified: bool
    authenticated: bool


class SecureClusterClient:
    """HTTPS-only cluster client using the shared CA and HMAC request signing."""

    def __init__(
        self,
        node_id: str,
        authenticator: ClusterAuthenticator,
        ca_file: str | Path,
        *,
        timeout_seconds: float = 3.0,
    ) -> None:
        if not node_id.strip():
            raise ValueError("node_id is required")
        ca_path = Path(ca_file)
        if not ca_path.is_file() or ca_path.is_symlink():
            raise ValueError("cluster CA file is missing or unsafe")
        if not 0.1 <= float(timeout_seconds) <= 30:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        self.node_id = node_id
        self.authenticator = authenticator
        self.ca_file = ca_path
        self.timeout_seconds = float(timeout_seconds)
        self._context = ssl.create_default_context(cafile=str(ca_path))
        self._context.check_hostname = True
        self._context.verify_mode = ssl.CERT_REQUIRED

    @staticmethod
    def _validate_url(url: str) -> str:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
        ):
            raise ValueError("cluster requests require a plain HTTPS URL")
        return url

    def request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> ClusterHTTPResponse:
        target = self._validate_url(url)
        body = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            if payload is not None
            else b""
        )
        parts = urlsplit(target)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self.authenticator.sign(self.node_id, method, path, body),
        }
        request = urllib.request.Request(
            target,
            data=body if method.upper() != "GET" or body else None,
            headers=headers,
            method=method.upper(),
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self._context,
            ) as response:
                raw = response.read().decode("utf-8")
                status_code = int(response.status)
        except urllib.error.HTTPError as exc:
            raise ClusterClientError(f"cluster HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            raise ClusterClientError(f"cluster connection failed: {type(exc).__name__}") from None
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            raise ClusterClientError("cluster returned invalid JSON") from None
        if not isinstance(decoded, dict):
            raise ClusterClientError("cluster returned a non-object response")
        return ClusterHTTPResponse(
            status_code=status_code,
            payload=decoded,
            latency_ms=round((time.monotonic() - started) * 1000, 4),
            tls_verified=True,
            authenticated=True,
        )
