import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import select

from app.api.v1.endpoints import auth as auth_endpoints
from app.core import auth as auth_module
from app.core.auth import auth_service
from app.db.base import SessionLocal
from app.db.models import Organization, Role, User
from app.db.seed import seed


@pytest.mark.asyncio
async def test_invalid_password_is_rejected():
    await seed()
    async with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.authenticate(
                session, "owner@aionex.local", "wrong-password"
            )
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_rejects_reuse():
    await seed()
    async with SessionLocal() as session:
        user = await auth_service.authenticate(
            session, "owner@aionex.local", "ChangeMeNow!123"
        )
        pair = await auth_service.issue_pair(session, user)
        rotated = await auth_service.refresh(session, pair["refresh_token"])
        assert rotated["access_token"] != pair["access_token"]
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.refresh(session, pair["refresh_token"])
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_access_token_is_rejected(monkeypatch):
    revoked: set[str] = set()

    class FakeRedis:
        async def set(self, key, value, *, ex):
            revoked.add(key)
            return True

        async def exists(self, key):
            return int(key in revoked)

    async def fake_get_redis():
        return FakeRedis()

    monkeypatch.setattr(auth_module, "get_redis", fake_get_redis)
    await seed()
    async with SessionLocal() as session:
        user = await auth_service.authenticate(
            session, "owner@aionex.local", "ChangeMeNow!123"
        )
        token = auth_service.create_access_token(user)
        await auth_service.revoke_access_token(token)
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.decode_access_token(token)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_access_and_refresh_tokens(monkeypatch):
    revoked: set[str] = set()

    class FakeRedis:
        async def set(self, key, value, *, ex):
            revoked.add(key)
            return True

        async def exists(self, key):
            return int(key in revoked)

    async def fake_get_redis():
        return FakeRedis()

    monkeypatch.setattr(auth_module, "get_redis", fake_get_redis)
    await seed()
    async with SessionLocal() as session:
        user = await auth_service.authenticate(
            session, "owner@aionex.local", "ChangeMeNow!123"
        )
        pair = await auth_service.issue_pair(session, user)

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/auth/logout",
                "query_string": b"",
                "headers": [],
                "scheme": "http",
                "server": ("test", 80),
                "client": ("127.0.0.1", 1234),
            }
        )
        response = await auth_endpoints.logout(
            request=request,
            http_response=Response(),
            data=auth_endpoints.LogoutRequest(refresh_token=pair["refresh_token"]),
            token=pair["access_token"],
            session=session,
        )
        assert response == {"message": "Logged out successfully"}

        with pytest.raises(HTTPException) as access_exc:
            await auth_service.decode_access_token(pair["access_token"])
        assert access_exc.value.status_code == 401

        with pytest.raises(HTTPException) as refresh_exc:
            await auth_service.refresh(session, pair["refresh_token"])
        assert refresh_exc.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_revocation_is_scoped_to_authenticated_user():
    await seed()
    async with SessionLocal() as session:
        user = await auth_service.authenticate(
            session, "owner@aionex.local", "ChangeMeNow!123"
        )
        pair = await auth_service.issue_pair(session, user)

        revoked = await auth_service.revoke_refresh_token(
            session,
            pair["refresh_token"],
            user_id="different-user",
        )
        assert revoked is False

        rotated = await auth_service.refresh(session, pair["refresh_token"])
        assert rotated["refresh_token"] != pair["refresh_token"]


