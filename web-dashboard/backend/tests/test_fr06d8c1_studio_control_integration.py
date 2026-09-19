"""Retained-history control acceptance with real PostgreSQL locks and HTTP.

All rows belong to disposable per-test schemas. Claim means reservation only;
no archive build, external provider or production database is exercised here.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.endpoints import studio
from app.db.base import get_db
from app.db.models import AuditEvent, Organization, StudioJob, StudioPrestartCancellation, User
from app.services.studio_control_evidence import (
    StudioControlEvidenceUnavailable, has_retained_studio_evidence,
)

_spec = importlib.util.spec_from_file_location(
    "fr06d8c1_evidence_shared", Path(__file__).with_name("test_fr06d8c1_studio_control_evidence.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case
_new, _row, _history, _history_rows = _shared._new, _shared._row, _shared._history, _shared._history_rows
LEDGERS = _shared.LEDGERS
WAIT = 10
UNAVAILABLE = {"detail": "Studio control evidence is currently unavailable."}


async def _audits(case, job_id):
    async with case.sessions() as session:
        return [deepcopy(dict(row)) for row in (
            await session.execute(select(AuditEvent.__table__).where(
                AuditEvent.resource_id == job_id,
            ).order_by(AuditEvent.id))
        ).mappings()]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "retry"])
@pytest.mark.parametrize("model", LEDGERS)
async def test_missing_any_history_table_fails_closed_before_job_or_audit_mutation(execution_case, model, mode):
    case = execution_case
    job_id = await _new(case, status="queued" if mode == "cancel" else "cancelled")
    before = await _row(case, job_id)
    # Identifier comes only from the fixed ORM table tuple above.
    async with case.engine.begin() as connection:
        await connection.execute(text(f'ALTER TABLE "{model.__tablename__}" RENAME TO "unavailable_{model.__tablename__}"'))
    response = await case.client.post(f"/studio/jobs/{job_id}/{mode}")
    assert response.status_code == 503 and response.json() == UNAVAILABLE
    assert await _row(case, job_id) == before and not await _audits(case, job_id)
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", LEDGERS)
async def test_retained_cancel_is_idempotent_and_keeps_independent_rows(execution_case, model):
    case = execution_case
    job_id = await _new(case)
    await _history(case, job_id, model, generation=99)
    before = await _history_rows(case, model)
    first = await case.client.post(f"/studio/jobs/{job_id}/cancel")
    assert first.status_code == 200 and first.json()["status"] == "cancel_requested"
    cancelled = await _row(case, job_id)
    audits = await _audits(case, job_id)
    assert len(audits) == 1 and audits[0]["action"] == "studio.job.cancel_requested"
    assert audits[0]["details"]["cleanup_verified"] is False
    for _ in range(3):
        response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
        assert response.status_code == 200 and response.json() == first.json()
    assert await _row(case, job_id) == cancelled
    assert await _audits(case, job_id) == audits
    assert await _history_rows(case, model) == before
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "retry"])
@pytest.mark.parametrize("foreign", [False, True])
async def test_tenant_lookup_and_missing_job_precede_history_read(execution_case, monkeypatch, mode, foreign):
    case = execution_case
    job_id = str(uuid4())
    if foreign:
        org_id, user_id = str(uuid4()), str(uuid4())
        async with case.sessions() as session:
            session.add(Organization(id=org_id, name="Other synthetic tenant", slug=org_id, plan="enterprise", status="active"))
            await session.flush()
            session.add(User(id=user_id, organization_id=org_id, role_id=None,
                             email=user_id + "@example.invalid", name="Other synthetic user",
                             password_hash="unused", status="active"))
            await session.commit()
        await _new(case, id=job_id, organization_id=org_id, requested_by_id=user_id,
                   status="queued" if mode == "cancel" else "cancelled")
        await _history(case, job_id, LEDGERS[0])
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("tenant rejection must precede evidence read")
    monkeypatch.setattr(studio, "has_retained_studio_evidence", forbidden)
    response = await case.client.post(f"/studio/jobs/{job_id}/{mode}")
    assert response.status_code == 404 and response.json() == {"detail": "Studio job not found"}
    assert not calls and not await _audits(case, job_id)


@pytest.mark.asyncio
async def test_closed_admission_still_accepts_cancellation_intent_but_denies_retry(execution_case):
    case = execution_case
    job_id = await _new(case)
    await _history(case, job_id, LEDGERS[1])
    await _shared._shared._shared._close(case)
    response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
    assert response.status_code == 200 and response.json()["status"] == "cancel_requested"
    before = await _row(case, job_id)
    denied = await case.client.post(f"/studio/jobs/{job_id}/retry")
    assert denied.status_code == 503
    assert await _row(case, job_id) == before


@pytest.mark.asyncio
async def test_cached_job_is_refreshed_after_a_competing_actual_claim(execution_case):
    case = execution_case
    job_id = await _new(case)
    async with case.sessions() as session:
        cached = await session.get(StudioJob, job_id)
        await session.commit()
        assert cached.status == "queued" and cached.attempts == 0
        claim = await case.worker.claim_by_id(job_id)
        assert claim is not None
        result = await studio.cancel_job(job_id, actor=case.actor, session=session)
        assert result["status"] == "cancelled"
        assert cached.attempts == 1 and cached.lease_token is None
    after = await _row(case, job_id)
    assert after["attempts"] == 1 and after["lease_token"] is None
    assert after["completed_at"] == after["cancelled_at"] and not case.root.exists()
    async with case.sessions() as verify:
        receipt = await verify.scalar(select(StudioPrestartCancellation).where(
            StudioPrestartCancellation.job_id == job_id,
        ))
        assert receipt is not None and receipt.execution_id


@pytest.mark.asyncio
async def test_cached_terminal_job_cannot_be_reset_after_concurrent_completion(execution_case):
    case = execution_case
    job_id = await _new(case, status="cancelled")
    async with case.sessions() as session:
        cached = await session.get(StudioJob, job_id)
        await session.commit()
        async with case.sessions() as other:
            item = await other.get(StudioJob, job_id)
            item.status = "completed"
            await other.commit()
        before = await _row(case, job_id)
        with pytest.raises(HTTPException) as caught:
            await studio.retry_job(job_id, actor=case.actor, session=session)
        assert caught.value.status_code == 409 and cached.status == "completed"
        await session.rollback()
    assert await _row(case, job_id) == before


@pytest.mark.asyncio
async def test_locked_lookup_prevents_autoflush_before_tenant_and_row_lock(execution_case):
    case = execution_case
    job_id = await _new(case)
    writes = []
    def observe(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)
    event.listen(case.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with case.sessions() as session:
            session.add(AuditEvent(id=str(uuid4()), organization_id=case.actor.organization_id,
                                  user_id=case.actor.id, action="synthetic.pending", resource_type="test",
                                  resource_id=job_id, details={}))
            job = await studio._job_or_404(session, case.actor, job_id, lock=True)
            assert job.id == job_id and not writes and session.in_transaction()
            assert await has_retained_studio_evidence(session, job_id) is False
            assert not writes
            await session.rollback()
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", observe)
    assert not await _audits(case, job_id)


@pytest.mark.asyncio
async def test_evidence_requires_an_existing_transaction(execution_case):
    async with execution_case.sessions() as session:
        with pytest.raises(StudioControlEvidenceUnavailable):
            await has_retained_studio_evidence(session, str(uuid4()))
        assert not session.in_transaction()


async def _wait_for_blocker(case, blocked_pid, holder_pid):
    async with asyncio.timeout(WAIT):
        while True:
            async with case.sessions() as session:
                blockers = await session.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": blocked_pid})
            if holder_pid in blockers:
                return
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["commit", "rollback"])
async def test_actual_claim_blocks_cancel_until_its_registry_transaction_finishes(execution_case, outcome):
    case = execution_case
    job_id = await _new(case)
    ready, release = asyncio.Event(), asyncio.Event()
    started = asyncio.Queue()
    holder_pid = None
    class HeldClaim(AsyncSession):
        async def commit(self):
            nonlocal holder_pid
            holder_pid = int(await super().scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            await release.wait()
            if outcome == "rollback":
                await self.rollback()
                raise RuntimeError("synthetic claim transaction rollback")
            await super().commit()
    class ObservedControl(AsyncSession):
        async def scalar(self, statement, *args, **kwargs):
            lock = getattr(statement, "_for_update_arg", None)
            if lock is not None and not self.info.get("reported"):
                self.info["reported"] = True
                started.put_nowait(int(await super().scalar(text("SELECT pg_backend_pid()"))))
            return await super().scalar(statement, *args, **kwargs)
    case.worker._session_factory = async_sessionmaker(case.engine, class_=HeldClaim, expire_on_commit=False)
    controls = async_sessionmaker(case.engine, class_=ObservedControl, expire_on_commit=False)
    async def db():
        async with controls() as session:
            yield session
    case.app.dependency_overrides[get_db] = db
    claimant = asyncio.create_task(case.worker.claim_by_id(job_id))
    control = None
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        control = asyncio.create_task(case.client.post(f"/studio/jobs/{job_id}/cancel"))
        pid = await asyncio.wait_for(started.get(), WAIT)
        await _wait_for_blocker(case, pid, holder_pid)
        assert not control.done()
    finally:
        release.set()
        tasks = [claimant] + ([control] if control is not None else [])
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), WAIT)
    assert control is not None
    response = results[1]
    assert not isinstance(response, BaseException) and response.status_code == 200
    if outcome == "commit":
        assert not isinstance(results[0], BaseException)
        assert response.json()["status"] == "cancel_requested"
        assert (await _row(case, job_id))["attempts"] == 1
    else:
        assert isinstance(results[0], RuntimeError)
        assert response.json()["status"] == "cancelled"
        assert (await _row(case, job_id))["attempts"] == 0
    assert not case.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "retry"])
@pytest.mark.parametrize("outcome", ["commit", "rollback"])
async def test_control_holds_job_lock_through_commit_or_rollback(execution_case, mode, outcome):
    case = execution_case
    job_id = await _new(case, status="queued" if mode == "cancel" else "cancelled")
    ready, release = asyncio.Event(), asyncio.Event()
    class HeldControl(AsyncSession):
        async def commit(self):
            ready.set()
            await release.wait()
            if outcome == "rollback":
                await self.rollback()
                raise RuntimeError("synthetic control rollback")
            await super().commit()
    controls = async_sessionmaker(case.engine, class_=HeldControl, expire_on_commit=False)
    async def db():
        async with controls() as session:
            yield session
    case.app.dependency_overrides[get_db] = db
    task = asyncio.create_task(case.client.post(f"/studio/jobs/{job_id}/{mode}"))
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        assert await case.worker.claim_by_id(job_id) is None
    finally:
        release.set()
        result, = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), WAIT)
    if outcome == "commit":
        assert not isinstance(result, BaseException) and result.status_code == 200
    else:
        assert isinstance(result, RuntimeError)
    should_claim = (mode == "retry" and outcome == "commit") or (mode == "cancel" and outcome == "rollback")
    assert (await case.worker.claim_by_id(job_id) is not None) is should_claim
    assert not case.root.exists()
