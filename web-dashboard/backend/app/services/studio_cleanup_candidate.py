"""Export a private Studio cleanup candidate from retained durable evidence.

This module is database-only and read-only. It does not inspect or mutate the
filesystem, settle an execution, delete evidence, authorize cleanup, or infer
process drain. A later host-side stage must combine this candidate with accepted
writer/runtime drain receipts and an exact process-reference scan.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select, text

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import (
    StudioCrashObservation,
    StudioExecution,
    StudioPoststartCancellation,
    StudioPrestartCancellation,
    StudioPublication,
    StudioSettlement,
)
from app.services import studio_crash_observation as crash
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry
from app.services.host_maintenance_admission import (
    SessionFactory,
    read_admission_snapshot,
)
from app.services.studio_result_binding import evidence_digest
from app.services.studio_success_settlement import _execution_evidence

SCHEMA = "aionex.studio-cleanup-candidate.v1"
_SAFE_LAYOUTS = frozenset({
    "no_archive_entry",
    "owned_staging_present",
    "owned_final_present",
    "owned_staging_and_final_hardlinks",
})


class StudioCleanupCandidateUnavailable(RuntimeError):
    """Durable evidence cannot safely describe one cleanup candidate."""


def _publication_digest(row: StudioPublication) -> str:
    return evidence_digest({
        "plan": deepcopy(row.plan),
        "events": deepcopy(row.events),
    })


def _relative_plan(publication: StudioPublication, organization_id: str) -> tuple[list[str], str, str]:
    journal.validate_row(publication)
    plan = publication.plan
    configured = str(Path(os.path.abspath(settings.STUDIO_ASSET_ROOT)))
    if plan["root"] != configured:
        raise StudioCleanupCandidateUnavailable(
            "Studio publication root differs from configured storage root"
        )
    root_parts = list(PurePosixPath(configured).parts[1:])
    components = plan["components"]
    if (
        components[: len(root_parts)] != root_parts
        or len(components) != len(root_parts) + 3
    ):
        raise StudioCleanupCandidateUnavailable(
            "Studio publication path is outside the configured root"
        )
    relative = components[len(root_parts) :]
    if relative[0] != organization_id:
        raise StudioCleanupCandidateUnavailable(
            "Studio publication tenant path differs"
        )
    return relative, plan["staging_name"], plan["filename"]


def _candidate(
    *,
    observation: StudioCrashObservation,
    execution: StudioExecution,
    publication: StudioPublication,
    authority_operation_id: str,
    authority_generation: int,
) -> dict[str, Any]:
    crash.validate_observation(observation)
    owner = registry._owner(execution)
    proof = observation.proof
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
        or proof["maintenance_operation_id"] != authority_operation_id
        or proof["maintenance_generation"] != authority_generation
        or proof["execution_evidence_sha256"]
        != evidence_digest(_execution_evidence(execution))
    ):
        raise StudioCleanupCandidateUnavailable(
            "Studio cleanup candidate durable ownership differs"
        )
    publication_sha = _publication_digest(publication)
    if proof["publication_evidence_sha256"] != publication_sha:
        raise StudioCleanupCandidateUnavailable(
            "Studio publication changed after crash observation"
        )
    layout = proof["layout"]
    if (
        layout not in _SAFE_LAYOUTS
        or proof["directory_chain_verified"] is not True
        or proof["process_drain_verified"] is not False
        or proof["cleanup_authorized"] is not False
        or proof["filesystem_mutation_performed"] is not False
        or proof["full_host_closure"] is not False
    ):
        raise StudioCleanupCandidateUnavailable(
            "Studio crash observation is not a bounded cleanup layout"
        )

    relative, staging_name, final_name = _relative_plan(
        publication, proof["organization_id"]
    )
    action = (
        "remove_owned_staging"
        if layout in {
            "owned_staging_present",
            "owned_staging_and_final_hardlinks",
        }
        else "no_staging_mutation_required"
    )
    candidate = {
        "schema": SCHEMA,
        "observation_id": observation.id,
        "observation_proof_sha256": observation.proof_sha256,
        "execution_id": observation.execution_id,
        "publication_id": publication.id,
        "job_id": observation.job_id,
        "organization_id": proof["organization_id"],
        "maintenance_operation_id": authority_operation_id,
        "maintenance_generation": authority_generation,
        "layout": layout,
        "publication_phase": proof["publication_phase"],
        "publication_evidence_sha256": publication_sha,
        "relative_components": relative,
        "staging_name": staging_name,
        "final_name": final_name,
        "staging": deepcopy(proof["staging"]),
        "final": deepcopy(proof["final"]),
        "action": action,
        "process_reference_scan_required": action == "remove_owned_staging",
        "final_deletion_permitted": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    }
    candidate["candidate_sha256"] = evidence_digest(candidate)
    return candidate


async def export_cleanup_candidate(
    *,
    observation_id: str,
    session_factory: SessionFactory = SessionLocal,
) -> dict[str, Any]:
    """Export one immutable candidate under the current closed authority."""
    if not registry._uuid(observation_id):
        raise ValueError("observation_id must be a canonical UUID")
    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            raise StudioCleanupCandidateUnavailable(
                "Studio cleanup candidate requires PostgreSQL"
            )
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        authority = await read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
        if authority.is_open or authority.operation_id is None:
            raise StudioCleanupCandidateUnavailable(
                "Studio cleanup candidate requires closed maintenance"
            )
        observation = await session.scalar(
            select(StudioCrashObservation).where(
                StudioCrashObservation.id == observation_id
            )
        )
        if observation is None:
            raise StudioCleanupCandidateUnavailable(
                "Studio crash observation is missing"
            )
        execution = await session.scalar(
            select(StudioExecution).where(
                StudioExecution.id == observation.execution_id
            )
        )
        if execution is None:
            raise StudioCleanupCandidateUnavailable(
                "Studio execution evidence is missing"
            )
        if observation.publication_id is None:
            raise StudioCleanupCandidateUnavailable(
                "Studio observation has no publication cleanup candidate"
            )
        publication = await session.scalar(
            select(StudioPublication).where(
                StudioPublication.id == observation.publication_id
            )
        )
        if publication is None:
            raise StudioCleanupCandidateUnavailable(
                "Studio publication evidence is missing"
            )
        terminal = [
            await session.scalar(
                select(StudioSettlement.id).where(
                    StudioSettlement.execution_id == observation.execution_id
                )
            ),
            await session.scalar(
                select(StudioPrestartCancellation.id).where(
                    StudioPrestartCancellation.execution_id
                    == observation.execution_id
                )
            ),
            await session.scalar(
                select(StudioPoststartCancellation.id).where(
                    StudioPoststartCancellation.execution_id
                    == observation.execution_id
                )
            ),
        ]
        if any(value is not None for value in terminal):
            raise StudioCleanupCandidateUnavailable(
                "Studio execution has conflicting terminal evidence"
            )
        return _candidate(
            observation=observation,
            execution=execution,
            publication=publication,
            authority_operation_id=authority.operation_id,
            authority_generation=authority.generation,
        )


async def _async_main(observation_id: str) -> int:
    try:
        candidate = await export_cleanup_candidate(observation_id=observation_id)
    except (ValueError, StudioCleanupCandidateUnavailable) as exc:
        print(
            "FR06D8C4B3_STUDIO_CLEANUP_CANDIDATE_BLOCKED:"
            f" {type(exc).__name__}"
        )
        return 2
    print(json.dumps(candidate, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation-id", required=True)
    args = parser.parse_args()
    return asyncio.run(_async_main(args.observation_id))


if __name__ == "__main__":
    raise SystemExit(main())
