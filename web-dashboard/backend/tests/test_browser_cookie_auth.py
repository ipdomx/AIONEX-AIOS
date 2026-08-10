"""Browser authentication uses HttpOnly cookies while native Bearer flows remain compatible."""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.auth import pwd_context
from app.db.base import SessionLocal
from app.db.redis import close_redis, init_redis
from app.db.models import Organization, RefreshSession, Role, User
from app.db.seed import seed
from main import app


@pytest.mark.asyncio
async def test_browser_session_cookie_refresh_origin_guard_and_logout() -> None:
    suffix = uuid4().hex[:12]
    email = f"cookie-auth-{suffix}@example.com"
    password = "Cookie-Auth-Test-Password-123!"
    user_id: str | None = None
    await seed()
    async with SessionLocal() as session:
        organization = await session.scalar(select(Organization).order_by(Organization.created_at))
        role = await session.scalar(
            select(Role).where(Role.status == "active", Role.name != "Super Owner").order_by(Role.created_at)
        )
        assert organization is not None and role is not None
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=email,
            name="Cookie Auth Test",
            password_hash=pwd_context.hash(password),
            status="active",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    await init_redis()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                data={"username": email, "password": password},
            )
            assert login.status_code == 200
            set_cookies = login.headers.get_list("set-cookie")
            assert any("aionex_access=" in item and "HttpOnly" in item for item in set_cookies)
            assert any("aionex_refresh=" in item and "HttpOnly" in item for item in set_cookies)

            current = await client.get("/api/v1/auth/me")
            assert current.status_code == 200
            assert current.json()["id"] == user_id

            rejected_refresh = await client.post(
                "/api/v1/auth/refresh",
                json={},
                headers={"Origin": "https://attacker.example"},
            )
            assert rejected_refresh.status_code == 403

            refreshed = await client.post(
                "/api/v1/auth/refresh",
                json={},
                headers={"Origin": "https://ai.vip-e.net"},
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["access_token"]
            assert refreshed.json()["refresh_token"]

            rejected_logout = await client.post(
                "/api/v1/auth/logout",
                json={},
                headers={"Origin": "https://attacker.example"},
            )
            assert rejected_logout.status_code == 403

            logout = await client.post(
                "/api/v1/auth/logout",
                json={},
                headers={"Origin": "https://ai.vip-e.net"},
            )
            assert logout.status_code == 200
            assert client.cookies.get("aionex_access") is None
            assert client.cookies.get("aionex_refresh") is None
    finally:
        await close_redis()
        if user_id:
            async with SessionLocal() as session:
                await session.execute(delete(RefreshSession).where(RefreshSession.user_id == user_id))
                stored = await session.get(User, user_id)
                if stored is not None:
                    await session.delete(stored)
                await session.commit()


def test_frontends_do_not_persist_access_or_refresh_tokens_in_web_storage() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    vip = (root / "vip-frontend/src/lib/api.ts").read_text(encoding="utf-8")
    owner_api = (root / "web-dashboard/frontend/src/lib/api-client.ts").read_text(encoding="utf-8")
    owner_auth = (root / "web-dashboard/frontend/src/lib/auth-service.ts").read_text(encoding="utf-8")
    forbidden = (
        "setItem(ACCESS_TOKEN_KEY",
        "setItem(REFRESH_TOKEN_KEY",
        "setItem(STORAGE_KEYS.access",
        "setItem(STORAGE_KEYS.refresh",
    )
    for source in (vip, owner_api, owner_auth):
        assert all(token not in source for token in forbidden)
    assert 'credentials: "include"' in vip
    assert "withCredentials: true" in owner_api
