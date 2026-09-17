"""Real PostgreSQL acceptance for unfinished backup-cycle ownership.

Every database case owns a UUID schema in an explicitly disposable database.
The authority, registry, locks, CAS transitions, and migrations are real. Session
probes only pause real locking SELECTs; no production singleton is modified.
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
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, ForeignKey, MetaData, String, Table, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.models import HostMaintenanceWorkCycle, OwnerControlRecord
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_cycles as cycles


def _disposable_postgres_url():
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        pytest.fail("Cycle acceptance requires a disposable PostgreSQL DATABASE_URL")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("Cycle acceptance requires the isolated asyncpg PostgreSQL harness")
    name = (url.database or "").lower()
    if re.search(r"(?:^|_)(?:test|pytest|ci|smoke|disposable)(?:_|$)", name) is None:
        pytest.fail("Cycle acceptance refuses a database without a delimited test marker")
    return url


def _run_migration(connection, revision, direction="upgrade"):
    directory = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    matches = list(directory.glob(f"*_{revision}_*.py"))
    assert len(matches) == 1, "Expected exactly one tracked admission migration"
    spec = importlib.util.spec_from_file_location("cycle_migration_" + uuid4().hex, matches[0])
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, direction)()


class _LockProbeSession(AsyncSession):
    """Observe a real FOR SHARE/FOR UPDATE and optionally pause after acquisition."""

    async def _before_lock(self, statement):
        lock = getattr(statement, "_for_update_arg", None)
        probe = self.info.get("cycle_lock_probe")
        if lock is None or probe is None or self.info.get("cycle_probe_seen"):
            return None
        self.info["cycle_probe_seen"] = True
        pid = await AsyncSession.scalar(self, text("SELECT pg_backend_pid()"))
        observed = (int(pid), bool(lock.read))
        probe.started.put_nowait(observed)
        return observed

    async def _after_lock(self, observed):
        if observed is not None:
            probe = self.info["cycle_lock_probe"]
            probe.acquired.set()
            if probe.pause:
                await probe.release.wait()

    async def execute(self, statement, *args, **kwargs):
        observed = await self._before_lock(statement)
        result = await super().execute(statement, *args, **kwargs)
        await self._after_lock(observed)
        return result

    async def scalar(self, statement, *args, **kwargs):
        observed = await self._before_lock(statement)
        result = await super().scalar(statement, *args, **kwargs)
        await self._after_lock(observed)
        return result


@pytest_asyncio.fixture
async def cycle_db(request):
    url = _disposable_postgres_url()
    schema = "maintenance_cycles_" + uuid4().hex
    admin_engine = create_async_engine(url, poolclass=NullPool)
    # Restrict EVERY connection, including independent control transactions and
    # migration binds, to this schema. There is deliberately no public fallback.
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    controls = OwnerControlRecord.__table__
    registry = HostMaintenanceWorkCycle.__table__

    async def migrate(revision="0048", direction="upgrade"):
        async with engine.begin() as connection:
            await connection.run_sync(_run_migration, revision, direction)

    async def authority_row():
        async with sessions() as session:
            rows = (await session.execute(select(controls))).mappings().all()
            assert len(rows) <= 1
            return deepcopy(dict(rows[0])) if rows else None

    async def registry_rows():
        async with sessions() as session:
            rows = (await session.execute(select(registry).order_by(registry.c.id))).mappings().all()
            return [deepcopy(dict(row)) for row in rows]

    async def update_authority(**values):
        async with sessions() as session:
            await session.execute(controls.update().values(**values))
            await session.commit()

    async def snapshot(closed):
        async with sessions() as session:
            return await cycles.snapshot_backup_cycles(
                session,
                operation_id=closed.operation_id,
                expected_generation=closed.generation,
            )

    async def close(*, expected_generation=None, operation_id=None, session_factory=None):
        if expected_generation is None:
            expected_generation = (await authority_row())["version"]
        return await admission.close_admission(
            operation_id=operation_id or str(uuid4()),
            expected_generation=expected_generation,
            reason="isolated cycle acceptance closure",
            session_factory=session_factory or sessions,
        )

    def probed_sessions(*, pause=False):
        probe = SimpleNamespace(
            started=asyncio.Queue(),
            acquired=asyncio.Event(),
            release=asyncio.Event(),
            pause=pause,
        )
        factory = async_sessionmaker(
            engine,
            class_=_LockProbeSession,
            expire_on_commit=False,
            info={"cycle_lock_probe": probe},
        )
        return factory, probe

    try:
        async with admin_engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT current_schema()")) == schema
            await connection.run_sync(controls.create)
        await migrate("0047")
        if getattr(request, "param", "covered") != "legacy":
            await migrate()
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            registry=registry,
            controls=controls,
            migrate=migrate,
            authority_row=authority_row,
            registry_rows=registry_rows,
            update_authority=update_authority,
            snapshot=snapshot,
            close=close,
            probed_sessions=probed_sessions,
        )
    finally:
        await engine.dispose()
        try:
            if created:
                async with admin_engine.begin() as connection:
                    await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await admin_engine.dispose()


async def _await_blocked(sessions, pid, blocker, *, timeout=5):
    deadline = asyncio.get_running_loop().time() + timeout
    async with sessions() as observer:
        while asyncio.get_running_loop().time() < deadline:
            blockers = await observer.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
            )
            if blocker in (blockers or []):
                return
            await asyncio.sleep(0.01)
    pytest.fail("Expected real PostgreSQL lock wait was not observed")


async def _stop_task(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _begin(db, **kwargs):
    return await cycles.begin_backup_cycle(
        worker_incarnation=kwargs.pop("worker_incarnation", str(uuid4())),
        session_factory=kwargs.pop("session_factory", db.sessions),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_begin_commits_owned_cycle_before_waiting_close_can_acquire_authority(cycle_db):
    db = cycle_db
    begin_factory, begin_probe = db.probed_sessions(pause=True)
    close_factory, close_probe = db.probed_sessions(pause=True)
    beginning = closing = None
    try:
        beginning = asyncio.create_task(_begin(db, session_factory=begin_factory))
        begin_pid, shared = await asyncio.wait_for(begin_probe.started.get(), 5)
        assert shared is True
        await asyncio.wait_for(begin_probe.acquired.wait(), 5)
        closing = asyncio.create_task(db.close(
            expected_generation=2, session_factory=close_factory,
        ))
        close_pid, shared = await asyncio.wait_for(close_probe.started.get(), 5)
        assert shared is False
        await _await_blocked(db.sessions, close_pid, begin_pid)
        assert not closing.done()
        assert await db.registry_rows() == []
        begin_probe.release.set()
        ownership = await asyncio.wait_for(beginning, 5)
        await asyncio.wait_for(close_probe.acquired.wait(), 5)
        # The exclusive closer now holds authority. Ownership must already be
        # committed and visible from another connection, not merely in memory.
        rows = await db.registry_rows()
        assert len(rows) == 1 and rows[0]["id"] == ownership.cycle_id
        assert ownership.admitted_generation == 2
        assert rows[0]["admitted_generation"] == ownership.admitted_generation
        assert rows[0]["ownership_nonce"] == ownership.ownership_nonce
        with pytest.raises((AttributeError, TypeError)):
            ownership.admitted_generation = 99
        close_probe.release.set()
        closed = await asyncio.wait_for(closing, 5)
        measured = await db.snapshot(closed)
        assert measured.unfinished_count == 1 and not measured.is_clear
    finally:
        begin_probe.release.set()
        close_probe.release.set()
        await _stop_task(beginning)
        await _stop_task(closing)


@pytest.mark.asyncio
async def test_close_first_makes_waiting_cycle_begin_fail_without_any_registry_row(cycle_db):
    db = cycle_db
    close_factory, close_probe = db.probed_sessions(pause=True)
    begin_factory, begin_probe = db.probed_sessions()
    closing = beginning = None
    try:
        closing = asyncio.create_task(db.close(
            expected_generation=2, session_factory=close_factory,
        ))
        close_pid, shared = await asyncio.wait_for(close_probe.started.get(), 5)
        assert shared is False
        await asyncio.wait_for(close_probe.acquired.wait(), 5)
        beginning = asyncio.create_task(_begin(db, session_factory=begin_factory))
        begin_pid, shared = await asyncio.wait_for(begin_probe.started.get(), 5)
        assert shared is True
        await _await_blocked(db.sessions, begin_pid, close_pid)
        assert not beginning.done()
        close_probe.release.set()
        closed = await asyncio.wait_for(closing, 5)
        with pytest.raises(admission.HostMaintenanceClosed):
            await asyncio.wait_for(beginning, 5)
        assert await db.registry_rows() == []
        assert (await db.snapshot(closed)).is_clear
    finally:
        close_probe.release.set()
        await _stop_task(beginning)
        await _stop_task(closing)


@pytest.mark.asyncio
async def test_begin_real_deferred_commit_failure_returns_no_ownership_and_rolls_back(cycle_db):
    db = cycle_db
    # A deferred FK fails at the actual PostgreSQL COMMIT, after the cycle row
    # was inserted. This does not substitute a simulated begin or commit method.
    tripwire = Table(
        "cycle_commit_tripwire",
        MetaData(),
        Column("id", String(36), primary_key=True),
        Column("cycle_id", String(36), ForeignKey(
            db.registry.c.id, deferrable=True, initially="DEFERRED",
        ), nullable=False),
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(tripwire.create)
    attempts = []

    def failing_sessions():
        session = db.sessions()

        def before_commit(sync_session):
            attempts.append(True)
            sync_session.execute(tripwire.insert().values(
                id=str(uuid4()), cycle_id=str(uuid4()),
            ))

        event.listen(session.sync_session, "before_commit", before_commit)
        return session

    with pytest.raises(IntegrityError) as caught:
        await _begin(db, session_factory=failing_sessions)
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23503"
    assert attempts == [True]
    assert await db.registry_rows() == []
    assert (await db.authority_row())["version"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", [
    "closed", "missing", "legacy-only", "malformed-generation",
    "wrong-scope", "unknown-schema", "full-host-claim",
])
async def test_backup_begin_fails_closed_for_unavailable_or_uncovered_authority(cycle_db, authority):
    db = cycle_db
    expected_error = admission.HostMaintenanceUnavailable
    if authority == "closed":
        await db.close()
        expected_error = admission.HostMaintenanceClosed
    elif authority == "missing":
        async with db.sessions() as session:
            await session.execute(db.controls.delete())
            await session.commit()
    else:
        before = await db.authority_row()
        payload = deepcopy(before["payload"])
        if authority == "legacy-only":
            payload = {
                "schema_version": 1, "scope": "project_execution", "generation": 1,
                "operation_id": None, "reason": "migration-seed",
                "changed_at": None, "full_host_closure": False,
            }
            await db.update_authority(payload=payload, version=1)
        else:
            if authority == "malformed-generation":
                payload["generation"] = True
            elif authority == "wrong-scope":
                payload["scope"] = "uncovered-backup"
            elif authority == "unknown-schema":
                payload["schema_version"] = 99
            else:
                payload["full_host_closure"] = True
            await db.update_authority(payload=payload)
    before = await db.authority_row()
    with pytest.raises(expected_error):
        await _begin(db)
    assert await db.registry_rows() == []
    assert await db.authority_row() == before
    if authority == "legacy-only":
        async with db.sessions() as session:
            assert (await admission.require_admission_open(session)).is_open


@pytest.mark.asyncio
async def test_snapshot_counts_all_generations_expired_active_and_unresolved_without_repair(cycle_db):
    db = cycle_db
    older = await _begin(db)
    first_close = await db.close()
    reopened = await admission.open_admission(
        operation_id=first_close.operation_id,
        expected_generation=first_close.generation,
        reason="continue isolated acceptance generation",
        session_factory=db.sessions,
    )
    newer = await _begin(db)
    assert older.admitted_generation == 2
    assert newer.admitted_generation == reopened.generation == 4
    await cycles.mark_backup_cycle_unresolved(
        older, reason="external worker outcome remains unknown", session_factory=db.sessions,
    )
    expired = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(db.registry.update().values(
            started_at=expired - timedelta(minutes=5),
            heartbeat_at=expired - timedelta(minutes=2),
            lease_expires_at=expired,
        ))
        await session.commit()
    closed = await db.close()
    before = await db.registry_rows()
    measured = await db.snapshot(closed)
    assert measured.authority.generation == 5
    assert measured.active_count == 1 and measured.unresolved_count == 1
    assert measured.expired_count == 2 and measured.unfinished_count == 2
    assert {row.admitted_generation for row in measured.cycles} == {2, 4}
    assert {row.cycle_id for row in measured.cycles} == {older.cycle_id, newer.cycle_id}
    assert not measured.is_clear and measured.full_host_closure is False
    assert measured.coverage_unverified is True
    assert measured.observed_at.utcoffset() is not None
    again = await db.snapshot(closed)
    assert again.unfinished_count == 2 and again.expired_count == 2
    assert await db.registry_rows() == before
    with pytest.raises(admission.HostMaintenanceClosed):
        await _begin(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "cycle_id", "worker_incarnation", "admitted_generation", "ownership_nonce",
])
@pytest.mark.parametrize("method", ["heartbeat", "unresolved", "finish"])
async def test_forged_identity_cannot_mutate_or_delete_any_owned_cycle(cycle_db, field, method):
    db = cycle_db
    owned = await _begin(db)
    other = await _begin(db)
    forged_value = (
        owned.admitted_generation + 1
        if field == "admitted_generation" else getattr(other, field)
    )
    forged = replace(owned, **{field: forged_value})
    before = await db.registry_rows()
    with pytest.raises(cycles.CycleOwnershipLost):
        if method == "heartbeat":
            await cycles.heartbeat_backup_cycle(
                forged, phase="forged", session_factory=db.sessions,
            )
        elif method == "unresolved":
            await cycles.mark_backup_cycle_unresolved(
                forged, reason="forged ownership", session_factory=db.sessions,
            )
        else:
            await cycles.finish_backup_cycle(forged, session_factory=db.sessions)
    assert await db.registry_rows() == before


@pytest.mark.asyncio
async def test_nonce_is_absent_from_ownership_repr_and_snapshot_observations(cycle_db):
    db = cycle_db
    owned = await _begin(db)
    assert owned.ownership_nonce not in repr(owned)
    closed = await db.close()
    measured = await db.snapshot(closed)
    encoded = json.dumps(asdict(measured), default=str)
    assert "ownership_nonce" not in encoded
    assert owned.ownership_nonce not in encoded
    assert owned.ownership_nonce not in repr(measured)
    assert all(not hasattr(row, "ownership_nonce") for row in measured.cycles)


@pytest.mark.asyncio
async def test_existing_owner_can_heartbeat_and_finish_after_close_without_reopening(cycle_db):
    db = cycle_db
    owned = await _begin(db)
    closed = await db.close()
    authority_before = await db.authority_row()
    job_id = str(uuid4())
    await cycles.heartbeat_backup_cycle(
        owned, phase="retention", job_id=job_id, session_factory=db.sessions,
    )
    row = (await db.registry_rows())[0]
    assert row["phase"] == "retention" and row["job_id"] == job_id
    assert row["state"] == "active"
    assert row["lease_expires_at"] > row["heartbeat_at"]
    await cycles.finish_backup_cycle(owned, session_factory=db.sessions)
    assert await db.registry_rows() == []
    measured = await db.snapshot(closed)
    assert measured.is_clear and measured.unfinished_count == 0
    assert measured.full_host_closure is False
    assert measured.coverage_unverified is True
    assert await db.authority_row() == authority_before
    with pytest.raises(cycles.CycleOwnershipLost):
        await cycles.finish_backup_cycle(owned, session_factory=db.sessions)


@pytest.mark.asyncio
async def test_diagnostic_expiry_does_not_take_ownership_away_or_delete_it(cycle_db):
    db = cycle_db
    completing = await _begin(db)
    continuing = await _begin(db)
    expired = datetime.now(UTC) - timedelta(days=30)
    async with db.sessions() as session:
        await session.execute(db.registry.update().values(
            started_at=expired - timedelta(minutes=5),
            heartbeat_at=expired - timedelta(minutes=2),
            lease_expires_at=expired,
        ))
        await session.commit()
    closed = await db.close()
    assert (await db.snapshot(closed)).expired_count == 2
    # Expiry neither revokes the active owner nor requires a new lease/claim.
    await cycles.finish_backup_cycle(completing, session_factory=db.sessions)
    measured = await db.snapshot(closed)
    assert measured.expired_count == 1 and measured.unfinished_count == 1
    await cycles.heartbeat_backup_cycle(
        continuing, phase="awaiting_thread_completion", session_factory=db.sessions,
    )
    measured = await db.snapshot(closed)
    assert measured.expired_count == 0 and measured.unfinished_count == 1
    assert measured.active_count == 1
    row = (await db.registry_rows())[0]
    assert row["id"] == continuing.cycle_id
    assert row["ownership_nonce"] == continuing.ownership_nonce


@pytest.mark.asyncio
async def test_unresolved_state_survives_heartbeat_and_exact_finish_cannot_remove_it(cycle_db):
    db = cycle_db
    owned = await _begin(db)
    reason = "cancelled await; external thread not yet joined"
    await cycles.mark_backup_cycle_unresolved(
        owned, reason=reason, session_factory=db.sessions,
    )
    closed = await db.close()
    await cycles.heartbeat_backup_cycle(
        owned, phase="joining_external_thread", session_factory=db.sessions,
    )
    measured = await db.snapshot(closed)
    assert measured.unresolved_count == 1 and not measured.is_clear
    assert (await db.registry_rows())[0]["unresolved_reason"] == reason
    before = await db.registry_rows()
    with pytest.raises(cycles.CycleOwnershipLost):
        await cycles.finish_backup_cycle(owned, session_factory=db.sessions)
    assert await db.registry_rows() == before
    assert (await db.snapshot(closed)).unfinished_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["open", "wrong-operation", "stale-generation"])
async def test_snapshot_requires_exact_current_closed_authority(cycle_db, condition):
    db = cycle_db
    await _begin(db)
    if condition == "open":
        current = await db.authority_row()
        operation_id = current["payload"]["operation_id"]
        generation = current["version"]
    else:
        closed = await db.close()
        operation_id = str(uuid4()) if condition == "wrong-operation" else closed.operation_id
        generation = closed.generation - 1 if condition == "stale-generation" else closed.generation
    before = await db.registry_rows()
    async with db.sessions() as session:
        with pytest.raises(admission.HostMaintenanceConflict):
            await cycles.snapshot_backup_cycles(
                session, operation_id=operation_id, expected_generation=generation,
            )
    assert await db.registry_rows() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", ["worker-incarnation", "phase", "job-id", "future-generation"])
async def test_malformed_registry_row_cannot_be_reported_as_clear(cycle_db, malformed):
    db = cycle_db
    await _begin(db)
    closed = await db.close()
    values = {
        "worker-incarnation": {"worker_incarnation": "not-a-uuid"},
        "phase": {"phase": "   "},
        "job-id": {"job_id": "not-a-uuid"},
        "future-generation": {"admitted_generation": closed.generation + 1},
    }[malformed]
    async with db.sessions() as session:
        await session.execute(db.registry.update().values(**values))
        await session.commit()
    before = await db.registry_rows()
    async with db.sessions() as session:
        with pytest.raises(cycles.CycleRegistryUnavailable):
            await cycles.snapshot_backup_cycles(
                session, operation_id=closed.operation_id,
                expected_generation=closed.generation,
            )
    assert await db.registry_rows() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle_db", ["legacy"], indirect=True)
async def test_migration_upgrades_initial_seed_to_coverage_generation_two(cycle_db):
    db = cycle_db
    initial = await db.authority_row()
    assert initial["version"] == 1
    assert initial["payload"]["schema_version"] == 1
    await db.migrate()
    upgraded = await db.authority_row()
    payload = upgraded["payload"]
    assert upgraded["id"] == initial["id"]
    assert upgraded["status"] == "open" and upgraded["enabled"] is True
    assert upgraded["version"] == payload["generation"] == 2
    assert payload["schema_version"] == admission.COVERAGE_SCHEMA_VERSION == 2
    assert payload["scope"] == admission.COVERAGE_SCOPE == "project_execution+backup_cycles"
    assert str(UUID(payload["operation_id"])) == payload["operation_id"]
    assert payload["operation_id"] == "f96750f5-e078-48f2-858d-1fdf82acf270"
    assert payload["reason"] == "backup-cycle-coverage-migration"
    changed_at = datetime.fromisoformat(payload["changed_at"])
    assert changed_at.utcoffset() is not None
    assert payload["full_host_closure"] is False
    async with db.sessions() as session:
        project = await admission.require_admission_open(session)
        backup = await admission.require_admission_open(session, required_scope="backup_cycles")
        assert project.is_open and backup.is_open
        assert project.schema_version == backup.schema_version == 2
    assert (await _begin(db)).admitted_generation == 2
    await db.migrate()
    assert await db.authority_row() == upgraded


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle_db", ["legacy"], indirect=True)
async def test_migration_preserves_closed_operation_and_invalidates_stale_cas(cycle_db):
    db = cycle_db
    closed_legacy = await db.close(expected_generation=1)
    before = await db.authority_row()
    await db.migrate()
    upgraded = await db.authority_row()
    assert upgraded["status"] == "closed" and upgraded["enabled"] is False
    assert upgraded["version"] == closed_legacy.generation + 1
    assert upgraded["payload"]["operation_id"] == closed_legacy.operation_id
    assert upgraded["payload"]["reason"] == before["payload"]["reason"]
    assert upgraded["payload"]["changed_at"] == before["payload"]["changed_at"]
    assert upgraded["payload"]["schema_version"] == 2
    assert upgraded["payload"]["scope"] == "project_execution+backup_cycles"
    with pytest.raises(admission.HostMaintenanceConflict):
        await admission.open_admission(
            operation_id=closed_legacy.operation_id,
            expected_generation=closed_legacy.generation,
            reason="stale generation cannot undo coverage upgrade",
            session_factory=db.sessions,
        )
    assert await db.authority_row() == upgraded
    with pytest.raises(admission.HostMaintenanceClosed):
        await _begin(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle_db", ["legacy"], indirect=True)
@pytest.mark.parametrize("existing", ["missing", "malformed", "unknown-schema", "already-covered"])
async def test_migration_retains_missing_malformed_unknown_and_preupgraded_authority(cycle_db, existing):
    db = cycle_db
    before = await db.authority_row()
    payload = deepcopy(before["payload"])
    if existing == "missing":
        async with db.sessions() as session:
            await session.execute(db.controls.delete())
            await session.commit()
    else:
        if existing == "malformed":
            payload["generation"] = True
        elif existing == "unknown-schema":
            payload["schema_version"] = 99
        else:
            payload.update({
                "schema_version": 2,
                "scope": "project_execution+backup_cycles",
                "generation": 8,
                "operation_id": str(uuid4()),
                "reason": "preexisting covered closure",
                "changed_at": datetime.now(UTC).isoformat(),
            })
            await db.update_authority(status="closed", enabled=False, version=8)
        await db.update_authority(payload=payload)
    preserved = await db.authority_row()
    for direction in ("upgrade", "upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.authority_row() == preserved


@pytest.mark.asyncio
async def test_migration_replay_and_downgrade_retain_active_and_unresolved_registry_rows(cycle_db):
    db = cycle_db
    await _begin(db)
    unresolved = await _begin(db)
    await cycles.mark_backup_cycle_unresolved(
        unresolved, reason="retained across migration replay", session_factory=db.sessions,
    )
    closed = await db.close()
    before = await db.registry_rows()
    authority_before = await db.authority_row()
    for direction in ("upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.registry_rows() == before
        assert await db.authority_row() == authority_before
    measured = await db.snapshot(closed)
    assert measured.active_count == measured.unresolved_count == 1
    assert measured.unfinished_count == 2 and not measured.is_clear


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["state", "generation", "deadline"])
async def test_registry_constraints_reject_invalid_ownership_without_losing_blocker(cycle_db, invalid):
    db = cycle_db
    await _begin(db)
    closed = await db.close()
    before = await db.registry_rows()
    row = before[0]
    values = {
        "state": {"state": "finished"},
        "generation": {"admitted_generation": 0},
        "deadline": {"lease_expires_at": row["heartbeat_at"] - timedelta(seconds=1)},
    }[invalid]
    async with db.sessions() as session:
        with pytest.raises(IntegrityError) as caught:
            await session.execute(db.registry.update().values(**values))
            await session.commit()
        await session.rollback()
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23514"
    assert await db.registry_rows() == before
    assert (await db.snapshot(closed)).unfinished_count == 1
