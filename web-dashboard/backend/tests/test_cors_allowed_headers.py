"""The portal calls the API cross-origin, so every request header it sends must pass CORS preflight."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from main import app

REPO = Path(__file__).resolve().parents[3]
FRONTENDS = (REPO / "vip-frontend" / "src", REPO / "web-dashboard" / "frontend" / "src")
HEADER_KEY = re.compile(r'"((?:X-[A-Za-z-]+)|(?:[A-Z][a-z]+-[A-Z][A-Za-z-]*))"\s*:')
SAFE = {"content-type", "accept", "accept-language", "content-language"}


def _frontend_request_headers() -> set[str]:
    found: set[str] = set()
    for root in FRONTENDS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.ts*"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "headers" not in text:
                continue
            found.update(match.lower() for match in HEADER_KEY.findall(text))
    return found - SAFE


def _cors_allowed_headers() -> set[str]:
    for middleware in app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            return {header.lower() for header in middleware.kwargs["allow_headers"]}
    raise AssertionError("CORSMiddleware is not installed")


def test_every_frontend_request_header_is_cors_allowed() -> None:
    headers = _frontend_request_headers()
    assert "idempotency-key" in headers
    assert headers <= _cors_allowed_headers()


@pytest.mark.asyncio
async def test_billing_checkout_preflight_accepts_idempotency_key() -> None:
    origin = next(iter(settings.CORS_ORIGINS))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/api/v1/billing/checkout",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,idempotency-key",
            },
        )
    assert response.status_code == 200
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