@pytest.mark.asyncio
async def test_suspended_user_is_rejected_for_current_and_refresh_sessions():
    await seed()
    async with SessionLocal() as session:
        user_model = await session.scalar(
            select(User).where(User.email == "owner@aionex.local")
        )
        assert user_model is not None
        user = await auth_service.authenticate(
            session,
            "owner@aionex.local",
            "ChangeMeNow!123",
        )
        pair = await auth_service.issue_pair(session, user)
        original_status = user_model.status
        try:
            user_model.status = "suspended"
            await session.commit()

            with pytest.raises(HTTPException) as current_exc:
                await auth_service.get_user_by_id(session, user_model.id)
            assert current_exc.value.status_code == 403

            with pytest.raises(HTTPException) as refresh_exc:
                await auth_service.refresh(session, pair["refresh_token"])
            assert refresh_exc.value.status_code == 403

            user_model.status = original_status
            await session.commit()
            with pytest.raises(HTTPException) as consumed_exc:
                await auth_service.refresh(session, pair["refresh_token"])
            assert consumed_exc.value.status_code == 401
        finally:
            user_model.status = original_status
            await session.commit()


@pytest.mark.asyncio
async def test_inactive_organization_is_rejected_for_current_and_refresh_sessions():
    await seed()
    async with SessionLocal() as session:
        user_model = await session.scalar(
            select(User).where(User.email == "owner@aionex.local")
        )
        assert user_model is not None
        organization = await session.get(Organization, user_model.organization_id)
        assert organization is not None
        user = await auth_service.authenticate(
            session,
            "owner@aionex.local",
            "ChangeMeNow!123",
        )
        pair = await auth_service.issue_pair(session, user)
        original_status = organization.status
        try:
            organization.status = "inactive"
            await session.commit()

            with pytest.raises(HTTPException) as current_exc:
                await auth_service.get_user_by_id(session, user_model.id)
            assert current_exc.value.status_code == 403

            with pytest.raises(HTTPException) as refresh_exc:
                await auth_service.refresh(session, pair["refresh_token"])
            assert refresh_exc.value.status_code == 403

            organization.status = original_status
            await session.commit()
            with pytest.raises(HTTPException) as consumed_exc:
                await auth_service.refresh(session, pair["refresh_token"])
            assert consumed_exc.value.status_code == 401
        finally:
            organization.status = original_status
            await session.commit()


@pytest.mark.asyncio
async def test_suspended_super_owner_role_is_rejected():
    await seed()
    async with SessionLocal() as session:
        user_model = await session.scalar(
            select(User).where(User.email == "owner@aionex.local")
        )
        assert user_model is not None
        role = await session.get(Role, user_model.role_id)
        assert role is not None
        original_status = role.status
        try:
            role.status = "suspended"
            await session.commit()

            with pytest.raises(HTTPException) as current_exc:
                await auth_service.get_user_by_id(session, user_model.id)
            assert current_exc.value.status_code == 403
        finally:
            role.status = original_status
            await session.commit()


@pytest.mark.asyncio
async def test_legacy_pbkdf2_password_is_rehashed_to_argon2id_on_login():
    from passlib.context import CryptContext
    from sqlalchemy import select

    from app.core.auth import auth_service, pwd_context
    from app.db.base import SessionLocal
    from app.db.models import Organization, Role, User, uuid_str

    legacy = CryptContext(schemes=["pbkdf2_sha256"])
    password = "Legacy-Rehash-Test-Password-123!"
    email = f"legacy-rehash-{uuid_str()}@example.com"
    async with SessionLocal() as session:
        organization = await session.scalar(select(Organization).order_by(Organization.created_at))
        role = await session.scalar(select(Role).where(Role.status == "active").order_by(Role.created_at))
        assert organization is not None and role is not None
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=email,
            name="Legacy Rehash Test",
            password_hash=legacy.hash(password),
            status="active",
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    try:
        async with SessionLocal() as session:
            authenticated = await auth_service.authenticate(session, email, password)
            assert authenticated.id == user_id
            stored = await session.get(User, user_id)
            assert stored is not None
            assert stored.password_hash.startswith("$argon2id$")
            assert pwd_context.verify(password, stored.password_hash)
    finally:
        async with SessionLocal() as session:
            stored = await session.get(User, user_id)
            if stored is not None:
                await session.delete(stored)
                await session.commit()
