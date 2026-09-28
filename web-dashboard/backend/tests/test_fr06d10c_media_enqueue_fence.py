"""Real PostgreSQL queue-publication fences; no provider or customer data.

All database/schema mutations use the existing disposable-schema fixture.
Tests call the actual arm/graph functions and the 3D request handler. Storage
and upload callbacks are explicit test doubles, never production resources.
"""
from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import func, select, text

from app.core.auth import UserRecord
from app.db.models import IdentityMediaExecution, MediaAssetGraph, MediaRenderStep, OwnerControlRecord
from app.services import host_maintenance_admission as maintenance
from app.services.identity_media_runtime import arm_execution
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph, create_partial_media_revision
from app.services.media_orchestrator import MediaGraphSpec, MediaNodeSpec
from tests.test_fr06d10a_media_claim_fence import _open, _queue_access, _row, _wait_for_lock
from tests.test_fr06d10a_media_claim_fence import case as case

ARMS = (
    ("design_image_runtime", "arm_design_image_execution", "design_image_executions", {}),
    ("audio_speech_runtime", "arm_audio_speech_execution", "audio_speech_executions", {"approved_max_cost_usd": 0.25}),
    ("audio_transcript_runtime", "arm_audio_transcript_execution", "audio_transcript_executions", {"approved_max_cost_usd": 0.25}),
    ("audio_dubbing_runtime", "arm_audio_dubbing_execution", "audio_dubbing_executions", {"approved_max_total_cost_usd": 0.25}),
    ("audio_music_runtime", "arm_audio_music_execution", "audio_music_executions", {"approved_max_cost_usd": 0.25}),
    ("audio_song_runtime", "arm_audio_song_execution", "audio_song_executions", {
        "approved_max_cost_usd": 0.25, "monthly_user_cap_usd": 1.0,
        "provider_balance_usd": 5.0, "balance_evidence_sha256": "f" * 64}),
    ("video_runtime", "arm_video_execution", "video_executions", {}),
    ("identity_media_runtime", "arm_execution", "identity_media_executions", {}),
)


async def _arm(session, case, entry, identity=None):
    module, name, _, extra = entry
    function = getattr(importlib.import_module("app.services." + module), name)
    return await function(session, organization_id=case.oid, execution_id=identity or str(uuid4()), **extra)


async def _authority(case, state):
    if state == "closed":
        return
    async with case.sessions() as session, session.begin():
        row = await session.get(OwnerControlRecord, case.authority_id)
        if state == "missing":
            await session.delete(row)
        elif state == "schema6":
            row.status, row.enabled = "open", True
            row.payload = {**row.payload, "schema_version": 6, "scope": maintenance.SCAN_REQUEST_COVERAGE_SCOPE}
        elif state == "malformed":
            row.payload = {"unexpected": True}
        else:
            raise AssertionError("Unknown test authority")
    case.sql.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ARMS, ids=[x[0] for x in ARMS])
@pytest.mark.parametrize("state", ["closed", "missing", "schema6", "malformed"])
async def test_denied_arm_never_reads_queue_or_flushes_pending_changes(case, entry, state):
    await _authority(case, state)
    before = await _row(case, OwnerControlRecord, case.authority_id) if state != "missing" else None
    case.sql.clear()
    async with case.sessions() as session:
        pending = OwnerControlRecord(id=str(uuid4()), domain="synthetic-not-published", resource_id=uuid4().hex, payload={})
        session.add(pending)
        with pytest.raises(HTTPException) as raised:
            await _arm(session, case, entry)
        assert raised.value.status_code == 503
        assert not _queue_access(case, entry[2])
        assert pending in session.new
        assert not any(q.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in case.sql)
        await session.rollback()
    if before is not None:
        assert await _row(case, OwnerControlRecord, case.authority_id) == before
    else:
        async with case.sessions() as session:
            assert await session.get(OwnerControlRecord, case.authority_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ARMS, ids=[x[0] for x in ARMS])
async def test_open_arm_keeps_original_execution_validation(case, entry):
    await _open(case)
    async with case.sessions() as session:
        # Missing execution still raises its original domain error, not a
        # spurious maintenance refusal or successful no-op.
        error_names = {
            "design_image_runtime": "DesignImageExecutionError",
            "audio_speech_runtime": "AudioSpeechExecutionError",
            "audio_transcript_runtime": "AudioTranscriptExecutionError",
            "audio_dubbing_runtime": "AudioDubbingExecutionError",
            "audio_music_runtime": "AudioMusicExecutionError",
            "audio_song_runtime": "AudioSongExecutionError",
            "video_runtime": "VideoExecutionError",
            "identity_media_runtime": "IdentityMediaExecutionError",
        }
        domain_error = getattr(importlib.import_module("app.services." + entry[0]), error_names[entry[0]])
        with pytest.raises(domain_error):
            await _arm(session, case, entry)
        assert _queue_access(case, entry[2])
        await session.rollback()


