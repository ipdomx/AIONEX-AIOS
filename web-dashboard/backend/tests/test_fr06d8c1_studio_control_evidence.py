"""Disposable PostgreSQL control-evidence and endpoint regression acceptance.

History reads and control mutations use real isolated schemas and HTTP handlers.
The six original regressions are preserved without xfail or weakened assertions.
No provider or production record is used.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.db.models import AuditEvent, StudioExecution, StudioJob, StudioPublication, StudioSettlement
from app.services.studio_control_evidence import has_retained_studio_evidence

_spec = importlib.util.spec_from_file_location(
    "fr06d8c1_controls_fixture", Path(__file__).with_name("test_fr06c5d8a2a_studio_one_shot.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case
_new, _row = _shared._new, _shared._row
LEDGERS = (StudioExecution, StudioPublication, StudioSettlement)


async def _history(case, job_id, model, generation=7):
    stamp = datetime.now(UTC)
    common = dict(
        id=str(uuid4()), job_id=job_id, worker_incarnation=str(uuid4()),
        admitted_generation=generation,
    )
    if model is StudioExecution:
        row = model(
            **common, ownership_nonce=str(uuid4()), state="unresolved", phase="claimed",
            resources={}, cleanup_verified=False, started_at=stamp, updated_at=stamp,
            unresolved_reason="synthetic retained historical attempt",
        )
    elif model is StudioPublication:
        row = model(
            **common, execution_id=str(uuid4()), thread_resource_id=str(uuid4()),
            ownership_nonce=str(uuid4()), state="reserved", plan={}, events=[],
            created_at=stamp, updated_at=stamp,
        )
    else:
        row = model(
            **common, execution_id=str(uuid4()), publication_id=str(uuid4()),
            proof={}, proof_sha256="0" * 64, created_at=stamp,
        )
    async with case.sessions() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _read(case, job_id):
    async with case.sessions() as session:
        await session.scalar(select(StudioJob.id).where(StudioJob.id == job_id).with_for_update())
        return await has_retained_studio_evidence(session, job_id)


async def _history_rows(case, model):
    async with case.sessions() as session:
        return [deepcopy(dict(row)) for row in (
            await session.execute(select(model.__table__).order_by(model.id))
        ).mappings()]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", LEDGERS)
@pytest.mark.parametrize("generation", [7, 8, 99])
async def test_retained_row_is_evidence_without_status_or_generation_filter(execution_case, model, generation):
    case = execution_case
    job_id = await _new(case)
    await _history(case, job_id, model, generation)
    before = await _history_rows(case, model)
    assert await _read(case, job_id) is True
    assert await _history_rows(case, model) == before
    assert (await _row(case, job_id))["status"] == "queued"
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", LEDGERS)
async def test_foreign_job_evidence_does_not_block_untouched_job(execution_case, model):
    case = execution_case
    target, other = await _new(case), await _new(case)
    await _history(case, other, model)
    assert await _read(case, target) is False
    assert await _read(case, other) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("model", LEDGERS)
async def test_job_deletion_cannot_erase_independent_history(execution_case, model):
    case = execution_case
    job_id = await _new(case)
    await _history(case, job_id, model)
    before = await _history_rows(case, model)
    async with case.sessions() as session:
        item = await session.get(StudioJob, job_id)
        await session.delete(item)
        await session.commit()
    async with case.sessions() as session:
        await session.execute(select(StudioJob.id).where(StudioJob.id == job_id))
        assert await has_retained_studio_evidence(session, job_id) is True
    assert await _history_rows(case, model) == before
    await _new(case, id=job_id)
    assert await _read(case, job_id) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("retained", [False, True])
async def test_evidence_read_has_no_autoflush_or_commit(execution_case, retained):
    case = execution_case
    job_id = await _new(case)
    if retained:
        await _history(case, job_id, StudioExecution)
    writes = []
    def observe(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(case.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with case.sessions() as session:
            await session.scalar(select(StudioJob.id).where(StudioJob.id == job_id).with_for_update())
            session.add(AuditEvent(
                id=str(uuid4()), organization_id=case.actor.organization_id,
                user_id=case.actor.id, action="synthetic.pending", resource_type="test",
                resource_id=job_id, details={},
            ))
            assert await has_retained_studio_evidence(session, job_id) is retained
            assert session.in_transaction() and not writes
            await session.rollback()
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
async def test_empty_history_does_not_mutate_job_or_create_files(execution_case):
    case = execution_case
    job_id = await _new(case)
    before = await _row(case, job_id)
    assert await _read(case, job_id) is False
    assert await _row(case, job_id) == before
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", LEDGERS)
async def test_regression_cancel_must_not_certify_unstarted_when_history_survives(execution_case, model):
    case = execution_case
    job_id = await _new(case)
    await _history(case, job_id, model)
    before = await _history_rows(case, model)
    response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancel_requested", "retained history contradicts never-started cancellation"
    assert (await _row(case, job_id))["completed_at"] is None
    assert await _history_rows(case, model) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("model", LEDGERS)
async def test_regression_retry_must_not_reset_job_when_history_survives(execution_case, model):
    case = execution_case
    job_id = await _new(case, status="cancelled")
    await _history(case, job_id, model)
    before = await _row(case, job_id)
    response = await case.client.post(f"/studio/jobs/{job_id}/retry")
    assert response.status_code == 409, "retained history must reject a destructive pristine reset"
    assert await _row(case, job_id) == before
