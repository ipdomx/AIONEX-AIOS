from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.services import firebase_social, passkeys
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_firebase_social_token_normalizes_verified_provider_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    monkeypatch.setattr(
        firebase_social,
        "_verify_id_token_sync",
        lambda token: {
            "uid": "firebase-user",
            "email": "User@Example.com",
            "email_verified": True,
            "auth_time": now,
            "firebase": {
                "sign_in_provider": "google.com",
                "identities": {"google.com": ["google-subject"]},
            },
        },
    )
    monkeypatch.setattr(
        firebase_social.settings,
        "FIREBASE_SOCIAL_PROVIDERS",
        ["google"],
    )

    identity = await firebase_social.verify_firebase_social_id_token("x" * 200)

    assert identity["provider"] == "google"
    assert identity["subject"] == "google-subject"
    assert identity["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_firebase_social_token_rejects_unapproved_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    monkeypatch.setattr(
        firebase_social,
        "_verify_id_token_sync",
        lambda token: {
            "uid": "firebase-user",
            "email": "user@example.com",
            "email_verified": True,
            "auth_time": now,
            "firebase": {"sign_in_provider": "phone"},
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        await firebase_social.verify_firebase_social_id_token("x" * 200)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "SOCIAL_PROVIDER_NOT_ALLOWED"


def test_social_public_configuration_exposes_browser_provider_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        firebase_social,
        "firebase_public_configuration",
        lambda: {
            "enabled": True,
            "web_config": {"apiKey": "public", "projectId": "aionex"},
        },
    )
    monkeypatch.setattr(
        firebase_social.settings,
        "FIREBASE_SOCIAL_PROVIDERS",
        ["google", "instagram"],
    )

    result = firebase_social.firebase_social_public_configuration()

    assert result["enabled"] is True
    assert result["providers"] == [
        {
            "id": "google",
            "label": "Google",
            "firebase_provider": "google.com",
            "enabled": True,
        },
        {
            "id": "instagram",
            "label": "Instagram",
            "firebase_provider": "oidc.instagram",
            "enabled": True,
        },
    ]


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, **kwargs) -> bool:
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


@pytest.mark.asyncio
async def test_passkey_ceremony_is_bound_and_consumed_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()

    async def fake_get_redis() -> FakeRedis:
        return redis

    monkeypatch.setattr(passkeys, "get_redis", fake_get_redis)
    challenge = b"aionex-passkey-challenge"
    ceremony_id = await passkeys._store_ceremony(
        "registration", challenge, user_id="user-1"
    )

    consumed = await passkeys._consume_ceremony(
        ceremony_id, "registration", user_id="user-1"
    )
    assert consumed == challenge

    with pytest.raises(HTTPException) as exc_info:
        await passkeys._consume_ceremony(ceremony_id, "registration", user_id="user-1")
    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_social_registration_assertion_is_one_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()

    async def fake_get_redis() -> FakeRedis:
        return redis

    monkeypatch.setattr(firebase_social, "get_redis", fake_get_redis)
    prepared = await firebase_social.create_social_registration(
        {
            "provider": "google",
            "subject": "google-subject",
            "firebase_uid": "firebase-user",
            "email": "user@example.com",
            "name": "AIONEX User",
            "picture": None,
        }
    )

    identity = await firebase_social.consume_social_registration(
        prepared["registration_token"]
    )
    assert identity["provider"] == "google"
    assert identity["email"] == "user@example.com"

    with pytest.raises(HTTPException) as exc_info:
        await firebase_social.consume_social_registration(
            prepared["registration_token"]
        )
    assert exc_info.value.status_code == 410


def test_passkey_credential_id_is_canonical_base64url() -> None:
    assert passkeys.canonical_credential_id("AQIDBA==") == "AQIDBA"


def test_passkey_credential_id_rejects_invalid_base64url() -> None:
    with pytest.raises(HTTPException) as exc_info:
        passkeys.canonical_credential_id("not valid!!!")
    assert exc_info.value.status_code == 422
