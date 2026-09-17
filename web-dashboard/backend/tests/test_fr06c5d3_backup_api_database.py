"""PostgreSQL and HTTP contracts for backup API maintenance admission.

Every test owns a random schema in an explicitly test-named database. The app
contains only the four existing routers under test, with isolated request and
independent Owner audit sessions. Storage, executors and external I/O are denied.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.backup_admission import (
    BACKUP_ADMISSION_CLOSED_DETAIL,
    BACKUP_ADMISSION_UNAVAILABLE_DETAIL,
)
from app.api.owner import control_plane, operations_integration
from app.api.v1.endpoints import backups, databases
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AuditEvent,
    BackupRecord,
    DisasterRecoveryRun,
    HostMaintenanceWorkCycle,
    Organization,
    OwnerCommandRecord,
    OwnerControlRecord,
    Role,
    User,
)
from app.services import backup_executor, offsite_backup, three_d_asset_backup
from app.services.host_maintenance_admission import (
    COVERAGE_SCHEMA_VERSION,
    COVERAGE_SCOPE,
    DOMAIN,
    RESOURCE_ID,
    SCHEMA_VERSION,
    SCOPE,
    close_admission,
    open_admission,
)


WAIT_SECONDS = 10
ROUTES = (
    "backup",
    "restore",
    "dr-test",
    "database",
    "owner-create",
    "owner-restore",
    "owner-drill",
    "operations-recover",
)
OWNER_ACTIONS = {
    "owner-create": ("recovery", "create-backup"),
    "owner-restore": ("recovery", "validate-restore"),
    "owner-drill": ("recovery", "dr-drill"),
    "operations-recover": ("operations-integration", "recover"),
}
BACKUP_ROUTES = {"backup", "database", "owner-create"}
ROUTE_MODULES = {
    "backup": backups,
    "restore": backups,
    "dr-test": backups,
    "database": databases,
    "owner-create": control_plane,
    "owner-restore": control_plane,
    "owner-drill": control_plane,
    "operations-recover": operations_integration,
}


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AuditEvent,
            BackupRecord,
            DisasterRecoveryRun,
            HostMaintenanceWorkCycle,
            Organization,
            OwnerCommandRecord,
            OwnerControlRecord,
            Role,
            User,
        )
    }
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return list(tables)
        tables = expanded


@pytest_asyncio.fixture
async def api_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("backup API admission contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])",
        (url.database or "").lower(),
    ) is None:
        raise RuntimeError("backup API tests require an isolated test database")

    schema = f"fr06c5d3_api_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {"search_path": schema, "application_name": schema}
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor_id, organization_id, role_id = (str(uuid4()) for _ in range(3))
    operation_id = str(uuid4())
    completed_id = str(uuid4())
    actor = UserRecord(
        id=actor_id,
        email=f"owner-{actor_id}@example.test",
        name="Isolated Backup Owner",
        role="Super Owner",
        password_hash="unused-synthetic-hash",
        organization_id=organization_id,
        organization_name="Isolated Backup Organization",
        organization_plan="enterprise",
        permissions=["*"],
    )
    case = SimpleNamespace(
        sessions=sessions,
        engine=engine,
        schema=schema,
        actor=actor,
        operation_id=operation_id,
        completed_id=completed_id,
        requests=[],
        auxiliary_sessions=[],
        artifact_checks=[],
        health_checks=[],
        forbidden_attempts=[],
        advisory_calls=[],
        artifact_ready=True,
    )
    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda connection: Base.metadata.create_all(
                    connection, tables=_required_tables()
                )
            )
        async with sessions() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name=actor.organization_name,
                    slug=f"isolated-{organization_id}",
                    plan="enterprise",
                    status="active",
                )
            )
            await session.flush()
            session.add(
                Role(
                    id=role_id,
                    organization_id=organization_id,
                    name="Super Owner",
                    status="active",
                )
            )
            await session.flush()
            session.add(
                User(
                    id=actor_id,
                    organization_id=organization_id,
                    role_id=role_id,
                    name=actor.name,
                    email=actor.email,
                    password_hash=actor.password_hash,
                    status="active",
                )
            )
            session.add(
                OwnerControlRecord(
                    domain=DOMAIN,
                    resource_id=RESOURCE_ID,
                    status="open",
                    enabled=True,
                    version=2,
                    payload={
                        "schema_version": COVERAGE_SCHEMA_VERSION,
                        "scope": COVERAGE_SCOPE,
                        "generation": 2,
                        "operation_id": operation_id,
                        "reason": "synthetic-private-authority-note",
                        "changed_at": datetime.now(UTC).isoformat(),
                        "full_host_closure": False,
                    },
                )
            )
            session.add(
                BackupRecord(
                    id=completed_id,
                    kind="synthetic-completed",
                    scope="platform",
                    status="completed",
                    location="/synthetic/no-io/completed.dump",
                    checksum="a" * 64,
                    size_bytes=64,
                    completed_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await session.commit()

        async def request_db():
            async with sessions() as session:
                case.requests.append(session)
                yield session

        def auxiliary_session():
            session = sessions()
            case.auxiliary_sessions.append(session)
            return session

        async def actor_dependency():
            return case.actor

        async def artifact_readiness(backup, *, verify_checksum):
            assert verify_checksum is False
            case.artifact_checks.append(backup.id if backup is not None else None)
            return bool(
                case.artifact_ready
                and backup is not None
                and backup.status == "completed"
                and backup.location
                and backup.checksum
                and backup.size_bytes
                and backup.size_bytes > 0
            )

        async def health_readiness(_session):
            case.health_checks.append("read-only-health")
            return [
                {
                    "id": "postgres-primary",
                    "name": "PostgreSQL",
                    "status": "healthy",
                    "detail": "Synthetic dependency evidence",
                }
            ]

        async def publish_empty(notifications):
            assert not notifications

        def forbidden_sync(*_args, **_kwargs):
            case.forbidden_attempts.append("runtime-io")
            raise AssertionError("backup API tests must not perform runtime I/O")

        async def forbidden_async(*_args, **_kwargs):
            forbidden_sync()

        for module in (backups, databases, control_plane, operations_integration):
            original_lock = module.acquire_enqueue_lock

            async def observed_lock(session, key, _original=original_lock):
                case.advisory_calls.append(key)
                await _original(session, key)

            monkeypatch.setattr(module, "acquire_enqueue_lock", observed_lock)

        monkeypatch.setattr(control_plane, "SessionLocal", auxiliary_session)
        monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_readiness)
        monkeypatch.setattr(
            operations_integration, "_backup_artifact_ready", artifact_readiness
        )
        monkeypatch.setattr(operations_integration, "_health_items", health_readiness)
        monkeypatch.setattr(control_plane.communications, "publish_many", publish_empty)
        monkeypatch.setattr(control_plane, "get_backup_executor", forbidden_sync)
        monkeypatch.setattr(backup_executor, "get_backup_executor", forbidden_sync)
        monkeypatch.setattr(
            backup_executor.BackupExecutor, "create_backup", forbidden_async
        )
        monkeypatch.setattr(
            offsite_backup.OffsiteBackupReplicator, "replicate", forbidden_sync
        )
        monkeypatch.setattr(
            three_d_asset_backup.ThreeDAssetSnapshotExecutor,
            "create_snapshot",
            forbidden_sync,
        )
        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_async)
        monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_async)
        monkeypatch.setattr(subprocess, "Popen", forbidden_sync)
        for name in ("mkdir", "chmod", "unlink", "rename", "replace", "write_text", "write_bytes"):
            monkeypatch.setattr(Path, name, forbidden_sync)
        monkeypatch.setattr(settings, "BACKUP_THREE_D_ASSETS_ENABLED", False)
        monkeypatch.setattr(settings, "BACKUP_OFFSITE_ENABLED", False)

        app = FastAPI()
        app.include_router(backups.router, prefix="/api/v1/backups")
        app.include_router(databases.router, prefix="/api/v1/infrastructure/databases")
        app.include_router(control_plane.router, prefix="/api/v1")
        app.include_router(operations_integration.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = request_db
        # Keep each router's real require_super_owner dependency in the chain.
        app.dependency_overrides[current_user] = actor_dependency
        case.app = app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://isolated.test",
        ) as client:
            case.client = client
            yield case
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


def _request_spec(case, route):
    if route == "backup":
        return "/api/v1/backups", {"params": {"name": "on-demand", "scope": "platform"}}
    if route == "restore":
        return f"/api/v1/backups/{case.completed_id}/restore", {"params": {"dry_run": True}}
    if route == "dr-test":
        return "/api/v1/backups/dr/test", {}
    if route == "database":
        return "/api/v1/infrastructure/databases/postgres-primary/backup", {}
    if route in OWNER_ACTIONS and route != "operations-recover":
        _, action = OWNER_ACTIONS[route]
        payload = (
            {"kind": "on-demand", "scope": "platform"}
            if route == "owner-create"
            else {"region": "synthetic-region"}
        )
        return (
            f"/api/v1/owner/resources/recovery/{case.completed_id}/actions",
            {"json": {"action": action, "payload": payload}},
        )
    assert route == "operations-recover"
    return (
        "/api/v1/owner/operations-integration/backup/command",
        {"json": {"action": "recover"}},
    )


async def _post(case, route):
    path, kwargs = _request_spec(case, route)
    return await case.client.post(path, **kwargs)


async def _close(case):
    return await close_admission(
        operation_id=case.operation_id,
        expected_generation=2,
        reason="isolated-api-close",
        session_factory=case.sessions,
    )


async def _reopen(case, closed):
    return await open_admission(
        operation_id=case.operation_id,
        expected_generation=closed.generation,
        reason="isolated-api-reopen",
        session_factory=case.sessions,
    )


async def _business_snapshot(case):
    async with case.sessions() as session:
        result = {}
        for model in (BackupRecord, DisasterRecoveryRun, HostMaintenanceWorkCycle):
            rows = list((await session.scalars(select(model).order_by(model.id))).all())
            result[model.__tablename__] = [
                {
                    column.key: getattr(row, column.key)
                    for column in inspect(model).column_attrs
                }
                for row in rows
            ]
        return result


async def _owner_evidence(case, route):
    domain, action = OWNER_ACTIONS[route]
    async with case.sessions() as session:
        commands = list(
            (
                await session.scalars(
                    select(OwnerCommandRecord).where(
                        OwnerCommandRecord.actor_id == case.actor.id,
                        OwnerCommandRecord.domain == domain,
                        OwnerCommandRecord.action == action,
                    )
                )
            ).all()
        )
        audits = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.user_id == case.actor.id,
                        AuditEvent.action == f"owner.{domain}.{action}",
                    )
                )
            ).all()
        )
        return commands, audits


async def _assert_failed_owner_audit(case, route, detail):
    commands, audits = await _owner_evidence(case, route)
    assert len(commands) == 1 and len(audits) == 1
    command, audit = commands[0], audits[0]
    assert command.status == "failed" and command.completed_at is not None
    assert command.result == {"statusCode": 503, "detail": detail}
    assert command.error == detail
    assert audit.organization_id == case.actor.organization_id
    assert audit.details == {"status": "failed", "result": command.result}
    assert case.auxiliary_sessions
    assert all(
        auxiliary is not request
        for auxiliary in case.auxiliary_sessions
        for request in case.requests
    )


def _assert_rejected(response, detail):
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": detail}
    assert "retry-after" not in response.headers
    assert "synthetic-private-authority-note" not in response.text


async def _assert_success(case, route, response):
    assert response.status_code == (200 if route in OWNER_ACTIONS else 202), response.text
    async with case.sessions() as session:
        pending_backups = list(
            (
                await session.scalars(
                    select(BackupRecord).where(BackupRecord.status == "pending")
                )
            ).all()
        )
        pending_runs = list(
            (
                await session.scalars(
                    select(DisasterRecoveryRun).where(DisasterRecoveryRun.status == "pending")
                )
            ).all()
        )
        assert await session.scalar(
            select(func.count()).select_from(HostMaintenanceWorkCycle)
        ) == 0
    assert len(pending_backups) == (1 if route in BACKUP_ROUTES else 0)
    assert len(pending_runs) == (0 if route in BACKUP_ROUTES else 1)
    job = (pending_backups or pending_runs)[0]
    body = response.json()
    if route in BACKUP_ROUTES:
        assert job.scope == "platform"
    else:
        assert job.details["backup_id"] == case.completed_id
        assert job.details["dry_run"] is True
        assert job.details["requested_by"] == case.actor.id
        assert job.operation == (
            "restore_validation" if route in {"restore", "owner-restore"} else "test"
        )
    if route == "backup":
        assert body["id"] == job.id and body["status"] == "pending"
        assert body["kind"] == "on-demand" and body["artifact_ready"] is False
    elif route == "restore":
        assert body["run_id"] == job.id and body["backup_id"] == case.completed_id
        assert body["status"] == "pending" and body["dry_run"] is True
    elif route == "dr-test":
        assert body["status"] == "pending" and body["run"]["id"] == job.id
        assert body["run"]["operation"] == "test"
    elif route == "database":
        assert body == {
            "backup_id": job.id, "database_id": "postgres-primary", "status": "pending"
        }
    elif route.startswith("owner-"):
        assert body["domain"] == "recovery"
        assert any(item["id"] == job.id and item["status"] == "pending" for item in body["items"])
    else:
        assert set(body) == {"generated_at", "completion", "targets"}
        assert any(target["id"] == "backup" for target in body["targets"])
    assert not case.forbidden_attempts
    return job.id


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ROUTES)
async def test_each_enqueue_closes_without_work_and_reopens_with_original_contract(
    api_case, route
):
    case = api_case
    closed = await _close(case)
    before = await _business_snapshot(case)
    response = await _post(case, route)
    _assert_rejected(response, BACKUP_ADMISSION_CLOSED_DETAIL)
    assert await _business_snapshot(case) == before
    assert not case.artifact_checks and not case.health_checks
    assert not case.advisory_calls and not case.forbidden_attempts
    if route in OWNER_ACTIONS:
        await _assert_failed_owner_audit(case, route, BACKUP_ADMISSION_CLOSED_DETAIL)
    else:
        async with case.sessions() as session:
            assert await session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.user_id == case.actor.id
                )
            ) == 0

    await _reopen(case, closed)
    await _assert_success(case, route, await _post(case, route))
    after_success = await _business_snapshot(case)
    duplicate = await _post(case, route)
    assert duplicate.status_code == 409, duplicate.text
    assert await _business_snapshot(case) == after_success
    if route in OWNER_ACTIONS:
        commands, audits = await _owner_evidence(case, route)
        assert sorted(command.status for command in commands) == [
            "completed", "failed", "failed"
        ]
        assert sorted(audit.details["status"] for audit in audits) == [
            "completed", "failed", "failed"
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authority_state", ["missing", "malformed", "unknown", "legacy", "database-error"]
)
async def test_unavailable_authority_rejects_every_enqueue_and_preserves_failed_audits(
    api_case, authority_state
):
    case = api_case
    async with case.sessions() as session:
        authority = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == DOMAIN,
                OwnerControlRecord.resource_id == RESOURCE_ID,
            )
        )
        assert authority is not None
        if authority_state == "missing":
            await session.delete(authority)
        elif authority_state == "malformed":
            authority.payload = {**authority.payload, "full_host_closure": True}
        elif authority_state == "unknown":
            authority.payload = {**authority.payload, "schema_version": 999}
        elif authority_state == "legacy":
            authority.version = 1
            authority.payload = {
                "schema_version": SCHEMA_VERSION,
                "scope": SCOPE,
                "generation": 1,
                "operation_id": None,
                "reason": "migration-seed",
                "changed_at": None,
                "full_host_closure": False,
            }
        else:
            # Cause a genuine PostgreSQL read error in this isolated schema.
            # The separate failed-command tables remain available for auditing.
            await session.execute(
                text("ALTER TABLE owner_control_records RENAME TO unavailable_admission")
            )
        await session.commit()
    before = await _business_snapshot(case)

    for route in ROUTES:
        _assert_rejected(
            await _post(case, route), BACKUP_ADMISSION_UNAVAILABLE_DETAIL
        )
        assert await _business_snapshot(case) == before, route
        if route in OWNER_ACTIONS:
            await _assert_failed_owner_audit(
                case, route, BACKUP_ADMISSION_UNAVAILABLE_DETAIL
            )
    assert not case.artifact_checks and not case.health_checks
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["anonymous", "Owner"])
async def test_authentication_and_super_owner_authorization_precede_admission(
    api_case, role
):
    case = api_case
    await _close(case)
    if role == "anonymous":
        del case.app.dependency_overrides[current_user]
    else:
        case.actor = replace(case.actor, role=role, permissions=[])
    before = await _business_snapshot(case)
    for route in ROUTES:
        response = await _post(case, route)
        assert response.status_code == (401 if role == "anonymous" else 403), (
            route, response.text
        )
        if role == "anonymous":
            assert response.headers["www-authenticate"] == "Bearer"
        else:
            assert response.json() == {"detail": "Super Owner access required"}
    assert await _business_snapshot(case) == before
    assert not case.artifact_checks and not case.health_checks
    async with case.sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(OwnerCommandRecord)
        ) == 0


@pytest.mark.asyncio
async def test_open_admission_preserves_input_target_and_live_restore_rejections(api_case):
    case = api_case
    recovery_path = f"/api/v1/owner/resources/recovery/{case.completed_id}/actions"
    checks = [
        ("/api/v1/backups", {"params": {"name": " ", "scope": "platform"}}, 422),
        ("/api/v1/backups", {"params": {"name": "x" * 81}}, 422),
        (f"/api/v1/backups/{case.completed_id}/restore", {"params": {"dry_run": False}}, 409),
        (f"/api/v1/backups/{uuid4()}/restore", {}, 404),
        ("/api/v1/infrastructure/databases/redis-primary/backup", {}, 409),
        (recovery_path, {"json": {"action": "create-backup", "payload": {"kind": ""}}}, 422),
        (recovery_path, {"json": {"action": "validate-restore", "payload": {"region": "x" * 121}}}, 422),
        (recovery_path, {"json": {"action": "unsupported-recovery", "payload": {}}}, 422),
        ("/api/v1/owner/operations-integration/missing/command", {"json": {"action": "recover"}}, 404),
        ("/api/v1/owner/operations-integration/postgres-primary/command", {"json": {"action": "recover"}}, 409),
        ("/api/v1/owner/operations-integration/backup/command", {"json": {"action": "unsupported"}}, 422),
    ]
    before = await _business_snapshot(case)
    for path, kwargs, status in checks:
        response = await case.client.post(path, **kwargs)
        assert response.status_code == status, (path, response.text)
        assert await _business_snapshot(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
async def test_closed_backup_admission_does_not_gate_readonly_operations_validation(api_case):
    case = api_case
    await _close(case)
    before = await _business_snapshot(case)
    response = await case.client.post(
        "/api/v1/owner/operations-integration/backup/command",
        json={"action": "validate"},
    )
    assert response.status_code == 200, response.text
    assert any(item["id"] == "backup" for item in response.json()["targets"])
    assert await _business_snapshot(case) == before
    async with case.sessions() as session:
        commands = list((await session.scalars(select(OwnerCommandRecord))).all())
        assert len(commands) == 1 and commands[0].status == "completed"
        assert commands[0].action == "validate"
        assert commands[0].result["health_rechecked"] is True
    assert not case.forbidden_attempts


@pytest.mark.asyncio
async def test_open_admission_keeps_readonly_artifact_readiness_required(api_case):
    case = api_case
    case.artifact_ready = False
    before = await _business_snapshot(case)
    for route in ("owner-restore", "owner-drill", "operations-recover"):
        response = await _post(case, route)
        assert response.status_code == 409, (route, response.text)
        assert await _business_snapshot(case) == before
    assert case.artifact_checks and not case.forbidden_attempts


async def _wait_for_close_blocked_by(case, holder_pid):
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            async with case.sessions() as observer:
                blocked = await observer.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name = :application_name "
                        "AND :holder_pid = ANY(pg_blocking_pids(pid))"
                    ),
                    {"application_name": case.schema, "holder_pid": holder_pid},
                )
            if blocked:
                return
            await asyncio.sleep(0.01)


async def _settle_tasks(*tasks):
    present = [task for task in tasks if task is not None]
    for task in present:
        if not task.done():
            task.cancel()
    if present:
        await asyncio.wait_for(
            asyncio.gather(*present, return_exceptions=True), timeout=WAIT_SECONDS
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "force_conflict"),
    [
        ("backup", False),
        ("restore", False),
        ("database", False),
        ("owner-create", False),
        ("operations-recover", False),
        ("backup", True),
    ],
    ids=[
        "backup-commit",
        "restore-commit",
        "database-commit",
        "owner-commit",
        "operations-commit",
        "backup-rollback",
    ],
)
async def test_actual_enqueue_holds_shared_admission_until_its_commit_or_rollback(
    api_case, monkeypatch, route, force_conflict
):
    case = api_case
    if force_conflict:
        async with case.sessions() as session:
            session.add(
                BackupRecord(
                    kind="synthetic-existing", scope="platform", status="pending"
                )
            )
            await session.commit()
    before = await _business_snapshot(case)
    at_advisory_boundary = asyncio.Event()
    release_enqueue = asyncio.Event()
    at_commit_boundary = asyncio.Event()
    release_commit = asyncio.Event()
    holder_pid = None
    enqueue_transaction = None
    module = ROUTE_MODULES[route]
    original_lock = module.acquire_enqueue_lock

    async def held_advisory_boundary(session, key):
        nonlocal holder_pid, enqueue_transaction
        assert any(session is request for request in case.requests)
        holder_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        enqueue_transaction = await session.scalar(text("SELECT txid_current()"))
        actual_request_commit = session.commit

        async def held_request_commit():
            assert not force_conflict, "conflicting enqueue must roll back without commit"
            assert await session.scalar(
                text("SELECT txid_current()")
            ) == enqueue_transaction
            assert await session.scalar(
                text("SELECT pg_backend_pid()")
            ) == holder_pid
            model = BackupRecord if route in BACKUP_ROUTES else DisasterRecoveryRun
            pending = list(
                (
                    await session.scalars(
                        select(model).where(model.status == "pending")
                    )
                ).all()
            )
            assert len(pending) == 1
            pending_id = pending[0].id
            assert pending_id not in {
                row["id"] for row in before[model.__tablename__]
            }
            # The actual request transaction sees its flushed job. A separate
            # committed connection must still see no such job before publication.
            async with case.sessions() as observer:
                assert await observer.get(model, pending_id) is None
            at_commit_boundary.set()
            await release_commit.wait()
            await actual_request_commit()

        # Wrap this request instance only. Close, observer, default-seeding and
        # independent failed-audit sessions retain their real commits untouched.
        monkeypatch.setattr(session, "commit", held_request_commit)
        at_advisory_boundary.set()
        await release_enqueue.wait()
        # This remains the real pg_advisory_xact_lock. Only the scheduling of
        # entry is controlled; no fake lock supplies the concurrency evidence.
        await original_lock(session, key)

    monkeypatch.setattr(module, "acquire_enqueue_lock", held_advisory_boundary)
    request_task = asyncio.create_task(_post(case, route))
    close_task = None
    try:
        await asyncio.wait_for(at_advisory_boundary.wait(), timeout=WAIT_SECONDS)
        close_task = asyncio.create_task(_close(case))
        await _wait_for_close_blocked_by(case, holder_pid)
        assert not request_task.done() and not close_task.done()

        release_enqueue.set()
        if not force_conflict:
            await asyncio.wait_for(at_commit_boundary.wait(), timeout=WAIT_SECONDS)
            await _wait_for_close_blocked_by(case, holder_pid)
            assert not request_task.done() and not close_task.done()
            release_commit.set()
        response = await asyncio.wait_for(request_task, timeout=WAIT_SECONDS)
        await asyncio.wait_for(close_task, timeout=WAIT_SECONDS)
        if force_conflict:
            assert response.status_code == 409, response.text
            assert await _business_snapshot(case) == before
        else:
            await _assert_success(case, route, response)
        after = await _business_snapshot(case)
        _assert_rejected(await _post(case, route), BACKUP_ADMISSION_CLOSED_DETAIL)
        assert await _business_snapshot(case) == after
        assert not case.forbidden_attempts
    finally:
        release_enqueue.set()
        release_commit.set()
        await _settle_tasks(request_task, close_task)


@pytest.mark.asyncio
async def test_synthetic_first_owner_default_commit_precedes_enqueue_admission_check(
    api_case, monkeypatch
):
    case = api_case
    default_id = "synthetic-first-recovery-default"
    # Recovery currently has no production CONTROL_DEFAULTS entry. Inject one
    # explicitly to protect the first-use commit boundary against future defaults.
    monkeypatch.setitem(
        control_plane.CONTROL_DEFAULTS,
        "recovery",
        [
            {
                "id": default_id,
                "name": "Synthetic first-use default",
                "status": "active",
                "enabled": True,
            }
        ],
    )
    defaults_committed = asyncio.Event()
    release_mutation = asyncio.Event()
    real_ensure_defaults = control_plane._ensure_defaults

    async def pause_after_real_default_commit(session, domain):
        await real_ensure_defaults(session, domain)
        if domain == "recovery" and not defaults_committed.is_set():
            assert not session.in_transaction()
            async with case.sessions() as observer:
                seeded = await observer.scalar(
                    select(OwnerControlRecord).where(
                        OwnerControlRecord.domain == "recovery",
                        OwnerControlRecord.resource_id == default_id,
                    )
                )
                assert seeded is not None
                assert await observer.scalar(
                    select(func.count()).select_from(OwnerCommandRecord)
                ) == 0
            defaults_committed.set()
            await release_mutation.wait()

    monkeypatch.setattr(control_plane, "_ensure_defaults", pause_after_real_default_commit)
    path, kwargs = _request_spec(case, "owner-create")
    kwargs["json"]["payload"]["secret"] = "synthetic-private-request-value"
    before = await _business_snapshot(case)
    request_task = asyncio.create_task(case.client.post(path, **kwargs))
    try:
        await asyncio.wait_for(defaults_committed.wait(), timeout=WAIT_SECONDS)
        # Close wins after the real seeding commit but before the actual mutation.
        await asyncio.wait_for(_close(case), timeout=WAIT_SECONDS)
        release_mutation.set()
        response = await asyncio.wait_for(request_task, timeout=WAIT_SECONDS)
        _assert_rejected(response, BACKUP_ADMISSION_CLOSED_DETAIL)
        assert await _business_snapshot(case) == before
        await _assert_failed_owner_audit(
            case, "owner-create", BACKUP_ADMISSION_CLOSED_DETAIL
        )
        commands, _ = await _owner_evidence(case, "owner-create")
        assert commands[0].request["secret"] == "[REDACTED]"
        assert "synthetic-private-request-value" not in json.dumps(commands[0].request)
        assert not case.advisory_calls and not case.forbidden_attempts
        async with case.sessions() as observer:
            assert await observer.scalar(
                select(func.count()).select_from(OwnerControlRecord).where(
                    OwnerControlRecord.domain == "recovery",
                    OwnerControlRecord.resource_id == default_id,
                )
            ) == 1
    finally:
        release_mutation.set()
        await _settle_tasks(request_task)


@pytest.mark.asyncio
async def test_injected_nested_default_seed_preserves_actual_owner_enqueue_lock(
    api_case, monkeypatch
):
    case = api_case
    nested_domain = "synthetic-nested-backup-default"
    default_id = "synthetic-nested-default"
    # No current recovery or operations snapshot seeds this domain. Inject the
    # extra nested call deliberately, while exercising the real helper and its
    # independent SessionLocal transaction with owner_mutation_active set.
    monkeypatch.setitem(
        control_plane.CONTROL_DEFAULTS,
        nested_domain,
        [
            {
                "id": default_id,
                "name": "Synthetic nested default",
                "status": "active",
                "enabled": True,
            }
        ],
    )
    nested_seed_committed = asyncio.Event()
    release_enqueue = asyncio.Event()
    holder_pid = None
    original_lock = control_plane.acquire_enqueue_lock

    async def inject_real_nested_seed(session, key):
        nonlocal holder_pid
        assert session.info.get("owner_mutation_active") is True
        holder_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        outer_transaction = await session.scalar(text("SELECT txid_current()"))
        await control_plane._ensure_defaults(session, nested_domain)
        assert await session.scalar(text("SELECT txid_current()")) == outer_transaction
        async with case.sessions() as observer:
            assert await observer.scalar(
                select(func.count()).select_from(OwnerControlRecord).where(
                    OwnerControlRecord.domain == nested_domain,
                    OwnerControlRecord.resource_id == default_id,
                )
            ) == 1
            # The default is committed independently; the accepted Owner command
            # in the protected enqueue transaction is still invisible here.
            assert await observer.scalar(
                select(func.count()).select_from(OwnerCommandRecord)
            ) == 0
        assert len(case.auxiliary_sessions) == 1
        nested_seed_committed.set()
        await release_enqueue.wait()
        await original_lock(session, key)

    monkeypatch.setattr(control_plane, "acquire_enqueue_lock", inject_real_nested_seed)
    request_task = asyncio.create_task(_post(case, "owner-create"))
    close_task = None
    try:
        await asyncio.wait_for(nested_seed_committed.wait(), timeout=WAIT_SECONDS)
        close_task = asyncio.create_task(_close(case))
        await _wait_for_close_blocked_by(case, holder_pid)
        assert not close_task.done()
        release_enqueue.set()
        response = await asyncio.wait_for(request_task, timeout=WAIT_SECONDS)
        await asyncio.wait_for(close_task, timeout=WAIT_SECONDS)
        await _assert_success(case, "owner-create", response)
        commands, audits = await _owner_evidence(case, "owner-create")
        assert len(commands) == 1 and commands[0].status == "completed"
        assert len(audits) == 1 and audits[0].details["status"] == "completed"
        assert all(
            auxiliary is not request
            for auxiliary in case.auxiliary_sessions
            for request in case.requests
        )
    finally:
        release_enqueue.set()
        await _settle_tasks(request_task, close_task)
