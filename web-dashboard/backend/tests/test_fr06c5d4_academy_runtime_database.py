"""PostgreSQL contracts for Academy package admission and durable ownership.

Every case owns a random schema in an explicitly test-named database. The real
runtime and activity service use only the isolated session factory. No worker
lifecycle, builder, storage, provider, or subprocess is started by these tests.
"""

from __future__ import annotations

import asyncio
import copy
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.auth import UserRecord
from app.core.config import settings
from app.db import base as database
from app.db.base import Base
from app.db.models import (
    AcademyCourse,
    AcademyCoursePackage,
    HostMaintenanceWorkCycle,
    Organization,
    OwnerControlRecord,
    User,
)
from app.services import academy_course_runtime as runtime
from app.services import academy_course_worker as worker_module
from app.services import host_maintenance_academy as maintenance
from app.services import host_maintenance_admission as admission


WAIT_SECONDS = 10
ACTIVITY_COMMIT_REJECTION = "synthetic academy activity commit rejected"


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AcademyCourse,
            AcademyCoursePackage,
            HostMaintenanceWorkCycle,
            Organization,
            OwnerControlRecord,
            User,
        )
    }
    while True:
        expanded = tables | {
            key.column.table for table in tables for key in table.foreign_keys
        }
        if expanded == tables:
            return sorted(tables, key=lambda table: table.name)
        tables = expanded


@pytest_asyncio.fixture
async def academy_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("Academy maintenance contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])",
        (url.database or "").lower(),
    ) is None:
        raise RuntimeError("Academy maintenance tests require an isolated test database")

    schema = f"fr06c5d4_academy_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {"search_path": schema, "application_name": schema}
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor_id, organization_id, course_id = (str(uuid4()) for _ in range(3))
    operation_id = str(uuid4())
    actor = UserRecord(
        id=actor_id,
        email=f"academy-{actor_id}@example.test",
        name="Isolated Academy Owner",
        role="Super Owner",
        password_hash="unused-synthetic-hash",
        organization_id=organization_id,
        organization_name="Isolated Academy Organization",
        organization_plan="enterprise",
        permissions=["*"],
    )
    case = SimpleNamespace(
        sessions=sessions,
        engine=engine,
        schema=schema,
        application_name=schema,
        actor=actor,
        course_id=course_id,
        operation_id=operation_id,
        generation=3,
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
                    slug=f"isolated-academy-{organization_id}",
                    plan="enterprise",
                    status="active",
                )
            )
            await session.flush()
            session.add(
                User(
                    id=actor_id,
                    organization_id=organization_id,
                    name=actor.name,
                    email=actor.email,
                    password_hash=actor.password_hash,
                    status="active",
                )
            )
            await session.flush()
            session.add(
                AcademyCourse(
                    id=course_id,
                    organization_id=organization_id,
                    code=f"synthetic-{course_id}",
                    title="Synthetic Academy Course",
                    passing_score=80.0,
                    status="active",
                    created_by_id=actor_id,
                )
            )
            session.add(
                OwnerControlRecord(
                    domain=admission.DOMAIN,
                    resource_id=admission.RESOURCE_ID,
                    status="open",
                    enabled=True,
                    version=case.generation,
                    payload={
                        "schema_version": admission.ACADEMY_SCHEMA_VERSION,
                        "scope": admission.ACADEMY_COVERAGE_SCOPE,
                        "generation": case.generation,
                        "operation_id": operation_id,
                        "reason": "isolated-academy-contracts",
                        "changed_at": datetime.now(UTC).isoformat(),
                        "full_host_closure": False,
                    },
                )
            )
            await session.commit()

        # All exercised independent operations also receive sessions explicitly:
        # replacing a module name cannot change an already-bound Python default.
        for module in (database, admission, maintenance, runtime, worker_module):
            if hasattr(module, "SessionLocal"):
                monkeypatch.setattr(module, "SessionLocal", sessions)
        yield case
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


async def _create_in_session(case, session, *, idempotency_key):
    course = await session.get(AcademyCourse, case.course_id)
    assert course is not None
    return await runtime.create_package_job(
        session,
        case.actor,
        course,
        idempotency_key=idempotency_key,
        domain="Synthetic maintenance contracts",
        audience="Synthetic learners",
        locales=["en"],
        module_count=1,
        lessons_per_module=1,
        citations=[],
    )


