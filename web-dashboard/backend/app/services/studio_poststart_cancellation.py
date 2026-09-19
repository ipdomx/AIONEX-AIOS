"""Settle only cancellation proven after Studio payload execution started.

This path is invoked by the live worker after its execution-end evidence and job
"reconciliation required" state are committed. It never guesses from age, lease
expiry or queue emptiness. Every registered thread must be durably joined with a
successful outcome. A complete publication may be retained, but partial/failed or
unknown publication stays unresolved. Raw execution/publication evidence is never
rewritten or deleted.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditEvent,
    StudioCrashObservation,
    StudioAsset,
    StudioAssetRevision,
    StudioExecution,
    StudioJob,
    StudioPoststartCancellation,
    StudioPrestartCancellation,
    StudioPublication,
    StudioSettlement,
)
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry
from app.services.host_maintenance_admission import SessionFactory
from app.services.studio_execution_guard import GUARD_KEY, execution_guard
from app.services.studio_result_binding import evidence_digest
from app.services.studio_success_settlement import _execution_evidence

SCHEMA = "aionex.studio-poststart-cancellation.v1"
MODES = frozenset({
    "started_no_payload_resource",
    "joined_build_before_storage",
    "complete_publication_retained",
})
_PROOF_KEYS = frozenset({
    "schema",
    "organization_id",
    "mode",
    "execution_evidence_sha256",
    "publication_evidence_sha256",
    "guard_sha256",
    "cancel_requested_at",
    "payload_resources_stopped",
    "staging_cleanup_verified",
    "accepted_archive_retained",
    "filesystem_cleanup_claimed",
    "full_host_closure",
})


def _publication_digest(row: StudioPublication) -> str:
    return evidence_digest({
        "plan": deepcopy(row.plan),
        "events": deepcopy(row.events),
    })


def _qualify_resources(
    execution: StudioExecution,
    publication: StudioPublication | None,
) -> tuple[registry.StudioOwnership, str, bool, str | None] | None:
    """Return safe terminal classification, or None for unresolved evidence."""
    try:
        owner = registry._owner(execution)
        if (
            execution.state != "unresolved"
            or execution.phase not in {"executing", "returned"}
            or execution.unresolved_reason not in {
                "execution_interrupted",
                "filesystem_settlement_pending",
            }
        ):
            return None
        resources = registry._resources(execution)
    except (registry.StudioResourceUncertain, ValueError, TypeError, KeyError):
        return None

    if any(
        item["state"] != "joined" or item["outcome"] != "success"
        for item in resources.values()
    ):
        return None

    operations = {
        item["operation"]: (identifier, item)
        for identifier, item in resources.items()
    }
    if not operations:
        if publication is not None:
            return None
        return owner, "started_no_payload_resource", False, None

    if set(operations) == {"build_archive"}:
        if publication is not None:
            return None
        _, build = operations["build_archive"]
        if registry._stamp(build["registered_at"]) < execution.started_at:
            return None
        return owner, "joined_build_before_storage", False, None

    if set(operations) != {"build_archive", "store_artifact"}:
        return None
    if publication is None:
        return None

    build_id, build = operations["build_archive"]
    store_id, store = operations["store_artifact"]
    try:
        journal.validate_row(publication)
        build_joined = registry._stamp(build["joined_at"])
        store_registered = registry._stamp(store["registered_at"])
        store_joined = registry._stamp(store["joined_at"])
    except (registry.StudioResourceUncertain, ValueError, TypeError, KeyError):
        return None

    if (
        build_id == store_id
        or publication.state != "observed"
        or publication.execution_id != owner.execution_id
        or publication.job_id != owner.job_id
        or publication.worker_incarnation != owner.worker_incarnation
        or publication.ownership_nonce != owner.nonce
        or publication.admitted_generation != owner.admitted_generation
        or publication.thread_resource_id != store_id
        or registry._stamp(build["registered_at"]) < execution.started_at
        or store_registered < build_joined
        or publication.created_at < store_registered
        or publication.updated_at > store_joined
        or (
            execution.phase == "returned"
            and (
                execution.returned_at is None
                or store_joined > execution.returned_at
            )
        )
    ):
        return None

    # validate_row(state="observed") proves the full journal ended at "complete":
    # the private staging name was removed and the retained archive had one link.
    return (
        owner,
        "complete_publication_retained",
        True,
        _publication_digest(publication),
    )


def _business_is_cancelled(
    job: StudioJob,
    owner: registry.StudioOwnership,
) -> dict[str, Any] | None:
    guard = execution_guard(job)
    if (
        job.id != owner.job_id
        or job.status != "cancel_requested"
        or type(job.attempts) is not int
        or job.attempts != 1
        or job.progress != 10
        or not registry._aware(job.started_at)
        or not registry._aware(job.cancelled_at)
        or job.completed_at is not None
        or job.lease_token != owner.nonce
        or job.error_code != "STUDIO_RECONCILIATION_REQUIRED"
        or not isinstance(job.error_message, str)
        or not job.error_message
        or job.safety_status != "pending"
        or job.safety_findings != []
        or job.provider_mode != "provider_neutral"
        or job.provider is not None
        or job.model is not None
        or not isinstance(job.result_metadata, dict)
        or set(job.result_metadata) != {GUARD_KEY}
        or guard is None
        or guard["phase"] != "unresolved"
        or guard["worker_incarnation"] != owner.worker_incarnation
        or guard["admitted_generation"] != owner.admitted_generation
    ):
        return None
    assert isinstance(job.cancelled_at, datetime)
    return {
        "organization_id": job.organization_id,
        "cancel_requested_at": job.cancelled_at.isoformat(),
        "guard_sha256": evidence_digest(guard),
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


async def settle_poststart_cancellation(
    *,
    session_factory: SessionFactory,
    job_id: str,
    nonce: str,
    worker_incarnation: str,
) -> bool:
    """Persist one cancellation receipt after the live worker stopped its work.

    False means evidence is not the bounded safe case; the original unresolved
    state remains. Database errors propagate. This function performs no filesystem
    operation and no automatic retry or post-crash adoption.
    """
    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            raise registry.StudioResourceUncertain(
                "Studio post-start cancellation requires PostgreSQL"
            )
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
        with session.no_autoflush:
            job = await session.scalar(
                select(StudioJob)
                .where(StudioJob.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if job is None or job.status != "cancel_requested":
                return False

            owner = await registry.find_owner(
                session,
                job_id=job_id,
                nonce=nonce,
                worker_incarnation=worker_incarnation,
            )
            if owner is None:
                return False
            execution = await registry._locked(session, owner)

            if await session.scalar(
                select(StudioSettlement.id)
                .where(StudioSettlement.execution_id == owner.execution_id)
            ) is not None:
                return False
            if await session.scalar(
                select(StudioPrestartCancellation.id)
                .where(
                    StudioPrestartCancellation.execution_id == owner.execution_id
                )
            ) is not None:
                return False
            if await session.scalar(
                select(StudioPoststartCancellation.id)
                .where(
                    StudioPoststartCancellation.execution_id
                    == owner.execution_id
                )
            ) is not None:
                return False
            if await session.scalar(
                select(StudioCrashObservation.id)
                .where(StudioCrashObservation.execution_id == owner.execution_id)
            ) is not None:
                return False

            publication = await session.scalar(
                select(StudioPublication)
                .where(StudioPublication.execution_id == owner.execution_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )

            qualification = _qualify_resources(execution, publication)
            business = _business_is_cancelled(job, owner)
            if qualification is None or business is None:
                return False
            checked_owner, mode, archive_retained, publication_sha = qualification
            if checked_owner != owner:
                return False

            # Business output rows would mean this is not the bounded
            # "cancelled before result acceptance" case.
            if await session.scalar(
                select(StudioAsset.id).where(StudioAsset.job_id == job_id).limit(1)
            ) is not None:
                return False
            if await session.scalar(
                select(StudioAssetRevision.id)
                .where(StudioAssetRevision.job_id == job_id)
                .limit(1)
            ) is not None:
                return False

            stamp = await registry._now(session)
            cancelled_at = registry._stamp(business["cancel_requested_at"])
            if not (
                execution.started_at
                <= cancelled_at
                <= execution.updated_at
                <= stamp
            ):
                return False

            receipt = StudioPoststartCancellation(
                id=str(uuid4()),
                execution_id=owner.execution_id,
                publication_id=publication.id if publication is not None else None,
                job_id=job_id,
                worker_incarnation=owner.worker_incarnation,
                admitted_generation=owner.admitted_generation,
                created_at=stamp,
                proof={
                    "schema": SCHEMA,
                    "organization_id": business["organization_id"],
                    "mode": mode,
                    "execution_evidence_sha256": evidence_digest(
                        _execution_evidence(execution)
                    ),
                    "publication_evidence_sha256": publication_sha,
                    "guard_sha256": business["guard_sha256"],
                    "cancel_requested_at": business["cancel_requested_at"],
                    "payload_resources_stopped": True,
                    "staging_cleanup_verified": True,
                    "accepted_archive_retained": archive_retained,
                    "filesystem_cleanup_claimed": False,
                    "full_host_closure": False,
                },
            )
            receipt.proof_sha256 = evidence_digest(receipt.proof)
            validate_receipt(receipt, execution, publication)

        # Preserve the raw guard and execution ledger. The receipt, terminal
        # business state and audit commit atomically.
        job.status = "cancelled"
        job.progress = 100
        job.completed_at = stamp
        job.lease_token = None
        job.error_code = None
        job.error_message = None
        job.version += 1
        session.add(receipt)
        session.add(AuditEvent(
            organization_id=job.organization_id,
            user_id=None,
            action="studio.job.cancel_settled_after_start",
            resource_type="studio_job",
            resource_id=job.id,
            details={
                "mode": mode,
                "archive_retained": archive_retained,
                "cleanup_verified": False,
            },
        ))
        await session.commit()
        return True


def validate_receipt(
    receipt: StudioPoststartCancellation,
    execution: StudioExecution,
    publication: StudioPublication | None,
) -> None:
    proof = receipt.proof
    qualification = _qualify_resources(execution, publication)
    if qualification is None:
        raise registry.StudioResourceUncertain(
            "Studio post-start cancellation proof is invalid"
        )
    owner, mode, archive_retained, publication_sha = qualification
    valid = (
        all(registry._uuid(value) for value in (
            receipt.id,
            receipt.execution_id,
            receipt.job_id,
            receipt.worker_incarnation,
        ))
        and receipt.execution_id == owner.execution_id
        and receipt.job_id == owner.job_id
        and receipt.worker_incarnation == owner.worker_incarnation
        and type(receipt.admitted_generation) is int
        and receipt.admitted_generation == owner.admitted_generation
        and registry._aware(receipt.created_at)
        and receipt.created_at >= execution.updated_at
        and (
            (publication is None and receipt.publication_id is None)
            or (
                publication is not None
                and receipt.publication_id == publication.id
            )
        )
        and isinstance(proof, dict)
        and set(proof) == _PROOF_KEYS
        and proof["schema"] == SCHEMA
        and registry._uuid(proof["organization_id"])
        and proof["mode"] in MODES
        and proof["mode"] == mode
        and proof["execution_evidence_sha256"]
        == evidence_digest(_execution_evidence(execution))
        and proof["publication_evidence_sha256"] == publication_sha
        and isinstance(proof["guard_sha256"], str)
        and len(proof["guard_sha256"]) == 64
        and registry._stamp(proof["cancel_requested_at"])
        >= execution.started_at
        and registry._stamp(proof["cancel_requested_at"])
        <= receipt.created_at
        and proof["payload_resources_stopped"] is True
        and proof["staging_cleanup_verified"] is True
        and proof["accepted_archive_retained"] is archive_retained
        and proof["filesystem_cleanup_claimed"] is False
        and proof["full_host_closure"] is False
        and evidence_digest(proof) == receipt.proof_sha256
    )
    if not valid:
        raise registry.StudioResourceUncertain(
            "Studio post-start cancellation proof is invalid"
        )


async def snapshot_poststart_cancellations(
    session: AsyncSession,
    executions: list[StudioExecution],
    publications: list[StudioPublication],
    jobs: list[StudioJob],
) -> tuple[
    set[str],
    set[str],
    list[dict[str, Any]],
    set[str],
]:
    """Validate retained receipts without mutating or rereading filesystem paths."""
    receipts = list(
        (
            await session.scalars(
                select(StudioPoststartCancellation)
                .order_by(StudioPoststartCancellation.id)
            )
        ).all()
    )
    execution_by_id = {row.id: row for row in executions}
    publication_by_execution = {row.execution_id: row for row in publications}
    jobs_by_id = {row.id: row for row in jobs}
    accepted: set[str] = set()
    retained_publications: set[str] = set()
    receipt_jobs: set[str] = set()
    observations: list[dict[str, Any]] = []

    for receipt in receipts:
        execution = execution_by_id.get(receipt.execution_id)
        publication = publication_by_execution.get(receipt.execution_id)
        if (
            receipt.publication_id is not None
            and (publication is None or publication.id != receipt.publication_id)
        ):
            publication = None
        valid = False
        if execution is not None:
            try:
                validate_receipt(receipt, execution, publication)
                job = jobs_by_id.get(receipt.job_id)
                if job is not None:
                    guard = execution_guard(job)
                    if (
                        job.organization_id != receipt.proof["organization_id"]
                        or job.status != "cancelled"
                        or job.attempts != 1
                        or job.progress != 100
                        or job.lease_token is not None
                        or job.error_code is not None
                        or job.error_message is not None
                        or job.cancelled_at
                        != registry._stamp(receipt.proof["cancel_requested_at"])
                        or job.completed_at != receipt.created_at
                        or guard is None
                        or guard["phase"] != "unresolved"
                        or evidence_digest(guard)
                        != receipt.proof["guard_sha256"]
                    ):
                        raise registry.StudioResourceUncertain(
                            "Studio post-start business state differs"
                        )
            except (
                registry.StudioResourceUncertain,
                ValueError,
                TypeError,
                KeyError,
            ):
                valid = False
            else:
                valid = True

        receipt_jobs.add(receipt.job_id)
        if valid:
            accepted.add(receipt.execution_id)
            if receipt.publication_id is not None:
                retained_publications.add(receipt.publication_id)
        observations.append({
            "receipt_id": receipt.id,
            "execution_id": receipt.execution_id,
            "publication_id": receipt.publication_id,
            "job_id": receipt.job_id,
            "admitted_generation": receipt.admitted_generation,
            "cancelled_after_execution_start": valid,
            "accepted_archive_retained": (
                valid and receipt.publication_id is not None
            ),
            "requires_reconciliation": not valid,
            "filesystem_cleanup_claimed": False,
        })

    return accepted, retained_publications, observations, receipt_jobs
