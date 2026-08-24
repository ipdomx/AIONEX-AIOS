from __future__ import annotations

from typing import Any

import pytest

from app.realtime.backplane import DEFAULT_MAX_EVENT_BYTES, encode_event, tenant_channel
from app.realtime.hub import DistributedRealtimeHub


class FakeSocket:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.accepted = False
        self.fail_send = fail_send
        self.messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict[str, Any]) -> None:
        if self.fail_send:
            raise RuntimeError("socket closed")
        self.messages.append(event)


class MemoryBackplaneNetwork:
    def __init__(self) -> None:
        self.nodes: list[MemoryBackplane] = []

    def node(self) -> "MemoryBackplane":
        item = MemoryBackplane(self)
        self.nodes.append(item)
        return item

    async def publish(self, tenant_id: str, event: dict[str, Any]) -> None:
        for node in tuple(self.nodes):
            if tenant_id in node.subscriptions and node.deliver is not None:
                await node.deliver(tenant_id, dict(event))


class MemoryBackplane:
    def __init__(self, network: MemoryBackplaneNetwork) -> None:
        self.network = network
        self.deliver = None
        self.subscriptions: set[str] = set()
        self.subscribe_calls: list[str] = []
        self.unsubscribe_calls: list[str] = []
        self.started = False

    async def start(self, deliver) -> None:
        self.deliver = deliver
        self.started = True

    async def stop(self) -> None:
        self.deliver = None
        self.subscriptions.clear()
        self.started = False

    async def subscribe(self, tenant_id: str) -> None:
        if not self.started:
            raise RuntimeError("not started")
        self.subscribe_calls.append(tenant_id)
        self.subscriptions.add(tenant_id)

    async def unsubscribe(self, tenant_id: str) -> None:
        self.unsubscribe_calls.append(tenant_id)
        self.subscriptions.discard(tenant_id)

    async def publish(self, tenant_id: str, event: dict[str, Any]) -> None:
        if not self.started:
            raise RuntimeError("not started")
        await self.network.publish(tenant_id, event)


def test_tenant_channel_is_stable_and_does_not_expose_raw_tenant_id() -> None:
    tenant_id = "organization-sensitive-123"
    first = tenant_channel(tenant_id)
    second = tenant_channel(tenant_id)

    assert first == second
    assert tenant_id not in first
    assert first.startswith("aios:realtime:v1:")
    assert len(first.rsplit(":", 1)[-1]) == 64


def test_event_encoding_rejects_non_object_and_oversized_payloads() -> None:
    with pytest.raises(TypeError, match="JSON object"):
        encode_event(["not", "an", "object"])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="exceeds"):
        encode_event({"payload": "x" * DEFAULT_MAX_EVENT_BYTES})


@pytest.mark.asyncio
async def test_two_api_nodes_receive_same_tenant_event_without_cross_tenant_leak() -> None:
    network = MemoryBackplaneNetwork()
    hub_a = DistributedRealtimeHub(network.node())
    hub_b = DistributedRealtimeHub(network.node())
    hub_other = DistributedRealtimeHub(network.node())
    await hub_a.start()
    await hub_b.start()
    await hub_other.start()

    socket_a = FakeSocket()
    socket_b = FakeSocket()
    socket_other = FakeSocket()
    await hub_a.connect("tenant-a", socket_a)
    await hub_b.connect("tenant-a", socket_b)
    await hub_other.connect("tenant-b", socket_other)

    event = {"type": "project.updated", "project_id": "p-1"}
    await hub_a.publish("tenant-a", event)

    assert socket_a.accepted and socket_b.accepted and socket_other.accepted
    assert socket_a.messages == [event]
    assert socket_b.messages == [event]
    assert socket_other.messages == []

    await hub_a.stop()
    await hub_b.stop()
    await hub_other.stop()


@pytest.mark.asyncio
async def test_first_client_subscribes_once_and_last_client_unsubscribes_once() -> None:
    network = MemoryBackplaneNetwork()
    backplane = network.node()
    hub = DistributedRealtimeHub(backplane)
    await hub.start()

    first = FakeSocket()
    second = FakeSocket()
    await hub.connect("tenant-a", first)
    await hub.connect("tenant-a", second)

    assert backplane.subscribe_calls == ["tenant-a"]
    assert hub.connected_count("tenant-a") == 2

    await hub.disconnect("tenant-a", first)
    assert backplane.unsubscribe_calls == []
    assert hub.connected_count("tenant-a") == 1

    await hub.disconnect("tenant-a", second)
    assert backplane.unsubscribe_calls == ["tenant-a"]
    assert hub.connected_count("tenant-a") == 0
    await hub.stop()


@pytest.mark.asyncio
async def test_stale_last_socket_is_removed_and_tenant_subscription_is_released() -> None:
    network = MemoryBackplaneNetwork()
    backplane = network.node()
    hub = DistributedRealtimeHub(backplane)
    await hub.start()

    stale = FakeSocket(fail_send=True)
    await hub.connect("tenant-a", stale)
    await hub.publish("tenant-a", {"type": "notice"})

    assert hub.connected_count("tenant-a") == 0
    assert backplane.unsubscribe_calls == ["tenant-a"]
    await hub.stop()