async def create_queued_package(case, *, idempotency_key=None) -> str:
    """Create and commit one pristine package using the real producer."""
    async with case.sessions() as session:
        package = await _create_in_session(
            case, session, idempotency_key=idempotency_key or str(uuid4())
        )
        await session.commit()
        return package.id


async def reject_activity_insert_at_commit(case) -> None:
    """Make PostgreSQL reject the actual activity-registration COMMIT."""
    async with case.sessions() as session:
        await session.execute(
            text(
                """
                CREATE FUNCTION reject_academy_activity_commit()
                RETURNS trigger LANGUAGE plpgsql AS $function$
                BEGIN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'synthetic academy activity commit rejected';
                    RETURN NEW;
                END;
                $function$
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE CONSTRAINT TRIGGER reject_academy_activity_commit
                AFTER INSERT ON host_maintenance_work_cycles
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW
                WHEN (NEW.consumer = 'academy_course_packages')
                EXECUTE FUNCTION reject_academy_activity_commit()
                """
            )
        )
        await session.commit()


async def _close(case):
    return await admission.close_admission(
        operation_id=case.operation_id,
        expected_generation=case.generation,
        reason="isolated-academy-close",
        session_factory=case.sessions,
    )


async def _reopen(case, closed):
    return await admission.open_admission(
        operation_id=case.operation_id,
        expected_generation=closed.generation,
        reason="isolated-academy-reopen",
        session_factory=case.sessions,
    )


async def _snapshot(case):
    async with case.sessions() as session:
        result = {}
        for model in (AcademyCoursePackage, HostMaintenanceWorkCycle):
            records = list(
                (await session.scalars(select(model).order_by(model.id))).all()
            )
            result[model.__tablename__] = [
                {
                    column.key: copy.deepcopy(getattr(record, column.key))
                    for column in inspect(model).column_attrs
                }
                for record in records
            ]
        return result


async def _claim(case):
    async with case.sessions() as session:
        ownership = await runtime.claim_next_package(
            session, worker_incarnation=str(uuid4())
        )
        await session.commit()
        return ownership


async def _publish(session, package, ownership, outcome):
    if outcome == "complete":
        await runtime.complete_package(
            session,
            package,
            ownership=ownership,
            site_relpath=f"synthetic/{package.id}/index.html",
            archive_relpath=f"synthetic/{package.id}/course.zip",
            archive_sha256="a" * 64,
            manifest_sha256="b" * 64,
            archive_bytes=64,
            curriculum={"lessons": [{"key": "module-1-lesson-1"}]},
        )
    else:
        assert outcome == "fail"
        await runtime.fail_package(
            session,
            package,
            ownership=ownership,
            code="synthetic-build-failed",
            message="Synthetic package publication failure",
        )


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
@pytest.mark.parametrize("outcome", ["commit", "rollback"])
async def test_real_producer_holds_admission_through_its_commit_or_rollback(
    academy_case, monkeypatch, outcome
):
    case = academy_case
    admitted = asyncio.Event()
    release_producer = asyncio.Event()
    staged = asyncio.Event()
    release_transaction = asyncio.Event()
    transaction_identity = None
    actual_guard = runtime.require_academy_admission
    idempotency_key = str(uuid4())

    async def guarded_producer(session):
        nonlocal transaction_identity
        allowed = await actual_guard(session)
        transaction_identity = (
            await session.scalar(text("SELECT pg_backend_pid()")),
            await session.scalar(text("SELECT txid_current()")),
        )
        admitted.set()
        await release_producer.wait()
        return allowed

    async def produce():
        async with case.sessions() as session:
            package = await _create_in_session(
                case, session, idempotency_key=idempotency_key
            )
            # The flushed package and the shared admission lock belong to the
            # identical connection and transaction until the caller publishes.
            assert (
                await session.scalar(text("SELECT pg_backend_pid()")),
                await session.scalar(text("SELECT txid_current()")),
            ) == transaction_identity
            assert package.status == "queued"
            async with case.sessions() as observer:
                assert await observer.get(AcademyCoursePackage, package.id) is None
            package_id = package.id
            staged.set()
            await release_transaction.wait()
            assert (
                await session.scalar(text("SELECT pg_backend_pid()")),
                await session.scalar(text("SELECT txid_current()")),
            ) == transaction_identity
            if outcome == "commit":
                await session.commit()
            else:
                await session.rollback()
            return package_id

    monkeypatch.setattr(runtime, "require_academy_admission", guarded_producer)
    producer_task = asyncio.create_task(produce())
    close_task = None
    try:
        await asyncio.wait_for(admitted.wait(), timeout=WAIT_SECONDS)
        assert transaction_identity is not None
        holder_pid = transaction_identity[0]
        close_task = asyncio.create_task(_close(case))
        await _wait_for_close_blocked_by(case, holder_pid)
        assert not close_task.done() and not producer_task.done()

        release_producer.set()
        await asyncio.wait_for(staged.wait(), timeout=WAIT_SECONDS)
        await _wait_for_close_blocked_by(case, holder_pid)
        assert not close_task.done() and not producer_task.done()
        release_transaction.set()

        package_id = await asyncio.wait_for(producer_task, timeout=WAIT_SECONDS)
        closed = await asyncio.wait_for(close_task, timeout=WAIT_SECONDS)
        assert not closed.is_open
        async with case.sessions() as observer:
            package = await observer.get(AcademyCoursePackage, package_id)
            assert (package is not None) is (outcome == "commit")
            if package is not None:
                assert package.status == "queued"
                assert package.request_payload["locales"] == ["en"]

        before = await _snapshot(case)
        for key in (idempotency_key, str(uuid4())):
            with pytest.raises(admission.HostMaintenanceClosed):
                await create_queued_package(case, idempotency_key=key)
        assert await _snapshot(case) == before
    finally:
        release_producer.set()
        release_transaction.set()
        await _settle_tasks(producer_task, close_task)