def _spec():
    return MediaGraphSpec(title="Synthetic queue-fence graph", asset_kind="image",
        nodes=(MediaNodeSpec(key="frame", node_type="image", parameters={"operation": "resize"}),),
        edges=(), output_profile="image-png-lossless")


async def _graph(session, case, key):
    return await create_media_graph(session, scope=MediaGraphScope(
        organization_id=case.oid, created_by_id=case.uid), spec=_spec(), idempotency_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["closed", "missing", "schema6", "malformed"])
async def test_closed_graph_cannot_publish_automatically_claimable_render_steps(case, state):
    await _authority(case, state)
    async with case.sessions() as session:
        with pytest.raises(HTTPException) as raised:
            await _graph(session, case, uuid4().hex)
        assert raised.value.status_code == 503
        assert not _queue_access(case, "media_asset_graphs")
        assert not _queue_access(case, "media_render_steps")
        await session.rollback()


async def _planned_identity(case, status="planned"):
    async with case.sessions() as session, session.begin():
        row = IdentityMediaExecution(id=str(uuid4()), organization_id=case.oid, requested_by_id=case.uid,
            operation="synthetic-test", identity_basis="fictional", provider_access="local-test-only",
            model="synthetic", status=status, provider_state="not_started",
            idempotency_key=uuid4().hex, subject_reference="synthetic-fixture")
        session.add(row)
        await session.flush()
        return row.id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["planned", "queued"])
async def test_closed_arm_preserves_existing_row_even_for_duplicate(case, status):
    identity = await _planned_identity(case, status)
    before = await _row(case, IdentityMediaExecution, identity)
    async with case.sessions() as session:
        with pytest.raises(HTTPException) as raised:
            await arm_execution(session, organization_id=case.oid, execution_id=identity)
        assert raised.value.status_code == 503
        await session.rollback()
    assert await _row(case, IdentityMediaExecution, identity) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["identity", "graph"])
@pytest.mark.parametrize("commit", [False, True], ids=["rollback", "commit"])
async def test_publication_commit_or_rollback_precedes_successful_close(case, kind, commit):
    await _open(case)
    identity = await _planned_identity(case) if kind == "identity" else None
    close = None
    async with case.sessions() as session:
        try:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            result = (await arm_execution(session, organization_id=case.oid, execution_id=identity)
                      if identity else await _graph(session, case, uuid4().hex))
            result_id = result.id
            close = asyncio.create_task(maintenance.close_admission(operation_id=case.operation,
                expected_generation=26, reason="Serialize actual queue publication", session_factory=case.sessions))
            await _wait_for_lock(case, pid)
            assert not close.done()
            if commit:
                await session.commit()
            else:
                await session.rollback()
            assert (await asyncio.wait_for(close, 3)).generation == 27
        finally:
            await session.rollback()
            if close is not None:
                if not close.done():
                    close.cancel()
                await asyncio.gather(close, return_exceptions=True)
    async with case.sessions() as session:
        if kind == "identity":
            row = await session.get(IdentityMediaExecution, result_id)
            assert row.status == ("queued" if commit else "planned")
            assert row.attempts == 0 and not row.provider_job_id
        else:
            row = await session.get(MediaAssetGraph, result_id)
            assert (row is not None) is commit
            count = await session.scalar(select(func.count()).select_from(MediaRenderStep)
                                         .where(MediaRenderStep.graph_id == result_id))
            assert count == (1 if commit else 0)


@pytest.mark.asyncio
async def test_closure_first_rejects_arm_after_actual_exclusive_lock_wait(case):
    await _open(case)
    identity = await _planned_identity(case)
    before = await _row(case, IdentityMediaExecution, identity)
    async def enqueue():
        async with case.sessions() as session:
            with pytest.raises(HTTPException) as raised:
                await arm_execution(session, organization_id=case.oid, execution_id=identity)
            assert raised.value.status_code == 503
            await session.rollback()
    task = None
    async with case.sessions() as closer:
        try:
            pid = await closer.scalar(text("SELECT pg_backend_pid()"))
            row = await closer.scalar(select(OwnerControlRecord).where(
                OwnerControlRecord.id == case.authority_id).with_for_update())
            row.status, row.enabled, row.version = "closed", False, 27
            row.payload = {**row.payload, "generation": 27}
            await closer.flush()
            task = asyncio.create_task(enqueue())
            await _wait_for_lock(case, pid)
            assert not task.done()
            await closer.commit()
            await asyncio.wait_for(task, 3)
        finally:
            await closer.rollback()
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert await _row(case, IdentityMediaExecution, identity) == before


@pytest.mark.asyncio
async def test_cached_open_authority_does_not_admit_after_close(case):
    await _open(case)
    identity = await _planned_identity(case)
    async with case.sessions() as stale:
        held = await stale.get(OwnerControlRecord, case.authority_id)
        assert held.status == "open"
        await maintenance.close_admission(operation_id=case.operation, expected_generation=26,
            reason="Invalidate cached open policy", session_factory=case.sessions)
        with pytest.raises(HTTPException) as raised:
            await arm_execution(stale, organization_id=case.oid, execution_id=identity)
        assert raised.value.status_code == 503
        await stale.rollback()
    assert (await _row(case, IdentityMediaExecution, identity))["status"] == "planned"


