from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.base import Base, SessionLocal
from app.db.models import (
    Organization,
    RealtimeAdmissionGrant,
    RealtimeParticipant,
    RealtimeRoom,
    RealtimeTenantQuota,
    User,
)
from app.realtime.admission import RealtimeAdmissionAuthority, RealtimeAdmissionRejected

TEST_SECRET = "phase36h-admission-test-secret-12345678901234567890"
ROOT = Path(__file__).resolve().parents[3]
PRESENCE_MIGRATION = ROOT / "web-dashboard/backend/alembic/versions/20260824_0041_realtime_presence_leases.py"


async def _seed_tenant(suffix: str, *, users: int = 3) -> tuple[str, list[str]]:
    organization_id = f"p36h-org-{suffix}"
    user_ids = [f"p36h-user-{index}-{suffix}" for index in range(users)]
    async with SessionLocal() as session:
        session.add(
            Organization(
                id=organization_id,
                name=f"Phase 36H {suffix}",
                slug=f"p36h-{suffix}",
                plan="enterprise",
                status="active",
            )
        )
        await session.flush()
        session.add_all(
            [
                User(
                    id=user_id,
                    organization_id=organization_id,
                    email=f"{user_id}@example.com",
                    name=f"Realtime User {index}",
                    password_hash="unused",
                    status="active",
                )
                for index, user_id in enumerate(user_ids)
            ]
        )
        await session.commit()
    return organization_id, user_ids


async def _cleanup_tenant(organization_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(RealtimeAdmissionGrant).where(
                RealtimeAdmissionGrant.organization_id == organization_id
            )
        )
        await session.execute(
            delete(RealtimeParticipant).where(
                RealtimeParticipant.organization_id == organization_id
            )
        )
        await session.execute(
            delete(RealtimeRoom).where(RealtimeRoom.organization_id == organization_id)
        )
        await session.execute(
            delete(RealtimeTenantQuota).where(
                RealtimeTenantQuota.organization_id == organization_id
            )
        )
        await session.execute(delete(User).where(User.organization_id == organization_id))
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()


def test_presence_migration_0041_is_linear_reversible_and_provider_dormant() -> None:
    source = PRESENCE_MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "20260824_0041"' in source
    assert 'down_revision: str | None = "20260824_0040"' in source
    assert '"presence_fencing_token"' in source
    assert '"presence_lease_expires_at"' in source
    assert "def downgrade() -> None:" in source
    assert "LiveKit" not in source
    assert "TURN" not in source
    assert "https://" not in source


def test_presence_schema_is_durable_hash_only_and_fenced() -> None:
    participants = Base.metadata.tables["realtime_participants"]
    grants = Base.metadata.tables["realtime_admission_grants"]
    assert {"presence_fencing_token", "presence_lease_expires_at"} <= set(
        participants.c.keys()
    )
    assert {
        "token",
        "grant_token",
        "provider_token",
        "credential",
        "secret",
        "raw_token",
    }.isdisjoint(set(grants.c.keys()))
    assert "grant_digest_sha256" in grants.c


