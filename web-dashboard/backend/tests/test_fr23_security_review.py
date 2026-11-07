"""FR-23 final security review: regression tests for the issues it fixed.

* Security Lab HTTP-file verification is pinned to the address the SSRF guard
  validated (no DNS-rebinding window), reads a bounded body and maps transport
  failures to "not confirmed" instead of a 500.
* Payment webhook signature comparison never raises on a non-ASCII header.
* HTTP client libraries never log request URLs (Meta token/secret queries).

The signed_request replay window regression lives with the other
signed_request tests in ``test_p3_social_inbox.py``. No network is used:
``socket.getaddrinfo`` and the HTTP transport are replaced in-process.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.core import logging as app_logging
from app.db.models import SecurityTarget
from app.services import billing, security_fabric

PUBLIC = "93.184.216.34"
CHALLENGE = "aionex-verify-" + "y" * 43


def _target(**overrides: Any) -> SecurityTarget:
    values: dict[str, Any] = {
        "id": "target-fr23",
        "organization_id": "org-1",
        "created_by_id": "user-1",
        "kind": "external_authorized",
        "origin": "https://example.com",
        "hostname": "example.com",
        "authorization_status": "pending",
        "verification_method": "http_file",
        "challenge_hash": hashlib.sha256(CHALLENGE.encode()).hexdigest(),
        "active_scan_allowed": False,
        "status": "active",
        "target_metadata": {},
    }
    values.update(overrides)
    return SecurityTarget(**values)


def _resolve_to(monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    """Each getaddrinfo call returns the next answer (the last one repeats)."""

    calls: list[str] = []
    queue = list(answers)

    def fake_getaddrinfo(host: str, *_args: Any, **_kwargs: Any) -> list[Any]:
        calls.append(host)
        address = queue.pop(0) if len(queue) > 1 else queue[0]
        family = security_fabric.socket.AF_INET6 if ":" in address else security_fabric.socket.AF_INET
        return [(family, security_fabric.socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(security_fabric.socket, "getaddrinfo", fake_getaddrinfo)
    return calls


def _transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(security_fabric, "_VERIFICATION_TRANSPORT", httpx.MockTransport(record))
    return seen


# --- Security Lab HTTP-file verification (SSRF / DNS rebinding) ------------------------


@pytest.mark.asyncio
async def test_http_proof_fetch_connects_to_the_validated_address(monkeypatch) -> None:
    _resolve_to(monkeypatch, PUBLIC)
    seen = _transport(monkeypatch, lambda _request: httpx.Response(200, text=CHALLENGE + "\n"))

    assert await security_fabric._http_file_value(_target()) == CHALLENGE

    (request,) = seen
    assert request.url.host == PUBLIC
    assert request.url.port in (None, 443)  # httpx normalizes the default port
    assert request.url.path == security_fabric.HTTP_VERIFICATION_PATH
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"


@pytest.mark.asyncio
async def test_http_proof_fetch_keeps_a_non_default_port_and_brackets_ipv6(monkeypatch) -> None:
    _resolve_to(monkeypatch, "2606:2800:220:1:248:1893:25c8:1946")
    seen = _transport(monkeypatch, lambda _request: httpx.Response(200, text=CHALLENGE))
    target = _target(origin="http://example.com:8443")

    assert await security_fabric._http_file_value(target) == CHALLENGE

    (request,) = seen
    assert request.url.host == "2606:2800:220:1:248:1893:25c8:1946"
    assert request.url.port == 8443
    assert request.headers["host"] == "example.com:8443"
    assert "sni_hostname" not in request.extensions


@pytest.mark.asyncio
@pytest.mark.parametrize("rebound", ["127.0.0.1", "169.254.169.254", "10.0.0.7", "::1"])
async def test_dns_rebinding_between_check_and_fetch_never_connects(monkeypatch, rebound) -> None:
    """The first answer passes the guard; the answer at fetch time is internal."""

    calls = _resolve_to(monkeypatch, PUBLIC, rebound)
    seen = _transport(monkeypatch, lambda _request: httpx.Response(200, text=CHALLENGE))
    target = _target()

    assert security_fabric.assert_public_target(target.hostname) == [PUBLIC]
    with pytest.raises(ValueError, match="public routable addresses"):
        await security_fabric._http_file_value(target)
    assert calls == ["example.com", "example.com"]
    assert seen == []


@pytest.mark.asyncio
async def test_http_proof_fetch_bounds_the_body_and_ignores_non_200(monkeypatch) -> None:
    _resolve_to(monkeypatch, PUBLIC)
    oversized = "x" * (security_fabric.VERIFICATION_MAX_RESPONSE_BYTES + 1)
    _transport(monkeypatch, lambda _request: httpx.Response(200, text=oversized))
    assert await security_fabric._http_file_value(_target()) is None

    _transport(monkeypatch, lambda _request: httpx.Response(302, headers={"Location": "http://127.0.0.1/"}))
    assert await security_fabric._http_file_value(_target()) is None


@pytest.mark.asyncio
async def test_http_proof_transport_failure_is_not_a_server_error(monkeypatch) -> None:
    _resolve_to(monkeypatch, PUBLIC)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _transport(monkeypatch, refuse)
    assert await security_fabric._http_file_value(_target()) is None


# --- payment webhook signatures ----------------------------------------------------------


@pytest.fixture
def webhook_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(billing.settings, "STRIPE_WEBHOOK_SECRET", "whsec_fr23")
    monkeypatch.setattr(billing.settings, "PADDLE_WEBHOOK_SECRET", "pdl_fr23")
    monkeypatch.setattr(billing.settings, "PAYMOB_WEBHOOK_SECRET", "paymob_fr23")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "header", "value"),
    [
        ("stripe", "Stripe-Signature", "t={ts},v1=é" + "0" * 63),
        ("paddle", "Paddle-Signature", "ts={ts};h1=é" + "0" * 63),
        ("paymob", "X-AIOS-Signature", "é" + "0" * 63),
    ],
)
async def test_non_ascii_webhook_signature_is_a_400_not_a_500(
    webhook_secrets: None, provider: str, header: str, value: str
) -> None:
    raw = json.dumps({"id": "evt_fr23", "type": "checkout.session.completed"}).encode()
    with pytest.raises(HTTPException) as error:
        await billing.verify_webhook(provider, raw, {header: value.format(ts=int(time.time()))})
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_valid_stripe_signature_is_still_accepted(webhook_secrets: None) -> None:
    raw = json.dumps({"id": "evt_fr23", "type": "invoice.paid"}).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(b"whsec_fr23", timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    headers = {"Stripe-Signature": f"t={timestamp},v1=ébad,v1={signature}"}
    assert await billing.verify_webhook("stripe", raw, headers) == json.loads(raw)


def test_digest_comparison_is_constant_time_and_total() -> None:
    assert billing._digest_equal("abc", "abc")
    assert not billing._digest_equal("abc", "abd")
    assert not billing._digest_equal("abc", "ééé")
    assert not billing._digest_equal("abc", "\udcff")


# --- log leakage ---------------------------------------------------------------------------


def test_http_client_loggers_never_log_request_urls() -> None:
    root = logging.getLogger()
    saved = {name: logging.getLogger(name).level for name in app_logging.URL_LOGGING_LIBRARIES}
    saved_root = root.level
    try:
        for name in app_logging.URL_LOGGING_LIBRARIES:
            logging.getLogger(name).setLevel(logging.NOTSET)
        root.setLevel(logging.DEBUG)

        app_logging.quiet_url_logging()

        for name in ("httpx", "httpcore"):
            library_logger = logging.getLogger(name)
            assert library_logger.getEffectiveLevel() >= logging.WARNING
            assert not library_logger.isEnabledFor(logging.INFO)
    finally:
        root.setLevel(saved_root)
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)
