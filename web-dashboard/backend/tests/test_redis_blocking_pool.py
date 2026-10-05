"""Redis connection-pool capacity contracts."""

from __future__ import annotations

import pytest

from app.db import redis as redis_module


class _FakeClient:
    def __init__(self, *, connection_pool):
        self.connection_pool = connection_pool
        self.pinged = False
        self.closed = False

    async def ping(self):
        self.pinged = True
        return True

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_init_redis_uses_bounded_blocking_pool(monkeypatch):
    captured = {}
    pool = object()
    client_holder = {}

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return pool

    def fake_redis(*, connection_pool):
        client = _FakeClient(connection_pool=connection_pool)
        client_holder["client"] = client
        return client

    monkeypatch.setattr(
        redis_module.aioredis.BlockingConnectionPool,
        "from_url",
        fake_from_url,
    )
    monkeypatch.setattr(redis_module.aioredis, "Redis", fake_redis)
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://isolated:6379/0")
    monkeypatch.setattr(redis_module.settings, "REDIS_POOL_SIZE", 18)
    monkeypatch.setattr(redis_module.settings, "REDIS_POOL_WAIT_SECONDS", 5.0)
    redis_module.redis_client = None

    await redis_module.init_redis()

    client = client_holder["client"]
    assert captured == {
        "url": "redis://isolated:6379/0",
        "decode_responses": True,
        "max_connections": 18,
        "timeout": 5.0,
    }
    assert client.connection_pool is pool
    assert client.pinged is True
    assert await redis_module.get_redis() is client

    await redis_module.close_redis()
    assert client.closed is True
    assert redis_module.redis_client is None


@pytest.mark.asyncio
async def test_init_redis_closes_failed_client(monkeypatch):
    pool = object()

    class FailedClient(_FakeClient):
        async def ping(self):
            raise RuntimeError("synthetic redis failure")

    client = FailedClient(connection_pool=pool)
    monkeypatch.setattr(
        redis_module.aioredis.BlockingConnectionPool,
        "from_url",
        lambda *_args, **_kwargs: pool,
    )
    monkeypatch.setattr(redis_module.aioredis, "Redis", lambda **_kwargs: client)
    redis_module.redis_client = None

    with pytest.raises(RuntimeError, match="synthetic redis failure"):
        await redis_module.init_redis()

    assert client.closed is True
    assert redis_module.redis_client is None