@pytest.mark.asyncio
async def test_room_and_grant_idempotency_backpressure_and_single_use() -> None:
    suffix = uuid4().hex[:8]
    organization_id, users = await _seed_tenant(suffix)
    authority = RealtimeAdmissionAuthority(secret_key=TEST_SECRET)
    try:
        async with SessionLocal() as session:
            quota = await authority.provision_default_quota(
                session, organization_id=organization_id
            )
            quota.max_concurrent_rooms = 1
            quota.max_participants_per_room = 2
            quota.max_concurrent_participants = 2
            quota.max_publishers_per_room = 1
            quota.max_screen_shares_per_room = 1
            quota.max_admissions_per_window = 10
            quota.grant_ttl_seconds = 30
            await session.commit()

        async with SessionLocal() as session:
            room = await authority.create_room(
                session,
                organization_id=organization_id,
                created_by_id=users[0],
                room_key="primary-room",
                idempotency_key="room-create-1",
                max_participants=2,
            )
            replay = await authority.create_room(
                session,
                organization_id=organization_id,
                created_by_id=users[0],
                room_key="ignored-on-replay",
                idempotency_key="room-create-1",
                max_participants=2,
            )
            assert replay.id == room.id
            with pytest.raises(RealtimeAdmissionRejected) as blocked_room:
                await authority.create_room(
                    session,
                    organization_id=organization_id,
                    created_by_id=users[0],
                    room_key="second-room",
                    idempotency_key="room-create-2",
                    max_participants=2,
                )
            assert blocked_room.value.code == "tenant_room_backpressure"
            await session.commit()
            room_id = room.id

        async with SessionLocal() as session:
            first = await authority.issue_grant(
                session,
                organization_id=organization_id,
                room_id=room_id,
                user_id=users[0],
                issued_by_id=users[0],
                participant_key="participant-1",
                idempotency_key="grant-1",
                can_publish=True,
                can_screen_share=True,
            )
            replay = await authority.issue_grant(
                session,
                organization_id=organization_id,
                room_id=room_id,
                user_id=users[0],
                issued_by_id=users[0],
                participant_key="participant-1",
                idempotency_key="grant-1",
                can_publish=True,
                can_screen_share=True,
            )
            assert replay.idempotent_replay is True
            assert replay.token == first.token
            assert replay.grant.id == first.grant.id
            assert first.token not in first.grant.grant_digest_sha256

            with pytest.raises(RealtimeAdmissionRejected) as publisher_block:
                await authority.issue_grant(
                    session,
                    organization_id=organization_id,
                    room_id=room_id,
                    user_id=users[1],
                    issued_by_id=users[0],
                    participant_key="participant-2-publisher",
                    idempotency_key="grant-2-publisher",
                    can_publish=True,
                )
            assert publisher_block.value.code == "room_publisher_backpressure"

            second = await authority.issue_grant(
                session,
                organization_id=organization_id,
                room_id=room_id,
                user_id=users[1],
                issued_by_id=users[0],
                participant_key="participant-2",
                idempotency_key="grant-2",
                can_publish=False,
                can_screen_share=False,
            )
            with pytest.raises(RealtimeAdmissionRejected) as participant_block:
                await authority.issue_grant(
                    session,
                    organization_id=organization_id,
                    room_id=room_id,
                    user_id=users[2],
                    issued_by_id=users[0],
                    participant_key="participant-3",
                    idempotency_key="grant-3",
                    can_publish=False,
                )
            assert participant_block.value.code in {
                "tenant_participant_backpressure",
                "room_participant_backpressure",
            }
            await session.commit()
            first_token = first.token
            second_token = second.token

        async with SessionLocal() as session:
            consumed = await authority.consume_grant(
                session,
                organization_id=organization_id,
                token=first_token,
                node_id="node-a",
            )
            assert consumed.status == "consumed"
            await session.commit()

        async with SessionLocal() as session:
            with pytest.raises(RealtimeAdmissionRejected) as reused:
                await authority.consume_grant(
                    session,
                    organization_id=organization_id,
                    token=first_token,
                    node_id="node-a",
                )
            assert reused.value.code == "grant_consumed"
            second_grant = await authority.consume_grant(
                session,
                organization_id=organization_id,
                token=second_token,
                node_id="node-b",
            )
            assert second_grant.status == "consumed"
            await session.commit()

        async with SessionLocal() as session:
            assert (
                await session.scalar(
                    select(func.count(RealtimeAdmissionGrant.id)).where(
                        RealtimeAdmissionGrant.organization_id == organization_id
                    )
                )
                == 2
            )
    finally:
        await _cleanup_tenant(organization_id)


@pytest.mark.asyncio
async def test_rate_limit_and_cross_node_concurrency_are_serialized_per_tenant() -> None:
    suffix = uuid4().hex[:8]
    organization_id, users = await _seed_tenant(suffix)
    authority = RealtimeAdmissionAuthority(secret_key=TEST_SECRET)
    try:
        async with SessionLocal() as session:
            quota = await authority.provision_default_quota(
                session, organization_id=organization_id
            )
            quota.max_concurrent_rooms = 1
            quota.max_participants_per_room = 1
            quota.max_concurrent_participants = 1
            quota.max_publishers_per_room = 1
            quota.max_admissions_per_window = 10
            await session.commit()
        async with SessionLocal() as session:
            room = await authority.create_room(
                session,
                organization_id=organization_id,
                created_by_id=users[0],
                room_key="concurrent-room",
                idempotency_key="concurrent-room-create",
                max_participants=1,
            )
            await session.commit()
            room_id = room.id

        async def admit(index: int) -> str:
            async with SessionLocal() as session:
                try:
                    await authority.issue_grant(
                        session,
                        organization_id=organization_id,
                        room_id=room_id,
                        user_id=users[index],
                        issued_by_id=users[0],
                        participant_key=f"parallel-{index}",
                        idempotency_key=f"parallel-grant-{index}",
                        can_publish=False,
                    )
                    await session.commit()
                    return "accepted"
                except RealtimeAdmissionRejected as exc:
                    await session.rollback()
                    return exc.code

        results = await asyncio.gather(admit(0), admit(1))
        assert results.count("accepted") == 1
        assert sum(item.endswith("participant_backpressure") for item in results) == 1

        async with SessionLocal() as session:
            quota = await session.scalar(
                select(RealtimeTenantQuota)
                .where(RealtimeTenantQuota.organization_id == organization_id)
                .with_for_update()
            )
            assert quota is not None
            quota.max_concurrent_participants = 2
            quota.max_participants_per_room = 2
            quota.max_admissions_per_window = 1
            await session.commit()

        accepted_index = results.index("accepted")
        rejected_index = 1 - accepted_index
        async with SessionLocal() as session:
            participant = await session.scalar(
                select(RealtimeParticipant).where(
                    RealtimeParticipant.organization_id == organization_id,
                    RealtimeParticipant.user_id == users[accepted_index],
                )
            )
            assert participant is not None
            participant.status = "left"
            await session.commit()

        async with SessionLocal() as session:
            with pytest.raises(RealtimeAdmissionRejected) as rate_block:
                await authority.issue_grant(
                    session,
                    organization_id=organization_id,
                    room_id=room_id,
                    user_id=users[rejected_index],
                    issued_by_id=users[0],
                    participant_key="rate-limited-user",
                    idempotency_key="rate-limited-grant",
                    can_publish=False,
                )
            assert rate_block.value.code == "tenant_admission_backpressure"
    finally:
        await _cleanup_tenant(organization_id)


