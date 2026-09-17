"""Real isolated-PostgreSQL contracts for project worker maintenance admission.

Provider execution is forbidden. Every test owns a separate database schema; no
production database, application lifecycle, or other worker family is exercised.
"""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    AuditEvent,
    Notification,
    Organization,
    OwnerControlRecord,
    Project,
    ProjectExecution,
    ProjectExecutionWorkerNode,
    User,
    Workspace,
)
from app.services.host_maintenance_admission import (
    DOMAIN,
    RESOURCE_ID,
    SCHEMA_VERSION,
    SCOPE,
    close_admission,
    open_admission,
)
from app.services import project_execution_worker as project_worker_module
from app.services.project_execution_worker import ProjectExecutionWorker


class UnusedRunner:
    def run(self, **_kwargs):
        raise AssertionError("maintenance tests must not execute a provider")


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AuditEvent, Notification, Organization, OwnerControlRecord, Project,
            ProjectExecution, ProjectExecutionWorkerNode, User, Workspace,
        )
    }
    while True:
        dependencies = {
            foreign_key.column.table
            for table in tables
            for foreign_key in table.foreign_keys
        }
        expanded = tables | dependencies
        if expanded == tables:
            return list(tables)
        tables = expanded


@pytest_asyncio.fixture
async def worker_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("project maintenance locking contracts require PostgreSQL/asyncpg")
    database = (url.database or "").lower()
    if re.search(r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])", database) is None:
        raise RuntimeError("project maintenance tests require an isolated test database")

    schema = f"fr06c5d_project_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "application_name": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, tables=_required_tables()
                )
            )
        async with sessions() as session:
            session.add(
                OwnerControlRecord(
                    domain=DOMAIN,
                    resource_id=RESOURCE_ID,
                    status="open",
                    enabled=True,
                    version=1,
                    payload={
                        "schema_version": SCHEMA_VERSION,
                        "scope": SCOPE,
                        "generation": 1,
                        "operation_id": None,
                        "reason": "migration-seed",
                        "changed_at": None,
                        "full_host_closure": False,
                    },
                )
            )
            await session.commit()
        monkeypatch.setattr(settings, "PROJECT_EXECUTION_RESOURCE_CLASSES", "project-build-cpu")
        monkeypatch.setattr(settings, "PROJECT_EXECUTION_JOB_LEASE_SECONDS", 120)
        worker = ProjectExecutionWorker(
            runner=UnusedRunner(), session_factory=sessions,
            worker_id=f"maintenance-{uuid4().hex[:16]}", capacity=1,
        )
        yield SimpleNamespace(
            sessions=sessions, engine=engine, worker=worker,
            operation_id=str(uuid4()), application_name=schema,
        )
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


async def _seed(case, kind="queued"):
    suffix = uuid4().hex
    organization = Organization(
        id=str(uuid4()), name="Maintenance test",
        slug=f"maintenance-org-{suffix}", plan="enterprise", status="active",
    )
    user = User(
        id=str(uuid4()), organization_id=organization.id,
        role_id=None, email=f"maintenance-{suffix}@example.com",
        name="Synthetic operator", password_hash="unused", status="active",
    )
    workspace = Workspace(
        id=str(uuid4()), organization_id=organization.id,
        name="Maintenance workspace", slug=f"maintenance-ws-{suffix}", status="active",
    )
    project = Project(
        id=str(uuid4()), organization_id=organization.id,
        workspace_id=workspace.id, owner_id=user.id, name="Synthetic project",
        slug=f"maintenance-project-{suffix}", description="Synthetic guarded job",
        status="planning", priority="high", progress=0, tags=["maintenance-test"],
    )
    execution = ProjectExecution(
        id=str(uuid4()), organization_id=organization.id,
        workspace_id=workspace.id, project_id=project.id, requested_by_id=user.id,
        mode="full", provider="openai", status="queued", stage="queued",
        progress=0, objective=project.description, external_processing_confirmed=True,
        budget_cap_usd=0.05, result_summary={}, resource_class="project-build-cpu",
        priority_rank=200, attempts=0, max_attempts=3,
    )
    if kind != "queued":
        now = datetime.now(UTC)
        execution.status = "running"
        execution.stage = "provider_execution"
        execution.progress = 20
        execution.attempts = 3 if kind == "exhausted" else 1
        execution.fencing_token = 4
        execution.lease_token = uuid4().hex
        execution.lease_owner = "previous-synthetic-worker"
        execution.lease_expires_at = now - timedelta(seconds=1)
        execution.updated_at = now - timedelta(hours=1)
        project.status = "in_progress"
        project.progress = 20
    async with case.sessions() as session:
        session.add(organization)
        await session.flush()
        session.add_all([user, workspace])
        await session.flush()
        session.add(project)
        await session.flush()
        session.add(execution)
        await session.commit()
    return execution.id


