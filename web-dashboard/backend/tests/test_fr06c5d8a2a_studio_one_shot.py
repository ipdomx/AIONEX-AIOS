"""Real PostgreSQL Studio no-replay fences; not full resource-settlement proof.

Every test owns its schema. The real build/store success is tested separately
from execution-boundary sentinels. No production database or provider is used.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import Base
from app.db.models import Notification, ProjectEvent, StudioExecution, StudioJob, StudioSafetyReview
from app.services import host_maintenance_admission as admission
from app.services import studio_execution_guard as guards
from app.services import studio_worker as workers

_name = "fr06d8a2a_request_fixture"
_spec = importlib.util.spec_from_file_location(
    _name, Path(__file__).with_name("test_fr06c5d8a1_studio_request_admission.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
WAIT = 8


def _guard(**changes):
    return {
        "protocol_version": 1, "phase": "claimed", "worker_incarnation": str(uuid4()),
        "admitted_generation": 7, "cleanup_verified": False, **changes,
    }


@pytest.mark.parametrize("value", [
    None, [], "claimed", {}, _guard(protocol_version=True), _guard(protocol_version="1"),
    _guard(protocol_version=2), _guard(phase=[]), _guard(phase="settled"),
    _guard(worker_incarnation="unknown"), _guard(worker_incarnation=7),
    _guard(admitted_generation=True), _guard(admitted_generation=6),
    _guard(admitted_generation="7"), _guard(cleanup_verified=True),
    _guard(cleanup_verified=0), _guard(extra="untrusted"),
])
def test_invalid_provenance_never_authorizes_execution(value):
    assert guards.execution_guard(StudioJob(result_metadata={guards.GUARD_KEY: value})) is None


@pytest.mark.parametrize("phase", sorted(guards.PHASES))
def test_all_guard_phases_explicitly_leave_cleanup_unverified(phase):
    job = StudioJob(result_metadata={guards.GUARD_KEY: _guard(), "preserved": 1})
    guards.set_phase(job, phase)
    assert job.result_metadata["preserved"] == 1
    assert guards.execution_guard(job)["phase"] == phase
    assert guards.execution_guard(job)["cleanup_verified"] is False


@pytest_asyncio.fixture
async def execution_case(studio_case, monkeypatch, tmp_path):
    case = studio_case
    extra = {Notification.__table__, StudioSafetyReview.__table__, ProjectEvent.__table__, StudioExecution.__table__}
    while True:
        expanded = extra | {fk.column.table for table in extra for fk in table.foreign_keys}
        if expanded == extra:
            break
        extra = expanded
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=list(extra)))
    case.worker = workers.StudioWorker(session_factory=case.sessions)
    case.root = tmp_path / "studio-assets"
    monkeypatch.setattr(workers, "SessionLocal", case.sessions)
    monkeypatch.setattr(workers.settings, "STUDIO_ASSET_ROOT", str(case.root))
    monkeypatch.setattr(workers.StudioWorker, "write_health", lambda self, status: None)
    return case


async def _new(case, **changes):
    values = dict(
        id=str(uuid4()), organization_id=case.actor.organization_id,
        requested_by_id=case.actor.id, department="text", output_kind="document",
        title="Synthetic Studio build", brief="Prepare a harmless synthetic project briefing.",
        language="en-US", style="modern", provider_mode="provider_neutral", status="queued",
        progress=0, attempts=0, max_attempts=3, result_metadata={}, safety_status="pending",
    )
    values.update(changes)
    async with case.sessions() as session:
        session.add(StudioJob(**values))
        await session.commit()
    return values["id"]


async def _row(case, identifier):
    async with case.sessions() as session:
        result = (await session.execute(select(StudioJob.__table__).where(
            StudioJob.id == identifier,
        ))).mappings().one()
        return deepcopy(dict(result))


async def _terminal(case, identifier):
    async with case.sessions() as session:
        job = await session.get(StudioJob, identifier)
        guards.set_phase(job, "returned")
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.lease_token = None
        await session.commit()


async def _claim(case, mode, identifier):
    return await case.worker.claim() if mode == "queue" else await case.worker.claim_by_id(identifier)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queue", "by_id"])
async def test_claim_persists_owner_and_generation_before_io(execution_case, mode):
    case = execution_case
    identifier = await _new(case)
    result = await _claim(case, mode, identifier)
    row = await _row(case, identifier)
    assert result and result[0] == identifier and result[1] == row["lease_token"]
    assert row["status"] == "running" and row["attempts"] == 1
    guard = row["result_metadata"][guards.GUARD_KEY]
    assert guard["worker_incarnation"] == case.worker.incarnation
    assert guard["phase"] == "claimed" and guard["admitted_generation"] == 7
    assert guard["cleanup_verified"] is False and row["completed_at"] is None
    assert not case.root.exists()
    assert await _claim(case, mode, identifier) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queue", "by_id"])
@pytest.mark.parametrize("changes", [
    {"status": "running", "attempts": 1, "updated_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"status": "failed"}, {"status": "cancelled"}, {"status": "completed"},
    {"status": "cancel_requested"}, {"attempts": 1}, {"max_attempts": 0}, {"progress": 10},
    {"started_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"completed_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"cancelled_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"lease_token": "old-unproven-claim"}, {"error_code": "UNCERTAIN"},
    {"error_message": "unresolved"}, {"safety_status": "passed"},
    {"safety_findings": [{"review": "old"}]}, {"result_metadata": []},
    {"result_metadata": {guards.GUARD_KEY: None}}, {"result_metadata": {"old_output": True}},
    {"provider_mode": "livekit_egress"}, {"provider": "legacy-provider"}, {"model": "legacy-model"},
])
async def test_nonpristine_jobs_are_not_claimed_or_changed(execution_case, mode, changes):
    case = execution_case
    identifier = await _new(case, **changes)
    before = await _row(case, identifier)
    assert await _claim(case, mode, identifier) is None
    assert await _row(case, identifier) == before
    assert not case.root.exists()


@pytest.mark.asyncio
async def test_old_queued_rows_do_not_starve_pristine_work(execution_case):
    case = execution_case
    old = await _new(case, attempts=1, created_at=datetime(2000, 1, 1, tzinfo=UTC))
    pristine = await _new(case)
    before = await _row(case, old)
    result = await case.worker.claim()
    assert result and result[0] == pristine
    assert await _row(case, old) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queue", "by_id"])
@pytest.mark.parametrize("state", ["closed", "missing", "old_scope", "corrupt"])
async def test_claim_denial_precedes_job_writes(execution_case, mode, state):
    case = execution_case
    identifier = await _new(case)
    before = await _row(case, identifier)
    if state == "closed":
        await _shared._close(case)
    elif state == "missing":
        await _shared._change(case, remove=True)
    elif state == "old_scope":
        await _shared._change(case, schema_version=6, scope=admission.SCAN_REQUEST_COVERAGE_SCOPE)
    else:
        await _shared._change(case, generation="7")
    error = admission.HostMaintenanceClosed if state == "closed" else admission.HostMaintenanceUnavailable
    with pytest.raises(error):
        await _claim(case, mode, identifier)
    assert await _row(case, identifier) == before
    assert not case.root.exists()


@pytest.mark.asyncio
async def test_concurrent_public_claims_and_repeated_starts_execute_once(execution_case, monkeypatch):
    case = execution_case
    identifier = await _new(case)
    other = workers.StudioWorker(session_factory=case.sessions)
    result = await asyncio.wait_for(asyncio.gather(
        case.worker.claim(), other.claim_by_id(identifier),
    ), WAIT)
    winners = [item for item in result if item is not None]
    assert len(winners) == 1
    winner = case.worker if result[0] else other
    claimed = winners[0]
    calls = []
    async def execute(self, job_id, nonce):
        calls.append(job_id)
        await asyncio.sleep(0.03)
        await _terminal(case, job_id)
    monkeypatch.setattr(workers.StudioWorker, "_execute_claimed", execute)
    await workers.StudioWorker(session_factory=case.sessions).execute(*claimed)
    assert not calls
    await asyncio.wait_for(asyncio.gather(*(winner.execute(*claimed) for _ in range(16))), WAIT)
    assert calls == [identifier]
    assert (await _row(case, identifier))["status"] == "completed"
    await winner.execute(*claimed)
    assert calls == [identifier]


@pytest.mark.asyncio
async def test_close_prevents_start_and_reopen_does_not_adopt_old_generation(execution_case, monkeypatch):
    case = execution_case
    identifier = await _new(case)
    claimed = await case.worker.claim()
    closed = await _shared._close(case)
    calls = []
    async def execute(self, *args):
        calls.append(args)
    monkeypatch.setattr(workers.StudioWorker, "_execute_claimed", execute)
    with pytest.raises(admission.HostMaintenanceClosed):
        await case.worker.execute(*claimed)
    await admission.open_admission(
        operation_id=case.operation_id, expected_generation=closed.generation,
        reason="isolated reopen must not revive an old claim", session_factory=case.sessions,
    )
    await case.worker.execute(*claimed)
    assert not calls
    row = await _row(case, identifier)
    assert row["result_metadata"][guards.GUARD_KEY]["phase"] == "claimed"
    assert row["attempts"] == 1 and row["lease_token"] == claimed[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["claim", "begin"])
@pytest.mark.parametrize("acknowledgement_lost", [False, True])
async def test_commit_failure_never_dispatches_io(execution_case, monkeypatch, stage, acknowledgement_lost):
    case = execution_case
    identifier = await _new(case)
    claimed = await case.worker.claim() if stage == "begin" else None
    class BrokenCommit(AsyncSession):
        async def commit(self):
            await self.flush()
            if acknowledgement_lost:
                await super().commit()
            raise SQLAlchemyError("synthetic commit acknowledgement failure")
    case.worker._session_factory = async_sessionmaker(case.engine, class_=BrokenCommit, expire_on_commit=False)
    calls = []
    async def execute(self, *args):
        calls.append(args)
    monkeypatch.setattr(workers.StudioWorker, "_execute_claimed", execute)
    with pytest.raises(SQLAlchemyError):
        if stage == "claim":
            await case.worker.claim()
        else:
            await case.worker.execute(*claimed)
    assert not calls and not case.root.exists()
    row = await _row(case, identifier)
    case.worker._session_factory = case.sessions
    if acknowledgement_lost:
        assert row["attempts"] == 1 and await case.worker.claim() is None
        if stage == "begin":
            assert row["result_metadata"][guards.GUARD_KEY]["phase"] == "executing"
            await case.worker.execute(*claimed)
            assert not calls
    elif stage == "claim":
        assert row["status"] == "queued" and row["attempts"] == 0
    else:
        assert row["result_metadata"][guards.GUARD_KEY]["phase"] == "claimed"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["claim", "begin"])
@pytest.mark.parametrize("outcome", ["commit", "failure", "cancel"])
async def test_close_waits_for_claim_and_start_commit_or_rollback(execution_case, stage, outcome):
    case = execution_case
    await _new(case)
    claimed = await case.worker.claim() if stage == "begin" else None
    probe = SimpleNamespace(ready=asyncio.Event(), release=asyncio.Event(), fail=outcome == "failure", cancel=outcome == "cancel")
    case.worker._session_factory = async_sessionmaker(
        case.engine, class_=_shared._CommitProbe, expire_on_commit=False,
        info={"studio_probe": probe},
    )
    action = case.worker.claim() if stage == "claim" else case.worker._begin_execution(*claimed)
    task = asyncio.create_task(action)
    closer = None
    try:
        await asyncio.wait_for(probe.ready.wait(), WAIT)
        started = asyncio.Queue()
        factory = async_sessionmaker(
            case.engine, class_=_shared._CloseProbe, expire_on_commit=False,
            info={"closer_started": started},
        )
        closer = asyncio.create_task(_shared._close(case, factory))
        pid = await asyncio.wait_for(started.get(), WAIT)
        async with case.sessions() as session, asyncio.timeout(WAIT):
            while not await session.scalar(text("SELECT count(*) FROM pg_locks WHERE pid=:pid AND NOT granted"), {"pid": pid}):
                if closer.done():
                    await closer
                    raise AssertionError("Closure returned before the protected commit")
                await asyncio.sleep(0.01)
        assert not closer.done()
        probe.release.set()
        results = await asyncio.wait_for(asyncio.gather(task, closer, return_exceptions=True), WAIT)
        assert not isinstance(results[1], BaseException)
        if outcome == "commit":
            assert not isinstance(results[0], BaseException)
        else:
            assert isinstance(results[0], asyncio.CancelledError if outcome == "cancel" else SQLAlchemyError)
    finally:
        probe.release.set()
        pending = [item for item in (task, closer) if item is not None]
        for item in pending:
            if not item.done():
                item.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_interruption_retains_exact_attempt_and_blocks_retry(execution_case, monkeypatch, cancel):
    case = execution_case
    identifier = await _new(case)
    claimed = await case.worker.claim()
    started = asyncio.Event()
    async def execute(self, *args):
        started.set()
        if not cancel:
            raise OSError("synthetic artifact failure")
        await asyncio.Event().wait()
    monkeypatch.setattr(workers.StudioWorker, "_execute_claimed", execute)
    task = asyncio.create_task(case.worker.execute(*claimed))
    await asyncio.wait_for(started.wait(), WAIT)
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else OSError):
        await task
    row = await _row(case, identifier)
    assert row["status"] == "running" and row["attempts"] == 1
    assert row["lease_token"] == claimed[1] and row["completed_at"] is None
    assert row["result_metadata"][guards.GUARD_KEY]["phase"] == "unresolved"
    response = await case.client.post(f"/studio/jobs/{identifier}/cancel")
    assert response.status_code == 200 and response.json()["status"] == "cancel_requested"
    after = await _row(case, identifier)
    assert after["lease_token"] == claimed[1] and after["completed_at"] is None
    repeat = await case.client.post(f"/studio/jobs/{identifier}/cancel")
    assert repeat.status_code == 200 and await _row(case, identifier) == after
    assert (await case.client.post(f"/studio/jobs/{identifier}/retry")).status_code == 409
    assert await case.worker.claim() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"attempts": 1}, {"started_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"result_metadata": {guards.GUARD_KEY: _guard()}}, {"result_metadata": {"output": "old"}},
    {"result_metadata": []}, {"provider_mode": "livekit_egress"},
    {"provider": "old-provider"}, {"safety_status": "passed"},
])
async def test_legacy_terminal_rows_cannot_be_reset_to_pristine(execution_case, changes):
    case = execution_case
    identifier = await _new(case, status="cancelled", **changes)
    before = await _row(case, identifier)
    response = await case.client.post(f"/studio/jobs/{identifier}/retry")
    assert response.status_code == 409
    assert await _row(case, identifier) == before


@pytest.mark.asyncio
async def test_never_started_cancel_can_be_explicitly_retried(execution_case):
    case = execution_case
    identifier = await _new(case)
    cancelled = await case.client.post(f"/studio/jobs/{identifier}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    retried = await case.client.post(f"/studio/jobs/{identifier}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert await case.worker.claim_by_id(identifier) is not None


@pytest.mark.asyncio
async def test_real_archive_and_store_complete_without_erasing_guard(execution_case):
    case = execution_case
    identifier = await _new(case)
    claimed = await case.worker.claim()
    await case.worker.execute(*claimed)
    row = await _row(case, identifier)
    assert row["status"] == "completed", row["error_code"]
    guard = row["result_metadata"][guards.GUARD_KEY]
    assert guard["phase"] == "returned" and guard["cleanup_verified"] is False
    archives = list(case.root.rglob("*.zip"))
    assert len(archives) == 1 and archives[0].stat().st_size > 0
    original = archives[0].read_bytes()
    await case.worker.execute(*claimed)
    assert archives[0].read_bytes() == original
    assert len(list(case.root.rglob("*.zip"))) == 1


@pytest.mark.asyncio
async def test_build_failure_remains_unresolved_not_requeued(execution_case, monkeypatch):
    case = execution_case
    identifier = await _new(case)
    claimed = await case.worker.claim()
    def fail(*args, **kwargs):
        raise OSError("synthetic build failure")
    monkeypatch.setattr(workers, "build_archive", fail)
    await case.worker.execute(*claimed)
    row = await _row(case, identifier)
    assert row["status"] == "running" and row["attempts"] == 1
    assert row["lease_token"] == claimed[1] and row["completed_at"] is None
    assert row["result_metadata"][guards.GUARD_KEY]["phase"] == "unresolved"
    assert row["error_code"] == "STUDIO_RECONCILIATION_REQUIRED"
    assert row["error_message"] == "STUDIO_GENERATION_FAILED"
    assert await case.worker.claim() is None


@pytest.mark.asyncio
async def test_closed_idle_worker_is_not_a_worker_error(execution_case):
    case = execution_case
    await _shared._close(case)
    assert await case.worker.run_once() is False
    assert case.worker.errors == 0 and case.worker.cycles == 0
