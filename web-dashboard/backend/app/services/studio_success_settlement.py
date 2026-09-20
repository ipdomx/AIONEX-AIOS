"""Retained normal-success settlement, never post-crash reconciliation.

Only the task that received the business commit acknowledgement may attempt this
single-use path. A returned job or a timestamp cannot manufacture that capability.
The original execution/publication ledgers are retained unchanged. The receipt
certifies joined threads and observed staging cleanup, not deletion of the accepted
archive, current on-disk integrity, production coverage or full-host drain.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, NoReturn
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    StudioAsset, StudioAssetRevision, StudioCrashObservation, StudioCrashReconciliation, StudioExecution, StudioJob,
    StudioPublication, StudioSettlement,
)
from app.services.host_maintenance_admission import SessionFactory
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry
from app.services.studio_execution_guard import execution_guard
from app.services.studio_result_binding import BINDING_KEY, BINDING_SCHEMA, evidence_digest

SCHEMA = "aionex.studio-success-settlement.v1"
_BINDING_KEYS = frozenset({
    "schema", "job_id", "execution_id", "publication_id", "thread_resource_id",
    "admitted_generation", "asset_id", "revision_id", "revision_number", "checksum",
    "size_bytes", "storage_path_sha256", "publication_evidence_sha256",
    "file_identity_sha256", "thread_evidence_sha256", "publication_observed_at",
})
_PROOF_KEYS = frozenset({
    "schema", "binding", "execution_evidence_sha256", "business_evidence_sha256",
    "job_completed_at", "staging_cleanup_verified", "accepted_archive_retained",
    "full_host_closure",
})
_ISSUER = object()


def _reject() -> NoReturn:
    raise registry.StudioResourceUncertain("Studio successful settlement is unverified")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _BINDING_KEYS:
        _reject()
    if (
        value["schema"] != BINDING_SCHEMA
        or not all(registry._uuid(value[key]) for key in (
            "job_id", "execution_id", "publication_id", "thread_resource_id", "asset_id", "revision_id",
        ))
        or type(value["admitted_generation"]) is not int or value["admitted_generation"] < 7
        or type(value["revision_number"]) is not int or value["revision_number"] < 1
        or type(value["size_bytes"]) is not int or value["size_bytes"] <= 0
        or not all(_digest(value[key]) for key in (
            "checksum", "storage_path_sha256", "publication_evidence_sha256",
            "file_identity_sha256", "thread_evidence_sha256",
        ))
    ):
        _reject()
    registry._stamp(value["publication_observed_at"])
    return value


@dataclass(slots=True)
class StudioResultAcknowledgement:
    """Process-local single-use capability; never persisted, reconstructed or logged."""
    job_id: str
    worker_incarnation: str
    nonce: str = field(repr=False)
    binding_json: str = field(repr=False)
    task: asyncio.Task[Any] = field(repr=False)
    issuer: object = field(repr=False)
    consumed: bool = False


def acknowledge_business_result(
    *, job_id: str, nonce: str, worker_incarnation: str, binding: dict[str, Any],
) -> StudioResultAcknowledgement:
    """Called only after the worker's successful business commit and session exit."""
    current = asyncio.current_task()
    proof = _binding(binding)
    if (
        current is None or current.cancelling()
        or not all(registry._uuid(item) for item in (job_id, nonce, worker_incarnation))
        or proof["job_id"] != job_id
    ):
        _reject()
    return StudioResultAcknowledgement(
        job_id, worker_incarnation, nonce,
        json.dumps(proof, sort_keys=True, separators=(",", ":"), allow_nan=False),
        current, _ISSUER,
    )


def _execution_evidence(row: StudioExecution) -> dict[str, Any]:
    return {
        "id": row.id, "job_id": row.job_id, "worker_incarnation": row.worker_incarnation,
        "admitted_generation": row.admitted_generation,
        "ownership_nonce_sha256": hashlib.sha256(row.ownership_nonce.encode()).hexdigest(),
        "state": row.state, "phase": row.phase, "resources": deepcopy(row.resources),
        "cleanup_verified": row.cleanup_verified, "started_at": row.started_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "returned_at": row.returned_at.isoformat() if row.returned_at is not None else None,
        "unresolved_reason": row.unresolved_reason,
    }


