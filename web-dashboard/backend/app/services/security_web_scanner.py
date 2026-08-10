"""Built-in passive web, TLS, DNS, header and CSP validation.

These probes intentionally avoid exploit payloads. Intrusive validation is delegated
to separately admitted clone-only adapters after target authorization.
"""
from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.security_fabric import assert_public_target

SECURITY_HEADERS = {
    "strict-transport-security": ("high", "Enable HSTS with an appropriate max-age after validating HTTPS coverage."),
    "content-security-policy": ("high", "Deploy a restrictive Content-Security-Policy and remove unsafe directives where practical."),
    "x-content-type-options": ("medium", "Set X-Content-Type-Options: nosniff."),
    "referrer-policy": ("low", "Set a privacy-preserving Referrer-Policy."),
    "permissions-policy": ("low", "Set Permissions-Policy to disable browser capabilities not required by the application."),
}


def _fingerprint(source: str, category: str, title: str, location: str = "") -> str:
    return hashlib.sha256(f"{source}|{category}|{title}|{location}".encode()).hexdigest()


def finding(
    *,
    source: str,
    category: str,
    title: str,
    severity: str,
    confidence: float,
    evidence: dict[str, Any],
    remediation: str,
    cwe: str | None = None,
    owasp: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "category": category,
        "title": title,
        "severity": severity,
        "confidence": confidence,
        "state": "observed",
        "fingerprint": _fingerprint(source, category, title, location or ""),
        "cwe": cwe,
        "owasp": owasp,
        "location": location,
        "evidence": evidence,
        "remediation": remediation,
    }


def _tls_probe(hostname: str, port: int) -> dict[str, Any]:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((hostname, port), timeout=8) as raw:
        with context.wrap_socket(raw, server_hostname=hostname) as connection:
            cert = connection.getpeercert()
            cipher = connection.cipher()
            return {
                "version": connection.version(),
                "cipher": cipher[0] if cipher else None,
                "cipher_bits": cipher[2] if cipher else None,
                "subject": cert.get("subject"),
                "issuer": cert.get("issuer"),
                "notBefore": cert.get("notBefore"),
                "notAfter": cert.get("notAfter"),
                "subjectAltName": cert.get("subjectAltName", []),
            }


