"""Persist retained Studio post-crash containment provenance without settlement.

FR-06D8C4B6A binds the exact B3 cleanup candidate, B4 process-reference
receipt, and B5 retained-quarantine receipt to the immutable C4A crash
observation and raw execution/publication evidence.

This is database-only provenance. It never reads or mutates the Studio
filesystem, never deletes quarantine/final names, never retries work, never
settles an execution, and never clears a Studio blocker. Exact replay of an
already-persisted chain is idempotent even after maintenance authority rolls;
creating a new containment row still requires the matching currently closed
maintenance operation/generation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import (
    StudioCrashContainment,
    StudioCrashObservation,
    StudioExecution,
    StudioJob,
    StudioPoststartCancellation,
    StudioPrestartCancellation,
    StudioPublication,
    StudioSettlement,
)
from app.services import studio_cleanup_candidate as cleanup
from app.services import studio_crash_observation as crash
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry
from app.services.host_maintenance_admission import (
    SessionFactory,
    read_admission_snapshot,
)
from app.services.studio_result_binding import evidence_digest
from app.services.studio_success_settlement import _execution_evidence

SCHEMA = "aionex.studio-crash-containment.v1"
PROCESS_SCAN_SCHEMA = "aionex.studio-process-reference-scan.v1"
QUARANTINE_SCHEMA = "aionex.studio-staging-quarantine.v1"

_PROCESS_KEYS = frozenset({
    "schema", "observed_at", "writer_receipt_sha256",
    "runtime_receipt_sha256", "candidate_sha256", "operation_id",
    "generation", "boot_id", "staging_identity", "scan_passes",
    "visible_reference_count", "candidate_reference_drain_verified",
    "host_process_scan_verified", "process_drain_verified",
    "cleanup_authorized", "filesystem_mutation_performed",
    "final_deletion_permitted", "full_host_closure", "receipt_sha256",
})
_QUARANTINE_KEYS = frozenset({
    "schema", "observed_at", "writer_receipt_sha256",
    "runtime_receipt_sha256", "candidate_sha256",
    "process_scan_receipt_sha256", "operation_id", "generation",
    "boot_id", "staging_name", "quarantine_name", "retained_identity",
    "pre_quarantine_scan_passes", "post_quarantine_scan_passes",
    "recovered_existing_quarantine", "mutation_performed_by_this_run",
    "staging_namespace_detached", "quarantine_inode_retained",
    "final_layout_preserved", "candidate_reference_drain_verified",
    "process_drain_verified", "cleanup_authorized",
    "settlement_authorized", "filesystem_mutation_performed",
    "quarantine_deletion_permitted", "final_deletion_permitted",
    "full_host_closure", "receipt_sha256",
})
_IDENTITY_KEYS = frozenset({
    "device", "inode", "kind", "uid", "gid", "mode", "links", "size",
})
_PROOF_KEYS = frozenset({
    "schema", "organization_id", "observation_id",
    "observation_proof_sha256", "execution_evidence_sha256",
    "publication_evidence_sha256", "candidate_sha256",
    "process_scan_receipt_sha256", "staging_quarantine_receipt_sha256",
    "maintenance_operation_id", "maintenance_generation", "boot_id",
    "layout", "quarantine_name", "retained_identity",
    "staging_namespace_detached", "quarantine_inode_retained",
    "final_layout_preserved", "host_filesystem_mutation_recorded",
    "filesystem_cleanup_claimed", "blocker_cleared", "retry_authorized",
    "process_drain_verified", "cleanup_authorized",
    "settlement_authorized", "quarantine_deletion_permitted",
    "final_deletion_permitted", "full_host_closure",
})


class StudioCrashContainmentUnavailable(RuntimeError):
    """Durable evidence cannot safely bind the supplied host containment chain."""


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _receipt_digest(value: dict[str, Any], label: str) -> str:
    digest = value.get("receipt_sha256")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not _digest(digest) or evidence_digest(body) != digest:
        raise StudioCrashContainmentUnavailable(f"{label} digest differs")
    return digest


def _time(value: Any, label: str) -> datetime:
    try:
        return registry._stamp(value)
    except (
        registry.StudioResourceUncertain,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise StudioCrashContainmentUnavailable(
            f"{label} timestamp is invalid"
        ) from exc


def _identity(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _IDENTITY_KEYS:
        raise StudioCrashContainmentUnavailable(f"{label} identity is malformed")
    if (
        value.get("kind") != "file"
        or any(
            type(value[key]) is not int or value[key] < 0
            for key in _IDENTITY_KEYS - {"kind"}
        )
        or value["inode"] <= 0
        or value["mode"] > 0o7777
    ):
        raise StudioCrashContainmentUnavailable(f"{label} identity is invalid")
    return value


def _candidate_input(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not registry._uuid(value.get("observation_id"))
        or not registry._uuid(value.get("execution_id"))
        or not registry._uuid(value.get("publication_id"))
        or not registry._uuid(value.get("job_id"))
        or not _digest(value.get("candidate_sha256"))
        or value.get("action") != "remove_owned_staging"
        or value.get("process_reference_scan_required") is not True
        or value.get("cleanup_authorized") is not False
        or value.get("filesystem_mutation_performed") is not False
        or value.get("final_deletion_permitted") is not False
        or value.get("full_host_closure") is not False
    ):
        raise StudioCrashContainmentUnavailable(
            "cleanup candidate input is not containment-eligible"
        )
    body = {key: item for key, item in value.items() if key != "candidate_sha256"}
    if evidence_digest(body) != value["candidate_sha256"]:
        raise StudioCrashContainmentUnavailable("cleanup candidate digest differs")
    return value


def _process_receipt(
    value: Any, candidate: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PROCESS_KEYS:
        raise StudioCrashContainmentUnavailable(
            "process scan receipt fields are not exact"
        )
    _receipt_digest(value, "process scan receipt")
    staging = candidate.get("staging")
    expected_identity = (
        staging.get("identity") if isinstance(staging, dict) else None
    )
    current_identity = _identity(value.get("staging_identity"), "process scan")
    if (
        value.get("schema") != PROCESS_SCAN_SCHEMA
        or value.get("candidate_sha256") != candidate["candidate_sha256"]
        or value.get("operation_id")
        != candidate.get("maintenance_operation_id")
        or value.get("generation") != candidate.get("maintenance_generation")
        or not isinstance(value.get("boot_id"), str)
        or not value["boot_id"].strip()
        or current_identity != expected_identity
        or value.get("scan_passes") != 2
        or value.get("visible_reference_count") != 0
        or value.get("candidate_reference_drain_verified") is not True
        or value.get("host_process_scan_verified") is not True
        or value.get("process_drain_verified") is not False
        or value.get("cleanup_authorized") is not False
        or value.get("filesystem_mutation_performed") is not False
        or value.get("final_deletion_permitted") is not False
        or value.get("full_host_closure") is not False
        or not _digest(value.get("writer_receipt_sha256"))
        or not _digest(value.get("runtime_receipt_sha256"))
    ):
        raise StudioCrashContainmentUnavailable(
            "process scan receipt boundary is invalid"
        )
    _time(value.get("observed_at"), "process scan")
    return value


def _quarantine_receipt(
    value: Any,
    candidate: dict[str, Any],
    process_receipt: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _QUARANTINE_KEYS:
        raise StudioCrashContainmentUnavailable(
            "staging quarantine receipt fields are not exact"
        )
    _receipt_digest(value, "staging quarantine receipt")
    retained = _identity(value.get("retained_identity"), "quarantine")
    staging = candidate.get("staging")
    expected_identity = (
        staging.get("identity") if isinstance(staging, dict) else None
    )
    digest = candidate["candidate_sha256"]
    expected_name = f".studio-quarantine-{digest}.retained"
    recovered = value.get("recovered_existing_quarantine")
    mutated = value.get("mutation_performed_by_this_run")
    pre_scans = value.get("pre_quarantine_scan_passes")
    process_time = _time(process_receipt.get("observed_at"), "process scan")
    quarantine_time = _time(value.get("observed_at"), "quarantine")
    if (
        value.get("schema") != QUARANTINE_SCHEMA
        or value.get("writer_receipt_sha256")
        != process_receipt["writer_receipt_sha256"]
        or value.get("runtime_receipt_sha256")
        != process_receipt["runtime_receipt_sha256"]
        or value.get("candidate_sha256") != digest
        or value.get("process_scan_receipt_sha256")
        != process_receipt["receipt_sha256"]
        or value.get("operation_id") != process_receipt["operation_id"]
        or value.get("generation") != process_receipt["generation"]
        or value.get("boot_id") != process_receipt["boot_id"]
        or value.get("staging_name") != candidate.get("staging_name")
        or value.get("quarantine_name") != expected_name
        or retained != expected_identity
        or type(recovered) is not bool
        or type(mutated) is not bool
        or (
            recovered
            and (mutated is not False or pre_scans != 0)
        )
        or (
            not recovered
            and (mutated is not True or pre_scans != 2)
        )
        or value.get("post_quarantine_scan_passes") != 2
        or value.get("staging_namespace_detached") is not True
        or value.get("quarantine_inode_retained") is not True
        or value.get("final_layout_preserved") is not True
        or value.get("candidate_reference_drain_verified") is not True
        or value.get("process_drain_verified") is not False
        or value.get("cleanup_authorized") is not False
        or value.get("settlement_authorized") is not False
        or value.get("filesystem_mutation_performed") is not True
        or value.get("quarantine_deletion_permitted") is not False
        or value.get("final_deletion_permitted") is not False
        or value.get("full_host_closure") is not False
        or quarantine_time < process_time
    ):
        raise StudioCrashContainmentUnavailable(
            "staging quarantine receipt boundary is invalid"
        )
    return value


def _publication_digest(row: StudioPublication) -> str:
    journal.validate_row(row)
    return evidence_digest({
        "plan": deepcopy(row.plan),
        "events": deepcopy(row.events),
    })


def _reconstruct_candidate(
    *,
    observation: StudioCrashObservation,
    execution: StudioExecution,
    publication: StudioPublication,
) -> dict[str, Any]:
    crash.validate_observation(observation)
    proof = observation.proof
    try:
        return cleanup._candidate(
            observation=observation,
            execution=execution,
            publication=publication,
            authority_operation_id=proof["maintenance_operation_id"],
            authority_generation=proof["maintenance_generation"],
        )
    except (
        cleanup.StudioCleanupCandidateUnavailable,
        registry.StudioResourceUncertain,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise StudioCrashContainmentUnavailable(
            "cleanup candidate cannot be reconstructed"
        ) from exc


def _expected_proof(
    *,
    observation: StudioCrashObservation,
    execution: StudioExecution,
    publication: StudioPublication,
    candidate: dict[str, Any],
    process_receipt: dict[str, Any],
    quarantine_receipt: dict[str, Any],
) -> dict[str, Any]:
    owner = registry._owner(execution)
    publication_sha = _publication_digest(publication)
    execution_sha = evidence_digest(_execution_evidence(execution))
    retained = _identity(
        quarantine_receipt["retained_identity"], "quarantine"
    )
    if (
        observation.execution_id != owner.execution_id
        or observation.job_id != owner.job_id
        or observation.worker_incarnation != owner.worker_incarnation
        or observation.admitted_generation != owner.admitted_generation
        or observation.publication_id != publication.id
        or publication.execution_id != owner.execution_id
        or publication.job_id != owner.job_id
        or publication.worker_incarnation != owner.worker_incarnation
        or publication.admitted_generation != owner.admitted_generation
        or observation.proof["execution_evidence_sha256"] != execution_sha
        or observation.proof["publication_evidence_sha256"] != publication_sha
        or candidate["observation_id"] != observation.id
        or candidate["observation_proof_sha256"] != observation.proof_sha256
        or candidate["execution_id"] != execution.id
        or candidate["publication_id"] != publication.id
        or candidate["job_id"] != observation.job_id
        or candidate["candidate_sha256"]
        != process_receipt["candidate_sha256"]
        or candidate["candidate_sha256"]
        != quarantine_receipt["candidate_sha256"]
    ):
        raise StudioCrashContainmentUnavailable(
            "containment chain does not match durable Studio evidence"
        )
    return {
        "schema": SCHEMA,
        "organization_id": observation.proof["organization_id"],
        "observation_id": observation.id,
        "observation_proof_sha256": observation.proof_sha256,
        "execution_evidence_sha256": execution_sha,
        "publication_evidence_sha256": publication_sha,
        "candidate_sha256": candidate["candidate_sha256"],
        "process_scan_receipt_sha256": process_receipt["receipt_sha256"],
        "staging_quarantine_receipt_sha256": quarantine_receipt[
            "receipt_sha256"
        ],
        "maintenance_operation_id": quarantine_receipt["operation_id"],
        "maintenance_generation": quarantine_receipt["generation"],
        "boot_id": quarantine_receipt["boot_id"],
        "layout": candidate["layout"],
        "quarantine_name": quarantine_receipt["quarantine_name"],
        "retained_identity": deepcopy(retained),
        "staging_namespace_detached": True,
        "quarantine_inode_retained": True,
        "final_layout_preserved": True,
        "host_filesystem_mutation_recorded": True,
        "filesystem_cleanup_claimed": False,
        "blocker_cleared": False,
        "retry_authorized": False,
        "process_drain_verified": False,
        "cleanup_authorized": False,
        "settlement_authorized": False,
        "quarantine_deletion_permitted": False,
        "final_deletion_permitted": False,
        "full_host_closure": False,
    }


def validate_containment(
    row: StudioCrashContainment,
    *,
    observation: StudioCrashObservation,
    execution: StudioExecution,
    publication: StudioPublication,
) -> None:
    proof = row.proof
    valid = (
        all(registry._uuid(value) for value in (
            row.id, row.execution_id, row.publication_id,
            row.observation_id, row.job_id, row.worker_incarnation,
        ))
        and type(row.admitted_generation) is int
        and row.admitted_generation >= 7
        and registry._aware(row.created_at)
        and isinstance(proof, dict)
        and set(proof) == _PROOF_KEYS
        and proof.get("schema") == SCHEMA
        and registry._uuid(proof.get("organization_id"))
        and registry._uuid(proof.get("observation_id"))
        and all(_digest(proof.get(key)) for key in (
            "observation_proof_sha256",
            "execution_evidence_sha256",
            "publication_evidence_sha256",
            "candidate_sha256",
            "process_scan_receipt_sha256",
            "staging_quarantine_receipt_sha256",
        ))
        and registry._uuid(proof.get("maintenance_operation_id"))
        and type(proof.get("maintenance_generation")) is int
        and proof["maintenance_generation"] >= 7
        and isinstance(proof.get("boot_id"), str)
        and bool(proof["boot_id"].strip())
        and isinstance(proof.get("layout"), str)
        and isinstance(proof.get("quarantine_name"), str)
        and bool(proof["quarantine_name"])
        and isinstance(proof.get("retained_identity"), dict)
        and set(proof["retained_identity"]) == _IDENTITY_KEYS
        and proof.get("staging_namespace_detached") is True
        and proof.get("quarantine_inode_retained") is True
        and proof.get("final_layout_preserved") is True
        and proof.get("host_filesystem_mutation_recorded") is True
        and proof.get("filesystem_cleanup_claimed") is False
        and proof.get("blocker_cleared") is False
        and proof.get("retry_authorized") is False
        and proof.get("process_drain_verified") is False
        and proof.get("cleanup_authorized") is False
        and proof.get("settlement_authorized") is False
        and proof.get("quarantine_deletion_permitted") is False
        and proof.get("final_deletion_permitted") is False
        and proof.get("full_host_closure") is False
        and evidence_digest(proof) == row.proof_sha256
    )
    if not valid:
        raise registry.StudioResourceUncertain(
            "Studio crash containment proof is invalid"
        )

    crash.validate_observation(observation)
    owner = registry._owner(execution)
    publication_sha = _publication_digest(publication)
    candidate = _reconstruct_candidate(
        observation=observation,
        execution=execution,
        publication=publication,
    )
    expected_quarantine = (
        ".studio-quarantine-"
        + candidate["candidate_sha256"]
        + ".retained"
    )
    staging = candidate.get("staging")
    staging_identity = (
        staging.get("identity") if isinstance(staging, dict) else None
    )
    if (
        row.execution_id != execution.id
        or row.publication_id != publication.id
        or row.observation_id != observation.id
        or row.job_id != observation.job_id
        or row.worker_incarnation != owner.worker_incarnation
        or row.admitted_generation != owner.admitted_generation
        or proof["observation_id"] != observation.id
        or proof["observation_proof_sha256"] != observation.proof_sha256
        or proof["execution_evidence_sha256"]
        != evidence_digest(_execution_evidence(execution))
        or proof["publication_evidence_sha256"] != publication_sha
        or proof["candidate_sha256"] != candidate["candidate_sha256"]
        or proof["organization_id"] != observation.proof["organization_id"]
        or proof["maintenance_operation_id"]
        != observation.proof["maintenance_operation_id"]
        or proof["maintenance_generation"]
        != observation.proof["maintenance_generation"]
        or proof["layout"] != candidate["layout"]
        or proof["quarantine_name"] != expected_quarantine
        or proof["retained_identity"] != staging_identity
    ):
        raise registry.StudioResourceUncertain(
            "Studio crash containment ownership or raw evidence changed"
        )


async def _raw_evidence(
    session: AsyncSession,
    observation_id: str,
) -> tuple[
    StudioCrashObservation,
    StudioExecution,
    StudioPublication,
]:
    observation = await session.scalar(
        select(StudioCrashObservation)
        .where(StudioCrashObservation.id == observation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if observation is None or observation.publication_id is None:
        raise StudioCrashContainmentUnavailable(
            "Studio crash observation or publication is missing"
        )
    execution = await session.scalar(
        select(StudioExecution)
        .where(StudioExecution.id == observation.execution_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    publication = await session.scalar(
        select(StudioPublication)
        .where(StudioPublication.id == observation.publication_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if execution is None or publication is None:
        raise StudioCrashContainmentUnavailable(
            "Studio crash containment raw evidence is missing"
        )
    return observation, execution, publication


async def _terminal_conflict(
    session: AsyncSession,
    execution_id: str,
) -> bool:
    return any((
        await session.scalar(
            select(StudioSettlement.id).where(
                StudioSettlement.execution_id == execution_id
            )
        ),
        await session.scalar(
            select(StudioPrestartCancellation.id).where(
                StudioPrestartCancellation.execution_id == execution_id
            )
        ),
        await session.scalar(
            select(StudioPoststartCancellation.id).where(
                StudioPoststartCancellation.execution_id == execution_id
            )
        ),
    ))


async def record_crash_containment(
    *,
    cleanup_candidate: dict[str, Any],
    process_scan_receipt: dict[str, Any],
    staging_quarantine_receipt: dict[str, Any],
    session_factory: SessionFactory = SessionLocal,
) -> StudioCrashContainment:
    candidate_input = _candidate_input(cleanup_candidate)
    process = _process_receipt(process_scan_receipt, candidate_input)
    quarantine = _quarantine_receipt(
        staging_quarantine_receipt,
        candidate_input,
        process,
    )
    observation_id = candidate_input["observation_id"]

    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            raise StudioCrashContainmentUnavailable(
                "Studio crash containment requires PostgreSQL"
            )
        await session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
        with session.no_autoflush:
            observation, execution, publication = await _raw_evidence(
                session, observation_id
            )
            reconstructed = _reconstruct_candidate(
                observation=observation,
                execution=execution,
                publication=publication,
            )
            if reconstructed != candidate_input:
                raise StudioCrashContainmentUnavailable(
                    "cleanup candidate differs from durable Studio evidence"
                )
            expected = _expected_proof(
                observation=observation,
                execution=execution,
                publication=publication,
                candidate=reconstructed,
                process_receipt=process,
                quarantine_receipt=quarantine,
            )

            existing = await session.scalar(
                select(StudioCrashContainment)
                .where(
                    StudioCrashContainment.observation_id == observation.id
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing is not None:
                try:
                    validate_containment(
                        existing,
                        observation=observation,
                        execution=execution,
                        publication=publication,
                    )
                except registry.StudioResourceUncertain as exc:
                    raise StudioCrashContainmentUnavailable(
                        "existing containment receipt is invalid"
                    ) from exc
                if existing.proof != expected:
                    raise StudioCrashContainmentUnavailable(
                        "existing containment receipt differs"
                    )
                return existing

            if await _terminal_conflict(session, execution.id):
                raise StudioCrashContainmentUnavailable(
                    "conflicting terminal evidence blocks containment"
                )

            authority = await read_admission_snapshot(
                session, required_scope="studio_job_requests"
            )
            if (
                authority.is_open
                or authority.operation_id is None
                or authority.operation_id != quarantine["operation_id"]
                or authority.generation != quarantine["generation"]
            ):
                raise StudioCrashContainmentUnavailable(
                    "containment authority differs from current closed maintenance"
                )

            stamp = await registry._now(session)
            if _time(quarantine["observed_at"], "quarantine") > stamp:
                raise StudioCrashContainmentUnavailable(
                    "staging quarantine receipt is from the future"
                )

            row = StudioCrashContainment(
                id=str(uuid4()),
                execution_id=execution.id,
                publication_id=publication.id,
                observation_id=observation.id,
                job_id=observation.job_id,
                worker_incarnation=observation.worker_incarnation,
                admitted_generation=observation.admitted_generation,
                proof=expected,
                proof_sha256=evidence_digest(expected),
                created_at=stamp,
            )
            validate_containment(
                row,
                observation=observation,
                execution=execution,
                publication=publication,
            )
            session.add(row)
        await session.commit()
        return row


async def snapshot_crash_containments(
    session: AsyncSession,
    executions: list[StudioExecution],
    publications: list[StudioPublication],
    jobs: list[StudioJob],
) -> tuple[
    set[str],
    set[str],
    set[str],
    list[dict[str, Any]],
    set[str],
    int,
]:
    """Return diagnostic containment evidence; never clear a blocker."""
    rows = list((
        await session.scalars(
            select(StudioCrashContainment).order_by(
                StudioCrashContainment.id
            )
        )
    ).all())
    crash_rows = list((
        await session.scalars(
            select(StudioCrashObservation).order_by(
                StudioCrashObservation.id
            )
        )
    ).all())
    crash_by_id = {row.id: row for row in crash_rows}
    executions_by_id = {row.id: row for row in executions}
    publications_by_id = {row.id: row for row in publications}
    jobs_by_id = {row.id: row for row in jobs}
    terminal_execution_ids = set(
        await session.scalars(select(StudioSettlement.execution_id))
    ) | set(
        await session.scalars(select(StudioPrestartCancellation.execution_id))
    ) | set(
        await session.scalars(select(StudioPoststartCancellation.execution_id))
    )

    accepted_executions: set[str] = set()
    accepted_publications: set[str] = set()
    accepted_observations: set[str] = set()
    receipt_jobs: set[str] = set()
    observations: list[dict[str, Any]] = []
    invalid = 0

    for row in rows:
        execution = executions_by_id.get(row.execution_id)
        publication = publications_by_id.get(row.publication_id)
        observation = crash_by_id.get(row.observation_id)
        job = jobs_by_id.get(row.job_id)
        valid = True
        orphan = (
            execution is None
            or publication is None
            or observation is None
        )
        try:
            if orphan:
                raise registry.StudioResourceUncertain(
                    "Studio crash containment lost raw evidence"
                )
            assert execution is not None
            assert publication is not None
            assert observation is not None
            validate_containment(
                row,
                observation=observation,
                execution=execution,
                publication=publication,
            )
            if row.execution_id in terminal_execution_ids:
                raise registry.StudioResourceUncertain(
                    "Studio crash containment conflicts with terminal evidence"
                )
            if (
                job is not None
                and job.organization_id
                != observation.proof["organization_id"]
            ):
                raise registry.StudioResourceUncertain(
                    "Studio crash containment tenant differs"
                )
        except (
            StudioCrashContainmentUnavailable,
            registry.StudioResourceUncertain,
            ValueError,
            TypeError,
            KeyError,
            AssertionError,
        ):
            valid = False

        receipt_jobs.add(row.job_id)
        invalid += int(not valid)
        if valid:
            accepted_executions.add(row.execution_id)
            accepted_publications.add(row.publication_id)
            accepted_observations.add(row.observation_id)
        observations.append({
            "containment_id": row.id,
            "execution_id": row.execution_id,
            "publication_id": row.publication_id,
            "observation_id": row.observation_id,
            "job_id": row.job_id,
            "admitted_generation": row.admitted_generation,
            "layout": (
                row.proof.get("layout")
                if isinstance(row.proof, dict)
                else None
            ),
            "valid_containment": valid,
            "orphan_raw_evidence": orphan,
            "requires_reconciliation": True,
            "staging_namespace_detached": (
                valid
                and row.proof.get("staging_namespace_detached") is True
            ),
            "quarantine_retained": (
                valid
                and row.proof.get("quarantine_inode_retained") is True
            ),
            "filesystem_cleanup_claimed": False,
            "blocker_cleared": False,
            "retry_authorized": False,
            "cleanup_authorized": False,
            "settlement_authorized": False,
        })

    return (
        accepted_executions,
        accepted_publications,
        accepted_observations,
        observations,
        receipt_jobs,
        invalid,
    )
