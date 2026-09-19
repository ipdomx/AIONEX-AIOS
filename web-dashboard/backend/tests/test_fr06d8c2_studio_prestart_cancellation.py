"""Pre-start cancellation on isolated PostgreSQL with the real claim/start/API.

This suite adds its own receipt table to the inherited isolated schema. It does
not modify historical fixtures or claim that interrupted payload work is clean.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.api.v1.endpoints import studio as api
from app.db.base import get_db
from app.db.models import (
    AuditEvent, StudioExecution, StudioJob, StudioPrestartCancellation,
    StudioPublication, StudioSettlement,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_prestart_cancellation as cancellation
from app.services import studio_resource_registry as registry
from app.services.studio_control_evidence import has_retained_studio_evidence
from app.services.studio_execution_guard import GUARD_KEY
from app.services.studio_result_binding import evidence_digest

_spec = importlib.util.spec_from_file_location(
    "fr06d8c2_claim_fixture", Path(__file__).with_name("test_fr06c5d8a2a_studio_one_shot.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case
_new, _row = _shared._new, _shared._row
WAIT = 10


@pytest_asyncio.fixture
async def prestart_case(execution_case):
    case = execution_case
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda conn: StudioPrestartCancellation.__table__.create(conn, checkfirst=True))
    return case


async def _rows(case, model):
    async with case.sessions() as session:
        return [deepcopy(dict(row)) for row in (await session.execute(
            select(model.__table__).order_by(model.id),
        )).mappings()]


async def _claimed(case):
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None and claim[0] == job_id
    assert not case.root.exists()
    return claim


async def _cancel(case, job_id):
    return await case.client.post(f"/studio/jobs/{job_id}/cancel")


async def _wait_for_block(case, waiter_pid, holder_pid):
    async with asyncio.timeout(WAIT):
        while True:
            async with case.sessions() as session:
                blockers = await session.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid})
            if holder_pid in blockers:
                return
            await asyncio.sleep(0.01)


class _JobLockProbe(AsyncSession):
    async def scalar(self, statement, *args, **kwargs):
        lock = getattr(statement, "_for_update_arg", None)
        if lock is not None and not self.info.get("probe_seen") and any(
            getattr(table, "name", "") == "studio_jobs" for table in statement.get_final_froms()
        ):
            self.info["probe_seen"] = True
            pid = int(await super().scalar(text("SELECT pg_backend_pid()")))
            self.info["probe_queue"].put_nowait(pid)
        return await super().scalar(statement, *args, **kwargs)


@pytest.mark.asyncio
async def test_api_cancels_exact_claim_without_payload_or_history_deletion(prestart_case):
    case = prestart_case
    claim = await _claimed(case)
    before = await _rows(case, StudioExecution)
    response = await _cancel(case, claim[0])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    receipt, = await _rows(case, StudioPrestartCancellation)
    job = await _row(case, claim[0])
    assert receipt["proof_sha256"] == evidence_digest(receipt["proof"])
    assert receipt["execution_id"] == before[0]["id"]
    assert job["attempts"] == 1 and job["lease_token"] is None
    assert job["cancelled_at"] == job["completed_at"] == receipt["created_at"]
    assert job["result_metadata"][GUARD_KEY]["phase"] == "claimed"
    assert await _rows(case, StudioExecution) == before
    assert not await _rows(case, StudioPublication) and not await _rows(case, StudioSettlement)
    assert not case.root.exists()
    assert await case.worker._begin_execution(*claim) is False
    await case.worker.execute(*claim)
    assert not case.root.exists()
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["prestart_cancelled_count"] == 1
    assert snap["invalid_prestart_cancellation_count"] == 0
    assert snap["blocker_count"] == len(snap["unregistered_unverified_job_ids"])
    assert snap["coverage_unverified"] and not snap["full_host_closure"]
    assert claim[1] not in json.dumps(snap) and str(case.root) not in json.dumps(snap)
    assert receipt["proof"]["payload_resources_started"] is False
    assert receipt["proof"]["filesystem_cleanup_claimed"] is False
    assert (await _cancel(case, claim[0])).status_code == 409
    assert (await case.client.post(f"/studio/jobs/{claim[0]}/retry")).status_code == 409
    assert await _rows(case, StudioExecution) == before
    assert len(await _rows(case, StudioPrestartCancellation)) == 1


@pytest.mark.asyncio
async def test_plain_queue_cancel_keeps_existing_behavior_without_receipt(prestart_case):
    case = prestart_case
    job_id = await _new(case)
    assert (await _cancel(case, job_id)).json()["status"] == "cancelled"
    assert not await _rows(case, StudioPrestartCancellation)
    assert (await case.client.post(f"/studio/jobs/{job_id}/retry")).status_code == 200
    assert await case.worker.claim_by_id(job_id) is not None
    assert not case.root.exists()


@pytest.mark.asyncio
async def test_prestart_cancel_remains_available_after_admission_closes(prestart_case):
    case = prestart_case
    claim = await _claimed(case)
    async with case.sessions() as session:
        authority = await admission.read_admission_snapshot(session, required_scope="studio_job_requests")
    await admission.close_admission(
        operation_id=str(uuid4()), expected_generation=authority.generation,
        reason="isolated pre-start cancellation", session_factory=case.sessions,
    )
    response = await _cancel(case, claim[0])
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    receipt, = await _rows(case, StudioPrestartCancellation)
    assert receipt["admitted_generation"] == authority.generation
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["admission_closed"] and snap["prestart_cancelled_count"] == 1
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "started", "unresolved", "resources", "missing_execution", "nonce", "worker", "generation",
    "job_guard", "job_result", "job_start", "job_provider", "future_claim",
    "publication", "success_receipt", "prestart_receipt",
])
async def test_unknown_started_or_conflicting_claim_is_only_cancellation_intent(prestart_case, change):
    case = prestart_case
    claim = await _claimed(case)
    async with case.sessions() as session:
        row = await session.scalar(select(StudioExecution).where(StudioExecution.job_id == claim[0]))
        job = await session.get(StudioJob, claim[0])
        assert row is not None and job is not None
        if change == "started":
            row.phase = "executing"
        elif change == "unresolved":
            row.state, row.unresolved_reason = "unresolved", "synthetic ambiguous claim"
        elif change == "resources":
            row.resources = {"malformed": {}}
        elif change == "missing_execution":
            await session.delete(row)
        elif change == "nonce":
            row.ownership_nonce = str(uuid4())
        elif change == "worker":
            row.worker_incarnation = str(uuid4())
        elif change == "generation":
            row.admitted_generation += 1
        elif change == "job_guard":
            job.result_metadata = {GUARD_KEY: {**job.result_metadata[GUARD_KEY], "phase": "executing"}}
        elif change == "job_result":
            job.result_metadata = {**job.result_metadata, "prior_output": "synthetic"}
        elif change == "job_start":
            job.started_at = None
        elif change == "job_provider":
            job.provider = "synthetic-provider"
        elif change == "future_claim":
            row.started_at = row.updated_at = datetime.now(UTC) + timedelta(days=1)
        elif change == "publication":
            session.add(StudioPublication(
                id=str(uuid4()), job_id=claim[0], execution_id=row.id,
                thread_resource_id=str(uuid4()), worker_incarnation=row.worker_incarnation,
                ownership_nonce=row.ownership_nonce, admitted_generation=row.admitted_generation,
                state="reserved", plan={}, events=[], created_at=row.started_at, updated_at=row.updated_at,
            ))
        else:
            model = StudioSettlement if change == "success_receipt" else StudioPrestartCancellation
            extra = {"publication_id": str(uuid4())} if model is StudioSettlement else {}
            session.add(model(
                id=str(uuid4()), job_id=claim[0], execution_id=row.id,
                worker_incarnation=row.worker_incarnation, admitted_generation=row.admitted_generation,
                proof={}, proof_sha256="0" * 64, created_at=row.started_at, **extra,
            ))
        await session.commit()
    history = {model: await _rows(case, model) for model in (StudioExecution, StudioPublication, StudioSettlement, StudioPrestartCancellation)}
    response = await _cancel(case, claim[0])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancel_requested"
    job = await _row(case, claim[0])
    assert job["completed_at"] is None and job["lease_token"] == claim[1]
    for model, before in history.items():
        assert await _rows(case, model) == before
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True])
async def test_caller_controls_atomic_receipt_job_and_audit_commit(prestart_case, commit):
    case = prestart_case
    claim = await _claimed(case)
    before = await _row(case, claim[0])
    writes = []
    def observe(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)
    event.listen(case.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with case.sessions() as session:
            job = await api._job_or_404(session, case.actor, claim[0], lock=True)
            session.add(AuditEvent(
                id=str(uuid4()), organization_id=case.actor.organization_id, user_id=case.actor.id,
                action="synthetic.pending", resource_type="test", resource_id=claim[0], details={},
            ))
            assert await cancellation.cancel_claimed_before_start(session, job)
            assert not writes and session.in_transaction()
            assert await _row(case, claim[0]) == before
            assert not await _rows(case, StudioPrestartCancellation)
            await (session.commit() if commit else session.rollback())
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", observe)
    assert bool(await _rows(case, StudioPrestartCancellation)) is commit
    assert (await _row(case, claim[0]))["status"] == ("cancelled" if commit else "running")
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True])
async def test_cancellation_lock_fences_actual_worker_start_until_commit_or_rollback(prestart_case, commit):
    case = prestart_case
    claim = await _claimed(case)
    ready, release = asyncio.Event(), asyncio.Event()
    started = asyncio.Queue()
    holder_pid = None
    async def holder():
        nonlocal holder_pid
        async with case.sessions() as session:
            holder_pid = int(await session.scalar(text("SELECT pg_backend_pid()")))
            job = await api._job_or_404(session, case.actor, claim[0], lock=True)
            assert await cancellation.cancel_claimed_before_start(session, job)
            ready.set()
            await release.wait()
            await (session.commit() if commit else session.rollback())
    case.worker._session_factory = async_sessionmaker(
        case.engine, class_=_JobLockProbe, expire_on_commit=False, info={"probe_queue": started},
    )
    hold = asyncio.create_task(holder())
    begin = None
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        begin = asyncio.create_task(case.worker._begin_execution(*claim))
        pid = await asyncio.wait_for(started.get(), WAIT)
        await _wait_for_block(case, pid, holder_pid)
        assert not begin.done()
    finally:
        release.set()
        results = await asyncio.wait_for(asyncio.gather(hold, *([begin] if begin else [])), WAIT)
    assert results[-1] is (not commit)
    assert bool(await _rows(case, StudioPrestartCancellation)) is commit
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True])
async def test_worker_start_lock_fences_api_cancel_in_opposite_direction(prestart_case, commit):
    case = prestart_case
    claim = await _claimed(case)
    ready, release = asyncio.Event(), asyncio.Event()
    started = asyncio.Queue()
    holder_pid = None
    class PausedStart(AsyncSession):
        async def commit(self):
            nonlocal holder_pid
            holder_pid = int(await super().scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            await release.wait()
            if commit:
                await super().commit()
            else:
                await self.rollback()
                raise RuntimeError("synthetic start rollback")
    case.worker._session_factory = async_sessionmaker(case.engine, class_=PausedStart, expire_on_commit=False)
    factory = async_sessionmaker(case.engine, class_=_JobLockProbe, expire_on_commit=False, info={"probe_queue": started})
    async def cancel():
        async with factory() as session:
            return await api.cancel_job(claim[0], case.actor, session)
    begin = asyncio.create_task(case.worker._begin_execution(*claim))
    control = None
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        control = asyncio.create_task(cancel())
        pid = await asyncio.wait_for(started.get(), WAIT)
        await _wait_for_block(case, pid, holder_pid)
        assert not control.done()
    finally:
        release.set()
        results = await asyncio.wait_for(asyncio.gather(begin, *([control] if control else []), return_exceptions=True), WAIT)
    assert (results[0] is True) if commit else isinstance(results[0], RuntimeError)
    assert not isinstance(results[-1], BaseException)
    assert results[-1]["status"] == ("cancel_requested" if commit else "cancelled")
    assert bool(await _rows(case, StudioPrestartCancellation)) is (not commit)
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("timing", ["before", "after"])
async def test_commit_ack_loss_never_replays_cancellation_or_starts_payload(prestart_case, timing):
    case = prestart_case
    claim = await _claimed(case)
    original = RuntimeError("synthetic cancellation commit acknowledgement loss")
    class UncertainCommit(AsyncSession):
        async def commit(self):
            assert any(isinstance(item, StudioPrestartCancellation) for item in self.new)
            if timing == "before":
                raise original
            await super().commit()
            raise original
    factory = async_sessionmaker(case.engine, class_=UncertainCommit, expire_on_commit=False)
    async def db():
        async with factory() as session:
            yield session
    case.app.dependency_overrides[get_db] = db
    with pytest.raises(RuntimeError) as caught:
        await _cancel(case, claim[0])
    assert caught.value is original
    assert bool(await _rows(case, StudioPrestartCancellation)) is (timing == "after")
    assert (await _row(case, claim[0]))["status"] == ("cancelled" if timing == "after" else "running")
    if timing == "after":
        assert await case.worker._begin_execution(*claim) is False
    assert not case.root.exists()


@pytest.mark.asyncio
async def test_task_cancellation_before_commit_keeps_original_claim(prestart_case, monkeypatch):
    case = prestart_case
    claim = await _claimed(case)
    ready, release = asyncio.Event(), asyncio.Event()
    original = api.cancel_claimed_before_start
    async def pause(session, job):
        result = await original(session, job)
        ready.set()
        await release.wait()
        return result
    monkeypatch.setattr(api, "cancel_claimed_before_start", pause)
    before = await _row(case, claim[0])
    task = asyncio.create_task(_cancel(case, claim[0]))
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        task.cancel("synthetic caller cancellation")
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert await _row(case, claim[0]) == before
    assert not await _rows(case, StudioPrestartCancellation)
    assert not case.root.exists()


@pytest.mark.asyncio
async def test_deleted_business_and_execution_do_not_erase_no_replay_receipt(prestart_case):
    case = prestart_case
    claim = await _claimed(case)
    assert (await _cancel(case, claim[0])).status_code == 200
    receipt, = await _rows(case, StudioPrestartCancellation)
    async with case.sessions() as session:
        await session.execute(delete(StudioJob).where(StudioJob.id == claim[0]))
        await session.commit()
    assert (await registry.execution_snapshot(session_factory=case.sessions))["prestart_cancelled_count"] == 1
    async with case.sessions() as session:
        await session.execute(delete(StudioExecution).where(StudioExecution.job_id == claim[0]))
        await session.commit()
    await _new(case, id=claim[0])
    assert await case.worker.claim_by_id(claim[0]) is None
    assert await _rows(case, StudioPrestartCancellation) == [receipt]
    async with case.sessions() as session:
        await session.execute(select(StudioJob.id).where(StudioJob.id == claim[0]).with_for_update())
        assert await has_retained_studio_evidence(session, claim[0])
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["invalid_prestart_cancellation_count"] == 1 and not snap["is_clear"]
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["proof_flag", "proof_hash", "execution_stamp", "job_status", "job_guard", "job_cancel_time", "orphan", "nonce"])
async def test_mutated_prestart_evidence_is_never_a_clear_snapshot(prestart_case, change):
    case = prestart_case
    claim = await _claimed(case)
    assert (await _cancel(case, claim[0])).status_code == 200
    async with case.sessions() as session:
        receipt = await session.scalar(select(StudioPrestartCancellation))
        row = await session.scalar(select(StudioExecution))
        job = await session.get(StudioJob, claim[0])
        if change == "proof_flag":
            receipt.proof = {**receipt.proof, "payload_resources_started": 0}
            flag_modified(receipt, "proof")
            receipt.proof_sha256 = evidence_digest(receipt.proof)
        elif change == "proof_hash":
            receipt.proof_sha256 = "0" * 64
        elif change == "execution_stamp":
            row.updated_at += timedelta(seconds=1)
        elif change == "job_status":
            job.status = "running"
        elif change == "job_guard":
            job.result_metadata = {}
        elif change == "job_cancel_time":
            job.cancelled_at += timedelta(seconds=1)
        elif change == "orphan":
            await session.delete(row)
        else:
            row.ownership_nonce = str(uuid4())
        await session.commit()
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["invalid_prestart_cancellation_count"] == 1
    assert snap["prestart_cancelled_count"] == 0 and not snap["is_clear"]
    assert not snap["full_host_closure"] and not case.root.exists()


def _migration(connection, direction="upgrade"):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260919_0058_studio_prestart_cancellation.py"
    spec = importlib.util.spec_from_file_location("prestart_migration_" + uuid4().hex, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


@pytest.mark.asyncio
async def test_migration_retains_exact_existing_receipts_and_refuses_destructive_downgrade(prestart_case):
    case = prestart_case
    claim = await _claimed(case)
    assert (await _cancel(case, claim[0])).status_code == 200
    before = await _rows(case, StudioPrestartCancellation)
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    assert await _rows(case, StudioPrestartCancellation) == before
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration, "downgrade")
    assert await _rows(case, StudioPrestartCancellation) == before


@pytest.mark.asyncio
async def test_missing_receipt_table_is_created_without_backfill(prestart_case):
    case = prestart_case
    claim = await _claimed(case)
    before = await _row(case, claim[0])
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda conn: StudioPrestartCancellation.__table__.drop(conn))
        await connection.run_sync(_migration)
    assert not await _rows(case, StudioPrestartCancellation)
    assert await _row(case, claim[0]) == before


@pytest.mark.asyncio
async def test_weakened_migration_schema_is_rejected_without_erasing_data(prestart_case):
    case = prestart_case
    async with case.engine.begin() as connection:
        await connection.execute(text("ALTER TABLE studio_prestart_cancellations DROP CONSTRAINT ck_studio_prestart_generation"))
    with pytest.raises(RuntimeError, match="frozen schema"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration)


@pytest.mark.asyncio
async def test_sixteen_concurrent_cancellations_create_one_receipt_and_no_payload(prestart_case):
    case = prestart_case
    claim = await _claimed(case)
    before = await _rows(case, StudioExecution)
    responses = await asyncio.wait_for(asyncio.gather(*(_cancel(case, claim[0]) for _ in range(16))), WAIT)
    assert sorted(response.status_code for response in responses) == [200] + [409] * 15
    assert len(await _rows(case, StudioPrestartCancellation)) == 1
    assert await _rows(case, StudioExecution) == before
    assert await case.worker._begin_execution(*claim) is False
    fresh = await _new(case)
    assert await case.worker.claim_by_id(fresh) is not None
    assert not case.root.exists()


@pytest.mark.asyncio
async def test_missing_receipt_table_fails_closed_before_cancellation_mutation(prestart_case):
    case = prestart_case
    claim = await _claimed(case)
    before = await _row(case, claim[0])
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda conn: StudioPrestartCancellation.__table__.drop(conn))
    response = await _cancel(case, claim[0])
    assert response.status_code == 503
    assert response.json() == {"detail": "Studio control evidence is currently unavailable."}
    assert await _row(case, claim[0]) == before
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [registry.StudioResourceUncertain, RuntimeError])
async def test_prestart_failure_does_not_modify_the_job_or_manufacture_receipt(prestart_case, monkeypatch, error_type):
    case = prestart_case
    claim = await _claimed(case)
    before = await _row(case, claim[0])
    original = error_type("synthetic private failure detail")
    async def fail(*args):
        raise original
    monkeypatch.setattr(api, "cancel_claimed_before_start", fail)
    if error_type is registry.StudioResourceUncertain:
        response = await _cancel(case, claim[0])
        assert response.status_code == 503
        assert response.json() == {"detail": "Studio cancellation evidence is currently unavailable."}
    else:
        with pytest.raises(RuntimeError) as caught:
            await _cancel(case, claim[0])
        assert caught.value is original
    assert await _row(case, claim[0]) == before
    assert not await _rows(case, StudioPrestartCancellation)
    assert not case.root.exists()
