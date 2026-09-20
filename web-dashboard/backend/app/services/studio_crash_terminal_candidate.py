"""Export a bounded Studio post-crash terminal candidate without terminalizing it.

FR-06D8C4B6B1 consumes one valid B6A crash-containment row plus its retained
raw execution/publication/crash evidence. It binds that historical containment
to the *current* closed Studio maintenance authority so a later host-side stage
can revalidate the retained quarantine under current runtime conditions.

This module is database-only and read-only. It never touches the Studio
filesystem, clears blockers, retries or settles work, opens/closes admission,
deletes quarantine/final names, or authorizes terminalization.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select, text

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
from app.services import studio_crash_containment as containment
from app.services import studio_resource_registry as registry
from app.services.host_maintenance_admission import (
    SessionFactory,
    read_admission_snapshot,
)
from app.services.studio_result_binding import evidence_digest

SCHEMA = "aionex.studio-crash-terminal-candidate.v1"


class StudioCrashTerminalCandidateUnavailable(RuntimeError):
    """Durable evidence is not safe enough to export a terminal candidate."""


def _authority_payload(snapshot) -> dict[str, Any]:
    if (
        snapshot.is_open
        or snapshot.operation_id is None
        or snapshot.changed_at is None
        or snapshot.full_host_closure is not False
    ):
        raise StudioCrashTerminalCandidateUnavailable(
            "terminal candidate requires closed maintenance authority"
        )
    return {
        "schema_version": snapshot.schema_version,
        "scope": snapshot.scope,
        "generation": snapshot.generation,
        "status": snapshot.status,
        "enabled": snapshot.enabled,
        "operation_id": snapshot.operation_id,
        "reason": snapshot.reason,
        "changed_at": snapshot.changed_at.isoformat(),
        "full_host_closure": False,
    }


async def _terminal_conflict(session, execution_id: str) -> bool:
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


async def export_terminal_candidate(
    *,
    containment_id: str,
    session_factory: SessionFactory = SessionLocal,
) -> dict[str, Any]:
    """Export deterministic current-authority-bound reconciliation input."""
    if not registry._uuid(containment_id):
        raise ValueError("containment_id must be a canonical UUID")

    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            raise StudioCrashTerminalCandidateUnavailable(
                "Studio crash terminal candidate requires PostgreSQL"
            )
        await session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )

        row = await session.scalar(
            select(StudioCrashContainment).where(
                StudioCrashContainment.id == containment_id
            )
        )
        if row is None:
            raise StudioCrashTerminalCandidateUnavailable(
                "Studio crash containment is missing"
            )

        observation = await session.scalar(
            select(StudioCrashObservation).where(
                StudioCrashObservation.id == row.observation_id
            )
        )
        execution = await session.scalar(
            select(StudioExecution).where(
                StudioExecution.id == row.execution_id
            )
        )
        publication = await session.scalar(
            select(StudioPublication).where(
                StudioPublication.id == row.publication_id
            )
        )
        if observation is None or execution is None or publication is None:
            raise StudioCrashTerminalCandidateUnavailable(
                "Studio crash containment lost raw evidence"
            )

        try:
            containment.validate_containment(
                row,
                observation=observation,
                execution=execution,
                publication=publication,
            )
        except (
            containment.StudioCrashContainmentUnavailable,
            registry.StudioResourceUncertain,
        ) as exc:
            raise StudioCrashTerminalCandidateUnavailable(
                "Studio crash containment is invalid"
            ) from exc

        if await _terminal_conflict(session, execution.id):
            raise StudioCrashTerminalCandidateUnavailable(
                "terminal evidence conflicts with crash containment"
            )

        job = await session.scalar(
            select(StudioJob).where(StudioJob.id == row.job_id)
        )
        if (
            job is not None
            and job.organization_id != observation.proof["organization_id"]
        ):
            raise StudioCrashTerminalCandidateUnavailable(
                "Studio crash containment tenant differs"
            )

        current = await read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
        authority = _authority_payload(current)
        original_generation = row.proof["maintenance_generation"]
        if (
            type(original_generation) is not int
            or authority["generation"] < original_generation
        ):
            raise StudioCrashTerminalCandidateUnavailable(
                "current maintenance generation predates containment"
            )

        candidate = {
            "schema": SCHEMA,
            "containment_id": row.id,
            "containment_proof_sha256": row.proof_sha256,
            "observation_id": row.observation_id,
            "observation_proof_sha256": row.proof[
                "observation_proof_sha256"
            ],
            "execution_id": row.execution_id,
            "publication_id": row.publication_id,
            "job_id": row.job_id,
            "organization_id": observation.proof["organization_id"],
            "worker_incarnation": row.worker_incarnation,
            "admitted_generation": row.admitted_generation,
            "containment_operation_id": row.proof[
                "maintenance_operation_id"
            ],
            "containment_generation": original_generation,
            "containment_boot_id": row.proof["boot_id"],
            "cleanup_candidate_sha256": row.proof["candidate_sha256"],
            "process_scan_receipt_sha256": row.proof[
                "process_scan_receipt_sha256"
            ],
            "staging_quarantine_receipt_sha256": row.proof[
                "staging_quarantine_receipt_sha256"
            ],
            "layout": row.proof["layout"],
            "quarantine_name": row.proof["quarantine_name"],
            "retained_identity": deepcopy(row.proof["retained_identity"]),
            "reconciliation_authority": authority,
            "reconciliation_authority_sha256": evidence_digest(authority),
            "host_revalidation_required": True,
            "quarantine_revalidation_required": True,
            "terminalization_authorized": False,
            "blocker_cleared": False,
            "retry_authorized": False,
            "filesystem_cleanup_claimed": False,
            "cleanup_authorized": False,
            "settlement_authorized": False,
            "quarantine_deletion_permitted": False,
            "final_deletion_permitted": False,
            "full_host_closure": False,
        }
        candidate["candidate_sha256"] = evidence_digest(candidate)
        return candidate
