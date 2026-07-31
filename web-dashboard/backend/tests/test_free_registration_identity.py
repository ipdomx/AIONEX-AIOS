from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.services.free_tier import (
    _age_on,
    _assert_real_device_signals,
    verify_phone_verification_token,
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _token(secret: bytes, payload: dict) -> str:
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret, encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64(signature)}"


def test_phone_assertion_accepts_only_verified_mobile(monkeypatch):
    secret = b"x" * 32
    monkeypatch.setenv("AIOS_PHONE_VERIFICATION_SECRET", secret.decode())
    phone = "+971501234567"
    token = _token(
        secret,
        {
            "phone_number": phone,
            "verified": True,
            "line_type": "mobile",
            "provider": "test-provider",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        },
    )
    assert verify_phone_verification_token(token, phone)["line_type"] == "mobile"


@pytest.mark.parametrize("line_type", ["voip", "virtual", "landline", "unknown"])
def test_phone_assertion_rejects_virtual_and_non_mobile(monkeypatch, line_type):
    secret = b"y" * 32
    monkeypatch.setenv("AIOS_PHONE_VERIFICATION_SECRET", secret.decode())
    phone = "+201001234567"
    token = _token(
        secret,
        {
            "phone_number": phone,
            "verified": True,
            "line_type": line_type,
            "provider": "test-provider",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        },
    )
    with pytest.raises(HTTPException) as exc:
        verify_phone_verification_token(token, phone)
    assert exc.value.status_code == 422


def test_phone_assertion_rejects_tampered_signature(monkeypatch):
    secret = b"z" * 32
    monkeypatch.setenv("AIOS_PHONE_VERIFICATION_SECRET", secret.decode())
    phone = "+971501234567"
    token = _token(
        secret,
        {
            "phone_number": phone,
            "verified": True,
            "line_type": "mobile",
            "provider": "test-provider",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        },
    )
    encoded, _ = token.split(".", 1)
    tampered = f"{encoded}.{_b64(b'not-a-valid-signature')}"
    with pytest.raises(HTTPException) as exc:
        verify_phone_verification_token(tampered, phone)
    assert exc.value.status_code == 422


def test_minimum_age_calculation_is_calendar_correct():
    assert _age_on(date(2000, 8, 1), date(2026, 7, 31)) == 25
    assert _age_on(date(2000, 7, 31), date(2026, 7, 31)) == 26


def test_real_device_signals_accept_supported_browser():
    _assert_real_device_signals(
        {
            "cookie_enabled": True,
            "webdriver": False,
            "hardware_concurrency": 8,
            "platform": "iPhone",
            "user_agent": "Mozilla/5.0 Mobile Safari/604.1",
        }
    )


def test_real_device_signals_fail_closed_for_headless_browser():
    with pytest.raises(HTTPException) as exc:
        _assert_real_device_signals(
            {
                "cookie_enabled": True,
                "hardware_concurrency": 8,
                "platform": "Linux x86_64",
                "user_agent": "HeadlessChrome",
            }
        )
    assert exc.value.status_code == 422
