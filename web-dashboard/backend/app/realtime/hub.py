"""Horizontally scalable local websocket fanout hub for Phase 36H."""

from __future__ import annotations

import asyncio
from typing import Any

from app.realtime.backplane import RealtimeBackplane, RealtimeEvent


class DistributedRealtimeHub:
    """Maintain only local sockets while the backplane carries cross-node events."""

    def __init__(self, backplane: RealtimeBackplane) -> None:
        self._backplane = backplane
        self._clients: dict[str, set[Any]] = {}
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        await self._backplane.start(self._deliver_local)
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await self._backplane.stop()
        async with self._lock:
            self._clients.clear()
        self._started = False

    async def connect(self, tenant_id: str, websocket: Any) -> None:
        if not self._started:
            raise RuntimeError("distributed realtime hub is not started")
        await websocket.accept()
        subscribe = False
        async with self._lock:
            clients = self._clients.setdefault(tenant_id, set())
            subscribe = not clients
            clients.add(websocket)
        if not subscribe:
            return
        try:
            await self._backplane.subscribe(tenant_id)
        except Exception:
            async with self._lock:
                rollback_clients = self._clients.get(tenant_id)
                if rollback_clients is not None:
                    rollback_clients.discard(websocket)
                    if not rollback_clients:
                        self._clients.pop(tenant_id, None)
            raise

    async def disconnect(self, tenant_id: str, websocket: Any) -> None:
        unsubscribe = False
        async with self._lock:
            clients = self._clients.get(tenant_id)
            if clients is None:
                return
            clients.discard(websocket)
            if not clients:
                self._clients.pop(tenant_id, None)
                unsubscribe = True
        if unsubscribe and self._started:
            await self._backplane.unsubscribe(tenant_id)

    async def publish(self, tenant_id: str, event: RealtimeEvent) -> None:
        if not self._started:
            raise RuntimeError("distributed realtime hub is not started")
        await self._backplane.publish(tenant_id, event)

    async def _deliver_local(self, tenant_id: str, event: RealtimeEvent) -> None:
        async with self._lock:
            clients = tuple(self._clients.get(tenant_id, ()))
        stale: list[Any] = []
        for client in clients:
            try:
                await client.send_json(event)
            except Exception:
                stale.append(client)
        for client in stale:
            await self.disconnect(tenant_id, client)

    def connected_count(self, tenant_id: str | None = None) -> int:
        if tenant_id is not None:
            return len(self._clients.get(tenant_id, ()))
        return sum(len(clients) for clients in self._clients.values())
