"""FR-06D8C4B6A durable post-crash containment ledger acceptance."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    StudioCrashContainment,
    StudioCrashObservation,
    StudioExecution,
    StudioJob,
    StudioPrestartCancellation,
    StudioPublication,
)
from app.services import host_maintenance_admission as admission
from app.services import studio_cleanup_candidate as cleanup
from app.services import studio_crash_containment as containment
from app.services import studio_resource_registry as registry

# Reuse the already accepted real PostgreSQL + publication/crash fixture chain.
_B3_NAME = "fr06d8c4b6a_b3_fixture"
_B3_SPEC = importlib.util.spec_from_file_location(
    _B3_NAME,
    Path(__file__).with_name(
        "test_fr06d8c4b3_studio_cleanup_candidate.py"
    ),
)
assert _B3_SPEC is not None and _B3_SPEC.loader is not None
_b3 = importlib.util.module_from_spec(_B3_SPEC)
sys.modules[_B3_NAME] = _b3
_B3_SPEC.loader.exec_module(_b3)
studio_case = _b3.studio_case
execution_case = _b3.execution_case
publication_case = _b3.publication_case

REPO = Path(__file__).resolve().parents[3]


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


b4 = _load_script(
    "fr06d8c4b6a_b4",
    REPO / "scripts/security/fr06d8c4_studio_process_reference_scan.py",
)
b5 = _load_script(
    "fr06d8c4b6a_b5",
    REPO / "scripts/security/fr06d8c4_studio_staging_quarantine.py",
)


@pytest_asyncio.fixture
async def containment_case(publication_case):
    case = publication_case
    async with case.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: StudioCrashContainment.__table__.create(
                conn, checkfirst=True
            )
        )
    return case


def _digest(value: dict, key: str = "receipt_sha256") -> dict:
    body = {name: item for name, item in value.items() if name != key}
    value[key] = b4._sha(body)
    return value


def _container(
    service: str,
    identifier: str,
    volume: Path,
    *,
    rw: bool | None = None,
    started: str | None = None,
) -> dict:
    starts = {
        "backend": "2026-09-20T00:59:00+00:00",
        "studio-worker": "2026-09-20T00:59:30+00:00",
        "backup-worker": "2026-09-20T00:58:00+00:00",
    }
    mounts = []
    if rw is not None:
        mounts.append({
            "Destination": b4.DESTINATION,
            "Source": str(volume),
            "RW": rw,
            "Type": "volume",
            "Name": "studio-volume",
        })
    return {
        "Id": identifier,
        "RestartCount": 0,
        "Config": {
            "Labels": {
                "com.docker.compose.project": b4.PROJECT,
                "com.docker.compose.service": service,
            }
        },
        "State": {
            "Running": True,
            "Status": "running",
            "StartedAt": started or starts.get(
                service, "2026-09-20T00:57:00+00:00"
            ),
        },
        "Mounts": mounts,
    }


def _containers(volume: Path) -> list[dict]:
    return [
        _container("backend", "backend-id", volume, rw=True),
        _container("studio-worker", "studio-id", volume, rw=True),
        _container("backup-worker", "backup-id", volume, rw=False),
        _container("communication-worker", "comm-id", volume),
    ]


def _writer(candidate: dict, volume: Path) -> dict:
    return _digest({
        "schema": b4.WRITER_SCHEMA,
        "observed_at": "2026-09-20T01:00:00+00:00",
        "merge_sha": "a" * 40,
        "admission": {
            "operation_id": candidate["maintenance_operation_id"],
            "generation": candidate["maintenance_generation"],
        },
        "studio_snapshot": {"scope": "studio_execution_threads"},
        "writers": [
            {
                "service": "backend",
                "container_id": "backend-id",
                "started_at": "2026-09-20T00:59:00+00:00",
                "restart_count": 0,
            },
            {
                "service": "studio-worker",
                "container_id": "studio-id",
                "started_at": "2026-09-20T00:59:30+00:00",
                "restart_count": 0,
            },
        ],
        "readers": [
            {
                "service": "backup-worker",
                "container_id": "backup-id",
                "rw": False,
                "source": str(volume),
                "type": "volume",
                "name": "studio-volume",
            }
        ],
        "studio_volume_source": str(volume),
        "application_writer_epoch_verified": True,
        "process_drain_verified": False,
        "host_process_scan_verified": False,
        "backup_cycle_drain_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    })


def _runtime(writer: dict) -> dict:
    return _digest({
        "schema": b4.RUNTIME_SCHEMA,
        "observed_at": "2026-09-20T01:00:01+00:00",
        "writer_receipt_sha256": writer["receipt_sha256"],
        "merge_sha": writer["merge_sha"],
        "operation_id": writer["admission"]["operation_id"],
        "generation": writer["admission"]["generation"],
        "studio_volume_source": writer["studio_volume_source"],
        "writer_container_ids": sorted(
            row["container_id"] for row in writer["writers"]
        ),
        "backup_snapshot_sha256": "2" * 64,
        "application_writer_epoch_verified": True,
        "runtime_container_epoch_stable": True,
        "backup_cycle_drain_verified": True,
        "process_drain_verified": False,
        "host_process_scan_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    })


def _proc_root(tmp_path: Path) -> Path:
    proc = tmp_path / "proc"
    (proc / "100" / "task" / "100" / "fd").mkdir(parents=True)
    (proc / "100" / "map_files").mkdir(parents=True)
    return proc


async def _chain(case, monkeypatch, tmp_path):
    claim, observation = await _b3._crash_publication(
        case,
        monkeypatch,
        failure="link_intent",
        after_commit=False,
    )
    candidate = await cleanup.export_cleanup_candidate(
        observation_id=observation.id,
        session_factory=case.sessions,
    )
    assert candidate["layout"] == "owned_staging_present"
    writer = _writer(candidate, case.root)
    runtime = _runtime(writer)
    containers = _containers(case.root)
    proc = _proc_root(tmp_path)
    scan_receipt = b4.evaluate(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=candidate,
        containers=containers,
        proc_root=proc,
        boot_id="boot-b6a",
    )
    quarantine_receipt = b5.evaluate_and_quarantine(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=candidate,
        process_scan_receipt=scan_receipt,
        container_provider=lambda: _containers(case.root),
        proc_root=proc,
        boot_id="boot-b6a",
    )
    return (
        claim,
        observation,
        candidate,
        scan_receipt,
        quarantine_receipt,
    )


async def _raw(case, observation):
    async with case.sessions() as session:
        execution = (
            await session.execute(
                select(StudioExecution.__table__).where(
                    StudioExecution.id == observation.execution_id
                )
            )
        ).mappings().one()
        publication = (
            await session.execute(
                select(StudioPublication.__table__).where(
                    StudioPublication.id == observation.publication_id
                )
            )
        ).mappings().one()
        crash_row = (
            await session.execute(
                select(StudioCrashObservation.__table__).where(
                    StudioCrashObservation.id == observation.id
                )
            )
        ).mappings().one()
    return (
        deepcopy(dict(execution)),
        deepcopy(dict(publication)),
        deepcopy(dict(crash_row)),
    )


async def _snapshot(case):
    async with case.sessions() as session:
        executions = list(
            (
                await session.scalars(
                    select(StudioExecution).order_by(StudioExecution.id)
                )
            ).all()
        )
        publications = list(
            (
                await session.scalars(
                    select(StudioPublication).order_by(StudioPublication.id)
                )
            ).all()
        )
        jobs = list(
            (
                await session.scalars(
                    select(StudioJob).order_by(StudioJob.id)
                )
            ).all()
        )
        return await containment.snapshot_crash_containments(
            session, executions, publications, jobs
        )


@pytest.mark.asyncio
async def test_real_b3_b4_b5_chain_records_containment_without_terminal_state(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    (
        _claim,
        observation,
        candidate,
        scan_receipt,
        quarantine_receipt,
    ) = await _chain(case, monkeypatch, tmp_path)
    before = await _raw(case, observation)

    row = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=scan_receipt,
        staging_quarantine_receipt=quarantine_receipt,
    )

    assert row.execution_id == observation.execution_id
    assert row.publication_id == observation.publication_id
    assert row.observation_id == observation.id
    assert row.proof["staging_namespace_detached"] is True
    assert row.proof["quarantine_inode_retained"] is True
    assert row.proof["final_layout_preserved"] is True
    assert row.proof["filesystem_cleanup_claimed"] is False
    assert row.proof["blocker_cleared"] is False
    assert row.proof["retry_authorized"] is False
    assert row.proof["process_drain_verified"] is False
    assert row.proof["cleanup_authorized"] is False
    assert row.proof["settlement_authorized"] is False
    assert row.proof["quarantine_deletion_permitted"] is False
    assert row.proof["final_deletion_permitted"] is False
    assert row.proof["full_host_closure"] is False
    assert await _raw(case, observation) == before

    (
        accepted_executions,
        accepted_publications,
        accepted_observations,
        observations,
        _jobs,
        invalid,
    ) = await _snapshot(case)
    assert accepted_executions == {observation.execution_id}
    assert accepted_publications == {observation.publication_id}
    assert accepted_observations == {observation.id}
    assert invalid == 0
    assert len(observations) == 1
    assert observations[0]["valid_containment"] is True
    assert observations[0]["requires_reconciliation"] is True
    assert observations[0]["blocker_cleared"] is False
    assert observations[0]["retry_authorized"] is False


@pytest.mark.asyncio
async def test_repeat_same_chain_is_single_use_idempotent_even_after_authority_rollover(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    first = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )

    async with case.sessions() as session:
        current = await admission.read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
    opened = await admission.open_admission(
        operation_id=current.operation_id,
        expected_generation=current.generation,
        reason="roll containment authority",
        session_factory=case.sessions,
    )
    await admission.close_admission(
        operation_id=str(uuid4()),
        expected_generation=opened.generation,
        reason="new containment authority",
        session_factory=case.sessions,
    )

    second = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    assert second.id == first.id
    async with case.sessions() as session:
        count = await session.scalar(
            select(func.count()).select_from(StudioCrashContainment)
        )
    assert count == 1
    assert second.proof["blocker_cleared"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("receipt_name", "field", "value"),
    [
        ("b4", "cleanup_authorized", True),
        ("b4", "visible_reference_count", 1),
        ("b5", "settlement_authorized", True),
        ("b5", "final_deletion_permitted", True),
        ("b5", "boot_id", "other-boot"),
    ],
)
async def test_tampered_chain_is_rejected_before_db_receipt(
    containment_case,
    monkeypatch,
    tmp_path,
    receipt_name,
    field,
    value,
):
    case = containment_case
    _, _observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    target = b4_receipt if receipt_name == "b4" else b5_receipt
    target[field] = value

    with pytest.raises(
        containment.StudioCrashContainmentUnavailable
    ):
        await containment.record_crash_containment(
            session_factory=case.sessions,
            cleanup_candidate=candidate,
            process_scan_receipt=b4_receipt,
            staging_quarantine_receipt=b5_receipt,
        )
    async with case.sessions() as session:
        assert (
            await session.scalar(
                select(StudioCrashContainment.id).limit(1)
            )
            is None
        )


@pytest.mark.asyncio
async def test_different_valid_chain_cannot_replace_existing_receipt(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, _observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    first = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    changed = deepcopy(b5_receipt)
    changed["observed_at"] = (
        datetime.fromisoformat(changed["observed_at"])
        + timedelta(microseconds=1)
    ).isoformat()
    changed["receipt_sha256"] = b4._sha({
        key: item
        for key, item in changed.items()
        if key != "receipt_sha256"
    })
    with pytest.raises(
        containment.StudioCrashContainmentUnavailable,
        match="existing containment receipt differs",
    ):
        await containment.record_crash_containment(
            session_factory=case.sessions,
            cleanup_candidate=candidate,
            process_scan_receipt=b4_receipt,
            staging_quarantine_receipt=changed,
        )
    async with case.sessions() as session:
        row = await session.get(StudioCrashContainment, first.id)
        assert row.proof_sha256 == first.proof_sha256


@pytest.mark.asyncio
async def test_conflicting_terminal_receipt_blocks_new_containment(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    async with case.sessions() as session:
        execution = await session.get(
            StudioExecution, observation.execution_id
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
        containment.StudioCrashContainmentUnavailable,
        match="conflicting terminal evidence",
    ):
        await containment.record_crash_containment(
            session_factory=case.sessions,
            cleanup_candidate=candidate,
            process_scan_receipt=b4_receipt,
            staging_quarantine_receipt=b5_receipt,
        )


@pytest.mark.asyncio
async def test_raw_evidence_drift_turns_containment_invalid_not_terminal(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    async with case.sessions() as session:
        await session.execute(
            update(StudioExecution)
            .where(StudioExecution.id == observation.execution_id)
            .values(worker_incarnation=str(uuid4()))
        )
        await session.commit()

    result = await _snapshot(case)
    observations, invalid = result[3], result[5]
    assert invalid == 1
    assert result[0] == set()
    assert observations[0]["valid_containment"] is False
    assert observations[0]["requires_reconciliation"] is True
    assert observations[0]["blocker_cleared"] is False


@pytest.mark.asyncio
async def test_missing_execution_keeps_orphan_containment_invalid(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    async with case.sessions() as session:
        await session.execute(
            delete(StudioExecution).where(
                StudioExecution.id == observation.execution_id
            )
        )
        await session.commit()

    result = await _snapshot(case)
    assert result[5] == 1
    assert result[0] == set()
    assert result[3][0]["requires_reconciliation"] is True


def _migration(connection, direction="upgrade"):
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260920_0061_studio_crash_containment.py"
    )
    spec = importlib.util.spec_from_file_location(
        "studio_crash_containment_migration_" + uuid4().hex,
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, direction)()


@pytest.mark.asyncio
async def test_frozen_0061_migration_is_repeatable_and_downgrade_refused(
    containment_case,
):
    case = containment_case
    for _ in range(2):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration)
    with pytest.raises(RuntimeError, match="cannot be discarded"):
        async with case.engine.begin() as connection:
            await connection.run_sync(_migration, "downgrade")


@pytest.mark.asyncio
async def test_database_uniqueness_rejects_second_containment_for_execution(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    first = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    clone = {
        key: value
        for key, value in first.__dict__.items()
        if not key.startswith("_")
    }
    clone["id"] = str(uuid4())
    clone["observation_id"] = str(uuid4())
    clone["publication_id"] = str(uuid4())
    clone["job_id"] = str(uuid4())
    with pytest.raises(IntegrityError):
        async with case.sessions() as session:
            session.add(StudioCrashContainment(**clone))
            await session.commit()


@pytest.mark.asyncio
async def test_recovered_same_boot_b5_receipt_is_bindable(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _claim, observation = await _b3._crash_publication(
        case,
        monkeypatch,
        failure="link_intent",
        after_commit=False,
    )
    candidate = await cleanup.export_cleanup_candidate(
        observation_id=observation.id,
        session_factory=case.sessions,
    )
    writer = _writer(candidate, case.root)
    runtime = _runtime(writer)
    proc = _proc_root(tmp_path)
    scan_receipt = b4.evaluate(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=candidate,
        containers=_containers(case.root),
        proc_root=proc,
        boot_id="boot-b6a-recovery",
    )
    partial, = case.root.rglob("*.partial")
    quarantine = (
        partial.parent
        / (
            ".studio-quarantine-"
            + candidate["candidate_sha256"]
            + ".retained"
        )
    )
    os.rename(partial, quarantine)
    b5_receipt = b5.evaluate_and_quarantine(
        writer_receipt=writer,
        runtime_receipt=runtime,
        cleanup_candidate=candidate,
        process_scan_receipt=scan_receipt,
        container_provider=lambda: _containers(case.root),
        proc_root=proc,
        boot_id="boot-b6a-recovery",
    )
    assert b5_receipt["recovered_existing_quarantine"] is True
    assert b5_receipt["mutation_performed_by_this_run"] is False
    assert b5_receipt["pre_quarantine_scan_passes"] == 0

    row = await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=scan_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    assert row.proof["staging_namespace_detached"] is True
    assert row.proof["blocker_cleared"] is False


@pytest.mark.asyncio
async def test_authority_rollover_before_first_bind_rejects_new_containment(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, _observation, candidate, b4_receipt, b5_receipt = await _chain(
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
        reason="roll before first B6 bind",
        session_factory=case.sessions,
    )
    await admission.close_admission(
        operation_id=str(uuid4()),
        expected_generation=opened.generation,
        reason="new B6 authority",
        session_factory=case.sessions,
    )
    with pytest.raises(
        containment.StudioCrashContainmentUnavailable,
        match="authority differs",
    ):
        await containment.record_crash_containment(
            session_factory=case.sessions,
            cleanup_candidate=candidate,
            process_scan_receipt=b4_receipt,
            staging_quarantine_receipt=b5_receipt,
        )


@pytest.mark.asyncio
async def test_future_b5_receipt_is_rejected_before_db_insert(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, _observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    future = deepcopy(b5_receipt)
    future["observed_at"] = (
        datetime.now(UTC) + timedelta(days=1)
    ).isoformat()
    future["receipt_sha256"] = b4._sha({
        key: item
        for key, item in future.items()
        if key != "receipt_sha256"
    })
    with pytest.raises(
        containment.StudioCrashContainmentUnavailable,
        match="from the future",
    ):
        await containment.record_crash_containment(
            session_factory=case.sessions,
            cleanup_candidate=candidate,
            process_scan_receipt=b4_receipt,
            staging_quarantine_receipt=future,
        )
    async with case.sessions() as session:
        assert await session.scalar(
            select(StudioCrashContainment.id).limit(1)
        ) is None


@pytest.mark.asyncio
async def test_registry_snapshot_reports_containment_without_reducing_blocker(
    containment_case, monkeypatch, tmp_path
):
    case = containment_case
    _, observation, candidate, b4_receipt, b5_receipt = await _chain(
        case, monkeypatch, tmp_path
    )
    before = await registry.execution_snapshot(session_factory=case.sessions)
    await containment.record_crash_containment(
        session_factory=case.sessions,
        cleanup_candidate=candidate,
        process_scan_receipt=b4_receipt,
        staging_quarantine_receipt=b5_receipt,
    )
    after = await registry.execution_snapshot(session_factory=case.sessions)

    assert after["blocker_count"] == before["blocker_count"]
    assert after["postcrash_containment_count"] == 1
    assert after["valid_postcrash_containment_count"] == 1
    assert after["invalid_postcrash_containment_count"] == 0
    assert after["postcrash_containments"][0]["blocker_cleared"] is False
    assert after["postcrash_containments"][0]["requires_reconciliation"] is True
    assert after["postcrash_observations"][0]["containment_recorded"] is True
    assert after["executions"][0]["postcrash_containment_recorded"] is True
    assert after["publications"][0]["postcrash_containment_recorded"] is True
    assert observation.id in {
        item["observation_id"] for item in after["postcrash_containments"]
    }
    assert not after["is_clear"]
