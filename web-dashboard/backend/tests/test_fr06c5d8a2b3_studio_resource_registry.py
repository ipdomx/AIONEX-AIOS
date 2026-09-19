"""Real disposable PostgreSQL, worker, thread and retention acceptance.

No production data, provider, target scan or real user content is used. These
contracts prove durable ownership and thread evidence, not filesystem settlement.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
import threading
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from app.db.models import StudioExecution, StudioJob, StudioPoststartCancellation
from app.services import studio_resource_registry as registry
from app.services import studio_worker as workers

_name = "fr06d8b3_studio_execution_fixture"
_spec = importlib.util.spec_from_file_location(
    _name, Path(__file__).with_name("test_fr06c5d8a2a_studio_one_shot.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case


def _migration(connection, direction="upgrade"):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260918_0055_studio_execution_resources.py"
    spec = importlib.util.spec_from_file_location("studio_resource_migration_" + uuid4().hex, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


async def _ledger(case, job_id):
    async with case.sessions() as session:
        result = (await session.execute(select(StudioExecution.__table__).where(
            StudioExecution.job_id == job_id,
        ))).mappings().one_or_none()
        return None if result is None else deepcopy(dict(result))


async def _started(case):
    identifier = await _shared._new(case)
    claim = await case.worker.claim_by_id(identifier)
    assert claim is not None
    assert await case.worker._begin_execution(*claim)
    async with case.sessions() as session:
        owner = await registry.find_owner(
            session, job_id=identifier, nonce=claim[1], worker_incarnation=case.worker.incarnation,
        )
    return claim, owner


async def _until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.002)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["claim", "claim_by_id"])
async def test_both_claims_atomically_create_durable_owner(execution_case, mode):
    case = execution_case
    identifier = await _shared._new(case)
    claim = await case.worker.claim() if mode == "claim" else await case.worker.claim_by_id(identifier)
    assert claim is not None and claim[0] == identifier
    row = await _ledger(case, identifier)
    job = await _shared._row(case, identifier)
    assert row["job_id"] == identifier and row["worker_incarnation"] == case.worker.incarnation
    assert row["ownership_nonce"] == claim[1] and job["lease_token"] == claim[1]
    assert row["admitted_generation"] == 7
    assert row["state"] == "active" and row["phase"] == "claimed" and row["resources"] == {}
    assert row["cleanup_verified"] is False
    assert await case.worker.claim_by_id(identifier) is None


@pytest.mark.asyncio
async def test_registration_rollback_removes_intent_without_touching_job(execution_case):
    case = execution_case
    identifier = await _shared._new(case)
    before = await _shared._row(case, identifier)
    async with case.sessions() as session:
        await registry.register_claim(session, job_id=identifier, nonce=str(uuid4()), worker_incarnation=case.worker.incarnation)
        assert await _ledger(case, identifier) is None
        await session.rollback()
    assert await _ledger(case, identifier) is None
    assert await _shared._row(case, identifier) == before


@pytest.mark.asyncio
async def test_prior_owner_survives_business_row_deletion(execution_case):
    case = execution_case
    identifier = await _shared._new(case)
    assert await case.worker.claim_by_id(identifier)
    before = await _ledger(case, identifier)
    async with case.sessions() as session:
        await session.execute(delete(StudioJob).where(StudioJob.id == identifier))
        await session.commit()
    assert await _ledger(case, identifier) == before
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert any(item["job_id"] == identifier for item in snapshot["executions"])
    assert snapshot["is_clear"] is False and snapshot["full_host_closure"] is False


@pytest.mark.asyncio
async def test_reset_metadata_cannot_replay_or_starve_fresh_work(execution_case):
    case = execution_case
    identifier = await _shared._new(case)
    assert await case.worker.claim_by_id(identifier)
    before = await _ledger(case, identifier)
    async with case.sessions() as session:
        job = await session.get(StudioJob, identifier)
        job.status, job.attempts, job.progress = "queued", 0, 0
        job.started_at, job.lease_token, job.result_metadata = None, None, {}
        await session.commit()
    assert await case.worker.claim_by_id(identifier) is None
    fresh = await _shared._new(case)
    claim = await case.worker.claim()
    assert claim is not None and claim[0] == fresh
    assert await _ledger(case, identifier) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["execution_id", "job_id", "nonce", "worker_incarnation", "admitted_generation"])
async def test_every_owner_component_is_enforced(execution_case, field):
    case = execution_case
    claim, owner = await _started(case)
    changed = replace(owner, **{field: 8 if field == "admitted_generation" else str(uuid4())})
    before = await _ledger(case, claim[0])
    async with case.sessions() as session:
        with pytest.raises(registry.StudioOwnershipLost):
            await registry._locked(session, changed)
    assert await _ledger(case, claim[0]) == before
    assert owner.nonce not in repr(owner)


@pytest.mark.asyncio
async def test_cached_owner_cannot_hide_a_concurrent_change(execution_case):
    case = execution_case
    claim, owner = await _started(case)
    async with case.sessions() as cached:
        stale = await cached.get(StudioExecution, owner.execution_id)
        assert stale.worker_incarnation == owner.worker_incarnation
        async with case.sessions() as other:
            await other.execute(update(StudioExecution).where(StudioExecution.id == owner.execution_id).values(worker_incarnation=str(uuid4())))
            await other.commit()
        with pytest.raises(registry.StudioOwnershipLost):
            await registry._locked(cached, owner)


@pytest.mark.asyncio
async def test_worker_records_two_joined_threads_and_keeps_cleanup_unverified(execution_case):
    case = execution_case
    identifier = await _shared._new(case)
    claim = await case.worker.claim_by_id(identifier)
    await case.worker.execute(*claim)
    job = await _shared._row(case, identifier)
    row = await _ledger(case, identifier)
    assert job["status"] == "completed"
    assert row["phase"] == "returned" and row["returned_at"] is not None
    assert row["state"] == "unresolved" and row["cleanup_verified"] is False
    assert row["unresolved_reason"] == "filesystem_settlement_pending"
    assert {item["operation"] for item in row["resources"].values()} == {"build_archive", "store_artifact"}
    assert all(item["state"] == "joined" and item["outcome"] == "success" and item["cleanup_verified"] is False for item in row["resources"].values())
    archives = list(case.root.rglob("*.zip"))
    assert len(archives) == 1 and archives[0].stat().st_size > 0
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["is_clear"] is False
    serialized = json.dumps(snapshot)
    assert claim[1] not in serialized and "ownership_nonce" not in serialized
    assert snapshot["coverage_unverified"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["build_archive", "store_artifact"])
async def test_intent_is_committed_before_thread_runs(execution_case, monkeypatch, operation):
    case = execution_case
    identifier = await _shared._new(case)
    claim = await case.worker.claim_by_id(identifier)
    entered, release = threading.Event(), threading.Event()
    original = getattr(workers, operation)
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)
    monkeypatch.setattr(workers, operation, blocked)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await _until(entered.is_set)
        row = await _ledger(case, identifier)
        resource = next(value for value in row["resources"].values() if value["operation"] == operation)
        assert resource["state"] == "reserved" and resource["joined_at"] is None
        assert resource["cleanup_verified"] is False
    finally:
        release.set()
        await asyncio.gather(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 3, 16])
async def test_repeated_cancellation_keeps_intent_until_actual_join(execution_case, monkeypatch, count):
    case = execution_case
    identifier = await _shared._new(case)
    claim = await case.worker.claim_by_id(identifier)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = workers.build_archive
    def blocking(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(8)
            return original(*args, **kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(workers, "build_archive", blocking)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await _until(entered.is_set)
        for _ in range(count):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not finished.is_set()
        row = await _ledger(case, identifier)
        assert len(row["resources"]) == 1
        assert next(iter(row["resources"].values()))["state"] == "reserved"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = await _ledger(case, identifier)
        assert finished.is_set() and row["state"] == "unresolved"
        resource = next(iter(row["resources"].values()))
        assert resource["state"] == "joined" and resource["cleanup_verified"] is False
        assert await case.worker.claim_by_id(identifier) is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_during_store_retains_output_without_path_deletion(execution_case, monkeypatch):
    case = execution_case
    identifier = await _shared._new(case)
    claim = await case.worker.claim_by_id(identifier)
    entered, release = threading.Event(), threading.Event()
    original = workers.store_artifact
    paths = []
    def store(*args, **kwargs):
        path = original(*args, **kwargs)
        paths.append(path)
        entered.set()
        assert release.wait(8)
        return path
    monkeypatch.setattr(workers, "store_artifact", store)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await _until(entered.is_set)
        response = await case.client.post(f"/studio/jobs/{identifier}/cancel")
        assert response.status_code == 200
        release.set()
        await task
        assert len(paths) == 1 and paths[0].exists()
        assert (await _shared._row(case, identifier))["status"] == "cancelled"
        row = await _ledger(case, identifier)
        assert row["state"] == "unresolved" and row["cleanup_verified"] is False
        async with case.sessions() as session:
            receipt = await session.scalar(select(StudioPoststartCancellation).where(
                StudioPoststartCancellation.job_id == identifier,
            ))
            assert receipt is not None and receipt.publication_id is not None
            assert receipt.proof["accepted_archive_retained"] is True
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_work_cannot_reserve_another_thread(execution_case):
    case = execution_case
    claim, _owner = await _started(case)
    response = await case.client.post(f"/studio/jobs/{claim[0]}/cancel")
    assert response.status_code == 200
    with pytest.raises(registry.StudioResourceCancelled):
        await registry.reserve_thread(session_factory=case.sessions, job_id=claim[0], nonce=claim[1], worker_incarnation=case.worker.incarnation, operation="build_archive")
    assert (await _ledger(case, claim[0]))["resources"] == {}


@pytest.mark.asyncio
async def test_concurrent_resource_submission_is_single_use(execution_case):
    case = execution_case
    claim, _owner = await _started(case)
    async def reserve():
        return await registry.reserve_thread(session_factory=case.sessions, job_id=claim[0], nonce=claim[1], worker_incarnation=case.worker.incarnation, operation="build_archive")
    results = await asyncio.gather(*(reserve() for _ in range(16)), return_exceptions=True)
    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(isinstance(result, registry.StudioOwnershipLost) for result in results) == 15
    assert len((await _ledger(case, claim[0]))["resources"]) == 1


@pytest.mark.asyncio
async def test_storage_cannot_precede_joined_build(execution_case):
    case = execution_case
    claim, _owner = await _started(case)
    with pytest.raises(registry.StudioOwnershipLost, match="joined successful build"):
        await registry.reserve_thread(session_factory=case.sessions, job_id=claim[0], nonce=claim[1], worker_incarnation=case.worker.incarnation, operation="store_artifact")


@pytest.mark.asyncio
async def test_unknown_thread_completion_is_never_inferred(execution_case):
    case = execution_case
    claim, _owner = await _started(case)
    owner, resource_id = await registry.reserve_thread(session_factory=case.sessions, job_id=claim[0], nonce=claim[1], worker_incarnation=case.worker.incarnation, operation="build_archive")
    await registry.observe_thread(session_factory=case.sessions, owner=owner, resource_id=resource_id, joined=False, succeeded=False)
    row = await _ledger(case, claim[0])
    assert row["resources"][resource_id]["state"] == "unresolved"
    assert row["resources"][resource_id]["joined_at"] is None
    assert row["cleanup_verified"] is False
    with pytest.raises(registry.StudioOwnershipLost):
        await registry.observe_thread(session_factory=case.sessions, owner=owner, resource_id=resource_id, joined=True, succeeded=True)


@pytest.mark.asyncio
async def test_old_generation_and_old_timestamp_never_release_owner(execution_case):
    case = execution_case
    claim, _owner = await _started(case)
    await _shared._shared._close(case)
    async with case.sessions() as session:
        await session.execute(update(StudioExecution).where(StudioExecution.job_id == claim[0]).values(started_at=datetime.now(UTC) - timedelta(days=300)))
        await session.commit()
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["admission_closed"] is True
    assert any(row["job_id"] == claim[0] and row["admitted_generation"] == 7 for row in snapshot["executions"])
    assert snapshot["is_clear"] is False and snapshot["full_host_closure"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "cancel_requested", "failed", "cancelled", "completed", "unknown"])
async def test_unregistered_nonpristine_jobs_remain_blockers(execution_case, status):
    case = execution_case
    identifier = await _shared._new(case, status=status, attempts=1)
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert identifier in snapshot["unregistered_unverified_job_ids"]
    assert snapshot["is_clear"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {"bad-key": {}}, {str(uuid4()): {}}, [], None,
])
async def test_malformed_resource_inventory_fails_closed(execution_case, mutation):
    case = execution_case
    claim, _owner = await _started(case)
    async with case.sessions() as session:
        row = await session.scalar(select(StudioExecution).where(StudioExecution.job_id == claim[0]))
        row.resources = mutation
        await session.commit()
    with pytest.raises(registry.StudioResourceUncertain):
        await registry.execution_snapshot(session_factory=case.sessions)


@pytest.mark.asyncio
async def test_missing_registry_table_is_not_an_empty_snapshot(execution_case):
    case = execution_case
    async with case.engine.begin() as connection:
        await connection.execute(text("DROP TABLE studio_executions"))
    with pytest.raises(Exception) as error:
        await registry.execution_snapshot(session_factory=case.sessions)
    assert "studio_executions" in str(error.value)


@pytest.mark.asyncio
async def test_migration_preserves_exact_existing_table_and_rows(execution_case):
    case = execution_case
    claim, _owner = await _started(case)
    before = await _ledger(case, claim[0])
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    assert await _ledger(case, claim[0]) == before
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration, "downgrade")
    assert await _ledger(case, claim[0]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("ddl", [
    "ALTER TABLE studio_executions DROP CONSTRAINT ck_studio_execution_no_settlement",
    "ALTER TABLE studio_executions ADD COLUMN surprise TEXT",
    "ALTER TABLE studio_executions ALTER COLUMN job_id TYPE VARCHAR(100)",
    "DROP INDEX ix_studio_execution_unfinished",
])
async def test_migration_rejects_incompatible_existing_schema(execution_case, ddl):
    case = execution_case
    async with case.engine.begin() as connection:
        await connection.execute(text(ddl))
    with pytest.raises(RuntimeError, match="frozen schema"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration)


@pytest.mark.asyncio
async def test_database_rejects_fabricated_cleanup_success(execution_case):
    case = execution_case
    claim, _owner = await _started(case)
    with pytest.raises(IntegrityError):
        async with case.sessions() as session:
            await session.execute(update(StudioExecution).where(StudioExecution.job_id == claim[0]).values(cleanup_verified=True))
            await session.commit()
    assert (await _ledger(case, claim[0]))["cleanup_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_lost", [False, True])
async def test_claim_commit_failure_never_starts_io_or_reclaims_unknown(execution_case, monkeypatch, ack_lost):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    case = execution_case
    identifier = await _shared._new(case)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("no I/O after uncertain claim commit")
    monkeypatch.setattr(workers, "build_archive", forbidden)
    class BrokenCommit(AsyncSession):
        async def commit(self):
            if ack_lost:
                await super().commit()
            raise OSError("synthetic claim acknowledgement failure")
    worker = workers.StudioWorker(session_factory=async_sessionmaker(case.engine, class_=BrokenCommit, expire_on_commit=False))
    with pytest.raises(OSError):
        await worker.claim_by_id(identifier)
    row = await _ledger(case, identifier)
    assert (row is not None) is ack_lost
    assert not calls
    if ack_lost:
        assert await case.worker.claim_by_id(identifier) is None
        assert row["phase"] == "claimed" and row["cleanup_verified"] is False
    else:
        assert await case.worker.claim_by_id(identifier) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_lost", [False, True])
async def test_resource_commit_failure_never_launches_thread(execution_case, ack_lost):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    case = execution_case
    claim, _owner = await _started(case)
    calls = []
    class BrokenCommit(AsyncSession):
        async def commit(self):
            if ack_lost:
                await super().commit()
            raise OSError("synthetic resource acknowledgement failure")
    broken = async_sessionmaker(case.engine, class_=BrokenCommit, expire_on_commit=False)
    with pytest.raises(OSError):
        await registry.owned_studio_thread(broken, claim[0], claim[1], case.worker.incarnation, "build_archive", lambda: calls.append(True))
    assert not calls
    row = await _ledger(case, claim[0])
    assert len(row["resources"]) == int(ack_lost)
    assert all(value["state"] == "reserved" for value in row["resources"].values())
    assert row["cleanup_verified"] is False


@pytest.mark.asyncio
async def test_late_thread_observation_failure_keeps_original_cancellation(execution_case, monkeypatch):
    case = execution_case
    claim, _owner = await _started(case)
    entered, release = threading.Event(), threading.Event()
    def function():
        entered.set()
        assert release.wait(8)
        raise ValueError("synthetic late function failure")
    async def unavailable(**kwargs):
        raise OSError("synthetic journal write unavailable")
    monkeypatch.setattr(registry, "observe_thread", unavailable)
    task = asyncio.create_task(registry.owned_studio_thread(case.sessions, claim[0], claim[1], case.worker.incarnation, "build_archive", function))
    try:
        await _until(entered.is_set)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError) as error:
            await task
        assert isinstance(error.value.__cause__, ValueError)
        assert "OSError" in " ".join(error.value.__notes__)
        row = await _ledger(case, claim[0])
        assert next(iter(row["resources"].values()))["state"] == "reserved"
        assert row["cleanup_verified"] is False
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_snapshot_database_transaction_really_uses_repeatable_read(execution_case):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    case = execution_case
    observations = []
    class ObservedSession(AsyncSession):
        async def scalars(self, statement, *args, **kwargs):
            isolation = await super().scalar(text("SHOW transaction_isolation"))
            observations.append((tuple(table.name for table in statement.get_final_froms()), isolation))
            return await super().scalars(statement, *args, **kwargs)
    sessions = async_sessionmaker(case.engine, class_=ObservedSession, expire_on_commit=False)
    await registry.execution_snapshot(session_factory=sessions)
    # Every execution, queue, job, publication and settlement read shares one
    # snapshot. Match the queried tables, not just an increased query count.
    assert sorted(tables for tables, _ in observations) == sorted([
        ("studio_executions",), ("studio_jobs",), ("studio_jobs",),
        ("studio_publications",), ("studio_settlements",),
        ("studio_prestart_cancellations",), ("studio_poststart_cancellations",),
    ])
    assert {isolation for _, isolation in observations} == {"repeatable read"}


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_error", [OSError, asyncio.CancelledError])
@pytest.mark.parametrize("original_error", [ValueError, asyncio.CancelledError])
async def test_thread_journal_failure_never_replaces_original_error(
    execution_case, monkeypatch, journal_error, original_error,
):
    case = execution_case
    claim, _owner = await _started(case)
    original = original_error("synthetic original interruption")
    late_cause = LookupError("synthetic prior cause")
    def function():
        raise original from late_cause
    async def unavailable(**kwargs):
        raise journal_error("private-journal-detail-must-not-be-in-notes")
    monkeypatch.setattr(registry, "observe_thread", unavailable)
    with pytest.raises(original_error) as error:
        await registry.owned_studio_thread(
            case.sessions, claim[0], claim[1], case.worker.incarnation,
            "build_archive", function,
        )
    assert error.value is original
    assert error.value.__cause__ is late_cause
    notes = " ".join(error.value.__notes__)
    assert journal_error.__name__ in notes
    assert "private-journal-detail" not in notes
    row = await _ledger(case, claim[0])
    assert next(iter(row["resources"].values()))["state"] == "reserved"
    assert row["cleanup_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("function_finished", [False, True])
async def test_uncertain_join_never_certifies_completion_even_with_local_finished_flag(
    execution_case, monkeypatch, function_finished,
):
    # The uncertainty is an injected executor-boundary fault; PostgreSQL and
    # the function execution (when enabled) are real. No host-drain claim.
    case = execution_case
    claim, _owner = await _started(case)
    calls = []
    original_join = registry.joined_studio_thread
    async def uncertain(function):
        if function_finished:
            await original_join(function)
        raise registry.StudioThreadUncertain("synthetic executor completion uncertainty")
    monkeypatch.setattr(registry, "joined_studio_thread", uncertain)
    with pytest.raises(registry.StudioThreadUncertain):
        await registry.owned_studio_thread(
            case.sessions, claim[0], claim[1], case.worker.incarnation,
            "build_archive", lambda: calls.append(True),
        )
    assert len(calls) == int(function_finished)
    row = await _ledger(case, claim[0])
    resource = next(iter(row["resources"].values()))
    assert resource["state"] == "unresolved"
    assert resource["joined_at"] is None and resource["outcome"] is None
    assert row["state"] == "unresolved"
    assert row["unresolved_reason"] == "thread_completion_unverified"
    assert row["cleanup_verified"] is False
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    observed = next(item for item in snapshot["executions"] if item["job_id"] == claim[0])
    assert observed["joined_threads"] == 0
    assert snapshot["is_clear"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_error", [OSError, asyncio.CancelledError])
@pytest.mark.parametrize("original_error", [ValueError, asyncio.CancelledError])
async def test_worker_interruption_observation_preserves_original_error(
    execution_case, monkeypatch, journal_error, original_error,
):
    case = execution_case
    identifier = await _shared._new(case)
    claim = await case.worker.claim_by_id(identifier)
    original = original_error("synthetic worker interruption")
    cause = LookupError("synthetic worker cause")
    async def interrupted(*args):
        raise original from cause
    async def unavailable(**kwargs):
        raise journal_error("private-ledger-detail-must-not-be-in-notes")
    monkeypatch.setattr(case.worker, "_execute_claimed", interrupted)
    monkeypatch.setattr(registry, "observe_execution_end", unavailable)
    with pytest.raises(original_error) as error:
        await case.worker.execute(*claim)
    assert error.value is original and error.value.__cause__ is cause
    notes = " ".join(error.value.__notes__)
    assert journal_error.__name__ in notes
    assert "private-ledger-detail" not in notes
    row = await _ledger(case, identifier)
    assert row["phase"] == "executing" and row["cleanup_verified"] is False
    assert await case.worker.claim_by_id(identifier) is None
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["is_clear"] is False
