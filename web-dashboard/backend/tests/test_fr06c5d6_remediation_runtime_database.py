"""Real PostgreSQL remediation preparation with retained local filesystem work.

Each case imports the private UUID-schema fixture and runs actual admission,
ownership, claim/begin/result commits, heartbeat, uncertainty and finish. The
observing builder always invokes the real descriptor-pinned filesystem helper.
No application subprocess, external agent, scanner or production path is used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import HostMaintenanceWorkCycle, SecurityRemediation
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_remediation as activities
from app.services import security_remediation_files as files
from app.services import security_remediation_worker as worker
from tests.test_host_maintenance_remediation_db import remediation_db as remediation_db


WAIT_SECONDS = 15
HEARTBEAT_INTERVAL = 0.05


class ThreadBarrier:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self):
        self.entered.set()
        if not self.release.wait(WAIT_SECONDS):
            raise RuntimeError("Synthetic remediation thread barrier timed out")


@pytest_asyncio.fixture
async def runtime_case(remediation_db, monkeypatch, tmp_path):
    source_root = tmp_path / "security-sources"
    project_root = tmp_path / "project-executions"
    work_root = tmp_path / "security-remediations"
    for path in (source_root, project_root, work_root):
        path.mkdir(mode=0o700)
    source = source_root / "snapshot"
    source.mkdir(mode=0o700)
    payload = b"print('synthetic isolated remediation')\n"
    (source / "main.py").write_bytes(payload)
    (source / "main.py").chmod(0o600)
    for name, value in (
        ("SOURCE_ROOT", source_root),
        ("PROJECT_EXECUTION_ROOT", project_root),
        ("WORK_ROOT", work_root),
    ):
        monkeypatch.setattr(worker, name, value)
    monkeypatch.setenv(
        "SECURITY_REMEDIATION_WORKER_HEALTH_FILE", str(tmp_path / "worker-health.json")
    )
    case = SimpleNamespace(
        db=remediation_db,
        sessions=remediation_db.sessions,
        loop=asyncio.get_running_loop(),
        loop_thread=threading.get_ident(),
        source_root=source_root,
        source=source,
        payload=payload,
        work_root=work_root,
        remediation_id=None,
        builder_calls=[],
        before_copy=[],
        thread_entered=threading.Event(),
        thread_finished=threading.Event(),
        barriers=[],
        stop_signal=None,
        helper_limits={},
    )

    def observed_builder(build, stop):
        assert threading.get_ident() != case.loop_thread
        assert isinstance(build, files.RemediationBuildInput)
        assert build.source == source
        assert build.work_root == work_root
        assert build.remediation_id == case.remediation_id
        observation = asyncio.run_coroutine_threadsafe(
            _observe_committed_before_copy(case, build), case.loop
        )
        observation.result(timeout=WAIT_SECONDS)
        case.builder_calls.append(build)
        case.stop_signal = stop
        case.thread_entered.set()
        try:
            return files.prepare_remediation_bundle(build, stop, **case.helper_limits)
        finally:
            case.thread_finished.set()

    case.worker = worker.Worker(
        session_factory=case.sessions,
        builder=observed_builder,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )
    try:
        yield case
    finally:
        for barrier in case.barriers:
            barrier.release.set()


async def _new_remediation(case, **changes):
    return await case.db.new_remediation(source_snapshot=str(case.source), **changes)


async def _claim(case):
    case.remediation_id = await _new_remediation(case)
    ownership = await case.worker.claim()
    assert ownership is not None
    assert ownership.remediation_id == case.remediation_id
    return ownership


async def _observe_committed_before_copy(case, build):
    # A separate PG connection verifies both claim and one-time begin commits
    # before the real filesystem helper can create any stage or copy a byte.
    async with case.sessions() as observer:
        item = await observer.get(SecurityRemediation, case.remediation_id)
        activity = await observer.get(HostMaintenanceWorkCycle, build.activity_id)
        assert item is not None and activity is not None
        assert activity.job_id == item.id
        assert activity.consumer == activities.CONSUMER
        assert activity.state == "active" and activity.phase == "preparing"
        assert item.status == "preparing"
        assert item.worktree_ref == "preparing:" + activity.id
        assert item.preparation_protocol_version == 1
        assert item.preparation_outcome is None
        case.before_copy.append((item.id, activity.id, activity.admitted_generation))


def _copy_barrier(case, monkeypatch):
    barrier = ThreadBarrier()
    case.barriers.append(barrier)
    actual = files._copy_regular_file

    def blocked(*args, **kwargs):
        barrier.wait()
        return actual(*args, **kwargs)

    monkeypatch.setattr(files, "_copy_regular_file", blocked)
    return barrier


def _cleanup_barrier(case, monkeypatch):
    barrier = ThreadBarrier()
    case.barriers.append(barrier)
    actual = files._cleanup_owned_stage

    def blocked(*args, **kwargs):
        barrier.wait()
        return actual(*args, **kwargs)

    monkeypatch.setattr(files, "_cleanup_owned_stage", blocked)
    return barrier


async def _wait_thread(event):
    async with asyncio.timeout(WAIT_SECONDS):
        while not event.is_set():
            await asyncio.sleep(0.005)


async def _drain(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True), timeout=WAIT_SECONDS
        )


async def _snapshot(case, closed, *, unresolved=False):
    snapshot = await case.db.snapshot(closed)
    assert snapshot.authority.operation_id == closed.operation_id
    assert snapshot.authority.generation == closed.generation
    assert not snapshot.authority.is_open
    assert snapshot.blocker_count == 1 and snapshot.unfinished_count == 1
    assert snapshot.unresolved_count == int(unresolved)
    assert not snapshot.is_clear
    return snapshot


async def _wait_unresolved(case):
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            rows = await case.db.registry_rows()
            if len(rows) == 1 and rows[0]["state"] == "unresolved":
                assert rows[0]["unresolved_reason"]
                return rows[0]
            await asyncio.sleep(0.005)


async def _wait_heartbeat_advance(case, previous):
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            rows = await case.db.registry_rows()
            assert len(rows) == 1 and rows[0]["state"] == "active"
            assert rows[0]["unresolved_reason"] is None
            if rows[0]["heartbeat_at"] > previous:
                return rows[0]["heartbeat_at"]
            await asyncio.sleep(0.01)


async def _assert_unresolved(case, *, outcome=None):
    item = await case.db.remediation_row(case.remediation_id)
    rows = await case.db.registry_rows()
    assert len(rows) == 1 and rows[0]["state"] == "unresolved"
    assert rows[0]["unresolved_reason"]
    assert item["preparation_protocol_version"] == 1
    assert item["preparation_outcome"] == outcome
    if outcome is None:
        assert item["status"] == "preparing"
        assert item["worktree_ref"] == "preparing:" + rows[0]["id"]
    elif outcome == "clean_failed":
        assert item["status"] == "failed" and item["worktree_ref"] is None
        assert item["regression_result"]["production_modified"] is False
        assert item["regression_result"]["error_type"]
        assert rows[0]["phase"] == outcome
    else:
        assert outcome == "prepared"
        assert item["status"] == "worktree_ready"
        assert item["worktree_ref"] == (
            "security-remediation://" + case.remediation_id + "/source"
        )
        assert item["regression_result"]["production_modified"] is False
        assert item["regression_result"]["isolation"]["files"] == 1
        assert rows[0]["phase"] == outcome
    return item, rows


async def _reopen(case, closed):
    await admission.open_admission(
        operation_id=closed.operation_id,
        expected_generation=closed.generation,
        reason="Synthetic remediation runtime reopen",
        session_factory=case.sessions,
    )


async def _assert_no_reclaim(case, ownership, *, closed=None, outcome=None):
    if closed is not None:
        await _reopen(case, closed)
    before = await _assert_unresolved(case, outcome=outcome)
    calls = len(case.builder_calls)
    assert await case.worker.claim() is None
    assert await case.worker.claim() is None
    with pytest.raises(activities.RemediationActivityOwnershipLost):
        await case.worker.prepare(ownership)
    assert len(case.builder_calls) == calls
    assert await _assert_unresolved(case, outcome=outcome) == before


async def _assert_prepared(case):
    item = await case.db.remediation_row(case.remediation_id)
    assert item["status"] == "worktree_ready"
    assert item["preparation_protocol_version"] == 1
    assert item["preparation_outcome"] == "prepared"
    assert item["worktree_ref"] == (
        "security-remediation://" + case.remediation_id + "/source"
    )
    assert item["regression_result"]["production_modified"] is False
    isolation = item["regression_result"]["isolation"]
    assert isolation["files"] == 1 and isolation["bytes"] == len(case.payload)
    assert len(isolation["manifest_digest"]) == 64
    plan_path = case.work_root / case.remediation_id / "remediation-plan.json"
    plan_digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert isolation["plan_digest"] == plan_digest
    copied_file = case.work_root / case.remediation_id / "source" / "main.py"
    assert copied_file.read_bytes() == case.payload
    assert await case.db.registry_rows() == []
    assert len(case.builder_calls) == len(case.before_copy) == 1
    return item


async def _reject_commit(case, phase):
    if phase == "claim":
        event = "INSERT"
        predicate = "NEW.consumer = '" + activities.CONSUMER + "'"
    elif phase == "begin":
        event = "UPDATE"
        predicate = (
            "NEW.phase = 'preparing' AND OLD.phase = 'claimed' "
            "AND NEW.state = 'active'"
        )
    elif phase == "heartbeat":
        event = "UPDATE"
        predicate = (
            "NEW.heartbeat_at IS DISTINCT FROM OLD.heartbeat_at "
            "AND NEW.state = 'active'"
        )
    else:
        assert phase == "result"
        event = "UPDATE"
        predicate = (
            "NEW.phase = 'prepared' AND OLD.phase = 'preparing' "
            "AND NEW.state = 'active'"
        )
    async with case.sessions() as session:
        await session.execute(
            text(
                """
                CREATE FUNCTION reject_remediation_runtime_commit()
                RETURNS trigger LANGUAGE plpgsql AS $function$
                BEGIN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'synthetic remediation deferred commit rejected';
                    RETURN NEW;
                END;
                $function$
                """
            )
        )
        await session.execute(
            text(
                "CREATE CONSTRAINT TRIGGER reject_remediation_runtime_commit "
                f"AFTER {event} ON host_maintenance_work_cycles "
                "DEFERRABLE INITIALLY DEFERRED "
                f"FOR EACH ROW WHEN ({predicate}) "
                "EXECUTE FUNCTION reject_remediation_runtime_commit()"
            )
        )
        await session.commit()

@pytest.mark.asyncio
async def test_committed_owner_begins_after_close_and_blocks_drain_through_copy(
    runtime_case, monkeypatch
):
    case = runtime_case
    barrier = _copy_barrier(case, monkeypatch)
    ownership = await _claim(case)
    closed = await case.db.close()
    await _snapshot(case, closed)
    task = asyncio.create_task(case.worker.prepare(ownership))
    try:
        await _wait_thread(barrier.entered)
        assert case.before_copy == [
            (case.remediation_id, ownership.activity_id, ownership.admitted_generation)
        ]
        await _snapshot(case, closed)
        assert not task.done() and not case.thread_finished.is_set()
        barrier.release.set()
        await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert case.thread_finished.is_set()
        await _assert_prepared(case)
        assert (await case.db.snapshot(closed)).is_clear
    finally:
        barrier.release.set()
        await _drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["copy", "cleanup"])
async def test_repeated_cancellation_joins_actual_filesystem_and_retains_real_owner(
    runtime_case, monkeypatch, phase
):
    case = runtime_case
    if phase == "copy":
        barrier = _copy_barrier(case, monkeypatch)
    else:
        case.helper_limits["max_bytes"] = 1
        barrier = _cleanup_barrier(case, monkeypatch)
    ownership = await _claim(case)
    task = asyncio.create_task(case.worker.prepare(ownership))
    try:
        await _wait_thread(barrier.entered)
        closed = await case.db.close()
        previous = (await case.db.registry_rows())[0]["heartbeat_at"]
        task.cancel()
        assert case.stop_signal is not None
        await _wait_thread(case.stop_signal)
        advanced = await _wait_heartbeat_advance(case, previous)
        await _snapshot(case, closed)
        assert not task.done() and not case.thread_finished.is_set()
        task.cancel()
        await _wait_heartbeat_advance(case, advanced)
        await _snapshot(case, closed)
        assert not task.done() and not case.thread_finished.is_set()
        barrier.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert case.thread_finished.is_set()
        assert not (case.work_root / case.remediation_id).exists()
        # Cleanup can finish a previously observed ordinary failure and commit
        # clean_failed while the cancelled caller retains its unresolved owner.
        outcome = "clean_failed" if phase == "cleanup" else None
        await _assert_unresolved(case, outcome=outcome)
        await _assert_no_reclaim(
            case, ownership, closed=closed, outcome=outcome
        )
    finally:
        barrier.release.set()
        await _drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["claim", "begin", "result"])
async def test_real_deferred_commit_failures_keep_copy_and_proof_boundaries(
    runtime_case, phase
):
    case = runtime_case
    case.remediation_id = await _new_remediation(case)
    before = await case.db.remediation_row(case.remediation_id)
    if phase == "claim":
        await _reject_commit(case, phase)
        with pytest.raises(
            SQLAlchemyError, match="synthetic remediation deferred commit rejected"
        ):
            await asyncio.wait_for(case.worker.run_once(), timeout=WAIT_SECONDS)
        assert case.builder_calls == [] and case.before_copy == []
        assert not case.thread_entered.is_set()
        assert await case.db.remediation_row(case.remediation_id) == before
        assert await case.db.registry_rows() == []
        assert list(case.work_root.iterdir()) == []
        return

    ownership = await case.worker.claim()
    assert ownership is not None and ownership.remediation_id == case.remediation_id
    await _reject_commit(case, phase)
    with pytest.raises(
        SQLAlchemyError, match="synthetic remediation deferred commit rejected"
    ):
        await asyncio.wait_for(case.worker.prepare(ownership), timeout=WAIT_SECONDS)
    await _assert_unresolved(case)
    if phase == "begin":
        assert case.builder_calls == [] and case.before_copy == []
        assert not case.thread_entered.is_set()
        assert list(case.work_root.iterdir()) == []
    else:
        assert len(case.builder_calls) == len(case.before_copy) == 1
        assert case.thread_finished.is_set()
        # Publication happened before PostgreSQL rejected the result commit.
        # Its source and plan must remain available for reconciliation.
        bundle = case.work_root / case.remediation_id
        assert (bundle / "source" / "main.py").read_bytes() == case.payload
        assert json.loads((bundle / "remediation-plan.json").read_text()) == {
            "schema_version": 1
        }
    await _assert_no_reclaim(case, ownership)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cancel_before_loss",
    [False, True],
    ids=["heartbeat-loss", "loss-during-cancel-join"],
)
async def test_real_heartbeat_commit_loss_marks_uncertainty_before_joining_copy(
    runtime_case, monkeypatch, cancel_before_loss
):
    case = runtime_case
    barrier = _copy_barrier(case, monkeypatch)
    ownership = await _claim(case)
    task = asyncio.create_task(case.worker.prepare(ownership))
    try:
        await _wait_thread(barrier.entered)
        if cancel_before_loss:
            previous = (await case.db.registry_rows())[0]["heartbeat_at"]
            task.cancel()
            assert case.stop_signal is not None
            await _wait_thread(case.stop_signal)
            await _wait_heartbeat_advance(case, previous)
            assert not task.done() and not case.thread_finished.is_set()
        await _reject_commit(case, "heartbeat")
        closed = await case.db.close()
        await _wait_unresolved(case)
        await _snapshot(case, closed, unresolved=True)
        assert not task.done() and not case.thread_finished.is_set()
        if cancel_before_loss:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not case.thread_finished.is_set()
        barrier.release.set()
        expected = asyncio.CancelledError if cancel_before_loss else SQLAlchemyError
        with pytest.raises(expected):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert case.thread_finished.is_set()
        await _assert_unresolved(case)
        await _assert_no_reclaim(case, ownership, closed=closed)
    finally:
        barrier.release.set()
        await _drain(task)


@pytest.mark.asyncio
async def test_actual_cleanup_failure_keeps_independent_uncertainty_and_no_reclaim(
    runtime_case, monkeypatch
):
    case = runtime_case
    case.helper_limits["max_bytes"] = 1
    cleanup_calls = []

    def fail_cleanup(parent_fd, stage_name, stage_fd, identities):
        assert parent_fd >= 0 and stage_fd >= 0
        assert identities.get(())
        cleanup_calls.append(stage_name)
        raise OSError("Synthetic pinned cleanup failure")

    monkeypatch.setattr(files, "_cleanup_owned_stage", fail_cleanup)
    ownership = await _claim(case)
    with pytest.raises(worker.RemediationPreparationUncertain):
        await asyncio.wait_for(case.worker.prepare(ownership), timeout=WAIT_SECONDS)
    assert cleanup_calls == [ownership.activity_id]
    assert case.thread_finished.is_set()
    assert not (case.work_root / case.remediation_id).exists()
    assert (case.work_root / ".tmp" / ownership.activity_id).is_dir()
    await _assert_unresolved(case)
    await _assert_no_reclaim(case, ownership)


@pytest.mark.asyncio
async def test_actual_bounded_failure_with_verified_cleanup_finishes_clean_failed(
    runtime_case,
):
    case = runtime_case
    case.helper_limits["max_bytes"] = 1
    ownership = await _claim(case)
    await asyncio.wait_for(case.worker.prepare(ownership), timeout=WAIT_SECONDS)
    item = await case.db.remediation_row(case.remediation_id)
    assert item["status"] == "failed" and item["worktree_ref"] is None
    assert item["preparation_protocol_version"] == 1
    assert item["preparation_outcome"] == "clean_failed"
    assert item["regression_result"] == {
        "error_type": "RemediationSourceLimit",
        "production_modified": False,
    }
    assert case.thread_finished.is_set()
    assert await case.db.registry_rows() == []
    assert not (case.work_root / case.remediation_id).exists()
    assert not (case.work_root / ".tmp" / ownership.activity_id).exists()
    assert await case.worker.claim() is None


@pytest.mark.asyncio
async def test_concurrent_and_replayed_capability_copy_only_once(
    runtime_case, monkeypatch
):
    case = runtime_case
    barrier = _copy_barrier(case, monkeypatch)
    ownership = await _claim(case)
    tasks = [
        asyncio.create_task(case.worker.prepare(ownership)),
        asyncio.create_task(case.worker.prepare(ownership)),
    ]
    try:
        await _wait_thread(barrier.entered)
        done, pending = await asyncio.wait(
            tasks, timeout=WAIT_SECONDS, return_when=asyncio.FIRST_COMPLETED
        )
        assert len(done) == len(pending) == 1
        with pytest.raises(activities.RemediationActivityOwnershipLost):
            await next(iter(done))
        assert len(case.builder_calls) == 1
        barrier.release.set()
        await asyncio.wait_for(next(iter(pending)), timeout=WAIT_SECONDS)
        await _assert_prepared(case)
        with pytest.raises(activities.RemediationActivityOwnershipLost):
            await case.worker.prepare(ownership)
        assert len(case.builder_calls) == 1
    finally:
        barrier.release.set()
        for task in tasks:
            await _drain(task)


@pytest.mark.asyncio
async def test_closed_default_worker_poll_is_healthy_and_never_initializes_worktree(
    runtime_case,
):
    case = runtime_case
    case.remediation_id = await _new_remediation(case)
    before = await case.db.remediation_row(case.remediation_id)
    closed = await case.db.close()
    default_worker = worker.Worker(
        session_factory=case.sessions,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )
    await default_worker.preflight()
    assert await default_worker.run_once() == 0
    assert await default_worker.run_once() == 0
    health = json.loads(default_worker.health.read_text())
    assert health["status"] == "healthy"
    assert worker.healthcheck() == 0
    assert list(case.work_root.iterdir()) == []
    assert await case.db.remediation_row(case.remediation_id) == before
    assert await case.db.registry_rows() == []
    snapshot = await case.db.snapshot(closed)
    assert snapshot.is_clear
    assert snapshot.frozen_planned_ids == (case.remediation_id,)


@pytest.mark.asyncio
async def test_worker_never_adopts_expired_or_legacy_preparing_work(
    runtime_case,
):
    case = runtime_case
    ownership = await _claim(case)
    old = datetime.now(UTC) - timedelta(days=3)
    await case.db.update_remediation(case.remediation_id, updated_at=old)
    async with case.sessions() as session:
        await session.execute(
            HostMaintenanceWorkCycle.__table__.update()
            .where(HostMaintenanceWorkCycle.id == ownership.activity_id)
            .values(started_at=old, heartbeat_at=old, lease_expires_at=old)
        )
        await session.commit()
    legacy_id = await _new_remediation(
        case,
        status="preparing",
        worktree_ref="preparing:" + str(uuid4()),
        updated_at=old,
    )
    dirty_id = await _new_remediation(
        case, worktree_ref="legacy-isolation-reference", updated_at=old
    )
    fresh_id = await _new_remediation(case)
    before_owned = await case.db.remediation_row(case.remediation_id)
    before_legacy = await case.db.remediation_row(legacy_id)
    before_dirty = await case.db.remediation_row(dirty_id)
    closed = await case.db.close()
    assert await case.worker.claim() is None
    snapshot = await case.db.snapshot(closed)
    assert ownership.remediation_id in {
        item.remediation_id for item in snapshot.activities
    }
    assert legacy_id in snapshot.unowned_preparing_ids
    assert dirty_id in snapshot.nonpristine_planned_ids
    assert fresh_id in snapshot.frozen_planned_ids
    await _reopen(case, closed)
    fresh = await case.worker.claim()
    assert fresh is not None and fresh.remediation_id == fresh_id
    assert await case.worker.claim() is None
    assert await case.db.remediation_row(case.remediation_id) == before_owned
    assert await case.db.remediation_row(legacy_id) == before_legacy
    assert await case.db.remediation_row(dirty_id) == before_dirty
    assert case.builder_calls == []

@pytest.mark.asyncio
async def test_graceful_worker_stop_finishes_admitted_copy_and_freezes_next_plan(
    runtime_case, monkeypatch
):
    case = runtime_case
    barrier = _copy_barrier(case, monkeypatch)
    case.remediation_id = await _new_remediation(case)
    queued_id = await _new_remediation(case)
    queued_before = await case.db.remediation_row(queued_id)
    task = asyncio.create_task(case.worker.run())
    try:
        await _wait_thread(barrier.entered)
        closed = await case.db.close()
        await _snapshot(case, closed)
        prior_health = json.loads(case.worker.health.read_text())
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                current = json.loads(case.worker.health.read_text())
                if current["checked_at_epoch"] > prior_health["checked_at_epoch"]:
                    break
                await asyncio.sleep(0.01)
        assert current["status"] == "healthy" and worker.healthcheck() == 0
        assert not task.done() and not case.thread_finished.is_set()
        case.worker.stop()
        barrier.release.set()
        await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        await _assert_prepared(case)
        assert case.worker.errors == 0 and case.worker.cycles == 1
        assert await case.db.remediation_row(queued_id) == queued_before
        snapshot = await case.db.snapshot(closed)
        assert snapshot.is_clear and snapshot.frozen_planned_ids == (queued_id,)
        case.worker.stop_event.clear()
        assert await case.worker.run_once() == 0
        assert worker.healthcheck() == 0
        assert await case.db.remediation_row(queued_id) == queued_before
        assert len(case.builder_calls) == 1
    finally:
        case.worker.stop()
        barrier.release.set()
        await _drain(task)

async def _install_result_commit_gate(case, lock_key):
    async with case.sessions() as session:
        await session.execute(
            text(
                "CREATE FUNCTION hold_remediation_result_commit() "
                "RETURNS trigger LANGUAGE plpgsql AS $function$ "
                "BEGIN "
                f"PERFORM pg_advisory_xact_lock({lock_key}); "
                "RETURN NEW; END; $function$"
            )
        )
        await session.execute(
            text(
                "CREATE CONSTRAINT TRIGGER hold_remediation_result_commit "
                "AFTER UPDATE ON host_maintenance_work_cycles "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                "WHEN (NEW.phase = 'prepared' AND OLD.phase = 'preparing') "
                "EXECUTE FUNCTION hold_remediation_result_commit()"
            )
        )
        await session.commit()


async def _wait_for_database_waiter(case, blocker_pid):
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            async with case.sessions() as observer:
                waiting = (
                    await observer.execute(
                        text(
                            "SELECT pid, wait_event_type, query FROM pg_stat_activity "
                            "WHERE :blocker_pid = ANY(pg_blocking_pids(pid)) "
                            "AND datname = current_database()"
                        ),
                        {"blocker_pid": blocker_pid},
                    )
                ).mappings().all()
            if waiting:
                assert len(waiting) == 1
                # The blocker and activity observations may straddle entry to
                # a wait. Keep polling until BOTH prove a real database lock;
                # a blocker PID alone must never release the test barrier.
                if waiting[0]["wait_event_type"] == "Lock":
                    return dict(waiting[0])
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancelled_result_commit_retains_heartbeat_waiter_and_published_proof(
    runtime_case,
):
    case = runtime_case
    ownership = await _claim(case)
    closed = await case.db.close()
    lock_key = uuid4().int % (2**31 - 1)
    await _install_result_commit_gate(case, lock_key)
    task = None
    async with case.sessions() as locker:
        await locker.execute(
            text("SELECT pg_advisory_lock(:lock_key)"), {"lock_key": lock_key}
        )
        locker_pid = await locker.scalar(text("SELECT pg_backend_pid()"))
        released = False
        try:
            task = asyncio.create_task(case.worker.prepare(ownership))
            committing = await _wait_for_database_waiter(case, locker_pid)
            assert committing["query"].strip().upper().startswith("COMMIT")
            assert case.thread_finished.is_set()
            assert len(case.builder_calls) == len(case.before_copy) == 1
            await _snapshot(case, closed)

            # The retained heartbeat is the worker's other transaction. Its
            # actual SELECT FOR UPDATE waits behind the result transaction,
            # which is held inside PostgreSQL's deferred COMMIT trigger.
            heartbeat = await _wait_for_database_waiter(case, committing["pid"])
            assert "security_remediations" in heartbeat["query"]
            assert "FOR UPDATE" in heartbeat["query"].upper()
            before = (await case.db.registry_rows())[0]
            assert before["state"] == "active" and before["phase"] == "preparing"
            task.cancel()
            assert case.stop_signal is not None
            await _wait_thread(case.stop_signal)
            assert not task.done()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            await _snapshot(case, closed)
            waiting_again = await _wait_for_database_waiter(case, committing["pid"])
            assert waiting_again["pid"] == heartbeat["pid"]
            while_locked = (await case.db.registry_rows())[0]
            assert while_locked["state"] == "active"
            assert while_locked["heartbeat_at"] == before["heartbeat_at"]

            unlocked = await locker.scalar(
                text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key}
            )
            assert unlocked is True
            released = True
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=WAIT_SECONDS)
            await _assert_unresolved(case, outcome="prepared")
            bundle = case.work_root / case.remediation_id
            assert (bundle / "source" / "main.py").read_bytes() == case.payload
            assert (bundle / "remediation-plan.json").is_file()

            # NullPool closes the real heartbeat connection after its joined
            # transaction completes; it must not remain detached or waiting.
            async with asyncio.timeout(WAIT_SECONDS):
                while True:
                    async with case.sessions() as observer:
                        remaining = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity WHERE pid = :pid"
                            ),
                            {"pid": heartbeat["pid"]},
                        )
                    if remaining == 0:
                        break
                    await asyncio.sleep(0.01)
            await _assert_no_reclaim(
                case, ownership, closed=closed, outcome="prepared"
            )
        finally:
            if not released:
                await locker.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            await _drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_wait_event", [None, "Client", "IO"])
async def test_database_waiter_requires_lock_observation_before_return(initial_wait_event):
    """A transient activity observation is not proof of the lock barrier."""
    observations = [
        [{"pid": 42, "wait_event_type": initial_wait_event, "query": "COMMIT"}],
        [],
        [{"pid": 42, "wait_event_type": "Lock", "query": "COMMIT"}],
    ]
    calls = []

    class Observer:
        async def execute(self, statement, parameters):
            assert parameters == {"blocker_pid": 7}
            assert "pg_blocking_pids" in str(statement)
            assert "current_database()" in str(statement)
            calls.append(parameters)
            values = observations.pop(0)
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: values))

    @asynccontextmanager
    async def sessions():
        yield Observer()

    result = await _wait_for_database_waiter(SimpleNamespace(sessions=sessions), 7)
    assert result == {"pid": 42, "wait_event_type": "Lock", "query": "COMMIT"}
    assert len(calls) == 3 and not observations
