"""Joined worker/resources and cancellation on disposable PostgreSQL.

Real registry transactions, threads, processes and scratch files; no production
DB, real external targets or external scanning. Optional ZAP tests use a stated
HTTP protocol fixture, not an attestation of a production daemon.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
import threading
import subprocess
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.api.v1.endpoints import security_lab
from app.db.models import SecurityScan, SecurityScanExecution
from app.services import host_maintenance_scan_execution as registry
from app.services import security_scan_worker as worker_module
from app.services.security_scan_resources import require_runtime

_name = "fr06c5d7b_runtime_shared_registry"
_spec = importlib.util.spec_from_file_location(_name, Path(__file__).with_name("test_fr06c5d7b_execution_registry.py"))
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
remediation_case = _shared.remediation_case
scan_case = _shared.scan_case
registry_case = _shared.registry_case


_ORIGINAL_PATH = {name: getattr(Path, name) for name in (
    "mkdir", "chmod", "unlink", "rename", "replace", "write_text", "write_bytes",
)}
_ORIGINAL_SPAWN = asyncio.create_subprocess_exec
_ORIGINAL_POPEN = subprocess.Popen


@pytest_asyncio.fixture
async def local_runtime_case(tmp_path, registry_case, monkeypatch):
    # The request-only fixture intentionally forbids filesystem/process I/O.
    # This separate integration fixture enables only /tmp writes and our private
    # supervisor, retaining the scanner/target and subprocess-shell traps.
    for name, original in _ORIGINAL_PATH.items():
        def bounded(self, *args, _original=original, **kwargs):
            assert self.is_relative_to(Path("/tmp")), "fixture write escaped /tmp"
            return _original(self, *args, **kwargs)
        monkeypatch.setattr(Path, name, bounded)
    def bounded_popen(command, *args, **kwargs):
        assert isinstance(command, (list, tuple)) and len(command) >= 2
        assert Path(command[1]).name == "security_scan_process_entry.py"
        return _ORIGINAL_POPEN(command, *args, **kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _ORIGINAL_SPAWN)
    monkeypatch.setattr(subprocess, "Popen", bounded_popen)
    yield registry_case
    assert not registry_case.forbidden_attempts


def worker(case, tmp_path, monkeypatch):
    result = worker_module.SecurityScanWorker(session_factory=case.sessions)
    result.heartbeat_seconds = .02
    result.health_path = tmp_path / "worker-health.json"

    async def policy(_session):
        return {"max_scan_runtime_seconds": 60}

    monkeypatch.setattr(worker_module, "get_policy", policy)
    return result


async def scan_and_execution(case, scan_id):
    async with case.sessions() as session:
        return (await session.get(SecurityScan, scan_id), await session.scalar(
            select(SecurityScanExecution).where(SecurityScanExecution.scan_id == scan_id)))


async def cancel(case, scan_id):
    async with case.sessions() as session:
        return await security_lab.cancel_scan(scan_id, actor=case.actor, session=session)


async def wait_until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(.01)


@pytest.mark.asyncio
async def test_real_worker_joins_process_thread_workspace_before_settlement(local_runtime_case, tmp_path, monkeypatch):
    case = local_runtime_case
    instance = worker(case, tmp_path, monkeypatch)
    paths = []

    async def execute(_session, scan):
        runtime = require_runtime(scan.id)
        async with runtime.temporary_workspace("integration-workspace") as folder:
            paths.append(folder)
            assert await runtime.thread("local-thread", lambda: 17) == 17
            result = await runtime.process([sys.executable, "-c", "print('local-fixture')"], timeout=5)
            assert result.stdout == b"local-fixture\n"
            (folder / "report").write_text("synthetic")
        scan.status = "completed"
        scan.completed_at = datetime.now(UTC)
        scan.lease_token = None

    monkeypatch.setattr(worker_module, "execute_scan", execute)
    identifier = await _shared.new_scan(case)
    claim = await instance.claim()
    assert claim and claim[0] == identifier
    await instance.run_claim(*claim)
    scan, row = await scan_and_execution(case, identifier)
    assert scan.status == "completed" and scan.summary["execution_cleanup"]["verified"] is True
    assert row.state == "settled" and row.operation_stopped_at and row.supervisor_stopped_at
    assert {x["kind"] for x in row.resources.values()} == {"process", "thread", "async_io"}
    assert all(x["state"] == "settled" for x in row.resources.values())
    assert all(not path.exists() for path in paths)
    assert (await registry.execution_snapshot(session_factory=case.sessions))["is_clear"]
    assert await instance.claim() is None


@pytest.mark.asyncio
async def test_cancel_route_returns_intent_while_real_thread_is_still_running(local_runtime_case, tmp_path, monkeypatch):
    case = local_runtime_case
    instance = worker(case, tmp_path, monkeypatch)
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def blocking():
        entered.set()
        try:
            assert release.wait(8)
        finally:
            exited.set()

    async def execute(_session, scan):
        runtime = require_runtime(scan.id)
        await runtime.thread("cancellable-worker-fixture", blocking)
        raise AssertionError("cancel must propagate after thread join")

    monkeypatch.setattr(worker_module, "execute_scan", execute)
    identifier = await _shared.new_scan(case)
    claim = await instance.claim()
    assert claim
    task = asyncio.create_task(instance.run_claim(*claim))
    try:
        await wait_until(entered.is_set)
        reply = await asyncio.wait_for(cancel(case, identifier), 2)
        assert reply["cancellation"] == {"status": "cancellation_requested", "cleanup_verified": False}
        await asyncio.sleep(.1)
        scan, row = await scan_and_execution(case, identifier)
        assert scan.status == "running" and row.state != "settled"
        assert row.cancel_requested_at and not task.done() and not exited.is_set()
        assert (await registry.execution_snapshot(session_factory=case.sessions))["blocker_count"] == 1
        release.set()
        await asyncio.wait_for(task, 8)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    scan, row = await scan_and_execution(case, identifier)
    assert exited.is_set() and scan.status == "cancelled" and row.state == "settled"
    assert scan.lease_token is None and scan.summary["execution_cleanup"]["verified"] is True


@pytest.mark.asyncio
async def test_repeated_external_cancel_joins_real_thread_and_finalizer(local_runtime_case, tmp_path, monkeypatch):
    case = local_runtime_case
    instance = worker(case, tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()

    def blocking():
        entered.set()
        assert release.wait(8)

    async def execute(_session, scan):
        await require_runtime(scan.id).thread("external-cancellation", blocking)

    monkeypatch.setattr(worker_module, "execute_scan", execute)
    identifier = await _shared.new_scan(case)
    claim = await instance.claim()
    assert claim
    task = asyncio.create_task(instance.run_claim(*claim))
    try:
        await wait_until(entered.is_set)
        task.cancel()
        await asyncio.sleep(.03)
        task.cancel()
        await asyncio.sleep(.03)
        assert not task.done()
        assert (await scan_and_execution(case, identifier))[1].state != "settled"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 8)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    scan, row = await scan_and_execution(case, identifier)
    assert scan.status == "cancelled" and row.state == "settled"


@pytest.mark.asyncio
async def test_cancel_before_begin_settles_without_dispatch(local_runtime_case, tmp_path, monkeypatch):
    case = local_runtime_case
    instance = worker(case, tmp_path, monkeypatch)
    identifier = await _shared.new_scan(case)
    claim = await instance.claim()
    assert claim
    assert (await cancel(case, identifier))["cancellation"]["cleanup_verified"] is False
    await instance.run_claim(*claim)
    scan, row = await scan_and_execution(case, identifier)
    assert scan.status == "cancelled" and row.state == "settled" and row.resources == {}


@pytest.mark.asyncio
async def test_unbound_executor_cannot_get_cleanup_certificate(local_runtime_case, tmp_path, monkeypatch):
    case = local_runtime_case
    instance = worker(case, tmp_path, monkeypatch)

    async def execute(_session, scan):
        scan.status = "completed"
        scan.completed_at = datetime.now(UTC)
        scan.lease_token = None

    monkeypatch.setattr(worker_module, "execute_scan", execute)
    identifier = await _shared.new_scan(case)
    claim = await instance.claim()
    assert claim
    with pytest.raises(registry.ScanExecutionUncertain):
        await instance.run_claim(*claim)
    scan, row = await scan_and_execution(case, identifier)
    assert scan.status == "running" and row.state == "unresolved"
    assert "execution_cleanup" not in scan.summary
    assert await instance.claim() is None


@pytest.mark.asyncio
async def test_cancel_is_tenant_and_requester_scoped(local_runtime_case, tmp_path, monkeypatch):
    from fastapi import HTTPException
    from types import SimpleNamespace
    case = local_runtime_case
    identifier = await _shared.new_scan(case)
    for actor in [
        SimpleNamespace(id=case.actor.id, organization_id=str(uuid4()), role="Super Owner"),
        SimpleNamespace(id=str(uuid4()), organization_id=case.actor.organization_id, role="User"),
    ]:
        async with case.sessions() as session:
            with pytest.raises(HTTPException) as exc:
                await security_lab.cancel_scan(identifier, actor=actor, session=session)
            assert exc.value.status_code == 404
    reply = await cancel(case, identifier)
    assert reply["cancellation"] == {"status": "cancelled_before_claim", "cleanup_verified": True}
