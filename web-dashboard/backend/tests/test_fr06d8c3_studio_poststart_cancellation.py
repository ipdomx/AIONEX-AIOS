"""Post-start Studio cancellation settlement on disposable PostgreSQL and files."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.util
from pathlib import Path
import sys
import threading
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, select, text

from app.db.models import (
    StudioJob,
    StudioPoststartCancellation,
    StudioPublication,
)
from app.services import studio_poststart_cancellation as cancellation
from app.services import studio_resource_registry as registry
from app.services import studio_worker as workers

_spec = importlib.util.spec_from_file_location(
    "fr06d8c3_success_fixture",
    Path(__file__).with_name("test_fr06d8b5b_studio_success_settlement.py"),
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
        return list(
            (
                await session.scalars(
                    select(StudioPoststartCancellation)
                    .order_by(StudioPoststartCancellation.id)
                )
            ).all()
        )


async def _cancel(case, job_id):
    response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    return response.json()


async def _wait_thread(event: threading.Event) -> None:
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, WAIT), WAIT + 1)


def _migration(connection, direction="upgrade"):
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260919_0059_studio_poststart_cancellation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "studio_poststart_migration_" + uuid4().hex,
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


@pytest.mark.asyncio
async def test_cancel_after_start_before_first_resource_has_retained_receipt(
    publication_case,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None and await case.worker._begin_execution(*claim)

    requested = await _cancel(case, job_id)
    assert requested["status"] == "cancel_requested"

    await registry.observe_execution_end(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
        interrupted=True,
    )
    await case.worker._mark_unresolved(
        job_id, claim[1], "StudioResourceCancelled"
    )
    assert await cancellation.settle_poststart_cancellation(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )

    receipt, = await _receipts(case)
    assert receipt.publication_id is None
    assert receipt.proof["mode"] == "started_no_payload_resource"
    assert receipt.proof["payload_resources_stopped"] is True
    assert receipt.proof["accepted_archive_retained"] is False
    job = await _row(case, job_id)
    assert job["status"] == "cancelled" and job["lease_token"] is None
    assert job["completed_at"] == receipt.created_at
    assert not list(case.root.rglob("*.zip"))


@pytest.mark.asyncio
async def test_api_cancel_during_build_joins_thread_and_does_not_stop_worker(
    publication_case, monkeypatch,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None

    entered, release = threading.Event(), threading.Event()
    original = workers.build_archive

    def blocking(*args, **kwargs):
        entered.set()
        assert release.wait(WAIT)
        return original(*args, **kwargs)

    monkeypatch.setattr(workers, "build_archive", blocking)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await _wait_thread(entered)
        assert (await _cancel(case, job_id))["status"] == "cancel_requested"
        release.set()
        await asyncio.wait_for(task, WAIT)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    receipt, = await _receipts(case)
    assert receipt.proof["mode"] == "joined_build_before_storage"
    assert receipt.publication_id is None
    job = await _row(case, job_id)
    assert job["status"] == "cancelled" and job["lease_token"] is None
    ledger = await _ledger(case, job_id)
    resource, = ledger["resources"].values()
    assert resource["operation"] == "build_archive"
    assert resource["state"] == "joined" and resource["outcome"] == "success"
    assert not list(case.root.rglob("*.zip"))


@pytest.mark.asyncio
async def test_internal_cancel_does_not_stop_worker_cycle(publication_case, monkeypatch):
    case = publication_case
    job_id = await _new(case)
    entered, release = threading.Event(), threading.Event()
    original = workers.build_archive

    def blocking(*args, **kwargs):
        entered.set()
        assert release.wait(WAIT)
        return original(*args, **kwargs)

    monkeypatch.setattr(workers, "build_archive", blocking)
    task = asyncio.create_task(case.worker.run_once())
    try:
        await _wait_thread(entered)
        assert (await _cancel(case, job_id))["status"] == "cancel_requested"
        release.set()
        assert await asyncio.wait_for(task, WAIT) is True
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert case.worker.cycles == 1
    assert (await _row(case, job_id))["status"] == "cancelled"
    assert len(await _receipts(case)) == 1


@pytest.mark.asyncio
async def test_api_cancel_during_store_retains_complete_archive_and_receipt(
    publication_case, monkeypatch,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None

    entered, release = threading.Event(), threading.Event()
    original = workers.store_artifact
    paths = []

    def blocking(*args, **kwargs):
        path = original(*args, **kwargs)
        paths.append(path)
        entered.set()
        assert release.wait(WAIT)
        return path

    monkeypatch.setattr(workers, "store_artifact", blocking)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await _wait_thread(entered)
        assert len(paths) == 1 and paths[0].exists()
        assert (await _cancel(case, job_id))["status"] == "cancel_requested"
        release.set()
        await asyncio.wait_for(task, WAIT)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    receipt, = await _receipts(case)
    assert receipt.publication_id is not None
    assert receipt.proof["mode"] == "complete_publication_retained"
    assert receipt.proof["staging_cleanup_verified"] is True
    assert receipt.proof["accepted_archive_retained"] is True
    assert paths[0].exists() and not list(case.root.rglob("*.partial"))
    job = await _row(case, job_id)
    assert job["status"] == "cancelled" and job["lease_token"] is None

    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["poststart_cancelled_count"] == 1
    assert snapshot["invalid_poststart_cancellation_count"] == 0
    assert any(
        item["cancelled_archive_retained"]
        for item in snapshot["publications"]
        if item["job_id"] == job_id
    )


@pytest.mark.asyncio
async def test_external_task_cancellation_without_api_intent_never_settles(
    publication_case, monkeypatch,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    entered, release = threading.Event(), threading.Event()
    original = workers.build_archive

    def blocking(*args, **kwargs):
        entered.set()
        assert release.wait(WAIT)
        return original(*args, **kwargs)

    monkeypatch.setattr(workers, "build_archive", blocking)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await _wait_thread(entered)
        task.cancel("synthetic caller shutdown")
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, WAIT)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert not await _receipts(case)
    row = await _row(case, job_id)
    assert row["status"] == "running"
    assert row["error_code"] == "STUDIO_RECONCILIATION_REQUIRED"
    assert (await _ledger(case, job_id))["state"] == "unresolved"


@pytest.mark.asyncio
async def test_failed_or_unverified_resource_cannot_be_cancel_settled(
    publication_case,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert await case.worker._begin_execution(*claim)
    owner, resource_id = await registry.reserve_thread(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
        operation="build_archive",
    )
    await registry.observe_thread(
        session_factory=case.sessions,
        owner=owner,
        resource_id=resource_id,
        joined=True,
        succeeded=False,
    )
    assert (await _cancel(case, job_id))["status"] == "cancel_requested"
    await registry.observe_execution_end(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
        interrupted=True,
    )
    await case.worker._mark_unresolved(job_id, claim[1], "synthetic failure")

    assert not await cancellation.settle_poststart_cancellation(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert not await _receipts(case)
    assert (await _row(case, job_id))["status"] == "cancel_requested"


@pytest.mark.asyncio
async def test_receipt_survives_business_deletion_and_blocks_replay(
    publication_case, monkeypatch,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert await case.worker._begin_execution(*claim)
    assert (await _cancel(case, job_id))["status"] == "cancel_requested"
    await registry.observe_execution_end(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
        interrupted=True,
    )
    await case.worker._mark_unresolved(job_id, claim[1], "StudioResourceCancelled")
    assert await cancellation.settle_poststart_cancellation(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    receipt, = await _receipts(case)
    proof = deepcopy(receipt.proof)

    async with case.sessions() as session:
        await session.execute(delete(StudioJob).where(StudioJob.id == job_id))
        await session.commit()
    assert (await _receipts(case))[0].proof == proof

    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["poststart_cancelled_count"] == 1

    # Reintroducing mutable business state with the same identity cannot make
    # the historical attempt replayable; it deliberately invalidates the
    # terminal classification until reviewed.
    await _new(case, id=job_id)
    assert await case.worker.claim_by_id(job_id) is None
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["poststart_cancelled_count"] == 0
    assert snapshot["invalid_poststart_cancellation_count"] == 1
    assert not snapshot["is_clear"]


@pytest.mark.asyncio
async def test_later_execution_observation_cannot_mutate_poststart_receipt(
    publication_case,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert await case.worker._begin_execution(*claim)
    await _cancel(case, job_id)
    await registry.observe_execution_end(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
        interrupted=True,
    )
    await case.worker._mark_unresolved(job_id, claim[1], "StudioResourceCancelled")
    assert await cancellation.settle_poststart_cancellation(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    before = deepcopy(await _ledger(case, job_id))
    with pytest.raises(registry.StudioOwnershipLost, match="immutable"):
        await registry.observe_execution_end(
            session_factory=case.sessions,
            job_id=job_id,
            nonce=claim[1],
            worker_incarnation=case.worker.incarnation,
            interrupted=True,
        )
    assert await _ledger(case, job_id) == before


@pytest.mark.asyncio
async def test_late_publication_conflicts_with_no_publication_receipt(publication_case):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert await case.worker._begin_execution(*claim)
    await _cancel(case, job_id)
    await registry.observe_execution_end(
        session_factory=case.sessions, job_id=job_id, nonce=claim[1],
        worker_incarnation=case.worker.incarnation, interrupted=True,
    )
    await case.worker._mark_unresolved(job_id, claim[1], "StudioResourceCancelled")
    assert await cancellation.settle_poststart_cancellation(
        session_factory=case.sessions, job_id=job_id, nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    receipt, = await _receipts(case)
    assert receipt.publication_id is None
    ledger = await _ledger(case, job_id)
    root = Path(case.root).absolute()
    content = b"x"
    stamp = receipt.created_at + timedelta(microseconds=1)
    publication = StudioPublication(
        id=str(uuid4()), execution_id=ledger["id"], job_id=job_id,
        thread_resource_id=str(uuid4()), worker_incarnation=case.worker.incarnation,
        admitted_generation=ledger["admitted_generation"], ownership_nonce=claim[1],
        state="reserved",
        plan={
            "root": str(root),
            "components": [*root.parts[1:], case.actor.organization_id, str(uuid4()), "revision-1"],
            "filename": "late.zip",
            "staging_name": f".studio-publish-{uuid4().hex}.partial",
            "size_bytes": len(content),
            "checksum": hashlib.sha256(content).hexdigest(),
        },
        events=[], created_at=stamp, updated_at=stamp,
    )
    async with case.sessions() as session:
        session.add(publication)
        await session.commit()
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["poststart_cancelled_count"] == 0
    assert snapshot["invalid_poststart_cancellation_count"] == 1
    assert not snapshot["is_clear"]


@pytest.mark.asyncio
async def test_mutated_receipt_or_execution_remains_snapshot_blocker(
    publication_case,
):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert await case.worker._begin_execution(*claim)
    await _cancel(case, job_id)
    await registry.observe_execution_end(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
        interrupted=True,
    )
    await case.worker._mark_unresolved(job_id, claim[1], "StudioResourceCancelled")
    assert await cancellation.settle_poststart_cancellation(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    receipt, = await _receipts(case)
    async with case.sessions() as session:
        item = await session.get(StudioPoststartCancellation, receipt.id)
        item.proof = {**item.proof, "full_host_closure": True}
        await session.commit()
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["poststart_cancelled_count"] == 0
    assert snapshot["invalid_poststart_cancellation_count"] == 1
    assert not snapshot["is_clear"]


@pytest.mark.asyncio
async def test_missing_poststart_ledger_fails_control_closed(publication_case):
    case = publication_case
    job_id = await _new(case)
    before = await _row(case, job_id)
    async with case.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: StudioPoststartCancellation.__table__.drop(conn)
        )
    response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Studio control evidence is currently unavailable."
    }
    assert await _row(case, job_id) == before


@pytest.mark.asyncio
async def test_migration_creates_no_backfill_and_rejects_downgrade(
    publication_case,
):
    case = publication_case
    async with case.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: StudioPoststartCancellation.__table__.drop(
                conn, checkfirst=True
            )
        )
        await connection.run_sync(_migration)
    assert not await _receipts(case)

    with pytest.raises(RuntimeError, match="cannot be discarded"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration, "downgrade")


@pytest.mark.asyncio
async def test_migration_rejects_weakened_existing_ledger(publication_case):
    case = publication_case
    async with case.engine.begin() as connection:
        await connection.execute(text(
            "ALTER TABLE studio_poststart_cancellations "
            "DROP CONSTRAINT ck_studio_poststart_cancel_generation"
        ))
    with pytest.raises(RuntimeError, match="frozen schema"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration)
