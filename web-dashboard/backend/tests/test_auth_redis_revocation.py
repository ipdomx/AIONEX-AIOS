from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core import auth as auth_module
from app.core.auth import AuthService, UserRecord
from app.core.config import settings


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, tuple[str, int]] = {}
        self.fail_exists = False
        self.fail_set = False

    async def set(self, key: str, value: str, *, ex: int):
        if self.fail_set:
            raise ConnectionError("Redis unavailable")
        self.values[key] = (value, ex)
        return True

    async def exists(self, key: str) -> int:
        if self.fail_exists:
            raise ConnectionError("Redis unavailable")
        return int(key in self.values)


def _user() -> UserRecord:
    return UserRecord(
        id="user-1",
        email="owner@example.com",
        name="Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id="org-1",
        organization_name="AIONEX",
        organization_plan="enterprise",
        permissions=["*"],
    )


@pytest.mark.asyncio
async def test_revocation_is_shared_between_auth_service_instances_and_expires(
    monkeypatch,
):
    redis = FakeRedis()
    fixed_now = datetime.now(timezone.utc).replace(microsecond=0)

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(auth_module, "get_redis", fake_get_redis)
    monkeypatch.setattr(auth_module, "_now", lambda: fixed_now)

    issuing_worker = AuthService()
    validating_worker = AuthService()
    token = issuing_worker.create_access_token(_user())

    payload = await validating_worker.decode_access_token(token)
    assert payload["sub"] == "user-1"

    await issuing_worker.revoke_access_token(token)

    assert len(redis.values) == 1
    key, (value, ttl_seconds) = next(iter(redis.values.items()))
    assert key == auth_module._access_token_revocation_key(token)
    assert token not in key
    assert value == "1"
    assert ttl_seconds == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    with pytest.raises(HTTPException) as exc_info:
        await validating_worker.decode_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token has been revoked"


@pytest.mark.asyncio
async def test_validation_fails_closed_when_revocation_store_is_unavailable(
    monkeypatch,
):
    redis = FakeRedis()
    redis.fail_exists = True

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(auth_module, "get_redis", fake_get_redis)
    token = AuthService().create_access_token(_user())

    with pytest.raises(HTTPException) as exc_info:
        await AuthService().decode_access_token(token)
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Authentication state is temporarily unavailable"
    assert exc_info.value.headers == {"Retry-After": "5"}


@pytest.mark.asyncio
async def test_logout_does_not_report_success_when_revocation_cannot_be_persisted(
    monkeypatch,
):
    redis = FakeRedis()
    redis.fail_set = True

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(auth_module, "get_redis", fake_get_redis)
    token = AuthService().create_access_token(_user())

    with pytest.raises(HTTPException) as exc_info:
        await AuthService().revoke_access_token(token)
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Authentication state is temporarily unavailable"
