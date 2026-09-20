"""Real disposable PostgreSQL/worker/archives; output binding, not settlement."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuditEvent, StudioAsset, StudioAssetRevision, StudioExecution, StudioJob, StudioPublication
from app.services import host_maintenance_admission as admission
from app.services import production_studio as production
from app.services import studio_resource_registry as registry
from app.services import studio_result_binding as binding

_spec = importlib.util.spec_from_file_location(
    "fr06d8b5_publication_fixture", Path(__file__).with_name("test_fr06c5d8a2b4_studio_publication_journal.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case
publication_case = _shared.publication_case
_new = _shared._shared._shared._new
_row = _shared._shared._shared._row
_ledger = _shared._shared._ledger
WAIT = 8


async def _prepared(case):
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    assert claim is not None and await case.worker._begin_execution(*claim)
    async with case.sessions() as session:
        job = await session.get(StudioJob, job_id)
        owner = await registry.find_owner(session, job_id=job_id, nonce=claim[1], worker_incarnation=case.worker.incarnation)
    spec = production.StudioSpec(job.department, job.title, job.brief, job.language, job.style)
    artifact = await registry.owned_studio_thread(
        case.sessions, job_id, claim[1], case.worker.incarnation, "build_archive",
        production.build_archive, spec, job_id=job_id, revision_number=1,
    )
    asset_id, revision_id = str(uuid4()), str(uuid4())
    path = await registry.owned_studio_thread(
        case.sessions, job_id, claim[1], case.worker.incarnation, "store_artifact",
        production.store_artifact, organization_id=job.organization_id,
        asset_id=asset_id, revision_number=1, artifact=artifact,
    )
    return claim, owner, dict(
        job_id=job_id, nonce=claim[1], worker_incarnation=case.worker.incarnation,
        asset_id=asset_id, revision_id=revision_id, revision_number=1, path=path, artifact=artifact,
    )


async def _outputs(case, job_id):
    async with case.sessions() as session:
        asset = await session.scalar(select(StudioAsset).where(StudioAsset.job_id == job_id))
        revision = await session.scalar(select(StudioAssetRevision).where(StudioAssetRevision.job_id == job_id))
        return asset, revision


@pytest.mark.asyncio
async def test_real_worker_binds_all_business_rows_to_owned_archive(publication_case):
    case = publication_case
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    await case.worker.execute(*claim)
    job = await _row(case, job_id)
    asset, revision = await _outputs(case, job_id)
    proof = job["result_metadata"][binding.BINDING_KEY]
    assert asset.asset_metadata[binding.BINDING_KEY] == proof == revision.revision_metadata[binding.BINDING_KEY]
    assert proof["schema"] == binding.BINDING_SCHEMA
    assert proof["asset_id"] == asset.id and proof["revision_id"] == revision.id
    publication, = await _shared._rows(case)
    assert proof["publication_id"] == publication["id"]
    assert proof["execution_id"] == publication["execution_id"]
    assert proof["publication_evidence_sha256"] == binding.evidence_digest({"plan": publication["plan"], "events": publication["events"]})
    assert proof["file_identity_sha256"] == binding.evidence_digest(publication["events"][-1]["payload"]["file"])
    archive = Path(revision.storage_path)
    assert proof["checksum"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert proof["size_bytes"] == archive.stat().st_size
    assert proof["storage_path_sha256"] == hashlib.sha256(str(archive).encode()).hexdigest()
    public = json.dumps(proof)
    assert claim[1] not in public and str(case.root) not in public and "brief" not in public
    ledger = await _ledger(case, job_id)
    assert ledger["state"] == "unresolved" and ledger["cleanup_verified"] is False
    assert not (await registry.execution_snapshot(session_factory=case.sessions))["is_clear"]
    await case.worker.execute(*claim)
    assert len(await _shared._rows(case)) == 1


@pytest.mark.asyncio
async def test_revision_keeps_prior_binding_and_atomically_advances_current_asset(publication_case):
    case = publication_case
    first = await _new(case)
    await case.worker.execute(*(await case.worker.claim_by_id(first)))
    asset, old_revision = await _outputs(case, first)
    old_proof = deepcopy(old_revision.revision_metadata[binding.BINDING_KEY])
    second = await _new(case, revision_of_asset_id=asset.id, title="Synthetic revised package")
    await case.worker.execute(*(await case.worker.claim_by_id(second)))
    second_job = await _row(case, second)
    _, revised = await _outputs(case, second)
    proof = second_job["result_metadata"][binding.BINDING_KEY]
    async with case.sessions() as session:
        current = await session.get(StudioAsset, asset.id)
        previous = await session.get(StudioAssetRevision, old_revision.id)
    assert current.current_revision == 2 and proof["revision_number"] == 2
    assert current.asset_metadata[binding.BINDING_KEY] == revised.revision_metadata[binding.BINDING_KEY] == proof
    assert previous.revision_metadata[binding.BINDING_KEY] == old_proof
    assert proof["publication_id"] != old_proof["publication_id"]
    assert Path(previous.storage_path).exists() and Path(revised.storage_path).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "nonce", "worker_incarnation", "job_id", "asset_id", "revision_id", "revision_number",
    "path", "filename", "checksum", "size", "media_type", "manifest_job", "manifest_revision",
    "manifest_bool_revision", "manifest_department", "root",
])
async def test_mismatched_output_never_becomes_a_result(publication_case, monkeypatch, change):
    case = publication_case
    claim, _, args = await _prepared(case)
    before = await _row(case, claim[0])
    if change in {"nonce", "worker_incarnation", "job_id", "asset_id"}:
        args[change] = str(uuid4())
    elif change == "revision_id":
        args[change] = "not-an-identifier"
    elif change == "revision_number":
        args[change] = 2
    elif change == "path":
        args[change] = args[change].with_name("different-output.zip")
    elif change == "root":
        monkeypatch.setattr(binding.settings, "STUDIO_ASSET_ROOT", str(case.root / "other"))
    else:
        artifact = args["artifact"]
        if change.startswith("manifest_"):
            manifest = deepcopy(artifact.manifest)
            key, value = {
                "manifest_job": ("job_id", str(uuid4())), "manifest_revision": ("revision", 2),
                "manifest_bool_revision": ("revision", True), "manifest_department": ("department", "video"),
            }[change]
            manifest[key] = value
            args["artifact"] = replace(artifact, manifest=manifest)
        else:
            key, value = {
                "filename": ("filename", "other-output.zip"), "checksum": ("checksum", "0" * 64),
                "size": ("size_bytes", artifact.size_bytes + 1), "media_type": ("media_type", "text/plain"),
            }[change]
            args["artifact"] = replace(artifact, **{key: value})
    async with case.sessions() as session:
        with pytest.raises((registry.StudioResourceUncertain, registry.StudioOwnershipLost)):
            await binding.bind_owned_result(session, **args)
        await session.rollback()
    assert await _row(case, claim[0]) == before
    assert await _outputs(case, claim[0]) == (None, None)
    assert len(list(case.root.rglob("*.zip"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "publication_missing", "publication_owner", "publication_thread", "publication_generation",
    "publication_checksum", "publication_identity", "publication_state",
    "execution_owner", "reserved_thread", "failed_thread", "cancel_requested",
])
async def test_incomplete_or_foreign_evidence_is_not_accepted(publication_case, change):
    case = publication_case
    claim, owner, args = await _prepared(case)
    async with case.sessions() as session:
        publication = await session.scalar(select(StudioPublication).where(StudioPublication.job_id == claim[0]))
        execution = await session.get(StudioExecution, owner.execution_id)
        if change == "publication_missing":
            await session.delete(publication)
        elif change == "publication_owner":
            publication.ownership_nonce = str(uuid4())
        elif change == "publication_thread":
            publication.thread_resource_id = str(uuid4())
        elif change == "publication_generation":
            publication.admitted_generation += 1
        elif change == "publication_checksum":
            publication.plan = {**publication.plan, "checksum": "0" * 64}
        elif change == "publication_identity":
            events = deepcopy(publication.events)
            events[-1]["payload"]["file"]["inode"] += 1
            publication.events = events
        elif change == "publication_state":
            publication.state = "reserved"
        elif change == "execution_owner":
            execution.worker_incarnation = str(uuid4())
        elif change == "cancel_requested":
            job = await session.get(StudioJob, claim[0])
            job.status = "cancel_requested"
        else:
            resources = deepcopy(execution.resources)
            resource = next(item for item in resources.values() if item["operation"] == "store_artifact")
            if change == "reserved_thread":
                resource.update(state="reserved", joined_at=None, outcome=None)
            else:
                resource["outcome"] = "failed"
            execution.resources = resources
        await session.commit()
    async with case.sessions() as session:
        with pytest.raises((registry.StudioResourceUncertain, registry.StudioOwnershipLost)):
            await binding.bind_owned_result(session, **args)
    assert await _outputs(case, claim[0]) == (None, None)
    assert len(list(case.root.rglob("*.zip"))) == 1
    assert await case.worker.claim_by_id(claim[0]) is None


@pytest.mark.asyncio
async def test_binding_retains_caller_transaction_without_autoflush(publication_case):
    case = publication_case
    claim, _, args = await _prepared(case)
    writes = []
    def observe(_connection, _cursor, sql, _params, _context, _many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)
    event.listen(case.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with case.sessions() as session:
            session.add(AuditEvent(
                id=str(uuid4()), organization_id=case.actor.organization_id,
                action="synthetic.pending_binding", resource_type="test", resource_id=claim[0], details={},
            ))
            result = await binding.bind_owned_result(session, **args)
            assert session.in_transaction() and not writes
            assert result["job_id"] == claim[0]
            await session.rollback()
    finally:
        event.remove(case.engine.sync_engine, "before_cursor_execute", observe)
    assert await _outputs(case, claim[0]) == (None, None)


@pytest.mark.asyncio
async def test_started_work_can_bind_after_maintenance_closes(publication_case):
    case = publication_case
    claim, _, args = await _prepared(case)
    async with case.sessions() as session:
        authority = await admission.read_admission_snapshot(session, required_scope="studio_job_requests")
    await admission.close_admission(
        operation_id=str(uuid4()), expected_generation=authority.generation,
        reason="synthetic binding after close", session_factory=case.sessions,
    )
    async with case.sessions() as session:
        result = await binding.bind_owned_result(session, **args)
        assert result["admitted_generation"] == authority.generation
    assert await _outputs(case, claim[0]) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("timing", ["before", "after"])
async def test_business_commit_failure_does_not_replay_or_destroy_archive(publication_case, timing):
    case = publication_case
    error = RuntimeError("synthetic business commit acknowledgement failure")
    class FailingCommit(AsyncSession):
        async def commit(self):
            terminal = any(
                isinstance(item, StudioJob) and item.status == "completed"
                and binding.BINDING_KEY in (item.result_metadata or {})
                for item in self.identity_map.values()
            )
            if terminal and timing == "before":
                raise error
            await super().commit()
            if terminal:
                raise error
    case.worker._session_factory = async_sessionmaker(case.engine, class_=FailingCommit, expire_on_commit=False)
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    with pytest.raises(RuntimeError) as caught:
        await case.worker.execute(*claim)
    assert caught.value is error
    job = await _row(case, job_id)
    asset, revision = await _outputs(case, job_id)
    assert (job["status"] == "completed") is (timing == "after")
    assert (binding.BINDING_KEY in job["result_metadata"]) is (timing == "after")
    assert (asset is not None and revision is not None) is (timing == "after")
    assert len(list(case.root.rglob("*.zip"))) == 1
    ledger = await _ledger(case, job_id)
    assert ledger["state"] == "unresolved" and ledger["cleanup_verified"] is False
    assert await case.worker.claim_by_id(job_id) is None


@pytest.mark.asyncio
async def test_acknowledged_cancellation_cannot_publish_a_business_result(publication_case, monkeypatch):
    case = publication_case
    entered, release = asyncio.Event(), asyncio.Event()
    journal = _shared.journal
    original = journal.persist_event
    async def pause(**kwargs):
        if kwargs["operation"] == "complete":
            entered.set()
            await release.wait()
        await original(**kwargs)
    monkeypatch.setattr(journal, "persist_event", pause)
    job_id = await _new(case)
    claim = await case.worker.claim_by_id(job_id)
    task = asyncio.create_task(case.worker.execute(*claim))
    try:
        await asyncio.wait_for(entered.wait(), WAIT)
        response = await case.client.post(f"/studio/jobs/{job_id}/cancel")
        assert response.status_code == 200 and response.json()["status"] == "cancel_requested"
    finally:
        release.set()
        await asyncio.wait_for(task, WAIT)
    job = await _row(case, job_id)
    assert job["status"] == "cancelled" and binding.BINDING_KEY not in job["result_metadata"]
    assert job["lease_token"] is None and job["completed_at"] is not None
    assert await _outputs(case, job_id) == (None, None)
    assert len(list(case.root.rglob("*.zip"))) == 1
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["poststart_cancelled_count"] == 1
    assert snapshot["invalid_poststart_cancellation_count"] == 0
    execution = next(item for item in snapshot["executions"] if item["job_id"] == job_id)
    publication = next(item for item in snapshot["publications"] if item["job_id"] == job_id)
    assert execution["cancelled_after_execution_start"] is True
    assert publication["cancelled_archive_retained"] is True
    assert snapshot["full_host_closure"] is False


@pytest.mark.asyncio
async def test_stale_revision_head_is_not_overwritten(publication_case, monkeypatch):
    case = publication_case
    first = await _new(case)
    await case.worker.execute(*(await case.worker.claim_by_id(first)))
    asset, _ = await _outputs(case, first)
    original = binding.bind_owned_result
    async def advance(session, **kwargs):
        proof = await original(session, **kwargs)
        async with case.sessions() as other:
            current = await other.get(StudioAsset, asset.id)
            current.current_revision = 9
            await other.commit()
        return proof
    monkeypatch.setattr(binding, "bind_owned_result", advance)
    job_id = await _new(case, revision_of_asset_id=asset.id, title="Synthetic stale revision")
    claim = await case.worker.claim_by_id(job_id)
    with pytest.raises(registry.StudioOwnershipLost, match="revision head"):
        await case.worker.execute(*claim)
    async with case.sessions() as session:
        current = await session.get(StudioAsset, asset.id)
    assert current.current_revision == 9
    assert binding.BINDING_KEY not in (await _row(case, job_id))["result_metadata"]
    assert len(list(case.root.rglob("*.zip"))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [StudioJob, StudioExecution, StudioPublication])
@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_job_execution_publication_locks_survive_until_business_transaction_ends(publication_case, model, finish):
    from sqlalchemy import text
    case = publication_case
    claim, owner, args = await _prepared(case)
    publication, = await _shared._rows(case)
    identifier = {StudioJob: claim[0], StudioExecution: owner.execution_id, StudioPublication: publication["id"]}[model]
    ready, release = asyncio.Event(), asyncio.Event()
    entered = asyncio.Queue()
    finished = asyncio.Event()
    binder_pid = None
    async def holder():
        nonlocal binder_pid
        async with case.sessions() as session:
            binder_pid = int(await session.scalar(text("SELECT pg_backend_pid()")))
            await binding.bind_owned_result(session, **args)
            ready.set()
            await release.wait()
            if finish == "commit":
                await session.commit()
            else:
                await session.rollback()
    async def contender():
        async with case.sessions() as session:
            pid = int(await session.scalar(text("SELECT pg_backend_pid()")))
            entered.put_nowait(pid)
            assert await session.scalar(select(model.id).where(model.id == identifier).with_for_update()) == identifier
            finished.set()
    hold = asyncio.create_task(holder())
    wait = None
    try:
        await asyncio.wait_for(ready.wait(), WAIT)
        wait = asyncio.create_task(contender())
        pid = await asyncio.wait_for(entered.get(), WAIT)
        async with asyncio.timeout(WAIT):
            while True:
                async with case.sessions() as probe:
                    blockers = await probe.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
                if binder_pid in blockers:
                    break
                await asyncio.sleep(0.01)
        assert not finished.is_set()
    finally:
        release.set()
        tasks = [hold] + ([wait] if wait is not None else [])
        await asyncio.wait_for(asyncio.gather(*tasks), WAIT)
    assert finished.is_set()
    assert await _outputs(case, claim[0]) == (None, None)
