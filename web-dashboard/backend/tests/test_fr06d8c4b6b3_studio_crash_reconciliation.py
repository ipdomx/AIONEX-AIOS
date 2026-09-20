"""FR-06D8C4B6B3 PostgreSQL terminal crash reconciliation acceptance."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.db.models import (
    StudioCrashReconciliation,
    StudioExecution,
    StudioPrestartCancellation,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_crash_containment as containment
from app.services import studio_crash_reconciliation as reconciliation
from app.services import studio_crash_terminal_candidate as terminal_candidate
from app.services import studio_resource_registry as registry
from app.services.studio_result_binding import evidence_digest

_B6A_NAME = "fr06d8c4b6b3_b6a_fixture"
_B6A_SPEC = importlib.util.spec_from_file_location(
    _B6A_NAME,
    Path(__file__).with_name(
        "test_fr06d8c4b6a_studio_crash_containment.py"
    ),
)
assert _B6A_SPEC is not None and _B6A_SPEC.loader is not None
_b6a = importlib.util.module_from_spec(_B6A_SPEC)
sys.modules[_B6A_NAME] = _b6a
_B6A_SPEC.loader.exec_module(_b6a)

studio_case = _b6a.studio_case
execution_case = _b6a.execution_case
publication_case = _b6a.publication_case
containment_case = _b6a.containment_case

REPO = Path(__file__).resolve().parents[3]
_B6B2_SPEC = importlib.util.spec_from_file_location(
    "fr06d8c4b6b3_host_revalidation",
    REPO / "scripts/security/fr06d8c4_studio_quarantine_revalidation.py",
)
assert _B6B2_SPEC is not None and _B6B2_SPEC.loader is not None
b6b2 = importlib.util.module_from_spec(_B6B2_SPEC)
sys.modules["fr06d8c4b6b3_host_revalidation"] = b6b2
_B6B2_SPEC.loader.exec_module(b6b2)


@pytest_asyncio.fixture
async def reconciliation_case(containment_case):
    case = containment_case
    async with case.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: StudioCrashReconciliation.__table__.create(
                conn, checkfirst=True
            )
        )
    return case


def _redigest(value: dict, key: str) -> dict:
    body = {name: item for name, item in value.items() if name != key}
    value[key] = evidence_digest(body)
    return value


async def _prepared(case, monkeypatch, tmp_path):
    (
        _claim,
        observation,
        cleanup_candidate,
        scan_receipt,
        quarantine_receipt,
    ) = await _b6a._chain(case, monkeypatch, tmp_path)
    containment_row = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=cleanup_candidate,
        process_scan_receipt=scan_receipt,
        staging_quarantine_receipt=quarantine_receipt,
    )
    candidate = await terminal_candidate.export_terminal_candidate(
        containment_id=containment_row.id,
        session_factory=case.sessions,
    )
    host_receipt = b6b2.evaluate(
        terminal_candidate=candidate,
        container_provider=lambda: _b6a._containers(case.root),
        proc_root=tmp_path / "proc",
        boot_id="boot-b6b3-host-revalidation",
    )
    return observation, containment_row, candidate, host_receipt


async def _count(case) -> int:
    async with case.sessions() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(StudioCrashReconciliation)
            )
            or 0
        )


@pytest.mark.asyncio
async def test_full_b6_chain_records_terminal_reconciliation_and_clears_exact_two_blockers(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    observation, containment_row, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    before = await registry.execution_snapshot(session_factory=case.sessions)

    row = await reconciliation.record_crash_reconciliation(
        session_factory=case.sessions,
        terminal_candidate_input=candidate,
        quarantine_revalidation_receipt=host_receipt,
    )
    after = await registry.execution_snapshot(session_factory=case.sessions)

    assert row.containment_id == containment_row.id
    assert row.observation_id == observation.id
    assert row.proof["terminal_state"] == "crash_reconciled_quarantine_retained"
    assert row.proof["terminalization_authorized"] is True
    assert row.proof["blocker_cleared"] is True
    assert row.proof["quarantine_retained"] is True
    assert row.proof["retry_authorized"] is False
    assert row.proof["cleanup_authorized"] is False
    assert row.proof["settlement_authorized"] is False
    assert row.proof["quarantine_deletion_permitted"] is False
    assert row.proof["final_deletion_permitted"] is False
    assert row.proof["process_drain_verified"] is False
    assert row.proof["full_host_closure"] is False

    assert before["blocker_count"] >= 2
    assert after["blocker_count"] == before["blocker_count"] - 2
    assert after["postcrash_reconciliation_count"] == 1
    assert after["valid_postcrash_reconciliation_count"] == 1
    assert after["invalid_postcrash_reconciliation_count"] == 0
    assert after["postcrash_reconciliations"][0]["blocker_cleared"] is True
    crash = next(
        item
        for item in after["postcrash_observations"]
        if item["observation_id"] == observation.id
    )
    assert crash["terminal_reconciliation_recorded"] is True
    assert crash["requires_reconciliation"] is False
    containment_item = next(
        item
        for item in after["postcrash_containments"]
        if item["containment_id"] == containment_row.id
    )
    assert containment_item["terminal_reconciliation_recorded"] is True
    assert containment_item["requires_reconciliation"] is False


@pytest.mark.asyncio
async def test_exact_replay_is_idempotent_after_authority_rollover(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, _containment, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    first = await reconciliation.record_crash_reconciliation(
        session_factory=case.sessions,
        terminal_candidate_input=candidate,
        quarantine_revalidation_receipt=host_receipt,
    )

    async with case.sessions() as session:
        current = await admission.read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
    assert current.operation_id is not None
    opened = await admission.open_admission(
        operation_id=current.operation_id,
        expected_generation=current.generation,
        reason="roll after terminal reconciliation",
        session_factory=case.sessions,
    )
    await admission.close_admission(
        operation_id=str(uuid4()),
        expected_generation=opened.generation,
        reason="new authority after terminal reconciliation",
        session_factory=case.sessions,
    )

    second = await reconciliation.record_crash_reconciliation(
        session_factory=case.sessions,
        terminal_candidate_input=candidate,
        quarantine_revalidation_receipt=host_receipt,
    )
    assert second.id == first.id
    assert await _count(case) == 1


@pytest.mark.asyncio
async def test_authority_rollover_before_first_record_rejects_stale_host_proof(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, _containment, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    async with case.sessions() as session:
        current = await admission.read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
    assert current.operation_id is not None
    opened = await admission.open_admission(
        operation_id=current.operation_id,
        expected_generation=current.generation,
        reason="roll before B6B3",
        session_factory=case.sessions,
    )
    await admission.close_admission(
        operation_id=str(uuid4()),
        expected_generation=opened.generation,
        reason="new B6B3 authority",
        session_factory=case.sessions,
    )

    with pytest.raises(
        reconciliation.StudioCrashReconciliationUnavailable,
        match="authority changed",
    ):
        await reconciliation.record_crash_reconciliation(
            session_factory=case.sessions,
            terminal_candidate_input=candidate,
            quarantine_revalidation_receipt=host_receipt,
        )
    assert await _count(case) == 0


@pytest.mark.asyncio
async def test_terminal_conflict_blocks_new_crash_reconciliation(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, containment_row, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    async with case.sessions() as session, session.begin():
        stamp = await registry._now(session)
        session.add(
            StudioPrestartCancellation(
                id=str(uuid4()),
                execution_id=containment_row.execution_id,
                job_id=containment_row.job_id,
                worker_incarnation=containment_row.worker_incarnation,
                admitted_generation=containment_row.admitted_generation,
                proof={},
                proof_sha256="0" * 64,
                created_at=stamp,
            )
        )

    with pytest.raises(
        reconciliation.StudioCrashReconciliationUnavailable,
        match="conflicting terminal evidence",
    ):
        await reconciliation.record_crash_reconciliation(
            session_factory=case.sessions,
            terminal_candidate_input=candidate,
            quarantine_revalidation_receipt=host_receipt,
        )


@pytest.mark.asyncio
async def test_tampered_host_safety_flag_is_rejected_even_with_fresh_digest(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, _containment, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    changed = deepcopy(host_receipt)
    changed["archive_content_revalidated"] = False
    _redigest(changed, "receipt_sha256")

    with pytest.raises(
        reconciliation.StudioCrashReconciliationUnavailable,
        match="safety boundary",
    ):
        await reconciliation.record_crash_reconciliation(
            session_factory=case.sessions,
            terminal_candidate_input=candidate,
            quarantine_revalidation_receipt=changed,
        )


@pytest.mark.asyncio
async def test_candidate_archive_digest_cannot_drift_from_publication(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, _containment, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    changed = deepcopy(candidate)
    changed["archive_checksum_sha256"] = "f" * 64
    _redigest(changed, "candidate_sha256")
    host = deepcopy(host_receipt)
    host["terminal_candidate_sha256"] = changed["candidate_sha256"]
    host["archive_checksum_sha256"] = changed["archive_checksum_sha256"]
    _redigest(host, "receipt_sha256")

    with pytest.raises(
        reconciliation.StudioCrashReconciliationUnavailable,
        match="durable crash evidence",
    ):
        await reconciliation.record_crash_reconciliation(
            session_factory=case.sessions,
            terminal_candidate_input=changed,
            quarantine_revalidation_receipt=host,
        )


@pytest.mark.asyncio
async def test_raw_execution_drift_after_host_revalidation_blocks_terminal_record(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, containment_row, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    async with case.sessions() as session, session.begin():
        await session.execute(
            update(StudioExecution)
            .where(StudioExecution.id == containment_row.execution_id)
            .values(worker_incarnation=str(uuid4()))
        )

    with pytest.raises(
        reconciliation.StudioCrashReconciliationUnavailable,
        match="invalid|durable crash evidence",
    ):
        await reconciliation.record_crash_reconciliation(
            session_factory=case.sessions,
            terminal_candidate_input=candidate,
            quarantine_revalidation_receipt=host_receipt,
        )


@pytest.mark.asyncio
async def test_future_host_receipt_is_rejected(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, _containment, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    changed = deepcopy(host_receipt)
    changed["observed_at"] = (
        datetime.now(UTC) + timedelta(days=1)
    ).isoformat()
    _redigest(changed, "receipt_sha256")

    with pytest.raises(
        reconciliation.StudioCrashReconciliationUnavailable,
        match="outside the current authority window",
    ):
        await reconciliation.record_crash_reconciliation(
            session_factory=case.sessions,
            terminal_candidate_input=candidate,
            quarantine_revalidation_receipt=changed,
        )


@pytest.mark.asyncio
async def test_different_host_receipt_cannot_replace_existing_terminal_record(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, _containment, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    await reconciliation.record_crash_reconciliation(
        session_factory=case.sessions,
        terminal_candidate_input=candidate,
        quarantine_revalidation_receipt=host_receipt,
    )

    changed = deepcopy(host_receipt)
    changed["current_boot_id"] = "different-host-boot"
    changed["same_boot_as_containment"] = False
    _redigest(changed, "receipt_sha256")

    with pytest.raises(
        reconciliation.StudioCrashReconciliationUnavailable,
        match="existing crash reconciliation differs",
    ):
        await reconciliation.record_crash_reconciliation(
            session_factory=case.sessions,
            terminal_candidate_input=candidate,
            quarantine_revalidation_receipt=changed,
        )
    assert await _count(case) == 1


@pytest.mark.asyncio
async def test_raw_drift_after_terminal_record_turns_reconciliation_invalid_not_clear(
    reconciliation_case, monkeypatch, tmp_path
):
    case = reconciliation_case
    _observation, containment_row, candidate, host_receipt = await _prepared(
        case, monkeypatch, tmp_path
    )
    await reconciliation.record_crash_reconciliation(
        session_factory=case.sessions,
        terminal_candidate_input=candidate,
        quarantine_revalidation_receipt=host_receipt,
    )
    async with case.sessions() as session, session.begin():
        await session.execute(
            update(StudioExecution)
            .where(StudioExecution.id == containment_row.execution_id)
            .values(worker_incarnation=str(uuid4()))
        )

    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["valid_postcrash_reconciliation_count"] == 0
    assert snapshot["invalid_postcrash_reconciliation_count"] == 1
    assert snapshot["postcrash_reconciliations"][0][
        "requires_reconciliation"
    ] is True
    assert snapshot["postcrash_reconciliations"][0]["blocker_cleared"] is False
    assert snapshot["blocker_count"] > 0
    assert snapshot["is_clear"] is False
