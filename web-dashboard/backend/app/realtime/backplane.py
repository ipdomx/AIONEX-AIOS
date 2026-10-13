"""Distributed tenant-scoped realtime event backplane.

The production implementation uses Redis Pub/Sub for live fanout and a bounded,
tenant-hashed Redis list for cursor replay. Events without an event_id retain
legacy live-only behavior.
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
DEFAULT_MAX_RETAINED_EVENTS = 500
MAX_EVENT_ID_CHARACTERS = 256

_RETAIN_AND_PUBLISH = """
local entries = redis.call('LRANGE', KEYS[1], 0, -1)
for _, entry in ipairs(entries) do
    local ok, decoded = pcall(cjson.decode, entry)
    if ok and tostring(decoded['event_id']) == ARGV[2] then
        return 0
    end
end
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], -tonumber(ARGV[3]), -1)
redis.call('PUBLISH', KEYS[2], ARGV[1])
return 1
"""


class RealtimeBackplane(Protocol):
    """Provider-neutral contract used by horizontally scaled realtime hubs."""

    async def start(self, deliver: RealtimeDelivery) -> None: ...

    async def stop(self) -> None: ...

    async def subscribe(self, tenant_id: str) -> None: ...

    async def unsubscribe(self, tenant_id: str) -> None: ...

    async def publish(self, tenant_id: str, event: RealtimeEvent) -> None: ...

    async def read(
        self, tenant_id: str, *, after_event_id: str | None = None
    ) -> list[RealtimeEvent]: ...


def tenant_channel(tenant_id: str, *, prefix: str = DEFAULT_CHANNEL_PREFIX) -> str:
    """Return a non-reversible Redis channel name for one tenant."""

    normalized = tenant_id.strip()
    if not normalized:
        raise ValueError("tenant_id is required")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def tenant_retention_key(
    tenant_id: str, *, prefix: str = DEFAULT_CHANNEL_PREFIX
) -> str:
    """Return the bounded event-retention key for one tenant."""

    return f"{tenant_channel(tenant_id, prefix=prefix)}:retained"


def _event_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("realtime event_id must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_EVENT_ID_CHARACTERS:
        raise ValueError("realtime event_id is invalid")
    return normalized


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
    """Redis live fanout plus bounded replay with tenant-hashed storage keys."""

    def __init__(
        self,
        *,
        channel_prefix: str = DEFAULT_CHANNEL_PREFIX,
        max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES,
        max_retained_events: int = DEFAULT_MAX_RETAINED_EVENTS,
    ) -> None:
        if max_retained_events <= 0:
            raise ValueError("max_retained_events must be positive")
        self._channel_prefix = channel_prefix.rstrip(":")
        self._max_event_bytes = max_event_bytes
        self._max_retained_events = max_retained_events
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._listener: asyncio.Task[None] | None = None
        self._deliver: RealtimeDelivery | None = None
        self._channel_tenants: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

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
            self._listener = None
            self._started = True

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
            self._started = False
        if pubsub is not None and channels:
            await pubsub.unsubscribe(*channels)
        if listener is not None:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
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
            else:
                await self._pubsub.subscribe(channel)
                self._channel_tenants[channel] = tenant_id
            if self._listener is None or self._listener.done():
                self._listener = asyncio.create_task(
                    self._listen(), name="aionex-realtime-redis-listener"
                )

    async def unsubscribe(self, tenant_id: str) -> None:
        channel = tenant_channel(tenant_id, prefix=self._channel_prefix)
        listener: asyncio.Task[None] | None = None
        pubsub: Any | None = None
        async with self._lock:
            pubsub = self._pubsub
            if pubsub is None:
                self._channel_tenants.pop(channel, None)
                return
            if channel not in self._channel_tenants:
                return
            last_subscription = len(self._channel_tenants) == 1
            self._channel_tenants.pop(channel, None)
            if last_subscription:
                listener = self._listener
                self._listener = None
            # Keep channel removal ordered with concurrent subscriptions.
            # The delivery callback can remove its own final client. Such a
            # callback must never cancel/gather the task currently executing it.
            await pubsub.unsubscribe(channel)
        if listener is not None and listener is not asyncio.current_task():
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)

    async def publish(self, tenant_id: str, event: RealtimeEvent) -> None:
        payload = encode_event(event, max_bytes=self._max_event_bytes)
        channel = tenant_channel(tenant_id, prefix=self._channel_prefix)
        redis = self._redis
        if redis is None:
            raise RuntimeError("realtime backplane is not started")
        event_id = _event_id(event.get("event_id"))
        if event_id is None:
            await redis.publish(channel, payload)
            return
        retention_key = tenant_retention_key(
            tenant_id, prefix=self._channel_prefix
        )
        await redis.eval(
            _RETAIN_AND_PUBLISH,
            2,
            retention_key,
            channel,
            payload,
            event_id,
            self._max_retained_events,
        )

    async def read(
        self, tenant_id: str, *, after_event_id: str | None = None
    ) -> list[RealtimeEvent]:
        redis = self._redis
        if redis is None:
            raise RuntimeError("realtime backplane is not started")
        cursor = _event_id(after_event_id)
        retention_key = tenant_retention_key(
            tenant_id, prefix=self._channel_prefix
        )
        raw_events = await redis.lrange(retention_key, 0, -1)
        events: list[RealtimeEvent] = []
        for raw in raw_events:
            data = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        if cursor is None:
            return events
        for index, event in enumerate(events):
            if event.get("event_id") == cursor:
                return events[index + 1 :]
        return []

    async def _listen(self) -> None:
        # A retired listener exits after its current delivery, even when that
        # delivery itself removed the final subscription and a new one started.
        while self._listener is asyncio.current_task():
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
