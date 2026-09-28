"""Downstream media claim/reaper admission on private disposable PostgreSQL.

No worker run loop, storage operation, provider client or production record is
used. Actual claim methods and actual PostgreSQL locks are exercised. Recording
which tables a closed claimant touches is an independent early-fence assertion.
"""
from __future__ import annotations

import importlib
import os
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    IdentityMediaExecution, MediaAssetGraph, MediaAssetNode, MediaRenderStep,
    Organization, OwnerControlRecord, User,
)
from app.services import host_maintenance_admission as maintenance

# module, class (None for caller-owned session), method, protected table
CLAIMS = (
    ("design_image_runtime", "DesignImageExecutionAuthority", "claim", "design_image_executions"),
    ("audio_speech_runtime", "AudioSpeechExecutionAuthority", "claim", "audio_speech_executions"),
    ("audio_transcript_runtime", "AudioTranscriptExecutionAuthority", "claim", "audio_transcript_executions"),
    ("audio_dubbing_runtime", "AudioDubbingExecutionAuthority", "claim", "audio_dubbing_executions"),
    ("audio_music_runtime", "AudioMusicExecutionAuthority", "claim", "audio_music_executions"),
    ("video_runtime", "VideoExecutionAuthority", "claim", "video_executions"),
    ("audio_song_runtime", None, "claim_audio_song_execution", "audio_song_executions"),
    ("identity_media_runtime", None, "claim_next", "identity_media_executions"),
    ("three_d_worker", "ThreeDGenerationWorker", "claim", "three_d_generation_jobs"),
    ("media_render_worker", "MediaRenderWorker", "claim", "media_render_steps"),
    ("design_image_derivative_worker", "DesignImageDerivativeWorker", "claim", "media_render_steps"),
)
REAPERS = (
    ("audio_speech_runtime", "AudioSpeechExecutionAuthority", "reap_ambiguous_submissions", "audio_speech_executions"),
    ("audio_music_runtime", "AudioMusicExecutionAuthority", "reap_ambiguous_submissions", "audio_music_executions"),
    ("video_runtime", "VideoExecutionAuthority", "reap_exhausted", "video_executions"),
    ("audio_song_runtime", None, "recover_expired_audio_song_executions", "audio_song_executions"),
    ("media_render_worker", "MediaRenderWorker", "reap_exhausted_leases", "media_render_steps"),
    ("design_image_derivative_worker", "DesignImageDerivativeWorker", "reap_exhausted_leases", "media_render_steps"),
)


def _tables():
    needed = set()

    def visit(table):
        if table.name in needed:
            return
        needed.add(table.name)
        for foreign in table.foreign_keys:
            visit(foreign.column.table)

    for name in {item[3] for item in CLAIMS} | {"owner_control_records", "media_asset_edges", "audit_events"}:
        visit(Base.metadata.tables[name])
    return [table for table in Base.metadata.sorted_tables if table.name in needed]


@pytest_asyncio.fixture
async def case(monkeypatch):
    url = make_url(os.environ["DATABASE_URL"])
    assert os.environ.get("ENVIRONMENT") == "test"
    assert url.drivername == "postgresql+asyncpg"
    assert re.search(r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)", url.database or "")
    schema = "fr06_media_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={
        "server_settings": {"search_path": schema, "statement_timeout": "8000"},
    })
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    sql = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, parameters, context, executemany
        sql.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    created = False
    oid, uid = str(uuid4()), str(uuid4())
    authority_id = str(uuid4())
    operation = str(uuid4())
    try:
        async with admin.begin() as conn:
            await conn.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=_tables()))
        async with sessions() as session, session.begin():
            session.add(Organization(id=oid, name="Synthetic media fence", slug=uuid4().hex))
            await session.flush()
            session.add(User(id=uid, organization_id=oid, email=uuid4().hex+"@example.invalid",
                             name="Synthetic media fence", password_hash="unused-test-only"))
            session.add(OwnerControlRecord(id=authority_id, domain=maintenance.DOMAIN,
                resource_id=maintenance.RESOURCE_ID, status="closed", enabled=False, version=26,
                payload={"schema_version": 8, "scope": maintenance.REALTIME_REQUEST_COVERAGE_SCOPE,
                         "generation": 26, "operation_id": operation, "reason": "Isolated media admission test",
                         "changed_at": datetime.now(UTC).isoformat(), "full_host_closure": False}))
        for name in ("three_d_worker", "design_image_derivative_worker"):
            module = importlib.import_module("app.services."+name)
            monkeypatch.setattr(module, "SessionLocal", sessions)
        monkeypatch.setattr(settings, "DESIGN_IMAGE_DERIVATIVE_ENABLED", True)
        sql.clear()
        yield SimpleNamespace(sessions=sessions, engine=engine, sql=sql, oid=oid, uid=uid,
                              authority_id=authority_id, operation=operation)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", observe)
        await engine.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def _invoke(case, entry):
    name, cls, method, _ = entry
    module = importlib.import_module("app.services."+name)
    if cls is None:
        async with case.sessions() as session:
            kwargs = {} if method == "recover_expired_audio_song_executions" else {"worker_id": "synthetic-fence-worker", "lease_seconds": 60}
            result = await getattr(module, method)(session, **kwargs)
            await session.commit()
            return result
    # Claim methods do not use the provider/store. Skip constructors that may
    # create production filesystem directories; all claim fields are explicit.
    instance = object.__new__(getattr(module, cls))
    instance.session_factory = case.sessions
    instance.worker_id = "synthetic-fence-worker"
    if cls not in {"MediaRenderWorker", "DesignImageDerivativeWorker", "ThreeDGenerationWorker"}:
        instance.lease_seconds = 60
    return await getattr(instance, method)()


