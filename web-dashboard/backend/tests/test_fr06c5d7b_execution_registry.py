"""Real disposable-PostgreSQL registry contracts, not runtime cleanup acceptance.

Thread/process/remote observations below are synthetic evidence inputs. These
cases test durable fencing and evidence validation, never certify a real scanner,
process group, thread or ZAP daemon as stopped. No worker is activated here.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import SecurityScan, SecurityScanExecution
from app.services import host_maintenance_scan_execution as registry
from app.services.host_maintenance_admission import HostMaintenanceClosed

_name = "fr06c5d7b_registry_shared"
_spec = importlib.util.spec_from_file_location(_name, Path(__file__).with_name("test_fr06c5d7_scan_request_admission.py"))
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
remediation_case = _shared.remediation_case
scan_case = _shared.scan_case


@pytest_asyncio.fixture
async def registry_case(scan_case):
    case = scan_case
    async with case.engine.begin() as connection:
        await connection.run_sync(_shared._run_migration, "0053", "upgrade")
    # Remove synthetic completed baseline scans; there are no real user rows in
    # this UUID schema. Their dependent fixture findings cascade inside the lab.
    async with case.sessions() as session, session.begin():
        await session.execute(delete(SecurityScan))
    return case


async def new_scan(case, **changes):
    values = {
        "id": str(uuid4()), "organization_id": case.actor.organization_id,
        "project_id": case.project_id, "target_id": case.target_id,
        "requested_by_id": case.actor.id, "profile": "passive", "status": "queued",
        "execution_mode": "passive", "attempts": 0, "max_attempts": 2, "summary": {},
    }
    values.update(changes)
    async with case.sessions() as session, session.begin():
        session.add(SecurityScan(**values))
    return values["id"]


async def claim(case, identifier=None, *, commit=True):
    identifier = identifier or await new_scan(case)
    async with case.sessions() as session:
        owner = await registry.register_execution(session, scan_id=identifier, worker_incarnation=str(uuid4()))
        if commit:
            await session.commit()
        else:
            await session.rollback()
        return owner


async def begin(case, owner):
    async with case.sessions() as session, session.begin():
        return await registry.begin_execution(session, owner)


async def row(case, owner):
    async with case.sessions() as session:
        record = await session.get(SecurityScanExecution, owner.execution_id)
        return record


async def snapshot(case):
    return await registry.execution_snapshot(session_factory=case.sessions)


async def reserve(case, owner, kind="thread", **kw):
    return await registry.reserve_resource(owner, kind, session_factory=case.sessions, **kw)


async def update(case, owner, identifier, **kw):
    return await registry.update_resource(owner, identifier, session_factory=case.sessions, **kw)


async def returned(case, owner, outcome="failed"):
    async with case.sessions() as session, session.begin():
        if outcome == "completed":
            scan = await session.get(SecurityScan, owner.scan_id)
            scan.status = "completed"
            scan.completed_at = datetime.now(UTC)
            scan.lease_token = None
        await registry.operation_returned(session, owner, outcome=outcome)


async def settle(case, owner):
    await registry.supervisor_returned(owner, session_factory=case.sessions)
    return await registry.reconcile_returned_execution(owner.scan_id, session_factory=case.sessions)


async def cancel(case, identifier, *, commit=True, organization=None):
    async with case.sessions() as session:
        result = await registry.request_scan_cancellation(
            session, scan_id=identifier,
            organization_id=organization or case.actor.organization_id, user_id=case.actor.id,
        )
        if commit:
            await session.commit()
        else:
            await session.rollback()
        return result


@pytest.mark.asyncio
async def test_migration_schema_and_no_authority_or_business_change(scan_case):
    case = scan_case
    before = await _shared._authority(case)
    async with case.engine.begin() as connection:
        await connection.run_sync(_shared._run_migration, "0053", "upgrade")
        names = set((await connection.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
            "AND table_name='security_scan_executions'"
        ))).scalars())
    assert names == set(SecurityScanExecution.__table__.c.keys())
    assert await _shared._authority(case) == before
    async with case.sessions() as session:
        assert list((await session.scalars(select(SecurityScanExecution))).all()) == []


@pytest.mark.asyncio
async def test_migration_downgrade_refuses_to_erase_evidence(registry_case):
    case = registry_case
    owner = await claim(case)
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_shared._run_migration, "0053", "downgrade")
    assert (await row(case, owner)).phase == "claimed"


@pytest.mark.asyncio
async def test_register_is_atomic_with_business_claim(registry_case):
    case = registry_case
    identifier = await new_scan(case)
    owner = await claim(case, identifier, commit=False)
    assert await row(case, owner) is None
    async with case.sessions() as session:
        scan = await session.get(SecurityScan, identifier)
        assert scan.status == "queued" and scan.attempts == 0 and scan.lease_token is None
    owner = await claim(case, identifier)
    record = await row(case, owner)
    assert record.scan_id == identifier and record.phase == "claimed"
    assert record.resources == {} and record.state == "active"
    assert owner.ownership_nonce not in repr(owner)
    observed = await snapshot(case)
    assert observed["blocker_count"] == 1 and observed["coverage_unverified"] is True
    assert observed["full_host_closure"] is False
    assert owner.ownership_nonce not in str(observed)


@pytest.mark.asyncio
async def test_duplicate_registration_cannot_transfer_or_replace(registry_case):
    case = registry_case
    owner = await claim(case)
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await claim(case, owner.scan_id)
    record = await row(case, owner)
    assert record.worker_incarnation == owner.worker_incarnation
    assert record.ownership_nonce == owner.ownership_nonce


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["execution_id", "scan_id", "worker_incarnation", "ownership_nonce", "admitted_generation"])
async def test_wrong_capability_rejected_without_mutation(registry_case, field):
    case = registry_case
    owner = await claim(case)
    bad = replace(owner, **{field: 999 if field == "admitted_generation" else str(uuid4())})
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await begin(case, bad)
    assert (await row(case, owner)).phase == "claimed"


@pytest.mark.asyncio
async def test_begin_is_once_and_requires_current_open_generation(registry_case):
    case = registry_case
    owner = await claim(case)
    assert sorted(await asyncio.gather(begin(case, owner), begin(case, owner))) == [False, True]
    assert await begin(case, owner) is False
    assert (await row(case, owner)).phase == "executing"
    other = await claim(case)
    await _shared._close(case)
    with pytest.raises(HostMaintenanceClosed):
        await begin(case, other)
    assert (await row(case, other)).phase == "claimed"


@pytest.mark.asyncio
async def test_stale_generation_does_not_start_after_reopen(registry_case):
    case = registry_case
    owner = await claim(case)
    closed = await _shared._close(case)
    await _shared.admission.open_admission(
        operation_id=closed.operation_id, expected_generation=closed.generation,
        reason="isolated explicit generation change", session_factory=case.sessions,
    )
    assert await begin(case, owner) is False
    assert (await row(case, owner)).phase == "claimed"


@pytest.mark.asyncio
async def test_expiry_is_observation_not_release_or_reclaim(registry_case):
    case = registry_case
    owner = await claim(case)
    async with case.sessions() as session, session.begin():
        record = await session.get(SecurityScanExecution, owner.execution_id)
        record.heartbeat_at = record.started_at - timedelta(days=1)
        record.lease_expires_at = record.heartbeat_at + timedelta(seconds=1)
    observed = await snapshot(case)
    assert observed["executions"][0]["expired"] is True
    assert observed["is_clear"] is False and observed["blocker_count"] == 1
    assert await registry.reconcile_returned_execution(owner.scan_id, session_factory=case.sessions) is False
    assert (await row(case, owner)).state == "active"


@pytest.mark.asyncio
async def test_heartbeat_continues_after_admission_close_and_reads_cancel(registry_case):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    await _shared._close(case)
    assert await registry.heartbeat_execution(owner, session_factory=case.sessions) is False
    assert (await cancel(case, owner.scan_id))["cleanup_verified"] is False
    assert await registry.heartbeat_execution(owner, session_factory=case.sessions) is True
    assert (await row(case, owner)).state == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,evidence", [
    ("thread", {"joined": True, "cleanup_complete": True}),
    ("async_io", {"joined": True, "cleanup_complete": True}),
    ("process", {"leader_reaped": True, "group_empty": True, "descendants_reaped": True, "cleanup_complete": True}),
    ("zap", {"remote_zero": True, "cleanup_complete": True}),
])
async def test_resource_record_requires_explicit_settlement_and_supervisor_join(registry_case, kind, evidence):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    kw = {"exclusive_key": "a" * 64} if kind == "zap" else {}
    identifier = await reserve(case, owner, kind, **kw)
    assert (await row(case, owner)).resources[identifier]["state"] == "reserved"
    await update(case, owner, identifier, state="active")
    await update(case, owner, identifier, state="settled", evidence=evidence)
    await returned(case, owner)
    assert await registry.reconcile_returned_execution(owner.scan_id, session_factory=case.sessions) is False
    assert (await snapshot(case))["is_clear"] is False
    assert await settle(case, owner) is True
    assert await settle(case, owner) is True
    assert (await snapshot(case))["is_clear"] is True
    assert (await row(case, owner)).resources[identifier]["evidence"] == evidence
    async with case.sessions() as session:
        scan = await session.get(SecurityScan, owner.scan_id)
        assert scan.status == "failed" and scan.lease_token is None
        assert scan.summary["execution_cleanup"]["verified"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,evidence", [
    ("thread", {}), ("thread", {"joined": True}),
    ("thread", {"joined": 1, "cleanup_complete": True}),
    ("process", {"leader_reaped": True, "cleanup_complete": True}),
    ("process", {"group_empty": True, "cleanup_complete": True}),
    ("zap", {"remote_zero": True}),
    ("zap", {"remote_zero": "true", "cleanup_complete": True}),
])
async def test_incomplete_resource_proof_cannot_settle(registry_case, kind, evidence):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    identifier = await reserve(case, owner, kind, **({"exclusive_key": "b" * 64} if kind == "zap" else {}))
    with pytest.raises(registry.ScanExecutionUncertain):
        await update(case, owner, identifier, state="settled", evidence=evidence)
    assert (await row(case, owner)).resources[identifier]["state"] == "reserved"
    await returned(case, owner)
    assert await settle(case, owner) is False
    assert (await row(case, owner)).state == "unresolved"


@pytest.mark.asyncio
async def test_uncertain_remote_submission_holds_exclusive_engine_across_owners(registry_case):
    case = registry_case
    first, second = await claim(case), await claim(case)
    await begin(case, first)
    await begin(case, second)
    identifier = await reserve(case, first, "zap", exclusive_key="c" * 64)
    await update(case, first, identifier, state="active", identity={"submission_pending": True})
    with pytest.raises(IntegrityError):
        await reserve(case, second, "zap", exclusive_key="c" * 64)
    with pytest.raises(registry.ScanExecutionUncertain, match="submission"):
        await update(case, first, identifier, state="settled", evidence={"remote_zero": True, "cleanup_complete": True})
    assert (await row(case, first)).zap_owner_key == "c" * 64
    await registry.mark_unresolved(first, reason="unknown-engine-acknowledgement", session_factory=case.sessions)
    assert (await row(case, first)).zap_owner_key == "c" * 64
    assert (await row(case, second)).resources == {}


@pytest.mark.asyncio
async def test_known_remote_settlement_releases_only_its_engine_slot(registry_case):
    case = registry_case
    first, second = await claim(case), await claim(case)
    await begin(case, first)
    await begin(case, second)
    identifier = await reserve(case, first, "zap", exclusive_key="d" * 64)
    await update(case, first, identifier, state="active", identity={"submission_pending": False, "spider_ids": ["0"]})
    await update(case, first, identifier, state="settled", evidence={"remote_zero": True, "cleanup_complete": True})
    assert (await row(case, first)).zap_owner_key is None
    next_id = await reserve(case, second, "zap", exclusive_key="d" * 64)
    assert next_id != identifier
    assert identifier in (await row(case, first)).resources


@pytest.mark.asyncio
async def test_repeated_cancel_is_idempotent_and_transaction_owned(registry_case):
    case = registry_case
    owner = await claim(case)
    assert (await cancel(case, owner.scan_id, commit=False))["status"] == "cancellation_requested"
    assert (await row(case, owner)).cancel_requested_at is None
    one = await cancel(case, owner.scan_id)
    stamp = (await row(case, owner)).cancel_requested_at
    assert await cancel(case, owner.scan_id) == one
    assert (await row(case, owner)).cancel_requested_at == stamp
    with pytest.raises(registry.ScanExecutionCancelled):
        await begin(case, owner)
    assert (await row(case, owner)).phase == "claimed"


@pytest.mark.asyncio
async def test_cancel_blocks_new_resources_not_existing_cleanup(registry_case):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    identifier = await reserve(case, owner)
    await cancel(case, owner.scan_id)
    with pytest.raises(registry.ScanExecutionCancelled):
        await reserve(case, owner)
    await update(case, owner, identifier, state="settled", evidence={"joined": True, "cleanup_complete": True})
    await returned(case, owner, "cancelled")
    assert await settle(case, owner)
    assert (await cancel(case, owner.scan_id))["status"] == "already_settled"


@pytest.mark.asyncio
async def test_cross_tenant_cancel_is_hidden_and_has_no_side_effect(registry_case):
    case = registry_case
    owner = await claim(case)
    with pytest.raises(LookupError):
        await cancel(case, owner.scan_id, organization=case.outsider.organization_id)
    assert (await row(case, owner)).cancel_requested_at is None


@pytest.mark.asyncio
async def test_cancel_pristine_backlog_does_not_claim_execution(registry_case):
    case = registry_case
    identifier = await new_scan(case)
    assert (await cancel(case, identifier, commit=False))["status"] == "cancelled_before_claim"
    async with case.sessions() as session:
        assert (await session.get(SecurityScan, identifier)).status == "queued"
    result = await cancel(case, identifier)
    assert result == {"status": "cancelled_before_claim", "cleanup_verified": True}
    assert await cancel(case, identifier) == result
    assert (await snapshot(case))["is_clear"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"status": "completed"}, {"status": "failed"}, {"status": "running"},
    {"status": "cancelled"}, {"status": "future_unknown"}, {"attempts": 1},
    {"summary": []}, {"summary": {"_execution_guard": {}}},
    {"error_code": "UNCERTAIN"}, {"max_attempts": 0},
    {"summary": {"cancellation_before_claim": {"protocol_version": True, "verified": True}}},
])
async def test_legacy_or_malformed_business_rows_remain_blockers(registry_case, changes):
    case = registry_case
    identifier = await new_scan(case, **changes)
    assert (await cancel(case, identifier))["cleanup_verified"] is False
    observed = await snapshot(case)
    assert observed["legacy_unverified_scan_ids"] == [identifier]
    assert observed["is_clear"] is False


@pytest.mark.asyncio
async def test_business_deletion_does_not_cascade_resource_evidence(registry_case):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    identifier = await reserve(case, owner)
    async with case.sessions() as session, session.begin():
        await session.execute(delete(SecurityScan).where(SecurityScan.id == owner.scan_id))
    assert identifier in (await row(case, owner)).resources
    assert (await snapshot(case))["blocker_count"] == 1
    assert await registry.reconcile_returned_execution(owner.scan_id, session_factory=case.sessions) is False


@pytest.mark.asyncio
async def test_no_new_work_after_unresolved_or_returned_or_settled(registry_case):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    await registry.mark_unresolved(owner, reason="test-uncertain", session_factory=case.sessions)
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await reserve(case, owner)
    await returned(case, owner)
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await reserve(case, owner)
    assert await settle(case, owner)
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await registry.heartbeat_execution(owner, session_factory=case.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("resources", [
    [], "invalid", {"not-a-uuid": {}},
    {"00000000-0000-0000-0000-000000000001": {"kind": [], "state": "active", "identity": {}, "evidence": {}}},
    {"00000000-0000-0000-0000-000000000001": {"kind": "thread", "state": [], "identity": {}, "evidence": {}}},
    {"00000000-0000-0000-0000-000000000001": {"kind": "thread", "state": "settled", "identity": {}, "evidence": {}}},
])
async def test_malformed_registry_never_reports_clear(registry_case, resources):
    case = registry_case
    owner = await claim(case)
    async with case.sessions() as session, session.begin():
        record = await session.get(SecurityScanExecution, owner.execution_id)
        record.resources = resources
    with pytest.raises(registry.ScanExecutionUncertain):
        await snapshot(case)


@pytest.mark.asyncio
async def test_concurrent_resources_are_not_lost_and_settlement_is_monotonic(registry_case):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    identifiers = await asyncio.gather(*(reserve(case, owner) for _ in range(16)))
    assert len(set(identifiers)) == 16
    assert len((await row(case, owner)).resources) == 16
    await asyncio.gather(*(update(case, owner, identifier, state="settled", evidence={
        "joined": True, "cleanup_complete": True,
    }) for identifier in identifiers))
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await update(case, owner, identifiers[0], state="active")
    await returned(case, owner, "completed")
    await registry.supervisor_returned(owner, session_factory=case.sessions)
    assert all(await asyncio.gather(*(registry.reconcile_returned_execution(
        owner.scan_id, session_factory=case.sessions,
    ) for _ in range(8))))
    assert (await row(case, owner)).state == "settled"
    assert (await snapshot(case))["is_clear"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"status": "running", "attempts": 1}, {"status": "failed"},
    {"summary": {"_execution_guard": {"phase": "claimed"}}},
    {"summary": {"execution_cleanup": {"verified": True}}},
    {"started_at": datetime.now(UTC)}, {"error_message": "uncertain"},
])
async def test_registration_cannot_adopt_legacy_or_touched_work(registry_case, changes):
    case = registry_case
    identifier = await new_scan(case, **changes)
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await claim(case, identifier)
    async with case.sessions() as session:
        assert not (await session.scalars(select(SecurityScanExecution))).all()


@pytest.mark.asyncio
async def test_registration_rechecks_authority_before_writes(registry_case):
    case = registry_case
    identifier = await new_scan(case)
    await _shared._close(case)
    with pytest.raises(HostMaintenanceClosed):
        await claim(case, identifier)
    async with case.sessions() as session:
        assert (await session.get(SecurityScan, identifier)).status == "queued"
        assert not (await session.scalars(select(SecurityScanExecution))).all()


@pytest.mark.asyncio
async def test_concurrent_cancel_or_claim_has_no_lost_intent(registry_case):
    case = registry_case
    identifier = await new_scan(case)
    results = await asyncio.gather(claim(case, identifier), cancel(case, identifier), return_exceptions=True)
    accepted = [x for x in results if isinstance(x, registry.ScanExecutionOwnership)]
    if accepted:
        assert results[1]["status"] == "cancellation_requested"
        assert (await row(case, accepted[0])).cancel_requested_at is not None
    else:
        assert isinstance(results[0], registry.ScanExecutionOwnershipLost)
        assert results[1]["status"] == "cancelled_before_claim"
    async with case.sessions() as session:
        scan = await session.get(SecurityScan, identifier)
        assert scan.attempts == (1 if accepted else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["nonce", "status", "guard", "deletion"])
async def test_begin_requires_compatible_business_record(registry_case, change):
    case = registry_case
    owner = await claim(case)
    async with case.sessions() as session, session.begin():
        scan = await session.get(SecurityScan, owner.scan_id)
        if change == "nonce":
            scan.lease_token = str(uuid4())
        elif change == "status":
            scan.status = "queued"
        elif change == "guard":
            scan.summary = {"_execution_guard": {"protocol_version": True, "phase": "claimed", "cleanup_verified": False}}
            # Python considers True == 1; force the deliberately corrupt JSON
            # write so the fixture actually tests a stored boolean, not old 1.
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(scan, "summary")
        else:
            await session.delete(scan)
    with pytest.raises(registry.ScanExecutionOwnershipLost):
        await begin(case, owner)
    assert (await row(case, owner)).phase == "claimed"


@pytest.mark.asyncio
async def test_active_resource_cannot_be_relabelled_never_started(registry_case):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    identifier = await reserve(case, owner)
    await update(case, owner, identifier, state="active")
    with pytest.raises(registry.ScanExecutionUncertain):
        await update(case, owner, identifier, state="settled", evidence={"not_started": True, "cleanup_complete": True})
    assert (await row(case, owner)).resources[identifier]["state"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,key,identity", [
    ("zap", None, None), ("zap", "a", None), ("zap", "G" * 64, None),
    ("thread", "a" * 64, None), ([], None, None),
    ("thread", None, {"password": "must-not-be-recorded"}),
    ("thread", None, {"pid": {"untrusted": True}}),
    ("zap", "f" * 64, {"active_ids": ["-1"]}),
])
async def test_bad_resource_identity_denied_before_registration(registry_case, kind, key, identity):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    with pytest.raises(ValueError):
        await reserve(case, owner, kind, exclusive_key=key, identity=identity)
    assert (await row(case, owner)).resources == {}


@pytest.mark.asyncio
async def test_snapshot_uses_one_repeatable_read_inventory(registry_case):
    case = registry_case
    statements = []
    from sqlalchemy import event
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(case.engine.sync_engine, "before_cursor_execute", capture)
    try:
        assert (await snapshot(case))["is_clear"] is True
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", capture)
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["reserved", "active", "unresolved"])
async def test_business_completed_does_not_clear_unfinished_resources(registry_case, stage):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    identifier = await reserve(case, owner)
    if stage != "reserved":
        await update(case, owner, identifier, state=stage)
    await returned(case, owner, "completed")
    assert await settle(case, owner) is False
    assert (await snapshot(case))["is_clear"] is False
    async with case.sessions() as session:
        scan = await session.get(SecurityScan, owner.scan_id)
        assert scan.status == "completed" and "execution_cleanup" not in scan.summary


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True])
async def test_cancel_and_settle_race_preserves_finished_evidence(registry_case, commit):
    case = registry_case
    owner = await claim(case)
    await begin(case, owner)
    await returned(case, owner, "completed")
    await registry.supervisor_returned(owner, session_factory=case.sessions)
    results = await asyncio.gather(
        registry.reconcile_returned_execution(owner.scan_id, session_factory=case.sessions),
        cancel(case, owner.scan_id, commit=commit),
    )
    assert results[0] is True
    assert results[1]["status"] in {"cancellation_requested", "already_settled"}
    assert (await row(case, owner)).state == "settled"
    assert (await snapshot(case))["is_clear"] is True


@pytest.mark.asyncio
async def test_migration_accepts_current_metadata_bootstrap_without_changing_rows(scan_case):
    case = scan_case
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda bind: SecurityScanExecution.__table__.create(bind))
    owner = await claim(case)
    before = await row(case, owner)
    async with case.engine.begin() as connection:
        await connection.run_sync(_shared._run_migration, "0053", "upgrade")
    after = await row(case, owner)
    assert after.ownership_nonce == before.ownership_nonce
    assert after.resources == before.resources and after.state == before.state
    assert after.started_at == before.started_at


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["nullability", "constraint", "index", "extra_column"])
async def test_migration_refuses_incompatible_preexisting_ledger(registry_case, corruption):
    case = registry_case
    owner = await claim(case)
    async with case.engine.begin() as connection:
        if corruption == "nullability":
            await connection.execute(text("ALTER TABLE security_scan_executions ALTER COLUMN resources DROP NOT NULL"))
        elif corruption == "constraint":
            await connection.execute(text("ALTER TABLE security_scan_executions DROP CONSTRAINT ck_scan_execution_state"))
            await connection.execute(text("ALTER TABLE security_scan_executions ADD CONSTRAINT ck_scan_execution_state CHECK (state IS NOT NULL)"))
        elif corruption == "index":
            await connection.execute(text("DROP INDEX ix_scan_execution_unfinished"))
        else:
            await connection.execute(text("ALTER TABLE security_scan_executions ADD COLUMN unverified_extra text"))
    with pytest.raises(RuntimeError, match="frozen schema"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_shared._run_migration, "0053", "upgrade")
    assert (await row(case, owner)).ownership_nonce == owner.ownership_nonce
