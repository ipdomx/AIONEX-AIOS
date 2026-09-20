"""Immutable terminal reconciliation for one safely retained Studio crash.

FR-06D8C4B6B3 is database-only. It consumes the exact B6B1 terminal candidate
and B6B2 host revalidation receipt, revalidates the retained B6A/raw evidence,
and records a terminal crash outcome only while the same closed Studio
maintenance authority is still current.

The terminal outcome keeps the quarantine and all raw evidence. It never retries,
settles as success, deletes quarantine/final names, performs filesystem cleanup,
or claims full process/host drain.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import (
    StudioCrashContainment,
    StudioCrashObservation,
    StudioCrashReconciliation,
    StudioExecution,
    StudioJob,
    StudioPoststartCancellation,
    StudioPrestartCancellation,
    StudioPublication,
    StudioSettlement,
)
from app.services import studio_crash_containment as containment
from app.services import studio_crash_terminal_candidate as terminal_candidate
from app.services import studio_resource_registry as registry
from app.services.host_maintenance_admission import (
    SessionFactory,
    read_admission_snapshot,
)
from app.services.studio_result_binding import evidence_digest

SCHEMA = "aionex.studio-crash-reconciliation.v1"
CANDIDATE_SCHEMA = "aionex.studio-crash-terminal-candidate.v1"
HOST_RECEIPT_SCHEMA = "aionex.studio-quarantine-revalidation.v1"

_CANDIDATE_KEYS = {
    "schema",
    "containment_id",
    "containment_proof_sha256",
    "observation_id",
    "observation_proof_sha256",
    "execution_id",
    "publication_id",
    "job_id",
    "organization_id",
    "worker_incarnation",
    "admitted_generation",
    "containment_operation_id",
    "containment_generation",
    "containment_boot_id",
    "cleanup_candidate_sha256",
    "process_scan_receipt_sha256",
    "staging_quarantine_receipt_sha256",
    "layout",
    "relative_components",
    "original_staging_name",
    "final_name",
    "final_evidence",
    "archive_size_bytes",
    "archive_checksum_sha256",
    "quarantine_name",
    "retained_identity",
    "reconciliation_authority",
    "reconciliation_authority_sha256",
    "host_revalidation_required",
    "quarantine_revalidation_required",
    "terminalization_authorized",
    "blocker_cleared",
    "retry_authorized",
    "filesystem_cleanup_claimed",
    "cleanup_authorized",
    "settlement_authorized",
    "quarantine_deletion_permitted",
    "final_deletion_permitted",
    "full_host_closure",
    "candidate_sha256",
}
_AUTHORITY_KEYS = {
    "schema_version",
    "scope",
    "generation",
    "status",
    "enabled",
    "operation_id",
    "reason",
    "changed_at",
    "full_host_closure",
}
_HOST_RECEIPT_KEYS = {
    "schema",
    "observed_at",
    "terminal_candidate_sha256",
    "containment_id",
    "reconciliation_authority_sha256",
    "containment_boot_id",
    "current_boot_id",
    "same_boot_as_containment",
    "studio_volume_source",
    "container_inventory",
    "container_inventory_sha256",
    "retained_identity",
    "archive_size_bytes",
    "archive_checksum_sha256",
    "content_hash_passes",
    "archive_content_revalidated",
    "scan_passes",
    "visible_reference_count",
    "current_container_epoch_stable",
    "staging_name_absent",
    "quarantine_identity_revalidated",
    "final_layout_revalidated",
    "quarantine_reference_drain_verified",
    "host_process_scan_verified",
    "process_drain_verified",
    "authority_revalidation_required_by_next_stage",
    "terminalization_authorized",
    "blocker_cleared",
    "retry_authorized",
    "filesystem_cleanup_claimed",
    "filesystem_mutation_performed",
    "cleanup_authorized",
    "settlement_authorized",
    "quarantine_deletion_permitted",
    "final_deletion_permitted",
    "full_host_closure",
    "receipt_sha256",
}
_CONTAINER_KEYS = {
    "service",
    "container_id",
    "restart_count",
    "started_at",
    "rw",
    "source",
    "type",
    "name",
}
_PROOF_KEYS = {
    "schema",
    "organization_id",
    "containment_id",
    "containment_proof_sha256",
    "observation_id",
    "observation_proof_sha256",
    "execution_evidence_sha256",
    "publication_evidence_sha256",
    "cleanup_candidate_sha256",
    "terminal_candidate_sha256",
    "quarantine_revalidation_receipt_sha256",
    "reconciliation_authority_sha256",
    "reconciliation_operation_id",
    "reconciliation_generation",
    "containment_operation_id",
    "containment_generation",
    "containment_boot_id",
    "host_revalidation_boot_id",
    "same_boot_as_containment",
    "container_inventory_sha256",
    "retained_identity",
    "archive_size_bytes",
    "archive_checksum_sha256",
    "content_hash_passes",
    "process_reference_scan_passes",
    "archive_content_revalidated",
    "quarantine_reference_drain_verified",
    "host_process_scan_verified",
    "current_container_epoch_stable",
    "staging_name_absent",
    "quarantine_identity_revalidated",
    "final_layout_revalidated",
    "authority_revalidated",
    "terminal_state",
    "terminal_reconciliation_recorded",
    "terminalization_authorized",
    "blocker_cleared",
    "retry_authorized",
    "filesystem_cleanup_claimed",
    "filesystem_mutation_performed_by_b6b3",
    "cleanup_authorized",
    "settlement_authorized",
    "quarantine_retained",
    "quarantine_deletion_permitted",
    "final_deletion_permitted",
    "process_drain_verified",
    "full_host_closure",
}


class StudioCrashReconciliationUnavailable(RuntimeError):
    """Crash evidence is insufficient or inconsistent for terminalization."""


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise StudioCrashReconciliationUnavailable(f"{label} is missing")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StudioCrashReconciliationUnavailable(
            f"{label} is malformed"
        ) from exc
    if not registry._aware(result):
        raise StudioCrashReconciliationUnavailable(
            f"{label} lacks timezone"
        )
    return result


def _candidate(
    value: Any,
    *,
    row: StudioCrashContainment,
    observation: StudioCrashObservation,
    execution: StudioExecution,
    publication: StudioPublication,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CANDIDATE_KEYS:
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate fields are not exact"
        )
    body = {
        key: item for key, item in value.items() if key != "candidate_sha256"
    }
    if (
        value.get("schema") != CANDIDATE_SCHEMA
        or not _digest(value.get("candidate_sha256"))
        or evidence_digest(body) != value["candidate_sha256"]
    ):
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate digest differs"
        )
    for key in (
        "containment_id",
        "observation_id",
        "execution_id",
        "publication_id",
        "job_id",
        "organization_id",
        "worker_incarnation",
        "containment_operation_id",
    ):
        if not registry._uuid(value.get(key)):
            raise StudioCrashReconciliationUnavailable(
                f"terminal candidate {key} is invalid"
            )
    for key in (
        "containment_proof_sha256",
        "observation_proof_sha256",
        "cleanup_candidate_sha256",
        "process_scan_receipt_sha256",
        "staging_quarantine_receipt_sha256",
        "reconciliation_authority_sha256",
        "archive_checksum_sha256",
    ):
        if not _digest(value.get(key)):
            raise StudioCrashReconciliationUnavailable(
                f"terminal candidate {key} is invalid"
            )
    if (
        type(value.get("admitted_generation")) is not int
        or value["admitted_generation"] < 7
        or type(value.get("containment_generation")) is not int
        or value["containment_generation"] < 7
        or type(value.get("archive_size_bytes")) is not int
        or value["archive_size_bytes"] < 0
        or not isinstance(value.get("containment_boot_id"), str)
        or not value["containment_boot_id"].strip()
    ):
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate scalar evidence is invalid"
        )

    authority = value.get("reconciliation_authority")
    if not isinstance(authority, dict) or set(authority) != _AUTHORITY_KEYS:
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate authority fields differ"
        )
    if (
        evidence_digest(authority) != value["reconciliation_authority_sha256"]
        or authority.get("status") != "closed"
        or authority.get("enabled") is not False
        or authority.get("full_host_closure") is not False
        or type(authority.get("generation")) is not int
        or authority["generation"] < value["containment_generation"]
        or not registry._uuid(authority.get("operation_id"))
        or not isinstance(authority.get("scope"), str)
        or not authority["scope"]
        or not isinstance(authority.get("reason"), str)
        or not authority["reason"]
    ):
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate authority is invalid"
        )
    _time(authority.get("changed_at"), "reconciliation authority changed_at")

    if (
        value.get("host_revalidation_required") is not True
        or value.get("quarantine_revalidation_required") is not True
        or value.get("terminalization_authorized") is not False
        or value.get("blocker_cleared") is not False
        or value.get("retry_authorized") is not False
        or value.get("filesystem_cleanup_claimed") is not False
        or value.get("cleanup_authorized") is not False
        or value.get("settlement_authorized") is not False
        or value.get("quarantine_deletion_permitted") is not False
        or value.get("final_deletion_permitted") is not False
        or value.get("full_host_closure") is not False
    ):
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate safety boundary differs"
        )

    try:
        containment.validate_containment(
            row,
            observation=observation,
            execution=execution,
            publication=publication,
        )
        cleanup_candidate = containment._reconstruct_candidate(
            observation=observation,
            execution=execution,
            publication=publication,
        )
    except (
        containment.StudioCrashContainmentUnavailable,
        registry.StudioResourceUncertain,
    ) as exc:
        raise StudioCrashReconciliationUnavailable(
            "crash containment or raw evidence is invalid"
        ) from exc

    publication_size = publication.plan.get("size_bytes")
    publication_checksum = publication.plan.get("checksum")
    if (
        row.id != value["containment_id"]
        or row.proof_sha256 != value["containment_proof_sha256"]
        or row.observation_id != value["observation_id"]
        or row.execution_id != value["execution_id"]
        or row.publication_id != value["publication_id"]
        or row.job_id != value["job_id"]
        or row.worker_incarnation != value["worker_incarnation"]
        or row.admitted_generation != value["admitted_generation"]
        or observation.proof_sha256 != value["observation_proof_sha256"]
        or observation.proof.get("organization_id")
        != value["organization_id"]
        or row.proof.get("maintenance_operation_id")
        != value["containment_operation_id"]
        or row.proof.get("maintenance_generation")
        != value["containment_generation"]
        or row.proof.get("boot_id") != value["containment_boot_id"]
        or row.proof.get("candidate_sha256")
        != value["cleanup_candidate_sha256"]
        or row.proof.get("process_scan_receipt_sha256")
        != value["process_scan_receipt_sha256"]
        or row.proof.get("staging_quarantine_receipt_sha256")
        != value["staging_quarantine_receipt_sha256"]
        or row.proof.get("layout") != value["layout"]
        or row.proof.get("quarantine_name") != value["quarantine_name"]
        or row.proof.get("retained_identity") != value["retained_identity"]
        or cleanup_candidate.get("relative_components")
        != value["relative_components"]
        or cleanup_candidate.get("staging_name")
        != value["original_staging_name"]
        or cleanup_candidate.get("final_name") != value["final_name"]
        or cleanup_candidate.get("final") != value["final_evidence"]
        or cleanup_candidate.get("candidate_sha256")
        != value["cleanup_candidate_sha256"]
        or publication_size != value["archive_size_bytes"]
        or publication_checksum != value["archive_checksum_sha256"]
    ):
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate differs from durable crash evidence"
        )
    return value


def _host_receipt(
    value: Any,
    *,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _HOST_RECEIPT_KEYS:
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation receipt fields are not exact"
        )
    body = {
        key: item for key, item in value.items() if key != "receipt_sha256"
    }
    if (
        value.get("schema") != HOST_RECEIPT_SCHEMA
        or not _digest(value.get("receipt_sha256"))
        or evidence_digest(body) != value["receipt_sha256"]
        or value.get("terminal_candidate_sha256")
        != candidate["candidate_sha256"]
        or value.get("containment_id") != candidate["containment_id"]
        or value.get("reconciliation_authority_sha256")
        != candidate["reconciliation_authority_sha256"]
        or value.get("containment_boot_id")
        != candidate["containment_boot_id"]
        or value.get("retained_identity") != candidate["retained_identity"]
        or value.get("archive_size_bytes")
        != candidate["archive_size_bytes"]
        or value.get("archive_checksum_sha256")
        != candidate["archive_checksum_sha256"]
    ):
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation receipt differs from terminal candidate"
        )
    _time(value.get("observed_at"), "quarantine revalidation observed_at")
    current_boot = value.get("current_boot_id")
    if not isinstance(current_boot, str) or not current_boot.strip():
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation boot id is invalid"
        )
    if value.get("same_boot_as_containment") is not (
        current_boot == candidate["containment_boot_id"]
    ):
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation boot relation differs"
        )

    source = value.get("studio_volume_source")
    if (
        not isinstance(source, str)
        or not source
        or not Path(source).is_absolute()
        or Path(source) == Path("/")
        or ".." in Path(source).parts
    ):
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation source is unsafe"
        )
    inventory = value.get("container_inventory")
    if not isinstance(inventory, list) or len(inventory) != 3:
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation container inventory differs"
        )
    if (
        not _digest(value.get("container_inventory_sha256"))
        or evidence_digest(inventory) != value["container_inventory_sha256"]
    ):
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation container digest differs"
        )
    services: set[str] = set()
    for item in inventory:
        if not isinstance(item, dict) or set(item) != _CONTAINER_KEYS:
            raise StudioCrashReconciliationUnavailable(
                "quarantine revalidation container entry differs"
            )
        service = item.get("service")
        if (
            not isinstance(service, str)
            or service not in {"backend", "studio-worker", "backup-worker"}
        ):
            raise StudioCrashReconciliationUnavailable(
                "quarantine revalidation service is invalid"
            )
        services.add(service)
        expected_rw = service in {"backend", "studio-worker"}
        if (
            not isinstance(item.get("container_id"), str)
            or not item["container_id"]
            or type(item.get("restart_count")) is not int
            or item["restart_count"] < 0
            or not isinstance(item.get("started_at"), str)
            or item.get("rw") is not expected_rw
            or item.get("source") != source
        ):
            raise StudioCrashReconciliationUnavailable(
                "quarantine revalidation container epoch is invalid"
            )
        _time(item["started_at"], f"{service} started_at")
    if services != {"backend", "studio-worker", "backup-worker"}:
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation service set differs"
        )

    if (
        value.get("content_hash_passes") != 2
        or value.get("archive_content_revalidated") is not True
        or value.get("scan_passes") != 2
        or value.get("visible_reference_count") != 0
        or value.get("current_container_epoch_stable") is not True
        or value.get("staging_name_absent") is not True
        or value.get("quarantine_identity_revalidated") is not True
        or value.get("final_layout_revalidated") is not True
        or value.get("quarantine_reference_drain_verified") is not True
        or value.get("host_process_scan_verified") is not True
        or value.get("process_drain_verified") is not False
        or value.get("authority_revalidation_required_by_next_stage") is not True
        or value.get("terminalization_authorized") is not False
        or value.get("blocker_cleared") is not False
        or value.get("retry_authorized") is not False
        or value.get("filesystem_cleanup_claimed") is not False
        or value.get("filesystem_mutation_performed") is not False
        or value.get("cleanup_authorized") is not False
        or value.get("settlement_authorized") is not False
        or value.get("quarantine_deletion_permitted") is not False
        or value.get("final_deletion_permitted") is not False
        or value.get("full_host_closure") is not False
    ):
        raise StudioCrashReconciliationUnavailable(
            "quarantine revalidation safety boundary differs"
        )
    return value


def _expected_proof(
    *,
    candidate: dict[str, Any],
    host_receipt: dict[str, Any],
    containment_row: StudioCrashContainment,
    observation: StudioCrashObservation,
    execution: StudioExecution,
    publication: StudioPublication,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "organization_id": candidate["organization_id"],
        "containment_id": containment_row.id,
        "containment_proof_sha256": containment_row.proof_sha256,
        "observation_id": observation.id,
        "observation_proof_sha256": observation.proof_sha256,
        "execution_evidence_sha256": evidence_digest(
            containment._execution_evidence(execution)
        ),
        "publication_evidence_sha256": containment._publication_digest(
            publication
        ),
        "cleanup_candidate_sha256": candidate["cleanup_candidate_sha256"],
        "terminal_candidate_sha256": candidate["candidate_sha256"],
        "quarantine_revalidation_receipt_sha256": host_receipt["receipt_sha256"],
        "reconciliation_authority_sha256": candidate[
            "reconciliation_authority_sha256"
        ],
        "reconciliation_operation_id": candidate[
            "reconciliation_authority"
        ]["operation_id"],
        "reconciliation_generation": candidate[
            "reconciliation_authority"
        ]["generation"],
        "containment_operation_id": candidate["containment_operation_id"],
        "containment_generation": candidate["containment_generation"],
        "containment_boot_id": candidate["containment_boot_id"],
        "host_revalidation_boot_id": host_receipt["current_boot_id"],
        "same_boot_as_containment": host_receipt["same_boot_as_containment"],
        "container_inventory_sha256": host_receipt[
            "container_inventory_sha256"
        ],
        "retained_identity": deepcopy(candidate["retained_identity"]),
        "archive_size_bytes": candidate["archive_size_bytes"],
        "archive_checksum_sha256": candidate["archive_checksum_sha256"],
        "content_hash_passes": 2,
        "process_reference_scan_passes": 2,
        "archive_content_revalidated": True,
        "quarantine_reference_drain_verified": True,
        "host_process_scan_verified": True,
        "current_container_epoch_stable": True,
        "staging_name_absent": True,
        "quarantine_identity_revalidated": True,
        "final_layout_revalidated": True,
        "authority_revalidated": True,
        "terminal_state": "crash_reconciled_quarantine_retained",
        "terminal_reconciliation_recorded": True,
        "terminalization_authorized": True,
        "blocker_cleared": True,
        "retry_authorized": False,
        "filesystem_cleanup_claimed": False,
        "filesystem_mutation_performed_by_b6b3": False,
        "cleanup_authorized": False,
        "settlement_authorized": False,
        "quarantine_retained": True,
        "quarantine_deletion_permitted": False,
        "final_deletion_permitted": False,
        "process_drain_verified": False,
        "full_host_closure": False,
    }


def validate_reconciliation(
    row: StudioCrashReconciliation,
    *,
    containment_row: StudioCrashContainment,
    observation: StudioCrashObservation,
    execution: StudioExecution,
    publication: StudioPublication,
) -> None:
    proof = row.proof
    valid = (
        all(
            registry._uuid(value)
            for value in (
                row.id,
                row.containment_id,
                row.execution_id,
                row.publication_id,
                row.observation_id,
                row.job_id,
                row.worker_incarnation,
            )
        )
        and type(row.admitted_generation) is int
        and row.admitted_generation >= 7
        and registry._aware(row.created_at)
        and isinstance(proof, dict)
        and set(proof) == _PROOF_KEYS
        and proof.get("schema") == SCHEMA
        and registry._uuid(proof.get("organization_id"))
        and registry._uuid(proof.get("containment_id"))
        and registry._uuid(proof.get("observation_id"))
        and registry._uuid(proof.get("reconciliation_operation_id"))
        and all(
            _digest(proof.get(key))
            for key in (
                "containment_proof_sha256",
                "observation_proof_sha256",
                "execution_evidence_sha256",
                "publication_evidence_sha256",
                "cleanup_candidate_sha256",
                "terminal_candidate_sha256",
                "quarantine_revalidation_receipt_sha256",
                "reconciliation_authority_sha256",
                "container_inventory_sha256",
                "archive_checksum_sha256",
            )
        )
        and type(proof.get("reconciliation_generation")) is int
        and proof["reconciliation_generation"] >= 7
        and type(proof.get("containment_generation")) is int
        and proof["containment_generation"] >= 7
        and isinstance(proof.get("containment_boot_id"), str)
        and bool(proof["containment_boot_id"].strip())
        and isinstance(proof.get("host_revalidation_boot_id"), str)
        and bool(proof["host_revalidation_boot_id"].strip())
        and isinstance(proof.get("same_boot_as_containment"), bool)
        and isinstance(proof.get("retained_identity"), dict)
        and type(proof.get("archive_size_bytes")) is int
        and proof["archive_size_bytes"] >= 0
        and proof.get("content_hash_passes") == 2
        and proof.get("process_reference_scan_passes") == 2
        and proof.get("archive_content_revalidated") is True
        and proof.get("quarantine_reference_drain_verified") is True
        and proof.get("host_process_scan_verified") is True
        and proof.get("current_container_epoch_stable") is True
        and proof.get("staging_name_absent") is True
        and proof.get("quarantine_identity_revalidated") is True
        and proof.get("final_layout_revalidated") is True
        and proof.get("authority_revalidated") is True
        and proof.get("terminal_state")
        == "crash_reconciled_quarantine_retained"
        and proof.get("terminal_reconciliation_recorded") is True
        and proof.get("terminalization_authorized") is True
        and proof.get("blocker_cleared") is True
        and proof.get("retry_authorized") is False
        and proof.get("filesystem_cleanup_claimed") is False
        and proof.get("filesystem_mutation_performed_by_b6b3") is False
        and proof.get("cleanup_authorized") is False
        and proof.get("settlement_authorized") is False
        and proof.get("quarantine_retained") is True
        and proof.get("quarantine_deletion_permitted") is False
        and proof.get("final_deletion_permitted") is False
        and proof.get("process_drain_verified") is False
        and proof.get("full_host_closure") is False
        and evidence_digest(proof) == row.proof_sha256
    )
    if not valid:
        raise registry.StudioResourceUncertain(
            "Studio crash reconciliation proof is invalid"
        )

    containment.validate_containment(
        containment_row,
        observation=observation,
        execution=execution,
        publication=publication,
    )
    if (
        row.containment_id != containment_row.id
        or row.execution_id != execution.id
        or row.publication_id != publication.id
        or row.observation_id != observation.id
        or row.job_id != observation.job_id
        or row.worker_incarnation != execution.worker_incarnation
        or row.admitted_generation != execution.admitted_generation
        or proof["organization_id"]
        != observation.proof["organization_id"]
        or proof["containment_id"] != containment_row.id
        or proof["containment_proof_sha256"]
        != containment_row.proof_sha256
        or proof["observation_id"] != observation.id
        or proof["observation_proof_sha256"]
        != observation.proof_sha256
        or proof["execution_evidence_sha256"]
        != evidence_digest(containment._execution_evidence(execution))
        or proof["publication_evidence_sha256"]
        != containment._publication_digest(publication)
        or proof["cleanup_candidate_sha256"]
        != containment_row.proof["candidate_sha256"]
        or proof["containment_operation_id"]
        != containment_row.proof["maintenance_operation_id"]
        or proof["containment_generation"]
        != containment_row.proof["maintenance_generation"]
        or proof["containment_boot_id"] != containment_row.proof["boot_id"]
        or proof["retained_identity"]
        != containment_row.proof["retained_identity"]
        or proof["archive_size_bytes"] != publication.plan["size_bytes"]
        or proof["archive_checksum_sha256"] != publication.plan["checksum"]
    ):
        raise registry.StudioResourceUncertain(
            "Studio crash reconciliation raw evidence changed"
        )


async def record_crash_reconciliation(
    *,
    terminal_candidate_input: dict[str, Any],
    quarantine_revalidation_receipt: dict[str, Any],
    session_factory: SessionFactory = SessionLocal,
) -> StudioCrashReconciliation:
    containment_id = terminal_candidate_input.get("containment_id")
    if not registry._uuid(containment_id):
        raise StudioCrashReconciliationUnavailable(
            "terminal candidate containment_id is invalid"
        )

    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            raise StudioCrashReconciliationUnavailable(
                "Studio crash reconciliation requires PostgreSQL"
            )
        await session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))

        with session.no_autoflush:
            containment_row = await session.scalar(
                select(StudioCrashContainment)
                .where(StudioCrashContainment.id == containment_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if containment_row is None:
                raise StudioCrashReconciliationUnavailable(
                    "Studio crash containment is missing"
                )
            observation, execution, publication = await containment._raw_evidence(
                session, containment_row.observation_id
            )
            checked_candidate = _candidate(
                terminal_candidate_input,
                row=containment_row,
                observation=observation,
                execution=execution,
                publication=publication,
            )
            checked_host = _host_receipt(
                quarantine_revalidation_receipt,
                candidate=checked_candidate,
            )
            expected = _expected_proof(
                candidate=checked_candidate,
                host_receipt=checked_host,
                containment_row=containment_row,
                observation=observation,
                execution=execution,
                publication=publication,
            )

            existing = await session.scalar(
                select(StudioCrashReconciliation)
                .where(
                    StudioCrashReconciliation.containment_id
                    == containment_row.id
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing is not None:
                try:
                    validate_reconciliation(
                        existing,
                        containment_row=containment_row,
                        observation=observation,
                        execution=execution,
                        publication=publication,
                    )
                except registry.StudioResourceUncertain as exc:
                    raise StudioCrashReconciliationUnavailable(
                        "existing crash reconciliation is invalid"
                    ) from exc
                if existing.proof != expected:
                    raise StudioCrashReconciliationUnavailable(
                        "existing crash reconciliation differs"
                    )
                return existing

            if await terminal_candidate._terminal_conflict(
                session, execution.id
            ):
                raise StudioCrashReconciliationUnavailable(
                    "conflicting terminal evidence blocks crash reconciliation"
                )

            current = await read_admission_snapshot(
                session, required_scope="studio_job_requests"
            )
            try:
                current_authority = terminal_candidate._authority_payload(
                    current
                )
            except terminal_candidate.StudioCrashTerminalCandidateUnavailable as exc:
                raise StudioCrashReconciliationUnavailable(
                    "current Studio maintenance authority is not closed"
                ) from exc
            if (
                current_authority
                != checked_candidate["reconciliation_authority"]
                or evidence_digest(current_authority)
                != checked_candidate["reconciliation_authority_sha256"]
            ):
                raise StudioCrashReconciliationUnavailable(
                    "current Studio maintenance authority changed after host revalidation"
                )

            stamp = await registry._now(session)
            observed_at = _time(
                checked_host["observed_at"],
                "quarantine revalidation observed_at",
            )
            authority_changed_at = _time(
                checked_candidate["reconciliation_authority"]["changed_at"],
                "reconciliation authority changed_at",
            )
            if observed_at < authority_changed_at or observed_at > stamp:
                raise StudioCrashReconciliationUnavailable(
                    "quarantine revalidation time is outside the current authority window"
                )

            row = StudioCrashReconciliation(
                id=str(uuid4()),
                containment_id=containment_row.id,
                execution_id=execution.id,
                publication_id=publication.id,
                observation_id=observation.id,
                job_id=observation.job_id,
                worker_incarnation=execution.worker_incarnation,
                admitted_generation=execution.admitted_generation,
                proof=expected,
                proof_sha256=evidence_digest(expected),
                created_at=stamp,
            )
            validate_reconciliation(
                row,
                containment_row=containment_row,
                observation=observation,
                execution=execution,
                publication=publication,
            )
            session.add(row)
        await session.commit()
        return row


async def snapshot_crash_reconciliations(
    session: AsyncSession,
    executions: list[StudioExecution],
    publications: list[StudioPublication],
    jobs: list[StudioJob],
) -> tuple[
    set[str],
    set[str],
    set[str],
    set[str],
    list[dict[str, Any]],
    set[str],
    int,
]:
    rows = list(
        (
            await session.scalars(
                select(StudioCrashReconciliation).order_by(
                    StudioCrashReconciliation.id
                )
            )
        ).all()
    )
    containments = list(
        (
            await session.scalars(
                select(StudioCrashContainment).order_by(
                    StudioCrashContainment.id
                )
            )
        ).all()
    )
    crash_rows = list(
        (
            await session.scalars(
                select(StudioCrashObservation).order_by(
                    StudioCrashObservation.id
                )
            )
        ).all()
    )
    containment_by_id = {row.id: row for row in containments}
    crash_by_id = {row.id: row for row in crash_rows}
    execution_by_id = {row.id: row for row in executions}
    publication_by_id = {row.id: row for row in publications}
    job_by_id = {row.id: row for row in jobs}

    terminal_conflicts = set(
        await session.scalars(select(StudioSettlement.execution_id))
    ) | set(
        await session.scalars(select(StudioPrestartCancellation.execution_id))
    ) | set(
        await session.scalars(select(StudioPoststartCancellation.execution_id))
    )

    accepted_executions: set[str] = set()
    accepted_publications: set[str] = set()
    accepted_observations: set[str] = set()
    accepted_containments: set[str] = set()
    receipt_jobs: set[str] = set()
    observations: list[dict[str, Any]] = []
    invalid = 0

    for row in rows:
        containment_row = containment_by_id.get(row.containment_id)
        observation = crash_by_id.get(row.observation_id)
        execution = execution_by_id.get(row.execution_id)
        publication = publication_by_id.get(row.publication_id)
        job = job_by_id.get(row.job_id)
        orphan = (
            containment_row is None
            or observation is None
            or execution is None
            or publication is None
        )
        valid = True
        try:
            if orphan:
                raise registry.StudioResourceUncertain(
                    "Studio crash reconciliation lost retained raw evidence"
                )
            assert containment_row is not None
            assert observation is not None
            assert execution is not None
            assert publication is not None
            validate_reconciliation(
                row,
                containment_row=containment_row,
                observation=observation,
                execution=execution,
                publication=publication,
            )
            if row.execution_id in terminal_conflicts:
                raise registry.StudioResourceUncertain(
                    "Studio crash reconciliation conflicts with terminal evidence"
                )
            if (
                job is not None
                and job.organization_id
                != observation.proof["organization_id"]
            ):
                raise registry.StudioResourceUncertain(
                    "Studio crash reconciliation tenant differs"
                )
        except (
            registry.StudioResourceUncertain,
            containment.StudioCrashContainmentUnavailable,
            KeyError,
            TypeError,
            ValueError,
            AssertionError,
        ):
            valid = False

        receipt_jobs.add(row.job_id)
        invalid += int(not valid)
        if valid:
            accepted_executions.add(row.execution_id)
            accepted_publications.add(row.publication_id)
            accepted_observations.add(row.observation_id)
            accepted_containments.add(row.containment_id)
        observations.append(
            {
                "reconciliation_id": row.id,
                "containment_id": row.containment_id,
                "execution_id": row.execution_id,
                "publication_id": row.publication_id,
                "observation_id": row.observation_id,
                "job_id": row.job_id,
                "admitted_generation": row.admitted_generation,
                "valid_reconciliation": valid,
                "orphan_raw_evidence": orphan,
                "terminal_state": (
                    row.proof.get("terminal_state")
                    if isinstance(row.proof, dict)
                    else None
                ),
                "quarantine_retained": (
                    valid and row.proof.get("quarantine_retained") is True
                ),
                "blocker_cleared": valid,
                "retry_authorized": False,
                "cleanup_authorized": False,
                "settlement_authorized": False,
                "quarantine_deletion_permitted": False,
                "final_deletion_permitted": False,
                "requires_reconciliation": not valid,
            }
        )

    return (
        accepted_executions,
        accepted_publications,
        accepted_observations,
        accepted_containments,
        observations,
        receipt_jobs,
        invalid,
    )
