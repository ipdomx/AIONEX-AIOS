"""Authenticated Cloudflare API v4 integration with no simulated successes.

Only verified, read-only API capabilities are exposed. DNS mutations and all
other formerly mock-only operations fail closed and are NOT advertised. This
module has no automatic DNS, security-header, or tunnel mutations.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from .base import BaseInfrastructureIntegration
from .models import (
    ConnectionProfile,
    ConnectionState,
    Credential,
    HealthReport,
    IntegrationCapability,
    IntegrationDescriptor,
    IntegrationKind,
)

_API = "https://api.cloudflare.com/client/v4"
_ZONE_ID = re.compile(r"[0-9a-f]{32}\Z")
_DNS_NAME = re.compile(r"(?:\*|[a-zA-Z0-9_-]+)(?:\.[a-zA-Z0-9_-]+)*\.?\Z")
_DNS_TYPES = frozenset({"A", "AAAA", "CNAME", "TXT"})
_MAX_JSON_BYTES = 2 * 1024 * 1024


class CloudflareRequestError(RuntimeError):
    """A request could not be verified; never includes token or response text."""


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never forward an API bearer token to a redirecting destination.
        return None


def _identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ZONE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a 32-character hexadecimal Cloudflare ID")
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 253 or not _DNS_NAME.fullmatch(value):
        raise ValueError("DNS name must be a valid bounded ASCII DNS name")
    return value.rstrip(".").lower()


def _page(params: dict[str, Any]) -> dict[str, str]:
    query: dict[str, str] = {}
    for field, maximum in (("page", 100000), ("per_page", 100)):
        value = params.get(field)
        if value is not None:
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{field} must be a positive bounded integer")
            query[field] = str(value)
    return query



class CloudflareProvider(BaseInfrastructureIntegration):
    _capabilities = ("accounts", "zones", "dns_records", "zone_security_headers")

    def __init__(self, name: str = "cloudflare") -> None:
        descriptor = IntegrationDescriptor(
            name=name,
            kind=IntegrationKind.DNS,
            capabilities=tuple(
                IntegrationCapability(item) for item in self._capabilities
            ),
        )
        super().__init__(descriptor)
        self._endpoint: str | None = None
        self._token: str | None = None

    @staticmethod
    def _transport(request: Request) -> bytes:
        # Explicitly disable proxy-env routing and redirects: no bearer leakage.
        opener = build_opener(ProxyHandler({}), _RejectRedirects())
        with opener.open(request, timeout=8) as response:
            raw = response.read(_MAX_JSON_BYTES + 1)
        return raw

    def _api(
        self, token: str, method: str, path: str,
        *, params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/") or "//" in path or "?" in path or "#" in path:
            raise ValueError("invalid Cloudflare API path")
        if method != "GET" or body is not None:
            raise PermissionError("Cloudflare API adapter is read-only")
        url = _API + path
        if params:
            url += "?" + urlencode(params)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        request = Request(url, headers=headers, method="GET")
        try:
            response = self._transport(request)
        except HTTPError as exc:
            raise CloudflareRequestError(
                f"Cloudflare API rejected request with HTTP {exc.code}"
            ) from None
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            raise CloudflareRequestError(
                f"Cloudflare API transport unavailable ({type(exc).__name__})"
            ) from None
        if len(response) > _MAX_JSON_BYTES:
            raise CloudflareRequestError("Cloudflare API response exceeds safe size")
        try:
            decoded = json.loads(response)
        except (UnicodeError, ValueError, TypeError):
            raise CloudflareRequestError("Cloudflare API returned invalid JSON") from None
        if not isinstance(decoded, dict) or decoded.get("success") is not True:
            raise CloudflareRequestError("Cloudflare API did not confirm success")
        if "result" not in decoded:
            raise CloudflareRequestError("Cloudflare API result is missing")
        return decoded

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        self._endpoint = None
        self._token = None
        # Disallow arbitrary hosts and reflected endpoint URLs (SSRF/token exfil).
        if profile.endpoint and profile.endpoint.rstrip("/") != _API:
            raise ValueError("Cloudflare API host cannot be overridden")
        credential = context.get("credential")
        if not isinstance(credential, Credential) or not isinstance(credential.token, str):
            raise PermissionError("actual Cloudflare API token is required")
        token = credential.token
        if not token or len(token) > 1024 or any(c.isspace() or ord(c) < 33 for c in token):
            raise PermissionError("Cloudflare API token format is invalid")
        result = await asyncio.to_thread(self._api, token, "GET", "/user/tokens/verify")
        verification = result.get("result")
        if not isinstance(verification, dict) or verification.get("status") != "active":
            raise PermissionError("Cloudflare token has not been verified active")
        self._token = token
        self._endpoint = _API

    async def _disconnect(self) -> None:
        self._token = None
        self._endpoint = None

    async def _health_check(self) -> HealthReport:
        token = self._token
        if not token:
            return HealthReport(self.name, ConnectionState.DISCONNECTED,
                                message="Cloudflare API not authenticated")
        start = time.monotonic()
        try:
            response = await asyncio.to_thread(
                self._api, token, "GET", "/user/tokens/verify"
            )
            value = response.get("result")
            status = value.get("status") if isinstance(value, dict) else None
            if status != "active":
                raise CloudflareRequestError("Cloudflare API token is not active")
        except (CloudflareRequestError, ValueError, TypeError):
            return HealthReport(self.name, ConnectionState.FAILED,
                                message="Cloudflare authenticated API check failed")
        return HealthReport(
            self.name, ConnectionState.CONNECTED,
            latency_ms=round((time.monotonic() - start) * 1000, 2),
            message="Cloudflare API token verified active",
            details={"endpoint": _API},
        )

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        token = self._token
        if token is None:
            raise PermissionError("Cloudflare provider is not authenticated")
        if not isinstance(payload, dict):
            raise ValueError("Cloudflare payload must be an object")
        path: str
        params: dict[str, str] = {}
        method = "GET"
        body = None
        if capability == "accounts":
            path = "/accounts"
            params = _page(payload)
        elif capability == "zones":
            path = "/zones"
            params = _page(payload)
            if "name" in payload:
                params["name"] = _name(payload["name"])
        elif capability == "dns_records":
            zone = _identity(payload.get("zone_id"), "zone_id")
            path = f"/zones/{zone}/dns_records"
            params = _page(payload)
            if "name" in payload:
                params["name"] = _name(payload["name"])
            if "type" in payload:
                record_type = payload["type"]
                if not isinstance(record_type, str) or record_type not in _DNS_TYPES:
                    raise ValueError("unsupported DNS record search type")
                params["type"] = record_type
        elif capability == "zone_security_headers":
            zone = _identity(payload.get("zone_id"), "zone_id")
            path = f"/zones/{zone}/settings/security_header"
        else:
            # This is unreachable through BaseInfrastructureIntegration.execute,
            # which already rejects unadvertised capabilities. Stay fail-closed
            # if called directly instead of reporting imaginary success.
            raise KeyError("unsupported Cloudflare capability")
        response = await asyncio.to_thread(
            self._api, token, method, path, params=params, body=body
        )
        return {"provider": self.name, "operation": capability, "result": response["result"]}
