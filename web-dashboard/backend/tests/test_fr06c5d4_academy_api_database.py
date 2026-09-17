"""Real PostgreSQL and HTTP contracts for academy package admission.

Each test owns a random schema inside an explicitly test-named database. The
actual academy router, producer transaction and PostgreSQL locks are exercised;
factory execution, subprocesses and filesystem mutation are forbidden.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aios import course_factory
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1.endpoints import academy
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AcademyCourse,
    AcademyCoursePackage,
    HostMaintenanceWorkCycle,
    Organization,
    OwnerControlRecord,
    Role,
    User,
)
from app.services import academy_course_runtime as runtime
from app.services.host_maintenance_admission import (
    ACADEMY_COVERAGE_SCOPE,
    ACADEMY_SCHEMA_VERSION,
    COVERAGE_SCHEMA_VERSION,
    COVERAGE_SCOPE,
    DOMAIN,
    RESOURCE_ID,
    SCHEMA_VERSION,
    SCOPE,
    close_admission,
    open_admission,
)

CLOSED_DETAIL = (
    "Academy course package admission is temporarily closed for maintenance."
)
UNAVAILABLE_DETAIL = "Academy course package admission is currently unavailable."
WAIT_SECONDS = 10


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AcademyCourse,
            AcademyCoursePackage,
            HostMaintenanceWorkCycle,
            Organization,
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
async def academy_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("academy API admission contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])",
        (url.database or "").lower(),
    ) is None:
        raise RuntimeError("academy API tests require an isolated test database")

    schema = f"fr06c5d4_api_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {"search_path": schema, "application_name": schema}
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor_id, organization_id, role_id, course_id, other_org_id, other_course_id = (
        str(uuid4()) for _ in range(6)
    )
    actor = UserRecord(
        id=actor_id,
        email=f"academy-{actor_id}@example.test",
        name="Isolated Academy Author",
        role="Academy Author",
        password_hash="unused-synthetic-hash",
        organization_id=organization_id,
        organization_name="Isolated Academy Organization",
        organization_plan="enterprise",
        permissions=["academy:read", "academy:write", "academy:assess"],
    )
    case = SimpleNamespace(
        sessions=sessions,
        engine=engine,
        schema=schema,
        actor=actor,
        course_id=course_id,
        other_course_id=other_course_id,
        operation_id=str(uuid4()),
        requests=[],
        forbidden_attempts=[],
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
            session.add_all(
                [
                    Organization(
                        id=organization_id,
                        name=actor.organization_name,
                        slug=f"isolated-{organization_id}",
                        plan="enterprise",
                        status="active",
                    ),
                    Organization(
                        id=other_org_id,
                        name="Separate Academy Organization",
                        slug=f"isolated-{other_org_id}",
                        plan="enterprise",
                        status="active",
                    ),
                ]
            )
            await session.flush()
            session.add(
                Role(
                    id=role_id,
                    organization_id=organization_id,
                    name=actor.role,
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
            await session.flush()
            session.add_all(
                [
                    AcademyCourse(
                        id=course_id,
                        organization_id=organization_id,
                        code="isolated-course",
                        title="Isolated Course",
                        passing_score=85,
                        status="active",
                        version=4,
                        created_by_id=actor_id,
                    ),
                    AcademyCourse(
                        id=other_course_id,
                        organization_id=other_org_id,
                        code="separate-course",
                        title="Separate Course",
                        status="active",
                    ),
                    OwnerControlRecord(
                        domain=DOMAIN,
                        resource_id=RESOURCE_ID,
                        status="open",
                        enabled=True,
                        version=3,
                        payload={
                            "schema_version": ACADEMY_SCHEMA_VERSION,
                            "scope": ACADEMY_COVERAGE_SCOPE,
                            "generation": 3,
                            "operation_id": case.operation_id,
                            "reason": "synthetic-private-authority-note",
                            "changed_at": datetime.now(UTC).isoformat(),
                            "full_host_closure": False,
                        },
                    ),
                ]
            )
            await session.commit()

        async def request_db():
            async with sessions() as session:
                case.requests.append(session)
                yield session

        async def actor_dependency():
            return case.actor

        def forbidden_sync(*_args, **_kwargs):
            case.forbidden_attempts.append("runtime-io")
            raise AssertionError("academy API tests must not perform runtime I/O")

        async def forbidden_async(*_args, **_kwargs):
            forbidden_sync()

        monkeypatch.setattr(course_factory.CompleteCourseFactory, "build", forbidden_sync)
        monkeypatch.setattr(
            course_factory.LocalFFmpegCourseVideoRenderer, "preflight", forbidden_sync
        )
        monkeypatch.setattr(
            course_factory.LocalFFmpegCourseVideoRenderer, "render", forbidden_sync
        )
        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_async)
        monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_async)
        monkeypatch.setattr(subprocess, "Popen", forbidden_sync)
        for name in (
            "mkdir", "chmod", "unlink", "rename", "replace", "write_text", "write_bytes"
        ):
            monkeypatch.setattr(Path, name, forbidden_sync)

        app = FastAPI()
        app.include_router(academy.router, prefix="/api/v1/academy")
        app.dependency_overrides[get_db] = request_db
        # Retain the real require_permissions dependency in the router.
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


def _payload(**updates):
    result = {
        "idempotency_key": "isolated-package-request",
        "domain": " Practical reliability ",
        "audience": " Academy maintainers ",
        "locales": [" EN ", "ar", "en"],
        "module_count": 2,
        "lessons_per_module": 3,
        "citations": [
            {
                "citation_id": "source-1",
                "title": "Synthetic reference",
                "uri": "internal://academy/reference",
                "author": None,
            }
        ],
    }
    result.update(updates)
    return result


async def _post(case, *, course_id=None, **updates):
    return await case.client.post(
        f"/api/v1/academy/courses/{course_id or case.course_id}/packages",
        json=_payload(**updates),
    )


async def _close(case, *, session_factory=None):
    return await close_admission(
        operation_id=case.operation_id,
        expected_generation=3,
        reason="isolated-academy-close",
        session_factory=session_factory or case.sessions,
    )


async def _business_snapshot(case):
    async with case.sessions() as session:
        result = {}
        for model in (AcademyCourse, AcademyCoursePackage, HostMaintenanceWorkCycle):
            rows = list((await session.scalars(select(model).order_by(model.id))).all())
            result[model.__tablename__] = [
                {
                    column.key: getattr(row, column.key)
                    for column in inspect(model).column_attrs
                }
                for row in rows
            ]
        return result


def _assert_rejected(response, detail):
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": detail}
    assert "retry-after" not in response.headers
    for private in (
        "synthetic-private-authority-note", "operation_id", "generation",
        "postgresql", "owner_control_records", "sqlalchemy", "asyncpg",
    ):
        assert private not in response.text.lower()


async def _assert_queued(case, response, *, version=1, count=1):
    assert response.status_code == 202, response.text
    body = response.json()
    assert str(UUID(body["id"])) == body["id"]
    for name in ("created_at", "updated_at"):
        assert datetime.fromisoformat(body[name]).tzinfo is not None
    assert body == {
        "id": body["id"],
        "course_id": case.course_id,
        "status": "queued",
        "version": version,
        "lesson_count": 6,
        "request": {
            "domain": "Practical reliability",
            "audience": "Academy maintainers",
            "locales": ["en", "ar"],
            "module_count": 2,
            "lessons_per_module": 3,
            "passing_score": 85,
            "citations": _payload()["citations"],
        },
        "curriculum": {},
        "citations": _payload()["citations"],
        "review": {"status": "pending", "approved": False},
        "archive_sha256": None,
        "manifest_sha256": None,
        "archive_bytes": 0,
        "download_ready": False,
        "site_ready": False,
        "error_code": None,
        "completed_at": None,
        "reviewed_at": None,
        "created_at": body["created_at"],
        "updated_at": body["updated_at"],
    }
    after = await _business_snapshot(case)
    packages = after["academy_course_packages"]
    assert len(packages) == count
    package = next(row for row in packages if row["id"] == body["id"])
    assert package["requested_by_id"] == case.actor.id
    assert package["organization_id"] == case.actor.organization_id
    assert package["status"] == "queued"
    assert package["version"] == version
    assert not after["host_maintenance_work_cycles"]
    course = next(row for row in after["academy_courses"] if row["id"] == case.course_id)
    assert course["version"] == 4
    assert not case.forbidden_attempts
    return body


@pytest.mark.asyncio
async def test_closed_admission_reopens_only_through_current_authority_and_keeps_202(
    academy_case,
):
    case = academy_case
    before = await _business_snapshot(case)
    closed = await _close(case)
    _assert_rejected(await _post(case), CLOSED_DETAIL)
    assert await _business_snapshot(case) == before
    await open_admission(
        operation_id=case.operation_id,
        expected_generation=closed.generation,
        reason="isolated-academy-reopen",
        session_factory=case.sessions,
    )
    first = await _assert_queued(case, await _post(case))
    committed = await _business_snapshot(case)
    duplicate = await _post(case)
    assert duplicate.status_code == 202
    assert duplicate.json() == first
    assert await _business_snapshot(case) == committed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authority_state",
    ["missing", "malformed", "unknown", "schema-1", "schema-2", "database-error"],
)
async def test_unavailable_authority_never_creates_package_version_or_activity(
    academy_case, authority_state
):
    case = academy_case
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
        elif authority_state == "schema-1":
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
        elif authority_state == "schema-2":
            authority.payload = {
                **authority.payload,
                "schema_version": COVERAGE_SCHEMA_VERSION,
                "scope": COVERAGE_SCOPE,
            }
        else:
            # Produce a real PostgreSQL admission-read failure. All course and
            # package business tables remain available in this private schema.
            await session.execute(
                text("ALTER TABLE owner_control_records RENAME TO unavailable_admission")
            )
        await session.commit()
    before = await _business_snapshot(case)
    _assert_rejected(await _post(case), UNAVAILABLE_DETAIL)
    assert await _business_snapshot(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["anonymous", "reader"])
async def test_authentication_and_academy_write_permission_precede_admission(
    academy_case, identity
):
    case = academy_case
    await _close(case)
    if identity == "anonymous":
        del case.app.dependency_overrides[current_user]
    else:
        case.actor = replace(case.actor, permissions=["academy:read"])
    before = await _business_snapshot(case)
    response = await _post(case)
    assert response.status_code == (401 if identity == "anonymous" else 403), response.text
    if identity == "anonymous":
        assert response.headers["www-authenticate"] == "Bearer"
    else:
        assert response.json() == {"detail": "Insufficient permissions"}
    assert await _business_snapshot(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["separate-organization", "absent"])
async def test_scoped_course_lookup_retains_404_before_admission(academy_case, target):
    case = academy_case
    await _close(case)
    course_id = case.other_course_id if target == "separate-organization" else str(uuid4())
    before = await _business_snapshot(case)
    response = await _post(case, course_id=course_id)
    assert response.status_code == 404
    assert response.json() == {"detail": "Academy course not found"}
    assert await _business_snapshot(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", ["unsupported-locale", "excess-lessons", "inactive-course", "request-schema"]
)
async def test_open_admission_preserves_existing_validation_422(academy_case, invalid):
    case = academy_case
    updates = {}
    if invalid == "unsupported-locale":
        updates["locales"] = ["invalid-locale"]
    elif invalid == "excess-lessons":
        updates.update(module_count=8, lessons_per_module=8)
    elif invalid == "request-schema":
        updates["idempotency_key"] = "x"
    else:
        async with case.sessions() as session:
            course = await session.get(AcademyCourse, case.course_id)
            course.status = "draft"
            await session.commit()
    before = await _business_snapshot(case)
    response = await _post(case, **updates)
    assert response.status_code == 422, response.text
    assert await _business_snapshot(case) == before
    assert not case.forbidden_attempts


@pytest.mark.asyncio
async def test_existing_idempotency_key_cannot_bypass_a_later_close(academy_case):
    case = academy_case
    await _assert_queued(case, await _post(case))
    before = await _business_snapshot(case)
    await _close(case)
    _assert_rejected(await _post(case), CLOSED_DETAIL)
    assert await _business_snapshot(case) == before


@pytest.mark.asyncio
async def test_open_requests_preserve_distinct_key_version_sequence(academy_case):
    case = academy_case
    first = await _assert_queued(case, await _post(case))
    second = await _assert_queued(
        case, await _post(case, idempotency_key="second-isolated-request"),
        version=2, count=2,
    )
    assert second["id"] != first["id"]
    assert [row["version"] for row in (
        await case.client.get(f"/api/v1/academy/courses/{case.course_id}/packages")
    ).json()] == [2, 1]


@pytest.mark.asyncio
async def test_closed_admission_keeps_existing_package_list_get_and_review(academy_case):
    case = academy_case
    first = await _assert_queued(case, await _post(case))
    async with case.sessions() as session:
        item = await session.get(AcademyCoursePackage, first["id"])
        item.status = "review_pending"
        await session.commit()
    await _close(case)
    listing = await case.client.get(
        f"/api/v1/academy/courses/{case.course_id}/packages"
    )
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [first["id"]]
    detail = await case.client.get(f"/api/v1/academy/packages/{first['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "review_pending"
    reviewed = await case.client.post(
        f"/api/v1/academy/packages/{first['id']}/review",
        json={"approved": True, "notes": "Synthetic review after admission closed"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "approved"
    assert reviewed.json()["review"]["reviewer_id"] == case.actor.id
    after = await _business_snapshot(case)
    assert len(after["academy_course_packages"]) == 1
    assert not after["host_maintenance_work_cycles"]
    assert not case.forbidden_attempts


async def _wait_for_blocked_by(case, holder_pid):
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
async def test_real_producer_shared_lock_is_held_through_actual_package_commit(
    academy_case, monkeypatch
):
    case = academy_case
    admitted = asyncio.Event()
    release_producer = asyncio.Event()
    at_commit = asyncio.Event()
    release_commit = asyncio.Event()
    holder_pid = None
    original_guard = runtime.require_academy_admission

    async def held_guard(session):
        nonlocal holder_pid
        await original_guard(session)
        assert any(session is request for request in case.requests)
        holder_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        transaction_id = await session.scalar(text("SELECT txid_current()"))
        actual_commit = session.commit

        async def held_commit():
            assert await session.scalar(text("SELECT txid_current()")) == transaction_id
            pending = (await session.scalars(select(AcademyCoursePackage))).all()
            assert len(pending) == 1 and pending[0].status == "queued"
            async with case.sessions() as observer:
                assert await observer.get(AcademyCoursePackage, pending[0].id) is None
            at_commit.set()
            await release_commit.wait()
            await actual_commit()

        monkeypatch.setattr(session, "commit", held_commit)
        admitted.set()
        await release_producer.wait()

    monkeypatch.setattr(runtime, "require_academy_admission", held_guard)
    request_task = asyncio.create_task(_post(case))
    close_task = None
    try:
        await asyncio.wait_for(admitted.wait(), timeout=WAIT_SECONDS)
        close_task = asyncio.create_task(_close(case))
        await _wait_for_blocked_by(case, holder_pid)
        assert not request_task.done() and not close_task.done()
        release_producer.set()
        await asyncio.wait_for(at_commit.wait(), timeout=WAIT_SECONDS)
        await _wait_for_blocked_by(case, holder_pid)
        assert not request_task.done() and not close_task.done()
        release_commit.set()
        response = await asyncio.wait_for(request_task, timeout=WAIT_SECONDS)
        await asyncio.wait_for(close_task, timeout=WAIT_SECONDS)
        await _assert_queued(case, response)
        after = await _business_snapshot(case)
        _assert_rejected(
            await _post(case, idempotency_key="after-close-request"), CLOSED_DETAIL
        )
        assert await _business_snapshot(case) == after
    finally:
        release_producer.set()
        release_commit.set()
        await _settle_tasks(request_task, close_task)


@pytest.mark.asyncio
async def test_committing_close_first_blocks_real_producer_then_rejects_it(
    academy_case, monkeypatch
):
    case = academy_case
    close_updated = asyncio.Event()
    release_close = asyncio.Event()
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
                authority = await session.scalar(
                    select(OwnerControlRecord).where(
                        OwnerControlRecord.domain == DOMAIN,
                        OwnerControlRecord.resource_id == RESOURCE_ID,
                    )
                )
                assert authority.status == "closed" and authority.version == 4
                close_updated.set()
                await release_close.wait()

        monkeypatch.setattr(session, "begin", held_transaction)
        return session

    before = await _business_snapshot(case)
    close_task = asyncio.create_task(_close(case, session_factory=held_close_session))
    request_task = None
    try:
        await asyncio.wait_for(close_updated.wait(), timeout=WAIT_SECONDS)
        request_task = asyncio.create_task(_post(case))
        await _wait_for_blocked_by(case, holder_pid)
        assert not request_task.done() and not close_task.done()
        release_close.set()
        await asyncio.wait_for(close_task, timeout=WAIT_SECONDS)
        _assert_rejected(
            await asyncio.wait_for(request_task, timeout=WAIT_SECONDS), CLOSED_DETAIL
        )
        assert await _business_snapshot(case) == before
        assert not case.forbidden_attempts
    finally:
        release_close.set()
        await _settle_tasks(request_task, close_task)


@pytest.mark.asyncio
async def test_business_unique_constraint_failure_rolls_back_and_releases_close(
    academy_case, monkeypatch
):
    case = academy_case
    admitted = asyncio.Event()
    release_producer = asyncio.Event()
    holder_pid = None
    rejected_id = None
    competing_id = str(uuid4())
    actual_constraint_failed = False
    original_guard = runtime.require_academy_admission

    async def held_guard(session):
        nonlocal holder_pid
        await original_guard(session)
        holder_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        actual_flush = session.flush

        async def collide_at_actual_flush(*args, **kwargs):
            nonlocal rejected_id, actual_constraint_failed
            pending = [
                item for item in session.new if isinstance(item, AcademyCoursePackage)
            ]
            assert len(pending) == 1
            rejected_id = pending[0].id
            # Commit a genuine competing version after the producer calculated
            # max_version. Its actual INSERT must fail the PostgreSQL constraint.
            async with case.sessions() as competitor:
                competitor.add(
                    AcademyCoursePackage(
                        id=competing_id,
                        organization_id=case.actor.organization_id,
                        course_id=case.course_id,
                        requested_by_id=case.actor.id,
                        idempotency_key="isolated-competing-version",
                        status="queued",
                        version=pending[0].version,
                    )
                )
                await competitor.commit()
            await _wait_for_blocked_by(case, holder_pid)
            try:
                await actual_flush(*args, **kwargs)
            except IntegrityError as exc:
                assert "uq_academy_course_package_version" in str(exc.orig)
                actual_constraint_failed = True
                raise

        monkeypatch.setattr(session, "flush", collide_at_actual_flush)
        admitted.set()
        await release_producer.wait()

    monkeypatch.setattr(runtime, "require_academy_admission", held_guard)
    before = await _business_snapshot(case)
    request_task = asyncio.create_task(_post(case))
    close_task = None
    try:
        await asyncio.wait_for(admitted.wait(), timeout=WAIT_SECONDS)
        close_task = asyncio.create_task(_close(case))
        await _wait_for_blocked_by(case, holder_pid)
        assert not close_task.done()
        release_producer.set()
        response = await asyncio.wait_for(request_task, timeout=WAIT_SECONDS)
        await asyncio.wait_for(close_task, timeout=WAIT_SECONDS)
        # Business DB errors retain the existing safe server-error boundary;
        # only errors while reading admission map to the static unavailable 503.
        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        assert actual_constraint_failed
        assert rejected_id is not None
        async with case.sessions() as observer:
            assert await observer.get(AcademyCoursePackage, rejected_id) is None
        after = await _business_snapshot(case)
        assert after["academy_courses"] == before["academy_courses"]
        assert [row["id"] for row in after["academy_course_packages"]] == [competing_id]
        assert not after["host_maintenance_work_cycles"]
        assert not case.forbidden_attempts
    finally:
        release_producer.set()
        await _settle_tasks(request_task, close_task)
