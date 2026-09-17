"""PostgreSQL acceptance for transaction-scoped host-maintenance admission.

Every DB case owns one UUID control row in a verified disposable database.
Session probes delegate the real locking SELECT and observe PostgreSQL blocking;
they do not simulate row locks, transactions, guards, or state transitions.
"""
from __future__ import annotations

import asyncio
import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
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
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.models import OwnerControlRecord
from app.services import host_maintenance_admission as maintenance


def _disposable_postgres_url():
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        pytest.fail("Host-maintenance DB acceptance requires a disposable PostgreSQL DATABASE_URL")
    url = make_url(raw)
    if not url.drivername.startswith("postgresql"):
        pytest.fail("Host-maintenance DB acceptance requires PostgreSQL row locking")
    name = (url.database or "").lower()
    if re.search(r"(?:^|_)(?:test|pytest|ci|smoke|disposable)(?:_|$)", name) is None:
        pytest.fail("Host-maintenance DB acceptance refuses a non-test database")
    return url


class _LockProbeSession(AsyncSession):
    """Announce the real locking statement and optionally pause after acquisition."""

    async def _before_lock(self, statement):
        lock = getattr(statement, "_for_update_arg", None)
        probe = self.info.get("maintenance_lock_probe")
        if lock is None or probe is None or self.info.get("maintenance_probe_seen"):
            return None
        self.info["maintenance_probe_seen"] = True
        pid = await AsyncSession.scalar(self, text("SELECT pg_backend_pid()"))
        event = (int(pid), bool(lock.read))
        probe.started.put_nowait(event)
        return event

    async def _after_lock(self, event):
        if event is None:
            return
        probe = self.info["maintenance_lock_probe"]
        probe.acquired.set()
        if probe.pause_after_acquire:
            await probe.release.wait()

    async def execute(self, statement, *args, **kwargs):
        event = await self._before_lock(statement)
        result = await super().execute(statement, *args, **kwargs)
        await self._after_lock(event)
        return result

    async def scalar(self, statement, *args, **kwargs):
        event = await self._before_lock(statement)
        result = await super().scalar(statement, *args, **kwargs)
        await self._after_lock(event)
        return result


@pytest_asyncio.fixture
async def maintenance_db(monkeypatch):
    engine = create_async_engine(_disposable_postgres_url(), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    resource_id = "maintenance-test-" + str(uuid4())
    control_id = str(uuid4())
    monkeypatch.setattr(maintenance, "RESOURCE_ID", resource_id)
    payload = {
        "schema_version": 1,
        "scope": "project_execution",
        "generation": 1,
        "operation_id": None,
        "reason": "migration-seed",
        "changed_at": None,
        "full_host_closure": False,
    }

    def probed_sessions(*, pause_after_acquire=False):
        probe = SimpleNamespace(
            started=asyncio.Queue(),
            acquired=asyncio.Event(),
            release=asyncio.Event(),
            pause_after_acquire=pause_after_acquire,
        )
        factory = async_sessionmaker(
            engine,
            class_=_LockProbeSession,
            expire_on_commit=False,
            info={"maintenance_lock_probe": probe},
        )
        return factory, probe

    async def read_row():
        async with sessions() as session:
            row = await session.get(OwnerControlRecord, control_id)
            if row is None:
                return None
            return {
                "status": row.status,
                "enabled": row.enabled,
                "version": row.version,
                "payload": deepcopy(row.payload),
            }

    seeded = False
    try:
        async with sessions() as session:
            session.add(OwnerControlRecord(
                id=control_id,
                domain=maintenance.DOMAIN,
                resource_id=resource_id,
                status="open",
                enabled=True,
                payload=payload,
                version=1,
            ))
            await session.commit()
        seeded = True
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            control_id=control_id,
            resource_id=resource_id,
            probed_sessions=probed_sessions,
            read_row=read_row,
        )
    finally:
        if seeded:
            async with sessions() as cleanup:
                await cleanup.execute(
                    delete(OwnerControlRecord).where(OwnerControlRecord.id == control_id)
                )
                await cleanup.commit()
        await engine.dispose()


