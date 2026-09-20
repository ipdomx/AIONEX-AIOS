"""Bind a Studio business result to its acknowledged, owned publication.

This is a transactional output-acceptance boundary, not execution settlement or
post-crash reconciliation. It performs no filesystem operation, starts no thread,
commits nothing and releases no resource. The caller keeps job, execution and
publication locks through its business commit. A missing/ambiguous observation
must retain the archive and execution evidence instead of inventing a result.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import StudioJob, StudioPublication
from app.services.production_studio import BuiltArtifact
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry
from app.services.studio_execution_guard import execution_guard

BINDING_KEY = "studio_publication_binding"
BINDING_SCHEMA = "aionex.studio-publication-binding.v1"


def _reject() -> NoReturn:
    raise registry.StudioResourceUncertain("Studio output binding is unverified")


def evidence_digest(value: Any) -> str:
    """Canonical evidence fingerprint; not a signature or a filesystem reread."""
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def bind_owned_result(
    session: AsyncSession, *, job_id: str, nonce: str, worker_incarnation: str,
    asset_id: str, revision_id: str, revision_number: int, path: Path,
    artifact: BuiltArtifact,
) -> dict[str, Any]:
    """Return evidence only for the exact live owner and its successful output.

    Must precede all asset/revision/result mutations. The caller owns the commit;
    no admission-open check is added, so work already executing before maintenance
    closes may finish. An old, interrupted or orphan attempt is not reconciled
    here. Raw ownership nonces, storage paths and user content are never returned.
    """
    if (
        not all(registry._uuid(value) for value in (
            job_id, nonce, worker_incarnation, asset_id, revision_id,
        ))
        or type(revision_number) is not int or revision_number < 1
        or not isinstance(path, Path) or not isinstance(artifact, BuiltArtifact)
        or not isinstance(artifact.content, bytes)
        or type(artifact.size_bytes) is not int or artifact.size_bytes <= 0
        or len(artifact.content) != artifact.size_bytes
        or artifact.media_type != "application/zip"
        or not isinstance(artifact.manifest, dict)
    ):
        _reject()
    # Suppress pending caller autoflush until all evidence has been accepted.
    with session.no_autoflush:
        job = await session.scalar(select(StudioJob).where(
            StudioJob.id == job_id,
        ).with_for_update().execution_options(populate_existing=True))
        guard = execution_guard(job) if job is not None else None
        if (
            job is None or job.status != "running" or job.lease_token != nonce
            or job.attempts != 1 or job.completed_at is not None
            or job.cancelled_at is not None or job.provider_mode != "provider_neutral"
            or job.provider is not None or job.model is not None
            or guard is None or guard["phase"] != "executing"
            or guard["worker_incarnation"] != worker_incarnation
            or job.error_code is not None or job.error_message is not None
        ):
            _reject()
        owner = await registry.find_owner(
            session, job_id=job_id, nonce=nonce, worker_incarnation=worker_incarnation,
        )
        if owner is None or owner.admitted_generation != guard["admitted_generation"]:
            _reject()
        execution = await registry._locked(session, owner)
        if execution.state != "active" or execution.phase != "executing":
            _reject()
        resources = registry._resources(execution)
        operations = {item["operation"]: (key, item) for key, item in resources.items()}
        if (
            set(operations) != {"build_archive", "store_artifact"}
            or any(item["state"] != "joined" or item["outcome"] != "success" for item in resources.values())
        ):
            _reject()
        _, build = operations["build_archive"]
        storage_id, storage = operations["store_artifact"]
        if (
            registry._stamp(build["registered_at"]) < execution.started_at
            or registry._stamp(storage["registered_at"]) < registry._stamp(build["joined_at"])
        ):
            _reject()
        publication = await session.scalar(select(StudioPublication).where(
            StudioPublication.execution_id == owner.execution_id,
        ).with_for_update().execution_options(populate_existing=True))
        if publication is None:
            _reject()
        journal.validate_row(publication)
        if (
            publication.state != "observed" or publication.job_id != job_id
            or publication.thread_resource_id != storage_id
            or publication.worker_incarnation != owner.worker_incarnation
            or publication.ownership_nonce != owner.nonce
            or publication.admitted_generation != owner.admitted_generation
            or publication.created_at < registry._stamp(storage["registered_at"])
            or publication.updated_at > registry._stamp(storage["joined_at"])
        ):
            _reject()
        plan = publication.plan
        configured = Path(settings.STUDIO_ASSET_ROOT)
        if ".." in configured.parts:
            _reject()
        expected_root = Path(os.path.abspath(configured))
        expected_path = expected_root / job.organization_id / asset_id / f"revision-{revision_number}" / artifact.filename
        if (
            plan["root"] != str(expected_root)
            or plan["components"] != [*expected_root.parts[1:], job.organization_id, asset_id, f"revision-{revision_number}"]
            or plan["filename"] != artifact.filename or path != expected_path
            or plan["checksum"] != artifact.checksum or plan["size_bytes"] != artifact.size_bytes
            or (job.revision_of_asset_id is None and revision_number != 1)
            or (job.revision_of_asset_id is not None and job.revision_of_asset_id != asset_id)
            or artifact.manifest.get("schema") != "aionex.production-asset.v2"
            or artifact.manifest.get("job_id") != job_id
            or type(artifact.manifest.get("revision")) is not int
            or artifact.manifest["revision"] != revision_number
            or artifact.manifest.get("department") != job.department
            or artifact.manifest.get("provider_mode") != "provider_neutral"
        ):
            _reject()
        # Publication's descriptor-bound verifier already checked actual bytes.
        # These fingerprints bind that retained observation, not a new disk read.
        return {
            "schema": BINDING_SCHEMA, "job_id": job_id,
            "execution_id": owner.execution_id, "publication_id": publication.id,
            "thread_resource_id": storage_id, "admitted_generation": owner.admitted_generation,
            "asset_id": asset_id, "revision_id": revision_id, "revision_number": revision_number,
            "checksum": artifact.checksum, "size_bytes": artifact.size_bytes,
            "storage_path_sha256": hashlib.sha256(str(expected_path).encode("utf-8")).hexdigest(),
            "publication_evidence_sha256": evidence_digest({
                "plan": deepcopy(plan), "events": deepcopy(publication.events),
            }),
            "file_identity_sha256": evidence_digest(publication.events[-1]["payload"]["file"]),
            "thread_evidence_sha256": evidence_digest(deepcopy(resources)),
            "publication_observed_at": publication.updated_at.isoformat(),
        }