def _owned_evidence(
    execution: StudioExecution, publication: StudioPublication, binding: dict[str, Any],
) -> registry.StudioOwnership:
    owner = registry._owner(execution)
    journal.validate_row(publication)
    if (
        execution.state != "unresolved" or execution.phase != "returned"
        or execution.unresolved_reason != "filesystem_settlement_pending"
        or execution.returned_at is None
        or binding["execution_id"] != owner.execution_id or binding["job_id"] != owner.job_id
        or binding["admitted_generation"] != owner.admitted_generation
        or publication.id != binding["publication_id"] or publication.execution_id != owner.execution_id
        or publication.job_id != owner.job_id or publication.state != "observed"
        or publication.worker_incarnation != owner.worker_incarnation
        or publication.ownership_nonce != owner.nonce
        or publication.admitted_generation != owner.admitted_generation
        or publication.thread_resource_id != binding["thread_resource_id"]
        or publication.updated_at.isoformat() != binding["publication_observed_at"]
    ):
        _reject()
    resources = registry._resources(execution)
    operations = {item["operation"]: (key, item) for key, item in resources.items()}
    if (
        set(operations) != {"build_archive", "store_artifact"}
        or any(item["state"] != "joined" or item["outcome"] != "success" for item in resources.values())
    ):
        _reject()
    _, build = operations["build_archive"]
    storage_id, store = operations["store_artifact"]
    if (
        storage_id != publication.thread_resource_id
        or registry._stamp(build["registered_at"]) < execution.started_at
        or registry._stamp(store["registered_at"]) < registry._stamp(build["joined_at"])
        or publication.created_at < registry._stamp(store["registered_at"])
        or publication.updated_at > registry._stamp(store["joined_at"])
        or registry._stamp(store["joined_at"]) > execution.returned_at
        or evidence_digest(resources) != binding["thread_evidence_sha256"]
        or evidence_digest({"plan": publication.plan, "events": publication.events}) != binding["publication_evidence_sha256"]
        or evidence_digest(publication.events[-1]["payload"]["file"]) != binding["file_identity_sha256"]
        or publication.plan["checksum"] != binding["checksum"]
        or publication.plan["size_bytes"] != binding["size_bytes"]
    ):
        _reject()
    return owner


def _accepted_business(
    job: StudioJob, asset: StudioAsset, revision: StudioAssetRevision,
    binding: dict[str, Any], owner: registry.StudioOwnership, publication: StudioPublication,
) -> dict[str, Any]:
    guard = execution_guard(job)
    result = job.result_metadata
    if (
        job.id != owner.job_id or job.status != "completed" or job.progress != 100 or job.attempts != 1
        or job.lease_token is not None or not isinstance(job.completed_at, datetime) or not registry._aware(job.completed_at)
        or job.cancelled_at is not None or job.error_code is not None or job.error_message is not None
        or job.safety_status != "passed" or job.safety_findings != []
        or job.provider_mode != "provider_neutral" or job.provider is not None or job.model is not None
        or guard is None or guard["phase"] != "returned"
        or guard["worker_incarnation"] != owner.worker_incarnation
        or guard["admitted_generation"] != owner.admitted_generation
        or not isinstance(result, dict) or not isinstance(revision.revision_metadata, dict)
        or evidence_digest(result.get(BINDING_KEY)) != evidence_digest(binding)
        or evidence_digest(revision.revision_metadata.get(BINDING_KEY)) != evidence_digest(binding)
        or any(result.get(key) != binding[key] for key in ("asset_id", "revision_id", "checksum"))
        or any(type(result.get(key)) is not int or result[key] != binding[key] for key in ("revision_number", "size_bytes"))
        or asset.id != binding["asset_id"] or asset.organization_id != job.organization_id
        or revision.id != binding["revision_id"] or revision.asset_id != asset.id
        or revision.job_id != job.id or revision.organization_id != job.organization_id
        or revision.revision_number != binding["revision_number"]
        or revision.checksum != binding["checksum"] or revision.size_bytes != binding["size_bytes"]
        or revision.media_type != "application/zip" or revision.filename != publication.plan["filename"]
        or revision.status != "active" or asset.current_revision < revision.revision_number
        or (job.revision_of_asset_id is None and (revision.revision_number != 1 or asset.job_id != job.id))
        or (job.revision_of_asset_id is not None and job.revision_of_asset_id != asset.id)
    ):
        _reject()
    path = str(PurePosixPath("/", *publication.plan["components"], publication.plan["filename"]))
    if (
        revision.storage_path != path
        or hashlib.sha256(path.encode()).hexdigest() != binding["storage_path_sha256"]
        or publication.plan["components"][-3:] != [job.organization_id, asset.id, f"revision-{revision.revision_number}"]
    ):
        _reject()
    if asset.current_revision == revision.revision_number and (
        not isinstance(asset.asset_metadata, dict)
        or evidence_digest(asset.asset_metadata.get(BINDING_KEY)) != evidence_digest(binding)
        or asset.storage_path != path or asset.checksum != revision.checksum
        or asset.size_bytes != revision.size_bytes or asset.filename != revision.filename
        or asset.media_type != revision.media_type
    ):
        _reject()
    assert isinstance(job.completed_at, datetime)
    # A newer asset head is not evidence for this older attempt. Its immutable
    # revision and job binding above remain the source of acceptance.
    return {
        "job_id": job.id, "organization_id": job.organization_id,
        "completed_at": job.completed_at.isoformat(),
        "job_result": deepcopy(result), "revision_id": revision.id,
        "revision_binding": deepcopy(revision.revision_metadata[BINDING_KEY]),
    }


