"""Normal-success settlement on disposable PostgreSQL, real workers and archives."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    StudioAsset, StudioAssetRevision, StudioExecution, StudioJob,
    StudioPublication, StudioSettlement,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_resource_registry as registry
from app.services import studio_success_settlement as settlement
from app.services.studio_result_binding import BINDING_KEY, evidence_digest

_spec = importlib.util.spec_from_file_location(
    "fr06d8b5b_binding_fixture", Path(__file__).with_name("test_fr06c5d8b5_studio_result_binding.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case
publication_case = _shared.publication_case
_new, _row, _ledger = _shared._new, _shared._row, _shared._ledger
WAIT = 10


async def _receipts(case):
    async with case.sessions() as session:
        return list((await session.scalars(select(StudioSettlement).order_by(StudioSettlement.id))).all())


async def _pending(case, monkeypatch, **changes):
    """Run the real worker through acknowledged business commit, delaying settlement."""
    captured = []
    async def capture(*, session_factory, acknowledgement):
        captured.append(acknowledgement)
    job_id = await _new(case, **changes)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None
    with monkeypatch.context() as patch:
        patch.setattr(settlement, "settle_success", capture)
        await case.worker.execute(*claim)
    assert len(captured) == 1 and captured[0].job_id == job_id
    assert (await _row(case, job_id))["status"] == "completed"
    return claim, captured[0]


async def _returned(case, acknowledgement):
    await registry.observe_execution_end(
        session_factory=case.sessions, job_id=acknowledgement.job_id,
        nonce=acknowledgement.nonce, worker_incarnation=acknowledgement.worker_incarnation,
        interrupted=False,
    )
    return dict(
        job_id=acknowledgement.job_id, nonce=acknowledgement.nonce,
        worker_incarnation=acknowledgement.worker_incarnation,
        result_binding=json.loads(acknowledgement.binding_json),
    )


def _migration(connection, direction="upgrade"):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260919_0057_studio_success_settlement.py"
    spec = importlib.util.spec_from_file_location("studio_settlement_migration_" + uuid4().hex, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


@pytest.mark.asyncio
async def test_real_success_receipt_retains_archive_and_all_raw_evidence(publication_case):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    await case.worker.execute(*claim)
    receipt, = await _receipts(case)
    assert receipt.job_id == job_id and receipt.proof["schema"] == settlement.SCHEMA
    assert receipt.proof_sha256 == evidence_digest(receipt.proof)
    job = await _row(case, job_id)
    assert receipt.proof["binding"] == job["result_metadata"][BINDING_KEY]
    ledger = await _ledger(case, job_id)
    assert ledger["state"] == "unresolved" and ledger["phase"] == "returned"
    assert ledger["cleanup_verified"] is False and len(ledger["resources"]) == 2
    archive, = case.root.rglob("*.zip")
    assert archive.stat().st_nlink == 1 and archive.stat().st_size > 0
    assert not list(case.root.rglob("*.partial"))
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["settled_execution_count"] == snap["retained_archive_count"] == 1
    assert snap["blocker_count"] == len(snap["unregistered_unverified_job_ids"])
    assert not snap["full_host_closure"] and snap["coverage_unverified"]
    assert claim[1] not in json.dumps(snap) and str(case.root) not in json.dumps(snap)
    # The synthetic original fixture is unrelated legacy work, not a drain proof.
    async with case.sessions() as session:
        await session.execute(delete(StudioJob).where(StudioJob.id == case.original_id))
        await session.commit()
    assert (await registry.execution_snapshot(session_factory=case.sessions))["is_clear"]
    await case.worker.execute(*claim)
    assert len(await _receipts(case)) == 1 and len(list(case.root.rglob("*.zip"))) == 1


@pytest.mark.asyncio
async def test_receipt_survives_business_deletion_without_releasing_replay(publication_case):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    await case.worker.execute(*claim)
    receipt, = await _receipts(case)
    before = deepcopy(receipt.proof)
    async with case.sessions() as session:
        await session.execute(delete(StudioJob).where(StudioJob.id == job_id))
        await session.commit()
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["settled_execution_count"] == 1
    assert (await _receipts(case))[0].proof == before
    assert len(list(case.root.rglob("*.zip"))) == 1
    # Even deletion of both independent resource ledgers cannot make this ID new.
    async with case.sessions() as session:
        await session.execute(delete(StudioExecution).where(StudioExecution.job_id == job_id))
        await session.execute(delete(StudioPublication).where(StudioPublication.job_id == job_id))
        await session.commit()
    await _new(case, id=job_id)
    assert await case.worker.claim_by_id(job_id) is None
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["invalid_settlement_count"] == 1 and not snap["is_clear"]


@pytest.mark.asyncio
async def test_capability_is_single_use_and_bound_to_the_acknowledging_task(publication_case, monkeypatch):
    case = publication_case
    _, ack = await _pending(case, monkeypatch)
    with pytest.raises(registry.StudioResourceUncertain):
        await asyncio.create_task(settlement.settle_success(session_factory=case.sessions, acknowledgement=ack))
    assert not ack.consumed
    with pytest.raises(registry.StudioResourceUncertain):
        await settlement.settle_success(session_factory=case.sessions, acknowledgement=replace(ack, issuer=object()))
    await settlement.settle_success(session_factory=case.sessions, acknowledgement=ack)
    with pytest.raises(registry.StudioResourceUncertain):
        await settlement.settle_success(session_factory=case.sessions, acknowledgement=ack)
    assert len(await _receipts(case)) == 1


@pytest.mark.asyncio
async def test_pending_success_can_settle_after_maintenance_generation_changes(publication_case, monkeypatch):
    case = publication_case
    _, ack = await _pending(case, monkeypatch)
    async with case.sessions() as session:
        before = await admission.read_admission_snapshot(session, required_scope="studio_job_requests")
    await admission.close_admission(
        operation_id=str(uuid4()), expected_generation=before.generation,
        reason="synthetic drain of an already completed attempt", session_factory=case.sessions,
    )
    await settlement.settle_success(session_factory=case.sessions, acknowledgement=ack)
    receipt, = await _receipts(case)
    assert receipt.admitted_generation == before.generation
    assert (await registry.execution_snapshot(session_factory=case.sessions))["admission_closed"]


@pytest.mark.asyncio
async def test_newer_asset_head_does_not_replace_old_revision_evidence(publication_case, monkeypatch):
    case = publication_case
    _, old_ack = await _pending(case, monkeypatch)
    old = json.loads(old_ack.binding_json)
    second = await _new(case, revision_of_asset_id=old["asset_id"], title="Synthetic next revision")
    await case.worker.execute(*(await case.worker.claim_by_id(second)))
    await settlement.settle_success(session_factory=case.sessions, acknowledgement=old_ack)
    receipts = await _receipts(case)
    assert {r.proof["binding"]["revision_number"] for r in receipts} == {1, 2}
    assert (await registry.execution_snapshot(session_factory=case.sessions))["retained_archive_count"] == 2
    assert len(list(case.root.rglob("*.zip"))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "owner_nonce", "worker", "generation", "missing_execution", "missing_publication",
    "publication_nonce", "publication_thread", "publication_generation", "publication_checksum",
    "publication_identity", "publication_incomplete", "reserved_thread", "failed_thread",
    "cancel_requested", "job_binding", "revision_binding", "revision_checksum", "revision_path",
    "missing_revision", "missing_job", "current_asset_binding", "completed_time",
])
async def test_mutated_or_unresolved_evidence_never_settles(publication_case, monkeypatch, change):
    case = publication_case
    claim, ack = await _pending(case, monkeypatch)
    proof = json.loads(ack.binding_json)
    async with case.sessions() as session:
        job = await session.get(StudioJob, claim[0])
        execution = await session.get(StudioExecution, proof["execution_id"])
        publication = await session.get(StudioPublication, proof["publication_id"])
        revision = await session.get(StudioAssetRevision, proof["revision_id"])
        asset = await session.get(StudioAsset, proof["asset_id"])
        if change == "owner_nonce":
            execution.ownership_nonce = str(uuid4())
        elif change == "worker":
            execution.worker_incarnation = str(uuid4())
        elif change == "generation":
            execution.admitted_generation += 1
        elif change.startswith("missing_"):
            await session.delete({"execution": execution, "publication": publication, "revision": revision, "job": job}[change[8:]])
        elif change == "publication_nonce":
            publication.ownership_nonce = str(uuid4())
        elif change == "publication_thread":
            publication.thread_resource_id = str(uuid4())
        elif change == "publication_generation":
            publication.admitted_generation += 1
        elif change == "publication_checksum":
            publication.plan = {**publication.plan, "checksum": "0" * 64}
        elif change == "publication_identity":
            events = deepcopy(publication.events)
            events[-1]["payload"]["file"]["inode"] += 1
            publication.events = events
        elif change == "publication_incomplete":
            publication.events = publication.events[:-1]
            publication.updated_at = registry._stamp(publication.events[-1]["at"])
            publication.state = "reserved"
        elif change in {"reserved_thread", "failed_thread"}:
            resources = deepcopy(execution.resources)
            store = next(r for r in resources.values() if r["operation"] == "store_artifact")
            if change == "reserved_thread":
                store.update(state="reserved", joined_at=None, outcome=None)
            else:
                store["outcome"] = "failed"
            execution.resources = resources
        elif change == "cancel_requested":
            job.status = "cancel_requested"
        elif change == "job_binding":
            job.result_metadata = {**job.result_metadata, BINDING_KEY: {**proof, "revision_number": True}}
            # JSON equality treats True == 1. Force the intended negative fixture
            # write, then verify the changed type from a separate DB session.
            flag_modified(job, "result_metadata")
        elif change == "revision_binding":
            revision.revision_metadata = {**revision.revision_metadata, BINDING_KEY: {**proof, "publication_id": str(uuid4())}}
        elif change == "revision_checksum":
            revision.checksum = "0" * 64
        elif change == "revision_path":
            revision.storage_path += ".foreign"
        elif change == "current_asset_binding":
            asset.asset_metadata = {}
        else:
            job.completed_at += timedelta(days=1)
        await session.commit()
    if change == "job_binding":
        persisted = await _row(case, claim[0])
        assert type(persisted["result_metadata"][BINDING_KEY]["revision_number"]) is bool, "test mutation must reach PostgreSQL"
    with pytest.raises((registry.StudioOwnershipLost, registry.StudioResourceUncertain)):
        await settlement.settle_success(session_factory=case.sessions, acknowledgement=ack)
    assert not await _receipts(case)
    assert len(list(case.root.rglob("*.zip"))) == 1
    assert await case.worker.claim_by_id(claim[0]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["business", "return", "settlement"])
@pytest.mark.parametrize("timing", ["before", "after"])
async def test_commit_acknowledgement_losses_never_replay_or_delete(publication_case, monkeypatch, stage, timing):
    case = publication_case
    error = RuntimeError("synthetic acknowledgement loss")
    if stage == "business":
        class BusinessFailure(AsyncSession):
            async def commit(self):
                target = any(isinstance(item, StudioJob) and item.status == "completed" and BINDING_KEY in (item.result_metadata or {}) for item in self.identity_map.values())
                if target and timing == "before":
                    raise error
                await super().commit()
                if target:
                    raise error
        case.worker._session_factory = async_sessionmaker(case.engine, class_=BusinessFailure, expire_on_commit=False)
        job_id = await _new(case)
        claim = await case.worker.claim_by_id(job_id)
        with pytest.raises(RuntimeError) as caught:
            await case.worker.execute(*claim)
    else:
        claim, ack = await _pending(case, monkeypatch)
        if stage == "return":
            original = registry.observe_execution_end
            async def failed_return(**kwargs):
                if timing == "after":
                    await original(**kwargs)
                raise error
            monkeypatch.setattr(registry, "observe_execution_end", failed_return)
            factory = case.sessions
        else:
            class ReceiptFailure(AsyncSession):
                async def commit(self):
                    target = any(isinstance(item, StudioSettlement) for item in self.new)
                    if target and timing == "before":
                        raise error
                    await super().commit()
                    if target:
                        raise error
            factory = async_sessionmaker(case.engine, class_=ReceiptFailure, expire_on_commit=False)
        with pytest.raises(RuntimeError) as caught:
            await settlement.settle_success(session_factory=factory, acknowledgement=ack)
        assert ack.consumed
        with pytest.raises(registry.StudioResourceUncertain):
            await settlement.settle_success(session_factory=case.sessions, acknowledgement=ack)
    assert caught.value is error
    durable_receipt = stage == "settlement" and timing == "after"
    assert bool(await _receipts(case)) is durable_receipt
    assert len(list(case.root.rglob("*.zip"))) == 1
    assert await case.worker.claim_by_id(claim[0]) is None
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert (snap["settled_execution_count"] == 1) is durable_receipt


@pytest.mark.asyncio
async def test_cancellation_during_settlement_keeps_output_and_original_cancellation(publication_case, monkeypatch):
    case = publication_case
    ready, release = asyncio.Event(), asyncio.Event()
    original = settlement._record_success
    async def pause(session, **kwargs):
        row = await original(session, **kwargs)
        ready.set()
        await release.wait()
        return row
    monkeypatch.setattr(settlement, "_record_success", pause)
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        task.cancel("synthetic settlement cancellation")
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert not await _receipts(case) and len(list(case.root.rglob("*.zip"))) == 1
    assert not (await registry.execution_snapshot(session_factory=case.sessions))["is_clear"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [StudioJob, StudioExecution, StudioPublication, StudioAsset, StudioAssetRevision])
@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_all_evidence_locks_survive_until_receipt_transaction_ends(publication_case, monkeypatch, model, finish):
    case = publication_case
    _, ack = await _pending(case, monkeypatch)
    args = await _returned(case, ack)
    proof = json.loads(ack.binding_json)
    identifier = proof[{StudioJob: "job_id", StudioExecution: "execution_id", StudioPublication: "publication_id", StudioAsset: "asset_id", StudioAssetRevision: "revision_id"}[model]]
    ready, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    waiting = asyncio.Queue()
    holder_pid = None
    async def holder():
        nonlocal holder_pid
        async with case.sessions() as session:
            holder_pid = int(await session.scalar(text("SELECT pg_backend_pid()")))
            await settlement._record_success(session, **args)
            ready.set()
            await release.wait()
            if finish == "commit":
                await session.commit()
            else:
                await session.rollback()
    async def contender():
        async with case.sessions() as session:
            pid = int(await session.scalar(text("SELECT pg_backend_pid()")))
            waiting.put_nowait(pid)
            assert await session.scalar(select(model.id).where(model.id == identifier).with_for_update()) == identifier
            finished.set()
    hold = asyncio.create_task(holder())
    wait = None
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        wait = asyncio.create_task(contender())
        pid = await asyncio.wait_for(waiting.get(), WAIT)
        async with asyncio.timeout(WAIT):
            while True:
                async with case.sessions() as probe:
                    blockers = await probe.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
                if holder_pid in blockers:
                    break
                await asyncio.sleep(0.01)
        assert not finished.is_set()
        assert not await _receipts(case)
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(hold, *([wait] if wait else [])), WAIT)
    assert finished.is_set()
    assert bool(await _receipts(case)) is (finish == "commit")


@pytest.mark.asyncio
async def test_no_autoflush_or_business_mutation_before_receipt_acceptance(publication_case, monkeypatch):
    case = publication_case
    _, ack = await _pending(case, monkeypatch)
    args = await _returned(case, ack)
    statements = []
    def observe(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(sql)
    event.listen(case.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with case.sessions() as session:
            await settlement._record_success(session, **args)
            assert session.in_transaction() and not statements
            await session.rollback()
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", observe)
    assert not await _receipts(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["proof", "execution", "publication", "orphan_execution", "orphan_publication", "reset_job"])
async def test_mutated_or_orphan_terminal_evidence_remains_a_snapshot_blocker(publication_case, change):
    case = publication_case
    job_id = await _new(case)
    await case.worker.execute(*(await case.worker.claim_by_id(job_id)))
    receipt, = await _receipts(case)
    async with case.sessions() as session:
        item = await session.get(StudioSettlement, receipt.id)
        execution = await session.get(StudioExecution, receipt.execution_id)
        publication = await session.get(StudioPublication, receipt.publication_id)
        if change == "proof":
            item.proof = {**item.proof, "full_host_closure": True}
        elif change == "execution":
            execution.updated_at += timedelta(seconds=1)
        elif change == "publication":
            publication.plan = {**publication.plan, "checksum": "0" * 64}
        elif change.startswith("orphan_"):
            await session.delete(execution if change == "orphan_execution" else publication)
        else:
            job = await session.get(StudioJob, job_id)
            job.status = "queued"
            job.result_metadata = {}
        await session.commit()
    snap = await registry.execution_snapshot(session_factory=case.sessions)
    assert snap["invalid_settlement_count"] == 1 and not snap["is_clear"]
    assert snap["settled_execution_count"] == 0 and not snap["full_host_closure"]
    assert len(list(case.root.rglob("*.zip"))) == 1


@pytest.mark.asyncio
async def test_migration_accepts_exact_bootstrap_preserves_rows_and_rejects_downgrade(publication_case):
    case = publication_case
    job_id = await _new(case)
    await case.worker.execute(*(await case.worker.claim_by_id(job_id)))
    before = deepcopy((await _receipts(case))[0].proof)
    async with case.engine.begin() as connection:
        await connection.run_sync(_migration)
    assert (await _receipts(case))[0].proof == before
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration, "downgrade")
    assert (await _receipts(case))[0].proof == before


@pytest.mark.asyncio
async def test_migration_rejects_unknown_existing_column(publication_case):
    case = publication_case
    async with case.engine.begin() as connection:
        await connection.execute(text("ALTER TABLE studio_settlements ADD COLUMN unexpected integer"))
    with pytest.raises(RuntimeError, match="frozen schema"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration)


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_later_end_observation_cannot_mutate_a_settled_execution(publication_case, interrupted):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    await case.worker.execute(*claim)
    before = deepcopy(await _ledger(case, job_id))
    receipt, = await _receipts(case)
    proof = deepcopy(receipt.proof)
    with pytest.raises(registry.StudioOwnershipLost, match="immutable"):
        await registry.observe_execution_end(
            session_factory=case.sessions, job_id=job_id, nonce=claim[1],
            worker_incarnation=case.worker.incarnation, interrupted=interrupted,
        )
    assert await _ledger(case, job_id) == before
    assert (await _receipts(case))[0].proof == proof
    assert (await registry.execution_snapshot(session_factory=case.sessions))["settled_execution_count"] == 1
    assert len(list(case.root.rglob("*.zip"))) == 1


@pytest.mark.asyncio
async def test_copied_consumed_capability_cannot_invalidate_a_durable_receipt(publication_case, monkeypatch):
    case = publication_case
    _, ack = await _pending(case, monkeypatch)
    await settlement.settle_success(session_factory=case.sessions, acknowledgement=ack)
    before = deepcopy(await _ledger(case, ack.job_id))
    # This is a trusted-process misuse control, not a claimed Python sandbox.
    duplicate = replace(ack, consumed=False)
    with pytest.raises(registry.StudioOwnershipLost, match="immutable"):
        await settlement.settle_success(session_factory=case.sessions, acknowledgement=duplicate)
    assert await _ledger(case, ack.job_id) == before
    assert len(await _receipts(case)) == 1
    assert (await registry.execution_snapshot(session_factory=case.sessions))["settled_execution_count"] == 1


@pytest.mark.asyncio
async def test_competing_receipt_transactions_create_one_terminal_receipt(publication_case, monkeypatch):
    case = publication_case
    _, ack = await _pending(case, monkeypatch)
    args = await _returned(case, ack)
    before = deepcopy(await _ledger(case, ack.job_id))
    async def contender():
        try:
            async with case.sessions() as session:
                await settlement._record_success(session, **args)
                await session.commit()
            return "committed"
        except registry.StudioOwnershipLost:
            return "already_recorded"
    outcomes = await asyncio.wait_for(asyncio.gather(contender(), contender()), WAIT)
    assert sorted(outcomes) == ["already_recorded", "committed"]
    assert len(await _receipts(case)) == 1
    assert await _ledger(case, ack.job_id) == before
    assert len(list(case.root.rglob("*.zip"))) == 1


@pytest.mark.asyncio
async def test_migration_creates_missing_ledger_without_backfilling_existing_success(publication_case, monkeypatch):
    case = publication_case
    _, ack = await _pending(case, monkeypatch)
    before = deepcopy(await _ledger(case, ack.job_id))
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda conn: StudioSettlement.__table__.drop(conn))
        await connection.run_sync(_migration)
    assert not await _receipts(case)
    assert await _ledger(case, ack.job_id) == before
    assert (await registry.execution_snapshot(session_factory=case.sessions))["settled_execution_count"] == 0
    await settlement.settle_success(session_factory=case.sessions, acknowledgement=ack)
    assert len(await _receipts(case)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("alteration", ["generation_check", "job_unique", "proof_type"])
async def test_migration_rejects_weakened_existing_ledger(publication_case, alteration):
    case = publication_case
    async with case.engine.begin() as connection:
        if alteration == "generation_check":
            await connection.execute(text("ALTER TABLE studio_settlements DROP CONSTRAINT ck_studio_settlement_generation"))
        elif alteration == "proof_type":
            await connection.execute(text("ALTER TABLE studio_settlements ALTER COLUMN proof TYPE text USING proof::text"))
        else:
            def drop_unique(conn):
                import sqlalchemy as sa
                names = [item["name"] for item in sa.inspect(conn).get_unique_constraints("studio_settlements") if item["column_names"] == ["job_id"]]
                assert len(names) == 1
                constraint = sa.UniqueConstraint(StudioSettlement.__table__.c.job_id, name=names[0])
                try:
                    conn.execute(sa.schema.DropConstraint(constraint))
                finally:
                    # The inspection helper must not alter shared ORM metadata.
                    StudioSettlement.__table__.constraints.discard(constraint)
            await connection.run_sync(drop_unique)
    with pytest.raises(RuntimeError, match="frozen schema"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration)