@pytest.mark.asyncio
async def test_presence_heartbeat_takeover_and_stale_fencing() -> None:
    suffix = uuid4().hex[:8]
    organization_id, users = await _seed_tenant(suffix, users=1)
    authority = RealtimeAdmissionAuthority(secret_key=TEST_SECRET)
    try:
        async with SessionLocal() as session:
            await authority.provision_default_quota(session, organization_id=organization_id)
            room = await authority.create_room(
                session,
                organization_id=organization_id,
                created_by_id=users[0],
                room_key="presence-room",
                idempotency_key="presence-room-create",
                max_participants=1,
            )
            grant = await authority.issue_grant(
                session,
                organization_id=organization_id,
                room_id=room.id,
                user_id=users[0],
                issued_by_id=users[0],
                participant_key="presence-user",
                idempotency_key="presence-grant",
                can_publish=False,
            )
            await authority.consume_grant(
                session,
                organization_id=organization_id,
                token=grant.token,
                node_id="node-a",
            )
            await session.commit()
            participant_id = grant.participant.id
            room_id = room.id

        async with SessionLocal() as session:
            first = await authority.claim_presence(
                session,
                organization_id=organization_id,
                participant_id=participant_id,
                node_id="node-a",
                lease_seconds=5,
            )
            first_fence = first.fencing_token
            same_node = await authority.claim_presence(
                session,
                organization_id=organization_id,
                participant_id=participant_id,
                node_id="node-a",
                lease_seconds=5,
            )
            assert same_node.fencing_token == first_fence
            with pytest.raises(RealtimeAdmissionRejected) as held:
                await authority.claim_presence(
                    session,
                    organization_id=organization_id,
                    participant_id=participant_id,
                    node_id="node-b",
                    lease_seconds=5,
                )
            assert held.value.code == "presence_lease_held"
            await session.commit()

        async with SessionLocal() as session:
            participant = await session.get(RealtimeParticipant, participant_id)
            assert participant is not None
            participant.presence_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        async with SessionLocal() as session:
            takeover = await authority.claim_presence(
                session,
                organization_id=organization_id,
                participant_id=participant_id,
                node_id="node-b",
                lease_seconds=5,
            )
            assert takeover.takeover is True
            assert takeover.fencing_token > first_fence
            new_fence = takeover.fencing_token
            with pytest.raises(RealtimeAdmissionRejected) as stale:
                await authority.heartbeat_presence(
                    session,
                    organization_id=organization_id,
                    participant_id=participant_id,
                    node_id="node-a",
                    fencing_token=first_fence,
                    lease_seconds=5,
                )
            assert stale.value.code == "stale_presence_fence"
            renewed = await authority.heartbeat_presence(
                session,
                organization_id=organization_id,
                participant_id=participant_id,
                node_id="node-b",
                fencing_token=new_fence,
                lease_seconds=5,
            )
            assert renewed.fencing_token == new_fence
            room_fence_1 = await authority.advance_room_fence(
                session, organization_id=organization_id, room_id=room_id
            )
            room_fence_2 = await authority.advance_room_fence(
                session, organization_id=organization_id, room_id=room_id
            )
            assert room_fence_2 == room_fence_1 + 1
            await session.commit()

        async with SessionLocal() as session:
            participant = await session.get(RealtimeParticipant, participant_id)
            assert participant is not None
            participant.presence_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        async with SessionLocal() as session:
            reaped = await authority.reap_stale_presence(
                session, organization_id=organization_id
            )
            assert reaped == 1
            participant = await session.get(RealtimeParticipant, participant_id)
            assert participant is not None
            assert participant.node_id is None
            assert participant.connection_count == 0
            assert participant.status == "admitted"
            assert participant.presence_fencing_token > new_fence
            await session.commit()
    finally:
        await _cleanup_tenant(organization_id)
