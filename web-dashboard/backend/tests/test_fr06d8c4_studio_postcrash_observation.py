"""Post-crash Studio observation is durable evidence, never cleanup authority."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import stat
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.models import (
    OwnerControlRecord,
    StudioCrashObservation,
    StudioExecution,
    StudioJob,
    StudioPublication,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_crash_observation as crash
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry

_spec = importlib.util.spec_from_file_location(
    "fr06d8c4_publication_fixture",
    Path(__file__).with_name("test_fr06c5d8a2b4_studio_publication_journal.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)
publication_case = _shared.publication_case
execution_case = _shared.execution_case
studio_case = _shared.studio_case


async def _close(case):
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        assert row is not None
        generation = row.version
    return await admission.close_admission(
        operation_id=str(uuid4()),
        expected_generation=generation,
        reason="isolated Studio post-crash observation",
        session_factory=case.sessions,
    )


async def _observations(case):
    async with case.sessions() as session:
        return list((
            await session.scalars(
                select(StudioCrashObservation).order_by(StudioCrashObservation.id)
            )
        ).all())


def _filesystem_snapshot(root: Path) -> dict[str, tuple[int, int, int, int]]:
    if not root.exists():
        return {}
    result = {}
    for path in sorted(root.rglob("*")):
        value = path.lstat()
        result[str(path.relative_to(root))] = (
            value.st_ino,
            value.st_nlink,
            value.st_size,
            stat.S_IMODE(value.st_mode),
        )
    return result


@pytest.mark.asyncio
async def test_open_admission_cannot_create_postcrash_observation(publication_case):
    case = publication_case
    claim, _ = await _shared._store_owner(case)
    with pytest.raises(
        crash.StudioCrashObservationUnavailable,
        match="closed maintenance",
    ):
        await crash.observe_postcrash_state(
            session_factory=case.sessions,
            job_id=claim[0],
            nonce=claim[1],
            worker_incarnation=case.worker.incarnation,
        )
    assert not await _observations(case)


@pytest.mark.asyncio
async def test_closed_observation_without_publication_is_read_only_and_stays_blocked(
    publication_case,
):
    case = publication_case
    claim, _ = await _shared._store_owner(case)
    await _close(case)
    before = _filesystem_snapshot(case.root)

    row = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=claim[0],
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert row is not None
    assert row.proof["layout"] == "no_publication"
    assert row.proof["process_drain_verified"] is False
    assert row.proof["cleanup_authorized"] is False
    assert row.proof["filesystem_mutation_performed"] is False
    assert _filesystem_snapshot(case.root) == before

    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    observation, = snapshot["postcrash_observations"]
    assert observation["observation_id"] == row.id
    assert observation["valid_observation"] is True
    assert observation["requires_reconciliation"] is True
    assert snapshot["postcrash_observation_count"] == 1
    assert not snapshot["is_clear"] and not snapshot["full_host_closure"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "after_commit", "layout", "partials", "finals"),
    [
        ("link_intent", False, "owned_staging_present", 1, 0),
        ("published", True, "owned_staging_and_final_hardlinks", 1, 1),
        ("complete", True, "owned_final_present", 0, 1),
    ],
)
async def test_observation_classifies_real_crash_like_publication_without_mutation(
    publication_case,
    monkeypatch,
    failure,
    after_commit,
    layout,
    partials,
    finals,
):
    case = publication_case
    claim, _ = await _shared._store_owner(case)
    args = _shared._args(case.root)
    original = journal.persist_event

    async def fail(**kwargs):
        if kwargs["operation"] == failure and not after_commit:
            raise RuntimeError("synthetic pre-ack crash")
        await original(**kwargs)
        if kwargs["operation"] == failure and after_commit:
            raise RuntimeError("synthetic post-ack crash")

    monkeypatch.setattr(journal, "persist_event", fail)
    with pytest.raises(registry.StudioResourceUncertain):
        await _shared._publish(case, claim, args)

    assert len(list(case.root.rglob("*.partial"))) == partials
    assert len(list(case.root.rglob("*.zip"))) == finals
    before = _filesystem_snapshot(case.root)
    await _close(case)

    row = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=claim[0],
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert row is not None
    assert row.proof["layout"] == layout
    assert row.proof["directory_chain_verified"] is True
    assert _filesystem_snapshot(case.root) == before
    assert row.proof["cleanup_authorized"] is False
    assert row.proof["process_drain_verified"] is False


@pytest.mark.asyncio
async def test_observation_is_idempotent_and_never_reobserves_mutated_files(
    publication_case,
    monkeypatch,
):
    case = publication_case
    claim, _ = await _shared._store_owner(case)
    args = _shared._args(case.root)
    original = journal.persist_event

    async def fail(**kwargs):
        if kwargs["operation"] == "link_intent":
            raise RuntimeError("synthetic stopped publication")
        await original(**kwargs)

    monkeypatch.setattr(journal, "persist_event", fail)
    with pytest.raises(registry.StudioResourceUncertain):
        await _shared._publish(case, claim, args)
    await _close(case)

    first = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=claim[0],
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert first is not None
    before_proof = deepcopy(first.proof)

    partial, = case.root.rglob("*.partial")
    partial.chmod(0o400)
    second = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=claim[0],
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert second is not None and second.id == first.id
    assert second.proof == before_proof
    assert len(await _observations(case)) == 1


@pytest.mark.asyncio
async def test_observation_survives_raw_row_deletion_and_blocks_replay(
    publication_case,
):
    case = publication_case
    claim, _ = await _shared._store_owner(case)
    closed = await _close(case)
    row = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=claim[0],
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert row is not None

    async with case.sessions() as session:
        await session.execute(
            delete(StudioPublication).where(StudioPublication.job_id == claim[0])
        )
        await session.execute(
            delete(StudioExecution).where(StudioExecution.job_id == claim[0])
        )
        await session.execute(delete(StudioJob).where(StudioJob.id == claim[0]))
        await session.commit()

    assert (await _observations(case))[0].proof == row.proof
    await _shared._shared._shared._new(case, id=claim[0])
    assert closed.operation_id is not None
    await admission.open_admission(
        operation_id=closed.operation_id,
        expected_generation=closed.generation,
        reason="isolated replay-fence verification",
        session_factory=case.sessions,
    )
    assert await case.worker.claim_by_id(claim[0]) is None

    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["orphan_postcrash_observation_count"] == 1
    assert snapshot["invalid_postcrash_observation_count"] == 1
    assert not snapshot["is_clear"]


@pytest.mark.asyncio
async def test_observation_blocks_later_prestart_terminalization(publication_case):
    case = publication_case
    job_id = await _shared._shared._shared._new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None
    closed = await _close(case)
    observed = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert observed is not None and observed.proof["layout"] == "no_publication"

    # Cancellation is still available during maintenance closure, but the
    # retained crash observation prevents C2 from certifying never-started work.
    response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancel_requested"
    assert (await _shared._shared._shared._row(case, job_id))["completed_at"] is None
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["postcrash_observation_count"] == 1
    assert snapshot["blocker_count"] >= 1 and not snapshot["is_clear"]
    assert closed.operation_id is not None


@pytest.mark.asyncio
async def test_observation_blocks_later_poststart_terminalization(publication_case):
    from app.services import studio_poststart_cancellation as poststart

    case = publication_case
    job_id = await _shared._shared._shared._new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None and await case.worker._begin_execution(*claim)
    await _close(case)
    observed = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert observed is not None

    response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancel_requested"
    await registry.observe_execution_end(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
        interrupted=True,
    )
    await case.worker._mark_unresolved(job_id, claim[1], "synthetic post-crash")
    assert not await poststart.settle_poststart_cancellation(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["poststart_cancelled_count"] == 0
    assert snapshot["postcrash_observation_count"] == 1
    assert not snapshot["is_clear"]
