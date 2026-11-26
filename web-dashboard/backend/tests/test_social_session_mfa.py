"""Social sign-in must not skip the authenticator step (same rule as password sign-in)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.v1.endpoints import identity as identity_endpoints
from app.api.v1.router import api_router
from app.core.auth import auth_service
from app.db.base import SessionLocal
from app.db.models import ExternalIdentity, RefreshSession
from app.db.seed import seed
from app.services import account_security


class _FakeRedis:
    def __init__(self) -> None:
        self.values: set[str] = set()
        self.counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values.add(key)
        return True


def _identity(email: str, subject: str) -> dict:
    return {
        "provider": "google",
        "firebase_provider": "google.com",
        "subject": subject,
        "firebase_uid": f"uid-{subject}",
        "email": email,
        "name": "Social MFA",
        "picture": None,
        "authenticated_at": datetime.now(UTC),
    }


async def _client():
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-AIOS-Auth-Channel": "public"},
    )


@pytest.mark.asyncio
async def test_social_sign_in_asks_for_the_authenticator_code_when_mfa_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    email = f"social-mfa-{suffix}@example.com"
    redis = _FakeRedis()

    async def fake_get_redis() -> _FakeRedis:
        return redis

    async def fake_verify(_token: str) -> dict:
        return _identity(email, f"sub-{suffix}")

    monkeypatch.setattr(account_security, "get_redis", fake_get_redis)
    monkeypatch.setattr(identity_endpoints, "verify_firebase_social_id_token", fake_verify)

    async with SessionLocal() as session:
        user = await auth_service.register(
            session,
            email=email,
            password=f"Strong!{suffix}",
            name="Social MFA",
            organization_name=f"Social MFA {suffix}",
        )
        setup = await account_security.start_mfa_setup(session, user)
        code = account_security._totp(str(setup["secret"]))
        await account_security.confirm_mfa_setup(session, user, code)

    async with await _client() as client:
        first = await client.post("/api/v1/auth/firebase/social/session", json={"id_token": "x" * 120})
        assert first.status_code == 200, first.text
        challenge = first.json()
        assert challenge["mfa_required"] is True
        assert "access_token" not in challenge and "refresh_token" not in challenge

        async with SessionLocal() as session:
            sessions = (await session.scalars(select(RefreshSession).where(RefreshSession.user_id == user.id))).all()
            assert sessions == []
            linked = await session.scalar(select(ExternalIdentity).where(ExternalIdentity.user_id == user.id))
            assert linked is not None and linked.provider == "google"

        completed = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={"challenge_token": challenge["challenge_token"], "code": str(setup["backup_codes"][0])},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["user"]["email"] == email


@pytest.mark.asyncio
async def test_social_sign_in_without_mfa_still_returns_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    email = f"social-plain-{suffix}@example.com"

    async def fake_verify(_token: str) -> dict:
        return _identity(email, f"sub-{suffix}")

    monkeypatch.setattr(identity_endpoints, "verify_firebase_social_id_token", fake_verify)
    async with SessionLocal() as session:
        await auth_service.register(
            session,
            email=email,
            password=f"Strong!{suffix}",
            name="Social Plain",
            organization_name=f"Social Plain {suffix}",
        )

    async with await _client() as client:
        response = await client.post("/api/v1/auth/firebase/social/session", json={"id_token": "x" * 120})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["access_token"] and body["refresh_token"]
        assert body["user"]["email"] == email