async def _await_blocked(sessions, pid, expected_blockers, *, timeout=5):
    deadline = asyncio.get_running_loop().time() + timeout
    last = set()
    async with sessions() as observer:
        while asyncio.get_running_loop().time() < deadline:
            blocking = await observer.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
            )
            last = set(blocking or [])
            if last.intersection(expected_blockers):
                return last
            await asyncio.sleep(0.01)
    pytest.fail(f"Real PostgreSQL lock wait was not observed; blocker count={len(last)}")


async def _stop_task(task):
    if task is None:
        return
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_shared_guards_coexist_and_close_waits_for_both_transactions(maintenance_db):
    db = maintenance_db
    operation_id = str(uuid4())
    writer_factory, writer_probe = db.probed_sessions()
    closing = None
    async with db.sessions() as first, db.sessions() as second:
        try:
            left = await asyncio.wait_for(maintenance.require_admission_open(first), 5)
            right = await asyncio.wait_for(maintenance.require_admission_open(second), 5)
            assert left.is_open and right.is_open
            assert left.generation == right.generation == 1
            with pytest.raises((AttributeError, TypeError)):
                left.generation = 99
            first_pid = int(await first.scalar(text("SELECT pg_backend_pid()")))
            second_pid = int(await second.scalar(text("SELECT pg_backend_pid()")))
            assert first_pid != second_pid
            closing = asyncio.create_task(maintenance.close_admission(
                operation_id=operation_id,
                expected_generation=1,
                reason="transaction-lock acceptance close",
                session_factory=writer_factory,
            ))
            writer_pid, shared = await asyncio.wait_for(writer_probe.started.get(), 5)
            assert shared is False
            await _await_blocked(db.sessions, writer_pid, {first_pid, second_pid})
            assert not closing.done()
            assert (await db.read_row())["status"] == "open"

            # Either original reader can be PostgreSQL's immediate blocker.
            # The writer must still wait for the second after the first commits.
            await first.commit()
            await _await_blocked(db.sessions, writer_pid, {second_pid})
            assert not closing.done()
            await second.rollback()
            closed = await asyncio.wait_for(closing, 5)
            assert closed.status == "closed" and closed.enabled is False
            assert closed.generation == 2 and closed.operation_id == operation_id
            assert closed.changed_at.utcoffset() is not None
            stored = await db.read_row()
            assert stored["status"] == "closed" and stored["version"] == 2
            assert stored["payload"]["generation"] == 2
        finally:
            writer_probe.release.set()
            await first.rollback()
            await second.rollback()
            await _stop_task(closing)


@pytest.mark.asyncio
async def test_close_wins_and_waiting_guard_rejects_despite_cached_open_row(maintenance_db):
    db = maintenance_db
    writer_factory, writer_probe = db.probed_sessions(pause_after_acquire=True)
    reader_factory, reader_probe = db.probed_sessions()
    closing = reading = None
    async with reader_factory() as reader:
        cached = await reader.get(OwnerControlRecord, db.control_id)
        assert cached is not None and cached.status == "open"
        try:
            closing = asyncio.create_task(maintenance.close_admission(
                operation_id=str(uuid4()),
                expected_generation=1,
                reason="close wins admission race",
                session_factory=writer_factory,
            ))
            writer_pid, writer_shared = await asyncio.wait_for(writer_probe.started.get(), 5)
            assert writer_shared is False
            await asyncio.wait_for(writer_probe.acquired.wait(), 5)
            reading = asyncio.create_task(maintenance.require_admission_open(reader))
            reader_pid, reader_shared = await asyncio.wait_for(reader_probe.started.get(), 5)
            assert reader_shared is True
            await _await_blocked(db.sessions, reader_pid, {writer_pid})
            assert not reading.done()
            assert cached.status == "open"  # Keep the stale ORM object strongly referenced.
            writer_probe.release.set()
            closed = await asyncio.wait_for(closing, 5)
            assert closed.status == "closed" and closed.generation == 2
            with pytest.raises(maintenance.HostMaintenanceClosed):
                await asyncio.wait_for(reading, 5)
            assert (await db.read_row())["status"] == "closed"
        finally:
            writer_probe.release.set()
            await _stop_task(reading)
            await reader.rollback()
            await _stop_task(closing)


