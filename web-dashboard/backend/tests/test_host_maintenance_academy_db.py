"""Real PostgreSQL contracts for Academy package maintenance ownership.

Each case owns a UUID schema. Production guards, predicates, registry operations,
migrations and PostgreSQL locks are exercised without worker or external I/O.
Only the root harness runs these tests against its verified disposable target.
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
from sqlalchemy import Column, ForeignKey, MetaData, String, Table, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.base import Base
from app.db.models import (
    AcademyCourse, AcademyCoursePackage, HostMaintenanceWorkCycle,
    Organization, OwnerControlRecord, Role, User,
)
from app.services import host_maintenance_academy as academy
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_cycles as backup_cycles


WAIT = 8
PACKAGES = AcademyCoursePackage.__table__
REGISTRY = HostMaintenanceWorkCycle.__table__
CONTROLS = OwnerControlRecord.__table__


def _disposable_url():
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        pytest.fail("Academy PostgreSQL acceptance requires a disposable DATABASE_URL")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("Academy PostgreSQL acceptance requires the isolated asyncpg harness")
    if re.search(
        r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)",
        (url.database or "").lower(),
    ) is None:
        pytest.fail("Academy acceptance refuses a database without a delimited test marker")
    return url


def _run_migration(connection, revision, direction):
    directory = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    paths = list(directory.glob(f"*_{revision}_*.py"))
    assert len(paths) == 1
    spec = importlib.util.spec_from_file_location("academy_migration_" + uuid4().hex, paths[0])
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, direction)()


def _package_tables():
    tables = {PACKAGES, CONTROLS}
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return list(tables)
        tables = expanded


class _LockProbeSession(AsyncSession):
    async def _before(self, statement):
        lock = getattr(statement, "_for_update_arg", None)
        probe = self.info.get("academy_lock_probe")
        if lock is None or probe is None or self.info.get("academy_probe_seen"):
            return None
        self.info["academy_probe_seen"] = True
        pid = int(await AsyncSession.scalar(self, text("SELECT pg_backend_pid()")))
        observed = (pid, bool(lock.read))
        probe.started.put_nowait(observed)
        return observed

    async def _after(self, observed):
        if observed is not None:
            probe = self.info["academy_lock_probe"]
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
async def academy_db(request):
    url = _disposable_url()
    schema = "maintenance_academy_" + uuid4().hex
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    organization_ids = (str(uuid4()), str(uuid4()))
    user_id, role_id = str(uuid4()), str(uuid4())

    async def migrate(revision="0049", direction="upgrade"):
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

    async def package_row(package_id):
        async with sessions() as session:
            row = (await session.execute(
                select(PACKAGES).where(PACKAGES.c.id == package_id)
            )).mappings().one_or_none()
            return deepcopy(dict(row)) if row is not None else None

    async def new_package(*, organization_id=None, **changes):
        organization_id = organization_id or organization_ids[0]
        course_id, package_id = str(uuid4()), str(uuid4())
        async with sessions() as session:
            session.add(AcademyCourse(
                id=course_id, organization_id=organization_id,
                code="acceptance-" + uuid4().hex, title="Isolated Academy Course",
            ))
            await session.flush()
            values = dict(
                id=package_id, organization_id=organization_id, course_id=course_id,
                idempotency_key=str(uuid4()), status="queued", version=1,
                lesson_count=0, request_payload={}, curriculum={}, citations=[],
                review={}, archive_bytes=0,
            )
            values.update(changes)
            session.add(AcademyCoursePackage(**values))
            await session.commit()
        return package_id

    async def update_package(package_id, **values):
        async with sessions() as session:
            await session.execute(
                PACKAGES.update().where(PACKAGES.c.id == package_id).values(**values)
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
            reason="isolated academy closure", session_factory=session_factory or sessions,
        )

    async def snapshot(closed):
        async with sessions() as session:
            return await academy.snapshot_academy_activities(
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
            info={"academy_lock_probe": probe},
        )
        return factory, probe

    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT current_schema()")) == schema
            await connection.run_sync(
                lambda connection: Base.metadata.create_all(connection, tables=_package_tables())
            )
        await migrate("0047")
        await migrate("0048")
        if getattr(request, "param", "academy") != "schema2":
            await migrate()
        async with sessions() as session:
            for identity in organization_ids:
                session.add(Organization(
                    id=identity, name="Isolated Academy Organization",
                    slug="academy-" + identity,
                ))
            await session.flush()
            session.add(Role(id=role_id, organization_id=organization_ids[0], name="Owner"))
            await session.flush()
            session.add(User(
                id=user_id, organization_id=organization_ids[0], role_id=role_id,
                name="Isolated Academy Reviewer", email=user_id + "@example.test",
                password_hash="synthetic-unused-hash",
            ))
            await session.commit()
        yield SimpleNamespace(
            engine=engine, sessions=sessions, migrate=migrate,
            authority_row=authority_row, registry_rows=registry_rows,
            package_row=package_row, new_package=new_package,
            update_package=update_package, update_authority=update_authority,
            organization_ids=organization_ids, user_id=user_id,
            close=close, snapshot=snapshot, probed_sessions=probed_sessions,
        )
    finally:
        await engine.dispose()
        try:
            if created:
                async with administration.begin() as connection:
                    await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await administration.dispose()


async def _claim(db, package_id=None, *, session_factory=None):
    package_id = package_id or await db.new_package()
    async with (session_factory or db.sessions)() as session:
        await academy.require_academy_admission(session)
        ownership = await academy.register_academy_activity(
            session, package_id=package_id, worker_incarnation=str(uuid4()),
        )
        await session.execute(
            PACKAGES.update().where(PACKAGES.c.id == package_id).values(status="building")
        )
        await session.flush()
        await session.commit()
        return ownership


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
async def test_registration_and_building_share_one_transaction_until_close_can_win(academy_db, outcome):
    db = academy_db
    package_id = await db.new_package()
    registered, release = asyncio.Event(), asyncio.Event()
    claim_factory, claim_probe = db.probed_sessions()
    close_factory, close_probe = db.probed_sessions()
    claimant = closer = None

    async def claim_until_released():
        async with claim_factory() as session:
            await academy.require_academy_admission(session)
            owned = await academy.register_academy_activity(
                session, package_id=package_id, worker_incarnation=str(uuid4()),
            )
            await session.execute(
                PACKAGES.update().where(PACKAGES.c.id == package_id).values(status="building")
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
        # Both writes are still invisible to another connection. register must
        # not commit either an activity or a partly completed package claim.
        assert await db.registry_rows() == []
        assert (await db.package_row(package_id))["status"] == "queued"
        closer = asyncio.create_task(db.close(
            expected_generation=3, session_factory=close_factory,
        ))
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
            if outcome == "commit":
                assert owned.admitted_generation == 3
                with pytest.raises((AttributeError, TypeError)):
                    owned.admitted_generation = 99
        closed = await asyncio.wait_for(closer, WAIT)
        measured = await db.snapshot(closed)
        if outcome == "commit":
            assert (await db.package_row(package_id))["status"] == "building"
            assert measured.unfinished_count == measured.blocker_count == 1
            assert not measured.is_clear
        else:
            assert await db.registry_rows() == []
            assert (await db.package_row(package_id))["status"] == "queued"
            assert measured.is_clear and package_id in measured.frozen_queued_ids
    finally:
        release.set()
        await _stop_task(claimant)
        await _stop_task(closer)


@pytest.mark.asyncio
async def test_close_first_rejects_waiting_registration_without_package_or_registry_mutation(academy_db):
    db = academy_db
    package_id = await db.new_package()
    close_factory, close_probe = db.probed_sessions(pause=True)
    claim_factory, claim_probe = db.probed_sessions()
    claimant = closer = None
    before = await db.package_row(package_id)
    try:
        closer = asyncio.create_task(db.close(
            expected_generation=3, session_factory=close_factory,
        ))
        close_pid, shared = await asyncio.wait_for(close_probe.started.get(), WAIT)
        assert shared is False
        await asyncio.wait_for(close_probe.acquired.wait(), WAIT)
        claimant = asyncio.create_task(_claim(db, package_id, session_factory=claim_factory))
        claim_pid, shared = await asyncio.wait_for(claim_probe.started.get(), WAIT)
        assert shared is True
        await _await_blocked(db.sessions, claim_pid, close_pid)
        close_probe.release.set()
        await asyncio.wait_for(closer, WAIT)
        with pytest.raises(admission.HostMaintenanceClosed):
            await asyncio.wait_for(claimant, WAIT)
        assert await db.registry_rows() == []
        assert await db.package_row(package_id) == before
    finally:
        close_probe.release.set()
        await _stop_task(claimant)
        await _stop_task(closer)


@pytest.mark.asyncio
async def test_actual_commit_failure_rolls_back_registration_and_building_together(academy_db):
    db = academy_db
    package_id = await db.new_package()
    tripwire = Table(
        "academy_commit_tripwire", MetaData(),
        Column("id", String(36), primary_key=True),
        Column("package_id", String(36), ForeignKey(
            PACKAGES.c.id, deferrable=True, initially="DEFERRED",
        ), nullable=False),
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(tripwire.create)

    def failing_sessions():
        session = db.sessions()

        def before_commit(sync_session):
            sync_session.execute(tripwire.insert().values(
                id=str(uuid4()), package_id=str(uuid4()),
            ))

        event.listen(session.sync_session, "before_commit", before_commit)
        return session

    with pytest.raises(IntegrityError) as caught:
        await _claim(db, package_id, session_factory=failing_sessions)
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23503"
    assert await db.registry_rows() == []
    assert (await db.package_row(package_id))["status"] == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [
    "schema1", "schema2", "closed", "missing", "malformed", "unknown", "database-error",
])
async def test_academy_registration_requires_current_coverage_and_fails_closed(academy_db, condition):
    db = academy_db
    package_id = await db.new_package()
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
                    "ALTER TABLE owner_control_records RENAME TO unavailable_academy_authority"
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
            elif condition == "malformed":
                payload["full_host_closure"] = True
            else:
                payload["schema_version"] = 99
            await db.update_authority(payload=payload)
    async with db.sessions() as session:
        with pytest.raises(expected) as caught:
            await academy.register_academy_activity(
                session, package_id=package_id, worker_incarnation=str(uuid4()),
            )
    if condition == "database-error":
        assert caught.value.__suppress_context__ is True
        assert "unavailable_academy_authority" not in str(caught.value)
        assert "SELECT" not in str(caught.value)
    assert await db.registry_rows() == []
    assert (await db.package_row(package_id))["status"] == "queued"


@pytest.mark.asyncio
async def test_admission_does_not_hide_unexpected_non_database_errors(academy_db, monkeypatch):
    failure = RuntimeError("synthetic non-database programming failure")
    async with academy_db.sessions() as session:
        monkeypatch.setattr(session, "execute", AsyncMock(side_effect=failure))
        with pytest.raises(RuntimeError) as caught:
            await academy.require_academy_admission(session)
        assert caught.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize("review", [{}, {"status": "pending", "approved": False}])
async def test_pristine_sql_and_python_allow_request_metadata_and_pending_review(academy_db, review):
    db = academy_db
    package_id = await db.new_package(
        lesson_count=3, citations=[{"url": "https://example.test/source"}],
        request_payload={"requested_lessons": 3}, review=review,
    )
    async with db.sessions() as session:
        row = (await session.execute(select(PACKAGES).where(PACKAGES.c.id == package_id))).mappings().one()
        model = await session.get(AcademyCoursePackage, package_id)
        assert academy.is_pristine_queued_package(row)
        assert academy.is_pristine_queued_package(model)
        assert await session.scalar(select(PACKAGES.c.id).where(
            PACKAGES.c.id == package_id, *academy.pristine_queued_package_conditions(PACKAGES),
        )) == package_id
    assert (await _claim(db, package_id)).package_id == package_id


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "error_code", "error_message", "completed_at", "reviewed_at", "reviewed_by_id",
    "site_relpath", "archive_relpath", "archive_sha256", "manifest_sha256",
    "archive_bytes", "curriculum", "review-extra", "review-numeric-false",
])
async def test_nonpristine_queue_is_rejected_by_both_predicates_and_registration(academy_db, field):
    db = academy_db
    values = {
        "error_code": {"error_code": "old-failure"},
        "error_message": {"error_message": "prior build did not settle"},
        "completed_at": {"completed_at": datetime.now(UTC)},
        "reviewed_at": {"reviewed_at": datetime.now(UTC)},
        "reviewed_by_id": {"reviewed_by_id": db.user_id},
        "site_relpath": {"site_relpath": "old/site"},
        "archive_relpath": {"archive_relpath": "old/archive.zip"},
        "archive_sha256": {"archive_sha256": "a" * 64},
        "manifest_sha256": {"manifest_sha256": "b" * 64},
        "archive_bytes": {"archive_bytes": 1},
        "curriculum": {"curriculum": {"stale": True}},
        "review-extra": {"review": {"status": "pending", "approved": False, "old": True}},
        "review-numeric-false": {"review": {"status": "pending", "approved": 0}},
    }[field]
    package_id = await db.new_package(**values)
    before = await db.package_row(package_id)
    async with db.sessions() as session:
        row = (await session.execute(select(PACKAGES).where(PACKAGES.c.id == package_id))).mappings().one()
        model = await session.get(AcademyCoursePackage, package_id)
        assert not academy.is_pristine_queued_package(row)
        assert not academy.is_pristine_queued_package(model)
        assert await session.scalar(select(PACKAGES.c.id).where(
            PACKAGES.c.id == package_id, *academy.pristine_queued_package_conditions(PACKAGES),
        )) is None
        with pytest.raises(academy.AcademyActivityOwnershipLost):
            await academy.register_academy_activity(
                session, package_id=package_id, worker_incarnation=str(uuid4()),
            )
    assert await db.registry_rows() == []
    assert await db.package_row(package_id) == before


@pytest.mark.asyncio
async def test_register_rechecks_database_row_instead_of_cached_pristine_orm(academy_db):
    db = academy_db
    package_id = await db.new_package()
    async with db.sessions() as session:
        cached = await session.get(AcademyCoursePackage, package_id)
        assert academy.is_pristine_queued_package(cached)
        await db.update_package(package_id, error_code="changed-by-another-transaction")
        with pytest.raises(academy.AcademyActivityOwnershipLost):
            await academy.register_academy_activity(
                session, package_id=package_id, worker_incarnation=str(uuid4()),
            )
        assert cached.error_code is None
    assert await db.registry_rows() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "activity_id", "package_id", "worker_incarnation", "admitted_generation", "ownership_nonce",
])
async def test_exact_identity_fences_public_mutations_and_terminal_finish(academy_db, field):
    db = academy_db
    owned, other = await _claim(db), await _claim(db)
    replacement = owned.admitted_generation + 1 if field == "admitted_generation" else getattr(other, field)
    forged = replace(owned, **{field: replacement})
    before = await db.registry_rows()
    async with db.sessions() as session:
        with pytest.raises(academy.AcademyActivityOwnershipLost):
            await academy.require_owned_academy_activity(session, forged)
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.heartbeat_academy_activity(forged, phase="forged", session_factory=db.sessions)
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.mark_academy_activity_unresolved(
            forged, reason="forged ownership", session_factory=db.sessions,
        )
    await db.update_package(owned.package_id, status="failed", completed_at=datetime.now(UTC))
    await db.update_package(other.package_id, status="failed", completed_at=datetime.now(UTC))
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.finish_academy_activity(forged, session_factory=db.sessions)
    assert await db.registry_rows() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["review_pending", "approved", "rejected", "failed"])
async def test_only_actual_terminal_package_allows_exact_active_finish_after_close_and_expiry(academy_db, terminal):
    db = academy_db
    owned = await _claim(db)
    closed = await db.close()
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.finish_academy_activity(owned, session_factory=db.sessions)
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    assert (await db.snapshot(closed)).expired_count == 1
    await db.update_package(owned.package_id, status=terminal, completed_at=datetime.now(UTC))
    await academy.finish_academy_activity(owned, session_factory=db.sessions)
    assert await db.registry_rows() == []
    measured = await db.snapshot(closed)
    assert measured.is_clear and measured.blocker_count == 0
    assert measured.coverage_unverified is True and measured.full_host_closure is False
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.finish_academy_activity(owned, session_factory=db.sessions)


@pytest.mark.asyncio
async def test_ambiguous_activity_remains_unresolved_after_expiry_terminal_status_and_close(academy_db):
    db = academy_db
    owned = await _claim(db)
    reason = "cancelled await with external publication outcome unknown"
    await academy.mark_academy_activity_unresolved(
        owned, reason=reason, session_factory=db.sessions,
    )
    await academy.mark_academy_activity_unresolved(
        owned, reason=reason, session_factory=db.sessions,
    )
    closed = await db.close()
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().where(
            REGISTRY.c.id == owned.activity_id
        ).values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    before = await db.registry_rows()
    async with db.sessions() as session:
        with pytest.raises(academy.AcademyActivityOwnershipLost):
            await academy.require_owned_academy_activity(session, owned)
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.heartbeat_academy_activity(owned, session_factory=db.sessions)
    await db.update_package(owned.package_id, status="failed", completed_at=datetime.now(UTC))
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.finish_academy_activity(owned, session_factory=db.sessions)
    assert await db.registry_rows() == before
    measured = await db.snapshot(closed)
    assert measured.unresolved_count == measured.blocker_count == 1
    assert measured.expired_count == 1
    assert not measured.is_clear


@pytest.mark.asyncio
async def test_family_snapshot_keeps_all_generations_and_deduplicates_legacy_blockers(academy_db):
    db = academy_db
    older = await _claim(db)
    closed_once = await db.close()
    reopened = await admission.open_admission(
        operation_id=closed_once.operation_id, expected_generation=closed_once.generation,
        reason="continue academy acceptance", session_factory=db.sessions,
    )
    newer = await _claim(db)
    assert {older.admitted_generation, newer.admitted_generation} == {3, reopened.generation}
    await academy.mark_academy_activity_unresolved(
        older, reason="unsettled old generation", session_factory=db.sessions,
    )
    # The active registry row remains a blocker even if a package is reset to
    # a stale queue; count that package once, never as a frozen pristine queue.
    await db.update_package(newer.package_id, status="queued", error_code="ambiguous-reset")
    legacy = await db.new_package(status="building", organization_id=db.organization_ids[1])
    stale_queue = await db.new_package(error_code="legacy-failure")
    unknown = await db.new_package(status="unrecognized-future-state")
    pristine = await db.new_package(lesson_count=2, request_payload={"lessons": 2})
    pending_review = await db.new_package(review={"status": "pending", "approved": False})
    backup_owner = await backup_cycles.begin_backup_cycle(
        worker_incarnation=str(uuid4()), session_factory=db.sessions,
    )
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().where(
            REGISTRY.c.consumer == academy.CONSUMER
        ).values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    closed = await db.close()
    before = await db.registry_rows()
    measured = await db.snapshot(closed)
    assert measured.unfinished_count == 2
    assert measured.active_count == measured.unresolved_count == 1
    assert measured.expired_count == 2
    assert {item.admitted_generation for item in measured.activities} == {3, reopened.generation}
    assert set(measured.unowned_building_ids) == {legacy}
    assert set(measured.unknown_status_ids) == {unknown}
    assert set(measured.nonpristine_queued_ids) == {newer.package_id, stale_queue}
    assert set(measured.frozen_queued_ids) == {pristine, pending_review}
    assert measured.blocker_count == 5 and not measured.is_clear
    assert measured.coverage_unverified is True and measured.full_host_closure is False
    encoded = json.dumps(asdict(measured), default=str)
    assert "ownership_nonce" not in encoded
    assert older.ownership_nonce not in encoded
    assert older.ownership_nonce not in repr(older)
    assert newer.ownership_nonce not in repr(measured)
    assert all(not hasattr(item, "ownership_nonce") for item in measured.activities)
    assert await db.registry_rows() == before
    async with db.sessions() as session:
        backup_snapshot = await backup_cycles.snapshot_backup_cycles(
            session, operation_id=closed.operation_id, expected_generation=closed.generation,
        )
    assert {item.cycle_id for item in backup_snapshot.cycles} == {backup_owner.cycle_id}


@pytest.mark.asyncio
async def test_existing_unfinished_activity_prevents_readoption_and_unique_index_enforces_it(academy_db):
    db = academy_db
    owned = await _claim(db)
    await db.update_package(owned.package_id, status="queued")
    before = await db.registry_rows()
    async with db.sessions() as session:
        with pytest.raises(academy.AcademyActivityOwnershipLost):
            await academy.register_academy_activity(
                session, package_id=owned.package_id, worker_incarnation=str(uuid4()),
            )
    duplicate = {**before[0], "id": str(uuid4()), "ownership_nonce": str(uuid4())}
    async with db.sessions() as session:
        with pytest.raises(IntegrityError) as caught:
            await session.execute(REGISTRY.insert().values(**duplicate))
            await session.commit()
        await session.rollback()
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23505"
    assert await db.registry_rows() == before
    closed = await db.close()
    measured = await db.snapshot(closed)
    assert owned.package_id not in measured.frozen_queued_ids
    assert measured.blocker_count == 1


@pytest.mark.asyncio
async def test_package_deletion_cannot_cascade_away_unfinished_ownership(academy_db):
    db = academy_db
    owned = await _claim(db)
    before = await db.registry_rows()
    async with db.sessions() as session:
        await session.execute(PACKAGES.delete().where(PACKAGES.c.id == owned.package_id))
        await session.commit()
    assert await db.registry_rows() == before
    with pytest.raises(academy.AcademyActivityOwnershipLost):
        await academy.finish_academy_activity(owned, session_factory=db.sessions)
    closed = await db.close()
    assert (await db.snapshot(closed)).blocker_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("academy_db", ["schema2"], indirect=True)
@pytest.mark.parametrize("state", ["open", "closed"])
async def test_0049_advances_only_coverage_generation_and_retains_backup_ownership(academy_db, state):
    db = academy_db
    backup_owner = await backup_cycles.begin_backup_cycle(
        worker_incarnation=str(uuid4()), session_factory=db.sessions,
    )
    if state == "closed":
        await db.close()
    before = await db.authority_row()
    registry_before = await db.registry_rows()
    await db.migrate()
    after = await db.authority_row()
    assert after["id"] == before["id"]
    assert after["status"] == before["status"] and after["enabled"] == before["enabled"]
    assert after["version"] == before["version"] + 1
    payload = after["payload"]
    assert payload["schema_version"] == admission.ACADEMY_SCHEMA_VERSION == 3
    assert payload["scope"] == admission.ACADEMY_COVERAGE_SCOPE == (
        "project_execution+backup_cycles+academy_course_packages"
    )
    assert payload["generation"] == after["version"]
    for field in ("operation_id", "reason", "changed_at", "full_host_closure"):
        assert payload[field] == before["payload"][field]
    assert await db.registry_rows() == registry_before
    for direction in ("upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.authority_row() == after
        assert await db.registry_rows() == registry_before
    with pytest.raises(admission.HostMaintenanceConflict):
        await admission.close_admission(
            operation_id=str(uuid4()), expected_generation=before["version"],
            reason="stale pre-upgrade CAS", session_factory=db.sessions,
        )
    if state == "closed":
        with pytest.raises(admission.HostMaintenanceConflict):
            await admission.open_admission(
                operation_id=before["payload"]["operation_id"],
                expected_generation=before["version"],
                reason="stale pre-upgrade reopen", session_factory=db.sessions,
            )
        await admission.open_admission(
            operation_id=after["payload"]["operation_id"],
            expected_generation=after["version"],
            reason="current covered generation reopen", session_factory=db.sessions,
        )
    async with db.sessions() as session:
        assert (await admission.require_admission_open(session)).is_open
        assert (await admission.require_admission_open(session, required_scope="backup_cycles")).is_open
        assert (await academy.require_academy_admission(session)).is_open
    await backup_cycles.finish_backup_cycle(backup_owner, session_factory=db.sessions)
    assert await db.registry_rows() == []
    assert (await _claim(db)).package_id


@pytest.mark.asyncio
@pytest.mark.parametrize("academy_db", ["schema2"], indirect=True)
@pytest.mark.parametrize("state", ["missing", "malformed", "unknown", "schema1", "already3"])
async def test_0049_retains_unupgradeable_authority_and_never_repairs_or_reopens_it(academy_db, state):
    db = academy_db
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
        else:
            payload.update(
                schema_version=3,
                scope="project_execution+backup_cycles+academy_course_packages",
                generation=8, operation_id=str(uuid4()), reason="already covered closure",
                changed_at=datetime.now(UTC).isoformat(),
            )
            await db.update_authority(status="closed", enabled=False, version=8)
        await db.update_authority(payload=payload)
    preserved = await db.authority_row()
    for direction in ("upgrade", "upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.authority_row() == preserved


@pytest.mark.asyncio
async def test_0049_replay_and_downgrade_preserve_active_and_unresolved_academy_rows(academy_db):
    db = academy_db
    await _claim(db)
    uncertain = await _claim(db)
    await academy.mark_academy_activity_unresolved(
        uncertain, reason="preserve unresolved through migration replay", session_factory=db.sessions,
    )
    closed = await db.close()
    before, authority_before = await db.registry_rows(), await db.authority_row()
    for direction in ("upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.registry_rows() == before
        assert await db.authority_row() == authority_before
    measured = await db.snapshot(closed)
    assert measured.active_count == measured.unresolved_count == 1
    assert measured.blocker_count == 2 and not measured.is_clear