async def _record_success(
    session: AsyncSession, *, job_id: str, nonce: str, worker_incarnation: str,
    result_binding: dict[str, Any],
) -> StudioSettlement:
    """Keep job -> execution -> publication -> asset -> revision locks to commit.

    Internal transactional helper. It performs no commit or filesystem operation;
    only settle_success supplies the current task's acknowledged return capability.
    """
    proof = _binding(result_binding)
    if session.get_bind().dialect.name != "postgresql":
        _reject()
    with session.no_autoflush:
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
        job = await session.scalar(select(StudioJob).where(StudioJob.id == job_id).with_for_update().execution_options(populate_existing=True))
        owner = await registry.find_owner(session, job_id=job_id, nonce=nonce, worker_incarnation=worker_incarnation)
        if job is None or owner is None:
            _reject()
        execution = await registry._locked(session, owner)
        prior = await session.scalar(select(StudioSettlement.id).where(StudioSettlement.execution_id == owner.execution_id))
        if prior is not None:
            raise registry.StudioOwnershipLost("Studio settlement is single-use")
        if await session.scalar(
            select(StudioCrashReconciliation.id).where(
                StudioCrashReconciliation.execution_id == owner.execution_id
            )
        ) is not None:
            raise registry.StudioOwnershipLost(
                "Terminally reconciled Studio crash cannot settle as success"
            )
        if await session.scalar(
            select(StudioCrashObservation.id).where(
                StudioCrashObservation.execution_id == owner.execution_id
            )
        ) is not None:
            raise registry.StudioOwnershipLost(
                "Observed post-crash Studio execution requires explicit reconciliation"
            )
        publication = await session.scalar(select(StudioPublication).where(
            StudioPublication.execution_id == owner.execution_id,
        ).with_for_update().execution_options(populate_existing=True))
        if publication is None:
            _reject()
        _owned_evidence(execution, publication, proof)
        asset = await session.scalar(select(StudioAsset).where(StudioAsset.id == proof["asset_id"]).with_for_update().execution_options(populate_existing=True))
        revision = await session.scalar(select(StudioAssetRevision).where(StudioAssetRevision.id == proof["revision_id"]).with_for_update().execution_options(populate_existing=True))
        if asset is None or revision is None:
            _reject()
        business = _accepted_business(job, asset, revision, proof, owner, publication)
        stamp = await registry._now(session)
        if execution.returned_at is None or not isinstance(job.completed_at, datetime) or not (job.completed_at <= execution.returned_at <= stamp):
            _reject()
        row = StudioSettlement(
            id=str(uuid4()), execution_id=owner.execution_id, publication_id=publication.id,
            job_id=job_id, worker_incarnation=worker_incarnation,
            admitted_generation=owner.admitted_generation, created_at=stamp,
            proof={
                "schema": SCHEMA, "binding": deepcopy(proof),
                "execution_evidence_sha256": evidence_digest(_execution_evidence(execution)),
                "business_evidence_sha256": evidence_digest(business),
                "job_completed_at": job.completed_at.isoformat(),
                "staging_cleanup_verified": True, "accepted_archive_retained": True,
                "full_host_closure": False,
            },
        )
        row.proof_sha256 = evidence_digest(row.proof)
        validate_settlement(row, execution, publication)
    session.add(row)
    # No flush of unrelated caller mutations is performed here. Our wrapper owns
    # a fresh session and commits the receipt exactly once.
    return row


