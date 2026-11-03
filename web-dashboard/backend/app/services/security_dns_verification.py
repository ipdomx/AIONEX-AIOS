"""DNS TXT ownership verification for external Security Lab targets.

A subscriber proves control of ``example.com`` by publishing::

    _aionex-security.example.com.  TXT  "aionex-verify=<token>"

Lookups use dnspython's asyncio resolver (already present in the runtime via
``email-validator``) with a hard lifetime so a slow or hostile authoritative
server cannot hold an API worker. Only the TXT record name derived from the
already-normalized target hostname is queried; no target-controlled address is
ever contacted by this module, so the existing SSRF guards stay authoritative
for HTTP-based verification and scanning.
"""

from __future__ import annotations

import ipaddress
from typing import Any

DNS_RECORD_PREFIX = "_aionex-security"
DNS_VALUE_PREFIX = "aionex-verify="
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_TXT_RECORDS = 50


class DnsVerificationError(ValueError):
    """The TXT record could not be resolved or did not contain the token."""

    code = "SECURITY_DNS_VERIFICATION_FAILED"


class DnsVerificationTimeout(DnsVerificationError):
    """The resolver did not answer within the configured lifetime."""

    code = "SECURITY_DNS_TIMEOUT"


def record_name(hostname: str) -> str:
    host = hostname.strip().lower().rstrip(".")
    if not host:
        raise DnsVerificationError("DNS verification requires a hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise DnsVerificationError(
            "DNS TXT verification requires a domain name, not an IP address"
        )
    return f"{DNS_RECORD_PREFIX}.{host}"


def record_value(token: str) -> str:
    return f"{DNS_VALUE_PREFIX}{token}"


def instructions(hostname: str, token: str) -> dict[str, Any]:
    try:
        name: str | None = record_name(hostname)
    except DnsVerificationError:
        name = None
    return {
        "method": "dns_txt",
        "available": name is not None,
        "record_name": name,
        "record_type": "TXT",
        "record_value": record_value(token),
    }


def _decode_txt(rdata: Any) -> str:
    strings = getattr(rdata, "strings", None)
    if strings is None:
        return str(rdata).strip().strip('"')
    return b"".join(
        part if isinstance(part, bytes) else str(part).encode() for part in strings
    ).decode("utf-8", "replace").strip()


async def _resolve_txt(name: str, timeout: float) -> list[str]:
    import dns.asyncresolver  # type: ignore[import-untyped]
    import dns.exception  # type: ignore[import-untyped]
    import dns.resolver  # type: ignore[import-untyped]

    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        answer = await resolver.resolve(name, "TXT", lifetime=timeout)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.Timeout as exc:
        raise DnsVerificationTimeout(
            "DNS TXT lookup timed out; try again after the record propagates"
        ) from exc
    except dns.exception.DNSException as exc:
        raise DnsVerificationError("DNS TXT lookup failed") from exc
    return [_decode_txt(item) for item in list(answer)[:MAX_TXT_RECORDS]]


async def lookup_tokens(
    hostname: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> list[str]:
    """Return every ``aionex-verify=`` token published for ``hostname``."""

    name = record_name(hostname)
    values = await _resolve_txt(name, max(0.5, min(float(timeout), 15.0)))
    tokens: list[str] = []
    for value in values:
        if value.startswith(DNS_VALUE_PREFIX):
            token = value[len(DNS_VALUE_PREFIX) :].strip()
            if token:
                tokens.append(token)
    return tokens