@pytest.mark.asyncio
async def test_stale_generation_or_wrong_operation_cannot_open_newer_close(maintenance_db):
    db = maintenance_db
    first_operation, current_operation = str(uuid4()), str(uuid4())
    first = await maintenance.close_admission(
        operation_id=first_operation,
        expected_generation=1,
        reason="first owner closure",
        session_factory=db.sessions,
    )
    current = await maintenance.close_admission(
        operation_id=current_operation,
        expected_generation=first.generation,
        reason="superseding owner closure",
        session_factory=db.sessions,
    )
    assert current.generation == 3 and current.status == "closed"
    before = await db.read_row()
    for operation, generation in (
        (first_operation, first.generation),
        (first_operation, current.generation),
        (current_operation, first.generation),
    ):
        with pytest.raises(maintenance.HostMaintenanceConflict):
            await maintenance.open_admission(
                operation_id=operation,
                expected_generation=generation,
                reason="stale or wrong-operation reopen",
                session_factory=db.sessions,
            )
        assert await db.read_row() == before

    opened = await maintenance.open_admission(
        operation_id=current_operation,
        expected_generation=current.generation,
        reason="current owner operation completed",
        session_factory=db.sessions,
    )
    assert opened.is_open and opened.generation == 4
    for generation in (current.generation, opened.generation):
        with pytest.raises(maintenance.HostMaintenanceConflict):
            await maintenance.open_admission(
                operation_id=current_operation,
                expected_generation=generation,
                reason="replay must not silently reopen",
                session_factory=db.sessions,
            )
    async with db.sessions() as session:
        assert (await maintenance.require_admission_open(session)).generation == 4


@pytest.mark.asyncio
async def test_missing_authority_never_seeds_itself_or_admits(maintenance_db):
    db = maintenance_db
    async with db.sessions() as session:
        await session.execute(
            delete(OwnerControlRecord).where(OwnerControlRecord.id == db.control_id)
        )
        await session.commit()
    async with db.sessions() as session:
        with pytest.raises(maintenance.HostMaintenanceUnavailable):
            await maintenance.require_admission_open(session)
        assert await maintenance.is_admission_open(session) is False
    with pytest.raises(maintenance.HostMaintenanceUnavailable):
        await maintenance.close_admission(
            operation_id=str(uuid4()),
            expected_generation=1,
            reason="missing authority must not be created",
            session_factory=db.sessions,
        )
    assert await db.read_row() is None
    async with db.sessions() as session:
        assert await session.scalar(
            select(OwnerControlRecord.id).where(
                OwnerControlRecord.domain == maintenance.DOMAIN,
                OwnerControlRecord.resource_id == db.resource_id,
            )
        ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "generation-string",
    "generation-boolean",
    "version-mismatch",
    "wrong-scope",
    "inconsistent-enabled",
    "unknown-status",
])
async def test_malformed_authority_stays_unavailable_without_mutation(maintenance_db, change):
    db = maintenance_db
    async with db.sessions() as session:
        row = await session.get(OwnerControlRecord, db.control_id)
        payload = deepcopy(row.payload)
        if change == "generation-string":
            payload["generation"] = "1"
        elif change == "generation-boolean":
            payload["generation"] = True
        elif change == "version-mismatch":
            row.version = 9
        elif change == "wrong-scope":
            payload["scope"] = "another-scope"
        elif change == "inconsistent-enabled":
            row.enabled = False
        else:
            row.status = "unknown"
        row.payload = payload
        # Python JSON equality treats True == 1; force the malformed boolean
        # to PostgreSQL instead of silently retaining the valid integer seed.
        flag_modified(row, "payload")
        await session.commit()
    before = await db.read_row()
    if change == "generation-boolean":
        assert before["payload"]["generation"] is True
    async with db.sessions() as session:
        with pytest.raises(maintenance.HostMaintenanceUnavailable):
            await maintenance.require_admission_open(session)
        assert await maintenance.is_admission_open(session) is False
    with pytest.raises(maintenance.HostMaintenanceUnavailable):
        await maintenance.close_admission(
            operation_id=str(uuid4()),
            expected_generation=1,
            reason="malformed authority stays blocked",
            session_factory=db.sessions,
        )
    assert await db.read_row() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [True, False])
