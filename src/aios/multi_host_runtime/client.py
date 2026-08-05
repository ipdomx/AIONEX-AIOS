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

from .auth import HostRequestAuthenticator


class MultiHostClientError(ConnectionError):
    """Sanitized cross-host control-plane client failure."""


@dataclass(frozen=True, slots=True)
class MultiHostHTTPResponse:
    status_code: int
    payload: dict[str, Any]
    latency_ms: float
    tls_verified: bool
    mutually_authenticated: bool
    hmac_authenticated: bool


class MultiHostControlClient:
    """HTTPS client using CA verification, client certificates, and per-host HMAC signing."""

    def __init__(
        self,
        base_url: str,
        authenticator: HostRequestAuthenticator,
        ca_file: str | Path,
        cert_file: str | Path,
        key_file: str | Path,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = self._validate_base_url(base_url)
        self.authenticator = authenticator
        self.ca_file = self._required_file(ca_file, "CA")
        self.cert_file = self._required_file(cert_file, "client certificate")
        self.key_file = self._required_file(key_file, "client key")
        if not 0.1 <= float(timeout_seconds) <= 30:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        self.timeout_seconds = float(timeout_seconds)
        context = ssl.create_default_context(cafile=str(self.ca_file))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(str(self.cert_file), str(self.key_file))
        self._context = context

    @staticmethod
    def _required_file(path: str | Path, label: str) -> Path:
        target = Path(path)
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"{label} file is missing or unsafe")
        return target

    @staticmethod
    def _validate_base_url(url: str) -> str:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("control-plane base URL must be plain HTTPS")
        path = parts.path.rstrip("/")
        if path:
            raise ValueError("control-plane base URL must not include a path")
        return url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> MultiHostHTTPResponse:
        if not path.startswith("/") or "#" in path:
            raise ValueError("request path must be absolute and contain no fragment")
        body = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            if payload is not None
            else b""
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self.authenticator.sign(method, path, body),
        }
        request = urllib.request.Request(
            f"{self.base_url}{path}",
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
            raise MultiHostClientError(f"control-plane HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            raise MultiHostClientError(
                f"control-plane connection failed: {type(exc).__name__}"
            ) from None
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            raise MultiHostClientError("control-plane returned invalid JSON") from None
        if not isinstance(decoded, dict):
            raise MultiHostClientError("control-plane returned a non-object response")
        return MultiHostHTTPResponse(
            status_code=status_code,
            payload=decoded,
            latency_ms=round((time.monotonic() - started) * 1000, 4),
            tls_verified=True,
            mutually_authenticated=True,
            hmac_authenticated=True,
        )