@pytest.mark.asyncio
async def test_closed_claim_preserves_queued_stale_legacy_and_provenance_rows(
    academy_case,
):
    case = academy_case
    owned_id = await create_queued_package(case)
    ownership = await _claim(case)
    assert ownership is not None and ownership.package_id == owned_id
    queued_id = await create_queued_package(case)
    legacy_id = await create_queued_package(case)
    provenance_id = await create_queued_package(case)
    old = datetime.now(UTC) - timedelta(days=3)

    async with case.sessions() as session:
        owned = await session.get(AcademyCoursePackage, owned_id)
        legacy = await session.get(AcademyCoursePackage, legacy_id)
        provenance = await session.get(AcademyCoursePackage, provenance_id)
        activity = await session.get(
            HostMaintenanceWorkCycle, ownership.activity_id
        )
        assert all(row is not None for row in (owned, legacy, provenance, activity))
        owned.updated_at = old
        legacy.status = "building"
        legacy.updated_at = old
        legacy.error_code = "legacy-build-provenance"
        legacy.error_message = "Synthetic unfinished legacy attempt"
        provenance.archive_relpath = "synthetic/prior-attempt.zip"
        provenance.curriculum = {"lessons": [{"key": "prior-attempt"}]}
        provenance.created_at = old
        provenance.updated_at = old
        activity.started_at = old
        activity.heartbeat_at = old
        activity.lease_expires_at = old + timedelta(seconds=120)
        await session.commit()

    closed = await _close(case)
    before = await _snapshot(case)
    assert await _claim(case) is None
    assert await _claim(case) is None
    assert await _snapshot(case) == before

    # Reopening permits only the untouched fresh queue entry. It cannot reclaim
    # either expired owned work, legacy building work, or a prior result.
    await _reopen(case, closed)
    accepted = await _claim(case)
    assert accepted is not None and accepted.package_id == queued_id
    assert await _claim(case) is None
    after = await _snapshot(case)
    original_rows = {
        row["id"]: row for row in before[AcademyCoursePackage.__tablename__]
    }
    final_rows = {
        row["id"]: row for row in after[AcademyCoursePackage.__tablename__]
    }
    for package_id in (owned_id, legacy_id, provenance_id):
        assert final_rows[package_id] == original_rows[package_id]
    original_activity = before[HostMaintenanceWorkCycle.__tablename__][0]
    assert original_activity in after[HostMaintenanceWorkCycle.__tablename__]


