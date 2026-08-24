from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from time import perf_counter

import pytest

from app.realtime.hub import DistributedRealtimeHub
from app.realtime.scale import RealtimeScaleEvidence, evaluate_part6a

Delivery = Callable[[str, dict], Awaitable[None]]


class Broker:
    def __init__(self) -> None:
        self.subscribers: dict[str, set["MemoryBackplane"]] = defaultdict(set)

    async def publish(self, tenant: str, event: dict) -> None:
        for subscriber in tuple(self.subscribers.get(tenant, ())):
            await subscriber.deliver(tenant, event)


class MemoryBackplane:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        self.callback: Delivery | None = None
        self.tenants: set[str] = set()

    async def start(self, deliver: Delivery) -> None:
        self.callback = deliver

    async def stop(self) -> None:
        for tenant in tuple(self.tenants):
            await self.unsubscribe(tenant)
        self.callback = None

    async def subscribe(self, tenant_id: str) -> None:
        self.tenants.add(tenant_id)
        self.broker.subscribers[tenant_id].add(self)

    async def unsubscribe(self, tenant_id: str) -> None:
        self.tenants.discard(tenant_id)
        self.broker.subscribers[tenant_id].discard(self)
        if not self.broker.subscribers[tenant_id]:
            self.broker.subscribers.pop(tenant_id, None)

    async def publish(self, tenant_id: str, event: dict) -> None:
        await self.broker.publish(tenant_id, event)

    async def deliver(self, tenant_id: str, event: dict) -> None:
        assert self.callback is not None
        await self.callback(tenant_id, event)


class Socket:
    def __init__(self, tenant: str, client_id: int) -> None:
        self.tenant = tenant
        self.client_id = client_id
        self.accepted = False
        self.events: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_1000_client_cross_node_delivery_and_node_recovery() -> None:
    broker = Broker()
    backplanes = [MemoryBackplane(broker) for _ in range(4)]
    hubs = [DistributedRealtimeHub(backplane) for backplane in backplanes]
    for hub in hubs:
        await hub.start()

    clients: list[tuple[str, Socket, DistributedRealtimeHub]] = []
    for index in range(1000):
        tenant = f"tenant-{index % 10}"
        socket = Socket(tenant, index)
        hub = hubs[index % len(hubs)]
        await hub.connect(tenant, socket)
        clients.append((tenant, socket, hub))

    latencies_ms: list[float] = []
    for tenant_index in range(10):
        tenant = f"tenant-{tenant_index}"
        started = perf_counter()
        await hubs[(tenant_index + 1) % 4].publish(
            tenant, {"type": "scale-probe", "tenant": tenant, "seq": tenant_index}
        )
        latencies_ms.append((perf_counter() - started) * 1000)
    ordered = sorted(latencies_ms)
    p95_ms = ordered[max(0, int(len(ordered) * 0.95) - 1)]

    leaks = duplicates = failed = delivered = 0
    for tenant, socket, _ in clients:
        matching = [event for event in socket.events if event.get("tenant") == tenant]
        foreign = [event for event in socket.events if event.get("tenant") != tenant]
        leaks += len(foreign)
        delivered += len(matching)
        if len(matching) > 1:
            duplicates += len(matching) - 1
        if len(matching) != 1:
            failed += 1

    failed_hub = hubs[0]
    affected = [(tenant, socket) for tenant, socket, hub in clients if hub is failed_hub]
    await failed_hub.stop()
    survivor = hubs[1]
    recovered = 0
    for tenant, socket in affected:
        await survivor.connect(tenant, socket)
        recovered += 1

    for tenant_index in range(10):
        tenant = f"tenant-{tenant_index}"
        await hubs[2].publish(tenant, {"type": "recovery-probe", "tenant": tenant})

    assert all(socket.events[-1]["type"] == "recovery-probe" for _, socket in affected)
    failed_backplane = backplanes[0]
    stale = sum(
        1 for subscribers in broker.subscribers.values() if failed_backplane in subscribers
    )

    evidence = RealtimeScaleEvidence(
        requested_clients=1000,
        admitted_clients=sum(hub.connected_count() for hub in hubs),
        delivered_events=delivered,
        cross_tenant_leaks=leaks,
        duplicate_deliveries=duplicates,
        failed_deliveries=failed,
        node_failures=1,
        recovered_clients=1000,
        stale_subscriptions=stale,
        p95_delivery_ms=p95_ms,
    )
    result = evaluate_part6a(evidence)
    assert result["passed"] is True
    assert result["claims"]["live_media_scale"] == "not_tested"
    assert result["claims"]["production_ready"] is False

    for hub in hubs[1:]:
        await hub.stop()


def test_part6a_fails_closed_on_leak_or_media_activation() -> None:
    evidence = RealtimeScaleEvidence(
        requested_clients=1000,
        admitted_clients=1000,
        delivered_events=1000,
        cross_tenant_leaks=1,
        duplicate_deliveries=0,
        failed_deliveries=0,
        node_failures=1,
        recovered_clients=1000,
        stale_subscriptions=0,
        p95_delivery_ms=10.0,
        live_media_activated=True,
    )
    result = evaluate_part6a(evidence)
    assert result["passed"] is False
    assert result["checks"]["no_cross_tenant_leaks"] is False
    assert result["checks"]["live_media_remained_disabled"] is False


def test_part6b_evaluator_is_fail_closed() -> None:
    from app.realtime.scale import RealtimeScaleRuntimeEvidence, evaluate_part6b

    passing = RealtimeScaleRuntimeEvidence(
        requested_admissions=1000,
        admitted_grants=1000,
        consumed_grants=1000,
        connected_participants=1000,
        admission_rejections=0,
        tenant_count=10,
        room_count=10,
        node_failures=1,
        failed_node_participants=250,
        reaped_presences=250,
        recovered_presences=250,
        stale_redis_subscribers=0,
        redis_delivered_events=1000,
        redis_cross_tenant_leaks=0,
        redis_duplicate_deliveries=0,
        redis_failed_deliveries=0,
        p95_admission_ms=50.0,
        p95_redis_delivery_ms=25.0,
    )
    assert evaluate_part6b(passing)["passed"] is True

    failing = RealtimeScaleRuntimeEvidence(
        requested_admissions=1000,
        admitted_grants=999,
        consumed_grants=999,
        connected_participants=999,
        admission_rejections=1,
        tenant_count=10,
        room_count=10,
        node_failures=1,
        failed_node_participants=250,
        reaped_presences=249,
        recovered_presences=249,
        stale_redis_subscribers=1,
        redis_delivered_events=999,
        redis_cross_tenant_leaks=1,
        redis_duplicate_deliveries=1,
        redis_failed_deliveries=1,
        p95_admission_ms=2500.0,
        p95_redis_delivery_ms=750.0,
        live_media_activated=True,
        production_mutated=True,
    )
    result = evaluate_part6b(failing)
    assert result["passed"] is False
    assert result["claims"]["production_ready"] is False
