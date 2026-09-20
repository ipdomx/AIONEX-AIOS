"""FR-06D8C4B3 cleanup-candidate export on disposable PostgreSQL/files."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import (
    StudioPrestartCancellation,
    StudioPublication,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_cleanup_candidate as candidate
from app.services import studio_crash_observation as crash
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry

_spec = importlib.util.spec_from_file_location(
    "fr06d8c4b3_crash_fixture",
    Path(__file__).with_name("test_fr06d8c4_studio_postcrash_observation.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case
publication_case = _shared.publication_case


async def _crash_publication(case, monkeypatch, *, failure, after_commit):
    claim, _ = await _shared._shared._store_owner(case)
    args = _shared._shared._args(case.root)
    args["organization_id"] = case.actor.organization_id
    original = journal.persist_event

    async def fail(**kwargs):
        if kwargs["operation"] == failure and not after_commit:
            raise RuntimeError("synthetic pre-ack crash")
        await original(**kwargs)
        if kwargs["operation"] == failure and after_commit:
            raise RuntimeError("synthetic post-ack crash")

    monkeypatch.setattr(journal, "persist_event", fail)
    with pytest.raises(registry.StudioResourceUncertain):
        await _shared._shared._publish(case, claim, args)
    await _shared._close(case)
    observation = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=claim[0],
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert observation is not None
    return claim, observation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "after_commit", "layout"),
    [
        ("link_intent", False, "owned_staging_present"),
        ("published", True, "owned_staging_and_final_hardlinks"),
        ("complete", True, "owned_final_present"),
    ],
)
async def test_candidate_exports_only_safe_relative_identity(
    publication_case, monkeypatch, failure, after_commit, layout
):
    case = publication_case
    _, observation = await _crash_publication(
        case, monkeypatch, failure=failure, after_commit=after_commit
    )
    result = await candidate.export_cleanup_candidate(
        observation_id=observation.id,
        session_factory=case.sessions,
    )
    assert result["layout"] == layout
    assert len(result["relative_components"]) == 3
    assert result["relative_components"][0] == case.actor.organization_id
    assert "/" not in result["staging_name"]
    assert "/" not in result["final_name"]
    assert result["final_deletion_permitted"] is False
    assert result["cleanup_authorized"] is False
    assert result["filesystem_mutation_performed"] is False
    assert result["full_host_closure"] is False
    expected_action = (
        "remove_owned_staging"
        if layout != "owned_final_present"
        else "no_staging_mutation_required"
    )
    assert result["action"] == expected_action
    assert result["process_reference_scan_required"] is (
        expected_action == "remove_owned_staging"
    )
    assert len(result["candidate_sha256"]) == 64
    serialized = str(result)
    assert str(case.root) not in serialized


@pytest.mark.asyncio
async def test_failed_write_with_removed_staging_exports_no_mutation_candidate(
    publication_case, monkeypatch
):
    case = publication_case
    claim, _ = await _shared._shared._store_owner(case)
    args = _shared._shared._args(case.root)
    args["organization_id"] = case.actor.organization_id

    def fail_write(_descriptor, _content):
        raise OSError("synthetic write crash")

    monkeypatch.setattr(_shared._shared.publication, "_write_bytes", fail_write)
    with pytest.raises(OSError):
        await _shared._shared._publish(case, claim, args)
    assert not list(case.root.rglob("*.partial"))
    assert not list(case.root.rglob("*.zip"))
    await _shared._close(case)
    observation = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=claim[0],
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert observation is not None
    assert observation.proof["layout"] == "no_archive_entry"

    result = await candidate.export_cleanup_candidate(
        observation_id=observation.id,
        session_factory=case.sessions,
    )
    assert result["action"] == "no_staging_mutation_required"
    assert result["process_reference_scan_required"] is False


@pytest.mark.asyncio
async def test_observation_without_publication_has_no_cleanup_candidate(publication_case):
    case = publication_case
    job_id = await _shared._shared._shared._shared._new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None
    await _shared._close(case)
    observation = await crash.observe_postcrash_state(
        session_factory=case.sessions,
        job_id=job_id,
        nonce=claim[1],
        worker_incarnation=case.worker.incarnation,
    )
    assert observation is not None and observation.publication_id is None
    with pytest.raises(
        candidate.StudioCleanupCandidateUnavailable,
        match="no publication",
    ):
        await candidate.export_cleanup_candidate(
            observation_id=observation.id,
            session_factory=case.sessions,
        )


@pytest.mark.asyncio
async def test_publication_mutation_after_observation_is_rejected(
    publication_case, monkeypatch
):
    case = publication_case
    _, observation = await _crash_publication(
        case, monkeypatch, failure="link_intent", after_commit=False
    )
    async with case.sessions() as session:
        row = await session.get(StudioPublication, observation.publication_id)
        row.events = [*row.events, {"operation": "foreign", "payload": {}, "at": datetime.now(UTC).isoformat()}]
        await session.commit()
    with pytest.raises(
        candidate.StudioCleanupCandidateUnavailable,
        match="changed after crash observation",
    ):
        await candidate.export_cleanup_candidate(
            observation_id=observation.id,
            session_factory=case.sessions,
        )


@pytest.mark.asyncio
async def test_new_maintenance_operation_invalidates_old_candidate(
    publication_case, monkeypatch
):
    case = publication_case
    _, observation = await _crash_publication(
        case, monkeypatch, failure="link_intent", after_commit=False
    )
    async with case.sessions() as session:
        snapshot = await admission.read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
    assert snapshot.operation_id is not None
    opened = await admission.open_admission(
        operation_id=snapshot.operation_id,
        expected_generation=snapshot.generation,
        reason="candidate epoch rollover",
        session_factory=case.sessions,
    )
    await admission.close_admission(
        operation_id=str(uuid4()),
        expected_generation=opened.generation,
        reason="new maintenance operation",
        session_factory=case.sessions,
    )
    with pytest.raises(
        candidate.StudioCleanupCandidateUnavailable,
        match="ownership differs",
    ):
        await candidate.export_cleanup_candidate(
            observation_id=observation.id,
            session_factory=case.sessions,
        )


@pytest.mark.asyncio
async def test_conflicting_terminal_receipt_blocks_candidate(
    publication_case, monkeypatch
):
    case = publication_case
    _, observation = await _crash_publication(
        case, monkeypatch, failure="link_intent", after_commit=False
    )
    async with case.sessions() as session:
        execution = await session.get(
            __import__("app.db.models", fromlist=["StudioExecution"]).StudioExecution,
            observation.execution_id,
        )
        session.add(
            StudioPrestartCancellation(
                id=str(uuid4()),
                execution_id=observation.execution_id,
                job_id=observation.job_id,
                worker_incarnation=observation.worker_incarnation,
                admitted_generation=observation.admitted_generation,
                proof={"synthetic": True},
                proof_sha256="0" * 64,
                created_at=execution.updated_at,
            )
        )
        await session.commit()
    with pytest.raises(
        candidate.StudioCleanupCandidateUnavailable,
        match="conflicting terminal",
    ):
        await candidate.export_cleanup_candidate(
            observation_id=observation.id,
            session_factory=case.sessions,
        )


@pytest.mark.asyncio
async def test_candidate_export_is_read_only(publication_case, monkeypatch):
    case = publication_case
    _, observation = await _crash_publication(
        case, monkeypatch, failure="link_intent", after_commit=False
    )
    async with case.sessions() as session:
        before = deepcopy(
            dict(
                (
                    await session.execute(
                        select(StudioPublication.__table__).where(
                            StudioPublication.id == observation.publication_id
                        )
                    )
                ).mappings().one()
            )
        )
    first = await candidate.export_cleanup_candidate(
        observation_id=observation.id,
        session_factory=case.sessions,
    )
    second = await candidate.export_cleanup_candidate(
        observation_id=observation.id,
        session_factory=case.sessions,
    )
    assert first == second
    async with case.sessions() as session:
        after = deepcopy(
            dict(
                (
                    await session.execute(
                        select(StudioPublication.__table__).where(
                            StudioPublication.id == observation.publication_id
                        )
                    )
                ).mappings().one()
            )
        )
    assert after == before