async def _open(case):
    async with case.sessions() as session, session.begin():
        row = await session.get(OwnerControlRecord, case.authority_id)
        row.status, row.enabled = "open", True
    case.sql.clear()


def _queue_access(case, table):
    return [statement for statement in case.sql
            if re.search(r"\b"+re.escape(table)+r"\b", statement)]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", CLAIMS, ids=[x[0] for x in CLAIMS])
async def test_closed_claim_does_not_touch_work_tables(case, entry):
    assert await _invoke(case, entry) is None
    assert not _queue_access(case, entry[3]), "closed maintenance reached a media work queue"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", REAPERS, ids=[x[0] for x in REAPERS])
async def test_closed_reaper_does_not_touch_work_tables(case, entry):
    result = await _invoke(case, entry)
    assert result in (0, {"recovered": 0, "needs_review": 0, "observed": 0})
    assert not _queue_access(case, entry[3]), "closed maintenance reached an expired-work reaper"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", CLAIMS, ids=[x[0] for x in CLAIMS])
async def test_open_claim_still_reads_its_queue(case, entry):
    await _open(case)
    assert await _invoke(case, entry) is None
    assert _queue_access(case, entry[3]), "open work must not be silently disabled"


async def _identity(case, *, provider_running=False):
    async with case.sessions() as session, session.begin():
        row = IdentityMediaExecution(id=str(uuid4()), organization_id=case.oid, requested_by_id=case.uid,
            operation="synthetic-test", identity_basis="fictional", provider_access="local-test-only",
            model="synthetic-model", status="provider_running" if provider_running else "queued",
            provider_state="running" if provider_running else "not_started",
            provider_job_id="synthetic-no-provider-request" if provider_running else None,
            idempotency_key=uuid4().hex, subject_reference="synthetic-fixture",
            lease_expires_at=datetime.now(UTC)-timedelta(seconds=60))
        session.add(row)
        await session.flush()
        return row.id


