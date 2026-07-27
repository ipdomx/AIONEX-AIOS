import pytest
from fastapi import HTTPException

from app.core.auth import auth_service
from app.db.base import SessionLocal
from app.db.seed import seed


@pytest.fixture(scope="module", autouse=True)
async def bootstrap_auth_data():
    await seed()


@pytest.mark.asyncio
async def test_invalid_password_is_rejected():
    async with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.authenticate(session, "owner@aionex.local", "wrong-password")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_rejects_reuse():
    async with SessionLocal() as session:
        user = await auth_service.authenticate(session, "owner@aionex.local", "ChangeMeNow!123")
        pair = await auth_service.issue_pair(session, user)
        rotated = await auth_service.refresh(session, pair["refresh_token"])
        assert rotated["access_token"] != pair["access_token"]
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.refresh(session, pair["refresh_token"])
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_access_token_is_rejected():
    async with SessionLocal() as session:
        user = await auth_service.authenticate(session, "owner@aionex.local", "ChangeMeNow!123")
        token = auth_service.create_access_token(user)
        await auth_service.revoke_access_token(token)
        with pytest.raises(HTTPException) as exc_info:
            auth_service.decode_access_token(token)
        assert exc_info.value.status_code == 401
