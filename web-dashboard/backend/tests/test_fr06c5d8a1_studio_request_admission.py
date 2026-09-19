"""Isolated PostgreSQL acceptance for Studio request admission, not execution.

Every case owns a disposable schema. No worker, artifact store or provider is
invoked. Existing functional Studio suites cover normal worker compatibility.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
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
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1.endpoints import studio
from app.core.auth import UserRecord, current_user
from app.db.base import Base, get_db
from app.db.models import (
    AuditEvent, Organization, OwnerControlRecord, Project, StudioAsset,
    StudioAssetRevision, StudioJob, StudioCrashObservation, StudioExecution, StudioPublication, StudioSettlement, StudioPrestartCancellation, StudioPoststartCancellation, User,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_governance
from app.services.host_maintenance_studio_admission import CONSUMER, require_studio_admission

CLOSED = "Studio request admission is temporarily closed for maintenance."
UNAVAILABLE = "Studio request admission is currently unavailable."
WAIT = 8


def _migration(connection, direction="upgrade"):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260918_0054_studio_request_admission.py"
    spec = importlib.util.spec_from_file_location("studio_admission_migration_" + uuid4().hex, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


def _tables():
    tables = {model.__table__ for model in (
        OwnerControlRecord, StudioJob, StudioAsset, StudioAssetRevision, AuditEvent, Project,
        StudioCrashObservation, StudioExecution, StudioPublication, StudioSettlement, StudioPrestartCancellation, StudioPoststartCancellation,
    )}
    while True:
        expanded = tables | {fk.column.table for table in tables for fk in table.foreign_keys}
        if expanded == tables:
            return list(tables)
        tables = expanded


def _schema_six():
    return {
        "schema_version": 6, "scope": admission.SCAN_REQUEST_COVERAGE_SCOPE,
        "generation": 6, "operation_id": str(uuid4()), "reason": "isolated-studio-acceptance",
        "changed_at": datetime.now(UTC).isoformat(), "full_host_closure": False,
    }


@pytest_asyncio.fixture
async def studio_case():
    url = make_url(os.environ.get("DATABASE_URL", ""))
    assert url.drivername == "postgresql+asyncpg"
    assert re.search(r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)", url.database or "")
    schema = "studio_admission_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_id, user_id, authority_id, original_id, asset_id = (str(uuid4()) for _ in range(5))
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=_tables()))
        async with sessions() as session:
            session.add(Organization(id=org_id, name="Isolated Studio", slug="studio-" + uuid4().hex, plan="enterprise", status="active"))
            await session.flush()
            session.add(User(id=user_id, organization_id=org_id, role_id=None, email=uuid4().hex + "@example.invalid", name="Studio Test", password_hash="unused", status="active"))
            session.add(OwnerControlRecord(id=authority_id, domain=admission.DOMAIN, resource_id=admission.RESOURCE_ID, status="open", enabled=True, payload=_schema_six(), version=6))
            await session.flush()
            session.add(StudioJob(
                id=original_id, organization_id=org_id, requested_by_id=user_id,
                department="text", output_kind="document", title="Original Studio asset",
                brief="An original synthetic briefing for admission tests.", language="en-US", style="modern",
                provider_mode="provider_neutral", status="completed", progress=100,
            ))
            await session.flush()
            session.add(StudioAsset(
                id=asset_id, organization_id=org_id, job_id=original_id, created_by_id=user_id,
                department="text", asset_type="document", title="Original Studio asset",
                filename="synthetic.zip", media_type="application/zip", storage_path="/nonexistent/synthetic.zip",
                checksum="0" * 64, size_bytes=1, status="active", current_revision=1, asset_metadata={},
            ))
            await session.commit()
        async with engine.begin() as connection:
            await connection.run_sync(_migration)
        actor = UserRecord(
            id=user_id, email="studio-test@example.invalid", name="Studio Test", role="Owner",
            password_hash="unused", organization_id=org_id, organization_name="Isolated Studio",
            organization_plan="enterprise", permissions=["*"],
        )
        app = FastAPI()
        app.include_router(studio.router, prefix="/studio")
        app.dependency_overrides[current_user] = lambda: actor
        async def db():
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_db] = db
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://studio.test") as client:
            yield SimpleNamespace(
                engine=engine, sessions=sessions, actor=actor, client=client, app=app,
                authority_id=authority_id, original_id=original_id, asset_id=asset_id,
                operation_id=str(uuid4()), schema=schema,
            )
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def _authority(case):
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        return None if row is None else {"payload": deepcopy(row.payload), "version": row.version, "status": row.status, "enabled": row.enabled}


async def _change(case, *, remove=False, **changes):
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        if remove:
            await session.delete(row)
        else:
            row.payload = {**row.payload, **changes}
        await session.commit()


async def _close(case, factory=None):
    row = await _authority(case)
    return await admission.close_admission(
        operation_id=case.operation_id, expected_generation=row["version"],
        reason="isolated Studio request test", session_factory=factory or case.sessions,
    )


async def _business(case):
    async with case.sessions() as session:
        return {
            table.name: [dict(row) for row in (await session.execute(select(table).order_by(table.c.id))).mappings()]
            for table in (StudioJob.__table__, StudioAsset.__table__, AuditEvent.__table__)
        }


async def _retryable(case):
    async with case.sessions() as session:
        job = await session.get(StudioJob, case.original_id)
        job.status = "failed"
        await session.commit()


async def _request(case, family):
    data = {"department": "text", "title": "Studio test request", "brief": "A lawful synthetic Studio brief for tests."}
    if family == "job":
        return await case.client.post("/studio/jobs", json=data)
    if family == "legacy":
        return await case.client.post("/studio/generate", json=data)
    if family == "revision":
        return await case.client.post(f"/studio/assets/{case.asset_id}/revisions", json={"brief": data["brief"], "change_note": "Isolated revision"})
    return await case.client.post(f"/studio/jobs/{case.original_id}/retry")


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["job", "revision", "retry"])
async def test_open_producer_commits_queue_with_real_policy(studio_case, family):
    case = studio_case
    if family == "retry":
        await _retryable(case)
    before = await _business(case)
    response = await _request(case, family)
    assert response.status_code == (200 if family == "retry" else 202), response.text
    assert response.json()["status"] == "queued"
    after = await _business(case)
    assert len(after["studio_jobs"]) == len(before["studio_jobs"]) + (family != "retry")
    assert after["studio_assets"] == before["studio_assets"]
    if family == "revision":
        created = next(row for row in after["studio_jobs"] if row["id"] == response.json()["id"])
        assert created["revision_of_asset_id"] == case.asset_id


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["job", "revision", "retry", "legacy"])
@pytest.mark.parametrize("state", ["closed", "missing", "corrupt", "old_scope", "future", "full_host"])
async def test_denied_before_scope_policy_queue_or_worker(studio_case, family, state, monkeypatch):
    case = studio_case
    await _retryable(case)
    if state == "closed":
        await _close(case)
    elif state == "missing":
        await _change(case, remove=True)
    elif state == "corrupt":
        await _change(case, generation="7")
    elif state == "old_scope":
        await _change(case, schema_version=6, scope=admission.SCAN_REQUEST_COVERAGE_SCOPE)
    elif state == "future":
        await _change(case, schema_version=999)
    else:
        await _change(case, full_host_closure=True)
    before = await _business(case)
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append("unexpected business or worker operation")
        raise AssertionError("denied request proceeded past maintenance authority")
    for name in ("_validate_scope", "_asset_or_404", "_job_or_404"):
        monkeypatch.setattr(studio, name, forbidden)
    monkeypatch.setattr(studio_governance, "admit_studio_job", forbidden)
    monkeypatch.setattr(studio.StudioWorker, "claim_by_id", forbidden)
    response = await _request(case, family)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": CLOSED if state == "closed" else UNAVAILABLE}
    assert not calls
    assert await _business(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["list", "get", "cancel"])
async def test_read_and_existing_cancellation_are_not_request_admission(studio_case, family):
    case = studio_case
    if family == "cancel":
        async with case.sessions() as session:
            job = await session.get(StudioJob, case.original_id)
            job.status = "queued"
            await session.commit()
    await _close(case)
    path = "/studio/jobs" if family == "list" else f"/studio/jobs/{case.original_id}"
    response = await case.client.post(path + "/cancel") if family == "cancel" else await case.client.get(path)
    assert response.status_code == 200, response.text
    if family == "cancel":
        assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_guard_no_autoflush_or_commit_on_closed_authority(studio_case):
    case = studio_case
    await _close(case)
    writes = []
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(case.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with case.sessions() as session:
            session.add(AuditEvent(id=str(uuid4()), organization_id=case.actor.organization_id, user_id=case.actor.id, action="studio.synthetic.pending", resource_type="test", resource_id=case.original_id, details={}))
            with pytest.raises(admission.HostMaintenanceClosed):
                await require_studio_admission(session)
            assert session.in_transaction()
            assert not writes
            await session.rollback()
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
async def test_driver_failure_is_sanitized():
    class BrokenSession:
        no_autoflush = __import__("contextlib").nullcontext()
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        async def execute(self, *args, **kwargs):
            raise SQLAlchemyError("synthetic private driver detail")
    with pytest.raises(HTTPException) as raised:
        await studio._require_studio_request_admission(BrokenSession())
    assert raised.value.status_code == 503
    assert raised.value.detail == UNAVAILABLE
    assert "private" not in str(raised.value)


class _CloseProbe(AsyncSession):
    async def execute(self, statement, *args, **kwargs):
        lock = getattr(statement, "_for_update_arg", None)
        if lock is not None and not lock.read and not self.info.get("closer_seen"):
            self.info["closer_seen"] = True
            pid = int(await super().scalar(text("SELECT pg_backend_pid()")))
            self.info["closer_started"].put_nowait(pid)
        return await super().execute(statement, *args, **kwargs)


class _CommitProbe(AsyncSession):
    async def commit(self):
        probe = self.info["studio_probe"]
        await self.flush()
        probe.ready.set()
        await probe.release.wait()
        if probe.fail:
            raise SQLAlchemyError("synthetic commit failure")
        if probe.cancel:
            raise asyncio.CancelledError()
        return await super().commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["job", "revision", "retry"])
@pytest.mark.parametrize("outcome", ["commit", "failure", "cancel"])
async def test_close_waits_for_actual_producer_commit_or_rollback(studio_case, family, outcome):
    case = studio_case
    if family == "retry":
        await _retryable(case)
    before = await _business(case)
    probe = SimpleNamespace(ready=asyncio.Event(), release=asyncio.Event(), fail=outcome == "failure", cancel=outcome == "cancel")
    factory = async_sessionmaker(case.engine, class_=_CommitProbe, expire_on_commit=False, info={"studio_probe": probe})
    async def produce():
        async with factory() as session:
            if family == "job":
                return await studio.create_job(studio.StudioRequest(department="text", title="Lock test", brief="A synthetic briefing to verify locking."), case.actor, session)
            if family == "revision":
                return await studio.create_revision(case.asset_id, studio.StudioRevisionRequest(brief="A synthetic revision briefing for locking.", change_note="Lock test"), case.actor, session)
            return await studio.retry_job(case.original_id, case.actor, session)
    producer = asyncio.create_task(produce())
    closer = None
    try:
        await asyncio.wait_for(probe.ready.wait(), WAIT)
        assert await _business(case) == before
        started = asyncio.Queue()
        close_factory = async_sessionmaker(
            case.engine, class_=_CloseProbe, expire_on_commit=False,
            info={"closer_started": started},
        )
        closer = asyncio.create_task(_close(case, close_factory))
        closer_pid = await asyncio.wait_for(started.get(), WAIT)
        # Observe a real PostgreSQL lock wait, not a timing-only sleep assertion.
        async with case.sessions() as observer:
            async with asyncio.timeout(WAIT):
                while True:
                    waiting = await observer.scalar(
                        text("SELECT count(*) FROM pg_locks WHERE pid=:pid AND NOT granted"),
                        {"pid": closer_pid},
                    )
                    if closer.done():
                        # Surface a real closure failure; never call an expired
                        # control timeout evidence of a correctly held lock.
                        await closer
                        raise AssertionError("closure completed before producer commit")
                    if waiting:
                        break
                    await asyncio.sleep(0.01)
        assert not closer.done()
        probe.release.set()
        if outcome == "commit":
            await asyncio.wait_for(producer, WAIT)
        else:
            with pytest.raises(asyncio.CancelledError if outcome == "cancel" else SQLAlchemyError):
                await asyncio.wait_for(producer, WAIT)
        closed = await asyncio.wait_for(closer, WAIT)
        assert not closed.is_open
        if outcome != "commit":
            assert await _business(case) == before
        denied = await _request(case, family)
        assert denied.status_code == 503
    finally:
        probe.release.set()
        for task in (producer, closer):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (producer, closer) if task is not None), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", [False, True])
async def test_migration_preserves_operation_and_closure_and_replay_is_noop(studio_case, closed):
    case = studio_case
    payload = _schema_six()
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        row.payload = payload
        row.version = 6
        row.status = "closed" if closed else "open"
        row.enabled = not closed
        await session.commit()
    before = await _authority(case)
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    after = await _authority(case)
    assert after["version"] == 7
    assert after["payload"]["schema_version"] == 7
    assert after["payload"]["scope"] == admission.STUDIO_REQUEST_COVERAGE_SCOPE
    assert (after["status"], after["enabled"]) == (before["status"], before["enabled"])
    for name in ("operation_id", "reason", "changed_at", "full_host_closure"):
        assert after["payload"][name] == before["payload"][name]
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration, "downgrade")
        await connection.run_sync(_migration)
    assert await _authority(case) == after
    async with case.sessions() as session:
        snapshot = await admission.read_admission_snapshot(session, required_scope=CONSUMER)
        assert set(snapshot.covered_scopes) == set(admission.STUDIO_REQUEST_COVERAGE_SCOPE.split("+"))
        assert snapshot.full_host_closure is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "version", "future", "scope", "closure", "operation", "timestamp", "reason", "generation"])
async def test_migration_preserves_malformed_authority_instead_of_reseeding(studio_case, mutation):
    case = studio_case
    payload = _schema_six()
    if mutation == "future":
        payload["schema_version"] = 999
    elif mutation == "scope":
        payload["scope"] = "unknown"
    elif mutation == "closure":
        payload["full_host_closure"] = True
    elif mutation == "operation":
        payload["operation_id"] = "invalid"
    elif mutation == "timestamp":
        payload["changed_at"] = "2026-09-18T00:00:00"
    elif mutation == "reason":
        payload["reason"] = ""
    elif mutation == "generation":
        payload["generation"] = True
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        if mutation == "missing":
            await session.delete(row)
        else:
            row.payload = payload
            row.version = 99 if mutation == "version" else 6
        await session.commit()
    before = await _authority(case)
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    assert await _authority(case) == before
