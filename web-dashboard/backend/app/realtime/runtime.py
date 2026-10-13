"""Production lifecycle owner for the distributed realtime event hub.

The API process owns one local websocket hub and one Redis backplane. Only local
sockets live in process memory; live fanout and bounded cursor replay are carried
by Redis with tenant-hashed keys. LiveKit/TURN media activation is separate.
"""

from __future__ import annotations

from app.realtime.backplane import RedisRealtimeBackplane, RealtimeEvent
from app.realtime.hub import DistributedRealtimeHub


class RealtimeEventRuntime:
    """Small lifecycle facade used by API routes and notification publishers."""

    def __init__(self) -> None:
        self._hub = DistributedRealtimeHub(RedisRealtimeBackplane())

    @property
    def started(self) -> bool:
        return self._hub.started

    async def start(self) -> None:
        await self._hub.start()

    async def stop(self) -> None:
        await self._hub.stop()

    async def connect(
        self,
        tenant_id: str,
        websocket: object,
        *,
        after_event_id: str | None = None,
    ) -> None:
        await self._hub.connect(
            tenant_id, websocket, after_event_id=after_event_id
        )

    async def replay(
        self, tenant_id: str, websocket: object, *, after_event_id: str
    ) -> None:
        await self._hub.replay(
            tenant_id, websocket, after_event_id=after_event_id
        )

    async def disconnect(self, tenant_id: str, websocket: object) -> None:
        await self._hub.disconnect(tenant_id, websocket)

    async def publish(self, tenant_id: str, event: RealtimeEvent) -> None:
        await self._hub.publish(tenant_id, event)

    def connected_count(self, tenant_id: str | None = None) -> int:
        return self._hub.connected_count(tenant_id)


realtime_event_runtime = RealtimeEventRuntime()
