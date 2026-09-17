"""Real PostgreSQL request-only scan/retest admission contracts.

No scanner, source copy, process, provider or real target is executed. The shared
D6 fixture supplies isolated schemas, real API/auth/policy and runtime-I/O traps.
This acceptance must not be described as scanner execution/drain acceptance.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import current_user
from app.db.base import get_db
from app.db.models import AuditEvent, OwnerControlRecord, SecurityRemediation
from app.services import host_maintenance_admission as admission
from app.services import security_fabric, security_remediation, security_scanning
from app.services.host_maintenance_scan_admission import CONSUMER, require_scan_admission
# Load the existing isolated fixtures explicitly: the root suite uses pytest's
# importlib mode and does not place the backend tests directory on sys.path.
import importlib.util
from pathlib import Path
import sys


def _fixture_module(filename):
    name = "fr06c5d7_shared_" + filename.removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_api = _fixture_module("test_fr06c5d6_remediation_api_database.py")
_db = _fixture_module("test_host_maintenance_remediation_db.py")
remediation_case = _api.remediation_case
remediation_db = _db.remediation_db
PREFIX, _business = _api.PREFIX, _api._business
_claim, _run_migration, _settle = _db._claim, _db._run_migration, _db._settle

CLOSED = "Security scan admission is temporarily closed for maintenance."
UNAVAILABLE = "Security scan admission is currently unavailable."
WAIT = 8


@pytest_asyncio.fixture
async def scan_case(remediation_case):
    case = remediation_case
    async with case.engine.begin() as connection:
        await connection.run_sync(_run_migration, "0052", "upgrade")
    return case


async def _authority(case):
    async with case.sessions() as session:
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == admission.DOMAIN,
            OwnerControlRecord.resource_id == admission.RESOURCE_ID,
        ))
        return deepcopy(row.payload) if row is not None else None


async def _change_authority(case, *, delete=False, **changes):
    async with case.sessions() as session:
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == admission.DOMAIN,
            OwnerControlRecord.resource_id == admission.RESOURCE_ID,
        ))
        if delete:
            await session.delete(row)
        else:
            row.payload = {**row.payload, **changes}
        await session.commit()


async def _close(case, session_factory=None):
    payload = await _authority(case)
    return await admission.close_admission(
        operation_id=case.operation_id, expected_generation=payload["generation"],
        reason="isolated scan request maintenance",
        session_factory=session_factory or case.sessions,
    )


async def _new_retest(case, *, status="regression_passed"):
    identifier = str(uuid4())
    async with case.sessions() as session:
        session.add(SecurityRemediation(
            id=identifier, organization_id=case.actor.organization_id,
            project_id=case.project_id, finding_id=case.finding_id,
            requested_by_id=case.actor.id, status=status,
            worktree_ref=f"security-remediation://{identifier}/source",
            plan={"schema_version": 1}, regression_result={"tests_passed": True},
            preparation_protocol_version=1, preparation_outcome="prepared",
        ))
        await session.commit()
    return identifier


async def _request(case, family, remediation_id=None):
    if family == "scan":
        return await case.client.post(
            PREFIX + "/scans", json={"target_id": case.target_id, "profile": "passive"},
        )
    return await case.client.post(PREFIX + f"/remediations/{remediation_id}/retest")


async def _remove_policy(case):
    async with case.sessions() as session:
        await session.execute(OwnerControlRecord.__table__.delete().where(
            OwnerControlRecord.domain == security_fabric.POLICY_DOMAIN,
        ))
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
async def test_open_request_202_persists_only_queue_and_preserves_preparation(scan_case, family):
    case = scan_case
    remediation_id = await _new_retest(case)
    before = await _business(case)
    response = await _request(case, family, remediation_id)
    assert response.status_code == 202, response.text
    payload = response.json()["scan"] if family == "retest" else response.json()
    assert payload["status"] == "queued"
    assert payload["target_id"] == case.target_id
    assert payload["requested_by_id"] == case.actor.id
    assert payload["started_at"] is None and payload["completed_at"] is None
    after = await _business(case)
    assert len(after["security_scans"]) == len(before["security_scans"]) + 1
    assert after["host_maintenance_work_cycles"] == before["host_maintenance_work_cycles"]
    item = next(row for row in after["security_scans"] if row["id"] == payload["id"])
    assert item["attempts"] == 0
    if family == "retest":
        original = next(row for row in before["security_remediations"] if row["id"] == remediation_id)
        current = next(row for row in after["security_remediations"] if row["id"] == remediation_id)
        assert current["status"] == "retest_queued"
        assert current["retest_scan_id"] == payload["id"]
        for key in ("preparation_protocol_version", "preparation_outcome", "plan", "regression_result", "worktree_ref"):
            assert current[key] == original[key]
    assert not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
@pytest.mark.parametrize("bad_state", ["closed", "missing", "corrupt", "old_scope", "future", "full_host"])
async def test_denial_precedes_policy_dns_target_and_business_mutations(scan_case, family, bad_state, monkeypatch):
    case = scan_case
    remediation_id = await _new_retest(case)
    await _remove_policy(case)
    if bad_state == "closed":
        await _close(case)
    elif bad_state == "missing":
        await _change_authority(case, delete=True)
    elif bad_state == "corrupt":
        await _change_authority(case, generation="6")
    elif bad_state == "old_scope":
        await _change_authority(case, schema_version=5, scope=admission.REMEDIATION_COVERAGE_SCOPE)
    elif bad_state == "future":
        await _change_authority(case, schema_version=999)
    else:
        await _change_authority(case, full_host_closure=True)
    before = await _business(case)
    dns_calls = []
    def forbidden_dns(*args):
        dns_calls.append(args)
        raise AssertionError("denied admission must not resolve DNS")
    monkeypatch.setattr(security_fabric, "assert_target_dns_stable", forbidden_dns)
    response = await _request(case, family, remediation_id)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": CLOSED if bad_state == "closed" else UNAVAILABLE}
    assert await _business(case) == before
    assert not dns_calls and not case.forbidden_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
async def test_guard_precedes_pending_autoflush_and_no_internal_commit(scan_case, family):
    case = scan_case
    remediation_id = await _new_retest(case)
    async with case.sessions() as session:
        item = await session.get(SecurityRemediation, remediation_id)
        await _close(case)
        before = await _business(case)
        writes = []
        def observed(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)
        event.listen(case.engine.sync_engine, "before_cursor_execute", observed)
        try:
            session.add(AuditEvent(
                id=str(uuid4()), organization_id=case.actor.organization_id,
                user_id=case.actor.id, action="synthetic.pending",
                resource_type="test", resource_id=str(uuid4()), details={},
            ))
            with pytest.raises(admission.HostMaintenanceClosed):
                if family == "scan":
                    await security_scanning.request_scan(session, case.actor, target_id=case.target_id, profile="passive")
                else:
                    await security_remediation.queue_retest(session, case.actor, item)
            assert not writes
            assert session.in_transaction()
        finally:
            event.remove(case.engine.sync_engine, "before_cursor_execute", observed)
            await session.rollback()
    assert await _business(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
@pytest.mark.parametrize("commit", [False, True])
async def test_direct_producers_retain_caller_transaction(scan_case, family, commit):
    case = scan_case
    remediation_id = await _new_retest(case)
    before = await _business(case)
    async with case.sessions() as session:
        if family == "scan":
            scan = await security_scanning.request_scan(session, case.actor, target_id=case.target_id, profile="passive")
        else:
            item = await session.get(SecurityRemediation, remediation_id)
            scan = await security_remediation.queue_retest(session, case.actor, item)
        scan_id = scan.id
        assert session.in_transaction()
        await session.flush()
        assert await _business(case) == before
        if commit:
            await session.commit()
        else:
            await session.rollback()
    after = await _business(case)
    assert any(row["id"] == scan_id for row in after["security_scans"]) is commit
    if not commit:
        assert after == before


class _ProbeSession(AsyncSession):
    async def execute(self, statement, *args, **kwargs):
        lock = getattr(statement, "_for_update_arg", None)
        probe = self.info["scan_probe"]
        first = lock is not None and not self.info.get("scan_probe_seen")
        if first:
            self.info["scan_probe_seen"] = True
            pid = int(await super().scalar(text("SELECT pg_backend_pid()")))
            probe.started.put_nowait((pid, bool(lock.read)))
        result = await super().execute(statement, *args, **kwargs)
        if first:
            probe.acquired.set()
            if probe.pause:
                await probe.release.wait()
        return result


def _factory(case, *, pause=False):
    probe = SimpleNamespace(started=asyncio.Queue(), acquired=asyncio.Event(), release=asyncio.Event(), pause=pause)
    factory = async_sessionmaker(
        case.engine, class_=_ProbeSession, expire_on_commit=False,
        info={"scan_probe": probe},
    )
    return factory, probe


async def _blocked(case, pid, blocker):
    deadline = asyncio.get_running_loop().time() + WAIT
    async with case.sessions() as observer:
        while asyncio.get_running_loop().time() < deadline:
            if blocker in (await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}) or []):
                return
            await asyncio.sleep(0.01)
    pytest.fail("real PostgreSQL blocker was not observed")


async def _stop(*tasks):
    for task in tasks:
        if task is not None and not task.done():
            task.cancel()
    await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
@pytest.mark.parametrize("outcome", ["commit", "rollback", "cancel"])
async def test_producer_first_blocks_close_through_real_policy_flush_and_final_transaction(scan_case, family, outcome, monkeypatch):
    case = scan_case
    remediation_id = await _new_retest(case)
    await _remove_policy(case)
    before = await _business(case)
    factory, request_probe = _factory(case)
    close_factory, close_probe = _factory(case)
    ready, release = asyncio.Event(), asyncio.Event()
    original = security_fabric.get_policy
    async def gated_policy(session):
        result = await original(session)
        await session.flush()
        ready.set()
        await release.wait()
        if outcome == "rollback":
            raise ValueError("synthetic rollback after policy flush")
        return result
    async def request_db():
        async with factory() as session:
            yield session
    case.app.dependency_overrides[get_db] = request_db
    monkeypatch.setattr(security_fabric, "get_policy", gated_policy)
    requester = closer = None
    try:
        requester = asyncio.create_task(_request(case, family, remediation_id))
        request_pid, shared = await asyncio.wait_for(request_probe.started.get(), WAIT)
        assert shared
        await asyncio.wait_for(ready.wait(), WAIT)
        assert await _business(case) == before
        closer = asyncio.create_task(_close(case, close_factory))
        close_pid, shared = await asyncio.wait_for(close_probe.started.get(), WAIT)
        assert not shared
        await _blocked(case, close_pid, request_pid)
        if outcome == "cancel":
            requester.cancel()
        else:
            release.set()
        results = await asyncio.wait_for(asyncio.gather(requester, closer, return_exceptions=True), WAIT)
        assert isinstance(results[1], admission.HostMaintenanceSnapshot)
        assert not results[1].is_open
        if outcome == "cancel":
            assert isinstance(results[0], asyncio.CancelledError)
        else:
            assert results[0].status_code == (202 if outcome == "commit" else (422 if family == "scan" else 409))
        after = await _business(case)
        if outcome == "commit":
            assert len(after["security_scans"]) == len(before["security_scans"]) + 1
            assert len(after["security_policy"]) == 1
        else:
            assert after == before
    finally:
        release.set()
        await _stop(requester, closer)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
async def test_close_first_blocks_shared_admission_and_denies_without_business_lock(scan_case, family):
    case = scan_case
    remediation_id = await _new_retest(case)
    before = await _business(case)
    close_factory, close_probe = _factory(case, pause=True)
    request_factory, request_probe = _factory(case)
    async def request_db():
        async with request_factory() as session:
            yield session
    case.app.dependency_overrides[get_db] = request_db
    closer = requester = None
    async with case.sessions() as blocker:
        # A reversed retest lock order would block on this row, not authority.
        await blocker.scalar(select(SecurityRemediation).where(
            SecurityRemediation.id == remediation_id,
        ).with_for_update())
        try:
            closer = asyncio.create_task(_close(case, close_factory))
            close_pid, shared = await asyncio.wait_for(close_probe.started.get(), WAIT)
            assert not shared
            await asyncio.wait_for(close_probe.acquired.wait(), WAIT)
            requester = asyncio.create_task(_request(case, family, remediation_id))
            request_pid, shared = await asyncio.wait_for(request_probe.started.get(), WAIT)
            assert shared
            await _blocked(case, request_pid, close_pid)
            close_probe.release.set()
            response, closed = await asyncio.wait_for(asyncio.gather(requester, closer), WAIT)
            assert response.status_code == 503 and response.json() == {"detail": CLOSED}
            assert not closed.is_open
            assert await _business(case) == before
        finally:
            close_probe.release.set()
            await _stop(requester, closer)
            await blocker.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
async def test_authentication_is_still_required_during_maintenance(scan_case, family):
    case = scan_case
    remediation_id = await _new_retest(case)
    await _close(case)
    async def unauthenticated():
        raise HTTPException(status_code=401, detail="Not authenticated")
    case.app.dependency_overrides[current_user] = unauthenticated
    response = await _request(case, family, remediation_id)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_scan_body_remains_422_during_maintenance(scan_case):
    await _close(scan_case)
    response = await scan_case.client.post(PREFIX + "/scans", json={"target_id": "", "profile": "invalid"})
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
async def test_authority_read_database_failure_is_sanitized(scan_case, family, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services import host_maintenance_scan_admission as guard
    case = scan_case
    remediation_id = await _new_retest(case)
    before = await _business(case)
    async def failed(*args, **kwargs):
        raise OperationalError("private connection statement", {}, Exception("synthetic-sensitive-driver-detail"))
    monkeypatch.setattr(guard, "require_admission_open", failed)
    response = await _request(case, family, remediation_id)
    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}
    assert "synthetic-sensitive" not in response.text
    assert await _business(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", [False, True])
async def test_migration_preserves_state_identity_and_expands_only_request_scope(remediation_db, closed):
    db = remediation_db
    if closed:
        await db.close()
    before = await db.authority_row()
    registry = await db.registry_rows()
    await db.migrate("0052")
    after = await db.authority_row()
    assert after["status"] == before["status"] and after["enabled"] == before["enabled"]
    assert after["version"] == before["version"] + 1
    for key in ("operation_id", "reason", "changed_at", "full_host_closure"):
        assert after["payload"][key] == before["payload"][key]
    assert after["payload"]["schema_version"] == admission.SCAN_REQUEST_SCHEMA_VERSION
    assert after["payload"]["scope"] == admission.SCAN_REQUEST_COVERAGE_SCOPE
    assert "security_scan_execution" not in after["payload"]["scope"]
    assert await db.registry_rows() == registry
    async with db.sessions() as session:
        for scope in ("project_execution", "backup_cycles", "academy_course_packages", "notification_delivery_dispatch", "security_remediation_preparation", CONSUMER):
            snapshot = await admission.read_admission_snapshot(session, required_scope=scope)
            assert snapshot.is_open is not closed
    for revision, direction in (("0052", "upgrade"), ("0052", "downgrade"), ("0049", "upgrade"), ("0050", "upgrade"), ("0051", "upgrade"), ("0052", "upgrade")):
        await db.migrate(revision, direction)
        assert await db.authority_row() == after
        assert await db.registry_rows() == registry


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"schema_version": 4}, {"schema_version": 7}, {"schema_version": True},
    {"scope": "project_execution"}, {"generation": "5"}, {"generation": True},
    {"generation": 4}, {"full_host_closure": True}, {"operation_id": "bad"},
    {"operation_id": None}, {"changed_at": "2026-09-17T00:00:00"},
    {"changed_at": "invalid"}, {"changed_at": None}, {"reason": ""},
    {"reason": "x" * 501}, {"reason": "bad\u0000reason"}, {"extra": "unexpected"},
])
async def test_migration_leaves_malformed_or_legacy_authority_untouched(remediation_db, bad):
    db = remediation_db
    before = await db.authority_row()
    await db.update_authority(payload={**before["payload"], **bad})
    before = await db.authority_row()
    await db.migrate("0052")
    assert await db.authority_row() == before
    async with db.sessions() as session:
        with pytest.raises(admission.HostMaintenanceUnavailable):
            await require_scan_admission(session)


@pytest.mark.asyncio
async def test_missing_authority_is_not_seeded_by_migration(remediation_db):
    db = remediation_db
    async with db.sessions() as session:
        await session.execute(OwnerControlRecord.__table__.delete())
        await session.commit()
    await db.migrate("0052")
    assert await db.authority_row() is None


@pytest.mark.asyncio
async def test_existing_remediation_owner_and_finished_proof_survive_expansion(remediation_db):
    from app.services import host_maintenance_remediation as ownership
    db = remediation_db
    owned = await _claim(db, begin=True)
    await db.migrate("0052")
    closed = await db.close()
    assert (await db.snapshot(closed)).blocker_count == 1
    await ownership.heartbeat_remediation_activity(owned, session_factory=db.sessions)
    await _settle(db, owned)
    await ownership.finish_remediation_activity(owned, session_factory=db.sessions)
    assert (await db.snapshot(closed)).is_clear
    assert (await db.get(owned.remediation_id))["preparation_outcome"] == "prepared"


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
async def test_real_deferred_commit_failure_rolls_back_policy_scan_link_and_audits(scan_case, family):
    from sqlalchemy import Column, ForeignKey, MetaData, String, Table
    from app.db.models import SecurityScan
    case = scan_case
    remediation_id = await _new_retest(case)
    await _remove_policy(case)
    before = await _business(case)
    tripwire = Table(
        "scan_commit_failure_" + uuid4().hex, MetaData(),
        Column("id", String(36), primary_key=True),
        Column("scan_id", String(36), ForeignKey(
            SecurityScan.__table__.c.id, deferrable=True, initially="DEFERRED",
        ), nullable=False),
    )
    async with case.engine.begin() as connection:
        await connection.run_sync(tripwire.create)
    fired = []
    def before_commit(sync_session):
        # This INSERT succeeds; PostgreSQL rejects the deferred FK at COMMIT.
        sync_session.execute(tripwire.insert().values(id=str(uuid4()), scan_id=str(uuid4())))
        fired.append(True)
    async def request_db():
        async with case.sessions() as session:
            event.listen(session.sync_session, "before_commit", before_commit)
            try:
                yield session
            finally:
                event.remove(session.sync_session, "before_commit", before_commit)
                await session.rollback()
    case.app.dependency_overrides[get_db] = request_db
    response = await _request(case, family, remediation_id)
    assert response.status_code == 500
    assert fired == [True]
    assert await _business(case) == before
    assert not case.forbidden_attempts
    assert not (await _close(case)).is_open


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["scan", "retest"])
async def test_open_unknown_resource_preserves_404(scan_case, family):
    case = scan_case
    if family == "scan":
        case.target_id = str(uuid4())
    response = await _request(case, family, str(uuid4()))
    assert response.status_code == 404
    assert not case.forbidden_attempts


@pytest.mark.asyncio
async def test_open_retest_still_requires_passed_regression(scan_case):
    remediation_id = await _new_retest(scan_case, status="worktree_ready")
    before = await _business(scan_case)
    response = await _request(scan_case, "retest", remediation_id)
    assert response.status_code == 409
    assert await _business(scan_case) == before


@pytest.mark.asyncio
async def test_open_retest_other_organization_cannot_access_prepared_artifact(scan_case):
    remediation_id = await _new_retest(scan_case)
    before = await _business(scan_case)
    scan_case.actor = scan_case.outsider
    response = await _request(scan_case, "retest", remediation_id)
    assert response.status_code == 404
    assert await _business(scan_case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("generation", [2, 3, 4, 5])
async def test_request_scope_cannot_be_accepted_with_predecessor_generation(scan_case, generation):
    async with scan_case.sessions() as session:
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == admission.DOMAIN,
        ))
        row.payload = {**row.payload, "generation": generation}
        row.version = generation
        await session.commit()
    before = await _business(scan_case)
    response = await _request(scan_case, "scan")
    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}
    assert await _business(scan_case) == before
