"""Permanent Studio execution and thread evidence, never automatic settlement.

The ledger is independent of business-row deletion. Claim and one-shot start are
committed with the job, before work is submitted. A thread resource is persisted
before its submission. Joined and cleaned are different facts: this increment
never certifies filesystem cleanup, retries an attempt, or releases a blocker.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import threading
from typing import Any, ParamSpec, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StudioExecution, StudioJob
from app.services.host_maintenance_admission import (
    SessionFactory, read_admission_snapshot,
)
from app.services.host_maintenance_studio_admission import require_studio_admission
from app.services.studio_execution_guard import execution_guard, pristine_conditions
from app.services.studio_thread_runtime import StudioThreadUncertain, joined_studio_thread

P = ParamSpec("P")
T = TypeVar("T")
_OPERATIONS = frozenset({"build_archive", "store_artifact"})
_RESOURCE_KEYS = frozenset({
    "kind", "operation", "state", "registered_at", "joined_at", "outcome",
    "cleanup_verified",
})


class StudioOwnershipLost(RuntimeError):
    """The exact durable execution owner no longer authorizes this operation."""


class StudioResourceUncertain(RuntimeError):
    """Malformed or unavailable evidence cannot certify completion or cleanup."""


class StudioResourceCancelled(asyncio.CancelledError):
    """Cancellation prevents new resources without proving prior resources ended."""


@dataclass(frozen=True, slots=True)
class StudioOwnership:
    execution_id: str
    job_id: str
    worker_incarnation: str
    admitted_generation: int
    nonce: str = field(repr=False)


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _stamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise StudioResourceUncertain("Studio resource timestamp is invalid")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise StudioResourceUncertain("Studio resource timestamp is invalid") from None
    if not _aware(result):
        raise StudioResourceUncertain("Studio resource timestamp lacks timezone")
    return result


def _resources(row: StudioExecution) -> dict[str, dict[str, Any]]:
    data = row.resources
    if not isinstance(data, dict) or len(data) > 2:
        raise StudioResourceUncertain("Studio resource inventory is invalid")
    operations: set[str] = set()
    for identifier, resource in data.items():
        if not _uuid(identifier) or not isinstance(resource, dict) or set(resource) != _RESOURCE_KEYS:
            raise StudioResourceUncertain("Studio resource record is invalid")
        if (
            resource["kind"] != "thread"
            or not isinstance(resource["operation"], str)
            or resource["operation"] not in _OPERATIONS
            or resource["operation"] in operations
            or not isinstance(resource["state"], str)
            or resource["state"] not in {"reserved", "joined", "unresolved"}
            or resource["cleanup_verified"] is not False
        ):
            raise StudioResourceUncertain("Studio resource identity is invalid")
        operations.add(resource["operation"])
        start = _stamp(resource["registered_at"])
        if resource["state"] == "joined":
            if (
                _stamp(resource["joined_at"]) < start
                or not isinstance(resource["outcome"], str)
                or resource["outcome"] not in {"success", "failed"}
            ):
                raise StudioResourceUncertain("Studio thread join evidence is invalid")
        elif resource["joined_at"] is not None or resource["outcome"] is not None:
            raise StudioResourceUncertain("Studio resource has unsupported completion proof")
    return data


def _owner(row: StudioExecution) -> StudioOwnership:
    if (
        not all(_uuid(value) for value in (row.id, row.job_id, row.worker_incarnation, row.ownership_nonce))
        or type(row.admitted_generation) is not int or row.admitted_generation < 7
        or not isinstance(row.state, str) or row.state not in {"active", "unresolved"}
        or not isinstance(row.phase, str) or row.phase not in {"claimed", "executing", "returned"}
        or row.cleanup_verified is not False
        or not _aware(row.started_at) or not _aware(row.updated_at)
        or row.updated_at < row.started_at
        or (row.returned_at is not None and (not _aware(row.returned_at) or row.returned_at < row.started_at))
        or (row.phase == "returned") != (row.returned_at is not None)
        or (row.state == "active" and row.unresolved_reason is not None)
        or (row.state == "unresolved" and (
            not isinstance(row.unresolved_reason, str) or not row.unresolved_reason
            or len(row.unresolved_reason) > 160 or "\x00" in row.unresolved_reason
        ))
    ):
        raise StudioResourceUncertain("Studio execution ownership is invalid")
    _resources(row)
    return StudioOwnership(row.id, row.job_id, row.worker_incarnation, row.admitted_generation, row.ownership_nonce)


async def _now(session: AsyncSession) -> datetime:
    if session.get_bind().dialect.name != "postgresql":
        raise StudioResourceUncertain("Studio resource evidence requires PostgreSQL")
    result = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(result, datetime) or not _aware(result):
        raise StudioResourceUncertain("Studio database clock is unavailable")
    return result


async def _locked(session: AsyncSession, owner: StudioOwnership) -> StudioExecution:
    if not isinstance(owner, StudioOwnership):
        raise StudioOwnershipLost("Studio execution owner is required")
    with session.no_autoflush:
        row = await session.scalar(select(StudioExecution).where(
            StudioExecution.id == owner.execution_id,
            StudioExecution.job_id == owner.job_id,
            StudioExecution.worker_incarnation == owner.worker_incarnation,
            StudioExecution.admitted_generation == owner.admitted_generation,
            StudioExecution.ownership_nonce == owner.nonce,
        ).with_for_update().execution_options(populate_existing=True))
    if row is None or _owner(row) != owner:
        raise StudioOwnershipLost("Studio execution ownership differs")
    return row


async def register_claim(
    session: AsyncSession, *, job_id: str, nonce: str, worker_incarnation: str,
) -> StudioOwnership:
    """Reserve an untouched job's owner within the caller's claim transaction.

    Does not commit. Registration must precede the caller's job mutation, and
    the acknowledged transaction must include both mutations before any I/O.
    """
    authority = await require_studio_admission(session)
    if not all(_uuid(value) for value in (job_id, nonce, worker_incarnation)):
        raise ValueError("Studio registration identity is invalid")
    with session.no_autoflush:
        job = await session.scalar(select(StudioJob).where(
            StudioJob.id == job_id, *pristine_conditions(),
        ).with_for_update().execution_options(populate_existing=True))
        prior = await session.scalar(select(StudioExecution.id).where(StudioExecution.job_id == job_id))
    if job is None or prior is not None:
        raise StudioOwnershipLost("Only untouched Studio backlog can register")
    stamp = await _now(session)
    row = StudioExecution(
        id=str(uuid4()), job_id=job_id, worker_incarnation=worker_incarnation,
        admitted_generation=authority.generation, ownership_nonce=nonce,
        state="active", phase="claimed", resources={}, cleanup_verified=False,
        started_at=stamp, updated_at=stamp,
    )
    session.add(row)
    await session.flush()
    return _owner(row)


async def find_owner(
    session: AsyncSession, *, job_id: str, nonce: str, worker_incarnation: str,
) -> StudioOwnership | None:
    with session.no_autoflush:
        row = await session.scalar(select(StudioExecution).where(
            StudioExecution.job_id == job_id, StudioExecution.ownership_nonce == nonce,
            StudioExecution.worker_incarnation == worker_incarnation,
        ).execution_options(populate_existing=True))
    return _owner(row) if row is not None else None


async def begin_registered(
    session: AsyncSession, *, job_id: str, nonce: str, worker_incarnation: str,
    admitted_generation: int,
) -> bool:
    """Transition the ledger with the already locked and validated business job."""
    owner = await find_owner(session, job_id=job_id, nonce=nonce, worker_incarnation=worker_incarnation)
    if owner is None or owner.admitted_generation != admitted_generation:
        return False
    row = await _locked(session, owner)
    if row.state != "active" or row.phase != "claimed" or row.resources:
        return False
    row.phase = "executing"
    row.updated_at = await _now(session)
    return True


async def observe_execution_end(
    *, session_factory: SessionFactory, job_id: str, nonce: str,
    worker_incarnation: str, interrupted: bool,
) -> None:
    """Retain all evidence; even normal return awaits filesystem reconciliation."""
    async with session_factory() as session:
        owner = await find_owner(session, job_id=job_id, nonce=nonce, worker_incarnation=worker_incarnation)
        if owner is None:
            raise StudioOwnershipLost("Studio execution ledger is missing")
        row = await _locked(session, owner)
        if row.phase not in {"executing", "returned"}:
            raise StudioOwnershipLost("Studio execution was not started")
        stamp = await _now(session)
        row.state = "unresolved"
        row.unresolved_reason = row.unresolved_reason or (
            "execution_interrupted" if interrupted else "filesystem_settlement_pending"
        )
        if not interrupted:
            row.phase = "returned"
            row.returned_at = row.returned_at or stamp
        row.updated_at = stamp
        await session.commit()


async def reserve_thread(
    *, session_factory: SessionFactory, job_id: str, nonce: str,
    worker_incarnation: str, operation: str,
) -> tuple[StudioOwnership, str]:
    """Acknowledge durable intent before executor submission; no retries."""
    if operation not in _OPERATIONS:
        raise ValueError("Unknown Studio thread operation")
    async with session_factory() as session:
        # Keep the job -> execution order used by claim/start. An old admitted
        # generation may drain after admission closes, but cannot start new work.
        with session.no_autoflush:
            job = await session.scalar(select(StudioJob).where(
                StudioJob.id == job_id,
            ).with_for_update().execution_options(populate_existing=True))
        owner = await find_owner(session, job_id=job_id, nonce=nonce, worker_incarnation=worker_incarnation)
        if owner is None:
            raise StudioOwnershipLost("Studio thread owner is missing")
        row = await _locked(session, owner)
        guard = execution_guard(job) if job is not None else None
        if job is not None and job.status == "cancel_requested":
            raise StudioResourceCancelled()
        if (
            job is None or job.status != "running" or job.lease_token != nonce
            or guard is None or guard["phase"] != "executing"
            or guard["worker_incarnation"] != worker_incarnation
            or guard["admitted_generation"] != owner.admitted_generation
            or row.state != "active" or row.phase != "executing"
        ):
            raise StudioOwnershipLost("Studio thread start is not owned")
        resources = _resources(row)
        if any(value["operation"] == operation for value in resources.values()):
            raise StudioOwnershipLost("Studio thread intent is single-use")
        if operation == "store_artifact" and not any(
            value["operation"] == "build_archive" and value["state"] == "joined"
            and value["outcome"] == "success" for value in resources.values()
        ):
            raise StudioOwnershipLost("Studio storage requires a joined successful build")
        identifier, stamp = str(uuid4()), await _now(session)
        row.resources = {**resources, identifier: {
            "kind": "thread", "operation": operation, "state": "reserved",
            "registered_at": stamp.isoformat(), "joined_at": None, "outcome": None,
            "cleanup_verified": False,
        }}
        row.updated_at = stamp
        await session.commit()
        return owner, identifier


async def observe_thread(
    *, session_factory: SessionFactory, owner: StudioOwnership,
    resource_id: str, joined: bool, succeeded: bool,
) -> None:
    """Accept local wrapper observations, not timeout or cancellation as proof."""
    if type(joined) is not bool or type(succeeded) is not bool:
        raise ValueError("Studio thread observations must be boolean")
    async with session_factory() as session:
        row = await _locked(session, owner)
        resources = _resources(row)
        resource = resources.get(resource_id)
        if resource is None or resource["state"] != "reserved":
            raise StudioOwnershipLost("Studio resource observation is single-use")
        stamp = await _now(session)
        row.resources = {**resources, resource_id: {
            **resource, "state": "joined" if joined else "unresolved",
            "joined_at": stamp.isoformat() if joined else None,
            "outcome": ("success" if succeeded else "failed") if joined else None,
        }}
        row.updated_at = stamp
        if not joined:
            row.state = "unresolved"
            row.unresolved_reason = row.unresolved_reason or "thread_completion_unverified"
        await session.commit()


async def owned_studio_thread(
    session_factory: SessionFactory, job_id: str, nonce: str,
    worker_incarnation: str, operation: str, function: Callable[P, T],
    /, *args: P.args, **kwargs: P.kwargs,
) -> T:
    """Journal intent, then join the actual function; journal failure stays visible."""
    owner, resource_id = await reserve_thread(
        session_factory=session_factory, job_id=job_id, nonce=nonce,
        worker_incarnation=worker_incarnation, operation=operation,
    )
    finished = threading.Event()
    successful = threading.Event()
    def call() -> T:
        try:
            result = function(*args, **kwargs)
            successful.set()
            return result
        finally:
            finished.set()
    try:
        result = await joined_studio_thread(call)
    except BaseException as original:
        # An uncertain executor is never join evidence, even if the function's
        # local completion flag was set. Persistence must not replace the
        # original cancellation or its late-function failure cause.
        try:
            await observe_thread(
                session_factory=session_factory, owner=owner, resource_id=resource_id,
                joined=finished.is_set() and not isinstance(original, StudioThreadUncertain),
                succeeded=successful.is_set(),
            )
        except BaseException as evidence_error:
            # The durable reservation remains a blocker. Expose only the error
            # class, not connection details or user content from the journal.
            original.add_note(
                f"Studio thread observation unavailable: {type(evidence_error).__name__}"
            )
        raise
    await observe_thread(
        session_factory=session_factory, owner=owner, resource_id=resource_id,
        joined=finished.is_set(), succeeded=successful.is_set(),
    )
    return result


async def execution_snapshot(*, session_factory: SessionFactory) -> dict[str, Any]:
    """One all-generation snapshot; no ownership nonces or content in output."""
    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            raise StudioResourceUncertain("Studio snapshot requires PostgreSQL")
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        authority = await read_admission_snapshot(session, required_scope="studio_job_requests")
        stamp = await _now(session)
        rows = (await session.scalars(select(StudioExecution).order_by(StudioExecution.id))).all()
        observed = []
        registered: set[str] = set()
        for row in rows:
            owner = _owner(row)
            registered.add(owner.job_id)
            observed.append({
                "execution_id": row.id, "job_id": row.job_id,
                "admitted_generation": row.admitted_generation,
                "state": row.state, "phase": row.phase,
                "resource_count": len(row.resources),
                "joined_threads": sum(value["state"] == "joined" for value in row.resources.values()),
                "cleanup_verified": False,
            })
        untouched = set((await session.scalars(select(StudioJob.id).where(*pristine_conditions()))).all())
        jobs = (await session.scalars(select(StudioJob).order_by(StudioJob.id))).all()
        legacy = [job.id for job in jobs if job.id not in registered and job.id not in untouched]
        # Completion/failed/cancelled and a missing business row cannot erase a
        # prior owner. This conservative foundation releases no execution rows.
        return {
            "scope": "studio_execution_threads", "observed_at": stamp.isoformat(),
            "executions": observed, "unregistered_unverified_job_ids": legacy,
            "blocker_count": len(observed) + len(legacy),
            "is_clear": not observed and not legacy,
            "admission_closed": not authority.is_open,
            "coverage_unverified": True, "full_host_closure": False,
        }
