"""Distributed tenant-scoped realtime event backplane.

This module is intentionally dormant in Phase 36H Part 1.  It provides the
provider-neutral contract that will replace process-local websocket fanout in a
later activation part after deterministic tests and production wiring review.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


RealtimeEvent = dict[str, Any]
RealtimeDelivery = Callable[[str, RealtimeEvent], Awaitable[None]]

DEFAULT_CHANNEL_PREFIX = "aios:realtime:v1"
DEFAULT_MAX_EVENT_BYTES = 65_536


class RealtimeBackplane(Protocol):
    """Provider-neutral contract used by horizontally scaled realtime hubs."""

    async def start(self, deliver: RealtimeDelivery) -> None: ...

    async def stop(self) -> None: ...

    async def subscribe(self, tenant_id: str) -> None: ...

    async def unsubscribe(self, tenant_id: str) -> None: ...

    async def publish(self, tenant_id: str, event: RealtimeEvent) -> None: ...


def tenant_channel(tenant_id: str, *, prefix: str = DEFAULT_CHANNEL_PREFIX) -> str:
    """Return a non-reversible Redis channel name for one tenant."""

    normalized = tenant_id.strip()
    if not normalized:
        raise ValueError("tenant_id is required")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def encode_event(event: RealtimeEvent, *, max_bytes: int = DEFAULT_MAX_EVENT_BYTES) -> str:
    """Serialize one bounded event; non-object and oversized payloads fail closed."""

    if not isinstance(event, dict):
        raise TypeError("realtime event must be a JSON object")
    payload = json.dumps(event, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    size = len(payload.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"realtime event exceeds {max_bytes} bytes")
    return payload


class RedisRealtimeBackplane:
    """Redis Pub/Sub implementation with dynamic per-tenant subscriptions.

    Only tenants with local websocket clients are subscribed on a given API
    replica.  Raw tenant identifiers are never embedded in Redis channel names.
    """

    def __init__(
        self,
        *,
        channel_prefix: str = DEFAULT_CHANNEL_PREFIX,
        max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES,
    ) -> None:
        self._channel_prefix = channel_prefix.rstrip(":")
        self._max_event_bytes = max_event_bytes
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._listener: asyncio.Task[None] | None = None
        self._deliver: RealtimeDelivery | None = None
        self._channel_tenants: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._listener is not None and not self._listener.done()

    async def start(self, deliver: RealtimeDelivery) -> None:
        async with self._lock:
            if self.started:
                return
            from app.db.redis import get_redis

            redis = await get_redis()
            pubsub = redis.pubsub(ignore_subscribe_messages=True)
            self._redis = redis
            self._pubsub = pubsub
            self._deliver = deliver
            self._listener = asyncio.create_task(
                self._listen(), name="aionex-realtime-redis-listener"
            )

    async def stop(self) -> None:
        async with self._lock:
            listener = self._listener
            pubsub = self._pubsub
            channels = tuple(self._channel_tenants)
            self._listener = None
            self._pubsub = None
            self._redis = None
            self._deliver = None
            self._channel_tenants.clear()
        if pubsub is not None and channels:
            await pubsub.unsubscribe(*channels)
        if listener is not None:
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass
        if pubsub is not None:
            closer = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if closer is not None:
                result = closer()
                if isinstance(result, Awaitable):
                    await result

    async def subscribe(self, tenant_id: str) -> None:
        channel = tenant_channel(tenant_id, prefix=self._channel_prefix)
        async with self._lock:
            if not self.started or self._pubsub is None:
                raise RuntimeError("realtime backplane is not started")
            existing = self._channel_tenants.get(channel)
            if existing is not None:
                if existing != tenant_id:
                    raise RuntimeError("tenant channel collision")
                return
            await self._pubsub.subscribe(channel)
            self._channel_tenants[channel] = tenant_id

    async def unsubscribe(self, tenant_id: str) -> None:
        channel = tenant_channel(tenant_id, prefix=self._channel_prefix)
        async with self._lock:
            if self._pubsub is None:
                self._channel_tenants.pop(channel, None)
                return
            if channel not in self._channel_tenants:
                return
            await self._pubsub.unsubscribe(channel)
            self._channel_tenants.pop(channel, None)

    async def publish(self, tenant_id: str, event: RealtimeEvent) -> None:
        payload = encode_event(event, max_bytes=self._max_event_bytes)
        channel = tenant_channel(tenant_id, prefix=self._channel_prefix)
        redis = self._redis
        if redis is None:
            raise RuntimeError("realtime backplane is not started")
        await redis.publish(channel, payload)

    async def _listen(self) -> None:
        while True:
            pubsub = self._pubsub
            if pubsub is None:
                return
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                await asyncio.sleep(0)
                continue
            channel_raw = message.get("channel")
            data_raw = message.get("data")
            channel = (
                channel_raw.decode("utf-8")
                if isinstance(channel_raw, bytes)
                else str(channel_raw)
            )
            tenant_id = self._channel_tenants.get(channel)
            deliver = self._deliver
            if tenant_id is None or deliver is None:
                continue
            data = data_raw.decode("utf-8") if isinstance(data_raw, bytes) else str(data_raw)
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            await deliver(tenant_id, event)
