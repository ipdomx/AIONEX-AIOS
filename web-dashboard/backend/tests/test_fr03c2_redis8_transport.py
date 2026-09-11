from __future__ import annotations

import asyncio
import os
from importlib.metadata import version
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from app.db import redis as redis_module
from app.realtime.backplane import RedisRealtimeBackplane
from app.services.project_execution_admission import _ACQUIRE_SCRIPT, _RELEASE_SCRIPT


def _redis_url() -> str:
    value = os.environ.get("REDIS_URL", "").strip()
    if not value:
        pytest.skip("REDIS_URL is required for the Redis transport acceptance")
    return value


@pytest.mark.asyncio
async def test_redis8_client_and_admission_lua_contract() -> None:
    assert version("redis") == "8.1.0"
    client = aioredis.from_url(_redis_url(), decode_responses=True, max_connections=8)
    key = f"fr03c2:admission:{uuid4().hex}"
    token_a = uuid4().hex
    token_b = uuid4().hex
    try:
        assert await client.ping() is True
        acquired_a = await client.eval(_ACQUIRE_SCRIPT, 1, key, token_a, 1, 5_000)
        assert int(acquired_a) == 1
        acquired_b_while_full = await client.eval(
            _ACQUIRE_SCRIPT, 1, key, token_b, 1, 5_000
        )
        assert int(acquired_b_while_full) == 0
        released_a = await client.eval(_RELEASE_SCRIPT, 1, key, token_a)
        assert int(released_a) == 1
        acquired_b = await client.eval(_ACQUIRE_SCRIPT, 1, key, token_b, 1, 5_000)
        assert int(acquired_b) == 1
        assert await client.delete(key) in {0, 1}
    finally:
        await redis_module._close_client(client)


@pytest.mark.asyncio
async def test_redis8_realtime_pubsub_contract(monkeypatch) -> None:
    assert version("redis") == "8.1.0"
    client = aioredis.from_url(_redis_url(), decode_responses=True, max_connections=8)
    delivered: list[tuple[str, dict]] = []

    async def fake_get_redis():
        return client

    async def deliver(tenant_id: str, event: dict) -> None:
        delivered.append((tenant_id, event))

    monkeypatch.setattr(redis_module, "get_redis", fake_get_redis)
    backplane = RedisRealtimeBackplane(channel_prefix=f"fr03c2:{uuid4().hex}")
    try:
        await backplane.start(deliver)
        await backplane.subscribe("tenant-a")
        await backplane.publish("tenant-a", {"type": "redis8.acceptance", "ok": True})
        for _ in range(100):
            if delivered:
                break
            await asyncio.sleep(0.02)
        assert delivered == [
            ("tenant-a", {"type": "redis8.acceptance", "ok": True})
        ]
        await backplane.unsubscribe("tenant-a")
    finally:
        await backplane.stop()
        await redis_module._close_client(client)
