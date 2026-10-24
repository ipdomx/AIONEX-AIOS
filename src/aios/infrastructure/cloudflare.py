"""Authenticated Cloudflare API v4 integration with no simulated successes.

Only verified API capabilities are exposed. DNS mutations require explicit
approval and validation; all other formerly mock-only capabilities fail closed.
This module has no automatic DNS, security-header, or tunnel mutations.
"""

from __future__ import annotations

import asyncio
import ipaddress
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


def _record(value: Any, *, creation: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("DNS record must be a nonempty object")
    allowed = {"name", "type", "content", "ttl", "proxied"}
    if set(value) - allowed:
        raise ValueError("DNS record contains unsupported fields")
    if creation and not {"name", "type", "content"} <= set(value):
        raise ValueError("DNS creation requires name, type and content")
    result = dict(value)
    kind = result.get("type")
    if kind is not None and (not isinstance(kind, str) or kind not in _DNS_TYPES):
        raise ValueError("DNS record type is not in the bounded supported set")
    if "name" in result:
        result["name"] = _name(result["name"])
    if "content" in result:
        content = result["content"]
        if not isinstance(content, str) or not content or len(content) > 8192:
            raise ValueError("DNS record content must be a bounded string")
        if any(ord(char) < 32 for char in content):
            raise ValueError("DNS record content contains control characters")
        if kind in ("A", "AAAA"):
            try:
                address = ipaddress.ip_address(content)
            except ValueError as exc:
                raise ValueError("DNS address content is not an IP address") from exc
            if (kind == "A" and address.version != 4) or (
                kind == "AAAA" and address.version != 6
            ):
                raise ValueError("DNS address family and type disagree")
        if kind == "CNAME":
            result["content"] = _name(content)
    if "ttl" in result:
        ttl = result["ttl"]
        if type(ttl) is not int or (ttl != 1 and not 60 <= ttl <= 86400):
            raise ValueError("DNS TTL must be automatic or 60 to 86400 seconds")
    if "proxied" in result:
        if type(result["proxied"]) is not bool:
            raise ValueError("proxied must be a boolean")
        if kind == "TXT":
            raise ValueError("TXT records cannot be proxied")
    return result


class CloudflareProvider(BaseInfrastructureIntegration):
    _capabilities = (
        "accounts", "zones", "dns_records", "zone_security_headers",
        "create_dns_record", "update_dns_record", "delete_dns_record",
    )

    def __init__(self, name: str = "cloudflare") -> None:
        writes = {"create_dns_record", "update_dns_record", "delete_dns_record"}
        descriptor = IntegrationDescriptor(
            name=name,
            kind=IntegrationKind.DNS,
            capabilities=tuple(
                IntegrationCapability(item, destructive=item in writes)
                for item in self._capabilities
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
        if method not in {"GET", "POST", "PATCH", "DELETE"}:
            raise ValueError("unapproved Cloudflare API method")
        url = _API + path
        if params:
            url += "?" + urlencode(params)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
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
        if capability in {"create_dns_record", "update_dns_record", "delete_dns_record"}:
            if payload.get("approved") is not True:
                raise PermissionError("explicit Owner approval required for DNS mutations")
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
        elif capability in {"dns_records", "create_dns_record", "update_dns_record", "delete_dns_record"}:
            zone = _identity(payload.get("zone_id"), "zone_id")
            path = f"/zones/{zone}/dns_records"
            if capability == "dns_records":
                params = _page(payload)
                if "name" in payload:
                    params["name"] = _name(payload["name"])
                if "type" in payload:
                    record_type = payload["type"]
                    if not isinstance(record_type, str) or record_type not in _DNS_TYPES:
                        raise ValueError("unsupported DNS record search type")
                    params["type"] = record_type
            elif capability == "create_dns_record":
                method = "POST"
                body = _record(payload.get("record"), creation=True)
            else:
                record_id = _identity(payload.get("record_id"), "record_id")
                path += "/" + record_id
                if capability == "update_dns_record":
                    method = "PATCH"
                    body = _record(payload.get("record"), creation=False)
                else:
                    method = "DELETE"
        elif capability == "zone_security_headers":
            zone = _identity(payload.get("zone_id"), "zone_id")
            path = f"/zones/{zone}/settings/security_header"
        else:
            # Do not report made-up success for formerly stubbed operations.
            raise NotImplementedError("Cloudflare capability is not implemented")
        response = await asyncio.to_thread(
            self._api, token, method, path, params=params, body=body
        )
        return {"provider": self.name, "operation": capability, "result": response["result"]}