@pytest.mark.asyncio
async def test_claim_and_activity_roll_back_together_when_postgres_rejects_commit(
    academy_case,
):
    case = academy_case
    package_id = await create_queued_package(case)
    before = await _snapshot(case)
    await reject_activity_insert_at_commit(case)

    async with case.sessions() as session:
        original_transaction = (
            await session.scalar(text("SELECT pg_backend_pid()")),
            await session.scalar(text("SELECT txid_current()")),
        )
        ownership = await runtime.claim_next_package(
            session, worker_incarnation=str(uuid4())
        )
        assert ownership is not None and ownership.package_id == package_id
        package = await session.get(AcademyCoursePackage, package_id)
        assert package is not None and package.status == "building"
        activity = await session.get(HostMaintenanceWorkCycle, ownership.activity_id)
        assert activity is not None and activity.state == "active"
        assert (
            await session.scalar(text("SELECT pg_backend_pid()")),
            await session.scalar(text("SELECT txid_current()")),
        ) == original_transaction

        # A returned capability alone has published neither building status nor
        # an owner. The constraint fires at the real PostgreSQL COMMIT boundary.
        async with case.sessions() as observer:
            committed_package = await observer.get(AcademyCoursePackage, package_id)
            assert committed_package is not None
            assert committed_package.status == "queued"
            assert await observer.get(
                HostMaintenanceWorkCycle, ownership.activity_id
            ) is None
        with pytest.raises(IntegrityError, match=ACTIVITY_COMMIT_REJECTION):
            await session.commit()
        await session.rollback()

    assert await _snapshot(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "fail"])
async def test_exact_owner_can_publish_and_finish_while_admission_is_closed(
    academy_case, outcome
):
    case = academy_case
    package_id = await create_queued_package(case)
    ownership = await _claim(case)
    assert ownership is not None and ownership.package_id == package_id
    closed = await _close(case)
    before = await _snapshot(case)

    with pytest.raises(maintenance.AcademyActivityOwnershipLost):
        await maintenance.finish_academy_activity(
            ownership, session_factory=case.sessions
        )
    assert await _snapshot(case) == before

    async with case.sessions() as session:
        package = await session.get(AcademyCoursePackage, package_id)
        assert package is not None
        await _publish(session, package, ownership, outcome)
        await session.commit()

    async with case.sessions() as observer:
        package = await observer.get(AcademyCoursePackage, package_id)
        activity = await observer.get(
            HostMaintenanceWorkCycle, ownership.activity_id
        )
        assert package is not None and activity is not None
        assert activity.state == "active"
        assert activity.admitted_generation == case.generation
        if outcome == "complete":
            assert package.status == "review_pending"
            assert package.completed_at is not None
            assert package.archive_sha256 == "a" * 64
            assert package.archive_bytes == 64
            assert package.curriculum == {
                "lessons": [{"key": "module-1-lesson-1"}]
            }
        else:
            assert package.status == "failed"
            assert package.error_code == "synthetic-build-failed"
            assert package.error_message == "Synthetic package publication failure"
            assert package.completed_at is None

    # Terminal publication is committed before the separate owner release.
    await maintenance.finish_academy_activity(
        ownership, session_factory=case.sessions
    )
    async with case.sessions() as observer:
        assert await observer.get(
            HostMaintenanceWorkCycle, ownership.activity_id
        ) is None
        authority = await admission.read_admission_snapshot(
            observer, required_scope=maintenance.CONSUMER
        )
        assert not authority.is_open and authority.generation == closed.generation
    assert await _claim(case) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "fail"])
@pytest.mark.parametrize(
    "mismatch",
    [
        "activity_id",
        "package_id",
        "worker_incarnation",
        "admitted_generation",
        "ownership_nonce",
    ],
)
async def test_publication_rejects_every_mismatched_owner_without_mutation(
    academy_case, outcome, mismatch
):
    case = academy_case
    package_id = await create_queued_package(case)
    ownership = await _claim(case)
    assert ownership is not None and ownership.package_id == package_id
    await _close(case)
    before = await _snapshot(case)
    wrong_value = (
        ownership.admitted_generation + 1
        if mismatch == "admitted_generation"
        else str(uuid4())
    )
    wrong_owner = replace(ownership, **{mismatch: wrong_value})

    async with case.sessions() as session:
        package = await session.get(AcademyCoursePackage, package_id)
        assert package is not None
        with pytest.raises(maintenance.AcademyActivityOwnershipLost):
            await _publish(session, package, wrong_owner, outcome)
        await session.rollback()

    assert await _snapshot(case) == before
