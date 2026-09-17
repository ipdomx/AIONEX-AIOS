"""Real PostgreSQL contracts for durable remediation preparation ownership.

Each test owns a UUID schema in the root harness's disposable database. Claims,
business publication, locks, proof validation and migrations are real database
operations; these core tests never copy files or invoke external remediation.
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
    JSON, Column, DateTime, ForeignKey, Index, MetaData, String, Table, Text,
    event, select, text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.base import Base
from app.db.models import (
    AuditEvent, HostMaintenanceWorkCycle, NotificationDeliveryAttempt,
    Organization, OwnerControlRecord, Project, Role, SecurityFinding,
    SecurityRemediation, SecurityScan, SecurityTarget, User, Workspace,
)
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_cycles as backup_cycles
from app.services import host_maintenance_remediation as remediation


WAIT = 8
JOBS = SecurityRemediation.__table__
REGISTRY = HostMaintenanceWorkCycle.__table__
CONTROLS = OwnerControlRecord.__table__


def _disposable_url():
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        pytest.fail("Remediation PostgreSQL acceptance requires a disposable DATABASE_URL")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("Remediation acceptance requires the isolated asyncpg harness")
    if re.search(
        r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)",
        (url.database or "").lower(),
    ) is None:
        pytest.fail("Remediation acceptance refuses a database without a delimited test marker")
    return url


def _run_migration(connection, revision, direction):
    directory = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    paths = list(directory.glob(f"*_{revision}_*.py"))
    assert len(paths) == 1
    spec = importlib.util.spec_from_file_location("remediation_migration_" + uuid4().hex, paths[0])
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, direction)()


def _dependency_tables():
    # 0050 validates notification attempt evidence even in this remediation
    # fixture. Include its actual table and complete FK graph in our own schema.
    tables = {JOBS, CONTROLS, NotificationDeliveryAttempt.__table__, AuditEvent.__table__}
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return list(tables)
        tables = expanded


def _legacy_remediation_table():
    table = Table(
        "security_remediations", MetaData(),
        Column("id", String(36), primary_key=True),
        Column("organization_id", String(36), ForeignKey(Organization.__table__.c.id, ondelete="CASCADE"), nullable=False),
        Column("project_id", String(36), ForeignKey(Project.__table__.c.id, ondelete="SET NULL")),
        Column("finding_id", String(36), ForeignKey(SecurityFinding.__table__.c.id, ondelete="CASCADE"), nullable=False),
        Column("requested_by_id", String(36), ForeignKey(User.__table__.c.id, ondelete="SET NULL")),
        Column("status", String(32), nullable=False),
        Column("worktree_ref", Text),
        Column("plan", JSON, nullable=False),
        Column("regression_result", JSON, nullable=False),
        Column("retest_scan_id", String(36), ForeignKey(SecurityScan.__table__.c.id, ondelete="SET NULL")),
        Column("verified_fixed_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    Index("ix_security_remediations_org_status_created", table.c.organization_id, table.c.status, table.c.created_at)
    for name in ("organization_id", "project_id", "finding_id", "requested_by_id", "status", "retest_scan_id"):
        Index("ix_security_remediations_" + name, table.c[name])
    return table


class _LockProbeSession(AsyncSession):
    async def _before(self, statement):
        lock = getattr(statement, "_for_update_arg", None)
        probe = self.info.get("remediation_lock_probe")
        if lock is None or probe is None or self.info.get("remediation_probe_seen"):
            return None
        self.info["remediation_probe_seen"] = True
        pid = int(await AsyncSession.scalar(self, text("SELECT pg_backend_pid()")))
        observed = (pid, bool(lock.read))
        probe.started.put_nowait(observed)
        return observed

    async def _after(self, observed):
        if observed is not None:
            probe = self.info["remediation_lock_probe"]
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
async def remediation_db(request):
    url = _disposable_url()
    schema = "maintenance_remediation_" + uuid4().hex
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    legacy_jobs = _legacy_remediation_table()
    organization_ids = (str(uuid4()), str(uuid4()))
    user_ids = (str(uuid4()), str(uuid4()))
    workspace_ids = (str(uuid4()), str(uuid4()))
    created = False

    async def migrate(revision="0051", direction="upgrade"):
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

    async def remediation_row(remediation_id, *, legacy=False):
        table = legacy_jobs if legacy else JOBS
        async with sessions() as session:
            row = (await session.execute(
                select(table).where(table.c.id == remediation_id)
            )).mappings().one_or_none()
            return deepcopy(dict(row)) if row is not None else None

    async def new_remediation(*, organization_index=0, plan=None, source_snapshot=None, **changes):
        org_id = organization_ids[organization_index]
        user_id = user_ids[organization_index]
        project_id, target_id, scan_id, finding_id, remediation_id = (
            str(uuid4()) for _ in range(5)
        )
        now = datetime.now(UTC)
        async with sessions() as session:
            session.add(Project(
                id=project_id, organization_id=org_id,
                workspace_id=workspace_ids[organization_index], owner_id=user_id,
                name="Isolated Remediation Project", slug="remediation-" + project_id,
            ))
            await session.flush()
            metadata = {"environment": "isolated-acceptance"}
            if source_snapshot is not None:
                metadata["source_snapshot"] = str(source_snapshot)
            session.add(SecurityTarget(
                id=target_id, organization_id=org_id, project_id=project_id,
                created_by_id=user_id, kind="managed_project",
                origin="https://" + target_id + ".example.test",
                hostname=target_id + ".example.test", authorization_status="verified",
                verification_method="manual", target_metadata=metadata,
            ))
            await session.flush()
            session.add(SecurityScan(
                id=scan_id, organization_id=org_id, project_id=project_id,
                target_id=target_id, requested_by_id=user_id, profile="passive",
                status="completed", execution_mode="passive",
                started_at=now - timedelta(minutes=2), completed_at=now,
            ))
            await session.flush()
            session.add(SecurityFinding(
                id=finding_id, organization_id=org_id, scan_id=scan_id, target_id=target_id,
                source="isolated-acceptance", category="test-contract",
                title="Synthetic private finding", severity="low", state="verified",
                fingerprint=uuid4().hex + uuid4().hex,
                evidence={"private": "synthetic-private-finding"},
            ))
            await session.flush()
            values = dict(
                id=remediation_id, organization_id=org_id, project_id=project_id,
                finding_id=finding_id, requested_by_id=user_id, status="planned",
                worktree_ref=None, plan={"schema_version": 1} if plan is None else deepcopy(plan),
                regression_result={}, retest_scan_id=None, verified_fixed_at=None,
                created_at=now, updated_at=now,
            )
            values.update(changes)
            # Explicit legacy-compatible inserts work before and after0051.
            # New proof values are sent only by cases requesting those columns.
            await session.execute(JOBS.insert().values(**values))
            await session.commit()
        return remediation_id

    async def update_remediation(remediation_id, **values):
        async with sessions() as session:
            await session.execute(JOBS.update().where(JOBS.c.id == remediation_id).values(**values))
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
            reason="isolated remediation closure", session_factory=session_factory or sessions,
        )

    async def snapshot(closed):
        async with sessions() as session:
            return await remediation.read_remediation_activity_snapshot(
                session, operation_id=closed.operation_id, expected_generation=closed.generation,
            )

    def probed_sessions(*, pause=False):
        probe = SimpleNamespace(
            started=asyncio.Queue(), acquired=asyncio.Event(), release=asyncio.Event(), pause=pause,
        )
        factory = async_sessionmaker(
            engine, class_=_LockProbeSession, expire_on_commit=False,
            info={"remediation_lock_probe": probe},
        )
        return factory, probe

    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT current_schema()")) == schema
            if getattr(request, "param", None) == "latest-metadata":
                # Reproduce0001's current-metadata creation for every table in
                # the maintenance migration chain; root runs the full chain.
                tables = list(set(_dependency_tables()) | {REGISTRY})
                await connection.run_sync(
                    lambda connection: Base.metadata.create_all(connection, tables=tables)
                )
            else:
                tables = [table for table in _dependency_tables() if table is not JOBS]
                await connection.run_sync(
                    lambda connection: Base.metadata.create_all(connection, tables=tables)
                )
                await connection.run_sync(legacy_jobs.create)
        for revision in ("0047", "0048", "0049", "0050"):
            await migrate(revision)
        if getattr(request, "param", "remediation") != "schema4":
            await migrate()
        async with sessions() as session:
            for index, org_id in enumerate(organization_ids):
                role_id = str(uuid4())
                session.add(Organization(
                    id=org_id, name="Isolated Remediation Organization", slug="remediation-" + org_id,
                ))
                await session.flush()
                session.add(Role(id=role_id, organization_id=org_id, name="Owner"))
                session.add(Workspace(
                    id=workspace_ids[index], organization_id=org_id,
                    name="Isolated Remediation Workspace", slug="remediation-" + workspace_ids[index],
                ))
                await session.flush()
                session.add(User(
                    id=user_ids[index], organization_id=org_id, role_id=role_id,
                    name="Isolated Remediation Owner", email=user_ids[index] + "@example.test",
                    password_hash="synthetic-unused-hash",
                ))
            await session.commit()
        yield SimpleNamespace(
            engine=engine, sessions=sessions, migrate=migrate,
            authority_row=authority_row, registry_rows=registry_rows,
            remediation_row=remediation_row, get=remediation_row,
            new_remediation=new_remediation, update_remediation=update_remediation,
            update=update_remediation, update_authority=update_authority,
            organization_ids=organization_ids, user_ids=user_ids, workspace_ids=workspace_ids,
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


def _prepared_values(remediation_id):
    return {
        "status": "worktree_ready",
        "worktree_ref": "security-remediation://" + remediation_id + "/source",
        "regression_result": {
            "isolation": {
                "files": 1, "bytes": 42,
                "manifest_digest": "a" * 64, "plan_digest": "b" * 64,
            },
            "production_modified": False,
        },
    }


def _clean_failed_values():
    return {
        "status": "failed", "worktree_ref": None,
        "regression_result": {"error_type": "SyntheticSettledFailure", "production_modified": False},
    }


async def _claim(db, remediation_id=None, *, begin=False, session_factory=None):
    remediation_id = remediation_id or await db.new_remediation()
    async with (session_factory or db.sessions)() as session:
        owned = await remediation.register_remediation_activity(
            session, remediation_id=remediation_id, worker_incarnation=str(uuid4()),
        )
        await session.commit()
    if begin:
        async with db.sessions() as session:
            await remediation.begin_remediation_preparation(session, owned)
            await session.commit()
    return owned


async def _settle(db, owned, *, outcome="prepared"):
    values = _prepared_values(owned.remediation_id) if outcome == "prepared" else _clean_failed_values()
    async with db.sessions() as session:
        await remediation.require_owned_remediation_activity(session, owned)
        await session.execute(JOBS.update().where(JOBS.c.id == owned.remediation_id).values(**values))
        await session.flush()
        await remediation.settle_remediation_activity(session, owned, outcome=outcome)
        await session.commit()


async def _await_blocked(sessions, pid, blocker):
    deadline = asyncio.get_running_loop().time() + WAIT
    async with sessions() as observer:
        while asyncio.get_running_loop().time() < deadline:
            if blocker in (await observer.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
            ) or []):
                return
            await asyncio.sleep(0.01)
    pytest.fail("A real PostgreSQL admission lock wait was not observed")


async def _stop_task(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _commit_tripwire(db):
    tripwire = Table(
        "remediation_commit_tripwire_" + uuid4().hex, MetaData(),
        Column("id", String(36), primary_key=True),
        Column("remediation_id", String(36), ForeignKey(
            JOBS.c.id, deferrable=True, initially="DEFERRED",
        ), nullable=False),
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(tripwire.create)

    def attach(session):
        def before_commit(sync_session):
            sync_session.execute(tripwire.insert().values(
                id=str(uuid4()), remediation_id=str(uuid4()),
            ))
        event.listen(session.sync_session, "before_commit", before_commit)
        return session

    return attach


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["commit", "rollback", "cancel"])
async def test_claim_and_preparing_marker_are_atomic_and_block_close(remediation_db, outcome):
    db = remediation_db
    remediation_id = await db.new_remediation()
    before = await db.get(remediation_id)
    registered, release = asyncio.Event(), asyncio.Event()
    claim_factory, claim_probe = db.probed_sessions()
    close_factory, close_probe = db.probed_sessions()
    claimant = closer = None

    async def claim_until_released():
        async with claim_factory() as session:
            owned = await remediation.register_remediation_activity(
                session, remediation_id=remediation_id, worker_incarnation=str(uuid4()),
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
        assert await db.get(remediation_id) == before
        closer = asyncio.create_task(db.close(expected_generation=5, session_factory=close_factory))
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
        measured = await db.snapshot(closed)
        if outcome == "commit":
            row, activities = await db.get(remediation_id), await db.registry_rows()
            assert owned.admitted_generation == 5
            assert row["status"] == "preparing"
            assert row["worktree_ref"] == "preparing:" + owned.activity_id
            assert row["preparation_protocol_version"] == 1
            assert row["preparation_outcome"] is None
            assert len(activities) == 1 and activities[0]["phase"] == "claimed"
            assert activities[0]["id"] == owned.activity_id
            assert measured.blocker_count == 1 and not measured.is_clear
            with pytest.raises((AttributeError, TypeError)):
                owned.admitted_generation = 99
        else:
            assert await db.registry_rows() == []
            assert await db.get(remediation_id) == before
            assert measured.is_clear and remediation_id in measured.frozen_planned_ids
    finally:
        release.set()
        await _stop_task(claimant)
        await _stop_task(closer)


@pytest.mark.asyncio
async def test_close_first_rejects_claim_after_real_shared_lock_wait(remediation_db):
    db = remediation_db
    remediation_id = await db.new_remediation()
    before = await db.get(remediation_id)
    close_factory, close_probe = db.probed_sessions(pause=True)
    claim_factory, claim_probe = db.probed_sessions()
    claimant = closer = None
    try:
        closer = asyncio.create_task(db.close(expected_generation=5, session_factory=close_factory))
        close_pid, shared = await asyncio.wait_for(close_probe.started.get(), WAIT)
        assert shared is False
        await asyncio.wait_for(close_probe.acquired.wait(), WAIT)
        claimant = asyncio.create_task(_claim(db, remediation_id, session_factory=claim_factory))
        claim_pid, shared = await asyncio.wait_for(claim_probe.started.get(), WAIT)
        assert shared is True
        await _await_blocked(db.sessions, claim_pid, close_pid)
        close_probe.release.set()
        await asyncio.wait_for(closer, WAIT)
        with pytest.raises(admission.HostMaintenanceClosed):
            await asyncio.wait_for(claimant, WAIT)
        assert await db.registry_rows() == []
        assert await db.get(remediation_id) == before
    finally:
        close_probe.release.set()
        await _stop_task(claimant)
        await _stop_task(closer)


@pytest.mark.asyncio
async def test_real_commit_failure_returns_no_usable_claim_and_keeps_job_pristine(remediation_db):
    db = remediation_db
    remediation_id = await db.new_remediation()
    before = await db.get(remediation_id)
    attach = await _commit_tripwire(db)
    capabilities = []
    async with db.sessions() as session:
        owned = await remediation.register_remediation_activity(
            session, remediation_id=remediation_id, worker_incarnation=str(uuid4()),
        )
        attach(session)
        with pytest.raises(IntegrityError) as caught:
            await session.commit()
            capabilities.append(owned)  # Stand-in for handing ownership to the copy task.
        await session.rollback()
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23503"
    assert capabilities == []
    assert await db.registry_rows() == []
    assert await db.get(remediation_id) == before
    async with db.sessions() as session:
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.begin_remediation_preparation(session, owned)


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [
    "schema1", "schema2", "schema3", "schema4", "closed", "missing",
    "malformed", "unknown", "database-error",
])
async def test_claim_requires_current_remediation_coverage_and_does_not_repair_authority(remediation_db, condition):
    db = remediation_db
    remediation_id = await db.new_remediation()
    before = await db.get(remediation_id)
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
                    "ALTER TABLE owner_control_records RENAME TO unavailable_remediation_authority"
                ))
            await session.commit()
    else:
        payload = deepcopy((await db.authority_row())["payload"])
        if condition == "schema1":
            await db.update_authority(version=1, payload={
                "schema_version": 1, "scope": "project_execution", "generation": 1,
                "operation_id": None, "reason": "migration-seed", "changed_at": None,
                "full_host_closure": False,
            })
        else:
            scopes = {
                "schema2": "project_execution+backup_cycles",
                "schema3": "project_execution+backup_cycles+academy_course_packages",
                "schema4": "project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch",
            }
            if condition in scopes:
                payload.update(schema_version=int(condition[-1]), scope=scopes[condition])
            elif condition == "malformed":
                payload["full_host_closure"] = True
            else:
                payload["schema_version"] = 99
            await db.update_authority(payload=payload)
    async with db.sessions() as session:
        with pytest.raises(expected) as caught:
            await remediation.register_remediation_activity(
                session, remediation_id=remediation_id, worker_incarnation=str(uuid4()),
            )
    if condition == "database-error":
        assert caught.value.__suppress_context__ is True
        assert "SELECT" not in str(caught.value)
        assert "unavailable_remediation_authority" not in str(caught.value)
    assert await db.registry_rows() == []
    assert await db.get(remediation_id) == before


@pytest.mark.asyncio
async def test_admission_does_not_swallow_non_database_programming_errors(remediation_db, monkeypatch):
    failure = RuntimeError("synthetic programming failure")
    async with remediation_db.sessions() as session:
        monkeypatch.setattr(session, "execute", AsyncMock(side_effect=failure))
        with pytest.raises(RuntimeError) as caught:
            await remediation.require_remediation_admission(session)
        assert caught.value is failure


@pytest.mark.asyncio
async def test_committed_claim_can_begin_after_close_but_begin_commit_is_one_time(remediation_db):
    db = remediation_db
    owned = await _claim(db)
    closed = await db.close()
    before = await db.registry_rows()
    async with db.sessions() as session:
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.require_owned_remediation_activity(session, owned)
        await remediation.begin_remediation_preparation(session, owned)
        await remediation.require_owned_remediation_activity(session, owned)
        assert await db.registry_rows() == before
        await session.rollback()
    assert await db.registry_rows() == before
    async with db.sessions() as session:
        await remediation.begin_remediation_preparation(session, owned)
        await session.commit()
    assert (await db.registry_rows())[0]["phase"] == "preparing"
    async with db.sessions() as session:
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.begin_remediation_preparation(session, owned)
    assert (await db.snapshot(closed)).blocker_count == 1


@pytest.mark.asyncio
async def test_concurrent_begin_waits_then_rejects_consumed_claim(remediation_db):
    db = remediation_db
    owned = await _claim(db)
    first_factory, first_probe = db.probed_sessions(pause=True)
    second_factory, second_probe = db.probed_sessions()
    first = second = None

    async def begin(factory):
        async with factory() as session:
            await remediation.begin_remediation_preparation(session, owned)
            await session.commit()

    try:
        first = asyncio.create_task(begin(first_factory))
        first_pid, shared = await asyncio.wait_for(first_probe.started.get(), WAIT)
        assert shared is False
        await asyncio.wait_for(first_probe.acquired.wait(), WAIT)
        second = asyncio.create_task(begin(second_factory))
        second_pid, shared = await asyncio.wait_for(second_probe.started.get(), WAIT)
        assert shared is False
        await _await_blocked(db.sessions, second_pid, first_pid)
        first_probe.release.set()
        await asyncio.wait_for(first, WAIT)
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await asyncio.wait_for(second, WAIT)
        assert (await db.registry_rows())[0]["phase"] == "preparing"
    finally:
        first_probe.release.set()
        await _stop_task(first)
        await _stop_task(second)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "activity_id", "remediation_id", "worker_incarnation", "admitted_generation", "ownership_nonce",
])
async def test_exact_identity_fences_begin_publication_heartbeat_uncertainty_and_finish(remediation_db, field):
    db = remediation_db
    owned, other = await _claim(db, begin=True), await _claim(db, begin=True)
    replacement = owned.admitted_generation + 1 if field == "admitted_generation" else getattr(other, field)
    forged = replace(owned, **{field: replacement})
    before = await db.registry_rows(), await db.get(owned.remediation_id)
    async with db.sessions() as session:
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.begin_remediation_preparation(session, forged)
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.require_owned_remediation_activity(session, forged)
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.settle_remediation_activity(session, forged, outcome="prepared")
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.heartbeat_remediation_activity(forged, session_factory=db.sessions)
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.mark_remediation_activity_unresolved(
            forged, reason="forged ownership", session_factory=db.sessions,
        )
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.finish_remediation_activity(forged, session_factory=db.sessions)
    assert (await db.registry_rows(), await db.get(owned.remediation_id)) == before
    await _settle(db, owned)
    await _settle(db, other)
    settled_before = await db.registry_rows()
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.finish_remediation_activity(forged, session_factory=db.sessions)
    assert await db.registry_rows() == settled_before


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "worktree", "result", "retest", "verified", "protocol-started",
    "plan-boolean", "plan-string", "plan-float", "plan-new-schema", "plan-not-object",
])
async def test_pristine_sql_and_python_reject_planned_effects_and_malformed_plans(remediation_db, case):
    db = remediation_db
    remediation_id = await db.new_remediation()
    row = await db.get(remediation_id)
    async with db.sessions() as session:
        finding = await session.get(SecurityFinding, row["finding_id"])
        scan_id = finding.scan_id
    values = {
        "worktree": {"worktree_ref": "preparing:" + str(uuid4())},
        "result": {"regression_result": {"old_output": True}},
        "retest": {"retest_scan_id": scan_id},
        "verified": {"verified_fixed_at": datetime.now(UTC)},
        "protocol-started": {"preparation_protocol_version": 1, "preparation_outcome": None},
        "plan-boolean": {"plan": {"schema_version": True}},
        "plan-string": {"plan": {"schema_version": "1"}},
        "plan-float": {"plan": {"schema_version": 1.0}},
        "plan-new-schema": {"plan": {"schema_version": 2}},
        "plan-not-object": {"plan": []},
    }[case]
    await db.update(remediation_id, **values)
    before = await db.get(remediation_id)
    async with db.sessions() as session:
        model = await session.get(SecurityRemediation, remediation_id)
        raw = (await session.execute(select(JOBS).where(JOBS.c.id == remediation_id))).mappings().one()
        assert not remediation.is_pristine_planned_remediation(model)
        assert not remediation.is_pristine_planned_remediation(raw)
        assert await session.scalar(select(JOBS.c.id).where(
            JOBS.c.id == remediation_id, *remediation.pristine_planned_remediation_conditions(JOBS),
        )) is None
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.register_remediation_activity(
                session, remediation_id=remediation_id, worker_incarnation=str(uuid4()),
            )
    assert await db.registry_rows() == []
    assert await db.get(remediation_id) == before


@pytest.mark.asyncio
async def test_pristine_schema_one_plan_accepts_unrestricted_input_but_raw_claim_rechecks_cache(remediation_db):
    db = remediation_db
    remediation_id = await db.new_remediation(plan={
        "schema_version": 1, "input": {"instructions": "synthetic private instructions"},
    })
    async with db.sessions() as session:
        cached = await session.get(SecurityRemediation, remediation_id)
        assert remediation.is_pristine_planned_remediation(cached)
        assert await session.scalar(select(JOBS.c.id).where(
            JOBS.c.id == remediation_id, *remediation.pristine_planned_remediation_conditions(JOBS),
        )) == remediation_id
        await db.update(remediation_id, regression_result={"external_change": True})
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.register_remediation_activity(
                session, remediation_id=remediation_id, worker_incarnation=str(uuid4()),
            )
        assert cached.regression_result == {}
    assert await db.registry_rows() == []


@pytest.mark.asyncio
async def test_prepared_result_and_proof_commit_together_and_commit_failure_keeps_blocker(remediation_db):
    db = remediation_db
    owned = await _claim(db, begin=True)
    before = await db.get(owned.remediation_id), await db.registry_rows()
    attach = await _commit_tripwire(db)
    async with db.sessions() as session:
        await remediation.require_owned_remediation_activity(session, owned)
        await session.execute(JOBS.update().where(JOBS.c.id == owned.remediation_id).values(
            **_prepared_values(owned.remediation_id)
        ))
        await session.flush()
        await remediation.settle_remediation_activity(session, owned, outcome="prepared")
        assert (await db.get(owned.remediation_id), await db.registry_rows()) == before
        attach(session)
        with pytest.raises(IntegrityError) as caught:
            await session.commit()
        await session.rollback()
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23503"
    assert (await db.get(owned.remediation_id), await db.registry_rows()) == before
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.finish_remediation_activity(owned, session_factory=db.sessions)
    # A caller with an unknown publication/commit result retains ownership.
    await remediation.mark_remediation_activity_unresolved(
        owned, reason="prepared publication commit outcome not confirmed", session_factory=db.sessions,
    )
    measured = await db.snapshot(await db.close())
    assert measured.unresolved_count == measured.blocker_count == 1
    assert not measured.is_clear


@pytest.mark.asyncio
@pytest.mark.parametrize("downstream", [
    "worktree_ready", "patch_ready", "regression_passed", "retest_queued",
    "retest_failed", "verified_fixed", "rejected", "cancelled",
])
async def test_prepared_proof_allows_confirmed_downstream_business_progress_after_close_and_expiry(remediation_db, downstream):
    db = remediation_db
    owned = await _claim(db, begin=True)
    await _settle(db, owned)
    closed = await db.close()
    if downstream != "worktree_ready":
        # Downstream status changes do not replace the dedicated preparation
        # proof. Real patch/retest helpers are exercised in the next test.
        await db.update(
            owned.remediation_id, status=downstream,
            regression_result={"downstream_business_result": True},
        )
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    assert (await db.snapshot(closed)).expired_count == 1
    await remediation.heartbeat_remediation_activity(owned, session_factory=db.sessions)
    business_before = await db.get(owned.remediation_id)
    await remediation.finish_remediation_activity(owned, session_factory=db.sessions)
    assert await db.registry_rows() == []
    assert await db.get(owned.remediation_id) == business_before
    measured = await db.snapshot(closed)
    assert measured.is_clear and owned.remediation_id in measured.preserved_result_ids
    assert measured.coverage_unverified is True and measured.full_host_closure is False


@pytest.mark.asyncio
@pytest.mark.parametrize("advance", ["regression_passed", "retest_failed", "verified_fixed"])
async def test_real_patch_and_retest_helpers_can_replace_result_without_losing_prepared_proof(remediation_db, advance):
    from app.core.auth import UserRecord
    from app.services.security_remediation import finalize_retest, record_patch_evidence

    db = remediation_db
    owned = await _claim(db, begin=True)
    await _settle(db, owned)
    closed = await db.close()
    actor = UserRecord(
        id=db.user_ids[0], email="owner@example.test", name="Isolated Super Owner",
        role="Super Owner", password_hash="synthetic-unused-hash",
        organization_id=db.organization_ids[0], organization_name="Isolated Organization",
        organization_plan="enterprise", permissions=[],
    )
    async with db.sessions() as session:
        job = await session.get(SecurityRemediation, owned.remediation_id)
        await record_patch_evidence(
            session, actor, job, changed_files=["app/example.py"],
            tests=[{"name": "synthetic recorded regression", "passed": True}],
            patch_digest="c" * 64,
        )
        await session.commit()
    patched = await db.get(owned.remediation_id)
    assert patched["status"] == "regression_passed"
    assert "isolation" not in patched["regression_result"]
    assert patched["preparation_protocol_version"] == 1
    assert patched["preparation_outcome"] == "prepared"
    if advance != "regression_passed":
        # Supply an already completed isolated scan row; execute no scan or
        # enqueue route. The real finalizer publishes its actual result shape.
        async with db.sessions() as session:
            job = await session.get(SecurityRemediation, owned.remediation_id)
            finding = await session.get(SecurityFinding, job.finding_id)
            retest_id = str(uuid4())
            session.add(SecurityScan(
                id=retest_id, organization_id=job.organization_id, project_id=job.project_id,
                target_id=finding.target_id, profile="passive", status="completed",
                completed_at=datetime.now(UTC),
            ))
            await session.flush()
            if advance == "retest_failed":
                session.add(SecurityFinding(
                    id=str(uuid4()), organization_id=job.organization_id,
                    scan_id=retest_id, target_id=finding.target_id, source="isolated-acceptance",
                    category="test-contract", title="Repeated synthetic finding",
                    severity="low", fingerprint=finding.fingerprint,
                ))
            job.status = "retest_queued"
            job.retest_scan_id = retest_id
            await session.commit()
        async with db.sessions() as session:
            job = await session.get(SecurityRemediation, owned.remediation_id)
            await finalize_retest(session, actor, job)
            await session.commit()
    final_business = await db.get(owned.remediation_id)
    assert final_business["status"] == advance
    assert final_business["preparation_outcome"] == "prepared"
    assert "isolation" not in final_business["regression_result"]
    async with db.sessions() as session:
        assert await session.scalar(select(AuditEvent.id).where(
            AuditEvent.resource_id == owned.remediation_id,
            AuditEvent.action == "security.remediation.regression_passed",
        )) is not None
    await remediation.heartbeat_remediation_activity(owned, session_factory=db.sessions)
    await remediation.finish_remediation_activity(owned, session_factory=db.sessions)
    assert await db.get(owned.remediation_id) == final_business
    measured = await db.snapshot(closed)
    assert measured.is_clear and owned.remediation_id in measured.preserved_result_ids


@pytest.mark.asyncio
async def test_clean_failed_proof_distinguishes_settled_failure_from_identical_legacy_json(remediation_db):
    db = remediation_db
    owned = await _claim(db, begin=True)
    await _settle(db, owned, outcome="clean_failed")
    closed = await db.close()
    await remediation.heartbeat_remediation_activity(owned, session_factory=db.sessions)
    business = await db.get(owned.remediation_id)
    assert business["preparation_protocol_version"] == 1
    assert business["preparation_outcome"] == "clean_failed"
    await remediation.finish_remediation_activity(owned, session_factory=db.sessions)
    assert await db.get(owned.remediation_id) == business
    assert (await db.snapshot(closed)).is_clear
    legacy = await db.new_remediation(**_clean_failed_values())
    measured = await db.snapshot(closed)
    assert measured.legacy_failed_ids == (legacy,)
    assert measured.blocker_count == 1 and not measured.is_clear


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "empty-isolation", "boolean-files", "negative-bytes", "upper-digest",
    "production-number", "clean-failed-empty-error",
])
async def test_unproven_business_result_cannot_settle_or_release_ownership(remediation_db, case):
    db = remediation_db
    owned = await _claim(db, begin=True)
    outcome = "prepared"
    values = _prepared_values(owned.remediation_id)
    if case == "empty-isolation":
        values["regression_result"]["isolation"] = {}
    elif case == "boolean-files":
        values["regression_result"]["isolation"]["files"] = True
    elif case == "negative-bytes":
        values["regression_result"]["isolation"]["bytes"] = -1
    elif case == "upper-digest":
        values["regression_result"]["isolation"]["manifest_digest"] = "A" * 64
    elif case == "production-number":
        values["regression_result"]["production_modified"] = 0
    else:
        outcome = "clean_failed"
        values = _clean_failed_values()
        values["regression_result"]["error_type"] = ""
    before = await db.get(owned.remediation_id), await db.registry_rows()
    async with db.sessions() as session:
        await remediation.require_owned_remediation_activity(session, owned)
        await session.execute(JOBS.update().where(JOBS.c.id == owned.remediation_id).values(**values))
        await session.flush()
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.settle_remediation_activity(session, owned, outcome=outcome)
        await session.rollback()
    assert (await db.get(owned.remediation_id), await db.registry_rows()) == before
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.finish_remediation_activity(owned, session_factory=db.sessions)


@pytest.mark.asyncio
async def test_expired_unresolved_owner_cannot_resume_finish_or_be_readopted_after_manual_reset(remediation_db):
    db = remediation_db
    owned = await _claim(db, begin=True)
    await remediation.mark_remediation_activity_unresolved(
        owned, reason="copy task cancellation has unsettled effects", session_factory=db.sessions,
    )
    await remediation.mark_remediation_activity_unresolved(
        owned, reason="later reason must preserve first uncertainty", session_factory=db.sessions,
    )
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().values(
            started_at=old - timedelta(minutes=5), heartbeat_at=old - timedelta(minutes=2),
            lease_expires_at=old,
        ))
        await session.commit()
    # Even resetting every business proof field cannot erase durable activity.
    await db.update(
        owned.remediation_id, status="planned", worktree_ref=None, regression_result={},
        preparation_protocol_version=None, preparation_outcome=None,
    )
    before = await db.registry_rows()
    async with db.sessions() as session:
        raw = (await session.execute(select(JOBS).where(JOBS.c.id == owned.remediation_id))).mappings().one()
        assert remediation.is_pristine_planned_remediation(raw)
        assert await session.scalar(select(JOBS.c.id).where(
            JOBS.c.id == owned.remediation_id, *remediation.pristine_planned_remediation_conditions(JOBS),
        )) is None
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.register_remediation_activity(
                session, remediation_id=owned.remediation_id, worker_incarnation=str(uuid4()),
            )
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.begin_remediation_preparation(session, owned)
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.require_owned_remediation_activity(session, owned)
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.heartbeat_remediation_activity(owned, session_factory=db.sessions)
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.finish_remediation_activity(owned, session_factory=db.sessions)
    assert await db.registry_rows() == before
    assert before[0]["unresolved_reason"] == "copy task cancellation has unsettled effects"
    measured = await db.snapshot(await db.close())
    assert measured.expired_count == measured.unresolved_count == measured.blocker_count == 1
    assert not measured.is_clear and owned.remediation_id not in measured.frozen_planned_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["planned", "cancelled", "worktree_ready", "regression_passed"])
async def test_independent_incomplete_proof_blocks_even_after_business_status_and_json_replacement(remediation_db, status):
    db = remediation_db
    remediation_id = await db.new_remediation()
    values = _prepared_values(remediation_id)
    values.update(
        status=status, preparation_protocol_version=1, preparation_outcome=None,
        regression_result={"patched_after_unknown_preparation": True},
    )
    await db.update(remediation_id, **values)
    assert await db.registry_rows() == []
    async with db.sessions() as session:
        assert await session.scalar(select(JOBS.c.id).where(
            JOBS.c.id == remediation_id, *remediation.pristine_planned_remediation_conditions(JOBS),
        )) is None
        with pytest.raises(remediation.RemediationActivityOwnershipLost):
            await remediation.register_remediation_activity(
                session, remediation_id=remediation_id, worker_incarnation=str(uuid4()),
            )
    measured = await db.snapshot(await db.close())
    assert measured.unresolved_preparation_ids == (remediation_id,)
    assert measured.blocker_count == 1 and not measured.is_clear
    assert remediation_id not in measured.preserved_result_ids
    assert remediation_id not in measured.frozen_planned_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", [None, "security-remediation://not-the-job/source"])
async def test_legacy_ready_status_without_canonical_artifact_is_a_blocker(remediation_db, reference):
    db = remediation_db
    remediation_id = await db.new_remediation(status="worktree_ready", worktree_ref=reference)
    measured = await db.snapshot(await db.close())
    assert remediation_id in measured.unresolved_preparation_ids
    assert remediation_id not in measured.preserved_result_ids
    assert measured.blocker_count == 1 and not measured.is_clear


@pytest.mark.asyncio
async def test_finding_cascade_deletes_business_row_but_retains_orphan_activity(remediation_db):
    db = remediation_db
    owned = await _claim(db, begin=True)
    business = await db.get(owned.remediation_id)
    before = await db.registry_rows()
    async with db.sessions() as session:
        await session.execute(SecurityFinding.__table__.delete().where(
            SecurityFinding.__table__.c.id == business["finding_id"]
        ))
        await session.commit()
    assert await db.get(owned.remediation_id) is None
    assert await db.registry_rows() == before
    with pytest.raises(remediation.RemediationActivityOwnershipLost):
        await remediation.finish_remediation_activity(owned, session_factory=db.sessions)
    await remediation.mark_remediation_activity_unresolved(
        owned, reason="finding cascade left unfinished preparation", session_factory=db.sessions,
    )
    measured = await db.snapshot(await db.close())
    assert measured.unresolved_count == measured.unfinished_count == measured.blocker_count == 1
    assert not measured.is_clear


@pytest.mark.asyncio
async def test_all_generation_snapshot_keeps_legacy_and_independent_proof_without_private_data(remediation_db):
    db = remediation_db
    older = await _claim(db, begin=True)
    first_closed = await db.close()
    reopened = await admission.open_admission(
        operation_id=first_closed.operation_id, expected_generation=first_closed.generation,
        reason="continue isolated remediation coverage", session_factory=db.sessions,
    )
    newer = await _claim(db, begin=True)
    await remediation.mark_remediation_activity_unresolved(
        older, reason="unfinished older copy task", session_factory=db.sessions,
    )
    unowned = await db.new_remediation(
        organization_index=1, status="preparing", worktree_ref="preparing:" + str(uuid4()),
    )
    failed = await db.new_remediation(**_clean_failed_values())
    unknown = await db.new_remediation(status="unrecognized-future-status")
    stale = await db.new_remediation(regression_result={"old_effect": True})
    incomplete = await db.new_remediation(
        status="cancelled", preparation_protocol_version=1, preparation_outcome=None,
    )
    pristine = await db.new_remediation(plan={
        "schema_version": 1, "instructions": "synthetic-private-plan",
    }, source_snapshot="/synthetic/private/source")
    prepared = await _claim(db, begin=True)
    await _settle(db, prepared)
    await remediation.finish_remediation_activity(prepared, session_factory=db.sessions)
    cleaned = await _claim(db, begin=True)
    await _settle(db, cleaned, outcome="clean_failed")
    await remediation.finish_remediation_activity(cleaned, session_factory=db.sessions)
    backup_owner = await backup_cycles.begin_backup_cycle(
        worker_incarnation=str(uuid4()), session_factory=db.sessions,
    )
    old = datetime.now(UTC) - timedelta(days=1)
    async with db.sessions() as session:
        await session.execute(REGISTRY.update().where(
            REGISTRY.c.consumer == remediation.CONSUMER
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
    assert {item.admitted_generation for item in measured.activities} == {5, reopened.generation}
    assert set(measured.unowned_preparing_ids) == {unowned}
    assert set(measured.legacy_failed_ids) == {failed}
    assert set(measured.unknown_status_ids) == {unknown}
    assert set(measured.nonpristine_planned_ids) == {stale}
    assert set(measured.unresolved_preparation_ids) == {
        older.remediation_id, newer.remediation_id, incomplete,
    }
    assert set(measured.frozen_planned_ids) == {pristine}
    assert set(measured.preserved_result_ids) == {prepared.remediation_id}
    assert measured.blocker_count == 7 and not measured.is_clear
    assert measured.coverage_unverified is True and measured.full_host_closure is False
    encoded = json.dumps(asdict(measured), default=str)
    for private in (
        "ownership_nonce", older.ownership_nonce, newer.ownership_nonce,
        "regression_result", "synthetic-private-plan", "synthetic-private-finding",
        "/synthetic/private/source", "worktree_ref",
    ):
        assert private not in encoded
    assert older.ownership_nonce not in repr(older)
    assert all(not hasattr(item, "ownership_nonce") for item in measured.activities)
    assert await db.registry_rows() == before
    async with db.sessions() as session:
        backups = await backup_cycles.snapshot_backup_cycles(
            session, operation_id=closed.operation_id, expected_generation=closed.generation,
        )
    assert {item.cycle_id for item in backups.cycles} == {backup_owner.cycle_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["future-generation", "invalid-activity-job", "invalid-business-id"])
async def test_snapshot_fails_closed_on_future_or_malformed_identity(remediation_db, case):
    db = remediation_db
    owned = await _claim(db, begin=True)
    async with db.sessions() as session:
        if case == "future-generation":
            await session.execute(REGISTRY.update().values(admitted_generation=999))
        elif case == "invalid-activity-job":
            await session.execute(REGISTRY.update().values(job_id="not-a-uuid"))
        else:
            await session.execute(JOBS.update().where(JOBS.c.id == owned.remediation_id).values(id="not-a-uuid"))
        await session.commit()
    closed = await db.close()
    with pytest.raises(remediation.RemediationActivityRegistryUnavailable):
        await db.snapshot(closed)


@pytest.mark.asyncio
@pytest.mark.parametrize("remediation_db", ["schema4"], indirect=True)
@pytest.mark.parametrize("state", ["open", "closed"])
async def test_0051_advances_only_coverage_and_preserves_legacy_rows_and_prior_consumer_ownership(remediation_db, state):
    db = remediation_db
    remediation_id = await db.new_remediation(**_clean_failed_values())
    legacy_before = await db.remediation_row(remediation_id, legacy=True)
    backup_owner = await backup_cycles.begin_backup_cycle(
        worker_incarnation=str(uuid4()), session_factory=db.sessions,
    )
    if state == "closed":
        await db.close()
    before, registry_before = await db.authority_row(), await db.registry_rows()
    await db.migrate()
    after = await db.authority_row()
    assert after["id"] == before["id"]
    assert after["status"] == before["status"] and after["enabled"] == before["enabled"]
    assert after["version"] == before["version"] + 1
    payload = after["payload"]
    assert payload["schema_version"] == admission.REMEDIATION_SCHEMA_VERSION == 5
    assert payload["scope"] == admission.REMEDIATION_COVERAGE_SCOPE == (
        "project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch+security_remediation_preparation"
    )
    assert payload["generation"] == after["version"]
    for field in ("operation_id", "reason", "changed_at", "full_host_closure"):
        assert payload[field] == before["payload"][field]
    business = await db.get(remediation_id)
    assert business["preparation_protocol_version"] is None
    assert business["preparation_outcome"] is None
    assert await db.remediation_row(remediation_id, legacy=True) == legacy_before
    assert await db.registry_rows() == registry_before
    for direction in ("upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.authority_row() == after
        assert await db.get(remediation_id) == business
        assert await db.registry_rows() == registry_before
    with pytest.raises(admission.HostMaintenanceConflict):
        await admission.close_admission(
            operation_id=str(uuid4()), expected_generation=before["version"],
            reason="stale pre-remediation generation", session_factory=db.sessions,
        )
    if state == "closed":
        with pytest.raises(admission.HostMaintenanceConflict):
            await admission.open_admission(
                operation_id=before["payload"]["operation_id"], expected_generation=before["version"],
                reason="stale closure receipt", session_factory=db.sessions,
            )
        await admission.open_admission(
            operation_id=after["payload"]["operation_id"], expected_generation=after["version"],
            reason="current covered generation", session_factory=db.sessions,
        )
    async with db.sessions() as session:
        for scope in (
            "project_execution", "backup_cycles", "academy_course_packages",
            "notification_delivery_dispatch", "security_remediation_preparation",
        ):
            assert (await admission.require_admission_open(session, required_scope=scope)).is_open
    await backup_cycles.finish_backup_cycle(backup_owner, session_factory=db.sessions)
    assert await db.registry_rows() == []
    assert (await _claim(db)).admitted_generation >= 5


@pytest.mark.asyncio
@pytest.mark.parametrize("remediation_db", ["schema4"], indirect=True)
@pytest.mark.parametrize("state", [
    "missing", "malformed", "unknown", "schema1", "schema2", "schema3", "already5",
])
async def test_0051_retains_old_or_unupgradeable_authority_without_repair_or_reopen(remediation_db, state):
    db = remediation_db
    payload = deepcopy((await db.authority_row())["payload"])
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
        elif state == "schema3":
            payload.update(
                schema_version=3, scope="project_execution+backup_cycles+academy_course_packages",
            )
        else:
            payload.update(
                schema_version=5,
                scope="project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch+security_remediation_preparation",
                generation=10, operation_id=str(uuid4()), reason="already covered closure",
                changed_at=datetime.now(UTC).isoformat(),
            )
            await db.update_authority(status="closed", enabled=False, version=10)
        await db.update_authority(payload=payload)
    preserved = await db.authority_row()
    for direction in ("upgrade", "upgrade", "downgrade", "upgrade"):
        await db.migrate(direction=direction)
        assert await db.authority_row() == preserved


@pytest.mark.asyncio
async def test_retained_d6_rows_survive_0051_0050_0049_downgrade_and_reupgrade(remediation_db):
    db = remediation_db
    active = await _claim(db, begin=True)
    uncertain = await _claim(db, begin=True)
    await _settle(db, active)
    await remediation.mark_remediation_activity_unresolved(
        uncertain, reason="preserve unsettled copy through replay", session_factory=db.sessions,
    )
    closed = await db.close()
    before = (
        await db.authority_row(), await db.registry_rows(),
        await db.get(active.remediation_id), await db.get(uncertain.remediation_id),
    )
    for revision, direction in (
        ("0051", "downgrade"), ("0050", "downgrade"), ("0049", "downgrade"),
        ("0049", "upgrade"), ("0050", "upgrade"), ("0051", "upgrade"),
    ):
        await db.migrate(revision, direction=direction)
        assert (
            await db.authority_row(), await db.registry_rows(),
            await db.get(active.remediation_id), await db.get(uncertain.remediation_id),
        ) == before
    measured = await db.snapshot(closed)
    assert measured.active_count == measured.unresolved_count == 1
    assert measured.blocker_count == 2 and not measured.is_clear


@pytest.mark.asyncio
@pytest.mark.parametrize("remediation_db", ["latest-metadata"], indirect=True)
async def test_current_model_metadata_accepts_0047_through_0051_without_shrinking_d6_registry(remediation_db):
    db = remediation_db
    authority = await db.authority_row()
    assert authority["version"] == authority["payload"]["schema_version"] == 5
    owned = await _claim(db, begin=True)
    before = await db.registry_rows(), await db.get(owned.remediation_id)
    for revision in ("0049", "0050", "0051"):
        await db.migrate(revision)
        assert (await db.registry_rows(), await db.get(owned.remediation_id)) == before
    duplicate = {**before[0][0], "id": str(uuid4()), "ownership_nonce": str(uuid4())}
    async with db.sessions() as session:
        with pytest.raises(IntegrityError) as caught:
            await session.execute(REGISTRY.insert().values(**duplicate))
        await session.rollback()
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23505"
    assert (await db.registry_rows(), await db.get(owned.remediation_id)) == before
    await _settle(db, owned)
    await remediation.finish_remediation_activity(owned, session_factory=db.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", ["0049", "0050", "0051"])
async def test_older_and_current_migrations_reject_unknown_widened_consumer_constraint(remediation_db, revision):
    db = remediation_db
    await _claim(db, begin=True)
    async with db.sessions() as session:
        await session.execute(text(
            "ALTER TABLE host_maintenance_work_cycles DROP CONSTRAINT ck_host_cycle_consumer"
        ))
        await session.execute(text(
            "ALTER TABLE host_maintenance_work_cycles ADD CONSTRAINT "
            "ck_host_cycle_consumer CHECK (consumer <> '')"
        ))
        await session.commit()
    before = await db.authority_row(), await db.registry_rows()
    with pytest.raises(RuntimeError):
        await db.migrate(revision)
    assert (await db.authority_row(), await db.registry_rows()) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("version,outcome", [
    (None, "prepared"), (None, "clean_failed"),
    (2, None), (2, "prepared"), (1, "unknown"),
])
async def test_database_check_rejects_invalid_preparation_proof_pairs_without_mutation(
    remediation_db, version, outcome,
):
    db = remediation_db
    remediation_id = await db.new_remediation()
    before = await db.get(remediation_id)
    assert before["preparation_protocol_version"] is None
    assert before["preparation_outcome"] is None
    async with db.sessions() as session:
        with pytest.raises(IntegrityError) as caught:
            await session.execute(JOBS.update().where(JOBS.c.id == remediation_id).values(
                preparation_protocol_version=version, preparation_outcome=outcome,
            ))
            await session.commit()
        await session.rollback()
    original = caught.value.orig
    assert (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "23514"
    assert await db.get(remediation_id) == before
    assert await db.registry_rows() == []
