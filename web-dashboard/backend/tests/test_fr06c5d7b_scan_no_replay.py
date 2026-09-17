"""PostgreSQL one-shot scan-start and conservative interruption contracts.

These tests use UUID schemas in the disposable-only D7 request fixture. No real
scanner, external target, subprocess, thread or ZAP job is run. They establish
no-replay safety, not complete resource cleanup or full-host drain coverage.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import SecurityScan
from app.services import security_scan_worker as worker_module
from app.services.host_maintenance_admission import HostMaintenanceClosed, HostMaintenanceUnavailable


_name = "fr06c5d7b_replay_shared_request"
_spec = importlib.util.spec_from_file_location(
    _name, Path(__file__).with_name("test_fr06c5d7_scan_request_admission.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
remediation_case = _shared.remediation_case
scan_case = _shared.scan_case
WAIT = 8


def _guard(phase="claimed", **changes):
    return {"protocol_version": 1, "phase": phase, "cleanup_verified": False, **changes}


@pytest.mark.parametrize("guard", [
    None, [], "claimed", {},
    _guard(protocol_version=True), _guard(protocol_version="1"),
    _guard(protocol_version=2), _guard(cleanup_verified=True),
    _guard(cleanup_verified=0), _guard(phase="done"), _guard(phase=[]),
    _guard(extra="untrusted"),
])
def test_malformed_guard_never_authorizes_start(guard):
    scan = SecurityScan(summary={worker_module.GUARD_KEY: guard})
    assert worker_module._execution_phase(scan) is None


@pytest.mark.parametrize("phase", ["claimed", "executing", "returned", "unresolved"])
def test_valid_guard_is_explicitly_not_cleanup_proof(phase):
    scan = SecurityScan(summary={"request": "preserved"})
    worker_module._set_execution_phase(scan, phase)
    assert worker_module._execution_phase(scan) == phase
    assert scan.summary["request"] == "preserved"
    assert scan.summary[worker_module.GUARD_KEY]["cleanup_verified"] is False


@pytest_asyncio.fixture
async def execution_case(scan_case, monkeypatch):
    case = scan_case
    case.io = []
    case.worker = worker_module.SecurityScanWorker()
    monkeypatch.setattr(worker_module, "SessionLocal", case.sessions)

    async def policy(_session):
        case.io.append("policy")
        return {"max_scan_runtime_seconds": 60}

    async def execute(_session, scan):
        case.io.append("execute")
        await asyncio.sleep(0)
        scan.status = "completed"
        scan.completed_at = datetime.now(UTC)
        scan.lease_token = None
        scan.summary = {**scan.summary, "synthetic_result": True}
        return scan

    monkeypatch.setattr(worker_module, "get_policy", policy)
    monkeypatch.setattr(worker_module, "execute_scan", execute)
    yield case
    assert not case.forbidden_attempts


async def _new(case, **changes):
    values = dict(
        id=str(uuid4()), organization_id=case.actor.organization_id,
        project_id=case.project_id, target_id=case.target_id,
        requested_by_id=case.actor.id, profile="passive", status="queued",
        execution_mode="passive", attempts=0, max_attempts=2,
        summary={"requested_at": datetime.now(UTC).isoformat()},
    )
    values.update(changes)
    async with case.sessions() as session:
        session.add(SecurityScan(**values))
        await session.commit()
    return values["id"]


async def _row(case, identifier):
    async with case.sessions() as session:
        row = (await session.execute(
            select(SecurityScan.__table__).where(SecurityScan.id == identifier)
        )).mappings().one()
        return deepcopy(dict(row))


async def _edit(case, identifier, **changes):
    async with case.sessions() as session:
        row = await session.get(SecurityScan, identifier)
        for name, value in changes.items():
            setattr(row, name, value)
        await session.commit()


@pytest.mark.asyncio
async def test_pristine_claim_commits_guard_before_any_execution(execution_case):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim()
    assert claim and claim[0] == identifier
    row = await _row(case, identifier)
    assert row["status"] == "running" and row["attempts"] == 1
    assert row["summary"][worker_module.GUARD_KEY] == _guard()
    assert row["lease_token"] == claim[1]
    assert row["completed_at"] is None
    assert not case.io
    assert await case.worker.claim() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"status": "running", "attempts": 1, "updated_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"status": "failed"}, {"status": "cancelled"}, {"status": "completed"},
    {"attempts": 1}, {"attempts": 100}, {"max_attempts": 0},
    {"started_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"completed_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"cancelled_at": datetime(2000, 1, 1, tzinfo=UTC)},
    {"lease_token": "00000000-0000-4000-8000-000000000001"},
    {"error_code": "UNCERTAIN"}, {"error_message": "uncertain"},
    {"summary": {worker_module.GUARD_KEY: None}},
    {"summary": {worker_module.GUARD_KEY: _guard("returned")}},
    {"summary": []}, {"summary": "legacy"},
])
async def test_touched_or_legacy_work_is_never_reclaimed(execution_case, changes):
    case = execution_case
    identifier = await _new(case, **changes)
    before = await _row(case, identifier)
    assert await case.worker.claim() is None
    assert await _row(case, identifier) == before
    assert not case.io


@pytest.mark.asyncio
async def test_concurrent_claims_and_duplicate_runs_execute_once(execution_case):
    case = execution_case
    identifier = await _new(case)
    claims = await asyncio.wait_for(asyncio.gather(
        case.worker.claim(), worker_module.SecurityScanWorker().claim(),
    ), WAIT)
    accepted = [claim for claim in claims if claim is not None]
    assert len(accepted) == 1 and accepted[0][0] == identifier
    await asyncio.wait_for(asyncio.gather(
        case.worker.run_claim(*accepted[0]),
        worker_module.SecurityScanWorker().run_claim(*accepted[0]),
    ), WAIT)
    assert case.io == ["policy", "execute"]
    row = await _row(case, identifier)
    assert row["status"] == "completed"
    assert row["summary"][worker_module.GUARD_KEY] == _guard("returned")
    assert row["lease_token"] is None
    await case.worker.run_claim(*accepted[0])
    assert case.io == ["policy", "execute"]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["claim", "start"])
async def test_closed_admission_precedes_claim_or_one_time_start(execution_case, boundary):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim() if boundary == "start" else None
    await _shared._close(case)
    before = await _row(case, identifier)
    with pytest.raises(HostMaintenanceClosed):
        if claim:
            await case.worker.run_claim(*claim)
        else:
            await case.worker.claim()
    assert await _row(case, identifier) == before
    assert not case.io


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["claim", "start"])
@pytest.mark.parametrize("kind", ["missing", "corrupt"])
async def test_unavailable_authority_never_starts_work(execution_case, boundary, kind):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim() if boundary == "start" else None
    await _shared._change_authority(case, delete=kind == "missing", generation="invalid")
    before = await _row(case, identifier)
    with pytest.raises(HostMaintenanceUnavailable):
        if claim:
            await case.worker.run_claim(*claim)
        else:
            await case.worker.claim()
    assert await _row(case, identifier) == before
    assert not case.io


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError, TimeoutError, OSError, asyncio.CancelledError])
async def test_interruption_retains_owner_and_requires_reconciliation(execution_case, monkeypatch, error):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim()
    assert claim

    async def interrupted(_session, scan):
        case.io.append("interrupted")
        scan.summary = {**scan.summary, "must_rollback": True}
        raise error("synthetic private error detail must not be persisted")

    monkeypatch.setattr(worker_module, "execute_scan", interrupted)
    with pytest.raises(error):
        await case.worker.run_claim(*claim)
    row = await _row(case, identifier)
    assert row["status"] == "running" and row["attempts"] == 1
    assert row["lease_token"] == claim[1] and row["completed_at"] is None
    assert row["summary"][worker_module.GUARD_KEY] == _guard("unresolved")
    assert "must_rollback" not in row["summary"]
    assert row["error_code"] == "SECURITY_SCAN_RECONCILIATION_REQUIRED"
    assert row["error_message"] == error.__name__
    assert await case.worker.claim() is None
    await case.worker.run_claim(*claim)
    assert case.io == ["policy", "interrupted"]


@pytest.mark.asyncio
async def test_repeated_external_cancel_does_not_cancel_reconciliation(execution_case, monkeypatch):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim()
    assert claim
    entered, recording, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = case.worker._mark_unresolved

    async def blocked_execute(_session, _scan):
        entered.set()
        await asyncio.Event().wait()

    async def delayed_record(*args):
        recording.set()
        await release.wait()
        await original(*args)

    monkeypatch.setattr(worker_module, "execute_scan", blocked_execute)
    monkeypatch.setattr(case.worker, "_mark_unresolved", delayed_record)
    task = asyncio.create_task(case.worker.run_claim(*claim))
    try:
        await asyncio.wait_for(entered.wait(), WAIT)
        task.cancel()
        await asyncio.wait_for(recording.wait(), WAIT)
        task.cancel()
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
    row = await _row(case, identifier)
    assert row["summary"][worker_module.GUARD_KEY] == _guard("unresolved")
    assert row["lease_token"] == claim[1]
    assert await case.worker.claim() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["claimed", "executing", "returned", "unresolved"])
async def test_wrong_owner_never_mutates_or_runs(execution_case, phase):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim()
    assert claim
    row = await _row(case, identifier)
    await _edit(case, identifier, summary={**row["summary"], worker_module.GUARD_KEY: _guard(phase)})
    before = await _row(case, identifier)
    await case.worker.run_claim(identifier, str(uuid4()))
    assert await _row(case, identifier) == before
    assert not case.io


@pytest.mark.asyncio
async def test_failed_reconciliation_retains_committed_executing_marker(execution_case, monkeypatch):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim()
    assert claim

    async def failed_execute(_session, _scan):
        raise TimeoutError("synthetic")

    async def failed_record(*_args):
        raise RuntimeError("synthetic database unavailable")

    monkeypatch.setattr(worker_module, "execute_scan", failed_execute)
    monkeypatch.setattr(case.worker, "_mark_unresolved", failed_record)
    with pytest.raises(TimeoutError):
        await case.worker.run_claim(*claim)
    row = await _row(case, identifier)
    assert row["summary"][worker_module.GUARD_KEY] == _guard("executing")
    assert row["lease_token"] == claim[1]
    assert await case.worker.claim() is None
    await case.worker.run_claim(*claim)
    assert case.io == ["policy"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_lost", [False, True])
async def test_start_commit_failure_never_performs_scanner_io(execution_case, monkeypatch, ack_lost):
    case = execution_case
    identifier = await _new(case)
    claim = await case.worker.claim()
    assert claim

    class FailingStartSession(AsyncSession):
        async def commit(self):
            if ack_lost:
                await super().commit()
            raise RuntimeError("synthetic commit acknowledgement failure")

    sessions = async_sessionmaker(case.engine, class_=FailingStartSession, expire_on_commit=False)
    monkeypatch.setattr(worker_module, "SessionLocal", sessions)
    with pytest.raises(RuntimeError, match="acknowledgement"):
        await case.worker.run_claim(*claim)
    assert not case.io
    row = await _row(case, identifier)
    expected = "executing" if ack_lost else "claimed"
    assert row["summary"][worker_module.GUARD_KEY] == _guard(expected)
    assert row["lease_token"] == claim[1]
    monkeypatch.setattr(worker_module, "SessionLocal", case.sessions)
    if ack_lost:
        await case.worker.run_claim(*claim)
        assert not case.io
    assert await case.worker.claim() is None
