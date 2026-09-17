"""Durable ownership of unfinished backup worker cycles.

Registration commits under shared admission before I/O. Heartbeat deadlines are
observations only: expiry never deletes, releases, or transfers an owner. Normal
completion explicitly deletes one exact active owner after all work has settled.
Unresolved records require reconciliation outside this initial partial scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, delete, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import HostMaintenanceWorkCycle
from app.services import host_maintenance_admission as admission
from app.services.host_maintenance_admission import HostMaintenanceSnapshot, SessionFactory

CONSUMER = "backup_cycles"
CYCLE_LEASE_SECONDS = 120


@dataclass(frozen=True, slots=True)
class CycleOwnership:
    cycle_id: str
    worker_incarnation: str
    admitted_generation: int
    ownership_nonce: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CycleObservation:
    cycle_id: str
    worker_incarnation: str
    admitted_generation: int
    state: str
    phase: str
    job_id: str | None
    started_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime
    unresolved_reason: str | None


@dataclass(frozen=True, slots=True)
class CycleSnapshot:
    """Partial, coverage-unverified observation of unfinished backup cycles."""

    authority: HostMaintenanceSnapshot
    observed_at: datetime
    cycles: tuple[CycleObservation, ...]
    active_count: int
    unresolved_count: int
    expired_count: int
    scope: str = CONSUMER
    coverage_unverified: bool = True
    full_host_closure: bool = False

    @property
    def unfinished_count(self) -> int:
        return len(self.cycles)

    @property
    def is_clear(self) -> bool:
        """Report an empty registry only; full-host coverage remains unverified.

        This property cannot establish that uninstrumented workers, enqueue
        paths, or other host activity have drained.
        """
        return self.unfinished_count == 0


class CycleOwnershipLost(RuntimeError):
    """The exact cycle owner no longer permits the requested operation."""


class CycleRegistryUnavailable(RuntimeError):
    """Registry state cannot support a trustworthy partial-cycle observation."""


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _text(value: Any, limit: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= limit
        and "\x00" not in value
    )


def _generation(value: Any) -> bool:
    return type(value) is int and value >= 1


def _validate_ownership(ownership: CycleOwnership) -> None:
    if not isinstance(ownership, CycleOwnership) or not (
        _uuid(ownership.cycle_id)
        and _uuid(ownership.worker_incarnation)
        and _uuid(ownership.ownership_nonce)
        and _generation(ownership.admitted_generation)
    ):
        raise ValueError("Cycle ownership identity is malformed")


def _require_postgresql(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "postgresql":
        raise CycleRegistryUnavailable("Backup cycle ownership requires PostgreSQL")


async def _database_now(session: AsyncSession) -> datetime:
    _require_postgresql(session)
    now = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise CycleRegistryUnavailable("Database clock did not return an aware timestamp")
    return now


def _observation(row: RowMapping) -> CycleObservation:
    started_at = row["started_at"]
    heartbeat_at = row["heartbeat_at"]
    lease_expires_at = row["lease_expires_at"]
    if not (
        _uuid(row["id"])
        and _uuid(row["worker_incarnation"])
        and _generation(row["admitted_generation"])
        and row["state"] in ("active", "unresolved")
        and _text(row["phase"], 80)
        and (row["job_id"] is None or _uuid(row["job_id"]))
        and all(
            isinstance(value, datetime) and value.utcoffset() is not None
            for value in (started_at, heartbeat_at, lease_expires_at)
        )
    ):
        raise CycleRegistryUnavailable("Backup cycle registry row is malformed")
    if lease_expires_at < heartbeat_at or (
        row["state"] == "active" and row["unresolved_reason"] is not None
    ) or (
        row["state"] == "unresolved" and not _text(row["unresolved_reason"], 160)
    ):
        raise CycleRegistryUnavailable("Backup cycle registry row is inconsistent")
    return CycleObservation(
        cycle_id=row["id"],
        worker_incarnation=row["worker_incarnation"],
        admitted_generation=row["admitted_generation"],
        state=row["state"],
        phase=row["phase"],
        job_id=row["job_id"],
        started_at=started_at,
        heartbeat_at=heartbeat_at,
        lease_expires_at=lease_expires_at,
        unresolved_reason=row["unresolved_reason"],
    )


def _owned_conditions(table: Table, ownership: CycleOwnership) -> tuple[Any, ...]:
    return (
        table.c.id == ownership.cycle_id,
        table.c.resource_id == admission.RESOURCE_ID,
        table.c.consumer == CONSUMER,
        table.c.worker_incarnation == ownership.worker_incarnation,
        table.c.admitted_generation == ownership.admitted_generation,
        table.c.ownership_nonce == ownership.ownership_nonce,
    )


async def _locked_owned_cycle(
    session: AsyncSession, ownership: CycleOwnership
) -> RowMapping:
    _require_postgresql(session)
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    with session.no_autoflush:
        row = (
            await session.execute(
                select(table).where(*_owned_conditions(table, ownership)).with_for_update()
            )
        ).mappings().one_or_none()
    if row is None:
        raise CycleOwnershipLost("Backup cycle ownership does not match")
    _observation(row)
    return row


async def begin_backup_cycle(
    *,
    worker_incarnation: str,
    phase: str = "run_once",
    session_factory: SessionFactory = SessionLocal,
) -> CycleOwnership:
    """Commit shared admission and durable ownership before any cycle I/O."""
    if not _uuid(worker_incarnation):
        raise ValueError("worker_incarnation must be a canonical UUID")
    if not _text(phase, 80):
        raise ValueError("phase must be nonblank and at most 80 characters")
    async with session_factory() as session:
        async with session.begin():
            authority = await admission.require_admission_open(
                session, required_scope=CONSUMER
            )
            now = await _database_now(session)
            ownership = CycleOwnership(
                cycle_id=str(uuid4()),
                worker_incarnation=worker_incarnation,
                admitted_generation=authority.generation,
                ownership_nonce=str(uuid4()),
            )
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            await session.execute(
                insert(table).values(
                    id=ownership.cycle_id,
                    resource_id=admission.RESOURCE_ID,
                    consumer=CONSUMER,
                    worker_incarnation=ownership.worker_incarnation,
                    admitted_generation=ownership.admitted_generation,
                    ownership_nonce=ownership.ownership_nonce,
                    state="active",
                    phase=phase,
                    job_id=None,
                    started_at=now,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=CYCLE_LEASE_SECONDS),
                    unresolved_reason=None,
                )
            )
        # No ownership capability leaves this method until commit succeeds.
        return ownership


async def heartbeat_backup_cycle(
    ownership: CycleOwnership,
    *,
    phase: str | None = None,
    job_id: str | None = None,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Observe the same owner; never clear unresolved state or transfer a lease."""
    _validate_ownership(ownership)
    if phase is not None and not _text(phase, 80):
        raise ValueError("phase must be nonblank and at most 80 characters")
    if job_id is not None and not _uuid(job_id):
        raise ValueError("job_id must be a canonical UUID")
    async with session_factory() as session:
        async with session.begin():
            await _locked_owned_cycle(session, ownership)
            now = await _database_now(session)
            values: dict[str, Any] = {
                "heartbeat_at": now,
                "lease_expires_at": now + timedelta(seconds=CYCLE_LEASE_SECONDS),
            }
            if phase is not None:
                values["phase"] = phase
            if job_id is not None:
                values["job_id"] = job_id
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            changed = await session.execute(
                update(table)
                .where(*_owned_conditions(table, ownership))
                .values(**values)
                .returning(table.c.id)
            )
            if changed.scalar_one_or_none() != ownership.cycle_id:
                raise CycleOwnershipLost("Backup cycle heartbeat lost ownership")


