"""Real PostgreSQL contracts for durable notification dispatch ownership.

Every case owns a UUID schema on the root harness's disposable database. These
tests invoke the real admission, registry, attempt and migration code, without
sending notifications or calling providers.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    JSON, Column, DateTime, ForeignKey, Index, Integer, MetaData, String, Table,
    UniqueConstraint, event, select, text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.base import Base
from app.db.models import (
    AuditEvent, HostMaintenanceWorkCycle, Notification, NotificationDelivery,
    NotificationDeliveryAttempt, Organization, OwnerControlRecord, Role, User,
)
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_cycles as backup_cycles
from app.services import host_maintenance_notifications as notifications


WAIT = 8
DELIVERIES = NotificationDelivery.__table__
ATTEMPTS = NotificationDeliveryAttempt.__table__
REGISTRY = HostMaintenanceWorkCycle.__table__
CONTROLS = OwnerControlRecord.__table__


def _disposable_url():
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        pytest.fail("Notification PostgreSQL acceptance requires a disposable DATABASE_URL")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("Notification acceptance requires the isolated asyncpg harness")
    if re.search(
        r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)",
        (url.database or "").lower(),
    ) is None:
        pytest.fail("Notification acceptance refuses a database without a delimited test marker")
    return url


def _run_migration(connection, revision, direction):
    directory = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    paths = list(directory.glob(f"*_{revision}_*.py"))
    assert len(paths) == 1
    spec = importlib.util.spec_from_file_location(
        "notification_migration_" + uuid4().hex, paths[0],
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, direction)()


def _delivery_tables():
    tables = {DELIVERIES, CONTROLS, AuditEvent.__table__}
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return list(tables)
        tables = expanded


def _legacy_attempt_table():
    # Build the actual pre-0050 shape. Current model metadata must not add the
    # new evidence columns before the migration being tested gets to run.
    table = Table(
        "notification_delivery_attempts", MetaData(),
        Column("id", String(36), primary_key=True),
        Column("delivery_id", String(36), ForeignKey(DELIVERIES.c.id, ondelete="CASCADE"), nullable=False),
        Column("attempt_number", Integer, nullable=False),
        Column("status", String(32), nullable=False),
        Column("provider_message_id", String(255)),
        Column("error_code", String(120)),
        Column("response_metadata", JSON, nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("completed_at", DateTime(timezone=True)),
        UniqueConstraint("delivery_id", "attempt_number", name="uq_notification_delivery_attempt"),
    )
    Index("ix_notification_delivery_attempts_delivery_id", table.c.delivery_id)
    Index("ix_notification_delivery_attempts_delivery", table.c.delivery_id, table.c.started_at)
    return table


class _LockProbeSession(AsyncSession):
    async def _before(self, statement):
        lock = getattr(statement, "_for_update_arg", None)
        probe = self.info.get("notification_lock_probe")
        if lock is None or probe is None or self.info.get("notification_probe_seen"):
            return None
        self.info["notification_probe_seen"] = True
        pid = int(await AsyncSession.scalar(self, text("SELECT pg_backend_pid()")))
        observed = (pid, bool(lock.read))
        probe.started.put_nowait(observed)
        return observed

    async def _after(self, observed):
        if observed is not None:
            probe = self.info["notification_lock_probe"]
            probe.acquired.set()
            if probe.pause:
                await probe.release.wait()

    async def execute(self, statement, *args, **kwargs):
        observed = await self._before(statement)
        result = await super().execute(statement, *args, **kwargs)
        await self._after(observed)
        return result

    async def scalar(self, statement, *args, **kwargs):
        observed = await self._before(statement)
        result = await super().scalar(statement, *args, **kwargs)
        await self._after(observed)
        return result


@pytest_asyncio.fixture
async def notification_db(request):
    url = _disposable_url()
    schema = "maintenance_notification_" + uuid4().hex
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    old_attempts = _legacy_attempt_table()
    organization_ids = (str(uuid4()), str(uuid4()))
    user_ids = (str(uuid4()), str(uuid4()))
    created = False

    async def migrate(revision="0050", direction="upgrade"):
        async with engine.begin() as connection:
            await connection.run_sync(_run_migration, revision, direction)

    async def authority_row():
        async with sessions() as session:
            rows = (await session.execute(select(CONTROLS))).mappings().all()
            assert len(rows) <= 1
            return deepcopy(dict(rows[0])) if rows else None

    async def registry_rows():
        async with sessions() as session:
            rows = (await session.execute(select(REGISTRY).order_by(REGISTRY.c.id))).mappings().all()
            return [deepcopy(dict(row)) for row in rows]

    async def attempt_rows(*, legacy=False):
        table = old_attempts if legacy else ATTEMPTS
        async with sessions() as session:
            rows = (await session.execute(select(table).order_by(table.c.id))).mappings().all()
            return [deepcopy(dict(row)) for row in rows]

    async def delivery_row(delivery_id):
        async with sessions() as session:
            row = (await session.execute(
                select(DELIVERIES).where(DELIVERIES.c.id == delivery_id)
            )).mappings().one_or_none()
            return deepcopy(dict(row)) if row is not None else None

    async def new_delivery(*, organization_index=0, **changes):
        notification_id, delivery_id = str(uuid4()), str(uuid4())
        async with sessions() as session:
            session.add(Notification(
                id=notification_id, organization_id=organization_ids[organization_index],
                recipient_id=user_ids[organization_index], type="acceptance",
                title="Synthetic notification", message="synthetic-private-message",
                payload={"private": "synthetic-private-payload"},
            ))
            await session.flush()
            values = dict(
                id=delivery_id, organization_id=organization_ids[organization_index],
                notification_id=notification_id, channel="email", status="queued",
                priority=50, attempt_count=0, max_attempts=5,
                idempotency_key=str(uuid4()),
                delivery_metadata={"address": "synthetic-recipient@example.test"},
            )
            values.update(changes)
            session.add(NotificationDelivery(**values))
            await session.commit()
        return delivery_id

    async def new_attempt(delivery_id, *, legacy=False, **changes):
        table = old_attempts if legacy else ATTEMPTS
        now = datetime.now(UTC)
        values = dict(
            id=str(uuid4()), delivery_id=delivery_id, attempt_number=1, status="failed",
            provider_message_id=None, error_code="synthetic-error",
            response_metadata={}, started_at=now - timedelta(minutes=1), completed_at=now,
        )
        if not legacy:
            values.update(dispatch_protocol_version=None, dispatch_outcome=None)
        values.update(changes)
        async with sessions() as session:
            await session.execute(table.insert().values(**values))
            await session.commit()
        return values["id"]

    async def update_delivery(delivery_id, **values):
        async with sessions() as session:
            await session.execute(
                DELIVERIES.update().where(DELIVERIES.c.id == delivery_id).values(**values)
            )
            await session.commit()

    async def update_authority(**values):
        async with sessions() as session:
            await session.execute(CONTROLS.update().values(**values))
            await session.commit()

    async def close(*, expected_generation=None, session_factory=None):
        if expected_generation is None:
            expected_generation = (await authority_row())["version"]
        return await admission.close_admission(
            operation_id=str(uuid4()), expected_generation=expected_generation,
            reason="isolated notification closure", session_factory=session_factory or sessions,
        )

    async def snapshot(closed):
        async with sessions() as session:
            return await notifications.read_notification_activity_snapshot(
                session, operation_id=closed.operation_id,
                expected_generation=closed.generation,
            )

    def probed_sessions(*, pause=False):
        probe = SimpleNamespace(
            started=asyncio.Queue(), acquired=asyncio.Event(),
            release=asyncio.Event(), pause=pause,
        )
        factory = async_sessionmaker(
            engine, class_=_LockProbeSession, expire_on_commit=False,
            info={"notification_lock_probe": probe},
        )
        return factory, probe

    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT current_schema()")) == schema
            if getattr(request, "param", None) == "latest-metadata":
                # 0001 uses today's model metadata. Reproduce that creation
                # path for every table touched by 0047-0050 and its FK graph;
                # the root separately verifies the complete application chain.
                tables = list(set(_delivery_tables()) | {REGISTRY, ATTEMPTS})
                await connection.run_sync(
                    lambda connection: Base.metadata.create_all(connection, tables=tables)
                )
            else:
                await connection.run_sync(
                    lambda connection: Base.metadata.create_all(connection, tables=_delivery_tables())
                )
                await connection.run_sync(old_attempts.create)
        for revision in ("0047", "0048", "0049"):
            await migrate(revision)
        if getattr(request, "param", "notification") != "schema3":
            await migrate()
        async with sessions() as session:
            for index, identity in enumerate(organization_ids):
                role_id = str(uuid4())
                session.add(Organization(
                    id=identity, name="Isolated Notification Organization",
                    slug="notification-" + identity,
                ))
                await session.flush()
                session.add(Role(id=role_id, organization_id=identity, name="Owner"))
                await session.flush()
                session.add(User(
                    id=user_ids[index], organization_id=identity, role_id=role_id,
                    name="Isolated Notification Recipient",
                    email=user_ids[index] + "@example.test", password_hash="synthetic-unused-hash",
                ))
            await session.commit()
        yield SimpleNamespace(
            engine=engine, sessions=sessions, migrate=migrate,
            authority_row=authority_row, registry_rows=registry_rows,
            attempt_rows=attempt_rows, delivery_row=delivery_row,
            new_delivery=new_delivery, new_attempt=new_attempt,
            update_delivery=update_delivery, update_authority=update_authority,
            organization_ids=organization_ids, user_ids=user_ids, close=close, snapshot=snapshot,
            probed_sessions=probed_sessions,
        )
    finally:
        await engine.dispose()
        try:
            if created:
                async with administration.begin() as connection:
                    await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await administration.dispose()


async def _claim(db, delivery_id=None, *, dispatch=False, session_factory=None):
    delivery_id = delivery_id or await db.new_delivery()
    async with (session_factory or db.sessions)() as session:
        owned = await notifications.register_notification_activity(
            session, delivery_id=delivery_id, worker_incarnation=str(uuid4()),
        )
        if dispatch:
            await notifications.begin_notification_dispatch(session, owned)
        await session.commit()
        return owned


async def _settle(db, owned, *, outcome="no_send", delivery_status="retrying", **extra):
    async with db.sessions() as session:
        await notifications.settle_notification_dispatch(
            session, owned, outcome=outcome, delivery_status=delivery_status, **extra,
        )
        await session.commit()


async def _await_blocked(sessions, pid, blocker):
    deadline = asyncio.get_running_loop().time() + WAIT
    async with sessions() as observer:
        while asyncio.get_running_loop().time() < deadline:
            if blocker in (await observer.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
            ) or []):
                return
            await asyncio.sleep(0.01)
    pytest.fail("A real PostgreSQL admission lock wait was not observed")


async def _stop_task(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["commit", "rollback", "cancel"])
async def test_claim_attempt_and_processing_are_one_transaction_that_blocks_close(notification_db, outcome):
    db = notification_db
    delivery_id = await db.new_delivery()
    registered, release = asyncio.Event(), asyncio.Event()
    claim_factory, claim_probe = db.probed_sessions()
    close_factory, close_probe = db.probed_sessions()
    claimant = closer = None

    async def claim_until_released():
        async with claim_factory() as session:
            owned = await notifications.register_notification_activity(
                session, delivery_id=delivery_id, worker_incarnation=str(uuid4()),
            )
            await session.flush()
            registered.set()
            await release.wait()
            if outcome == "rollback":
                await session.rollback()
                return None
            await session.commit()
            return owned

    try:
        claimant = asyncio.create_task(claim_until_released())
        claim_pid, shared = await asyncio.wait_for(claim_probe.started.get(), WAIT)
        assert shared is True
        await asyncio.wait_for(registered.wait(), WAIT)
        assert await db.registry_rows() == []
        assert await db.attempt_rows() == []
        before = await db.delivery_row(delivery_id)
        assert before["status"] == "queued" and before["attempt_count"] == 0
        closer = asyncio.create_task(db.close(expected_generation=4, session_factory=close_factory))
        close_pid, shared = await asyncio.wait_for(close_probe.started.get(), WAIT)
        assert shared is False
        await _await_blocked(db.sessions, close_pid, claim_pid)
        assert not closer.done()
        if outcome == "cancel":
            claimant.cancel()
            with pytest.raises(asyncio.CancelledError):
                await claimant
        else:
            release.set()
            owned = await asyncio.wait_for(claimant, WAIT)
        closed = await asyncio.wait_for(closer, WAIT)
        rows, attempts = await db.registry_rows(), await db.attempt_rows()
        delivery = await db.delivery_row(delivery_id)
        measured = await db.snapshot(closed)
        if outcome == "commit":
            assert owned.admitted_generation == 4 and owned.attempt_number == 1
            assert len(rows) == len(attempts) == 1
            assert rows[0]["id"] == attempts[0]["id"] == owned.activity_id
            assert rows[0]["phase"] == "claimed"
            assert attempts[0]["status"] == "started"
            assert attempts[0]["dispatch_protocol_version"] == 1
            assert attempts[0]["dispatch_outcome"] is None
            assert delivery["status"] == "processing" and delivery["attempt_count"] == 1
            assert not measured.is_clear
            with pytest.raises((AttributeError, TypeError)):
                owned.attempt_number = 99
        else:
            assert rows == attempts == []
            assert delivery == before
            assert measured.is_clear
    finally:
        release.set()
        await _stop_task(claimant)
        await _stop_task(closer)


@pytest.mark.asyncio
async def test_close_first_rejects_waiting_claim_without_any_partial_write(notification_db):
    db = notification_db
    delivery_id = await db.new_delivery()
    before = await db.delivery_row(delivery_id)
    close_factory, close_probe = db.probed_sessions(pause=True)
    claim_factory, claim_probe = db.probed_sessions()
    claimant = closer = None
    try:
        closer = asyncio.create_task(db.close(expected_generation=4, session_factory=close_factory))
        close_pid, shared = await asyncio.wait_for(close_probe.started.get(), WAIT)
        assert shared is False
        await asyncio.wait_for(close_probe.acquired.wait(), WAIT)
        claimant = asyncio.create_task(_claim(db, delivery_id, session_factory=claim_factory))
        claim_pid, shared = await asyncio.wait_for(claim_probe.started.get(), WAIT)
        assert shared is True
        await _await_blocked(db.sessions, claim_pid, close_pid)
        close_probe.release.set()
        await asyncio.wait_for(closer, WAIT)
        with pytest.raises(admission.HostMaintenanceClosed):
            await asyncio.wait_for(claimant, WAIT)
        assert await db.delivery_row(delivery_id) == before
        assert await db.registry_rows() == await db.attempt_rows() == []
    finally:
        close_probe.release.set()
        await _stop_task(claimant)
        await _stop_task(closer)


@pytest.mark.asyncio
async def test_actual_commit_failure_rolls_back_all_claim_evidence(notification_db):
    db = notification_db
    delivery_id = await db.new_delivery()
    before = await db.delivery_row(delivery_id)
    tripwire = Table(
        "notification_commit_tripwire", MetaData(),
        Column("id", String(36), primary_key=True),
        Column("delivery_id", String(36), ForeignKey(
            DELIVERIES.c.id, deferrable=True, initially="DEFERRED",
        ), nullable=False),
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(tripwire.create)

    def failing_sessions():
        session = db.sessions()

        def before_commit(sync_session):
            sync_session.execute(tripwire.insert().values(
                id=str(uuid4()), delivery_id=str(uuid4()),
            ))

        event.listen(session.sync_session, "before_commit", before_commit)
        return session

    with pytest.raises(IntegrityError) as caught:
        await _claim(db, delivery_id, session_factory=failing_sessions)
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23503"
    assert await db.registry_rows() == await db.attempt_rows() == []
    assert await db.delivery_row(delivery_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [
    "schema1", "schema2", "schema3", "closed", "missing", "malformed", "unknown", "database-error",
])
async def test_registration_requires_notification_coverage_and_fails_closed(notification_db, condition):
    db = notification_db
    delivery_id = await db.new_delivery()
    before = await db.delivery_row(delivery_id)
    expected = admission.HostMaintenanceUnavailable
    if condition == "closed":
        await db.close()
        expected = admission.HostMaintenanceClosed
    elif condition in ("missing", "database-error"):
        async with db.sessions() as session:
            if condition == "missing":
                await session.execute(CONTROLS.delete())
            else:
                await session.execute(text(
                    "ALTER TABLE owner_control_records RENAME TO unavailable_notification_authority"
                ))
            await session.commit()
    else:
        original = await db.authority_row()
        payload = deepcopy(original["payload"])
        if condition == "schema1":
            payload = {
                "schema_version": 1, "scope": "project_execution", "generation": 1,
                "operation_id": None, "reason": "migration-seed", "changed_at": None,
                "full_host_closure": False,
            }
            await db.update_authority(payload=payload, version=1)
        else:
            if condition == "schema2":
                payload.update(schema_version=2, scope="project_execution+backup_cycles")
            elif condition == "schema3":
                payload.update(
                    schema_version=3,
                    scope="project_execution+backup_cycles+academy_course_packages",
                )
            elif condition == "malformed":
                payload["full_host_closure"] = True
            else:
                payload["schema_version"] = 99
            await db.update_authority(payload=payload)
    async with db.sessions() as session:
        with pytest.raises(expected) as caught:
            await notifications.register_notification_activity(
                session, delivery_id=delivery_id, worker_incarnation=str(uuid4()),
            )
    if condition == "database-error":
        assert caught.value.__suppress_context__ is True
        assert "unavailable_notification_authority" not in str(caught.value)
        assert "SELECT" not in str(caught.value)
    assert await db.registry_rows() == await db.attempt_rows() == []
    assert await db.delivery_row(delivery_id) == before


@pytest.mark.asyncio
async def test_admission_preserves_unexpected_non_database_errors(notification_db, monkeypatch):
    failure = RuntimeError("synthetic non-database programming failure")
    async with notification_db.sessions() as session:
        monkeypatch.setattr(session, "execute", AsyncMock(side_effect=failure))
        with pytest.raises(RuntimeError) as caught:
            await notifications.require_notification_admission(session)
        assert caught.value is failure


@pytest.mark.asyncio
async def test_dispatch_begin_is_transactional_and_can_only_be_consumed_once(notification_db):
    db = notification_db
    owned = await _claim(db)
    before = await db.registry_rows()
    async with db.sessions() as session:
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.require_owned_notification_activity(session, owned)
        await notifications.begin_notification_dispatch(session, owned)
        await notifications.require_owned_notification_activity(session, owned)
        assert await db.registry_rows() == before
        await session.rollback()
    assert await db.registry_rows() == before
    async with db.sessions() as session:
        await notifications.begin_notification_dispatch(session, owned)
        await session.commit()
    dispatched = await db.registry_rows()
    assert dispatched[0]["phase"] == "dispatching"
    async with db.sessions() as session:
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.begin_notification_dispatch(session, owned)
    assert await db.registry_rows() == dispatched
    await _settle(db, owned)
    async with db.sessions() as session:
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.require_owned_notification_activity(session, owned)
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.begin_notification_dispatch(session, owned)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "activity_id", "delivery_id", "attempt_number",
    "worker_incarnation", "admitted_generation", "ownership_nonce",
])
async def test_identity_fences_every_owned_mutation(notification_db, field):
    db = notification_db
    owned, other = await _claim(db, dispatch=True), await _claim(db, dispatch=True)
    replacement = getattr(owned, field) + 1 if field in ("attempt_number", "admitted_generation") else getattr(other, field)
    forged = replace(owned, **{field: replacement})
    before = await db.registry_rows(), await db.attempt_rows(), await db.delivery_row(owned.delivery_id)
    async with db.sessions() as session:
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.begin_notification_dispatch(session, forged)
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.require_owned_notification_activity(session, forged)
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.settle_notification_dispatch(
                session, forged, outcome="no_send", delivery_status="retrying",
            )
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.heartbeat_notification_activity(forged, session_factory=db.sessions)
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.mark_notification_activity_unresolved(
            forged, reason="forged identity", session_factory=db.sessions,
        )
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.finish_notification_activity(forged, session_factory=db.sessions)
    assert (await db.registry_rows(), await db.attempt_rows(), await db.delivery_row(owned.delivery_id)) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,settled_status,manual_status", [
    ("accepted", "delivered", None),
    ("accepted", "delivered", "acknowledged"),
    ("no_send", "retrying", None),
    ("no_send", "unconfigured", "queued"),
    ("rejected", "failed", None),
    ("rejected", "dead_letter", "queued"),
])
async def test_settlement_is_atomic_and_old_exact_owner_can_finish_after_close_and_expiry(
    notification_db, outcome, settled_status, manual_status,
):
    db = notification_db
    owned = await _claim(db, dispatch=True)
    closed = await db.close()
    await notifications.heartbeat_notification_activity(owned, session_factory=db.sessions)
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    before = await db.registry_rows(), await db.attempt_rows(), await db.delivery_row(owned.delivery_id)
    assert (await db.snapshot(closed)).expired_count == 1
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.finish_notification_activity(owned, session_factory=db.sessions)
    async with db.sessions() as session:
        await notifications.settle_notification_dispatch(
            session, owned, outcome=outcome, delivery_status=settled_status,
            provider_message_id="synthetic-provider-id" if outcome == "accepted" else None,
            error_code=None if outcome == "accepted" else "synthetic-no-acceptance",
        )
        # The provider proof, business status and registry phase commit together.
        assert (await db.registry_rows(), await db.attempt_rows(), await db.delivery_row(owned.delivery_id)) == before
        await session.commit()
    rows, attempts = await db.registry_rows(), await db.attempt_rows()
    assert rows[0]["phase"] == "settled"
    assert attempts[0]["dispatch_outcome"] == outcome
    assert attempts[0]["completed_at"] is not None
    assert (await db.delivery_row(owned.delivery_id))["status"] == settled_status
    async with db.sessions() as session:
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.settle_notification_dispatch(
                session, owned, outcome=outcome, delivery_status=settled_status,
            )
    if manual_status == "acknowledged":
        from app.services.communications import acknowledge_delivery

        async with db.sessions() as session:
            delivery = await session.get(NotificationDelivery, owned.delivery_id)
            await acknowledge_delivery(session, delivery, actor_id=db.user_ids[0])
            await session.commit()
        # Exercise the route's actual business helper: acknowledged status is
        # accompanied by committed timing and its independently visible audit.
        acknowledged = await db.delivery_row(owned.delivery_id)
        assert acknowledged["acknowledged_at"].utcoffset() is not None
        async with db.sessions() as session:
            assert await session.scalar(select(AuditEvent.id).where(
                AuditEvent.resource_id == owned.delivery_id,
                AuditEvent.action == "notification.delivery.acknowledged",
            )) is not None
    elif manual_status is not None:
        # A safe manual queue clears the dead-letter marker as well as changing
        # status; stale result provenance alone must not become eligible work.
        fields = {"status": manual_status, "dead_lettered_at": None}
        await db.update_delivery(owned.delivery_id, **fields)
    attempts_before_finish = await db.attempt_rows()
    await notifications.finish_notification_activity(owned, session_factory=db.sessions)
    assert await db.registry_rows() == []
    assert await db.attempt_rows() == attempts_before_finish
    measured = await db.snapshot(closed)
    assert measured.is_clear and measured.blocker_count == 0
    assert measured.full_host_closure is False and measured.coverage_unverified is True
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.finish_notification_activity(owned, session_factory=db.sessions)


@pytest.mark.asyncio
async def test_accepted_delivery_manually_queued_cannot_be_finished_or_sent_again(notification_db):
    db = notification_db
    owned = await _claim(db, dispatch=True)
    await _settle(db, owned, outcome="accepted", delivery_status="delivered")
    await db.update_delivery(owned.delivery_id, status="queued")
    before = await db.registry_rows(), await db.attempt_rows()
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.finish_notification_activity(owned, session_factory=db.sessions)
    async with db.sessions() as session:
        assert await session.scalar(select(DELIVERIES.c.id).where(
            DELIVERIES.c.id == owned.delivery_id,
            *notifications.eligible_notification_delivery_conditions(DELIVERIES),
        )) is None
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.register_notification_activity(
                session, delivery_id=owned.delivery_id, worker_incarnation=str(uuid4()),
            )
    assert (await db.registry_rows(), await db.attempt_rows()) == before
    measured = await db.snapshot(await db.close())
    assert owned.delivery_id in {item.delivery_id for item in measured.activities}
    assert owned.delivery_id not in measured.frozen_queued_ids
    assert measured.blocker_count == 1 and not measured.is_clear


@pytest.mark.asyncio
async def test_unresolved_and_expired_dispatch_is_never_adopted_or_deleted(notification_db):
    db = notification_db
    owned = await _claim(db, dispatch=True)
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    await notifications.mark_notification_activity_unresolved(
        owned, reason="cancelled provider await has unknown acceptance",
        session_factory=db.sessions,
    )
    await notifications.mark_notification_activity_unresolved(
        owned, reason="later reason must not erase first ambiguity",
        session_factory=db.sessions,
    )
    await db.update_delivery(owned.delivery_id, status="queued")
    before = await db.registry_rows(), await db.attempt_rows()
    async with db.sessions() as session:
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.register_notification_activity(
                session, delivery_id=owned.delivery_id, worker_incarnation=str(uuid4()),
            )
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.require_owned_notification_activity(session, owned)
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.settle_notification_dispatch(
                session, owned, outcome="no_send", delivery_status="failed",
            )
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.finish_notification_activity(owned, session_factory=db.sessions)
    assert (await db.registry_rows(), await db.attempt_rows()) == before
    measured = await db.snapshot(await db.close())
    assert measured.unresolved_count == measured.expired_count == 1
    assert measured.blocker_count == 1 and not measured.is_clear
    assert before[0][0]["unresolved_reason"] == "cancelled provider await has unknown acceptance"


@pytest.mark.asyncio
async def test_contiguous_completed_no_send_and_rejected_proofs_allow_safe_retry(notification_db):
    db = notification_db
    delivery_id = await db.new_delivery()
    owners = []
    for number, outcome in enumerate(("no_send", "rejected"), start=1):
        owned = await _claim(db, delivery_id, dispatch=True)
        assert owned.attempt_number == number
        await _settle(db, owned, outcome=outcome, delivery_status="failed")
        await notifications.finish_notification_activity(owned, session_factory=db.sessions)
        owners.append(owned)
        await db.update_delivery(delivery_id, status="queued")
        async with db.sessions() as session:
            assert await session.scalar(select(DELIVERIES.c.id).where(
                DELIVERIES.c.id == delivery_id,
                *notifications.eligible_notification_delivery_conditions(DELIVERIES),
            )) == delivery_id
    attempts = await db.attempt_rows()
    assert {row["id"] for row in attempts} == {owned.activity_id for owned in owners}
    assert sorted(row["attempt_number"] for row in attempts) == [1, 2]
    assert all(row["dispatch_protocol_version"] == 1 and row["completed_at"] for row in attempts)
    closed = await db.close()
    measured = await db.snapshot(closed)
    assert measured.is_clear and measured.frozen_queued_ids == (delivery_id,)
    await admission.open_admission(
        operation_id=closed.operation_id, expected_generation=closed.generation,
        reason="resume proven safe retries", session_factory=db.sessions,
    )
    third = await _claim(db, delivery_id)
    assert third.attempt_number == 3
    assert len(await db.attempt_rows()) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "legacy-failed", "started", "uncertain", "accepted", "missing-attempt",
    "number-gap", "count-mismatch", "incompatible-status", "uncompleted",
])
async def test_independent_attempt_evidence_blocks_manual_queue_without_activity(notification_db, case):
    db = notification_db
    delivery_id = await db.new_delivery(attempt_count=1)
    values = dict(
        dispatch_protocol_version=1, dispatch_outcome="no_send",
        status="failed", completed_at=datetime.now(UTC),
    )
    if case == "legacy-failed":
        values.update(dispatch_protocol_version=None, dispatch_outcome=None)
    elif case == "started":
        values.update(dispatch_outcome=None, status="started", completed_at=None)
    elif case == "uncertain":
        values.update(dispatch_outcome="uncertain", status="failed")
    elif case == "accepted":
        values.update(dispatch_outcome="accepted", status="delivered")
    elif case == "number-gap":
        values["attempt_number"] = 2
        await db.update_delivery(delivery_id, attempt_count=2)
    elif case == "count-mismatch":
        await db.update_delivery(delivery_id, attempt_count=2)
    elif case == "incompatible-status":
        values["status"] = "unrecognized-attempt-status"
    elif case == "uncompleted":
        values["completed_at"] = None
    if case != "missing-attempt":
        await db.new_attempt(delivery_id, **values)
    before = await db.attempt_rows(), await db.delivery_row(delivery_id)
    assert await db.registry_rows() == []
    async with db.sessions() as session:
        assert await session.scalar(select(DELIVERIES.c.id).where(
            DELIVERIES.c.id == delivery_id,
            *notifications.eligible_notification_delivery_conditions(DELIVERIES),
        )) is None
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.register_notification_activity(
                session, delivery_id=delivery_id, worker_incarnation=str(uuid4()),
            )
    assert (await db.attempt_rows(), await db.delivery_row(delivery_id)) == before
    measured = await db.snapshot(await db.close())
    assert delivery_id in measured.nonpristine_queued_ids
    assert measured.blocker_count == 1 and not measured.is_clear
    assert delivery_id not in measured.frozen_queued_ids


@pytest.mark.asyncio
async def test_delivery_cascade_cannot_erase_orphan_activity(notification_db):
    db = notification_db
    owned = await _claim(db, dispatch=True)
    before = await db.registry_rows()
    async with db.sessions() as session:
        await session.execute(DELIVERIES.delete().where(DELIVERIES.c.id == owned.delivery_id))
        await session.commit()
    assert await db.delivery_row(owned.delivery_id) is None
    assert await db.attempt_rows() == []
    assert await db.registry_rows() == before
    with pytest.raises(notifications.NotificationActivityOwnershipLost):
        await notifications.finish_notification_activity(owned, session_factory=db.sessions)
    measured = await db.snapshot(await db.close())
    assert measured.unfinished_count == measured.blocker_count == 1
    assert not measured.is_clear


@pytest.mark.asyncio
async def test_snapshot_counts_every_generation_legacy_attempt_and_unknown_delivery_without_private_data(notification_db):
    db = notification_db
    older = await _claim(db, dispatch=True)
    first_closed = await db.close()
    reopened = await admission.open_admission(
        operation_id=first_closed.operation_id, expected_generation=first_closed.generation,
        reason="continue isolated dispatch coverage", session_factory=db.sessions,
    )
    newer = await _claim(db, dispatch=True)
    await notifications.mark_notification_activity_unresolved(
        older, reason="unsettled older provider call", session_factory=db.sessions,
    )
    legacy_processing = await db.new_delivery(status="processing", organization_index=1)
    legacy_failed = await db.new_delivery(attempt_count=1)
    await db.new_attempt(legacy_failed)
    started = await db.new_delivery(attempt_count=1)
    started_id = await db.new_attempt(
        started, status="started", dispatch_protocol_version=1,
        dispatch_outcome=None, completed_at=None,
    )
    unknown = await db.new_delivery(status="unrecognized-future-state")
    stale = await db.new_delivery(error_code="stale-pristine-provenance")
    pristine = await db.new_delivery()
    safe_retry = await _claim(db, dispatch=True)
    await _settle(db, safe_retry, outcome="no_send", delivery_status="retrying")
    await notifications.finish_notification_activity(safe_retry, session_factory=db.sessions)
    backup_owner = await backup_cycles.begin_backup_cycle(
        worker_incarnation=str(uuid4()), session_factory=db.sessions,
    )
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().where(
            REGISTRY.c.consumer == notifications.CONSUMER
        ).values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    closed = await db.close()
    before = await db.registry_rows(), await db.attempt_rows()
    measured = await db.snapshot(closed)
    assert measured.unfinished_count == 2
    assert measured.active_count == measured.unresolved_count == 1
    assert measured.expired_count == 2
    assert {item.admitted_generation for item in measured.activities} == {4, reopened.generation}
    assert set(measured.unowned_processing_ids) == {legacy_processing}
    assert set(measured.unknown_status_ids) == {unknown}
    assert {legacy_failed, started, stale}.issubset(measured.nonpristine_queued_ids)
    assert set(measured.frozen_queued_ids) == {pristine}
    assert set(measured.frozen_retrying_ids) == {safe_retry.delivery_id}
    assert started_id in {item.attempt_id for item in measured.unresolved_attempts}
    assert measured.blocker_count == 7 and not measured.is_clear
    assert measured.full_host_closure is False and measured.coverage_unverified is True
    encoded = json.dumps(asdict(measured), default=str)
    for private in (
        "ownership_nonce", older.ownership_nonce, newer.ownership_nonce,
        "provider_message_id", "synthetic-private-message", "synthetic-private-payload",
        "synthetic-recipient@example.test", "response_metadata", "delivery_metadata",
    ):
        assert private not in encoded
    assert older.ownership_nonce not in repr(older)
    assert all(not hasattr(item, "ownership_nonce") for item in measured.activities)
    assert (await db.registry_rows(), await db.attempt_rows()) == before
    async with db.sessions() as session:
        backups = await backup_cycles.snapshot_backup_cycles(
            session, operation_id=closed.operation_id, expected_generation=closed.generation,
        )
    assert {item.cycle_id for item in backups.cycles} == {backup_owner.cycle_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("notification_db", ["schema3"], indirect=True)
@pytest.mark.parametrize("state", ["open", "closed"])
async def test_0050_advances_only_coverage_and_preserves_legacy_attempts_and_existing_cycles(notification_db, state):
    db = notification_db
    delivery_id = await db.new_delivery(attempt_count=1)
    legacy_attempt = await db.new_attempt(delivery_id, legacy=True)
    backup_owner = await backup_cycles.begin_backup_cycle(
        worker_incarnation=str(uuid4()), session_factory=db.sessions,
    )
    if state == "closed":
        await db.close()
    before = await db.authority_row()
    attempts_before, registry_before = await db.attempt_rows(legacy=True), await db.registry_rows()
    await db.migrate()
    after = await db.authority_row()
    assert after["id"] == before["id"]
    assert after["status"] == before["status"] and after["enabled"] == before["enabled"]
    assert after["version"] == before["version"] + 1
    payload = after["payload"]
    assert payload["schema_version"] == admission.NOTIFICATION_SCHEMA_VERSION == 4
    assert payload["scope"] == (
        "project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch"
    )
    assert payload["generation"] == after["version"]
    for field in ("operation_id", "reason", "changed_at", "full_host_closure"):
        assert payload[field] == before["payload"][field]
    attempts = await db.attempt_rows()
    assert attempts[0]["id"] == legacy_attempt
    assert attempts[0]["dispatch_protocol_version"] is None
    assert attempts[0]["dispatch_outcome"] is None
    assert await db.attempt_rows(legacy=True) == attempts_before
    assert await db.registry_rows() == registry_before
    for direction in ("upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.authority_row() == after
        assert await db.attempt_rows() == attempts
        assert await db.registry_rows() == registry_before
    with pytest.raises(admission.HostMaintenanceConflict):
        await admission.close_admission(
            operation_id=str(uuid4()), expected_generation=before["version"],
            reason="stale pre-notification generation", session_factory=db.sessions,
        )
    if state == "closed":
        with pytest.raises(admission.HostMaintenanceConflict):
            await admission.open_admission(
                operation_id=before["payload"]["operation_id"],
                expected_generation=before["version"], reason="stale closure receipt",
                session_factory=db.sessions,
            )
        await admission.open_admission(
            operation_id=after["payload"]["operation_id"], expected_generation=after["version"],
            reason="current covered generation", session_factory=db.sessions,
        )
    async with db.sessions() as session:
        for scope in (
            "project_execution", "backup_cycles", "academy_course_packages",
            "notification_delivery_dispatch",
        ):
            assert (await admission.require_admission_open(session, required_scope=scope)).is_open
    await backup_cycles.finish_backup_cycle(backup_owner, session_factory=db.sessions)
    assert await db.registry_rows() == []
    assert (await _claim(db)).attempt_number == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("notification_db", ["schema3"], indirect=True)
@pytest.mark.parametrize("state", ["missing", "malformed", "unknown", "schema1", "schema2", "already4"])
async def test_0050_retains_unupgradeable_authority_without_repair_or_reopen(notification_db, state):
    db = notification_db
    before = await db.authority_row()
    payload = deepcopy(before["payload"])
    if state == "missing":
        async with db.sessions() as session:
            await session.execute(CONTROLS.delete())
            await session.commit()
    elif state == "schema1":
        await db.update_authority(version=1, payload={
            "schema_version": 1, "scope": "project_execution", "generation": 1,
            "operation_id": None, "reason": "migration-seed", "changed_at": None,
            "full_host_closure": False,
        })
    else:
        if state == "malformed":
            payload["generation"] = True
        elif state == "unknown":
            payload["schema_version"] = 99
        elif state == "schema2":
            payload.update(schema_version=2, scope="project_execution+backup_cycles")
        else:
            payload.update(
                schema_version=4,
                scope="project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch",
                generation=9, operation_id=str(uuid4()), reason="existing notification closure",
                changed_at=datetime.now(UTC).isoformat(),
            )
            await db.update_authority(status="closed", enabled=False, version=9)
        await db.update_authority(payload=payload)
    preserved = await db.authority_row()
    for direction in ("upgrade", "upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.authority_row() == preserved


@pytest.mark.asyncio
async def test_0050_replay_and_downgrade_preserve_active_and_unresolved_dispatch_evidence(notification_db):
    db = notification_db
    await _claim(db, dispatch=True)
    uncertain = await _claim(db, dispatch=True)
    await notifications.mark_notification_activity_unresolved(
        uncertain, reason="preserve uncertain dispatch", session_factory=db.sessions,
    )
    closed = await db.close()
    before = await db.registry_rows(), await db.attempt_rows(), await db.authority_row()
    # Retained notification rows and proof columns must survive crossing both
    # downgrade boundaries and replaying the now older 0049 migration.
    for revision, direction in (
        ("0050", "upgrade"), ("0050", "downgrade"), ("0049", "downgrade"),
        ("0049", "upgrade"), ("0050", "upgrade"),
    ):
        await db.migrate(revision, direction=direction)
        assert (await db.registry_rows(), await db.attempt_rows(), await db.authority_row()) == before
    measured = await db.snapshot(closed)
    assert measured.active_count == measured.unresolved_count == 1
    assert measured.blocker_count == 2 and not measured.is_clear


@pytest.mark.asyncio
@pytest.mark.parametrize("notification_db", ["latest-metadata"], indirect=True)
async def test_current_model_metadata_accepts_0047_through_0050_and_retains_notification_constraints(notification_db):
    db = notification_db
    row = await db.authority_row()
    assert row["version"] == 4 and row["payload"]["schema_version"] == 4
    owned = await _claim(db, dispatch=True)
    before = await db.registry_rows(), await db.attempt_rows()
    await db.migrate("0049")
    await db.migrate("0050")
    assert (await db.registry_rows(), await db.attempt_rows()) == before
    # A retained widened consumer check accepts notification evidence, and its
    # partial unique index still rejects duplicate ownership for one delivery.
    duplicate = {**before[0][0], "id": str(uuid4()), "ownership_nonce": str(uuid4())}
    async with db.sessions() as session:
        with pytest.raises(IntegrityError) as caught:
            await session.execute(REGISTRY.insert().values(**duplicate))
        await session.rollback()
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23505"
    assert (await db.registry_rows(), await db.attempt_rows()) == before
    await _settle(db, owned)
    await notifications.finish_notification_activity(owned, session_factory=db.sessions)
    assert await db.registry_rows() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["no_send", "rejected"])
async def test_provider_acceptance_artifact_invalidates_otherwise_safe_retry_history(notification_db, outcome):
    db = notification_db
    delivery_id = await db.new_delivery(attempt_count=1)
    provider_id = "synthetic-provider-acceptance-artifact"
    attempt_id = await db.new_attempt(
        delivery_id, status="failed", dispatch_protocol_version=1,
        dispatch_outcome=outcome, provider_message_id=provider_id,
    )
    before = await db.attempt_rows(), await db.delivery_row(delivery_id)
    async with db.sessions() as session:
        assert await session.scalar(select(DELIVERIES.c.id).where(
            DELIVERIES.c.id == delivery_id,
            *notifications.eligible_notification_delivery_conditions(DELIVERIES),
        )) is None
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.register_notification_activity(
                session, delivery_id=delivery_id, worker_incarnation=str(uuid4()),
            )
    assert await db.registry_rows() == []
    assert (await db.attempt_rows(), await db.delivery_row(delivery_id)) == before
    closed = await db.close()
    with pytest.raises(notifications.NotificationActivityRegistryUnavailable) as caught:
        await db.snapshot(closed)
    assert provider_id not in str(caught.value)
    assert attempt_id not in str(caught.value)


@pytest.mark.asyncio
async def test_malformed_attempt_uuid_cannot_be_claimed_and_snapshot_fails_closed(notification_db):
    db = notification_db
    delivery_id = await db.new_delivery(attempt_count=1)
    await db.new_attempt(
        delivery_id, id="not-a-uuid", status="failed", dispatch_protocol_version=1,
        dispatch_outcome="no_send",
    )
    before = await db.attempt_rows(), await db.delivery_row(delivery_id)
    async with db.sessions() as session:
        assert await session.scalar(select(DELIVERIES.c.id).where(
            DELIVERIES.c.id == delivery_id,
            *notifications.eligible_notification_delivery_conditions(DELIVERIES),
        )) is None
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.register_notification_activity(
                session, delivery_id=delivery_id, worker_incarnation=str(uuid4()),
            )
    assert await db.registry_rows() == []
    assert (await db.attempt_rows(), await db.delivery_row(delivery_id)) == before
    closed = await db.close()
    with pytest.raises(notifications.NotificationActivityRegistryUnavailable):
        await db.snapshot(closed)


@pytest.mark.asyncio
@pytest.mark.parametrize("notification_db", ["schema3"], indirect=True)
async def test_0050_refuses_missing_attempt_number_uniqueness_before_advancing_authority(notification_db):
    db = notification_db
    delivery_id = await db.new_delivery(attempt_count=1)
    await db.new_attempt(delivery_id, legacy=True)
    async with db.sessions() as session:
        await session.execute(text(
            "ALTER TABLE notification_delivery_attempts "
            "DROP CONSTRAINT uq_notification_delivery_attempt"
        ))
        await session.commit()
    before = await db.authority_row(), await db.attempt_rows(legacy=True), await db.registry_rows()
    assert before[0]["payload"]["schema_version"] == 3
    with pytest.raises(RuntimeError):
        await db.migrate()
    assert (await db.authority_row(), await db.attempt_rows(legacy=True), await db.registry_rows()) == before


@pytest.mark.asyncio
async def test_duplicate_attempt_numbers_cannot_satisfy_count_consistent_retry_history(notification_db):
    db = notification_db
    async with db.sessions() as session:
        await session.execute(text(
            "ALTER TABLE notification_delivery_attempts "
            "DROP CONSTRAINT uq_notification_delivery_attempt"
        ))
        await session.commit()
    delivery_id = await db.new_delivery(attempt_count=2)
    for outcome in ("no_send", "rejected"):
        await db.new_attempt(
            delivery_id, attempt_number=1, status="failed",
            dispatch_protocol_version=1, dispatch_outcome=outcome,
        )
    before = await db.attempt_rows(), await db.delivery_row(delivery_id)
    assert [row["attempt_number"] for row in before[0]] == [1, 1]
    async with db.sessions() as session:
        assert await session.scalar(select(DELIVERIES.c.id).where(
            DELIVERIES.c.id == delivery_id,
            *notifications.eligible_notification_delivery_conditions(DELIVERIES),
        )) is None
        with pytest.raises(notifications.NotificationActivityOwnershipLost):
            await notifications.register_notification_activity(
                session, delivery_id=delivery_id, worker_incarnation=str(uuid4()),
            )
    assert await db.registry_rows() == []
    assert (await db.attempt_rows(), await db.delivery_row(delivery_id)) == before
    measured = await db.snapshot(await db.close())
    assert measured.blocker_count == 1 and not measured.is_clear
    assert delivery_id in measured.nonpristine_queued_ids
    assert delivery_id not in measured.frozen_queued_ids