async def _row(case, model, identity):
    async with case.sessions() as session:
        row = (await session.execute(select(model.__table__).where(model.id == identity))).mappings().one()
        return dict(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_running", [False, True], ids=["fresh-submit", "resume-poll"])
async def test_closed_identity_claim_preserves_queued_or_provider_running_row(case, provider_running):
    identity = await _identity(case, provider_running=provider_running)
    before = await _row(case, IdentityMediaExecution, identity)
    assert await _invoke(case, CLAIMS[7]) is None
    assert await _row(case, IdentityMediaExecution, identity) == before


async def _render(case, engine):
    async with case.sessions() as session, session.begin():
        graph = MediaAssetGraph(id=str(uuid4()), organization_id=case.oid, created_by_id=case.uid,
            title="Synthetic render", asset_kind="image", output_profile="test-profile",
            idempotency_key=uuid4().hex, graph_checksum="a"*64)
        session.add(graph)
        await session.flush()
        node = MediaAssetNode(id=str(uuid4()), graph_id=graph.id, organization_id=case.oid,
            created_by_id=case.uid, logical_key="fixture", node_type="image", idempotency_key=uuid4().hex)
        session.add(node)
        await session.flush()
        row = MediaRenderStep(id=str(uuid4()), graph_id=graph.id, organization_id=case.oid,
            target_node_id=node.id, step_key="fixture", operation="design-image-derivative" if engine=="sharp" else "resize",
            output_profile="test-profile", engine=engine, engine_version="synthetic", status="running",
            attempts=3, max_attempts=3, lease_owner="expired-synthetic-worker", lease_token=str(uuid4()),
            lease_expires_at=datetime.now(UTC)-timedelta(seconds=60), idempotency_key=uuid4().hex)
        session.add(row)
        await session.flush()
        return row.id, graph.id


@pytest.mark.asyncio
@pytest.mark.parametrize("engine,entry", [("ffmpeg", REAPERS[4]), ("sharp", REAPERS[5])])
async def test_closed_reaper_preserves_expired_row_graph_and_evidence(case, engine, entry):
    identity, graph = await _render(case, engine)
    before = await _row(case, MediaRenderStep, identity)
    graph_before = await _row(case, MediaAssetGraph, graph)
    assert await _invoke(case, entry) == 0
    assert await _row(case, MediaRenderStep, identity) == before
    assert await _row(case, MediaAssetGraph, graph) == graph_before


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", CLAIMS, ids=[x[0] for x in CLAIMS])
async def test_missing_authority_blocks_claim_without_seeding_or_queue_access(case, entry):
    async with case.sessions() as session, session.begin():
        row = await session.get(OwnerControlRecord, case.authority_id)
        await session.delete(row)
    case.sql.clear()
    assert await _invoke(case, entry) is None
    assert not _queue_access(case, entry[3])
    async with case.sessions() as session:
        assert await session.get(OwnerControlRecord, case.authority_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["schema1", "schema6", "future-schema", "wrong-version", "full-host-claim", "malformed-payload", "wrong-status"])
async def test_unsupported_or_malformed_authority_cannot_authorize_media_claim(case, mode):
    async with case.sessions() as session, session.begin():
        row = await session.get(OwnerControlRecord, case.authority_id)
        payload = dict(row.payload)
        row.enabled, row.status = True, "open"
        if mode == "schema1":
            payload.update(schema_version=1, scope=maintenance.SCOPE)
        elif mode == "schema6":
            payload.update(schema_version=6, scope=maintenance.SCAN_REQUEST_COVERAGE_SCOPE)
        elif mode == "future-schema":
            payload["schema_version"] = 99
        elif mode == "wrong-version":
            row.version += 1
        elif mode == "full-host-claim":
            payload["full_host_closure"] = True
        elif mode == "malformed-payload":
            payload = {"unexpected": True}
        else:
            row.status = "unknown"
        row.payload = payload
    case.sql.clear()
    assert await _invoke(case, CLAIMS[7]) is None
    assert not _queue_access(case, CLAIMS[7][3])


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_running", [False, True])
async def test_open_identity_claim_remains_functional(case, provider_running):
    await _open(case)
    identity = await _identity(case, provider_running=provider_running)
    claimed = await _invoke(case, CLAIMS[7])
    assert claimed is not None and claimed.execution_id == identity
    assert claimed.mode == ("poll" if provider_running else "submit")
    after = await _row(case, IdentityMediaExecution, identity)
    assert after["lease_owner"] == "synthetic-fence-worker"
    assert after["fencing_token"] == 1
    assert after["attempts"] == (0 if provider_running else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("engine,entry", [("ffmpeg", REAPERS[4]), ("sharp", REAPERS[5])])
async def test_open_reaper_keeps_existing_behavior(case, engine, entry):
    await _open(case)
    identity, graph = await _render(case, engine)
    assert await _invoke(case, entry) == 1
    assert (await _row(case, MediaRenderStep, identity))["status"] == "failed"
    assert (await _row(case, MediaAssetGraph, graph))["status"] == "failed"


async def _wait_for_lock(case, holder_pid):
    import asyncio
    from sqlalchemy import text

    for _ in range(80):
        async with case.sessions() as probe:
            blocked = await probe.scalar(text(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' "
                "AND :holder = ANY(pg_blocking_pids(pid)))"
            ), {"holder": holder_pid})
        if blocked:
            return
        await asyncio.sleep(0.02)
    pytest.fail("The independent connection did not wait on the actual PostgreSQL lock")


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True], ids=["rollback", "commit"])
async def test_claim_shared_lock_orders_closure_after_caller_transaction(case, commit):
    import asyncio
    from sqlalchemy import text
    from app.services.identity_media_runtime import claim_next

    await _open(case)
    identity = await _identity(case)
    closing = None
    async with case.sessions() as caller:
        try:
            pid = await caller.scalar(text("SELECT pg_backend_pid()"))
            claimed = await claim_next(caller, worker_id="synthetic-fence-worker", lease_seconds=60)
            assert claimed is not None
            closing = asyncio.create_task(maintenance.close_admission(
                operation_id=str(uuid4()), expected_generation=26, reason="Isolated concurrent closure",
                session_factory=case.sessions))
            await _wait_for_lock(case, pid)
            assert not closing.done()
            if commit:
                await caller.commit()
            else:
                await caller.rollback()
            closed = await asyncio.wait_for(closing, timeout=3)
            assert closed.generation == 27 and not closed.is_open and not closed.full_host_closure
        finally:
            await caller.rollback()
            if closing is not None and not closing.done():
                closing.cancel()
                await asyncio.gather(closing, return_exceptions=True)
    after = await _row(case, IdentityMediaExecution, identity)
    assert after["attempts"] == (1 if commit else 0)
    assert bool(after["lease_owner"]) is commit
    assert await _invoke(case, CLAIMS[7]) is None
    assert await _row(case, IdentityMediaExecution, identity) == after