async def _snapshot(case, execution_id):
    async with case.sessions() as session:
        row = await session.get(ProjectExecution, execution_id)
        assert row is not None
        project = await session.get(Project, row.project_id)
        assert project is not None
        return {
            "execution": {column.key: getattr(row, column.key) for column in inspect(type(row)).column_attrs},
            "project": {column.key: getattr(project, column.key) for column in inspect(type(project)).column_attrs},
            "audit_count": await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.organization_id == row.organization_id)),
            "notification_count": await session.scalar(select(func.count()).select_from(Notification).where(Notification.organization_id == row.organization_id)),
        }


async def _close(case):
    return await close_admission(
        operation_id=case.operation_id, expected_generation=1,
        reason="isolated-project-worker-test", session_factory=case.sessions,
    )


async def _reopen(case, closed):
    return await open_admission(
        operation_id=case.operation_id, expected_generation=closed.generation,
        reason="isolated-project-worker-resume", session_factory=case.sessions,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["queued", "recovery", "exhausted"])
async def test_closed_claim_and_reaper_preserve_jobs_and_idle_health(worker_case, kind):
    case = worker_case
    execution_id = await _seed(case, kind)
    await _close(case)
    before = await _snapshot(case, execution_id)

    assert await case.worker.claim() is None
    assert await case.worker.reap_exhausted_leases() == 0
    assert await case.worker.run_once() is False
    assert await _snapshot(case, execution_id) == before

    # Closed admission is ordinary idle, so the existing heartbeat can continue.
    await case.worker.register_worker(active_count=0, status="online")
    async with case.sessions() as session:
        node = await session.get(ProjectExecutionWorkerNode, case.worker.worker_id)
        assert node is not None and node.status == "online" and node.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["queued", "recovery"])
async def test_valid_generation_reopen_resumes_claim_exactly_once(worker_case, kind):
    case = worker_case
    execution_id = await _seed(case, kind)
    closed = await _close(case)
    assert await case.worker.claim() is None
    before = (await _snapshot(case, execution_id))["execution"]

    await _reopen(case, closed)
    claimed = await case.worker.claim()
    assert claimed is not None and claimed[0] == execution_id
    assert await case.worker.claim() is None
    after = (await _snapshot(case, execution_id))["execution"]
    assert after["status"] == "running"
    assert after["attempts"] == before["attempts"] + 1
    assert after["fencing_token"] == before["fencing_token"] + 1
    assert after["lease_owner"] == case.worker.worker_id


@pytest.mark.asyncio
async def test_valid_generation_reopen_resumes_exhausted_lease_reaper(worker_case):
    case = worker_case
    execution_id = await _seed(case, "exhausted")
    closed = await _close(case)
    assert await case.worker.reap_exhausted_leases() == 0

    await _reopen(case, closed)
    assert await case.worker.reap_exhausted_leases() == 1
    assert await case.worker.reap_exhausted_leases() == 0
    row = (await _snapshot(case, execution_id))["execution"]
    assert row["status"] == "failed" and row["stage"] == "dead_lettered"
    assert row["lease_owner"] is None and row["lease_expires_at"] is None


@pytest.mark.asyncio
async def test_prior_owned_claim_can_renew_and_complete_after_close(worker_case):
    case = worker_case
    execution_id = await _seed(case)
    claimed = await case.worker.claim()
    assert claimed is not None and claimed[0] == execution_id
    await _close(case)
    assert await case.worker.claim() is None

    # Existing ownership/fencing remains authoritative during maintenance.
    await case.worker.renew(*claimed)
    renewed = (await _snapshot(case, execution_id))["execution"]
    assert renewed["status"] == "running"
    assert renewed["lease_expires_at"] > datetime.now(UTC)
    await case.worker.complete(
        *claimed,
        {
            "success": True, "phase": 36, "mode": "full", "approved": True,
            "readiness_score": 1.0, "workforce": [], "production_modified": False,
        },
    )
    finished = (await _snapshot(case, execution_id))["execution"]
    assert finished["status"] == "completed"
    assert finished["attempts"] == 1
    assert finished["lease_owner"] is None and finished["lease_expires_at"] is None
    assert await case.worker.claim() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_state", ["missing", "malformed"])
