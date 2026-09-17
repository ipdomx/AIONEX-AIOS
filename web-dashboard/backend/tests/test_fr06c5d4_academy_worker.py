"""Real Academy worker ownership with controlled local filesystem work.

The shared fixture owns a disposable PostgreSQL schema. Only the course builder
is fake; its files are created below tmp_path and every subprocess is forbidden.
Thread barriers observe real publication and strict-cleanup boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError

from aios.course_factory import CourseFactoryRequest, CoursePackageResult
from app.db.models import AcademyCoursePackage, HostMaintenanceWorkCycle
from app.services import academy_course_worker as worker
from app.services import host_maintenance_academy as activities
from app.services.host_maintenance_admission import close_admission
from tests.test_fr06c5d4_academy_runtime_database import (
    academy_case as academy_case,
    create_queued_package,
    reject_activity_insert_at_commit,
)


WAIT_SECONDS = 10
HEARTBEAT_INTERVAL = 0.05


class SyntheticBuildFailure(RuntimeError):
    pass


class ThreadBarrier:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self):
        self.entered.set()
        if not self.release.wait(WAIT_SECONDS):
            raise RuntimeError("synthetic Academy barrier timed out")


class ControlledBuilder:
    def __init__(self):
        self.barrier = None
        self.failure = None
        self.calls = []
        self.staging = None
        self.loop_thread_id = threading.get_ident()

    def __call__(self, request, destination):
        assert isinstance(request, CourseFactoryRequest)
        assert isinstance(destination, Path)
        assert threading.get_ident() != self.loop_thread_id
        self.calls.append((request, destination))
        self.staging = destination.parent
        if self.barrier is not None:
            self.barrier.wait()
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "index.html").write_text("synthetic Academy page", encoding="utf-8")
        if self.failure is not None:
            raise self.failure
        curriculum = {
            "lesson_count": 1,
            "lessons": [{"key": "m01l01", "ordinal": 1, "module": 1}],
        }
        (destination / "curriculum.json").write_text(
            json.dumps(curriculum), encoding="utf-8"
        )
        manifest = b'{"schema":"synthetic-academy-package"}'
        (destination / "manifest.json").write_bytes(manifest)
        archive = destination.parent / f"{request.course_id}-v1.zip"
        with zipfile.ZipFile(archive, "w") as package:
            for path in sorted(destination.iterdir()):
                package.write(path, path.name)
        raw = archive.read_bytes()
        return CoursePackageResult(
            course_id=request.course_id,
            archive_path=archive,
            archive_sha256=hashlib.sha256(raw).hexdigest(),
            archive_bytes=len(raw),
            manifest_sha256=hashlib.sha256(manifest).hexdigest(),
            lesson_count=1,
            locales=("en",),
            artifacts=(),
        )


@pytest_asyncio.fixture
async def worker_case(academy_case, tmp_path, monkeypatch):
    package_id = await create_queued_package(academy_case)
    async with academy_case.sessions() as session:
        package = await session.get(AcademyCoursePackage, package_id)
        assert package is not None
        organization_id, course_id, version = (
            package.organization_id, package.course_id, package.version
        )
    root = tmp_path / "academy-packages"
    case = SimpleNamespace(
        database=academy_case,
        sessions=academy_case.sessions,
        package_id=package_id,
        root=root,
        builder=ControlledBuilder(),
        final_dir=root / organization_id / course_id / f"v{version}",
        archive_target=root / organization_id / course_id / f"course-v{version}.zip",
        helper_entered=threading.Event(),
        helper_settled=threading.Event(),
        stop_event=None,
        build_input=None,
        barriers=[],
        forbidden_calls=[],
    )
    actual_helper = worker._build_publish_cleanup

    def observed_helper(build, stop_event, *, builder):
        case.stop_event = stop_event
        case.build_input = build
        case.helper_entered.set()
        try:
            return actual_helper(build, stop_event, builder=builder)
        finally:
            case.helper_settled.set()

    def forbidden_subprocess(*_args, **_kwargs):
        case.forbidden_calls.append("subprocess")
        raise AssertionError("Academy worker tests must not execute FFmpeg or providers")

    async def forbidden_async_subprocess(*_args, **_kwargs):
        forbidden_subprocess()

    monkeypatch.setattr(worker, "_build_publish_cleanup", observed_helper)
    monkeypatch.setattr(subprocess, "run", forbidden_subprocess)
    monkeypatch.setattr(subprocess, "Popen", forbidden_subprocess)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_async_subprocess)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_async_subprocess)
    try:
        yield case
    finally:
        for barrier in case.barriers:
            barrier.release.set()


async def _wait_thread(event):
    async with asyncio.timeout(WAIT_SECONDS):
        while not event.is_set():
            await asyncio.sleep(0.005)


async def _settle(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True), timeout=WAIT_SECONDS
        )


def _build_barrier(case):
    barrier = ThreadBarrier()
    case.barriers.append(barrier)
    case.builder.barrier = barrier
    return barrier


async def _state(case):
    async with case.sessions() as session:
        package = await session.get(AcademyCoursePackage, case.package_id)
        owners = list(
            (
                await session.scalars(
                    select(HostMaintenanceWorkCycle).where(
                        HostMaintenanceWorkCycle.consumer == activities.CONSUMER
                    )
                )
            ).all()
        )
        assert package is not None
        return package, owners


async def _run(case):
    return await worker.run_once(
        session_factory=case.sessions,
        root=case.root,
        builder=case.builder,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )


async def _assert_unresolved(case):
    package, owners = await _state(case)
    assert len(owners) == 1 and owners[0].state == "unresolved"
    assert owners[0].unresolved_reason
    assert package.status != "review_pending"
    assert not case.forbidden_calls
    return package, owners[0]


@pytest.mark.asyncio
async def test_closed_default_worker_does_not_enter_builder_or_initialize_storage(worker_case):
    case = worker_case
    await close_admission(
        operation_id=case.database.operation_id,
        expected_generation=case.database.generation,
        reason="synthetic-academy-worker-close",
        session_factory=case.sessions,
    )
    assert await _run(case) is False
    package, owners = await _state(case)
    assert package.status == "queued" and owners == []
    assert not case.builder.calls and not case.helper_entered.is_set()
    assert not case.root.exists() and not case.forbidden_calls


@pytest.mark.asyncio
async def test_activity_registration_commit_failure_starts_no_worker_io(worker_case):
    case = worker_case
    await reject_activity_insert_at_commit(case.database)
    with pytest.raises(SQLAlchemyError):
        await _run(case)
    package, owners = await _state(case)
    assert package.status == "queued" and owners == []
    assert not case.builder.calls and not case.helper_entered.is_set()
    assert not case.root.exists() and not case.forbidden_calls


@pytest.mark.asyncio
async def test_real_activity_is_durable_before_build_and_heartbeats_complete_after_close(
    worker_case,
):
    case = worker_case
    barrier = _build_barrier(case)
    task = asyncio.create_task(_run(case))
    try:
        await _wait_thread(barrier.entered)
        package, owners = await _state(case)
        assert package.status == "building"
        assert len(owners) == 1 and owners[0].state == "active"
        activity_id = owners[0].id
        assert case.builder.staging == case.root / ".tmp" / activity_id
        await close_admission(
            operation_id=case.database.operation_id,
            expected_generation=case.database.generation,
            reason="synthetic-close-existing-academy-owner",
            session_factory=case.sessions,
        )
        _, at_close = await _state(case)
        previous_heartbeat = at_close[0].heartbeat_at
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                _, current = await _state(case)
                assert len(current) == 1 and current[0].id == activity_id
                if current[0].heartbeat_at > previous_heartbeat:
                    break
                await asyncio.sleep(0.01)
        assert not task.done() and not case.helper_settled.is_set()
        barrier.release.set()
        assert await asyncio.wait_for(task, timeout=WAIT_SECONDS) is True
        package, owners = await _state(case)
        assert owners == [] and package.status == "review_pending"
        assert case.helper_settled.is_set()
        assert case.final_dir.is_dir() and case.archive_target.is_file()
        assert package.archive_sha256 == hashlib.sha256(
            case.archive_target.read_bytes()
        ).hexdigest()
        assert not case.builder.staging.exists()
        assert not case.forbidden_calls
    finally:
        barrier.release.set()
        await _settle(task)


@pytest.mark.asyncio
async def test_settled_ordinary_build_failure_commits_failure_and_releases_activity(worker_case):
    case = worker_case
    case.builder.failure = SyntheticBuildFailure("synthetic private build detail")
    assert await _run(case) is True
    package, owners = await _state(case)
    assert package.status == "failed" and owners == []
    assert package.error_code == "course_build_failed"
    assert "synthetic private build detail" not in (package.error_message or "")
    assert case.helper_settled.is_set()
    assert not case.builder.staging.exists()
    assert not case.final_dir.exists() and not case.archive_target.exists()
    assert not case.forbidden_calls


def _phase_barrier(case, monkeypatch, phase):
    if phase == "build":
        return _build_barrier(case)
    barrier = ThreadBarrier()
    case.barriers.append(barrier)
    if phase == "site-publication":
        actual_replace = worker._publish_noreplace

        def wait_before_site_publication(source, destination, *args, **kwargs):
            if Path(destination) == case.final_dir:
                barrier.wait()
            return actual_replace(source, destination, *args, **kwargs)

        monkeypatch.setattr(worker, "_publish_noreplace", wait_before_site_publication)
    else:
        assert phase == "cleanup"
        actual_cleanup = worker._cleanup_owned_stage

        def wait_before_stage_cleanup(stage, parent_fd, stage_fd, identity):
            if case.builder.staging is not None and stage == case.builder.staging:
                barrier.wait()
            return actual_cleanup(stage, parent_fd, stage_fd, identity)

        monkeypatch.setattr(worker, "_cleanup_owned_stage", wait_before_stage_cleanup)
    return barrier


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["build", "site-publication", "cleanup"])
@pytest.mark.parametrize("repeat_cancel", [False, True], ids=["cancel", "repeated-cancel"])
async def test_cancellation_joins_actual_filesystem_work_and_retains_unresolved_owner(
    worker_case, monkeypatch, phase, repeat_cancel
):
    case = worker_case
    barrier = _phase_barrier(case, monkeypatch, phase)
    task = asyncio.create_task(_run(case))
    try:
        await _wait_thread(barrier.entered)
        task.cancel()
        assert case.stop_event is not None
        await _wait_thread(case.stop_event)
        assert not case.helper_settled.is_set()
        assert not task.done()
        _, retained = await _state(case)
        assert len(retained) == 1
        if repeat_cancel:
            task.cancel()
        barrier.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert case.helper_settled.is_set()
        package, _ = await _assert_unresolved(case)
        assert package.status == "building"
        assert package.site_relpath is None and package.archive_relpath is None
        assert not case.builder.staging.exists()
        # Cancellation cannot undo an OS operation already entered. Published
        # effects remain explicit and unresolved instead of being overwritten.
        assert case.final_dir.exists() is (phase != "build")
        assert case.archive_target.exists() is (phase == "cleanup")
    finally:
        barrier.release.set()
        await _settle(task)


@pytest.mark.asyncio
async def test_heartbeat_failure_retains_owner_and_waits_for_real_builder_settlement(
    worker_case, monkeypatch
):
    case = worker_case
    barrier = _build_barrier(case)
    heartbeat_failed = asyncio.Event()

    async def fail_heartbeat(_ownership, *, phase=None, session_factory):
        assert session_factory is case.sessions
        await _wait_thread(barrier.entered)
        heartbeat_failed.set()
        raise SQLAlchemyError("synthetic Academy heartbeat failure")

    monkeypatch.setattr(activities, "heartbeat_academy_activity", fail_heartbeat)
    task = asyncio.create_task(_run(case))
    try:
        await asyncio.wait_for(heartbeat_failed.wait(), timeout=WAIT_SECONDS)
        assert case.stop_event is not None
        await _wait_thread(case.stop_event)
        assert not task.done() and not case.helper_settled.is_set()
        barrier.release.set()
        with pytest.raises(SQLAlchemyError, match="synthetic Academy heartbeat failure"):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert case.helper_settled.is_set()
        package, _ = await _assert_unresolved(case)
        assert package.status == "building"
        assert not case.final_dir.exists() and not case.archive_target.exists()
        assert not case.builder.staging.exists()
    finally:
        barrier.release.set()
        await _settle(task)


@pytest.mark.asyncio
async def test_strict_cleanup_failure_keeps_published_work_unresolved(worker_case, monkeypatch):
    case = worker_case
    cleanup_attempts = []
    actual_cleanup = worker._cleanup_owned_stage

    def reject_owned_stage_cleanup(stage, parent_fd, stage_fd, identity):
        if case.builder.staging is not None and stage == case.builder.staging:
            cleanup_attempts.append(stage)
            raise OSError("synthetic Academy cleanup failure")
        return actual_cleanup(stage, parent_fd, stage_fd, identity)

    monkeypatch.setattr(worker, "_cleanup_owned_stage", reject_owned_stage_cleanup)
    with pytest.raises(worker.AcademyWorkUnresolved) as failure:
        await _run(case)
    assert failure.value.reason == "academy-cleanup-incomplete"
    package, _ = await _assert_unresolved(case)
    assert cleanup_attempts == [case.builder.staging]
    assert case.helper_settled.is_set() and case.builder.staging.is_dir()
    assert case.final_dir.is_dir() and case.archive_target.is_file()
    assert package.site_relpath is None and package.archive_relpath is None


@pytest.mark.asyncio
async def test_archive_publication_failure_keeps_partial_site_unresolved(
    worker_case, monkeypatch
):
    case = worker_case
    archive_attempts = []
    actual_replace = worker._publish_noreplace

    def reject_archive_publication(source, destination, *args, **kwargs):
        if Path(destination) == case.archive_target:
            archive_attempts.append(Path(destination))
            raise OSError("synthetic Academy archive publication failure")
        return actual_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(worker, "_publish_noreplace", reject_archive_publication)
    with pytest.raises(worker.AcademyWorkUnresolved) as failure:
        await _run(case)
    assert failure.value.reason == "academy-publication-incomplete"
    package, _ = await _assert_unresolved(case)
    assert archive_attempts == [case.archive_target]
    assert case.final_dir.is_dir() and not case.archive_target.exists()
    assert not case.builder.staging.exists() and case.helper_settled.is_set()
    assert package.site_relpath is None and package.archive_relpath is None


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["site", "archive"])
async def test_existing_publication_is_preserved_without_rebuild_or_overwrite(
    worker_case, existing
):
    case = worker_case
    if existing == "site":
        case.final_dir.mkdir(parents=True)
        sentinel = case.final_dir / "preserved.txt"
    else:
        case.archive_target.parent.mkdir(parents=True)
        sentinel = case.archive_target
    sentinel.write_bytes(b"synthetic preexisting artifact")
    before = sentinel.stat()
    with pytest.raises(worker.AcademyWorkUnresolved) as failure:
        await _run(case)
    assert failure.value.reason == "academy-existing-publication"
    await _assert_unresolved(case)
    after = sentinel.stat()
    assert sentinel.read_bytes() == b"synthetic preexisting artifact"
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_ino, before.st_size, before.st_mtime_ns
    )
    assert not case.builder.calls and case.helper_settled.is_set()


async def _reject_terminal_package_commit(case):
    async with case.sessions() as session:
        await session.execute(
            text(
                """
                CREATE FUNCTION fr06c5d4_reject_terminal_commit()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.status IN ('review_pending', 'failed') THEN
                        RAISE EXCEPTION 'synthetic Academy terminal commit rejected'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END
                $$
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE CONSTRAINT TRIGGER fr06c5d4_reject_terminal_commit
                AFTER UPDATE ON academy_course_packages
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION fr06c5d4_reject_terminal_commit()
                """
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_terminal_database_commit_failure_preserves_owner_and_published_files(worker_case):
    case = worker_case
    await _reject_terminal_package_commit(case)
    with pytest.raises(SQLAlchemyError):
        await _run(case)
    package, _ = await _assert_unresolved(case)
    assert case.helper_settled.is_set()
    assert package.status == "building"
    assert package.site_relpath is None and package.archive_relpath is None
    assert case.final_dir.is_dir() and case.archive_target.is_file()
    assert not case.builder.staging.exists()


@pytest.mark.asyncio
async def test_claim_commit_response_failure_keeps_committed_owner_before_any_io(
    worker_case,
):
    case = worker_case
    first_session = None

    def lose_commit_response(_session):
        raise SQLAlchemyError("synthetic Academy claim commit response lost")

    def sessions_with_lost_first_commit_response():
        nonlocal first_session
        session = case.sessions()
        if first_session is None:
            first_session = session
            # This callback runs after the real database COMMIT. The later
            # independent uncertainty transaction uses a fresh unaffected session.
            event.listen(
                session.sync_session, "after_commit", lose_commit_response, once=True
            )
        return session

    try:
        with pytest.raises(SQLAlchemyError, match="claim commit response lost"):
            await worker.run_once(
                session_factory=sessions_with_lost_first_commit_response,
                root=case.root,
                builder=case.builder,
                heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
            )
        package, _ = await _assert_unresolved(case)
        assert package.status == "building"
        assert not case.builder.calls and not case.helper_entered.is_set()
        assert not case.root.exists()
    finally:
        if first_session is not None and event.contains(
            first_session.sync_session, "after_commit", lose_commit_response
        ):
            event.remove(
                first_session.sync_session, "after_commit", lose_commit_response
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ["empty-site", "foreign-archive"])
async def test_atomic_publication_collision_preserves_foreign_destination_and_owner(
    worker_case, monkeypatch, collision
):
    case = worker_case
    target = case.final_dir if collision == "empty-site" else case.archive_target
    collisions = []
    actual_publish = worker._publish_noreplace

    def create_collision_before_atomic_publish(source, destination):
        if Path(destination) == target:
            assert not target.exists()
            if collision == "empty-site":
                target.mkdir()
            else:
                target.write_bytes(b"synthetic foreign archive")
            collisions.append(target.stat())
        return actual_publish(source, destination)

    monkeypatch.setattr(worker, "_publish_noreplace", create_collision_before_atomic_publish)
    with pytest.raises(worker.AcademyWorkUnresolved) as failure:
        await _run(case)
    assert failure.value.reason == "academy-existing-publication"
    package, _ = await _assert_unresolved(case)
    assert len(collisions) == 1 and target.stat().st_ino == collisions[0].st_ino
    if collision == "empty-site":
        assert target.is_dir() and list(target.iterdir()) == []
        assert not case.archive_target.exists()
    else:
        assert target.read_bytes() == b"synthetic foreign archive"
        assert case.final_dir.is_dir()
    assert case.helper_settled.is_set() and not case.builder.staging.exists()
    assert package.site_relpath is None and package.archive_relpath is None


@pytest.mark.asyncio
async def test_closed_real_worker_poll_keeps_health_healthy_without_package_io(
    worker_case, monkeypatch
):
    case = worker_case
    await close_admission(
        operation_id=case.database.operation_id,
        expected_generation=case.database.generation,
        reason="synthetic-closed-academy-poll",
        session_factory=case.sessions,
    )
    health = case.root / ".worker-health.json"
    monkeypatch.setattr(worker, "ROOT", case.root)
    monkeypatch.setattr(worker, "HEALTH", health)
    actual_sleep = asyncio.sleep
    completed_polls = []

    def forbidden_default_builder(_request, _destination):
        case.forbidden_calls.append("default-builder")
        raise AssertionError("closed polling must not enter the default builder")

    async def stop_after_closed_poll(delay, *args, **kwargs):
        if delay == 2:
            data = json.loads(health.read_text(encoding="utf-8"))
            assert data["status"] == "healthy"
            assert data["cycles"] == 1 and data["errors"] == 0
            completed_polls.append(data)
            raise asyncio.CancelledError
        return await actual_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(worker, "_default_builder", forbidden_default_builder)
    monkeypatch.setattr(asyncio, "sleep", stop_after_closed_poll)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(worker.loop(), timeout=WAIT_SECONDS)
    package, owners = await _state(case)
    assert len(completed_polls) == 1
    assert package.status == "queued" and owners == []
    assert health.is_file()
    assert not (case.root / ".tmp").exists()
    assert not case.final_dir.exists() and not case.archive_target.exists()
    assert not case.helper_entered.is_set() and not case.forbidden_calls


@pytest.mark.asyncio
async def test_cleanup_substitution_preserves_foreign_tree_and_retains_owner(
    worker_case, monkeypatch
):
    case = worker_case
    substitutions = []
    actual_traversal = worker._remove_directory_contents

    def substitute_stage_after_validation(directory_fd):
        if not substitutions:
            stage = case.builder.staging
            assert stage is not None and stage.is_dir()
            descriptor = os.fstat(directory_fd)
            original = stage.stat()
            assert (descriptor.st_dev, descriptor.st_ino) == (
                original.st_dev, original.st_ino
            )
            # The cleanup helper already validated the open root descriptor.
            # Retain an owned file so the test proves traversal still reaches
            # that original directory after its path is replaced.
            residue = stage / "owned-cleanup-residue.txt"
            residue.write_bytes(b"synthetic owned cleanup residue")
            displaced = stage.with_name(stage.name + "-displaced")
            os.rename(stage, displaced)
            stage.mkdir()
            sentinel = stage / "foreign-sentinel.txt"
            sentinel.write_bytes(b"synthetic foreign staging data")
            substitutions.append((displaced, sentinel, sentinel.stat().st_ino))
        # Traverse the real open descriptor; never substitute a fake cleanup.
        return actual_traversal(directory_fd)

    monkeypatch.setattr(
        worker, "_remove_directory_contents", substitute_stage_after_validation
    )
    with pytest.raises(worker.AcademyWorkUnresolved) as failure:
        await _run(case)
    assert failure.value.reason == "academy-cleanup-incomplete"
    package, _ = await _assert_unresolved(case)
    assert len(substitutions) == 1
    displaced, sentinel, sentinel_inode = substitutions[0]
    assert sentinel.is_file() and sentinel.stat().st_ino == sentinel_inode
    assert sentinel.read_bytes() == b"synthetic foreign staging data"
    assert not (displaced / "owned-cleanup-residue.txt").exists()
    assert case.helper_settled.is_set()
    assert package.status == "building"
    assert package.site_relpath is None and package.archive_relpath is None
    assert case.final_dir.is_dir() and case.archive_target.is_file()
