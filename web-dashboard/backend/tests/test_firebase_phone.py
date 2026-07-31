"""Unit tests for Firebase-backed phone verification."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import firebase_phone


def test_firebase_phone_token_binds_verified_number(monkeypatch):
    monkeypatch.setattr(firebase_phone, "_firebase_app", lambda: object())
    monkeypatch.setattr(
        firebase_phone,
        "auth",
        SimpleNamespace(
            verify_id_token=lambda token, app, check_revoked: {
                "uid": "firebase-user-1",
                "phone_number": "+971501234567",
                "auth_time": 1_700_000_000,
                "firebase": {"sign_in_provider": "phone"},
            }
        ),
    )

    assertion = firebase_phone.verify_firebase_phone_token(
        "firebase-id-token",
        "+971501234567",
    )

    assert assertion["verified"] is True
    assert assertion["provider"] == "firebase"
    assert assertion["phone_number"] == "+971501234567"
    assert assertion["firebase_uid"] == "firebase-user-1"


def test_firebase_phone_token_rejects_number_mismatch(monkeypatch):
    monkeypatch.setattr(firebase_phone, "_firebase_app", lambda: object())
    monkeypatch.setattr(
        firebase_phone,
        "auth",
        SimpleNamespace(
            verify_id_token=lambda token, app, check_revoked: {
                "uid": "firebase-user-1",
                "phone_number": "+971501234567",
                "firebase": {"sign_in_provider": "phone"},
            }
        ),
    )

    with pytest.raises(HTTPException) as exc:
        firebase_phone.verify_firebase_phone_token(
            "firebase-id-token",
            "+971509999999",
        )

    assert exc.value.status_code == 422


def test_firebase_phone_token_rejects_non_phone_provider(monkeypatch):
    monkeypatch.setattr(firebase_phone, "_firebase_app", lambda: object())
    monkeypatch.setattr(
        firebase_phone,
        "auth",
        SimpleNamespace(
            verify_id_token=lambda token, app, check_revoked: {
                "uid": "firebase-user-1",
                "phone_number": "+971501234567",
                "firebase": {"sign_in_provider": "password"},
            }
        ),
    )

    with pytest.raises(HTTPException) as exc:
        firebase_phone.verify_firebase_phone_token(
            "firebase-id-token",
            "+971501234567",
        )

    assert exc.value.status_code == 422
