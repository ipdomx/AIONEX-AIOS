from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.services import firebase_phone
from app.services.free_tier import verify_phone_verification_token


def _decode_payload(token: str) -> dict:
    encoded, _ = token.split(".", 1)
    encoded += "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(encoded))


def test_issue_aios_phone_assertion_is_accepted_by_existing_registration(monkeypatch):
    secret = "x" * 32
    monkeypatch.setenv("AIOS_PHONE_VERIFICATION_SECRET", secret)
    phone = "+971501234567"

    token = firebase_phone.issue_aios_phone_assertion({"uid": "firebase-user"}, phone)
    payload = verify_phone_verification_token(token, phone)

    assert payload["verified"] is True
    assert payload["provider"] == "firebase"
    assert payload["firebase_uid"] == "firebase-user"
    assert payload["line_type"] == "mobile"


def test_issue_aios_phone_assertion_requires_strong_secret(monkeypatch):
    monkeypatch.setenv("AIOS_PHONE_VERIFICATION_SECRET", "short")
    with pytest.raises(HTTPException) as exc:
        firebase_phone.issue_aios_phone_assertion({"uid": "u"}, "+971501234567")
    assert exc.value.status_code == 503


def test_verify_firebase_phone_token_accepts_recent_phone_claim(monkeypatch):
    now = int(datetime.now(UTC).timestamp())

    class FakeAuth:
        @staticmethod
        def verify_id_token(*args, **kwargs):
            return {
                "uid": "firebase-user",
                "phone_number": "+971501234567",
                "auth_time": now,
                "firebase": {"sign_in_provider": "phone"},
            }

    monkeypatch.setattr(firebase_phone, "_firebase_app", lambda: object())
    monkeypatch.setitem(__import__("sys").modules, "firebase_admin.auth", FakeAuth)
    import firebase_admin

    monkeypatch.setattr(firebase_admin, "auth", FakeAuth, raising=False)

    claims = firebase_phone.verify_firebase_phone_token(
        "a" * 120,
        "+971501234567",
    )
    assert claims["uid"] == "firebase-user"


def test_verify_firebase_phone_token_rejects_phone_mismatch(monkeypatch):
    now = int(datetime.now(UTC).timestamp())

    class FakeAuth:
        @staticmethod
        def verify_id_token(*args, **kwargs):
            return {
                "uid": "firebase-user",
                "phone_number": "+971501234567",
                "auth_time": now,
                "firebase": {"sign_in_provider": "phone"},
            }

    monkeypatch.setattr(firebase_phone, "_firebase_app", lambda: object())
    import firebase_admin

    monkeypatch.setattr(firebase_admin, "auth", FakeAuth, raising=False)

    with pytest.raises(HTTPException) as exc:
        firebase_phone.verify_firebase_phone_token("a" * 120, "+201001234567")
    assert exc.value.status_code == 422
