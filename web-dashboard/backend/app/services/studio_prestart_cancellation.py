"""Cancel a proven claimed-but-never-started attempt, not interrupted work.

The API's tenant-scoped job lock is acquired again here before the execution
lock. The same locks fence the worker's committed one-shot start. Neither age,
empty queues nor missing history establishes eligibility: an exact active claim
with untouched provenance is required. There is no filesystem operation, retry,
backfill or cleanup. The receipt and cancelled job commit in the caller's TX.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    StudioCrashObservation, StudioExecution, StudioJob, StudioPrestartCancellation,
    StudioPublication, StudioSettlement,
)
from app.services import studio_resource_registry as registry
from app.services.studio_execution_guard import GUARD_KEY, execution_guard
from app.services.studio_result_binding import evidence_digest
from app.services.studio_success_settlement import _execution_evidence

SCHEMA = "aionex.studio-prestart-cancellation.v1"
_PROOF_KEYS = frozenset({
    "schema", "organization_id", "execution_evidence_sha256", "guard_sha256",
    "cancelled_at", "execution_start_fenced", "payload_resources_started",
    "filesystem_cleanup_claimed", "full_host_closure",
})


def _untouched_claim(row: StudioExecution) -> registry.StudioOwnership:
    owner = registry._owner(row)
    if (
        row.state != "active" or row.phase != "claimed" or row.resources != {}
        or row.returned_at is not None or row.unresolved_reason is not None
        or row.started_at != row.updated_at
    ):
        raise registry.StudioResourceUncertain("Studio claim is not proven unstarted")
    return owner


def _eligible(job: StudioJob, row: StudioExecution) -> bool:
    try:
        owner = _untouched_claim(row)
    except (registry.StudioResourceUncertain, ValueError, TypeError, KeyError):
        return False
    guard = execution_guard(job)
    return (
        job.id == owner.job_id and job.status == "running"
        and type(job.attempts) is int and job.attempts == 1 and job.progress == 10
        and type(job.max_attempts) is int and job.max_attempts >= 1
        and registry._aware(job.started_at)
        and job.completed_at is None and job.cancelled_at is None
        and job.lease_token == owner.nonce
        and job.error_code is None and job.error_message is None
        and job.safety_status == "pending" and job.safety_findings == []
        and job.provider_mode == "provider_neutral" and job.provider is None and job.model is None
        and isinstance(job.result_metadata, dict) and set(job.result_metadata) == {GUARD_KEY}
        and guard is not None and guard["phase"] == "claimed"
        and guard["worker_incarnation"] == owner.worker_incarnation
        and guard["admitted_generation"] == owner.admitted_generation
    )


async def cancel_claimed_before_start(session: AsyncSession, job: StudioJob) -> bool:
    """Return false for anything outside the proven pre-start case.

    Requires the caller's existing transaction; no commit, flush or rollback.
    Driver failures propagate for the API's sanitized fail-closed handling.
    The original execution ledger is never mutated or removed.
    """
    if session.get_bind().dialect.name != "postgresql" or not session.in_transaction():
        raise registry.StudioResourceUncertain("Studio pre-start cancellation requires PostgreSQL")
    with session.no_autoflush:
        locked_job = await session.scalar(select(StudioJob).where(
            StudioJob.id == job.id, StudioJob.organization_id == job.organization_id,
        ).with_for_update().execution_options(populate_existing=True))
        if locked_job is None:
            return False
        row = await session.scalar(select(StudioExecution).where(
            StudioExecution.job_id == locked_job.id,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None or not _eligible(locked_job, row):
            return False
        conflicting = await session.scalar(select(or_(
            select(StudioPublication.id).where(or_(
                StudioPublication.job_id == locked_job.id,
                StudioPublication.execution_id == row.id,
            )).exists(),
            select(StudioSettlement.id).where(or_(
                StudioSettlement.job_id == locked_job.id,
                StudioSettlement.execution_id == row.id,
            )).exists(),
            select(StudioPrestartCancellation.id).where(or_(
                StudioPrestartCancellation.job_id == locked_job.id,
                StudioPrestartCancellation.execution_id == row.id,
            )).exists(),
            select(StudioCrashObservation.id).where(or_(
                StudioCrashObservation.job_id == locked_job.id,
                StudioCrashObservation.execution_id == row.id,
            )).exists(),
        )))
        if type(conflicting) is not bool:
            raise registry.StudioResourceUncertain("Studio conflicting evidence is unavailable")
        if conflicting:
            return False
        stamp = await registry._now(session)
        if row.started_at > stamp or not isinstance(locked_job.started_at, datetime) or locked_job.started_at > stamp:
            return False
        guard = execution_guard(locked_job)
        assert guard is not None
        receipt = StudioPrestartCancellation(
            id=str(uuid4()), job_id=locked_job.id, execution_id=row.id,
            worker_incarnation=row.worker_incarnation,
            admitted_generation=row.admitted_generation, created_at=stamp,
            proof={
                "schema": SCHEMA, "organization_id": locked_job.organization_id,
                "execution_evidence_sha256": evidence_digest(_execution_evidence(row)),
                "guard_sha256": evidence_digest(guard), "cancelled_at": stamp.isoformat(),
                "execution_start_fenced": True, "payload_resources_started": False,
                "filesystem_cleanup_claimed": False, "full_host_closure": False,
            },
        )
        receipt.proof_sha256 = evidence_digest(receipt.proof)
        validate_receipt(receipt, row)
    locked_job.status = "cancelled"
    locked_job.progress = 100
    locked_job.cancelled_at = stamp
    locked_job.completed_at = stamp
    locked_job.lease_token = None
    session.add(receipt)
    return True


def validate_receipt(receipt: StudioPrestartCancellation, execution: StudioExecution) -> None:
    owner = _untouched_claim(execution)
    proof = receipt.proof
    valid = (
        all(registry._uuid(value) for value in (
            receipt.id, receipt.job_id, receipt.execution_id, receipt.worker_incarnation,
        ))
        and receipt.job_id == owner.job_id and receipt.execution_id == owner.execution_id
        and receipt.worker_incarnation == owner.worker_incarnation
        and type(receipt.admitted_generation) is int
        and receipt.admitted_generation == owner.admitted_generation
        and registry._aware(receipt.created_at) and execution.started_at <= receipt.created_at
        and isinstance(proof, dict) and set(proof) == _PROOF_KEYS
        and proof["schema"] == SCHEMA and registry._uuid(proof["organization_id"])
        and proof["execution_start_fenced"] is True and proof["payload_resources_started"] is False
        and proof["filesystem_cleanup_claimed"] is False and proof["full_host_closure"] is False
        and evidence_digest(proof) == receipt.proof_sha256
        and evidence_digest(_execution_evidence(execution)) == proof["execution_evidence_sha256"]
        and registry._stamp(proof["cancelled_at"]) == receipt.created_at
        and proof["guard_sha256"] == evidence_digest({
            "protocol_version": 1, "phase": "claimed",
            "worker_incarnation": owner.worker_incarnation,
            "admitted_generation": owner.admitted_generation, "cleanup_verified": False,
        })
    )
    if not valid:
        raise registry.StudioResourceUncertain("Studio pre-start cancellation proof is invalid")


async def snapshot_prestart_cancellations(
    session: AsyncSession, executions: list[StudioExecution], publications: list[StudioPublication],
    jobs: list[StudioJob], success_receipts: list[dict[str, Any]],
) -> tuple[set[str], list[dict[str, Any]], set[str]]:
    """Read-only retained proof; orphan or changed evidence remains a blocker."""
    receipts = list((await session.scalars(select(StudioPrestartCancellation).order_by(StudioPrestartCancellation.id))).all())
    by_execution = {row.id: row for row in executions}
    by_job = {row.id: row for row in jobs}
    conflicting_jobs = {row.job_id for row in publications} | {row["job_id"] for row in success_receipts}
    conflicting_executions = {row.execution_id for row in publications} | {row["execution_id"] for row in success_receipts}
    accepted: set[str] = set()
    observations: list[dict[str, Any]] = []
    receipt_jobs: set[str] = set()
    for receipt in receipts:
        valid = False
        execution = by_execution.get(receipt.execution_id)
        if execution is not None:
            try:
                validate_receipt(receipt, execution)
                if receipt.job_id in conflicting_jobs or receipt.execution_id in conflicting_executions:
                    raise registry.StudioResourceUncertain("Studio pre-start evidence conflicts")
                job = by_job.get(receipt.job_id)
                if job is not None and (
                    job.organization_id != receipt.proof["organization_id"]
                    or job.status != "cancelled" or job.attempts != 1 or job.progress != 100
                    or job.lease_token is not None
                    or job.cancelled_at != receipt.created_at or job.completed_at != receipt.created_at
                    or not isinstance(job.result_metadata, dict) or set(job.result_metadata) != {GUARD_KEY}
                    or evidence_digest(execution_guard(job)) != receipt.proof["guard_sha256"]
                ):
                    raise registry.StudioResourceUncertain("Studio cancellation business state differs")
            except (registry.StudioResourceUncertain, ValueError, TypeError, KeyError):
                valid = False
            else:
                valid = True
        receipt_jobs.add(receipt.job_id)
        if valid:
            accepted.add(receipt.execution_id)
        observations.append({
            "receipt_id": receipt.id, "job_id": receipt.job_id,
            "execution_id": receipt.execution_id, "admitted_generation": receipt.admitted_generation,
            "cancelled_before_execution": valid, "requires_reconciliation": not valid,
            "filesystem_cleanup_claimed": False,
        })
    return accepted, observations, receipt_jobs