async def test_expiry_field_never_autoopens_a_closed_generation(maintenance_db, expired):
    db = maintenance_db
    closed = await maintenance.close_admission(
        operation_id=str(uuid4()),
        expected_generation=1,
        reason="closure with no automatic expiry",
        session_factory=db.sessions,
    )
    async with db.sessions() as session:
        row = await session.get(OwnerControlRecord, db.control_id)
        expiry = datetime.now(UTC) + timedelta(days=-1 if expired else 1)
        row.payload = {**row.payload, "expires_at": expiry.isoformat()}
        await session.commit()
    before = await db.read_row()
    async with db.sessions() as session:
        with pytest.raises(maintenance.HostMaintenanceUnavailable):
            await maintenance.require_admission_open(session)
        assert await maintenance.is_admission_open(session) is False
    assert await db.read_row() == before
    assert before["status"] == "closed"
    assert before["enabled"] is False
    assert before["payload"]["generation"] == closed.generation


@pytest.mark.asyncio
async def test_database_exception_propagates_instead_of_becoming_admission_state(maintenance_db, monkeypatch):
    db = maintenance_db
    failure = OperationalError(
        "synthetic authority read",
        {},
        RuntimeError("synthetic disconnected PostgreSQL"),
    )
    async with db.sessions() as session:
        monkeypatch.setattr(session, "execute", AsyncMock(side_effect=failure))
        monkeypatch.setattr(session, "scalar", AsyncMock(side_effect=failure))
        with pytest.raises(OperationalError) as caught:
            await maintenance.is_admission_open(session)
        assert caught.value is failure
    assert (await db.read_row())["status"] == "open"


@pytest.mark.asyncio
async def test_committed_close_survives_later_callback_failure_and_caller_rollback(maintenance_db):
    db = maintenance_db
    operation_id = str(uuid4())
    with pytest.raises(RuntimeError, match="synthetic callback failure"):
        async with db.sessions() as caller:
            async with caller.begin():
                cached = await caller.get(OwnerControlRecord, db.control_id)
                assert cached.status == "open"
                closed = await maintenance.close_admission(
                    operation_id=operation_id,
                    expected_generation=1,
                    reason="commit authority before follow-up",
                    session_factory=db.sessions,
                )
                assert closed.status == "closed"
                raise RuntimeError("synthetic callback failure")
    async with db.sessions() as session:
        with pytest.raises(maintenance.HostMaintenanceClosed):
            await maintenance.require_admission_open(session)
        assert await maintenance.is_admission_open(session) is False
    stored = await db.read_row()
    assert stored["status"] == "closed" and stored["version"] == 2
    assert stored["payload"]["generation"] == 2
    assert stored["payload"]["operation_id"] == operation_id


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["close_admission", "open_admission"])
@pytest.mark.parametrize("invalid", [
    {"operation_id": "not-a-uuid"},
    {"operation_id": "A1234567-1234-4234-8234-123456789ABC"},
    {"expected_generation": 0},
    {"expected_generation": True},
    {"reason": ""},
    {"reason": "   "},
])
async def test_invalid_transition_arguments_fail_before_session_creation(method, invalid):
    def forbidden_factory():
        raise AssertionError("invalid transition opened a database session")

    values = {
        "operation_id": str(uuid4()),
        "expected_generation": 1,
        "reason": "synthetic valid reason",
        "session_factory": forbidden_factory,
    }
    values.update(invalid)
    with pytest.raises(ValueError):
        await getattr(maintenance, method)(**values)


