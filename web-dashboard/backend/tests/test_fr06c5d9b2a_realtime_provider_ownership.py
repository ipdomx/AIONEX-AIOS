"""Isolated PostgreSQL acceptance for FR-06C5D9B2A provider ownership."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.base import Base
from app.db.models import OwnerControlRecord, RealtimeProviderResourceOwnership
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_realtime_resources as registry
from app.services.host_maintenance_admission import HostMaintenanceClosed


def _schema8(*, generation: int = 16, operation_id: str | None = None) -> dict:
    return {
        "schema_version": 8,
        "scope": admission.REALTIME_REQUEST_COVERAGE_SCOPE,
        "generation": generation,
        "operation_id": operation_id or str(uuid4()),
        "reason": "isolated-realtime-provider-ownership",
        "changed_at": datetime.now(UTC).isoformat(),
        "full_host_closure": False,
    }


def _migration(connection) -> None:
    path = Path(__file__).resolve().parents[1] / (
        "alembic/versions/20260920_0064_realtime_provider_resources.py"
    )
    spec = importlib.util.spec_from_file_location("realtime_provider_" + uuid4().hex, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        module.downgrade()


@pytest_asyncio.fixture
async def provider_case():
    url = make_url(os.environ.get("DATABASE_URL", ""))
    assert url.drivername == "postgresql+asyncpg"
    assert re.search(r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)", url.database or "")
    schema = "realtime_provider_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    authority_id = str(uuid4())
    operation_id = str(uuid4())
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Base.metadata.create_all(
                conn, tables=[OwnerControlRecord.__table__, RealtimeProviderResourceOwnership.__table__]
            ))
            await connection.run_sync(_migration)
        payload = _schema8(operation_id=operation_id)
        async with sessions() as session:
            session.add(OwnerControlRecord(
                id=authority_id, domain=admission.DOMAIN, resource_id=admission.RESOURCE_ID,
                status="open", enabled=True, payload=payload, version=payload["generation"],
            ))
            await session.commit()
        yield SimpleNamespace(
            engine=engine, sessions=sessions, authority_id=authority_id,
            operation_id=operation_id, schema=schema,
        )
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def _row(case, owner):
    async with case.sessions() as session:
        return await session.get(RealtimeProviderResourceOwnership, owner.id)


@pytest.mark.asyncio
async def test_reservation_is_invisible_until_commit_and_begin_requires_committed_row(provider_case):
    case = provider_case
    org_id, room_id, incarnation = str(uuid4()), str(uuid4()), str(uuid4())
    async with case.sessions() as producer:
        async with producer.begin():
            owner = await registry.reserve_provider_resource(
                producer, organization_id=org_id, resource_kind="room",
                local_resource_id=room_id, owner_incarnation=incarnation,
            )
            async with case.sessions() as observer:
                count = await observer.scalar(select(func.count(RealtimeProviderResourceOwnership.id)).where(
                    RealtimeProviderResourceOwnership.id == owner.id
                ))
                assert count == 0
    row = await _row(case, owner)
    assert row is not None and row.state == "reserved"
    assert owner.admitted_generation == 16
    assert owner.admitted_operation_id == case.operation_id
    assert await registry.begin_provider_io(owner, session_factory=case.sessions) is True
    row = await _row(case, owner)
    assert row is not None and row.state == "submitted" and row.provider_started_at is not None


@pytest.mark.asyncio
async def test_close_after_reserve_blocks_begin_but_reserved_intent_can_settle_not_started(provider_case):
    case = provider_case
    async with case.sessions() as session:
        async with session.begin():
            owner = await registry.reserve_provider_resource(
                session, organization_id=str(uuid4()), resource_kind="room",
                local_resource_id=str(uuid4()), owner_incarnation=str(uuid4()),
            )
    await admission.close_admission(
        operation_id=str(uuid4()), expected_generation=16,
        reason="isolated close before provider start", session_factory=case.sessions,
    )
    with pytest.raises(HostMaintenanceClosed):
        await registry.begin_provider_io(owner, session_factory=case.sessions)
    row = await _row(case, owner)
    assert row is not None and row.state == "reserved" and row.provider_started_at is None
    await registry.settle_not_started(owner, session_factory=case.sessions)
    row = await _row(case, owner)
    assert row is not None and row.state == "settled" and row.settled_at is not None


@pytest.mark.asyncio
async def test_submitted_ownership_cannot_be_erased_as_not_started_and_keeps_first_uncertainty(provider_case):
    case = provider_case
    async with case.sessions() as session:
        async with session.begin():
            owner = await registry.reserve_provider_resource(
                session, organization_id=str(uuid4()), resource_kind="egress",
                local_resource_id=str(uuid4()), owner_incarnation=str(uuid4()),
            )
    assert await registry.begin_provider_io(owner, session_factory=case.sessions) is True
    with pytest.raises(registry.RealtimeProviderOwnershipLost, match="cannot be settled"):
        await registry.settle_not_started(owner, session_factory=case.sessions)
    await registry.mark_provider_unresolved(
        owner, reason="provider_timeout_unknown", session_factory=case.sessions,
    )
    await registry.mark_provider_unresolved(
        owner, reason="later_observation", session_factory=case.sessions,
    )
    row = await _row(case, owner)
    assert row is not None and row.state == "unresolved"
    assert row.unresolved_reason == "provider_timeout_unknown"


@pytest.mark.asyncio
async def test_active_participant_session_requires_expiry_and_hash(provider_case):
    case = provider_case
    async with case.sessions() as session:
        async with session.begin():
            owner = await registry.reserve_provider_resource(
                session, organization_id=str(uuid4()), resource_kind="participant_session",
                local_resource_id=str(uuid4()), owner_incarnation=str(uuid4()),
            )
    assert await registry.begin_provider_io(owner, session_factory=case.sessions) is True
    with pytest.raises(ValueError, match="requires provider expiry"):
        await registry.observe_provider_active(
            owner, provider_ref_sha256="a" * 64, session_factory=case.sessions,
        )
    expiry = datetime.now(UTC) + timedelta(minutes=5)
    await registry.observe_provider_active(
        owner, provider_ref_sha256="a" * 64, expires_at=expiry,
        session_factory=case.sessions,
    )
    row = await _row(case, owner)
    assert row is not None and row.state == "active"
    assert row.provider_ref_sha256 == "a" * 64
    assert row.expires_at is not None


@pytest.mark.asyncio
async def test_settled_history_is_retained_but_does_not_block_explicit_new_attempt(provider_case):
    case = provider_case
    org_id, room_id = str(uuid4()), str(uuid4())
    async with case.sessions() as session:
        async with session.begin():
            first = await registry.reserve_provider_resource(
                session, organization_id=org_id, resource_kind="room",
                local_resource_id=room_id, owner_incarnation=str(uuid4()),
            )
    await registry.settle_not_started(first, session_factory=case.sessions)
    async with case.sessions() as session:
        async with session.begin():
            second = await registry.reserve_provider_resource(
                session, organization_id=org_id, resource_kind="room",
                local_resource_id=room_id, owner_incarnation=str(uuid4()),
            )
    assert second.id != first.id
    async with case.sessions() as session:
        rows = list((await session.scalars(select(RealtimeProviderResourceOwnership).where(
            RealtimeProviderResourceOwnership.organization_id == org_id,
            RealtimeProviderResourceOwnership.resource_kind == "room",
            RealtimeProviderResourceOwnership.local_resource_id == room_id,
        ).order_by(RealtimeProviderResourceOwnership.started_at))).all())
    assert [row.state for row in rows] == ["settled", "reserved"]


@pytest.mark.asyncio
async def test_submitted_room_cannot_be_settled_from_absence_while_create_may_be_inflight(provider_case):
    case = provider_case
    org_id, room_id = str(uuid4()), str(uuid4())
    async with case.sessions() as session:
        async with session.begin():
            owner = await registry.reserve_provider_resource(
                session, organization_id=org_id, resource_kind="room",
                local_resource_id=room_id, owner_incarnation=str(uuid4()),
            )
    assert await registry.begin_provider_io(owner, session_factory=case.sessions) is True
    with pytest.raises(registry.RealtimeProviderOwnershipLost, match="completed-or-ambiguous"):
        await registry.settle_room_absent(
            owner, provider_ref_sha256="b" * 64, session_factory=case.sessions
        )
    assert await registry.provider_ownership_state(owner, session_factory=case.sessions) == "submitted"


@pytest.mark.asyncio
async def test_active_room_settles_only_with_matching_explicit_provider_absence(provider_case):
    case = provider_case
    org_id, room_id, digest = str(uuid4()), str(uuid4()), "c" * 64
    async with case.sessions() as session:
        async with session.begin():
            owner = await registry.reserve_provider_resource(
                session, organization_id=org_id, resource_kind="room",
                local_resource_id=room_id, owner_incarnation=str(uuid4()),
            )
    assert await registry.begin_provider_io(owner, session_factory=case.sessions) is True
    await registry.observe_provider_active(
        owner, provider_ref_sha256=digest, session_factory=case.sessions
    )
    async with case.sessions() as session:
        found = await registry.find_unfinished_provider_ownership(
            session, organization_id=org_id, resource_kind="room", local_resource_id=room_id
        )
    assert found == owner
    with pytest.raises(registry.RealtimeProviderOwnershipUncertain, match="identity differs"):
        await registry.settle_room_absent(
            owner, provider_ref_sha256="d" * 64, session_factory=case.sessions
        )
    await registry.settle_room_absent(
        owner, provider_ref_sha256=digest, session_factory=case.sessions
    )
    assert await registry.provider_ownership_state(owner, session_factory=case.sessions) == "settled"
    async with case.sessions() as session:
        assert await registry.find_unfinished_provider_ownership(
            session, organization_id=org_id, resource_kind="room", local_resource_id=room_id
        ) is None


@pytest.mark.asyncio
async def test_participant_session_uncertainty_requires_conservative_expiry(provider_case):
    case = provider_case
    async with case.sessions() as session:
        async with session.begin():
            owner = await registry.reserve_provider_resource(
                session, organization_id=str(uuid4()), resource_kind="participant_session",
                local_resource_id=str(uuid4()), owner_incarnation=str(uuid4()),
            )
    assert await registry.begin_provider_io(owner, session_factory=case.sessions) is True
    with pytest.raises(
        registry.RealtimeProviderOwnershipUncertain, match="requires a conservative expiry"
    ):
        await registry.mark_provider_unresolved(
            owner, reason="credential_mint_uncertain", session_factory=case.sessions
        )
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    await registry.mark_provider_unresolved(
        owner, reason="credential_mint_uncertain", expires_at=expiry,
        session_factory=case.sessions,
    )
    row = await _row(case, owner)
    assert row is not None and row.state == "unresolved"
    assert row.expires_at == expiry
    assert await registry.settle_participant_session_expired(
        owner, session_factory=case.sessions
    ) is False


@pytest.mark.asyncio
async def test_participant_session_settles_only_after_whole_bundle_expiry(
    provider_case, monkeypatch: pytest.MonkeyPatch
):
    case = provider_case
    async with case.sessions() as session:
        async with session.begin():
            owner = await registry.reserve_provider_resource(
                session, organization_id=str(uuid4()), resource_kind="participant_session",
                local_resource_id=str(uuid4()), owner_incarnation=str(uuid4()),
            )
    assert await registry.begin_provider_io(owner, session_factory=case.sessions) is True
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    await registry.observe_provider_active(
        owner, provider_ref_sha256="e" * 64, expires_at=expiry,
        session_factory=case.sessions,
    )
    assert await registry.settle_participant_session_expired(
        owner, session_factory=case.sessions
    ) is False

    async def after_expiry(_session):
        return expiry + timedelta(seconds=1)

    monkeypatch.setattr(registry, "_now", after_expiry)
    assert await registry.settle_participant_session_expired(
        owner, session_factory=case.sessions
    ) is True
    row = await _row(case, owner)
    assert row is not None and row.state == "settled"
    assert row.settled_at == expiry + timedelta(seconds=1)
