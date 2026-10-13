from __future__ import annotations

from typing import Any

import pytest

from app.realtime.hub import DistributedRealtimeHub


class FakeSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict[str, Any]) -> None:
        self.messages.append(dict(event))


class RetainedBackplane:
    def __init__(self) -> None:
        self.deliver = None
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.subscriptions: set[str] = set()
        self.emit_during_read = False

    async def start(self, deliver) -> None:
        self.deliver = deliver

    async def stop(self) -> None:
        self.deliver = None
        self.subscriptions.clear()

    async def subscribe(self, tenant_id: str) -> None:
        self.subscriptions.add(tenant_id)

    async def unsubscribe(self, tenant_id: str) -> None:
        self.subscriptions.discard(tenant_id)

    async def publish(self, tenant_id: str, event: dict[str, Any]) -> None:
        retained = self.events.setdefault(tenant_id, [])
        event_id = event.get("event_id")
        if event_id is not None and any(
            item.get("event_id") == event_id for item in retained
        ):
            return
        retained.append(dict(event))
        if tenant_id in self.subscriptions and self.deliver is not None:
            await self.deliver(tenant_id, dict(event))

    async def read(
        self, tenant_id: str, *, after_event_id: str | None = None
    ) -> list[dict[str, Any]]:
        retained = [dict(item) for item in self.events.get(tenant_id, ())]
        if self.emit_during_read and retained and self.deliver is not None:
            await self.deliver(tenant_id, dict(retained[-1]))
        if after_event_id is None:
            return retained
        for index, event in enumerate(retained):
            if event.get("event_id") == after_event_id:
                return retained[index + 1 :]
        return []


@pytest.mark.asyncio
async def test_reconnect_replays_terminal_event_published_while_absent() -> None:
    backplane = RetainedBackplane()
    hub = DistributedRealtimeHub(backplane)
    await hub.start()
    cursor = {"type": "job.running", "event_id": "cursor"}
    terminal = {"type": "job.completed", "event_id": "terminal"}
    await hub.publish("tenant-a", cursor)
    await hub.publish("tenant-a", terminal)

    socket = FakeSocket()
    await hub.connect("tenant-a", socket, after_event_id="cursor")
    await hub.replay("tenant-a", socket, after_event_id="cursor")

    assert socket.accepted is True
    assert socket.messages == [terminal]
    await hub.stop()


@pytest.mark.asyncio
async def test_replay_and_live_overlap_delivers_event_once() -> None:
    backplane = RetainedBackplane()
    hub = DistributedRealtimeHub(backplane)
    await hub.start()
    cursor = {"type": "job.running", "event_id": "cursor"}
    terminal = {"type": "job.completed", "event_id": "terminal"}
    await hub.publish("tenant-a", cursor)
    await hub.publish("tenant-a", terminal)
    backplane.emit_during_read = True

    socket = FakeSocket()
    await hub.connect("tenant-a", socket, after_event_id="cursor")
    await hub.replay("tenant-a", socket, after_event_id="cursor")

    assert socket.messages == [terminal]
    await hub.stop()


@pytest.mark.asyncio
async def test_unknown_cursor_fails_closed_without_cross_tenant_replay() -> None:
    backplane = RetainedBackplane()
    hub = DistributedRealtimeHub(backplane)
    await hub.start()
    await hub.publish(
        "tenant-a", {"type": "job.completed", "event_id": "shared"}
    )
    await hub.publish(
        "tenant-b", {"type": "job.completed", "event_id": "shared"}
    )

    socket = FakeSocket()
    await hub.connect("tenant-a", socket, after_event_id="missing")
    await hub.replay("tenant-a", socket, after_event_id="missing")

    assert socket.messages == []
    await hub.stop()