@pytest.mark.asyncio
async def test_closed_revision_does_not_read_or_publish_a_second_graph(case):
    await _open(case)
    async with case.sessions() as session, session.begin():
        graph = await _graph(session, case, uuid4().hex)
    await maintenance.close_admission(operation_id=case.operation, expected_generation=26,
        reason="Closed before partial revision", session_factory=case.sessions)
    case.sql.clear()
    async with case.sessions() as session:
        with pytest.raises(HTTPException) as raised:
            await create_partial_media_revision(session, graph=graph, created_by_id=case.uid,
                node_parameter_updates={"frame": {"operation": "resize", "width": 32}}, idempotency_key=uuid4().hex)
        assert raised.value.status_code == 503
        assert not _queue_access(case, "media_asset_nodes")
        await session.rollback()


@pytest.mark.asyncio
async def test_closed_3d_handler_rejects_before_upload_storage_or_lookup(case, monkeypatch):
    from app.api.v1.endpoints import three_d_jobs

    lookup = AsyncMock(side_effect=AssertionError("No project lookup under closed maintenance"))
    monkeypatch.setattr(three_d_jobs, "project_for_actor", lookup)
    image = AsyncMock()
    actor = UserRecord(id=case.uid, organization_id=case.oid, organization_name="Synthetic",
        organization_plan="enterprise", email="test@example.invalid", name="Synthetic", role="Builder",
        password_hash="unused", permissions=["projects:write"])
    request = Request({"type": "http", "method": "POST", "path": "/test-only", "headers": []})
    async with case.sessions() as session:
        with pytest.raises(HTTPException) as raised:
            await three_d_jobs.create_three_d_job(project_id=str(uuid4()), request=request,
                image=image, actor=actor, session=session)
        assert raised.value.status_code == 503
        image.read.assert_not_awaited()
        lookup.assert_not_awaited()
        await session.rollback()


@pytest.mark.asyncio
async def test_enqueue_guard_rejects_unknown_consumer_without_database_work(case, monkeypatch):
    from app.services import host_maintenance_media_enqueue as fence

    case.sql.clear()
    async with case.sessions() as session:
        with pytest.raises(ValueError, match="Unknown"):
            await fence.require_media_enqueue_admission(session, consumer="not-a-media-producer")
        assert not case.sql
        async def programming_error(_session):
            raise RuntimeError("Synthetic programming failure")
        monkeypatch.setattr(fence, "require_studio_admission", programming_error)
        with pytest.raises(RuntimeError, match="Synthetic"):
            await fence.require_media_enqueue_admission(session, consumer="audio_song")
        await session.rollback()


@pytest.mark.asyncio
async def test_readonly_lock_failure_is_503_not_open_or_repaired_authority(case):
    from app.services.host_maintenance_media_enqueue import require_media_enqueue_admission

    await _open(case)
    before = await _row(case, OwnerControlRecord, case.authority_id)
    async with case.sessions() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        with pytest.raises(HTTPException) as raised:
            await require_media_enqueue_admission(session, consumer="audio_song")
        assert raised.value.status_code == 503
        assert raised.value.detail["code"] == "MEDIA_MAINTENANCE_UNAVAILABLE"
        await session.rollback()
    assert await _row(case, OwnerControlRecord, case.authority_id) == before


@pytest.mark.asyncio
async def test_open_graph_duplicate_preserves_single_queue_publication(case):
    await _open(case)
    key = uuid4().hex
    async with case.sessions() as session, session.begin():
        first = await _graph(session, case, key)
    async with case.sessions() as session, session.begin():
        second = await _graph(session, case, key)
        assert second.id == first.id
        assert await session.scalar(select(func.count()).select_from(MediaRenderStep)
                                    .where(MediaRenderStep.graph_id == first.id)) == 1


@pytest.mark.asyncio
async def test_cancelled_publisher_rolls_back_before_closure_can_complete(case):
    await _open(case)
    identity = await _planned_identity(case)
    armed = asyncio.Event()
    holder = {}
    async def publisher():
        async with case.sessions() as session, session.begin():
            holder["pid"] = await session.scalar(text("SELECT pg_backend_pid()"))
            await arm_execution(session, organization_id=case.oid, execution_id=identity)
            armed.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(publisher())
    closing = None
    try:
        await asyncio.wait_for(armed.wait(), 3)
        closing = asyncio.create_task(maintenance.close_admission(operation_id=case.operation,
            expected_generation=26, reason="Cancel uncommitted publisher", session_factory=case.sessions))
        await _wait_for_lock(case, holder["pid"])
        assert not closing.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await asyncio.wait_for(closing, 3)).generation == 27
        assert (await _row(case, IdentityMediaExecution, identity))["status"] == "planned"
    finally:
        if not task.done():
            task.cancel()
        if closing is not None and not closing.done():
            closing.cancel()
        await asyncio.gather(task, *([closing] if closing else []), return_exceptions=True)