async def mark_backup_cycle_unresolved(
    ownership: CycleOwnership,
    *,
    reason: str,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Retain an ambiguous cycle as a durable reconciliation blocker."""
    _validate_ownership(ownership)
    if not _text(reason, 160):
        raise ValueError("reason must be nonblank and at most 160 characters")
    async with session_factory() as session:
        async with session.begin():
            await _locked_owned_cycle(session, ownership)
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            changed = await session.execute(
                update(table)
                .where(*_owned_conditions(table, ownership))
                .values(state="unresolved", unresolved_reason=reason)
                .returning(table.c.id)
            )
            if changed.scalar_one_or_none() != ownership.cycle_id:
                raise CycleOwnershipLost("Backup cycle uncertainty lost ownership")


async def finish_backup_cycle(
    ownership: CycleOwnership,
    *,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Delete one exact active owner only after its work and cleanup have settled.

    The caller must not use this as unconditional finally cleanup. Cancellation,
    failed work, or uncertain I/O retains an unresolved record. Neither current
    authority generation nor elapsed heartbeat time authorizes or forbids this
    original owner's successful completion.
    """
    _validate_ownership(ownership)
    async with session_factory() as session:
        async with session.begin():
            row = await _locked_owned_cycle(session, ownership)
            if row["state"] != "active":
                raise CycleOwnershipLost("Unresolved backup cycle requires reconciliation")
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            removed = await session.execute(
                delete(table)
                .where(*_owned_conditions(table, ownership), table.c.state == "active")
                .returning(table.c.id)
            )
            if removed.scalar_one_or_none() != ownership.cycle_id:
                raise CycleOwnershipLost("Backup cycle completion lost ownership")


async def snapshot_backup_cycles(
    session: AsyncSession, *, operation_id: str, expected_generation: int
) -> CycleSnapshot:
    """Observe every unfinished generation under the matching closed authority.

    The caller owns the transaction. No commit, expiry cleanup, or reconciliation
    occurs here. Ownership nonces are not selected or included in the snapshot.
    """
    if not _uuid(operation_id) or not _generation(expected_generation):
        raise ValueError("A canonical operation UUID and positive generation are required")
    authority = await admission.read_admission_snapshot(session, required_scope=CONSUMER)
    if (
        authority.is_open
        or authority.operation_id != operation_id
        or authority.generation != expected_generation
    ):
        raise admission.HostMaintenanceConflict("Cycle observation requires current closed authority")
    observed_at = await _database_now(session)
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    columns = [
        table.c.id,
        table.c.worker_incarnation,
        table.c.admitted_generation,
        table.c.state,
        table.c.phase,
        table.c.job_id,
        table.c.started_at,
        table.c.heartbeat_at,
        table.c.lease_expires_at,
        table.c.unresolved_reason,
    ]
    with session.no_autoflush:
        rows = (
            await session.execute(
                select(*columns)
                .where(
                    table.c.resource_id == admission.RESOURCE_ID,
                    table.c.consumer == CONSUMER,
                )
                .order_by(table.c.started_at, table.c.id)
            )
        ).mappings().all()
    cycles = tuple(_observation(row) for row in rows)
    if any(cycle.admitted_generation > authority.generation for cycle in cycles):
        raise CycleRegistryUnavailable("A cycle belongs to an unknown future generation")
    return CycleSnapshot(
        authority=authority,
        observed_at=observed_at,
        cycles=cycles,
        active_count=sum(cycle.state == "active" for cycle in cycles),
        unresolved_count=sum(cycle.state == "unresolved" for cycle in cycles),
        expired_count=sum(cycle.lease_expires_at <= observed_at for cycle in cycles),
    )