@pytest.mark.asyncio
async def test_closure_first_rejects_claim_after_exclusive_lock_wait(case):
    import asyncio
    from sqlalchemy import text

    await _open(case)
    identity = await _identity(case)
    before = await _row(case, IdentityMediaExecution, identity)
    claiming = None
    async with case.sessions() as closer:
        try:
            pid = await closer.scalar(text("SELECT pg_backend_pid()"))
            row = await closer.scalar(select(OwnerControlRecord).where(
                OwnerControlRecord.id == case.authority_id).with_for_update())
            row.status, row.enabled, row.version = "closed", False, 27
            row.payload = {**row.payload, "generation": 27, "operation_id": str(uuid4())}
            await closer.flush()
            claiming = asyncio.create_task(_invoke(case, CLAIMS[7]))
            await _wait_for_lock(case, pid)
            assert not claiming.done()
            await closer.commit()
            assert await asyncio.wait_for(claiming, timeout=3) is None
        finally:
            await closer.rollback()
            if claiming is not None and not claiming.done():
                claiming.cancel()
                await asyncio.gather(claiming, return_exceptions=True)
    assert await _row(case, IdentityMediaExecution, identity) == before


@pytest.mark.asyncio
async def test_cached_open_authority_does_not_hide_later_closure(case):
    from app.services.identity_media_runtime import claim_next

    await _open(case)
    identity = await _identity(case)
    before = await _row(case, IdentityMediaExecution, identity)
    async with case.sessions() as stale:
        held = await stale.get(OwnerControlRecord, case.authority_id)
        assert held.status == "open"
        await maintenance.close_admission(operation_id=str(uuid4()), expected_generation=26,
            reason="Isolated cached authority regression", session_factory=case.sessions)
        assert await claim_next(stale, worker_id="synthetic-fence-worker", lease_seconds=60) is None
        await stale.rollback()
    assert await _row(case, IdentityMediaExecution, identity) == before


@pytest.mark.asyncio
async def test_closed_fence_does_not_autoflush_pending_caller_changes(case):
    from app.services.host_maintenance_media_claims import media_claim_admission_open

    identity = str(uuid4())
    async with case.sessions() as session:
        row = OwnerControlRecord(id=identity, domain="synthetic-unflushed", resource_id=identity,
                                 payload={}, version=1)
        session.add(row)
        assert not await media_claim_admission_open(session, consumer="audio_song")
        assert row in session.new
        assert not any(statement.lstrip().startswith("INSERT") for statement in case.sql)
        await session.rollback()
    async with case.sessions() as session:
        assert await session.get(OwnerControlRecord, identity) is None


@pytest.mark.asyncio
async def test_failed_readonly_lock_is_not_an_open_authority(case):
    from sqlalchemy import text
    from app.services.host_maintenance_media_claims import media_claim_admission_open

    await _open(case)
    async with case.sessions() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        assert not await media_claim_admission_open(session, consumer="audio_song")
        await session.rollback()


@pytest.mark.asyncio
async def test_unknown_consumer_and_programming_error_are_not_silently_accepted(case, monkeypatch):
    from app.services import host_maintenance_media_claims as fence

    async with case.sessions() as session:
        with pytest.raises(ValueError, match="Unknown"):
            await fence.media_claim_admission_open(session, consumer="misspelled-worker")
        assert not case.sql

        async def broken(_session):
            raise RuntimeError("Synthetic programming error")

        monkeypatch.setattr(fence, "require_studio_admission", broken)
        with pytest.raises(RuntimeError, match="Synthetic"):
            await fence.media_claim_admission_open(session, consumer="audio_song")
