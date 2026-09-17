"""Isolated behavioral contracts for backup-cycle ownership.

Every authority, session, executor, and I/O operation used here is an explicit
in-memory fake. These tests never connect to PostgreSQL or execute a provider.
Real database locking and schema contracts belong to the authority test suite.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.db.models import BackupRecord
from app.services import backup_executor as executor_module
from app.services import backup_worker as worker_module
from app.services import host_maintenance_cycles as cycle_module
from app.services.backup_executor import BackupExecutionError, BackupExecutor
from app.services.backup_worker import BackupJobWorker, ClaimedJob, LeaseLostError
from app.services.host_maintenance_admission import (
    COVERAGE_SCHEMA_VERSION,
    COVERAGE_SCOPE,
    HostMaintenanceClosed,
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
)
from app.services.host_maintenance_cycles import CycleOwnership


WAIT_SECONDS = 5


def _closed_authority():
    return HostMaintenanceClosed(
        HostMaintenanceSnapshot(
            schema_version=COVERAGE_SCHEMA_VERSION,
            scope=COVERAGE_SCOPE,
            generation=2,
            status="closed",
            enabled=False,
            operation_id=str(uuid4()),
            reason="synthetic-test-closure",
            changed_at=datetime.now(UTC),
        )
    )


class NoDatabaseSession:
    """Permit dependency injection, but reject every actual database operation."""

    def __init__(self, factory):
        self.factory = factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def scalar(self, *_args, **_kwargs):
        raise AssertionError("cycle behavior tests must not query a database")

    async def execute(self, *_args, **_kwargs):
        raise AssertionError("cycle behavior tests must not execute SQL")

    async def commit(self):
        raise AssertionError("cycle behavior tests must not commit a database")


class NoDatabaseFactory:
    def __call__(self):
        return NoDatabaseSession(self)


class RecordingCycles:
    """A registry whose retained owners are observable after worker failure."""

    def __init__(self, sessions):
        self.sessions = sessions
        self.opened = True
        self.begin_error = None
        self.mark_error = None
        self.finish_error = None
        self.owners: list[CycleOwnership] = []
        self.states: dict[str, str] = {}
        self.events: list[tuple] = []
        self.marks: list[tuple[CycleOwnership, str]] = []
        self.finishes: list[CycleOwnership] = []
        self.scope_checks: list[str] = []

    async def admission_check(self, session, *, required_scope):
        assert isinstance(session, NoDatabaseSession)
        assert session.factory is self.sessions
        assert required_scope == "backup_cycles"
        self.scope_checks.append(required_scope)
        return self.opened

    def assert_active(self):
        assert len(self.owners) == 1
        owner = self.owners[0]
        assert self.states == {owner.cycle_id: "active"}
        assert not self.finishes
        return owner

    def _check(self, ownership, session_factory):
        assert session_factory is self.sessions
        assert ownership in self.owners
        assert ownership.cycle_id in self.states

    async def begin_backup_cycle(
        self, *, worker_incarnation, phase="run_once", session_factory
    ):
        assert session_factory is self.sessions
        assert str(UUID(worker_incarnation)) == worker_incarnation
        self.events.append(("begin-attempt", phase))
        if self.begin_error is not None:
            raise self.begin_error
        if not self.opened:
            raise _closed_authority()
        ownership = CycleOwnership(
            cycle_id=str(uuid4()),
            worker_incarnation=worker_incarnation,
            admitted_generation=1,
            ownership_nonce=str(uuid4()),
        )
        self.owners.append(ownership)
        self.states[ownership.cycle_id] = "active"
        self.events.append(("begin", phase, ownership.cycle_id))
        return ownership

    async def heartbeat_backup_cycle(
        self, ownership, *, phase=None, job_id=None, session_factory
    ):
        self._check(ownership, session_factory)
        if job_id is not None:
            assert str(UUID(job_id)) == job_id
        self.events.append(("heartbeat", phase, job_id))

    async def mark_backup_cycle_unresolved(
        self, ownership, *, reason, session_factory
    ):
        self._check(ownership, session_factory)
        assert isinstance(reason, str) and reason.strip()
        assert len(reason) <= 160
        self.marks.append((ownership, reason))
        self.events.append(("unresolved", ownership.cycle_id))
        if self.mark_error is not None:
            raise self.mark_error
        self.states[ownership.cycle_id] = "unresolved"

    async def finish_backup_cycle(self, ownership, *, session_factory):
        self._check(ownership, session_factory)
        assert self.states[ownership.cycle_id] == "active"
        self.finishes.append(ownership)
        self.events.append(("finish-attempt", ownership.cycle_id))
        if self.finish_error is not None:
            raise self.finish_error
        del self.states[ownership.cycle_id]
        self.events.append(("finished", ownership.cycle_id))


@pytest.fixture(autouse=True)
def prohibit_default_runtime_dependencies(monkeypatch):
    def forbidden_factory(*_args, **_kwargs):
        raise AssertionError("tests require explicit fake runtime dependencies")

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("tests must not use production authority or subprocess I/O")

    for name in (
        "get_backup_executor",
        "ThreeDAssetSnapshotExecutor",
        "OffsiteBackupReplicator",
    ):
        monkeypatch.setattr(worker_module, name, forbidden_factory)
    for name in (
        "begin_backup_cycle",
        "heartbeat_backup_cycle",
        "mark_backup_cycle_unresolved",
        "finish_backup_cycle",
    ):
        monkeypatch.setattr(cycle_module, name, forbidden_async)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_async)


@pytest.fixture
def cycle_case():
    sessions = NoDatabaseFactory()
    registry = RecordingCycles(sessions)
    worker = BackupJobWorker(
        executor=SimpleNamespace(),
        three_d_executor=SimpleNamespace(),
        offsite_replicator=SimpleNamespace(),
        session_factory=sessions,
        admission_check=registry.admission_check,
        cycle_service=registry,
    )
    return SimpleNamespace(worker=worker, registry=registry, sessions=sessions)


async def _wait(event):
    await asyncio.wait_for(event.wait(), timeout=WAIT_SECONDS)


async def _settle_tasks(*tasks):
    present = [task for task in tasks if task is not None]
    for task in present:
        if not task.done():
            task.cancel()
    if present:
        await asyncio.wait_for(
            asyncio.gather(*present, return_exceptions=True),
            timeout=WAIT_SECONDS,
        )


def _assert_unresolved(case):
    assert len(case.registry.owners) == 1
    owner = case.registry.owners[0]
    assert case.registry.states == {owner.cycle_id: "unresolved"}
    assert case.registry.marks
    assert not case.registry.finishes
    return owner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denial",
    [
        _closed_authority(),
        HostMaintenanceUnavailable("synthetic malformed or missing authority"),
    ],
)
async def test_denied_cycle_never_enters_work_or_finishes(
    cycle_case, monkeypatch, denial
):
    case = cycle_case
    case.registry.begin_error = denial

    async def forbidden_work():
        raise AssertionError("closed cycle entered backup, scheduling, or retention")

    monkeypatch.setattr(case.worker, "_run_once_owned", forbidden_work)
    assert await case.worker.run_once() is False
    assert not case.registry.owners
    assert not case.registry.marks
    assert not case.registry.finishes


@pytest.mark.asyncio
async def test_registration_database_error_precedes_every_io(cycle_case, monkeypatch):
    case = cycle_case
    case.registry.begin_error = RuntimeError("synthetic registration database failure")

    async def forbidden_work():
        raise AssertionError("work ran before cycle registration committed")

    monkeypatch.setattr(case.worker, "_run_once_owned", forbidden_work)
    with pytest.raises(RuntimeError, match="synthetic registration database failure"):
        await case.worker.run_once()
    assert not case.registry.owners
    assert not case.registry.finishes


@pytest.mark.asyncio
@pytest.mark.parametrize("worked", [False, True])
async def test_settled_cycle_finishes_exact_owner_and_preserves_result(
    cycle_case, monkeypatch, worked
):
    case = cycle_case
    job_id = str(uuid4())

    async def owned_work():
        case.registry.assert_active()
        await case.worker._update_cycle_phase("synthetic-work", job_id=job_id)
        case.registry.assert_active()
        case.registry.events.append(("work-settled",))
        return worked

    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    assert await case.worker.run_once() is worked
    assert not case.registry.states
    assert case.registry.finishes == case.registry.owners
    assert not case.registry.marks
    assert ("heartbeat", "synthetic-work", job_id) in case.registry.events
    settled_index = case.registry.events.index(("work-settled",))
    finish_index = next(
        index
        for index, event in enumerate(case.registry.events)
        if event[0] == "finish-attempt"
    )
    assert settled_index < finish_index


@pytest.mark.asyncio
async def test_swallowed_cleanup_uncertainty_retains_owner_despite_true_result(
    cycle_case, monkeypatch
):
    case = cycle_case

    async def owned_work():
        case.registry.assert_active()
        case.worker._record_cycle_uncertainty("synthetic-cleanup-unproved")
        return True

    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    assert await case.worker.run_once() is True
    _assert_unresolved(case)


@pytest.mark.asyncio
async def test_escaping_work_error_retains_owner_without_releasing_it(
    cycle_case, monkeypatch
):
    case = cycle_case

    async def owned_work():
        case.registry.assert_active()
        raise RuntimeError("synthetic-retention-error-with-private-detail")

    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    with pytest.raises(RuntimeError, match="synthetic-retention-error"):
        await case.worker.run_once()
    _assert_unresolved(case)
    assert all(
        "private-detail" not in reason for _owner, reason in case.registry.marks
    )


@pytest.mark.asyncio
async def test_cancellation_unwinds_owned_work_and_retains_cycle(
    cycle_case, monkeypatch
):
    case = cycle_case
    entered = asyncio.Event()
    release = asyncio.Event()
    unwound = asyncio.Event()

    async def owned_work():
        case.registry.assert_active()
        entered.set()
        try:
            await release.wait()
        finally:
            unwound.set()
        return True

    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    task = asyncio.create_task(case.worker.run_once())
    try:
        await _wait(entered)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert unwound.is_set()
        _assert_unresolved(case)
    finally:
        release.set()
        await _settle_tasks(task)


@pytest.mark.asyncio
async def test_cycle_heartbeat_failure_settles_work_and_retains_owner(
    cycle_case, monkeypatch
):
    case = cycle_case
    entered = asyncio.Event()
    release = asyncio.Event()
    unwound = asyncio.Event()

    async def owned_work():
        case.registry.assert_active()
        entered.set()
        try:
            await release.wait()
        finally:
            unwound.set()
        return True

    async def failed_heartbeat(ownership, stop_event):
        assert ownership in case.registry.owners
        await entered.wait()
        raise RuntimeError("synthetic cycle heartbeat database failure")

    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    monkeypatch.setattr(case.worker, "_heartbeat_cycle", failed_heartbeat)
    task = asyncio.create_task(case.worker.run_once())
    try:
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert entered.is_set() and unwound.is_set()
        _assert_unresolved(case)
    finally:
        release.set()
        await _settle_tasks(task)


@pytest.mark.asyncio
async def test_failed_unresolved_write_does_not_finish_or_forget_owner(
    cycle_case, monkeypatch
):
    case = cycle_case
    case.registry.mark_error = RuntimeError("synthetic registry write unavailable")

    async def owned_work():
        case.registry.assert_active()
        raise RuntimeError("synthetic operation failed")

    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    with pytest.raises(RuntimeError):
        await case.worker.run_once()
    assert len(case.registry.owners) == 1
    owner = case.registry.owners[0]
    assert case.registry.states == {owner.cycle_id: "active"}
    assert case.registry.marks
    assert not case.registry.finishes


@pytest.mark.asyncio
async def test_failed_finish_is_not_retried_as_unconditional_cleanup(
    cycle_case, monkeypatch
):
    case = cycle_case
    case.registry.finish_error = RuntimeError("synthetic finish database failure")

    async def owned_work():
        case.registry.assert_active()
        return True

    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    with pytest.raises(RuntimeError):
        await case.worker.run_once()
    assert len(case.registry.owners) == 1
    owner = case.registry.owners[0]
    assert case.registry.finishes == [owner]
    assert owner.cycle_id in case.registry.states


@pytest.mark.asyncio
async def test_startup_waits_for_admission_and_keeps_all_probes_owned(
    cycle_case, monkeypatch
):
    case = cycle_case
    probes = []

    def probe(name):
        def record(*_args, **_kwargs):
            case.registry.assert_active()
            probes.append(name)
        return record

    monkeypatch.setattr(
        case.worker,
        "_executor",
        SimpleNamespace(
            verify_storage=probe("backup-storage"),
            cleanup_stale_partials=probe("backup-partials"),
        ),
    )
    monkeypatch.setattr(
        case.worker,
        "_three_d_executor",
        SimpleNamespace(
            verify_source=probe("three-d-source"),
            cleanup_stale_partials=probe("three-d-partials"),
        ),
    )
    monkeypatch.setattr(
        case.worker,
        "_offsite",
        SimpleNamespace(preflight=probe("offsite-preflight")),
    )
    case.registry.opened = False
    assert await case.worker._ensure_startup() is False
    assert not probes and not case.registry.owners
    assert case.worker._startup_complete is False

    case.registry.opened = True
    assert await case.worker._ensure_startup() is True
    assert case.worker._startup_complete is True
    assert sorted(probes) == sorted(
        [
            "backup-storage", "backup-partials", "three-d-source",
            "three-d-partials", "offsite-preflight",
        ]
    )
    assert not case.registry.states
    assert len(case.registry.owners) == 1
    assert case.registry.finishes == case.registry.owners
    assert not case.registry.marks
    assert await case.worker._ensure_startup() is True
    assert len(probes) == 5 and len(case.registry.owners) == 1


@pytest.mark.asyncio
async def test_escaping_startup_error_never_marks_startup_complete(
    cycle_case, monkeypatch
):
    case = cycle_case

    async def failed_startup():
        case.registry.assert_active()
        raise RuntimeError("synthetic startup cleanup failure")

    monkeypatch.setattr(case.worker, "_startup_owned", failed_startup)
    with pytest.raises(RuntimeError, match="synthetic startup cleanup failure"):
        await case.worker._ensure_startup()
    assert case.worker._startup_complete is False
    _assert_unresolved(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["backup", "restore", "idle-maintenance"])
async def test_actual_cycle_body_keeps_followups_and_retention_inside_ownership(
    cycle_case, monkeypatch, branch
):
    case = cycle_case
    claim = ClaimedJob(str(uuid4()), "synthetic-job-lease", reclaimed=False)
    observed = []

    def record(name):
        case.registry.assert_active()
        observed.append(name)

    async def claim_backup():
        record("claim-backup")
        return claim if branch == "backup" else None

    async def claim_restore():
        record("claim-restore")
        return claim if branch == "restore" else None

    async def execute_backup(received):
        assert received == claim
        record("backup-settled")

    async def execute_restore(received):
        assert received == claim
        record("restore-settled")

    async def job_heartbeat(_model, _claim, stop_event):
        await stop_event.wait()

    async def schedule_restore():
        record("schedule-restore")
        return False

    async def schedule_backup():
        record("schedule-backup")
        return False

    async def retention(*, current_backup_id, pressure):
        assert current_backup_id == (claim.id if branch == "backup" else None)
        assert pressure is False
        record("retention-settled")

    monkeypatch.setattr(case.worker, "claim_backup", claim_backup)
    monkeypatch.setattr(case.worker, "claim_restore_validation", claim_restore)
    monkeypatch.setattr(case.worker, "execute_backup", execute_backup)
    monkeypatch.setattr(case.worker, "execute_restore_validation", execute_restore)
    monkeypatch.setattr(case.worker, "_heartbeat_lease", job_heartbeat)
    monkeypatch.setattr(
        case.worker, "_enqueue_latest_scheduled_restore_validation_if_needed",
        schedule_restore,
    )
    monkeypatch.setattr(
        case.worker, "_enqueue_scheduled_backup_if_due", schedule_backup
    )
    monkeypatch.setattr(case.worker, "_apply_retention", retention)

    assert await case.worker.run_once() is True
    expected = {
        "backup": [
            "claim-backup", "backup-settled", "schedule-restore", "retention-settled",
        ],
        "restore": ["claim-backup", "claim-restore", "restore-settled"],
        "idle-maintenance": [
            "claim-backup", "claim-restore", "schedule-restore",
            "schedule-backup", "retention-settled",
        ],
    }
    assert observed == expected[branch]
    assert case.registry.finishes == case.registry.owners
    assert not case.registry.states and not case.registry.marks


@pytest.mark.asyncio
async def test_outer_cancellation_waits_for_detached_job_cleanup_before_returning(
    cycle_case, monkeypatch
):
    case = cycle_case
    claim = ClaimedJob(str(uuid4()), "synthetic-job-lease", reclaimed=False)
    entered = asyncio.Event()
    release_work = asyncio.Event()
    child_cancelled = asyncio.Event()
    release_cleanup = asyncio.Event()
    child_settled = asyncio.Event()
    child_tasks = []

    async def controlled_io(_claim):
        case.registry.assert_active()
        child_tasks.append(asyncio.current_task())
        entered.set()
        try:
            await release_work.wait()
        except asyncio.CancelledError:
            child_cancelled.set()
            await release_cleanup.wait()
            raise
        finally:
            child_settled.set()

    async def job_heartbeat(_model, _claim, stop_event):
        await stop_event.wait()

    async def owned_work():
        await case.worker._run_with_heartbeat(BackupRecord, claim, controlled_io)
        return True

    monkeypatch.setattr(case.worker, "_heartbeat_lease", job_heartbeat)
    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    task = asyncio.create_task(case.worker.run_once())
    try:
        await _wait(entered)
        task.cancel()
        await _wait(child_cancelled)
        assert not child_settled.is_set()
        assert not task.done()
        assert not case.registry.finishes

        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert child_settled.is_set()
        _assert_unresolved(case)
    finally:
        release_work.set()
        release_cleanup.set()
        await _settle_tasks(task, *child_tasks)


def _heartbeat_executor(tmp_path):
    config = Settings(
        SECRET_KEY="synthetic-backup-heartbeat-unit-key-32-characters",
        DATABASE_URL=(
            "postgresql+asyncpg://synthetic:unused@127.0.0.1:5432/heartbeat_test"
        ),
        BACKUP_DIR=str(tmp_path / "protected-backups"),
        BACKUP_WORKER_HEARTBEAT_SECONDS=10,
    )
    return BackupExecutor(config=config)


def test_existing_heartbeat_verification_never_creates_or_chmods(tmp_path, monkeypatch):
    executor = _heartbeat_executor(tmp_path)
    executor.write_heartbeat()
    heartbeat = executor._heartbeat_path
    original = heartbeat.stat()
    directory_mode = heartbeat.parent.stat().st_mode

    def forbidden_mutation(*_args, **_kwargs):
        raise AssertionError("heartbeat verification must be read-only")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "mkdir", forbidden_mutation)
        patch.setattr(Path, "chmod", forbidden_mutation)
        patch.setattr(executor_module.os, "mkdir", forbidden_mutation)
        patch.setattr(executor_module.os, "chmod", forbidden_mutation)
        executor.verify_heartbeat()

    current = heartbeat.stat()
    assert (current.st_ino, current.st_size, current.st_mtime_ns, current.st_mode) == (
        original.st_ino, original.st_size, original.st_mtime_ns, original.st_mode,
    )
    assert heartbeat.parent.stat().st_mode == directory_mode


def test_missing_heartbeat_directory_fails_without_creation(tmp_path, monkeypatch):
    executor = _heartbeat_executor(tmp_path)
    directory = tmp_path / "protected-backups"
    assert not directory.exists()

    def forbidden_mutation(*_args, **_kwargs):
        raise AssertionError("missing heartbeat must not initialize protected storage")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "mkdir", forbidden_mutation)
        patch.setattr(Path, "chmod", forbidden_mutation)
        patch.setattr(executor_module.os, "mkdir", forbidden_mutation)
        patch.setattr(executor_module.os, "chmod", forbidden_mutation)
        with pytest.raises(BackupExecutionError):
            executor.verify_heartbeat()

    assert not directory.exists()


@pytest.mark.asyncio
async def test_terminal_publication_cancels_and_settles_pending_lease_renewal(
    cycle_case, monkeypatch
):
    case = cycle_case
    claim = ClaimedJob(str(uuid4()), "synthetic-job-lease", reclaimed=False)
    renewal_started = asyncio.Event()
    terminal_published = asyncio.Event()
    renewal_waiting = asyncio.Event()
    release_renewal = asyncio.Event()
    renewal_cancelled = asyncio.Event()

    async def delayed_renewal(model, received):
        assert model is BackupRecord and received == claim
        case.registry.assert_active()
        renewal_started.set()
        try:
            await terminal_published.wait()
            renewal_waiting.set()
            # This SELECT is still pending after the job commits its terminal
            # state; completing it would now find the running lease cleared.
            await release_renewal.wait()
            raise LeaseLostError("synthetic lease cleared by terminal publication")
        except asyncio.CancelledError:
            renewal_cancelled.set()
            raise

    async def job_heartbeat(model, received, _stop_event):
        await case.worker._renew_lease(model, received)

    async def settled_operation(received):
        assert received == claim
        await renewal_started.wait()
        terminal_published.set()
        await renewal_waiting.wait()

    async def owned_work():
        await case.worker._run_with_heartbeat(
            BackupRecord, claim, settled_operation
        )
        assert renewal_cancelled.is_set()
        return True

    monkeypatch.setattr(case.worker, "_renew_lease", delayed_renewal)
    monkeypatch.setattr(case.worker, "_heartbeat_lease", job_heartbeat)
    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    task = asyncio.create_task(case.worker.run_once())
    try:
        assert await asyncio.wait_for(task, timeout=WAIT_SECONDS) is True
        assert terminal_published.is_set() and renewal_waiting.is_set()
        assert renewal_cancelled.is_set() and not release_renewal.is_set()
        assert case.registry.finishes == case.registry.owners
        assert not case.registry.states and not case.registry.marks
    finally:
        release_renewal.set()
        await _settle_tasks(task)


@pytest.mark.asyncio
async def test_terminal_operation_and_lease_lost_both_done_release_settled_cycle(
    cycle_case, monkeypatch
):
    case = cycle_case
    claim = ClaimedJob(str(uuid4()), "synthetic-job-lease", reclaimed=False)
    renewal_started = asyncio.Event()
    terminal_published = asyncio.Event()
    both_done_observed = asyncio.Event()
    original_wait = asyncio.wait

    async def terminal_operation(received):
        assert received == claim
        case.registry.assert_active()
        await renewal_started.wait()
        case.registry.events.append(("terminal-publication-committed",))
        terminal_published.set()

    async def terminal_heartbeat(_model, received, _stop_event):
        assert received == claim
        renewal_started.set()
        await terminal_published.wait()
        raise LeaseLostError("synthetic renewal observed the committed terminal state")

    async def wait_after_both_job_tasks_settle(futures, *args, **kwargs):
        members = set(futures)
        names = {task.get_coro().__name__ for task in members}
        if names == {"terminal_operation", "terminal_heartbeat"}:
            # Hold only the inner job waiter until both outcomes are available.
            # The outer registry heartbeat continues under the real waiter.
            await asyncio.gather(*members, return_exceptions=True)
            done, pending = await original_wait(members, *args, **kwargs)
            assert done == members and not pending
            both_done_observed.set()
            return done, pending
        return await original_wait(members, *args, **kwargs)

    async def owned_work():
        await case.worker._run_with_heartbeat(
            BackupRecord, claim, terminal_operation
        )
        return True

    monkeypatch.setattr(case.worker, "_heartbeat_lease", terminal_heartbeat)
    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    monkeypatch.setattr(asyncio, "wait", wait_after_both_job_tasks_settle)

    assert await asyncio.wait_for(
        case.worker.run_once(), timeout=WAIT_SECONDS
    ) is True
    assert both_done_observed.is_set() and terminal_published.is_set()
    assert case.registry.finishes == case.registry.owners
    assert not case.registry.states and not case.registry.marks
    finished_at = next(
        index for index, event in enumerate(case.registry.events)
        if event[0] == "finished"
    )
    assert case.registry.events.index(
        ("terminal-publication-committed",)
    ) < finished_at


@pytest.mark.asyncio
async def test_lease_failure_before_operation_completion_cancels_work_and_retains_cycle(
    cycle_case, monkeypatch
):
    case = cycle_case
    claim = ClaimedJob(str(uuid4()), "synthetic-job-lease", reclaimed=False)
    operation_started = asyncio.Event()
    release_operation = asyncio.Event()
    operation_cancelled = asyncio.Event()
    operation_settled = asyncio.Event()

    async def unfinished_operation(received):
        assert received == claim
        case.registry.assert_active()
        operation_started.set()
        try:
            await release_operation.wait()
        except asyncio.CancelledError:
            operation_cancelled.set()
            raise
        finally:
            operation_settled.set()

    async def failed_renewal(model, received):
        assert model is BackupRecord and received == claim
        await operation_started.wait()
        assert not operation_settled.is_set()
        raise LeaseLostError("synthetic lease failure while operation is running")

    async def job_heartbeat(model, received, _stop_event):
        await case.worker._renew_lease(model, received)

    async def owned_work():
        await case.worker._run_with_heartbeat(
            BackupRecord, claim, unfinished_operation
        )
        return True

    monkeypatch.setattr(case.worker, "_renew_lease", failed_renewal)
    monkeypatch.setattr(case.worker, "_heartbeat_lease", job_heartbeat)
    monkeypatch.setattr(case.worker, "_run_once_owned", owned_work)
    task = asyncio.create_task(case.worker.run_once())
    try:
        with pytest.raises(LeaseLostError, match="while operation is running"):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert operation_cancelled.is_set() and operation_settled.is_set()
        assert not release_operation.is_set()
        _assert_unresolved(case)
    finally:
        release_operation.set()
        await _settle_tasks(task)


@pytest.mark.asyncio
async def test_normal_stop_during_startup_settles_owner_without_starting_next_cycle(
    cycle_case, monkeypatch
):
    case = cycle_case
    stop_event = asyncio.Event()
    startup_entered = asyncio.Event()
    release_startup = asyncio.Event()
    startup_settled = asyncio.Event()
    next_cycle_attempts = []

    async def startup_operation():
        case.registry.assert_active()
        startup_entered.set()
        await release_startup.wait()
        startup_settled.set()
        return True

    async def forbidden_new_cycle():
        next_cycle_attempts.append("unexpected-run-once")
        raise AssertionError("normal stop after startup must not admit another cycle")

    monkeypatch.setattr(case.worker, "_startup_owned", startup_operation)
    monkeypatch.setattr(case.worker, "run_once", forbidden_new_cycle)
    task = asyncio.create_task(case.worker._process_forever(stop_event))
    try:
        await _wait(startup_entered)
        stop_event.set()
        assert not startup_settled.is_set() and not case.registry.finishes
        release_startup.set()
        await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert startup_settled.is_set() and case.worker._startup_complete
        assert not next_cycle_attempts
        assert len(case.registry.owners) == 1
        assert case.registry.finishes == case.registry.owners
        assert not case.registry.states and not case.registry.marks
    finally:
        release_startup.set()
        await _settle_tasks(task)