@pytest.mark.asyncio
async def test_control_lock_timeout_preserves_open_generation_without_retry(maintenance_db, monkeypatch):
    db = maintenance_db
    monkeypatch.setattr(maintenance, "_CONTROL_LOCK_TIMEOUT", "100ms")
    before = await db.read_row()
    session_count = 0

    def counted_sessions():
        nonlocal session_count
        session_count += 1
        return db.sessions()

    async with db.sessions() as reader:
        try:
            admitted = await maintenance.require_admission_open(reader)
            assert admitted.is_open and admitted.generation == 1
            with pytest.raises(DBAPIError) as caught:
                await asyncio.wait_for(maintenance.close_admission(
                    operation_id=str(uuid4()),
                    expected_generation=1,
                    reason="bounded writer wait while admission owns a shared lock",
                    session_factory=counted_sessions,
                ), 5)
            original = caught.value.orig
            assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "55P03"
            assert session_count == 1
            assert reader.in_transaction()
            assert await db.read_row() == before
        finally:
            await reader.rollback()
    assert await db.read_row() == before
    async with db.sessions() as reader:
        assert (await maintenance.require_admission_open(reader)).is_open


def _run_seed_migration(sync_connection, direction):
    path = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "20260917_0047_host_maintenance_admission.py")
    spec = importlib.util.spec_from_file_location("maintenance_seed_test_" + uuid4().hex, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Bind the real migration to the caller's isolated schema, never the
    # disposable database's existing public singleton or Alembic version row.
    migration.op = Operations(MigrationContext.configure(sync_connection))
    getattr(migration, direction)()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["closed", "malformed"])
async def test_seed_migration_replay_and_downgrade_preserve_existing_authority(existing):
    engine = create_async_engine(_disposable_postgres_url(), poolclass=NullPool)
    schema = "maintenance_migration_" + uuid4().hex
    records = OwnerControlRecord.__table__
    created = False

    async def select_schema(connection):
        # A generated identifier is bound as a setting, and each transaction
        # omits public from search_path so unqualified migration writes stay here.
        await connection.execute(
            text("SELECT set_config('search_path', :schema, true)"), {"schema": schema}
        )

    async def migrate_and_read(direction):
        async with engine.begin() as connection:
            await select_schema(connection)
            await connection.run_sync(_run_seed_migration, direction)
            rows = (await connection.execute(select(records))).mappings().all()
            return [deepcopy(dict(row)) for row in rows]

    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            await select_schema(connection)
            await connection.run_sync(records.create)
        created = True
        initial = await migrate_and_read("upgrade")
        assert len(initial) == 1
        seeded = initial[0]
        assert seeded["domain"] == "host-maintenance-admission"
        assert seeded["resource_id"] == "runtime-node"
        assert seeded["status"] == "open" and seeded["enabled"] is True
        assert seeded["version"] == 1
        assert seeded["payload"] == {
            "schema_version": 1,
            "scope": "project_execution",
            "generation": 1,
            "operation_id": None,
            "reason": "migration-seed",
            "changed_at": None,
            "full_host_closure": False,
        }
        assert await migrate_and_read("upgrade") == initial

        payload = {
            **seeded["payload"],
            "generation": 7 if existing == "closed" else "malformed-generation",
            "operation_id": str(uuid4()),
            "reason": "existing authority must survive seed replay",
            "changed_at": datetime.now(UTC).isoformat(),
        }
        async with engine.begin() as connection:
            await select_schema(connection)
            await connection.execute(records.update().where(records.c.id == seeded["id"]).values(
                status="closed", enabled=False, version=7, payload=payload,
            ))
            before = [deepcopy(dict(row)) for row in
                      (await connection.execute(select(records))).mappings().all()]
        assert before[0]["status"] == "closed" and before[0]["enabled"] is False

        # Each migration invocation has a fresh, committed transaction; retain
        # every persisted field, including identity and both timestamps.
        for direction in ("upgrade", "downgrade", "upgrade"):
            assert await migrate_and_read(direction) == before
    finally:
        try:
            if created:
                async with engine.begin() as connection:
                    await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await engine.dispose()
