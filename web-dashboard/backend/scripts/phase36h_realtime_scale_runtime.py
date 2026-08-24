#!/usr/bin/env python3
"""Isolated Phase 36H.6B PostgreSQL/Redis admission/backplane acceptance."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import quantiles
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete, func, select, update

from app.db.base import SessionLocal
from app.db.models import (
    Organization,
    RealtimeAdmissionGrant,
    RealtimeParticipant,
    RealtimeRoom,
    RealtimeTenantQuota,
    User,
)
from app.db.redis import close_redis, get_redis, init_redis
from app.realtime.admission import RealtimeAdmissionAuthority, RealtimeAdmissionRejected
from app.realtime.backplane import RedisRealtimeBackplane, tenant_channel
from app.realtime.hub import DistributedRealtimeHub
from app.realtime.scale import RealtimeScaleRuntimeEvidence, evaluate_part6b

TEST_SECRET = "phase36h-6b-isolated-runtime-secret-12345678901234567890"


class ProbeSocket:
    def __init__(self, tenant: str, client_id: int) -> None:
        self.tenant = tenant
        self.client_id = client_id
        self.accepted = False
        self.events: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict) -> None:
        self.events.append(dict(event))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) < 20:
        ordered = sorted(values)
        return ordered[max(0, int(len(ordered) * 0.95) - 1)]
    return quantiles(values, n=100, method="inclusive")[94]


async def _wait_for(predicate, *, timeout_seconds: float = 5.0) -> None:
    deadline = perf_counter() + timeout_seconds
    while perf_counter() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise RuntimeError("realtime delivery did not converge before timeout")


async def _cleanup(org_ids: list[str]) -> None:
    if not org_ids:
        return
    async with SessionLocal() as session:
        await session.execute(delete(RealtimeAdmissionGrant).where(RealtimeAdmissionGrant.organization_id.in_(org_ids)))
        await session.execute(delete(RealtimeParticipant).where(RealtimeParticipant.organization_id.in_(org_ids)))
        await session.execute(delete(RealtimeRoom).where(RealtimeRoom.organization_id.in_(org_ids)))
        await session.execute(delete(RealtimeTenantQuota).where(RealtimeTenantQuota.organization_id.in_(org_ids)))
        await session.execute(delete(User).where(User.organization_id.in_(org_ids)))
        await session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
        await session.commit()


async def _seed(*, tenants: int, clients: int, suffix: str) -> tuple[list[str], dict[str, list[str]]]:
    org_ids = [f"p36h6b-org-{suffix}-{index}" for index in range(tenants)]
    per_tenant = clients // tenants
    users: dict[str, list[str]] = {}
    async with SessionLocal() as session:
        for tenant_index, org_id in enumerate(org_ids):
            session.add(Organization(id=org_id, name=f"Phase 36H 6B {tenant_index}", slug=org_id, plan="enterprise", status="active"))
            await session.flush()
            user_ids = [f"p36h6b-user-{suffix}-{tenant_index}-{index}" for index in range(per_tenant)]
            users[org_id] = user_ids
            session.add_all([
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=f"{user_id}@example.com",
                    name=f"Realtime Load User {index}",
                    password_hash="unused",
                    status="active",
                )
                for index, user_id in enumerate(user_ids)
            ])
        await session.commit()
    return org_ids, users


async def run_acceptance(*, clients: int, tenants: int, hubs_count: int) -> dict[str, object]:
    if clients < 1000 or tenants < 10 or hubs_count < 3 or clients % tenants:
        raise ValueError("36H.6B requires >=1000 clients, >=10 tenants, >=3 hubs and even tenant distribution")

    suffix = uuid4().hex[:8]
    authority = RealtimeAdmissionAuthority(secret_key=TEST_SECRET)
    org_ids: list[str] = []
    admission_latencies: list[float] = []
    rejected = 0
    failed_presence: list[tuple[str, str, int]] = []
    rooms: dict[str, str] = {}

    try:
        org_ids, users = await _seed(tenants=tenants, clients=clients, suffix=suffix)
        per_tenant = clients // tenants

        async def prepare_tenant(org_id: str) -> None:
            async with SessionLocal() as session:
                quota = await authority.provision_default_quota(session, organization_id=org_id)
                quota.max_concurrent_rooms = 1
                quota.max_participants_per_room = per_tenant
                quota.max_concurrent_participants = per_tenant
                quota.max_publishers_per_room = 0
                quota.max_screen_shares_per_room = 0
                quota.max_admissions_per_window = max(1000, per_tenant)
                quota.admission_window_seconds = 3600
                quota.grant_ttl_seconds = 300
                room = await authority.create_room(
                    session,
                    organization_id=org_id,
                    created_by_id=users[org_id][0],
                    room_key="scale-room",
                    idempotency_key="scale-room",
                    max_participants=per_tenant,
                    allow_screen_share=False,
                )
                rooms[org_id] = room.id
                await session.commit()

        await asyncio.gather(*(prepare_tenant(org_id) for org_id in org_ids))

        async def admit_tenant(org_id: str) -> None:
            nonlocal rejected
            async with SessionLocal() as session:
                for index, user_id in enumerate(users[org_id]):
                    started = perf_counter()
                    try:
                        result = await authority.issue_grant(
                            session,
                            organization_id=org_id,
                            room_id=rooms[org_id],
                            user_id=user_id,
                            issued_by_id=users[org_id][0],
                            participant_key=f"participant-{index}",
                            idempotency_key=f"grant-{index}",
                            can_publish=False,
                            can_screen_share=False,
                        )
                        node_id = f"node-{index % hubs_count}"
                        await authority.consume_grant(
                            session,
                            organization_id=org_id,
                            token=result.token,
                            node_id=node_id,
                        )
                        lease = await authority.claim_presence(
                            session,
                            organization_id=org_id,
                            participant_id=result.participant.id,
                            node_id=node_id,
                            lease_seconds=60,
                        )
                        if node_id == "node-0":
                            failed_presence.append((org_id, result.participant.id, lease.fencing_token))
                        admission_latencies.append((perf_counter() - started) * 1000.0)
                    except RealtimeAdmissionRejected:
                        rejected += 1
                        raise
                await session.commit()

        await asyncio.gather(*(admit_tenant(org_id) for org_id in org_ids))

        async with SessionLocal() as session:
            grants = int(await session.scalar(select(func.count(RealtimeAdmissionGrant.id)).where(RealtimeAdmissionGrant.organization_id.in_(org_ids))) or 0)
            consumed = int(await session.scalar(select(func.count(RealtimeAdmissionGrant.id)).where(RealtimeAdmissionGrant.organization_id.in_(org_ids), RealtimeAdmissionGrant.status == "consumed")) or 0)
            connected = int(await session.scalar(select(func.count(RealtimeParticipant.id)).where(RealtimeParticipant.organization_id.in_(org_ids), RealtimeParticipant.status == "connected")) or 0)
            room_count = int(await session.scalar(select(func.count(RealtimeRoom.id)).where(RealtimeRoom.organization_id.in_(org_ids))) or 0)
            await session.execute(
                update(RealtimeParticipant)
                .where(RealtimeParticipant.organization_id.in_(org_ids), RealtimeParticipant.node_id == "node-0")
                .values(presence_lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()

        reaped = 0
        for org_id in org_ids:
            async with SessionLocal() as session:
                reaped += await authority.reap_stale_presence(session, organization_id=org_id, limit=1000)
                await session.commit()

        recovered = 0
        for org_id, participant_id, old_fence in failed_presence:
            async with SessionLocal() as session:
                lease = await authority.claim_presence(
                    session,
                    organization_id=org_id,
                    participant_id=participant_id,
                    node_id="node-recovery",
                    lease_seconds=60,
                )
                if lease.fencing_token <= old_fence:
                    raise RuntimeError("presence fencing token did not advance after node loss")
                recovered += 1
                await session.commit()

        await init_redis()
        backplanes = [RedisRealtimeBackplane() for _ in range(hubs_count)]
        hubs = [DistributedRealtimeHub(backplane) for backplane in backplanes]
        for hub in hubs:
            await hub.start()

        sockets: list[tuple[str, ProbeSocket, DistributedRealtimeHub]] = []
        for index in range(clients):
            tenant = org_ids[index % tenants]
            socket = ProbeSocket(tenant, index)
            hub = hubs[index % hubs_count]
            await hub.connect(tenant, socket)
            sockets.append((tenant, socket, hub))
        await asyncio.sleep(0.1)

        redis_latencies: list[float] = []
        for tenant_index, tenant in enumerate(org_ids):
            tenant_sockets = [socket for item_tenant, socket, _ in sockets if item_tenant == tenant]
            started = perf_counter()
            await hubs[(tenant_index + 1) % hubs_count].publish(
                tenant, {"type": "runtime-scale-probe", "tenant": tenant, "seq": tenant_index}
            )
            await _wait_for(lambda tenant_sockets=tenant_sockets: all(len(item.events) >= 1 for item in tenant_sockets))
            redis_latencies.append((perf_counter() - started) * 1000.0)

        leaks = duplicates = failed = delivered = 0
        for tenant, socket, _ in sockets:
            matching = [event for event in socket.events if event.get("tenant") == tenant]
            foreign = [event for event in socket.events if event.get("tenant") != tenant]
            delivered += len(matching)
            leaks += len(foreign)
            if len(matching) > 1:
                duplicates += len(matching) - 1
            if len(matching) != 1:
                failed += 1

        failed_hub = hubs[0]
        affected_sockets = [(tenant, socket) for tenant, socket, hub in sockets if hub is failed_hub]
        await failed_hub.stop()
        survivor = hubs[1]
        for tenant, socket in affected_sockets:
            await survivor.connect(tenant, socket)
        await asyncio.sleep(0.1)

        for tenant_index, tenant in enumerate(org_ids):
            await hubs[2].publish(tenant, {"type": "runtime-recovery-probe", "tenant": tenant, "seq": tenant_index})
        await _wait_for(lambda: all(socket.events and socket.events[-1].get("type") == "runtime-recovery-probe" for _, socket in affected_sockets))

        redis = await get_redis()
        channels = [tenant_channel(org_id) for org_id in org_ids]
        raw_numsub = await redis.execute_command("PUBSUB", "NUMSUB", *channels)
        counts = {str(raw_numsub[index]): int(raw_numsub[index + 1]) for index in range(0, len(raw_numsub), 2)}
        stale_redis = sum(max(0, count - (hubs_count - 1)) for count in counts.values())

        for hub in hubs[1:]:
            await hub.stop()
        await close_redis()

        evidence = RealtimeScaleRuntimeEvidence(
            requested_admissions=clients,
            admitted_grants=grants,
            consumed_grants=consumed,
            connected_participants=connected,
            admission_rejections=rejected,
            tenant_count=tenants,
            room_count=room_count,
            node_failures=1,
            failed_node_participants=len(failed_presence),
            reaped_presences=reaped,
            recovered_presences=recovered,
            stale_redis_subscribers=stale_redis,
            redis_delivered_events=delivered,
            redis_cross_tenant_leaks=leaks,
            redis_duplicate_deliveries=duplicates,
            redis_failed_deliveries=failed,
            p95_admission_ms=_p95(admission_latencies),
            p95_redis_delivery_ms=_p95(redis_latencies),
        )
        return evaluate_part6b(evidence)
    finally:
        try:
            await close_redis()
        finally:
            await _cleanup(org_ids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=1000)
    parser.add_argument("--tenants", type=int, default=10)
    parser.add_argument("--hubs", type=int, default=4)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = asyncio.run(run_acceptance(clients=args.clients, tenants=args.tenants, hubs_count=args.hubs))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if bool(result["passed"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
