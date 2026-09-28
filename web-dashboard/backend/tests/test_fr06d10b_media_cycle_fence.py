"""Real PostgreSQL fences for worker work outside the ordinary claim method.

No real provider or customer storage is used. Balance/storage callbacks are
explicit test doubles; PostgreSQL transactions, locks and row mutations are real.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.base import Base
from app.db.models import (
    AudioDubbingExecution, AudioSongExecution, MediaAssetGraph, MediaAssetNode,
    OwnerControlRecord, Project, ThreeDArtifact, ThreeDGenerationJob, Workspace,
)
from app.services import audio_dubbing_worker as dubbing
from app.services import audio_song_worker as song
from app.services import host_maintenance_admission as maintenance
from app.services import three_d_worker as three_d
from tests.test_fr06d10a_media_claim_fence import _open, _queue_access, _row
from tests.test_fr06d10a_media_claim_fence import case as case  # reusable isolated-schema fixture


@pytest_asyncio.fixture
async def cycle_case(case, monkeypatch):
    async with case.engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ThreeDArtifact.__table__]))
    for module in (song, dubbing, three_d):
        monkeypatch.setattr(module, "SessionLocal", case.sessions)
    case.sql.clear()
    return case


def _worker(kind):
    if kind == "song":
        worker = object.__new__(song.AudioSongWorker)
        worker._next_balance_check_at = 0.0
        worker._runtime_secrets = lambda: SimpleNamespace(endpoint_id_sha256="e" * 64)
        worker._provider_balance_usd = AsyncMock(return_value=(5.0, "f" * 64))
        return worker, worker._arm_one_user_approved
    if kind == "dubbing":
        worker = object.__new__(dubbing.AudioDubbingWorker)
        return worker, worker._advance_one
    worker = object.__new__(three_d.ThreeDGenerationWorker)
    worker.next_cleanup_at = 0.0
    worker.last_cleanup_at = None
    worker.storage = SimpleNamespace(delete=lambda key: None)
    return worker, worker._cleanup_if_due


async def _song(case):
    async with case.sessions() as session, session.begin():
        graph = MediaAssetGraph(id=str(uuid4()), organization_id=case.oid, created_by_id=case.uid,
            title="Synthetic maintenance song", asset_kind="audio", output_profile="test",
            idempotency_key=uuid4().hex, graph_checksum="a" * 64)
        session.add(graph)
        await session.flush()
        node = MediaAssetNode(id=str(uuid4()), graph_id=graph.id, organization_id=case.oid,
            created_by_id=case.uid, logical_key="test", node_type="audio", idempotency_key=uuid4().hex)
        session.add(node)
        await session.flush()
        row = AudioSongExecution(id=str(uuid4()), organization_id=case.oid, requested_by_id=case.uid,
            graph_id=graph.id, target_node_id=node.id, route_id="runpod-flex-a40", provider="runpod",
            model="synthetic", model_revision="a" * 64, language_model="synthetic",
            language_model_revision="b" * 64, source_commit="c" * 40,
            separation_model="synthetic", separation_revision="d" * 64,
            separation_source_commit="d" * 40, separation_checkpoint_sha256="d" * 64,
            idempotency_key=uuid4().hex, plan_checksum="a" * 64, runtime_evidence_sha256="b" * 64,
            pricing_evidence_sha256="c" * 64, license_evidence_sha256="d" * 64,
            title_sha256="a" * 64, title_characters=1, concept_sha256="a" * 64,
            concept_characters=1, lyrics_sha256="a" * 64, lyrics_characters=1, language="en",
            duration_seconds=30, bpm=100, musical_key="Am", time_signature=4, seed=1,
            output_profile_id="test", rights_basis="original", cost_basis="synthetic",
            max_cost_usd=0.25, endpoint_id_sha256="e" * 64, status="planned", provider_state="not_started",
            provider_metadata={"user_cost_approved": True, "approved_max_cost_usd": 0.25,
                               "monthly_user_cap_usd": 1.0})
        session.add(row)
        await session.flush()
        return row.id


async def _dub(case, status):
    async with case.sessions() as session, session.begin():
        row = AudioDubbingExecution(id=str(uuid4()), organization_id=case.oid, requested_by_id=case.uid,
            idempotency_key=uuid4().hex, provider="synthetic", model="synthetic", status=status,
            source_transcript_storage_backend="local", source_transcript_storage_key="synthetic/test.json",
            source_transcript_object_checksum="a" * 64, source_transcript_object_size_bytes=2,
            source_transcript_checksum="b" * 64, source_language="en", target_language="fr",
            segment_count=1, speaker_count=1, output_profile_id="test")
        session.add(row)
        await session.flush()
        return row.id


async def _artifact(case):
    async with case.sessions() as session, session.begin():
        workspace = Workspace(id=str(uuid4()), organization_id=case.oid, name="Synthetic", slug=uuid4().hex)
        session.add(workspace)
        await session.flush()
        project = Project(id=str(uuid4()), organization_id=case.oid, workspace_id=workspace.id,
            owner_id=case.uid, name="Synthetic", slug=uuid4().hex)
        session.add(project)
        await session.flush()
        job = ThreeDGenerationJob(id=str(uuid4()), organization_id=case.oid, workspace_id=workspace.id,
            project_id=project.id, requested_by_id=case.uid, input_object_key="synthetic/input.png",
            input_content_type="image/png", input_size_bytes=10, input_sha256="a" * 64, status="completed")
        session.add(job)
        await session.flush()
        artifact = ThreeDArtifact(id=str(uuid4()), organization_id=case.oid, project_id=project.id,
            job_id=job.id, created_by_id=case.uid, filename="synthetic.glb", object_key="synthetic/result.glb",
            checksum="a" * 64, size_bytes=12, status="ready", expires_at=datetime.now(UTC) - timedelta(seconds=1))
        session.add(artifact)
        await session.flush()
        return artifact.id


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,table", [("song", "audio_song_executions"), ("dubbing", "audio_dubbing_executions"), ("cleanup", "three_d_artifacts")])
@pytest.mark.parametrize("state", ["closed", "missing", "malformed", "schema6"])
async def test_unavailable_cycle_stops_before_work_read_or_policy_initialization(cycle_case, kind, table, state):
    case = cycle_case
    if state != "closed":
        async with case.sessions() as session, session.begin():
            row = await session.get(OwnerControlRecord, case.authority_id)
            if state == "missing":
                await session.delete(row)
            else:
                row.enabled, row.status = True, "open"
                row.payload = ({"unexpected": True} if state == "malformed" else {
                    **row.payload, "schema_version": 6, "scope": maintenance.SCAN_REQUEST_COVERAGE_SCOPE})
    case.sql.clear()
    worker, call = _worker(kind)
    await call()
    assert not _queue_access(case, table)
    assert not any(query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in case.sql)
    if kind == "song":
        worker._provider_balance_usd.assert_not_awaited()


@pytest.mark.asyncio
async def test_closed_song_keeps_user_approval_and_lease_unchanged(cycle_case):
    identity = await _song(cycle_case)
    before = await _row(cycle_case, AudioSongExecution, identity)
    worker, call = _worker("song")
    assert await call() is False
    assert await _row(cycle_case, AudioSongExecution, identity) == before
    worker._provider_balance_usd.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["speech_running", "speech_completed", "rendering"])
async def test_closed_dubbing_never_enters_any_pipeline_branch(cycle_case, monkeypatch, status):
    identity = await _dub(cycle_case, status)
    before = await _row(cycle_case, AudioDubbingExecution, identity)
    effects = []
    async def forbidden(*args, **kwargs):
        effects.append(True)
        return "unchanged"
    for name in ["refresh_dubbing_speech_status", "create_dubbing_final_pipeline", "finalize_dubbing_execution"]:
        monkeypatch.setattr(dubbing, name, forbidden)
    _, call = _worker("dubbing")
    assert await call() is False
    assert effects == []
    assert await _row(cycle_case, AudioDubbingExecution, identity) == before


@pytest.mark.asyncio
async def test_closed_cleanup_preserves_expired_artifact_without_storage_calls(cycle_case):
    identity = await _artifact(cycle_case)
    before = await _row(cycle_case, ThreeDArtifact, identity)
    worker, call = _worker("cleanup")
    deleted = []
    worker.storage = SimpleNamespace(delete=deleted.append)
    await call()
    assert deleted == []
    assert worker.next_cleanup_at == 0.0 and worker.last_cleanup_at is None
    assert await _row(cycle_case, ThreeDArtifact, identity) == before


@pytest.mark.asyncio
async def test_open_song_arms_only_after_exact_balance_authorization(cycle_case):
    await _open(cycle_case)
    identity = await _song(cycle_case)
    worker, call = _worker("song")
    assert await call() is True
    row = await _row(cycle_case, AudioSongExecution, identity)
    assert row["status"] == "queued" and row["attempts"] == 0
    worker._provider_balance_usd.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_cleanup_retains_normal_retention_behavior(cycle_case):
    await _open(cycle_case)
    identity = await _artifact(cycle_case)
    worker, call = _worker("cleanup")
    deleted = []
    worker.storage = SimpleNamespace(delete=deleted.append)
    await call()
    assert deleted == ["synthetic/result.glb"]
    assert (await _row(cycle_case, ThreeDArtifact, identity))["status"] == "expired"
    assert worker.next_cleanup_at > 0 and worker.last_cleanup_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status", [("song", None), ("dubbing", "speech_running"), ("dubbing", "speech_completed"), ("dubbing", "rendering")])
async def test_close_between_discovery_and_work_transaction_prevents_side_effect(cycle_case, monkeypatch, kind, status):
    case = cycle_case
    await _open(case)
    identity = await _song(case) if kind == "song" else await _dub(case, status)
    effects = []
    async def effect(*args, **kwargs):
        effects.append(True)
        return "unchanged"
    for name in ["refresh_dubbing_speech_status", "create_dubbing_final_pipeline", "finalize_dubbing_execution"]:
        monkeypatch.setattr(dubbing, name, effect)
    calls = 0
    @asynccontextmanager
    async def boundary_sessions():
        nonlocal calls
        calls += 1
        async with case.sessions() as session:
            yield session
        if calls == 1:
            await maintenance.close_admission(operation_id=case.operation, expected_generation=26,
                reason="Close after discovery", session_factory=case.sessions)
    monkeypatch.setattr(song if kind == "song" else dubbing, "SessionLocal", boundary_sessions)
    worker, call = _worker(kind)
    before = await _row(case, AudioSongExecution if kind == "song" else AudioDubbingExecution, identity)
    assert await call() is False
    assert effects == []
    if kind == "song":
        worker._provider_balance_usd.assert_not_awaited()
    assert await _row(case, AudioSongExecution if kind == "song" else AudioDubbingExecution, identity) == before


async def _await_control_lock(case, close):
    for _ in range(100):
        async with case.sessions() as session:
            waiting = await session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%owner_control_records%' AND pid <> pg_backend_pid()"))
        if waiting:
            assert not close.done()
            return
        if close.done():
            await close
            pytest.fail("Closure overtook active guarded work")
        await asyncio.sleep(0.01)
    pytest.fail("The control transition did not reach its database lock")


@pytest.mark.asyncio
async def test_song_balance_and_arm_share_the_same_maintenance_lock(cycle_case):
    case = cycle_case
    await _open(case)
    identity = await _song(case)
    worker, call = _worker("song")
    entered, finish = asyncio.Event(), asyncio.Event()
    async def balance():
        entered.set()
        await finish.wait()
        return 5.0, "f" * 64
    worker._provider_balance_usd = balance
    task = asyncio.create_task(call())
    close = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        close = asyncio.create_task(maintenance.close_admission(operation_id=case.operation,
            expected_generation=26, reason="Wait for authorized balance/arm", session_factory=case.sessions))
        await _await_control_lock(case, close)
        finish.set()
        assert await asyncio.wait_for(task, 3) is True
        assert (await asyncio.wait_for(close, 3)).generation == 27
        assert (await _row(case, AudioSongExecution, identity))["status"] == "queued"
    finally:
        finish.set()
        await asyncio.gather(task, *([close] if close else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_cleanup_holds_fence_until_storage_and_database_finish(cycle_case):
    case = cycle_case
    await _open(case)
    identity = await _artifact(case)
    worker, call = _worker("cleanup")
    entered, finish = threading.Event(), threading.Event()
    def storage_delete(key):
        assert key == "synthetic/result.glb"
        entered.set()
        assert finish.wait(4)
    worker.storage = SimpleNamespace(delete=storage_delete)
    task = asyncio.create_task(call())
    close = None
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        close = asyncio.create_task(maintenance.close_admission(operation_id=case.operation,
            expected_generation=26, reason="Wait for local cleanup completion", session_factory=case.sessions))
        await _await_control_lock(case, close)
        finish.set()
        await asyncio.wait_for(task, 3)
        assert (await asyncio.wait_for(close, 3)).generation == 27
        assert (await _row(case, ThreeDArtifact, identity))["status"] == "expired"
    finally:
        finish.set()
        await asyncio.gather(task, *([close] if close else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_closed_song_does_not_even_load_runtime_credentials(cycle_case):
    del cycle_case
    worker, call = _worker("song")
    def forbidden():
        pytest.fail("Closed song cycle loaded runtime credentials")
    worker._runtime_secrets = forbidden
    assert await call() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancelled", "failure", "timeout"])
async def test_balance_failure_or_cancellation_never_arms_or_leaks_authority_lock(cycle_case, monkeypatch, outcome):
    case = cycle_case
    await _open(case)
    identity = await _song(case)
    before = await _row(case, AudioSongExecution, identity)
    worker, call = _worker("song")
    entered = asyncio.Event()
    async def balance():
        entered.set()
        if outcome == "failure":
            raise RuntimeError("Synthetic balance unavailable")
        await asyncio.Event().wait()
    worker._provider_balance_usd = balance
    if outcome == "timeout":
        monkeypatch.setattr(song, "SONG_BALANCE_TIMEOUT_SECONDS", 0.03)
    task = asyncio.create_task(call())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if outcome == "cancelled":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else RuntimeError if outcome == "failure" else TimeoutError):
            await task
        assert await _row(case, AudioSongExecution, identity) == before
        closed = await maintenance.close_admission(operation_id=case.operation, expected_generation=26,
            reason="No balance work remains", session_factory=case.sessions)
        assert closed.generation == 27
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_two_song_workers_do_not_double_arm_or_double_probe_balance(cycle_case):
    case = cycle_case
    await _open(case)
    identity = await _song(case)
    first, call1 = _worker("song")
    second, call2 = _worker("song")
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def balance():
        calls.append(True)
        entered.set()
        await finish.wait()
        return 5.0, "f" * 64
    first._provider_balance_usd = balance
    second._provider_balance_usd = balance
    t1, t2 = asyncio.create_task(call1()), None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        t2 = asyncio.create_task(call2())
        for _ in range(100):
            async with case.sessions() as session:
                blocked = await session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%audio_song_executions%' AND pid <> pg_backend_pid()"))
            if blocked:
                break
            await asyncio.sleep(0.01)
        assert blocked and not t2.done()
        finish.set()
        assert await asyncio.wait_for(t1, 3) is True
        assert await asyncio.wait_for(t2, 3) is False
        assert len(calls) == 1
        assert (await _row(case, AudioSongExecution, identity))["status"] == "queued"
    finally:
        finish.set()
        await asyncio.gather(t1, *([t2] if t2 else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_close_after_dubbing_refresh_rejects_new_final_pipeline(cycle_case, monkeypatch):
    case = cycle_case
    await _open(case)
    identity = await _dub(case, "speech_running")
    calls = 0
    @asynccontextmanager
    async def boundary_sessions():
        nonlocal calls
        calls += 1
        index = calls
        async with case.sessions() as session:
            yield session
        if index == 2:
            await maintenance.close_admission(operation_id=case.operation, expected_generation=26,
                reason="Close after speech refresh commit", session_factory=case.sessions)
    monkeypatch.setattr(dubbing, "SessionLocal", boundary_sessions)
    create = AsyncMock()
    monkeypatch.setattr(dubbing, "create_dubbing_final_pipeline", create)
    _, call = _worker("dubbing")
    assert await call() is False
    create.assert_not_awaited()
    assert (await _row(case, AudioDubbingExecution, identity))["status"] == "speech_completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,method,result", [
    ("speech_running", "refresh_dubbing_speech_status", "speech_running"),
    ("speech_completed", "create_dubbing_final_pipeline", "synthetic-graph"),
    ("rendering", "finalize_dubbing_execution", {}),
])
async def test_dubbing_branch_keeps_maintenance_lock_through_commit(cycle_case, monkeypatch, status, method, result):
    case = cycle_case
    await _open(case)
    await _dub(case, status)
    entered, finish = asyncio.Event(), asyncio.Event()
    async def effect(session, **kwargs):
        assert session.in_transaction()
        entered.set()
        await finish.wait()
        return result
    monkeypatch.setattr(dubbing, method, effect)
    _, call = _worker("dubbing")
    task, close = asyncio.create_task(call()), None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        close = asyncio.create_task(maintenance.close_admission(operation_id=case.operation,
            expected_generation=26, reason="Wait for dubbing transaction", session_factory=case.sessions))
        await _await_control_lock(case, close)
        finish.set()
        assert await asyncio.wait_for(task, 3) is True
        assert (await asyncio.wait_for(close, 3)).generation == 27
    finally:
        finish.set()
        await asyncio.gather(task, *([close] if close else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelling_cleanup_does_not_release_fence_while_storage_thread_runs(cycle_case):
    case = cycle_case
    await _open(case)
    identity = await _artifact(case)
    worker, call = _worker("cleanup")
    entered, finish = threading.Event(), threading.Event()
    def storage_delete(key):
        assert key == "synthetic/result.glb"
        entered.set()
        assert finish.wait(4)
    worker.storage = SimpleNamespace(delete=storage_delete)
    task, close = asyncio.create_task(call()), None
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done(), "Cancellation released the transaction while storage still ran"
        close = asyncio.create_task(maintenance.close_admission(operation_id=case.operation,
            expected_generation=26, reason="Cancelled cleanup must finish existing effects", session_factory=case.sessions))
        await _await_control_lock(case, close)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and not close.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert (await asyncio.wait_for(close, 3)).generation == 27
        assert (await _row(case, ThreeDArtifact, identity))["status"] == "expired"
    finally:
        finish.set()
        await asyncio.gather(task, *([close] if close else []), return_exceptions=True)
