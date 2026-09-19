"""Observe post-crash Studio filesystem state without mutating or settling it.

Observation requires Studio admission to be durably closed, but explicitly does
not treat admission closure as process drain. It only records point-in-time
descriptor identities beneath the already journaled directory chain. No path is
created, removed, renamed, linked, chmodded or rewritten; no retry is authorized.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import os
import stat
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    StudioCrashObservation,
    StudioExecution,
    StudioJob,
    StudioPoststartCancellation,
    StudioPrestartCancellation,
    StudioPublication,
    StudioSettlement,
)
from app.services import studio_publication_journal as journal
from app.services import studio_resource_registry as registry
from app.services.host_maintenance_admission import (
    SessionFactory,
    read_admission_snapshot,
)
from app.services.studio_result_binding import evidence_digest
from app.services.studio_success_settlement import _execution_evidence

SCHEMA = "aionex.studio-postcrash-observation.v1"
_LAYOUTS = frozenset({
    "no_publication",
    "directory_chain_incomplete",
    "directory_unavailable",
    "directory_identity_conflict",
    "no_archive_entry",
    "owned_staging_present",
    "owned_final_present",
    "owned_staging_and_final_hardlinks",
    "entry_identity_conflict",
})
_PROOF_KEYS = frozenset({
    "schema",
    "organization_id",
    "maintenance_operation_id",
    "maintenance_generation",
    "execution_evidence_sha256",
    "publication_evidence_sha256",
    "publication_phase",
    "layout",
    "directory_chain_verified",
    "staging",
    "final",
    "process_drain_verified",
    "cleanup_authorized",
    "filesystem_mutation_performed",
    "full_host_closure",
})
_ENTRY_KEYS = frozenset({"status", "identity"})
_ID_KEYS = frozenset({
    "device", "inode", "kind", "uid", "gid", "mode", "links", "size",
})
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class StudioCrashObservationUnavailable(RuntimeError):
    """Observation cannot be trusted or maintenance is not closed."""


def _current_identity(value: os.stat_result) -> dict[str, Any]:
    return {
        "device": value.st_dev,
        "inode": value.st_ino,
        "kind": "directory" if stat.S_ISDIR(value.st_mode) else (
            "file" if stat.S_ISREG(value.st_mode) else "other"
        ),
        "uid": value.st_uid,
        "gid": value.st_gid,
        "mode": stat.S_IMODE(value.st_mode),
        "links": value.st_nlink,
        "size": value.st_size,
    }


def _same_stable_identity(expected: dict[str, Any], current: dict[str, Any]) -> bool:
    return (
        isinstance(expected, dict)
        and all(expected.get(key) == current[key] for key in (
            "device", "inode", "kind", "uid", "gid", "mode",
        ))
    )


def _directory_evidence(publication: StudioPublication) -> list[dict[str, Any]]:
    return [
        deepcopy(event["payload"]["identity"])
        for event in publication.events
        if event["operation"] == "directory_observed"
    ]


def _pinned_file_evidence(publication: StudioPublication) -> dict[str, Any] | None:
    pinned = None
    for event in publication.events:
        payload = event["payload"]
        if set(payload) == {"file"}:
            pinned = deepcopy(payload["file"])
    return pinned


def _entry(directory: int, name: str, pinned: dict[str, Any] | None) -> dict[str, Any]:
    try:
        raw = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return {"status": "absent", "identity": None}
    except OSError:
        return {"status": "unavailable", "identity": None}
    identity = _current_identity(raw)
    if (
        identity["kind"] != "file"
        or pinned is None
        or not _same_stable_identity(pinned, identity)
    ):
        return {"status": "identity_conflict", "identity": identity}
    return {"status": "owned", "identity": identity}


def _observe_publication(publication: StudioPublication) -> dict[str, Any]:
    journal.validate_row(publication)
    phase = journal.validate_journal(
        publication.plan, publication.events, publication.created_at
    )
    components = publication.plan["components"]
    expected_directories = _directory_evidence(publication)
    empty = {"status": "not_observed", "identity": None}
    if len(expected_directories) != len(components):
        return {
            "publication_phase": phase,
            "layout": "directory_chain_incomplete",
            "directory_chain_verified": False,
            "staging": empty,
            "final": empty,
        }

    with ExitStack() as stack:
        directory = os.open("/", _DIRECTORY_FLAGS)
        stack.callback(os.close, directory)
        for index, name in enumerate(components):
            try:
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
            except OSError:
                return {
                    "publication_phase": phase,
                    "layout": "directory_unavailable",
                    "directory_chain_verified": False,
                    "staging": empty,
                    "final": empty,
                }
            stack.callback(os.close, child)
            current = _current_identity(os.fstat(child))
            if not _same_stable_identity(expected_directories[index], current):
                return {
                    "publication_phase": phase,
                    "layout": "directory_identity_conflict",
                    "directory_chain_verified": False,
                    "staging": empty,
                    "final": empty,
                }
            directory = child

        pinned = _pinned_file_evidence(publication)
        staging = _entry(directory, publication.plan["staging_name"], pinned)
        final = _entry(directory, publication.plan["filename"], pinned)

        if staging["status"] in {"identity_conflict", "unavailable"} or final["status"] in {
            "identity_conflict", "unavailable",
        }:
            layout = "entry_identity_conflict"
        elif staging["status"] == "absent" and final["status"] == "absent":
            layout = "no_archive_entry"
        elif staging["status"] == "owned" and final["status"] == "absent":
            layout = "owned_staging_present"
        elif staging["status"] == "absent" and final["status"] == "owned":
            layout = "owned_final_present"
        elif staging["status"] == "owned" and final["status"] == "owned":
            left, right = staging["identity"], final["identity"]
            layout = (
                "owned_staging_and_final_hardlinks"
                if left["device"] == right["device"]
                and left["inode"] == right["inode"]
                and left["links"] >= 2
                and right["links"] >= 2
                else "entry_identity_conflict"
            )
        else:
            layout = "entry_identity_conflict"

        return {
            "publication_phase": phase,
            "layout": layout,
            "directory_chain_verified": True,
            "staging": staging,
            "final": final,
        }


def validate_observation(row: StudioCrashObservation) -> None:
    proof = row.proof
    valid = (
        all(registry._uuid(value) for value in (
            row.id, row.execution_id, row.job_id, row.worker_incarnation,
        ))
        and (row.publication_id is None or registry._uuid(row.publication_id))
        and type(row.admitted_generation) is int
        and row.admitted_generation >= 7
        and registry._aware(row.created_at)
        and isinstance(proof, dict)
        and set(proof) == _PROOF_KEYS
        and proof["schema"] == SCHEMA
        and registry._uuid(proof["organization_id"])
        and registry._uuid(proof["maintenance_operation_id"])
        and type(proof["maintenance_generation"]) is int
        and proof["maintenance_generation"] >= 7
        and isinstance(proof["execution_evidence_sha256"], str)
        and len(proof["execution_evidence_sha256"]) == 64
        and (
            proof["publication_evidence_sha256"] is None
            or isinstance(proof["publication_evidence_sha256"], str)
            and len(proof["publication_evidence_sha256"]) == 64
        )
        and (
            (
                row.publication_id is None
                and proof["publication_evidence_sha256"] is None
                and proof["publication_phase"] is None
                and proof["layout"] == "no_publication"
            )
            or (
                row.publication_id is not None
                and isinstance(proof["publication_evidence_sha256"], str)
                and len(proof["publication_evidence_sha256"]) == 64
                and isinstance(proof["publication_phase"], str)
                and proof["layout"] != "no_publication"
            )
        )
        and proof["layout"] in _LAYOUTS
        and type(proof["directory_chain_verified"]) is bool
        and _valid_entry(proof["staging"])
        and _valid_entry(proof["final"])
        and proof["process_drain_verified"] is False
        and proof["cleanup_authorized"] is False
        and proof["filesystem_mutation_performed"] is False
        and proof["full_host_closure"] is False
        and evidence_digest(proof) == row.proof_sha256
    )
    if not valid:
        raise registry.StudioResourceUncertain(
            "Studio crash observation proof is invalid"
        )


def _valid_entry(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _ENTRY_KEYS:
        return False
    if value["status"] not in {
        "not_applicable", "not_observed", "absent", "owned",
        "identity_conflict", "unavailable",
    }:
        return False
    identity = value["identity"]
    if value["status"] in {
        "not_applicable", "not_observed", "absent", "unavailable",
    }:
        return identity is None
    if identity is None:
        return False
    return (
        isinstance(identity, dict)
        and set(identity) == _ID_KEYS
        and all(
            type(identity[key]) is int and identity[key] >= 0
            for key in _ID_KEYS - {"kind"}
        )
        and identity["kind"] in {"file", "directory", "other"}
        and identity["inode"] > 0
        and identity["mode"] <= 0o7777
    )


async def observe_postcrash_state(
    *,
    session_factory: SessionFactory,
    job_id: str,
    nonce: str,
    worker_incarnation: str,
) -> StudioCrashObservation | None:
    """Record one closed-maintenance, read-only observation for an unsettled attempt."""
    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            raise StudioCrashObservationUnavailable(
                "Studio crash observation requires PostgreSQL"
            )
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
        authority = await read_admission_snapshot(
            session, required_scope="studio_job_requests"
        )
        if authority.is_open or authority.operation_id is None:
            raise StudioCrashObservationUnavailable(
                "Studio crash observation requires closed maintenance admission"
            )

        with session.no_autoflush:
            job = await session.scalar(
                select(StudioJob)
                .where(StudioJob.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if job is None:
                return None
            owner = await registry.find_owner(
                session,
                job_id=job_id,
                nonce=nonce,
                worker_incarnation=worker_incarnation,
            )
            if owner is None:
                return None
            execution = await registry._locked(session, owner)

            existing = await session.scalar(
                select(StudioCrashObservation)
                .where(StudioCrashObservation.execution_id == owner.execution_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing is not None:
                validate_observation(existing)
                return existing

            terminal = [
                await session.scalar(
                    select(StudioSettlement.id)
                    .where(StudioSettlement.execution_id == owner.execution_id)
                ),
                await session.scalar(
                    select(StudioPrestartCancellation.id)
                    .where(
                        StudioPrestartCancellation.execution_id
                        == owner.execution_id
                    )
                ),
                await session.scalar(
                    select(StudioPoststartCancellation.id)
                    .where(
                        StudioPoststartCancellation.execution_id
                        == owner.execution_id
                    )
                ),
            ]
            if any(item is not None for item in terminal):
                return None

            publication = await session.scalar(
                select(StudioPublication)
                .where(StudioPublication.execution_id == owner.execution_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if publication is None:
                observed = {
                    "publication_phase": None,
                    "layout": "no_publication",
                    "directory_chain_verified": False,
                    "staging": {"status": "not_applicable", "identity": None},
                    "final": {"status": "not_applicable", "identity": None},
                }
                publication_sha = None
            else:
                observed = _observe_publication(publication)
                publication_sha = evidence_digest({
                    "plan": deepcopy(publication.plan),
                    "events": deepcopy(publication.events),
                })

            stamp = await registry._now(session)
            proof = {
                "schema": SCHEMA,
                "organization_id": job.organization_id,
                "maintenance_operation_id": authority.operation_id,
                "maintenance_generation": authority.generation,
                "execution_evidence_sha256": evidence_digest(
                    _execution_evidence(execution)
                ),
                "publication_evidence_sha256": publication_sha,
                **observed,
                "process_drain_verified": False,
                "cleanup_authorized": False,
                "filesystem_mutation_performed": False,
                "full_host_closure": False,
            }
            row = StudioCrashObservation(
                id=str(uuid4()),
                execution_id=owner.execution_id,
                publication_id=publication.id if publication is not None else None,
                job_id=job_id,
                worker_incarnation=owner.worker_incarnation,
                admitted_generation=owner.admitted_generation,
                proof=proof,
                proof_sha256=evidence_digest(proof),
                created_at=stamp,
            )
            validate_observation(row)
            session.add(row)
        await session.commit()
        return row


async def snapshot_crash_observations(
    session: AsyncSession,
    executions: list[StudioExecution],
    publications: list[StudioPublication],
    jobs: list[StudioJob],
) -> tuple[list[dict[str, Any]], set[str], int, int]:
    """Validate retained DB proof only; observations never clear a blocker."""
    rows = list((
        await session.scalars(
            select(StudioCrashObservation).order_by(StudioCrashObservation.id)
        )
    ).all())
    executions_by_id = {row.id: row for row in executions}
    publications_by_id = {row.id: row for row in publications}
    jobs_by_id = {row.id: row for row in jobs}
    receipt_jobs: set[str] = set()
    observations: list[dict[str, Any]] = []
    invalid = 0
    orphans = 0

    for row in rows:
        valid = True
        execution = executions_by_id.get(row.execution_id)
        publication = (
            publications_by_id.get(row.publication_id)
            if row.publication_id is not None
            else None
        )
        job = jobs_by_id.get(row.job_id)
        try:
            validate_observation(row)
            if execution is None:
                raise registry.StudioResourceUncertain(
                    "Studio crash observation lost its execution evidence"
                )
            owner = registry._owner(execution)
            if (
                owner.execution_id != row.execution_id
                or owner.job_id != row.job_id
                or owner.worker_incarnation != row.worker_incarnation
                or owner.admitted_generation != row.admitted_generation
                or evidence_digest(_execution_evidence(execution))
                != row.proof["execution_evidence_sha256"]
            ):
                raise registry.StudioResourceUncertain(
                    "Studio crash observation execution evidence changed"
                )
            expected_publication = row.proof["publication_evidence_sha256"]
            if row.publication_id is None:
                if expected_publication is not None:
                    raise registry.StudioResourceUncertain(
                        "Studio crash observation publication identity differs"
                    )
            else:
                if publication is None:
                    raise registry.StudioResourceUncertain(
                        "Studio crash observation publication is missing"
                    )
                journal.validate_row(publication)
                if evidence_digest({
                    "plan": deepcopy(publication.plan),
                    "events": deepcopy(publication.events),
                }) != expected_publication:
                    raise registry.StudioResourceUncertain(
                        "Studio crash observation publication evidence changed"
                    )
            if job is not None and job.organization_id != row.proof["organization_id"]:
                raise registry.StudioResourceUncertain(
                    "Studio crash observation tenant differs"
                )
        except (
            registry.StudioResourceUncertain,
            ValueError,
            TypeError,
            KeyError,
        ):
            valid = False

        receipt_jobs.add(row.job_id)
        invalid += int(not valid)
        orphans += int(execution is None)
        observations.append({
            "observation_id": row.id,
            "execution_id": row.execution_id,
            "publication_id": row.publication_id,
            "job_id": row.job_id,
            "admitted_generation": row.admitted_generation,
            "layout": row.proof.get("layout") if isinstance(row.proof, dict) else None,
            "directory_chain_verified": (
                row.proof.get("directory_chain_verified")
                if isinstance(row.proof, dict)
                else False
            ),
            "valid_observation": valid,
            "requires_reconciliation": True,
            "process_drain_verified": False,
            "cleanup_authorized": False,
        })

    return observations, receipt_jobs, invalid, orphans
