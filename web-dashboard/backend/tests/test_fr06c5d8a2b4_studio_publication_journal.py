"""Real disposable PostgreSQL and filesystem publication-bridge acceptance."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models import StudioExecution, StudioJob, StudioPublication, StudioSettlement
from app.services import studio_resource_registry as registry
from app.services import studio_publication_journal as journal
from app.services import studio_artifact_publication as publication
from app.services.studio_publication_protocol import publication_observer

_name = "fr06d8b4_resource_fixture"
_spec = importlib.util.spec_from_file_location(
    _name, Path(__file__).with_name("test_fr06c5d8a2b3_studio_resource_registry.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case


@pytest_asyncio.fixture
async def publication_case(execution_case):
    case = execution_case
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda conn: StudioPublication.__table__.create(conn, checkfirst=True))
    yield case


async def _rows(case):
    async with case.sessions() as session:
        rows = (await session.execute(select(StudioPublication.__table__))).mappings().all()
        return [deepcopy(dict(row)) for row in rows]


def _args(root):
    content = b"synthetic Studio publication acceptance\n" * 13
    return dict(
        root=root, organization_id="test-org", asset_id=str(uuid4()),
        revision_number=1, filename="test-archive.zip", content=content,
        checksum=hashlib.sha256(content).hexdigest(), size_bytes=len(content), maximum_bytes=10000,
    )


async def _store_owner(case):
    claim, owner = await _shared._started(case)
    await registry.owned_studio_thread(
        case.sessions, claim[0], claim[1], case.worker.incarnation,
        "build_archive", lambda: b"completed synthetic build",
    )
    return claim, owner


async def _publish(case, claim, args):
    return await registry.owned_studio_thread(
        case.sessions, claim[0], claim[1], case.worker.incarnation,
        "store_artifact", publication.publish_studio_archive, **args,
    )


@pytest.mark.asyncio
async def test_worker_publication_before_final_settlement_retains_complete_identity_chain(publication_case):
    case = publication_case
    identifier = await _shared._shared._new(case)
    claim = await case.worker.claim_by_id(identifier)
    assert await case.worker._begin_execution(*claim)
    acknowledgement = await case.worker._execute_claimed(*claim)
    assert acknowledgement is not None and acknowledgement.job_id == identifier
    # This is the real publication/business phase before the separate receipt
    # transaction. Complete worker settlement is exercised by the B5B suite.
    async with case.sessions() as session:
        assert await session.scalar(select(StudioSettlement.id).limit(1)) is None
    row, = await _rows(case)
    assert row["state"] == "observed"
    assert row["execution_id"] == (await _shared._ledger(case, identifier))["id"]
    assert row["admitted_generation"] == 7
    operations = [item["operation"] for item in row["events"]]
    assert operations[-8:] == [
        "staging_observed", "write_intent", "staged", "link_intent", "published",
        "cleanup_intent", "staging_removed", "complete",
    ]
    assert operations.count("directory_intent") == len(row["plan"]["components"])
    archive, = case.root.rglob("*.zip")
    identity = row["events"][-1]["payload"]["file"]
    assert (identity["device"], identity["inode"]) == (archive.stat().st_dev, archive.stat().st_ino)
    assert identity["links"] == 1 and identity["size"] == archive.stat().st_size
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == row["plan"]["checksum"]
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["blocker_count"] == 1 + len(snapshot["unregistered_unverified_job_ids"])
    assert not snapshot["is_clear"]
    assert not snapshot["full_host_closure"] and not snapshot["publications"][0]["cleanup_verified"]
    public = json.dumps(snapshot)
    assert claim[1] not in public and row["plan"]["root"] not in public


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reserve", "directory_intent", "staging_intent", "write_intent", "link_intent"])
async def test_missing_pre_effect_ack_prevents_corresponding_mutation(publication_case, monkeypatch, failure):
    case = publication_case
    claim, _ = await _store_owner(case)
    args = _args(case.root / "new-root")
    original = journal.persist_event
    async def fail(**kwargs):
        if kwargs["operation"] == failure:
            raise RuntimeError("synthetic unavailable acknowledgement")
        await original(**kwargs)
    monkeypatch.setattr(journal, "persist_event", fail)
    with pytest.raises(registry.StudioResourceUncertain):
        await _publish(case, claim, args)
    finals = list(case.root.rglob("*.zip"))
    assert not finals
    rows = await _rows(case)
    if failure == "reserve":
        assert rows == [] and not Path(args["root"]).exists()
    else:
        row, = rows
        assert row["state"] == "reserved"
        assert all(event["operation"] != failure for event in row["events"])
    partials = list(case.root.rglob("*.partial"))
    if failure == "write_intent":
        assert len(partials) == 1 and partials[0].stat().st_size == 0
    if failure == "link_intent":
        assert len(partials) == 1 and partials[0].read_bytes() == args["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["published", "cleanup_intent", "staging_removed", "complete"])
async def test_lost_ack_after_link_retains_complete_archive_without_retry(publication_case, monkeypatch, failure):
    case = publication_case
    claim, _ = await _store_owner(case)
    args = _args(case.root)
    original = journal.persist_event
    async def fail(**kwargs):
        # Lost acknowledgement AFTER an actual committed observation.
        await original(**kwargs)
        if kwargs["operation"] == failure:
            raise RuntimeError("synthetic acknowledgement loss after commit")
    monkeypatch.setattr(journal, "persist_event", fail)
    with pytest.raises(registry.StudioResourceUncertain):
        await _publish(case, claim, args)
    archive, = case.root.rglob("*.zip")
    assert archive.read_bytes() == args["content"]
    row, = await _rows(case)
    assert row["events"][-1]["operation"] == failure
    if failure in {"published", "cleanup_intent"}:
        assert len(list(case.root.rglob("*.partial"))) == 1
        assert archive.stat().st_nlink == 2
    else:
        assert list(case.root.rglob("*.partial")) == [] and archive.stat().st_nlink == 1
    assert await case.worker.claim_by_id(claim[0]) is None
    assert not (await registry.execution_snapshot(session_factory=case.sessions))["is_clear"]


@pytest.mark.asyncio
async def test_failed_write_keeps_original_error_and_records_owned_staging_removal(publication_case, monkeypatch):
    case = publication_case
    claim, _ = await _store_owner(case)
    original = OSError("synthetic partial write")
    def partial_write(fd, content):
        publication.os.write(fd, content[:5])
        raise original
    monkeypatch.setattr(publication, "_write_bytes", partial_write)
    with pytest.raises(OSError) as caught:
        await _publish(case, claim, _args(case.root))
    assert caught.value is original
    row, = await _rows(case)
    assert row["events"][-1]["operation"] == "staging_removed"
    assert row["events"][-1]["payload"]["file"]["links"] == 0
    assert row["state"] == "reserved" and not list(case.root.rglob("*.partial"))
    assert not list(case.root.rglob("*.zip"))


@pytest.mark.asyncio
async def test_failed_cleanup_journal_preserves_first_write_error_and_file(publication_case, monkeypatch):
    case = publication_case
    claim, _ = await _store_owner(case)
    error = OSError("synthetic first write failure")
    def fail_write(fd, content):
        raise error
    original = journal.persist_event
    async def fail_cleanup(**kwargs):
        if kwargs["operation"] == "cleanup_intent":
            raise RuntimeError("synthetic database failure")
        await original(**kwargs)
    monkeypatch.setattr(publication, "_write_bytes", fail_write)
    monkeypatch.setattr(journal, "persist_event", fail_cleanup)
    with pytest.raises(OSError) as caught:
        await _publish(case, claim, _args(case.root))
    assert caught.value is error and "unverified" in " ".join(error.__notes__)
    assert len(list(case.root.rglob("*.partial"))) == 1


@pytest.mark.asyncio
async def test_existing_destination_is_never_replaced_or_removed(publication_case):
    case = publication_case
    claim, _ = await _store_owner(case)
    args = _args(case.root)
    destination = args["root"] / args["organization_id"] / args["asset_id"] / "revision-1" / args["filename"]
    destination.parent.mkdir(parents=True, mode=0o700)
    destination.write_bytes(b"unrelated prior output")
    prior = destination.stat().st_ino
    with pytest.raises(FileExistsError):
        await _publish(case, claim, args)
    assert destination.read_bytes() == b"unrelated prior output" and destination.stat().st_ino == prior
    row, = await _rows(case)
    assert not any(event["operation"] == "published" for event in row["events"])
    assert row["events"][-1]["operation"] == "staging_removed"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 3, 16])
async def test_cancellation_joins_storage_and_inflight_publication_commit(publication_case, monkeypatch, count):
    case = publication_case
    claim, _ = await _store_owner(case)
    entered, release = asyncio.Event(), asyncio.Event()
    original = journal.persist_event
    async def pause(**kwargs):
        if kwargs["operation"] == "published":
            entered.set()
            await release.wait()
        await original(**kwargs)
    monkeypatch.setattr(journal, "persist_event", pause)
    task = asyncio.create_task(_publish(case, claim, _args(case.root)))
    try:
        await asyncio.wait_for(entered.wait(), 8)
        for _ in range(count):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()
        row, = await _rows(case)
        assert row["events"][-1]["operation"] == "link_intent"
        assert len(list(case.root.rglob("*.zip"))) == 1
    finally:
        release.set()
        result, = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result, asyncio.CancelledError)
    row, = await _rows(case)
    assert row["state"] == "observed"
    assert not (await registry.execution_snapshot(session_factory=case.sessions))["is_clear"]


@pytest.mark.asyncio
async def test_filesystem_records_survive_business_and_execution_deletion(publication_case):
    case = publication_case
    claim, _ = await _store_owner(case)
    await _publish(case, claim, _args(case.root))
    before = await _rows(case)
    async with case.sessions() as session:
        await session.execute(delete(StudioExecution))
        await session.execute(delete(StudioJob).where(StudioJob.id == claim[0]))
        await session.commit()
    assert await _rows(case) == before
    snapshot = await registry.execution_snapshot(session_factory=case.sessions)
    assert snapshot["orphan_publications"] == 1
    assert snapshot["blocker_count"] == 1 + len(snapshot["unregistered_unverified_job_ids"])
    assert not snapshot["is_clear"]


@pytest.mark.asyncio
async def test_observer_on_loop_thread_fails_without_blocking(publication_case):
    case = publication_case
    claim, owner = await _store_owner(case)
    _, thread_id = await registry.reserve_thread(
        session_factory=case.sessions, job_id=claim[0], nonce=claim[1],
        worker_incarnation=case.worker.incarnation, operation="store_artifact",
    )
    observer = journal.make_publication_observer(case.sessions, owner, thread_id)
    with pytest.raises(registry.StudioResourceUncertain, match="event loop"):
        observer("reserve", {})
    assert await _rows(case) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["execution_id", "job_id", "nonce", "worker_incarnation", "admitted_generation"])
async def test_file_reservation_requires_every_owner_component(publication_case, field):
    case = publication_case
    claim, owner = await _store_owner(case)
    _, thread_id = await registry.reserve_thread(
        session_factory=case.sessions, job_id=claim[0], nonce=claim[1],
        worker_incarnation=case.worker.incarnation, operation="store_artifact",
    )
    wrong = replace(owner, **{field: 8 if field == "admitted_generation" else str(uuid4())})
    observer = journal.make_publication_observer(case.sessions, wrong, thread_id)
    def run():
        with publication_observer(observer):
            return publication.publish_studio_archive(**_args(case.root / "absent"))
    with pytest.raises(registry.StudioResourceUncertain):
        await registry.joined_studio_thread(run)
    assert not (case.root / "absent").exists() and await _rows(case) == []


@pytest.mark.asyncio
async def test_stale_event_sequence_is_rejected_without_altering_evidence(publication_case):
    case = publication_case
    claim, owner = await _store_owner(case)
    entered, release = asyncio.Event(), asyncio.Event()
    original = journal.persist_event
    async def pause(**kwargs):
        await original(**kwargs)
        if kwargs["operation"] == "reserve":
            entered.set()
            await release.wait()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(journal, "persist_event", pause)
    task = asyncio.create_task(_publish(case, claim, _args(case.root)))
    try:
        await asyncio.wait_for(entered.wait(), 8)
        row, = await _rows(case)
        with pytest.raises(registry.StudioOwnershipLost):
            await original(
                session_factory=case.sessions, owner=owner, thread_resource_id=row["thread_resource_id"],
                publication_id=row["id"], expected_count=2, operation="complete", payload={},
            )
        assert await _rows(case) == [row]
    finally:
        release.set()
        await asyncio.gather(task)
        monkeypatch.undo()


def _migration(connection, direction="upgrade"):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260918_0056_studio_publication_journal.py"
    spec = importlib.util.spec_from_file_location("studio_publication_migration_" + uuid4().hex, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


@pytest.mark.asyncio
async def test_frozen_migration_is_repeatable_and_refuses_evidence_discard(publication_case):
    case = publication_case
    claim, _ = await _store_owner(case)
    await _publish(case, claim, _args(case.root))
    before = await _rows(case)
    for _ in range(2):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration)
    assert await _rows(case) == before
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration, "downgrade")
    assert await _rows(case) == before


@pytest.mark.asyncio
async def test_duplicate_execution_publication_is_rejected_by_database(publication_case):
    case = publication_case
    claim, _ = await _store_owner(case)
    await _publish(case, claim, _args(case.root))
    original, = await _rows(case)
    clone = {**original, "id": str(uuid4()), "thread_resource_id": str(uuid4())}
    with pytest.raises(IntegrityError):
        async with case.sessions() as session:
            session.add(StudioPublication(**clone))
            await session.commit()
    assert await _rows(case) == [original]


@pytest.mark.parametrize("field,value", [
    ("root", "/"), ("root", "/tmp/../bad"), ("components", []),
    ("filename", "../escape"), ("size_bytes", True), ("checksum", "invalid"),
    ("staging_name", "archive.zip"),
])
def test_invalid_plan_fails_closed(field, value):
    plan = {"root": "/tmp/test", "components": ["tmp", "test", "org", "asset", "revision-1"],
            "filename": "archive.zip", "staging_name": f".studio-publish-{uuid4().hex}.partial",
            "size_bytes": 12, "checksum": "a" * 64}
    plan[field] = value
    with pytest.raises(registry.StudioResourceUncertain):
        journal.validate_plan(plan)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["sequence", "inode", "links", "stamp", "unknown", "state"])
async def test_corrupt_evidence_cannot_produce_a_clear_snapshot(publication_case, mutation):
    case = publication_case
    claim, _ = await _store_owner(case)
    await _publish(case, claim, _args(case.root))
    async with case.sessions() as session:
        row = await session.scalar(select(StudioPublication))
        events = deepcopy(row.events)
        if mutation == "sequence":
            events.pop(-2)
        elif mutation == "inode":
            events[-1]["payload"]["file"]["inode"] += 1
        elif mutation == "links":
            events[-1]["payload"]["file"]["links"] = 2
        elif mutation == "stamp":
            events[-1]["at"] = datetime(2000, 1, 1, tzinfo=UTC).isoformat()
        elif mutation == "unknown":
            events[-1]["operation"] = "guessed_clean"
        else:
            row.state = "reserved"
        row.events = events
        await session.commit()
    with pytest.raises(registry.StudioResourceUncertain):
        await registry.execution_snapshot(session_factory=case.sessions)


@pytest.mark.asyncio
async def test_publication_survives_reset_and_execution_loss_without_replay_or_starvation(publication_case):
    case = publication_case
    claim, _ = await _store_owner(case)
    await _publish(case, claim, _args(case.root))
    before = await _rows(case)
    async with case.sessions() as session:
        await session.execute(delete(StudioExecution).where(StudioExecution.job_id == claim[0]))
        job = await session.get(StudioJob, claim[0])
        job.status, job.attempts, job.progress = "queued", 0, 0
        job.started_at, job.lease_token, job.result_metadata = None, None, {}
        await session.commit()
    assert await case.worker.claim_by_id(claim[0]) is None
    async with case.sessions() as session:
        with pytest.raises(registry.StudioOwnershipLost):
            await registry.register_claim(
                session, job_id=claim[0], nonce=str(uuid4()), worker_incarnation=case.worker.incarnation,
            )
    fresh = await _shared._shared._new(case)
    acquired = await case.worker.claim()
    assert acquired is not None and acquired[0] == fresh
    assert await _rows(case) == before


@pytest.mark.asyncio
async def test_committed_link_intent_is_visible_before_actual_link(publication_case, monkeypatch):
    case = publication_case
    claim, _ = await _store_owner(case)
    loop = asyncio.get_running_loop()
    actual_link = publication.os.link
    observed = []
    def checked_link(*args, **kwargs):
        rows = asyncio.run_coroutine_threadsafe(_rows(case), loop).result(timeout=8)
        row, = rows
        observed.append(row["events"][-1]["operation"])
        assert observed[-1] == "link_intent"
        return actual_link(*args, **kwargs)
    monkeypatch.setattr(publication.os, "link", checked_link)
    await _publish(case, claim, _args(case.root))
    assert observed == ["link_intent"]


@pytest.mark.asyncio
async def test_replaced_directory_is_not_followed_or_cleaned_by_path(publication_case, monkeypatch):
    case = publication_case
    claim, _ = await _store_owner(case)
    args = _args(case.root)
    target = args["root"] / args["organization_id"] / args["asset_id"] / "revision-1"
    moved = target.with_name("retained-original")
    original = journal.persist_event
    async def replace_directory(**kwargs):
        await original(**kwargs)
        if kwargs["operation"] == "published":
            target.rename(moved)
            target.mkdir(mode=0o700)
            (target / "unrelated.txt").write_bytes(b"must survive")
    monkeypatch.setattr(journal, "persist_event", replace_directory)
    with pytest.raises(publication.StudioPublicationUncertain):
        await _publish(case, claim, args)
    assert (target / "unrelated.txt").read_bytes() == b"must survive"
    assert (moved / args["filename"]).read_bytes() == args["content"]
    row, = await _rows(case)
    assert row["state"] == "reserved"
    assert row["events"][-1]["operation"] == "staging_removed"


@pytest.mark.asyncio
async def test_missing_publication_table_is_not_treated_as_empty_inventory(publication_case):
    case = publication_case
    async with case.engine.begin() as connection:
        await connection.run_sync(lambda conn: StudioPublication.__table__.drop(conn))
    from sqlalchemy.exc import ProgrammingError
    with pytest.raises(ProgrammingError):
        await registry.execution_snapshot(session_factory=case.sessions)
