"""Phase 29C password recovery, MFA, and session lifecycle acceptance."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.requests import Request

from app.api.v1.router import api_router
from app.core.auth import auth_service, pwd_context
from app.db.base import SessionLocal
from app.db.models import PasswordResetToken, RefreshSession, User, UserMFA
from app.db.seed import seed
from app.services import account_security


class _FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.values: set[str] = set()

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        assert seconds > 0
        return True

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        assert value == "1"
        assert ex is None or ex > 0
        if nx and key in self.values:
            return False
        self.values.add(key)
        return True


def _request(path: str = "/api/v1/auth/password-reset") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 41000),
            "server": ("test", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
async def test_password_reset_is_neutral_single_use_and_revokes_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    email = f"phase29c-reset-{suffix}@example.com"
    original_password = f"Original!{suffix}"
    replacement_password = f"Replacement!{suffix}"
    redis = _FakeRedis()
    captured: dict[str, str] = {}

    async def fake_get_redis() -> _FakeRedis:
        return redis

    def capture_delivery(recipient: str, token: str) -> None:
        captured["recipient"] = recipient
        captured["token"] = token

    monkeypatch.setattr(account_security, "get_redis", fake_get_redis)
    monkeypatch.setattr(account_security, "_deliver_password_reset", capture_delivery)

    async with SessionLocal() as session:
        user = await auth_service.register(
            session,
            email=email,
            password=original_password,
            name="Phase 29C Recovery",
            organization_name=f"Phase 29C Recovery {suffix}",
        )
        pair = await auth_service.issue_pair(session, user)
        response = await account_security.request_password_reset(
            session,
            _request(),
            email,
        )
        assert response == {
            "message": (
                "If the account exists, password recovery instructions will be sent."
            )
        }
        assert captured["recipient"] == email
        assert captured["token"] not in str(
            (
                await session.scalars(
                    select(PasswordResetToken).where(
                        PasswordResetToken.user_id == user.id
                    )
                )
            ).all()
        )

        result = await account_security.confirm_password_reset(
            session,
            _request("/api/v1/auth/password-reset/confirm"),
            captured["token"],
            replacement_password,
        )
        assert result["message"] == "Password reset completed successfully"

        stored_user = await session.get(User, user.id)
        assert stored_user is not None
        assert pwd_context.verify(replacement_password, stored_user.password_hash)
        assert not pwd_context.verify(original_password, stored_user.password_hash)
        assert stored_user.auth_version == user.auth_version + 1
        refresh = await session.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash
                == account_security._token_hash(pair["refresh_token"])
            )
        )
        assert refresh is not None and refresh.revoked_at is not None

        with pytest.raises(Exception) as reused:
            await account_security.confirm_password_reset(
                session,
                _request("/api/v1/auth/password-reset/confirm"),
                captured["token"],
                f"Another!{suffix}",
            )
        assert getattr(reused.value, "status_code", None) == 400

        unknown = await account_security.request_password_reset(
            session,
            _request(),
            f"unknown-{suffix}@example.com",
        )
        assert unknown == response


@pytest.mark.asyncio
async def test_totp_mfa_requires_one_time_challenge_and_supports_backup_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex
    email = f"phase29c-mfa-{suffix}@example.com"
    password = f"SecureMfa!{suffix}"
    redis = _FakeRedis()

    async def fake_get_redis() -> _FakeRedis:
        return redis

    monkeypatch.setattr(account_security, "get_redis", fake_get_redis)

    async with SessionLocal() as session:
        user = await auth_service.register(
            session,
            email=email,
            password=password,
            name="Phase 29C MFA",
            organization_name=f"Phase 29C MFA {suffix}",
        )
        setup = await account_security.start_mfa_setup(session, user)
        assert len(setup["backup_codes"]) == 8
        assert setup["secret"] not in str(await session.get(UserMFA, user.id))
        code = account_security._totp(str(setup["secret"]))
        status = await account_security.confirm_mfa_setup(session, user, code)
        assert status["enabled"] is True
        assert status["backup_codes_remaining"] == 8

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-AIOS-Auth-Channel": "public"},
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": email, "password": password},
        )
        assert login.status_code == 200, login.text
        challenge = login.json()
        assert challenge["mfa_required"] is True
        assert "access_token" not in challenge
        assert "refresh_token" not in challenge

        backup_code = str(setup["backup_codes"][0])
        completed = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={
                "challenge_token": challenge["challenge_token"],
                "code": backup_code,
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["user"]["email"] == email

        replay = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={
                "challenge_token": challenge["challenge_token"],
                "code": backup_code,
            },
        )
        assert replay.status_code == 401

    async with SessionLocal() as session:
        record = await session.get(UserMFA, user.id)
        assert record is not None and record.enabled is True
        assert len(record.backup_code_hashes) == 7


def test_phase29c_frontends_do_not_restore_identity_placeholders() -> None:
    root = Path(__file__).resolve().parents[3]
    identity_pages = [
        root / "web-dashboard/frontend/src/app/users/page.tsx",
        root / "web-dashboard/frontend/src/app/users/organizations/page.tsx",
        root / "web-dashboard/frontend/src/app/users/teams/page.tsx",
        root / "web-dashboard/frontend/src/app/users/roles/page.tsx",
        root / "web-dashboard/frontend/src/app/users/permissions/page.tsx",
    ]
    for path in identity_pages:
        source = path.read_text(encoding="utf-8")
        assert "under development" not in source.lower()
        assert "const users = [" not in source
        assert "identityApi" in source

    portal_api = (root / "vip-frontend/src/lib/api.ts").read_text(encoding="utf-8")
    login = (
        root / "vip-frontend/src/components/pages/login-client.tsx"
    ).read_text(encoding="utf-8")
    profile = (
        root / "vip-frontend/src/components/pages/profile-client.tsx"
    ).read_text(encoding="utf-8")
    assert "/auth/password-reset" in portal_api
    assert "/auth/mfa/challenge" in portal_api
    assert "/settings/sessions" in portal_api
    assert "mfaChallenge" in login
    assert "AccountSecurityManager" in profile

    owner_auth = (
        root / "web-dashboard/frontend/src/lib/auth-service.ts"
    ).read_text(encoding="utf-8")
    owner_gate = (
        root / "web-dashboard/frontend/src/components/auth/AuthGate.tsx"
    ).read_text(encoding="utf-8")
    owner_settings = (
        root / "web-dashboard/frontend/src/app/settings/page.tsx"
    ).read_text(encoding="utf-8")
    assert "/auth/mfa/challenge" in owner_auth
    assert "mfaChallenge" in owner_gate
    assert "OwnerAccountSecurityManager" in owner_settings

    canonical_auth = (
        root / "web-dashboard/backend/app/api/v1/endpoints/auth.py"
    ).read_text(encoding="utf-8")
    compatibility_auth = (
        root / "web-dashboard/backend/app/api/v1/auth.py"
    ).read_text(encoding="utf-8")
    assert "HTTP_501_NOT_IMPLEMENTED" not in canonical_auth
    assert "HTTP_501_NOT_IMPLEMENTED" not in compatibility_auth