async def test_unavailable_authority_is_idle_without_job_mutation(worker_case, authority_state):
    case = worker_case
    execution_id = await _seed(case, "exhausted")
    async with case.sessions() as session:
        if authority_state == "missing":
            await session.execute(
                delete(OwnerControlRecord).where(
                    OwnerControlRecord.domain == DOMAIN,
                    OwnerControlRecord.resource_id == RESOURCE_ID,
                )
            )
        else:
            row = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == DOMAIN,
                    OwnerControlRecord.resource_id == RESOURCE_ID,
                )
            )
            assert row is not None
            row.payload = {**row.payload, "generation": "not-an-integer"}
        await session.commit()
    before = await _snapshot(case, execution_id)
    assert await case.worker.claim() is None
    assert await case.worker.reap_exhausted_leases() == 0
    assert await _snapshot(case, execution_id) == before


@pytest.mark.asyncio
async def test_database_failure_propagates_without_claim_or_reaper_mutation(worker_case):
    case = worker_case
    execution_id = await _seed(case, "exhausted")
    before = await _snapshot(case, execution_id)
    async with case.engine.begin() as connection:
        await connection.run_sync(OwnerControlRecord.__table__.drop)

    with pytest.raises(DBAPIError):
        await case.worker.claim()
    with pytest.raises(DBAPIError):
        await case.worker.reap_exhausted_leases()
    assert await _snapshot(case, execution_id) == before


@pytest.mark.asyncio
async def test_close_between_reaper_and_claim_prevents_new_lease(worker_case, monkeypatch):
    case = worker_case
    execution_id = await _seed(case)
    before = await _snapshot(case, execution_id)
    real_reaper = case.worker.reap_exhausted_leases

    async def close_after_reaper(*args, **kwargs):
        result = await real_reaper(*args, **kwargs)
        await _close(case)
        return result

    monkeypatch.setattr(case.worker, "reap_exhausted_leases", close_after_reaper)
    assert await case.worker.claim() is None
    assert await _snapshot(case, execution_id) == before


@pytest.mark.asyncio
async def test_close_waits_for_actual_project_claim_transaction(worker_case, monkeypatch):
    case = worker_case
    execution_id = await _seed(case)
    admitted = asyncio.Event()
    release_claim = asyncio.Event()
    claimant_pid = None
    guard_calls = 0
    real_guard = project_worker_module.is_admission_open

    async def pause_claim_after_authority_lock(session):
        nonlocal guard_calls, claimant_pid
        allowed = await real_guard(session)
        guard_calls += 1
        # The first transaction is the reaper; the second is the real claim.
        if allowed and guard_calls == 2:
            claimant_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            admitted.set()
            await release_claim.wait()
        return allowed

    async def wait_for_blocked_closer():
        async with asyncio.timeout(10):
            while True:
                async with case.sessions() as observer:
                    blocked = await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name = :application_name "
                            "AND :claimant_pid = ANY(pg_blocking_pids(pid))"
                        ),
                        {
                            "application_name": case.application_name,
                            "claimant_pid": claimant_pid,
                        },
                    )
                if blocked:
                    return
                await asyncio.sleep(0.01)

    monkeypatch.setattr(
        project_worker_module, "is_admission_open", pause_claim_after_authority_lock
    )
    claim_task = asyncio.create_task(case.worker.claim())
    close_task = None
    try:
        await asyncio.wait_for(admitted.wait(), timeout=10)
        close_task = asyncio.create_task(_close(case))
        await wait_for_blocked_closer()
        assert not close_task.done()

        release_claim.set()
        claimed = await asyncio.wait_for(claim_task, timeout=10)
        assert claimed is not None and claimed[0] == execution_id
        await asyncio.wait_for(close_task, timeout=10)
        row = (await _snapshot(case, execution_id))["execution"]
        assert row["status"] == "running" and row["attempts"] == 1
        assert await case.worker.claim() is None
    finally:
        release_claim.set()
        pending = [task for task in (claim_task, close_task) if task is not None]
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
