"""FR-06D8C4B6B1 PostgreSQL terminal-candidate acceptance."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.db.models import (
    StudioCrashContainment,
    StudioExecution,
    StudioPoststartCancellation,
    StudioPrestartCancellation,
    StudioSettlement,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_crash_containment as containment
from app.services import studio_crash_terminal_candidate as candidate_service
from app.services import studio_resource_registry as registry
from app.services.studio_result_binding import evidence_digest

_B6A_NAME = "fr06d8c4b6b1_b6a_fixture"
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


async def _prepared(case, monkeypatch, tmp_path):
    _, observation, cleanup_candidate, b4_receipt, b5_receipt = (
        await _b6a._chain(case, monkeypatch, tmp_path)
    )
    row = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=cleanup_candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    return observation, row


async def _counts(case):
    async with case.sessions() as session:
        return (
            await session.scalar(
                select(func.count()).select_from(StudioCrashContainment)
            ),
            await session.scalar(
                select(func.count()).select_from(StudioSettlement)
            ),
            await session.scalar(
                select(func.count()).select_from(StudioPrestartCancellation)
            ),
            await session.scalar(
                select(func.count()).select_from(StudioPoststartCancellation)
            ),
        )


@pytest.mark.asyncio
async def test_valid_b6a_containment_exports_nonterminal_candidate(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    observation, row = await _prepared(case, monkeypatch, tmp_path)

    value = await candidate_service.export_terminal_candidate(
        containment_id=row.id,
        session_factory=case.sessions,
    )

    assert value["containment_id"] == row.id
    assert value["containment_proof_sha256"] == row.proof_sha256
    assert value["observation_id"] == observation.id
    assert value["execution_id"] == row.execution_id
    assert value["publication_id"] == row.publication_id
    assert value["job_id"] == row.job_id
    assert value["containment_operation_id"] == row.proof[
        "maintenance_operation_id"
    ]
    assert value["containment_generation"] == row.proof[
        "maintenance_generation"
    ]
    assert value["containment_boot_id"] == row.proof["boot_id"]
    assert value["quarantine_name"] == row.proof["quarantine_name"]
    assert value["retained_identity"] == row.proof["retained_identity"]
    assert value["host_revalidation_required"] is True
    assert value["quarantine_revalidation_required"] is True
    assert value["terminalization_authorized"] is False
    assert value["blocker_cleared"] is False
    assert value["retry_authorized"] is False
    assert value["cleanup_authorized"] is False
    assert value["settlement_authorized"] is False
    assert value["quarantine_deletion_permitted"] is False
    assert value["final_deletion_permitted"] is False
    assert value["full_host_closure"] is False

    body = {
        key: item
        for key, item in value.items()
        if key != "candidate_sha256"
    }
    assert value["candidate_sha256"] == evidence_digest(body)


@pytest.mark.asyncio
async def test_export_is_deterministic_and_database_read_only(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, row = await _prepared(case, monkeypatch, tmp_path)
    before = await _counts(case)

    first = await candidate_service.export_terminal_candidate(
        containment_id=row.id,
        session_factory=case.sessions,
    )
    second = await candidate_service.export_terminal_candidate(
        containment_id=row.id,
        session_factory=case.sessions,
    )

    assert second == first
    assert await _counts(case) == before


@pytest.mark.asyncio
async def test_open_authority_blocks_terminal_candidate(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, row = await _prepared(case, monkeypatch, tmp_path)
    async with case.sessions() as session:
        current = await admission.read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
    assert current.operation_id is not None
    await admission.open_admission(
        operation_id=current.operation_id,
        expected_generation=current.generation,
        reason="open before terminal candidate",
        session_factory=case.sessions,
    )

    with pytest.raises(
        candidate_service.StudioCrashTerminalCandidateUnavailable,
        match="closed maintenance",
    ):
        await candidate_service.export_terminal_candidate(
            containment_id=row.id,
            session_factory=case.sessions,
        )


@pytest.mark.asyncio
async def test_later_closed_authority_is_bound_without_rewriting_containment(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, row = await _prepared(case, monkeypatch, tmp_path)
    first = await candidate_service.export_terminal_candidate(
        containment_id=row.id,
        session_factory=case.sessions,
    )

    async with case.sessions() as session:
        current = await admission.read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
    assert current.operation_id is not None
    opened = await admission.open_admission(
        operation_id=current.operation_id,
        expected_generation=current.generation,
        reason="roll terminal candidate authority",
        session_factory=case.sessions,
    )
    new_operation = str(uuid4())
    closed = await admission.close_admission(
        operation_id=new_operation,
        expected_generation=opened.generation,
        reason="new terminal candidate authority",
        session_factory=case.sessions,
    )

    second = await candidate_service.export_terminal_candidate(
        containment_id=row.id,
        session_factory=case.sessions,
    )

    assert second["containment_operation_id"] == first[
        "containment_operation_id"
    ]
    assert second["containment_generation"] == first[
        "containment_generation"
    ]
    assert second["containment_boot_id"] == first["containment_boot_id"]
    assert second["reconciliation_authority"]["operation_id"] == new_operation
    assert second["reconciliation_authority"]["generation"] == (
        closed.generation
    )
    assert second["candidate_sha256"] != first["candidate_sha256"]


@pytest.mark.asyncio
async def test_terminal_conflict_blocks_candidate_export(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, row = await _prepared(case, monkeypatch, tmp_path)

    async with case.sessions() as session, session.begin():
        stamp = await registry._now(session)
        session.add(StudioPrestartCancellation(
            id=str(uuid4()),
            execution_id=row.execution_id,
            job_id=row.job_id,
            worker_incarnation=row.worker_incarnation,
            admitted_generation=row.admitted_generation,
            proof={},
            proof_sha256="0" * 64,
            created_at=stamp,
        ))

    with pytest.raises(
        candidate_service.StudioCrashTerminalCandidateUnavailable,
        match="terminal evidence conflicts",
    ):
        await candidate_service.export_terminal_candidate(
            containment_id=row.id,
            session_factory=case.sessions,
        )


@pytest.mark.asyncio
async def test_raw_execution_drift_invalidates_candidate_export(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, row = await _prepared(case, monkeypatch, tmp_path)

    async with case.sessions() as session, session.begin():
        await session.execute(
            update(StudioExecution)
            .where(StudioExecution.id == row.execution_id)
            .values(worker_incarnation=str(uuid4()))
        )

    with pytest.raises(
        candidate_service.StudioCrashTerminalCandidateUnavailable,
        match="containment is invalid",
    ):
        await candidate_service.export_terminal_candidate(
            containment_id=row.id,
            session_factory=case.sessions,
        )


@pytest.mark.asyncio
async def test_missing_containment_is_rejected(containment_case):
    with pytest.raises(
        candidate_service.StudioCrashTerminalCandidateUnavailable,
        match="containment is missing",
    ):
        await candidate_service.export_terminal_candidate(
            containment_id=str(uuid4()),
            session_factory=containment_case.sessions,
        )


@pytest.mark.asyncio
async def test_noncanonical_containment_id_is_rejected(containment_case):
    with pytest.raises(ValueError, match="canonical UUID"):
        await candidate_service.export_terminal_candidate(
            containment_id="not-a-uuid",
            session_factory=containment_case.sessions,
        )