def analyze_tls(origin: str, tls: dict[str, Any] | None, error: str | None = None) -> list[dict[str, Any]]:
    parsed = urlsplit(origin)
    findings: list[dict[str, Any]] = []
    if parsed.scheme != "https":
        findings.append(finding(source="aionex-tls", category="transport-security", title="Target does not use HTTPS", severity="high", confidence=0.99, evidence={"scheme": parsed.scheme}, remediation="Serve the application exclusively over HTTPS and redirect HTTP to HTTPS.", cwe="CWE-319", owasp="A02:2021"))
        return findings
    if error or tls is None:
        findings.append(finding(source="aionex-tls", category="transport-security", title="TLS handshake could not be validated", severity="high", confidence=0.90, evidence={"error_type": error or "unknown"}, remediation="Fix the certificate chain, hostname coverage, supported protocols, and TLS service availability.", cwe="CWE-295"))
        return findings
    not_after = tls.get("notAfter")
    if isinstance(not_after, str):
        try:
            expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
            days = int((expiry - datetime.now(UTC)).total_seconds() // 86400)
            if days < 0:
                findings.append(finding(source="aionex-tls", category="certificate", title="TLS certificate is expired", severity="critical", confidence=0.99, evidence={"days_remaining": days}, remediation="Replace the expired certificate immediately and verify automated renewal.", cwe="CWE-295"))
            elif days < 30:
                findings.append(finding(source="aionex-tls", category="certificate", title="TLS certificate expires soon", severity="medium", confidence=0.99, evidence={"days_remaining": days}, remediation="Renew the certificate and verify the renewal automation before expiry."))
        except ValueError:
            pass
    version = str(tls.get("version") or "")
    if version and version not in {"TLSv1.2", "TLSv1.3"}:
        findings.append(finding(source="aionex-tls", category="transport-security", title="Legacy TLS protocol negotiated", severity="high", confidence=0.95, evidence={"version": version}, remediation="Disable legacy TLS versions and require TLS 1.2 or later.", cwe="CWE-326"))
    return findings


def analyze_headers(origin: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    normalized = {key.lower(): value for key, value in headers.items()}
    findings: list[dict[str, Any]] = []
    for header, (severity, remediation) in SECURITY_HEADERS.items():
        if header not in normalized:
            findings.append(finding(source="aionex-headers", category="security-header", title=f"Missing {header}", severity=severity, confidence=0.99, evidence={"header": header}, remediation=remediation, cwe="CWE-693", location=origin))
    hsts = normalized.get("strict-transport-security", "").lower()
    if origin.startswith("https://") and hsts and "max-age=" not in hsts:
        findings.append(finding(source="aionex-headers", category="security-header", title="HSTS header is malformed", severity="medium", confidence=0.95, evidence={"header": "strict-transport-security"}, remediation="Set a valid Strict-Transport-Security max-age directive.", cwe="CWE-693", location=origin))
    xcto = normalized.get("x-content-type-options", "").lower()
    if xcto and xcto != "nosniff":
        findings.append(finding(source="aionex-headers", category="security-header", title="X-Content-Type-Options is not nosniff", severity="medium", confidence=0.99, evidence={"value": xcto}, remediation="Set X-Content-Type-Options: nosniff.", cwe="CWE-693", location=origin))
    csp = normalized.get("content-security-policy", "")
    lowered = csp.lower()
    if csp:
        if "'unsafe-eval'" in lowered:
            findings.append(finding(source="aionex-headers", category="csp", title="CSP allows unsafe-eval", severity="high", confidence=0.99, evidence={"directive": "unsafe-eval"}, remediation="Remove 'unsafe-eval' and migrate dynamic code execution to nonce/hash-based scripts.", cwe="CWE-79", location=origin))
        if "script-src" in lowered and "*" in lowered:
            findings.append(finding(source="aionex-headers", category="csp", title="CSP script-src contains wildcard sources", severity="medium", confidence=0.90, evidence={"directive": "script-src"}, remediation="Replace wildcard script sources with explicit trusted origins/nonces/hashes.", cwe="CWE-79", location=origin))
    for value in headers.get_list("set-cookie") if hasattr(headers, "get_list") else []:
        cookie = value.lower()
        cookie_name = value.split("=", 1)[0][:80]
        if "secure" not in cookie:
            findings.append(finding(source="aionex-headers", category="cookie-security", title="Cookie missing Secure flag", severity="high", confidence=0.98, evidence={"cookie": cookie_name}, remediation="Mark authentication and sensitive cookies Secure.", cwe="CWE-614", location=origin))
        if "httponly" not in cookie:
            findings.append(finding(source="aionex-headers", category="cookie-security", title="Cookie missing HttpOnly flag", severity="medium", confidence=0.90, evidence={"cookie": cookie_name}, remediation="Mark session/authentication cookies HttpOnly unless script access is explicitly required.", cwe="CWE-1004", location=origin))
        if "samesite=" not in cookie:
            findings.append(finding(source="aionex-headers", category="cookie-security", title="Cookie missing SameSite attribute", severity="medium", confidence=0.90, evidence={"cookie": cookie_name}, remediation="Set SameSite=Lax or Strict unless a documented cross-site flow requires None+Secure.", cwe="CWE-1275", location=origin))
    return findings


async def scan_web_origin(origin: str) -> dict[str, Any]:
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid web origin")
    addresses = await asyncio.to_thread(assert_public_target, parsed.hostname)
    tls: dict[str, Any] | None = None
    tls_error: str | None = None
    if parsed.scheme == "https":
        try:
            tls = await asyncio.to_thread(_tls_probe, parsed.hostname, parsed.port or 443)
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            tls_error = type(exc).__name__
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, max_redirects=5) as client:
        try:
            response = await client.get(origin + "/", headers={"User-Agent": "AIONEX-Security-Lab/1.0", "Accept": "text/html,application/json;q=0.9,*/*;q=0.1"})
            status_code = response.status_code
            final_url = str(response.url)
            headers = response.headers
        except httpx.HTTPError as exc:
            return {
                "scanner": "aionex-web-v1",
                "origin": origin,
                "resolved_addresses": addresses,
                "status": "unreachable",
                "findings": analyze_tls(origin, tls, tls_error) + [finding(source="aionex-headers", category="availability", title="HTTP endpoint could not be reached", severity="medium", confidence=0.90, evidence={"error_type": type(exc).__name__}, remediation="Confirm DNS, routing, TLS, reverse proxy and application health.", location=origin)],
            }
    findings = analyze_tls(origin, tls, tls_error)
    findings.extend(analyze_headers(origin, headers))
    if final_url.startswith("http://"):
        findings.append(finding(source="aionex-headers", category="transport-security", title="Redirect chain ended on HTTP", severity="high", confidence=0.99, evidence={"final_scheme": "http"}, remediation="Ensure all canonical redirects terminate on HTTPS.", cwe="CWE-319", location=origin))
    return {
        "scanner": "aionex-web-v1",
        "origin": origin,
        "resolved_addresses": addresses,
        "status": "completed",
        "http_status": status_code,
        "final_url": final_url,
        "tls": tls,
        "findings": findings,
    }
