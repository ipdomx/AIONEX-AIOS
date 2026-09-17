"""Real PostgreSQL producer and HTTP contracts for scoped remediation admission.

Every case uses a private random schema in an explicitly test-named database.
The actual router, policy/grant helpers, producer, caller commits and PostgreSQL
locks run. Preparation, scan execution, subprocesses and filesystem writes do not.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, ForeignKey, MetaData, String, Table, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1.endpoints import security_lab
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AuditEvent,
    HostMaintenanceWorkCycle,
    Organization,
    OwnerControlRecord,
    Project,
    ProjectExecution,
    Role,
    SecurityAccessGrant,
    SecurityFinding,
    SecurityRemediation,
    SecurityScan,
    SecurityTarget,
    User,
    Workspace,
)
from app.services import security_fabric, security_remediation, security_scanning, security_tools
from app.services.free_tier import FREE_USER_ROLE_NAME, require_non_free_user
from app.services.host_maintenance_admission import (
    ACADEMY_COVERAGE_SCOPE,
    ACADEMY_SCHEMA_VERSION,
    COVERAGE_SCHEMA_VERSION,
    COVERAGE_SCOPE,
    DOMAIN,
    NOTIFICATION_COVERAGE_SCOPE,
    NOTIFICATION_SCHEMA_VERSION,
    REMEDIATION_COVERAGE_SCOPE,
    REMEDIATION_SCHEMA_VERSION,
    RESOURCE_ID,
    SCHEMA_VERSION,
    SCOPE,
    HostMaintenanceClosed,
    HostMaintenanceUnavailable,
    close_admission,
    open_admission,
)

CLOSED_DETAIL = "Security remediation admission is temporarily closed for maintenance."
UNAVAILABLE_DETAIL = "Security remediation admission is currently unavailable."
PREFIX = "/api/v1/security-lab"
WAIT = 10


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AuditEvent, HostMaintenanceWorkCycle, Organization, OwnerControlRecord,
            Project, ProjectExecution, Role, SecurityAccessGrant, SecurityFinding,
            SecurityRemediation, SecurityScan, SecurityTarget, User, Workspace,
        )
    }
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return list(tables)
        tables = expanded


def _actor(user_id, organization_id, role):
    return UserRecord(
        id=user_id, email=f"remediation-{user_id}@example.test",
        name=f"Isolated {role}", role=role, password_hash="unused-synthetic-hash",
        organization_id=organization_id,
        organization_name="Isolated Remediation Organization",
        organization_plan="enterprise", permissions=[],
    )


@pytest_asyncio.fixture
async def remediation_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("remediation admission contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])",
        (url.database or "").lower(),
    ) is None:
        raise RuntimeError("remediation API tests require an isolated test database")
    schema = f"fr06c5d6_api_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool,
        connect_args={"server_settings": {
            "search_path": schema, "application_name": schema,
        }},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_id, other_org_id = str(uuid4()), str(uuid4())
    actor = _actor(str(uuid4()), org_id, "Security Operator")
    owner = _actor(str(uuid4()), org_id, "Super Owner")
    outsider = _actor(str(uuid4()), other_org_id, "Super Owner")
    case = SimpleNamespace(
        sessions=sessions, engine=engine, schema=schema, actor=actor, owner=owner,
        outsider=outsider, operation_id=str(uuid4()), requests=[],
        forbidden_attempts=[], project_id=str(uuid4()), target_id=str(uuid4()),
        scan_id=str(uuid4()), finding_id=str(uuid4()),
        other_project_id=str(uuid4()), other_target_id=str(uuid4()),
        other_scan_id=str(uuid4()), other_finding_id=str(uuid4()),
    )
    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda connection: Base.metadata.create_all(
                    connection, tables=_required_tables(),
                )
            )
        async with sessions() as session:
            for organization_id in (org_id, other_org_id):
                session.add(Organization(
                    id=organization_id, name="Isolated Remediation Organization",
                    slug=f"isolated-{organization_id}", plan="enterprise",
                    status="active",
                ))
            await session.flush()
            for user in (actor, owner, outsider):
                role = Role(
                    id=str(uuid4()), organization_id=user.organization_id,
                    name=user.role, status="active",
                )
                session.add(role)
                await session.flush()
                session.add(User(
                    id=user.id, organization_id=user.organization_id, role_id=role.id,
                    name=user.name, email=user.email,
                    password_hash=user.password_hash, status="active",
                ))
            await session.flush()
            for user, project_id, target_id, scan_id, finding_id in (
                (actor, case.project_id, case.target_id, case.scan_id, case.finding_id),
                (outsider, case.other_project_id, case.other_target_id,
                 case.other_scan_id, case.other_finding_id),
            ):
                workspace = Workspace(
                    id=str(uuid4()), organization_id=user.organization_id,
                    name="Isolated workspace", slug=f"workspace-{project_id}",
                    status="active",
                )
                session.add(workspace)
                await session.flush()
                session.add(Project(
                    id=project_id, organization_id=user.organization_id,
                    workspace_id=workspace.id, owner_id=user.id,
                    name="Isolated managed project", slug=f"project-{project_id}",
                    status="active",
                ))
                await session.flush()
                # A literal globally routable address exercises the actual DNS
                # stability validation without resolving or contacting any host.
                session.add(SecurityTarget(
                    id=target_id, organization_id=user.organization_id,
                    project_id=project_id, created_by_id=user.id, kind="managed_project",
                    origin="https://93.184.216.34", hostname="93.184.216.34",
                    authorization_status="verified", verification_method="managed",
                    status="active", target_metadata={
                        "environment": "production",
                        "verified_addresses": ["93.184.216.34"],
                    },
                ))
                await session.flush()
                session.add(SecurityScan(
                    id=scan_id, organization_id=user.organization_id,
                    project_id=project_id, target_id=target_id,
                    requested_by_id=user.id, profile="passive", status="completed",
                    execution_mode="passive", tool_plan=[], summary={},
                ))
                await session.flush()
                session.add(SecurityFinding(
                    id=finding_id, organization_id=user.organization_id,
                    scan_id=scan_id, target_id=target_id, source="synthetic-scanner",
                    category="headers", title="Confirmed isolated finding",
                    severity="high", confidence=1.0, state="confirmed",
                    fingerprint="a" * 64, cwe="CWE-693", location="src/headers.py",
                    evidence={}, remediation="Add the missing header.",
                ))
            session.add(SecurityAccessGrant(
                id=str(uuid4()), organization_id=org_id, user_id=actor.id,
                granted_by_id=owner.id, level="autonomous", status="active",
                profiles=["passive"], expires_at=None,
            ))
            session.add(OwnerControlRecord(
                domain=security_fabric.POLICY_DOMAIN,
                resource_id=security_fabric.POLICY_RESOURCE,
                status="active", enabled=True, version=1,
                payload={**security_fabric.DEFAULT_POLICY,
                         "auto_remediation_enabled": True},
            ))
            session.add(OwnerControlRecord(
                domain=DOMAIN, resource_id=RESOURCE_ID, status="open",
                enabled=True, version=5, payload={
                    "schema_version": REMEDIATION_SCHEMA_VERSION,
                    "scope": REMEDIATION_COVERAGE_SCOPE,
                    "generation": 5, "operation_id": case.operation_id,
                    "reason": "synthetic-private-remediation-authority",
                    "changed_at": datetime.now(UTC).isoformat(),
                    "full_host_closure": False,
                },
            ))
            await session.commit()

        async def request_db():
            async with sessions() as session:
                case.requests.append(session)
                yield session

        async def actor_dependency():
            return case.actor

        def forbidden_sync(*_args, **_kwargs):
            case.forbidden_attempts.append("runtime-io")
            raise AssertionError("remediation API tests must not perform runtime I/O")

        async def forbidden_async(*_args, **_kwargs):
            forbidden_sync()

        monkeypatch.setattr(security_scanning, "execute_scan", forbidden_async)
        monkeypatch.setattr(security_tools, "run_source_tool", forbidden_async)
        monkeypatch.setattr(security_tools, "run_network_tool", forbidden_async)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_async)
        monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_async)
        monkeypatch.setattr(subprocess, "Popen", forbidden_sync)
        for name in ("mkdir", "chmod", "unlink", "rename", "replace", "write_text", "write_bytes"):
            monkeypatch.setattr(Path, name, forbidden_sync)

        app = FastAPI()
        app.include_router(
            security_lab.router, prefix=PREFIX,
            dependencies=[Depends(require_non_free_user)],
        )
        app.dependency_overrides[get_db] = request_db
        app.dependency_overrides[current_user] = actor_dependency
        case.app = app
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
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


async def _post(case, finding_id=None):
    return await case.client.post(
        f"{PREFIX}/remediations",
        json={"finding_id": finding_id if finding_id is not None else case.finding_id},
    )


async def _close(case, session_factory=None):
    return await close_admission(
        operation_id=case.operation_id, expected_generation=5,
        reason="isolated remediation admission closure",
        session_factory=session_factory or case.sessions,
    )


async def _business(case):
    result = {}
    async with case.sessions() as session:
        for model in (
            SecurityTarget, SecurityScan, SecurityFinding, SecurityRemediation,
            AuditEvent, HostMaintenanceWorkCycle,
        ):
            table = model.__table__
            result[table.name] = [
                dict(row) for row in (
                    await session.execute(select(table).order_by(table.c.id))
                ).mappings()
            ]
        table = OwnerControlRecord.__table__
        result["security_policy"] = [
            dict(row) for row in (
                await session.execute(select(table).where(
                    table.c.domain == security_fabric.POLICY_DOMAIN,
                    table.c.resource_id == security_fabric.POLICY_RESOURCE,
                ))
            ).mappings()
        ]
    return result


def _rejected(response, detail):
    assert response.status_code == 503
    assert response.json() == {"detail": detail}
    assert "retry-after" not in response.headers


async def _assert_planned(case, response):
    assert response.status_code == 202, response.text
    payload = response.json()
    assert str(UUID(payload["id"])) == payload["id"]
    assert set(payload) == {
        "id", "project_id", "finding_id", "requested_by_id", "status",
        "worktree_ref", "plan", "regression_result", "retest_scan_id",
        "verified_fixed_at", "created_at", "updated_at",
    }
    assert payload["project_id"] == case.project_id
    assert payload["finding_id"] == case.finding_id
    assert payload["status"] == "planned"
    assert payload["worktree_ref"] is None
    assert payload["regression_result"] == {}
    assert payload["retest_scan_id"] is None
    assert payload["verified_fixed_at"] is None
    assert payload["created_at"] and payload["updated_at"]
    async with case.sessions() as session:
        row = await session.get(SecurityRemediation, payload["id"])
        finding = await session.get(SecurityFinding, case.finding_id)
        target = await session.get(SecurityTarget, finding.target_id)
        assert row is not None and row.status == "planned"
        assert row.preparation_protocol_version is None
        assert row.preparation_outcome is None
        assert payload["plan"] == security_remediation.build_remediation_plan(finding, target)
        assert payload["requested_by_id"] == row.requested_by_id
        audit = (await session.scalars(select(AuditEvent))).all()
        assert len(audit) == 1
        assert audit[0].action == "security.remediation.planned"
        assert audit[0].resource_id == row.id
        assert not (await session.scalars(select(HostMaintenanceWorkCycle))).all()
    assert not case.forbidden_attempts
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_kind", ["autonomous", "owner"])
async def test_open_202_reuses_existing_plan_but_existing_id_cannot_bypass_close(
    remediation_case, actor_kind,
):
    case = remediation_case
    if actor_kind == "owner":
        case.actor = case.owner
    first = await _assert_planned(case, await _post(case))
    second = await _assert_planned(case, await _post(case))
    assert second == first
    before = await _business(case)
    closed = await _close(case)
    _rejected(await _post(case), CLOSED_DETAIL)
    assert await _business(case) == before
    reopened = await open_admission(
        operation_id=closed.operation_id, expected_generation=closed.generation,
        reason="isolated explicit reopen", session_factory=case.sessions,
    )
    assert reopened.generation == closed.generation + 1
    assert (await _post(case)).json() == first


@pytest.mark.asyncio
async def test_closed_api_does_not_seed_missing_security_policy(remediation_case):
    case = remediation_case
    async with case.sessions() as session:
        policy = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == security_fabric.POLICY_DOMAIN,
        ))
        await session.delete(policy)
        await session.commit()
    before = await _business(case)
    assert before["security_policy"] == []
    await _close(case)
    _rejected(await _post(case), CLOSED_DETAIL)
    assert await _business(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_state", ["closed", "unavailable"])
async def test_admission_precedes_pending_autoflush_and_lazy_policy_setup(
    remediation_case, authority_state,
):
    case = remediation_case
    async with case.sessions() as session:
        policy = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == security_fabric.POLICY_DOMAIN,
        ))
        await session.delete(policy)
        if authority_state == "unavailable":
            authority = await session.scalar(select(OwnerControlRecord).where(
                OwnerControlRecord.domain == DOMAIN,
            ))
            authority.payload = {**authority.payload, "generation": "5"}
        await session.commit()
    if authority_state == "closed":
        await _close(case)
    before = await _business(case)
    writes = []

    def observe_writes(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement.split(None, 1)[0])

    event.listen(case.engine.sync_engine, "before_cursor_execute", observe_writes)
    try:
        async with case.sessions() as session:
            pending = AuditEvent(
                id=str(uuid4()), organization_id=case.actor.organization_id,
                user_id=case.actor.id, action="synthetic.pending",
                resource_type="synthetic", resource_id=case.finding_id, details={},
            )
            session.add(pending)
            error = HostMaintenanceClosed if authority_state == "closed" else HostMaintenanceUnavailable
            with pytest.raises(error):
                await security_remediation.request_remediation(
                    session, case.actor, finding_id=case.finding_id,
                )
            assert pending in session.new
            assert writes == []
            await session.rollback()
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", observe_writes)
    assert await _business(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [
    "schema1", "schema2", "schema3", "schema4", "missing", "malformed",
    "unknown", "database-read",
])
async def test_unavailable_authority_never_creates_plan_audit_or_activity(
    remediation_case, condition,
):
    case = remediation_case
    before = await _business(case)
    async with case.sessions() as session:
        authority = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == DOMAIN,
        ))
        older = {
            "schema1": (SCHEMA_VERSION, SCOPE),
            "schema2": (COVERAGE_SCHEMA_VERSION, COVERAGE_SCOPE),
            "schema3": (ACADEMY_SCHEMA_VERSION, ACADEMY_COVERAGE_SCOPE),
            "schema4": (NOTIFICATION_SCHEMA_VERSION, NOTIFICATION_COVERAGE_SCOPE),
        }
        if condition in older:
            version, scope = older[condition]
            authority.payload = {**authority.payload, "schema_version": version, "scope": scope}
        elif condition == "missing":
            await session.delete(authority)
        elif condition == "malformed":
            authority.payload = {**authority.payload, "generation": "5"}
        elif condition == "unknown":
            authority.payload = {**authority.payload, "schema_version": 999}
        await session.commit()
    if condition == "database-read":
        # An actual failed PostgreSQL admission SELECT, isolated to this schema.
        async with case.engine.begin() as connection:
            await connection.execute(text(
                "ALTER TABLE owner_control_records RENAME TO unavailable_owner_control_records"
            ))
    try:
        response = await _post(case)
        _rejected(response, UNAVAILABLE_DETAIL)
    finally:
        if condition == "database-read":
            async with case.engine.begin() as connection:
                await connection.execute(text(
                    "ALTER TABLE unavailable_owner_control_records RENAME TO owner_control_records"
                ))
    assert await _business(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
async def test_authentication_free_user_and_body_validation_precede_closed_admission(
    remediation_case,
):
    case = remediation_case
    before = await _business(case)
    await _close(case)
    actor_dependency = case.app.dependency_overrides.pop(current_user)
    try:
        response = await _post(case)
        assert response.status_code == 401
    finally:
        case.app.dependency_overrides[current_user] = actor_dependency
    original_actor = case.actor
    case.actor = replace(original_actor, role=FREE_USER_ROLE_NAME)
    response = await _post(case)
    assert response.status_code == 403
    assert response.json()["detail"] == "This capability is not included in the free-user plan"
    case.actor = original_actor
    response = await _post(case, finding_id="")
    assert response.status_code == 422
    assert await _business(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", [
    "policy-disabled", "policy-missing", "grant-missing", "grant-standard",
    "grant-expired", "grant-revoked",
])
async def test_open_admission_preserves_real_policy_and_grant_denials(
    remediation_case, denial,
):
    case = remediation_case
    async with case.sessions() as session:
        if denial.startswith("policy"):
            policy = await session.scalar(select(OwnerControlRecord).where(
                OwnerControlRecord.domain == security_fabric.POLICY_DOMAIN,
            ))
            if denial == "policy-missing":
                await session.delete(policy)
            else:
                policy.payload = {**policy.payload, "auto_remediation_enabled": False}
        else:
            grant = await session.scalar(select(SecurityAccessGrant))
            if denial == "grant-missing":
                await session.delete(grant)
            elif denial == "grant-standard":
                grant.level = "standard"
            elif denial == "grant-expired":
                grant.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            else:
                grant.status = "revoked"
        await session.commit()
    before = await _business(case)
    response = await _post(case)
    assert response.status_code == 403
    assert "Super Owner" in response.json()["detail"]
    assert await _business(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [
    "missing-finding", "foreign-finding", "unconfirmed", "external-target",
    "inactive-target", "target-without-project",
])
async def test_open_admission_preserves_scoped_lookup_and_business_validation(
    remediation_case, condition,
):
    case = remediation_case
    finding_id = case.finding_id
    if condition == "missing-finding":
        finding_id = str(uuid4())
    elif condition == "foreign-finding":
        finding_id = case.other_finding_id
    else:
        async with case.sessions() as session:
            finding = await session.get(SecurityFinding, case.finding_id)
            target = await session.get(SecurityTarget, case.target_id)
            if condition == "unconfirmed":
                finding.state = "observed"
            elif condition == "external-target":
                target.kind = "external"
            elif condition == "inactive-target":
                target.status = "inactive"
            else:
                target.project_id = None
            await session.commit()
    before = await _business(case)
    response = await _post(case, finding_id=finding_id)
    assert response.status_code == (404 if condition.endswith("finding") else 409)
    assert await _business(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("source_state", ["verified", "missing", "unverified"])
async def test_security_clone_keeps_verified_managed_source_requirement(
    remediation_case, source_state,
):
    case = remediation_case
    async with case.sessions() as session:
        source = await session.get(SecurityTarget, case.target_id)
        if source_state == "unverified":
            source.authorization_status = "pending"
        clone = SecurityTarget(
            id=str(uuid4()), organization_id=case.actor.organization_id,
            project_id=case.project_id, kind="security_clone",
            origin="https://93.184.216.35", hostname="93.184.216.35",
            authorization_status="verified", verification_method="managed",
            status="active", target_metadata={
                "environment": "security_clone",
                "source_target_id": source.id if source_state != "missing" else str(uuid4()),
            },
        )
        session.add(clone)
        await session.flush()
        finding = await session.get(SecurityFinding, case.finding_id)
        scan = await session.get(SecurityScan, case.scan_id)
        finding.target_id = clone.id
        scan.target_id = clone.id
        await session.commit()
    before = await _business(case)
    response = await _post(case)
    if source_state == "verified":
        payload = await _assert_planned(case, response)
        assert payload["plan"]["target"]["kind"] == "security_clone"
    else:
        assert response.status_code == 409
        assert "verified managed-project source" in response.json()["detail"]
        assert await _business(case) == before


async def _wait_for_blocked_by(case, holder_pid):
    async with asyncio.timeout(WAIT):
        while True:
            async with case.sessions() as observer:
                blocked = await observer.scalar(text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE application_name = :application_name "
                    "AND :holder_pid = ANY(pg_blocking_pids(pid))"
                ), {"application_name": case.schema, "holder_pid": holder_pid})
            if blocked:
                return
            await asyncio.sleep(0.01)


async def _settle_tasks(*tasks):
    present = [task for task in tasks if task is not None]
    for task in present:
        if not task.done():
            task.cancel()
    if present:
        await asyncio.wait_for(asyncio.gather(*present, return_exceptions=True), WAIT)


@pytest.mark.asyncio
async def test_real_producer_holds_shared_admission_through_actual_api_commit(
    remediation_case, monkeypatch,
):
    case = remediation_case
    admitted, release_producer = asyncio.Event(), asyncio.Event()
    at_commit, release_commit = asyncio.Event(), asyncio.Event()
    original_guard = security_remediation.require_remediation_admission
    holder_pid = None

    async def held_guard(session):
        nonlocal holder_pid
        await original_guard(session)
        assert any(session is request for request in case.requests)
        holder_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        transaction_id = await session.scalar(text("SELECT txid_current()"))
        actual_commit = session.commit

        async def held_commit():
            assert await session.scalar(text("SELECT txid_current()")) == transaction_id
            pending = (await session.scalars(select(SecurityRemediation))).all()
            assert len(pending) == 1 and pending[0].status == "planned"
            async with case.sessions() as observer:
                assert await observer.get(SecurityRemediation, pending[0].id) is None
                assert not (await observer.scalars(select(AuditEvent))).all()
            at_commit.set()
            await release_commit.wait()
            await actual_commit()

        monkeypatch.setattr(session, "commit", held_commit)
        admitted.set()
        await release_producer.wait()

    monkeypatch.setattr(security_remediation, "require_remediation_admission", held_guard)
    request_task = asyncio.create_task(_post(case))
    close_task = None
    try:
        await asyncio.wait_for(admitted.wait(), WAIT)
        close_task = asyncio.create_task(_close(case))
        await _wait_for_blocked_by(case, holder_pid)
        assert not close_task.done()
        release_producer.set()
        await asyncio.wait_for(at_commit.wait(), WAIT)
        await _wait_for_blocked_by(case, holder_pid)
        assert not request_task.done() and not close_task.done()
        release_commit.set()
        response = await asyncio.wait_for(request_task, WAIT)
        await asyncio.wait_for(close_task, WAIT)
        await _assert_planned(case, response)
        before = await _business(case)
        _rejected(await _post(case), CLOSED_DETAIL)
        assert await _business(case) == before
    finally:
        release_producer.set()
        release_commit.set()
        await _settle_tasks(request_task, close_task)


@pytest.mark.asyncio
async def test_close_commit_first_blocks_then_rejects_actual_producer(
    remediation_case, monkeypatch,
):
    case = remediation_case
    close_updated, release_close = asyncio.Event(), asyncio.Event()
    holder_pid = None

    def held_close_session():
        session = case.sessions()
        original_begin = session.begin

        @asynccontextmanager
        async def held_transaction():
            nonlocal holder_pid
            async with original_begin():
                yield
                holder_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                authority = await session.scalar(select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == DOMAIN,
                ))
                assert authority.status == "closed" and authority.version == 6
                close_updated.set()
                await release_close.wait()

        monkeypatch.setattr(session, "begin", held_transaction)
        return session

    before = await _business(case)
    close_task = asyncio.create_task(_close(case, session_factory=held_close_session))
    request_task = None
    try:
        await asyncio.wait_for(close_updated.wait(), WAIT)
        request_task = asyncio.create_task(_post(case))
        await _wait_for_blocked_by(case, holder_pid)
        assert not request_task.done() and not close_task.done()
        release_close.set()
        await asyncio.wait_for(close_task, WAIT)
        _rejected(await asyncio.wait_for(request_task, WAIT), CLOSED_DETAIL)
        assert await _business(case) == before
    finally:
        release_close.set()
        await _settle_tasks(request_task, close_task)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["policy", "commit"])
async def test_actual_denial_or_failed_commit_rolls_back_and_releases_waiting_close(
    remediation_case, monkeypatch, failure,
):
    case = remediation_case
    tripwire = None
    if failure == "policy":
        async with case.sessions() as session:
            policy = await session.scalar(select(OwnerControlRecord).where(
                OwnerControlRecord.domain == security_fabric.POLICY_DOMAIN,
            ))
            policy.payload = {**policy.payload, "auto_remediation_enabled": False}
            await session.commit()
    else:
        # Match the established notification PG contract: a real deferred FK
        # violation makes COMMIT fail after the producer's own flush succeeded.
        tripwire = Table(
            "remediation_commit_tripwire", MetaData(),
            Column("id", String(36), primary_key=True),
            Column("remediation_id", String(36), ForeignKey(
                SecurityRemediation.__table__.c.id,
                deferrable=True, initially="DEFERRED",
            ), nullable=False),
        )
        async with case.engine.begin() as connection:
            await connection.run_sync(tripwire.create)

    admitted, release_producer = asyncio.Event(), asyncio.Event()
    original_guard = security_remediation.require_remediation_admission
    holder_pid = None
    actual_commit_failed = False

    async def held_guard(session):
        nonlocal holder_pid, actual_commit_failed
        await original_guard(session)
        holder_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        if failure == "commit":
            def before_commit(sync_session):
                sync_session.execute(tripwire.insert().values(
                    id=str(uuid4()), remediation_id=str(uuid4()),
                ))

            event.listen(session.sync_session, "before_commit", before_commit)
            actual_commit = session.commit

            async def failing_commit():
                nonlocal actual_commit_failed
                pending = (await session.scalars(select(SecurityRemediation))).all()
                assert len(pending) == 1 and pending[0].status == "planned"
                await _wait_for_blocked_by(case, holder_pid)
                try:
                    await actual_commit()
                except IntegrityError as exc:
                    code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
                    assert code == "23503"
                    actual_commit_failed = True
                    raise

            monkeypatch.setattr(session, "commit", failing_commit)
        admitted.set()
        await release_producer.wait()

    monkeypatch.setattr(security_remediation, "require_remediation_admission", held_guard)
    before = await _business(case)
    request_task = asyncio.create_task(_post(case))
    close_task = None
    try:
        await asyncio.wait_for(admitted.wait(), WAIT)
        close_task = asyncio.create_task(_close(case))
        await _wait_for_blocked_by(case, holder_pid)
        assert not close_task.done()
        release_producer.set()
        response = await asyncio.wait_for(request_task, WAIT)
        await asyncio.wait_for(close_task, WAIT)
        if failure == "policy":
            assert response.status_code == 403
        else:
            assert response.status_code == 500
            assert response.text == "Internal Server Error"
            assert actual_commit_failed
        assert await _business(case) == before
        assert not case.forbidden_attempts
    finally:
        release_producer.set()
        await _settle_tasks(request_task, close_task)


@pytest.mark.asyncio
async def test_closed_preparation_keeps_existing_list_patch_retest_and_finalization(
    remediation_case,
):
    case = remediation_case
    planned = await _assert_planned(case, await _post(case))
    remediation_id = planned["id"]
    async with case.sessions() as session:
        item = await session.get(SecurityRemediation, remediation_id)
        item.status = "worktree_ready"
        item.worktree_ref = "isolated-evidence-only"
        await session.commit()
    await _close(case)
    response = await case.client.get(f"{PREFIX}/remediations")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [remediation_id]
    response = await case.client.post(
        f"{PREFIX}/remediations/{remediation_id}/patch-evidence",
        json={
            "changed_files": ["src/headers.py"],
            "tests": [{"name": "header regression", "passed": True}],
            "patch_digest": "b" * 64,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "regression_passed"
    assert response.json()["regression_result"]["production_modified"] is False
    response = await case.client.post(
        f"{PREFIX}/remediations/{remediation_id}/retest",
    )
    assert response.status_code == 202, response.text
    retest_id = response.json()["scan"]["id"]
    assert response.json()["remediation"]["status"] == "retest_queued"
    assert response.json()["scan"]["status"] == "queued"
    async with case.sessions() as session:
        retest = await session.get(SecurityScan, retest_id)
        assert retest.target_id == case.target_id
        retest.status = "completed"
        retest.completed_at = datetime.now(UTC)
        await session.commit()
    response = await case.client.post(
        f"{PREFIX}/remediations/{remediation_id}/finalize",
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified_fixed"
    assert response.json()["verified_fixed_at"]
    async with case.sessions() as session:
        finding = await session.get(SecurityFinding, case.finding_id)
        assert finding.state == "resolved" and finding.resolved_at is not None
        actions = set((await session.scalars(select(AuditEvent.action))).all())
        assert actions == {
            "security.remediation.planned",
            "security.remediation.regression_passed",
            "security.scan.queued",
            "security.remediation.retest_queued",
            "security.remediation.verified_fixed",
        }
        assert not (await session.scalars(select(HostMaintenanceWorkCycle))).all()
    assert not case.forbidden_attempts