async def settle_success(
    *, session_factory: SessionFactory, acknowledgement: StudioResultAcknowledgement,
) -> None:
    """One live-task attempt; never retry an unknown commit outcome.

    Lost acknowledgement of the final receipt commit may leave a durable receipt.
    A later snapshot can verify that persisted proof, but this caller still raises;
    it does not repeat effects, erase evidence, or regenerate the accepted output.
    """
    current = asyncio.current_task()
    if (
        not isinstance(acknowledgement, StudioResultAcknowledgement)
        or acknowledgement.issuer is not _ISSUER or acknowledgement.consumed
        or current is not acknowledgement.task or current is None or current.cancelling()
    ):
        _reject()
    acknowledgement.consumed = True
    await registry.observe_execution_end(
        session_factory=session_factory, job_id=acknowledgement.job_id,
        nonce=acknowledgement.nonce, worker_incarnation=acknowledgement.worker_incarnation,
        interrupted=False,
    )
    async with session_factory() as session:
        await _record_success(
            session, job_id=acknowledgement.job_id, nonce=acknowledgement.nonce,
            worker_incarnation=acknowledgement.worker_incarnation,
            result_binding=json.loads(acknowledgement.binding_json),
        )
        await session.commit()


def validate_settlement(
    row: StudioSettlement, execution: StudioExecution, publication: StudioPublication,
) -> None:
    """Validate retained evidence without requiring surviving business rows."""
    proof = row.proof
    if (
        not all(registry._uuid(item) for item in (row.id, row.execution_id, row.publication_id, row.job_id, row.worker_incarnation))
        or type(row.admitted_generation) is not int or row.admitted_generation < 7
        or not registry._aware(row.created_at)
        or not _digest(row.proof_sha256) or evidence_digest(proof) != row.proof_sha256
        or not isinstance(proof, dict) or set(proof) != _PROOF_KEYS or proof["schema"] != SCHEMA
        or proof["staging_cleanup_verified"] is not True or proof["accepted_archive_retained"] is not True
        or proof["full_host_closure"] is not False
        or not _digest(proof["execution_evidence_sha256"]) or not _digest(proof["business_evidence_sha256"])
    ):
        _reject()
    binding = _binding(proof["binding"])
    owner = _owned_evidence(execution, publication, binding)
    if (
        row.execution_id != owner.execution_id or row.publication_id != publication.id
        or row.job_id != owner.job_id or row.worker_incarnation != owner.worker_incarnation
        or row.admitted_generation != owner.admitted_generation
        or evidence_digest(_execution_evidence(execution)) != proof["execution_evidence_sha256"]
        or execution.returned_at is None
        or not (registry._stamp(proof["job_completed_at"]) <= execution.returned_at <= row.created_at)
    ):
        _reject()


async def snapshot_settlements(
    session: AsyncSession, executions: list[StudioExecution], publications: list[StudioPublication],
    jobs: list[StudioJob],
) -> tuple[set[str], set[str], list[dict[str, Any]], set[str]]:
    """Keep invalid/orphan receipts visible; no mutation or full-host claim."""
    rows = (await session.scalars(select(StudioSettlement).order_by(StudioSettlement.id))).all()
    jobs_by_id = {row.id: row for row in jobs}
    execution_by_id = {row.id: row for row in executions}
    publication_by_id = {row.id: row for row in publications}
    accepted_executions: set[str] = set()
    accepted_publications: set[str] = set()
    job_ids: set[str] = set()
    observations = []
    for row in rows:
        execution = execution_by_id.get(row.execution_id)
        publication = publication_by_id.get(row.publication_id)
        valid = False
        if execution is not None and publication is not None:
            try:
                validate_settlement(row, execution, publication)
                job = jobs_by_id.get(row.job_id)
                if job is not None and (
                    job.status != "completed" or not isinstance(job.result_metadata, dict)
                    or evidence_digest(job.result_metadata.get(BINDING_KEY)) != evidence_digest(row.proof["binding"])
                    or job.cancelled_at is not None
                ):
                    _reject()
            except (registry.StudioResourceUncertain, ValueError, TypeError, KeyError):
                valid = False
            else:
                valid = True
        job_ids.add(row.job_id)
        if valid:
            accepted_executions.add(row.execution_id)
            accepted_publications.add(row.publication_id)
        observations.append({
            "settlement_id": row.id, "execution_id": row.execution_id,
            "publication_id": row.publication_id, "job_id": row.job_id,
            "admitted_generation": row.admitted_generation,
            "accepted_success": valid, "requires_reconciliation": not valid,
            "staging_cleanup_verified": valid, "accepted_archive_retained": valid,
        })
    return accepted_executions, accepted_publications, observations, job_ids
