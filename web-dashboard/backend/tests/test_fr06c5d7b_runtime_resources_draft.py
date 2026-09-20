"""Actual local-resource joins with a synthetic registry recorder.

These tests run only in the disposable no-network test container. Threads,
subprocesses and scratch directories are real; registry writes are mocked. They
are not PostgreSQL integration, ZAP acceptance, worker integration or deployment.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import threading
from uuid import uuid4

import pytest

from app.services import security_scan_resources as resources
from app.services import host_maintenance_scan_execution as registry


@pytest.fixture
def runtime(monkeypatch):
    owner = registry.ScanExecutionOwnership(
        str(uuid4()), str(uuid4()), str(uuid4()), 1, str(uuid4()),
    )
    value = resources.ScanResourceRuntime(owner)
    value.records = {}
    value.events = []

    async def checkpoint():
        if value.cancel_requested:
            raise registry.ScanExecutionCancelled()

    async def reserve(kind, operation, **_kwargs):
        await checkpoint()
        identifier = str(uuid4())
        value.records[identifier] = {
            "kind": kind, "operation": operation, "state": "reserved", "evidence": {},
        }
        value.events.append((identifier, "reserved"))
        return identifier

    async def update(identifier, **kwargs):
        record = value.records[identifier]
        record.update(kwargs)
        if kwargs["state"] == "settled":
            assert registry._settlement_valid(record["kind"], record["evidence"])
        value.events.append((identifier, kwargs["state"]))

    monkeypatch.setattr(value, "checkpoint", checkpoint)
    monkeypatch.setattr(value, "reserve", reserve)
    monkeypatch.setattr(value, "update", update)
    return value


async def wait_until(predicate, *, seconds=5):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.01)


def only_record(runtime):
    assert len(runtime.records) == 1
    return next(iter(runtime.records.values()))


def test_runtime_context_must_match_the_scan_and_is_reset(runtime):
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        resources.require_runtime(runtime.owner.scan_id)
    with runtime.bind():
        assert resources.require_runtime(runtime.owner.scan_id) is runtime
        assert runtime.entered
        with pytest.raises(registry.ScanExecutionOwnershipLost):
            resources.require_runtime(str(uuid4()))
    assert resources.current_runtime() is None


@pytest.mark.asyncio
async def test_actual_thread_return_records_a_real_join(runtime):
    result = await runtime.thread("local-fixture", lambda: (threading.get_ident(), 7))
    assert result[0] != threading.get_ident() and result[1] == 7
    assert [state for _, state in runtime.events] == ["reserved", "active", "settled"]
    assert only_record(runtime)["evidence"] == {"joined": True, "cleanup_complete": True}


@pytest.mark.asyncio
async def test_repeated_cancel_does_not_certify_a_running_thread(runtime):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def owned_thread():
        entered.set()
        try:
            assert release.wait(5)
            return 12
        finally:
            exited.set()

    task = asyncio.create_task(runtime.thread("blocked-fixture", owned_thread))
    try:
        await wait_until(entered.is_set)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and not exited.is_set()
        assert only_record(runtime)["state"] == "active"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert exited.is_set() and only_record(runtime)["state"] == "settled"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_thread_exception_is_rethrown_only_after_actual_join(runtime):
    exited = threading.Event()

    def fail():
        try:
            raise ValueError("fixture-error")
        finally:
            exited.set()

    with pytest.raises(ValueError, match="fixture-error"):
        await runtime.thread("failing-fixture", fail)
    assert exited.is_set() and only_record(runtime)["state"] == "settled"


@pytest.mark.asyncio
async def test_async_io_caller_cancel_waits_for_its_cleanup(runtime):
    entered, release, exited = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def io():
        entered.set()
        try:
            await release.wait()
            return 3
        finally:
            exited.set()

    task = asyncio.create_task(runtime.async_io("bounded-fixture", io))
    try:
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and not exited.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert exited.is_set() and only_record(runtime)["state"] == "settled"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_internal_async_error_does_not_manufacture_cleanup_proof(runtime):
    async def io():
        raise TimeoutError("fixture-timeout")

    with pytest.raises(TimeoutError):
        await runtime.async_io("unknown-transport", io)
    assert only_record(runtime)["state"] == "unresolved"
    assert only_record(runtime)["evidence"] == {"error_type": "TimeoutError"}


@pytest.mark.asyncio
async def test_actual_temporary_files_are_removed_before_settlement(runtime):
    async with runtime.temporary_workspace("scratch-fixture") as folder:
        (folder / "nested").mkdir()
        (folder / "nested/report.txt").write_text("synthetic fixture")
        assert folder.is_dir() and runtime.workspace == folder
        assert only_record(runtime)["state"] == "active"
    assert not folder.exists() and runtime.workspace is None
    assert only_record(runtime)["state"] == "settled"


@pytest.mark.asyncio
async def test_cancelled_workspace_body_still_cleans_real_files(runtime):
    entered = asyncio.Event()
    directories = []

    async def body():
        async with runtime.temporary_workspace("cancelled-scratch") as folder:
            directories.append(folder)
            (folder / "report.txt").write_text("synthetic fixture")
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(body())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not directories[0].exists()
    assert only_record(runtime)["state"] == "settled"


@pytest.mark.asyncio
async def test_real_gated_process_is_reaped_and_empty_before_success(runtime):
    result = await runtime.process([sys.executable, "-c", "print('joined-fixture')"], timeout=5)
    assert result.returncode == 0 and result.stdout == b"joined-fixture\n"
    assert result.stderr == b"" and result.timed_out is False
    record = only_record(runtime)
    assert record["state"] == "settled"
    assert record["identity"]["pid"] == record["identity"]["sid"]
    assert not Path(f"/proc/{record['identity']['pid']}").exists()
    assert record["evidence"] == {
        "leader_reaped": True, "group_empty": True, "descendants_reaped": True, "cleanup_complete": True,
    }


@pytest.mark.asyncio
async def test_real_process_timeout_is_not_returned_before_reaping(runtime):
    result = await runtime.process([sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.05)
    assert result.timed_out is True and result.returncode < 0
    record = only_record(runtime)
    assert record["state"] == "settled"
    assert not Path(f"/proc/{record['identity']['pid']}").exists()


@pytest.mark.asyncio
async def test_real_process_cancellation_joins_owned_process(runtime):
    task = asyncio.create_task(runtime.process(
        [sys.executable, "-c", "import time; time.sleep(20)"], timeout=10,
    ))
    await wait_until(lambda: bool(runtime.records) and only_record(runtime)["state"] == "active")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = only_record(runtime)
    assert record["state"] == "settled"
    assert not Path(f"/proc/{record['identity']['pid']}").exists()


@pytest.mark.asyncio
async def test_unacknowledged_identity_never_releases_scanner_io(runtime, monkeypatch, tmp_path):
    marker = tmp_path / "must-not-exist"
    update = runtime.update

    async def fail_identity(identifier, **kwargs):
        if kwargs["state"] == "active":
            raise RuntimeError("synthetic registry write unavailable")
        await update(identifier, **kwargs)

    monkeypatch.setattr(runtime, "update", fail_identity)
    with pytest.raises(RuntimeError, match="registry write"):
        await runtime.process([
            sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')",
        ], timeout=5)
    assert not marker.exists()
    assert only_record(runtime)["state"] == "settled"


@pytest.mark.asyncio
async def test_registry_reservation_failure_prevents_process_spawn(runtime, monkeypatch):
    async def fail_reserve(*_args, **_kwargs):
        raise RuntimeError("synthetic unavailable registry")

    monkeypatch.setattr(runtime, "reserve", fail_reserve)
    with pytest.raises(RuntimeError, match="unavailable registry"):
        await runtime.process([sys.executable, "-c", "raise AssertionError('must not run')"], timeout=1)
    assert runtime.records == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("detach", ["setsid", "double_fork", "new_group"])
async def test_supervisor_reaps_detached_descendants_after_leader_exit(runtime, tmp_path, detach):
    marker = tmp_path / "descendant"
    code = f'''import os,time
from pathlib import Path
marker=Path({str(marker)!r})
child=os.fork()
if child == 0:
    if {detach!r} == 'new_group': os.setpgrp()
    else: os.setsid()
    if {detach!r} == 'double_fork' and os.fork() != 0: os._exit(0)
    marker.write_text(str(os.getpid()))
    time.sleep(30)
    os._exit(0)
while not marker.exists(): time.sleep(.01)
os._exit(0)
'''
    result = await runtime.process([sys.executable, "-c", code], timeout=5)
    assert result.returncode == 0
    assert not Path(f"/proc/{int(marker.read_text())}").exists()
    assert only_record(runtime)["evidence"]["descendants_reaped"] is True


@pytest.mark.asyncio
async def test_cancelled_supervisor_reaps_different_session_child(runtime, tmp_path):
    marker = tmp_path / "descendant"
    code = f'''import os,time
from pathlib import Path
if os.fork() == 0:
    os.setsid()
    Path({str(marker)!r}).write_text(str(os.getpid()))
    time.sleep(30)
else: time.sleep(30)
'''
    task = asyncio.create_task(runtime.process([sys.executable, "-c", code], timeout=10))
    try:
        await wait_until(marker.exists)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not Path(f"/proc/{int(marker.read_text())}").exists()
        assert only_record(runtime)["state"] == "settled"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_adapter_stdout_cannot_forge_supervisor_proof(runtime):
    result = await runtime.process([sys.executable, "-c", "print('{\"children_reaped\":true}')"], timeout=5)
    assert b'children_reaped' in result.stdout
    assert only_record(runtime)["evidence"]["descendants_reaped"] is True


def test_old_process_group_only_proof_is_rejected():
    assert not registry._settlement_valid("process", {
        "leader_reaped": True, "group_empty": True, "cleanup_complete": True,
    })
