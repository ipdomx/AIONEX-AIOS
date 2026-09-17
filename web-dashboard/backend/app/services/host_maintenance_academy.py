"""Durable, partial ownership of academy course-package builds.

Claims register in the caller's transaction before I/O. Deadline expiry is only
an observation: it never permits adoption, requeue, or deletion. Completion
requires an exact active owner and an already committed terminal package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, cast as sql_cast, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import SessionLocal
from app.db.models import AcademyCoursePackage, HostMaintenanceWorkCycle
from app.services.host_maintenance_admission import (
    RESOURCE_ID,
    HostMaintenanceConflict,
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
    SessionFactory,
    read_admission_snapshot,
    require_admission_open,
)

CONSUMER = "academy_course_packages"
ACTIVITY_LEASE_SECONDS = 120
TERMINAL_STATUSES = frozenset({"review_pending", "approved", "rejected", "failed"})
KNOWN_STATUSES = TERMINAL_STATUSES | {"queued", "building"}
_NULL_PROVENANCE = (
    "error_code", "error_message", "completed_at", "reviewed_at", "reviewed_by_id",
    "site_relpath", "archive_relpath", "archive_sha256", "manifest_sha256",
)
_PACKAGE_COLUMNS = (
    "id", "status", *_NULL_PROVENANCE, "archive_bytes", "curriculum", "review",
)


@dataclass(frozen=True, slots=True)
class AcademyActivityOwnership:
    activity_id: str
    package_id: str
    worker_incarnation: str
    admitted_generation: int
    ownership_nonce: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AcademyActivityObservation:
    activity_id: str
    package_id: str
    worker_incarnation: str
    admitted_generation: int
    state: str
    phase: str
    started_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime
    unresolved_reason: str | None


@dataclass(frozen=True, slots=True)
class AcademyActivitySnapshot:
    """Partial family evidence; a clear registry is never full-host closure."""

    authority: HostMaintenanceSnapshot
    observed_at: datetime
    activities: tuple[AcademyActivityObservation, ...]
    active_count: int
    unresolved_count: int
    expired_count: int
    unowned_building_ids: tuple[str, ...]
    unknown_status_ids: tuple[str, ...]
    nonpristine_queued_ids: tuple[str, ...]
    frozen_queued_ids: tuple[str, ...]
    scope: str = CONSUMER
    coverage_unverified: bool = True
    full_host_closure: bool = False

    @property
    def unfinished_count(self) -> int:
        return len(self.activities)

    @property
    def blocker_count(self) -> int:
        return len(
            {activity.package_id for activity in self.activities}
            | set(self.unowned_building_ids)
            | set(self.unknown_status_ids)
            | set(self.nonpristine_queued_ids)
        )

    @property
    def is_clear(self) -> bool:
        """Observe no known family blocker; deployment coverage stays unverified."""
        return self.blocker_count == 0


class AcademyActivityOwnershipLost(RuntimeError):
    """The exact activity owner or package state no longer permits this action."""


class AcademyActivityRegistryUnavailable(RuntimeError):
    """Durable activity evidence is unavailable or malformed."""


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _generation(value: Any) -> bool:
    return type(value) is int and value > 0


def _text(value: Any, limit: int) -> bool:
    return (
        isinstance(value, str) and bool(value.strip())
        and len(value) <= limit and "\x00" not in value
    )


def _validate_ownership(ownership: AcademyActivityOwnership) -> None:
    if not isinstance(ownership, AcademyActivityOwnership) or not (
        _uuid(ownership.activity_id) and _uuid(ownership.package_id)
        and _uuid(ownership.worker_incarnation) and _uuid(ownership.ownership_nonce)
        and _generation(ownership.admitted_generation)
    ):
        raise ValueError("Academy activity ownership is malformed")


async def require_academy_admission(session: AsyncSession) -> HostMaintenanceSnapshot:
    """Read shared admission in this transaction; sanitize only its DB failure."""
    try:
        return await require_admission_open(session, required_scope=CONSUMER)
    except SQLAlchemyError:
        raise HostMaintenanceUnavailable(
            "Academy package admission is currently unavailable"
        ) from None


def is_pristine_queued_package(package: AcademyCoursePackage | RowMapping) -> bool:
    """Match newly produced queue entries, never formerly building provenance.

    Lesson count, citations and request payload are legitimate producer input.
    Generated curriculum, review changes, result paths and error/completion
    provenance disqualify a queued record, regardless of its age.
    """
    if isinstance(package, AcademyCoursePackage):
        values = {name: getattr(package, name) for name in _PACKAGE_COLUMNS}
    else:
        values = {name: package[name] for name in _PACKAGE_COLUMNS}
    review = values["review"]
    pending_review = (
        isinstance(review, dict)
        and set(review) == {"status", "approved"}
        and review["status"] == "pending"
        and review["approved"] is False
    )
    return (
        values["status"] == "queued"
        and all(values[name] is None for name in _NULL_PROVENANCE)
        and type(values["archive_bytes"]) is int and values["archive_bytes"] == 0
        and isinstance(values["curriculum"], dict) and not values["curriculum"]
        and isinstance(review, dict) and (not review or pending_review)
    )


def pristine_queued_package_conditions(
    table: Table,
) -> tuple[ColumnElement[bool], ...]:
    """SQL counterpart used before SKIP LOCKED selection to avoid starvation."""
    return (
        table.c.status == "queued",
        *(table.c[name].is_(None) for name in _NULL_PROVENANCE),
        table.c.archive_bytes == 0,
        sql_cast(table.c.curriculum, JSONB) == {},
        or_(
            sql_cast(table.c.review, JSONB) == {},
            sql_cast(table.c.review, JSONB) == {"status": "pending", "approved": False},
        ),
    )


async def _database_now(session: AsyncSession) -> datetime:
    if session.get_bind().dialect.name != "postgresql":
        raise AcademyActivityRegistryUnavailable("Academy activity requires PostgreSQL")
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise AcademyActivityRegistryUnavailable("Database clock is not timezone-aware")
    return value


def _owned_conditions(
    table: Table, ownership: AcademyActivityOwnership
) -> tuple[Any, ...]:
    return (
        table.c.id == ownership.activity_id,
        table.c.resource_id == RESOURCE_ID,
        table.c.consumer == CONSUMER,
        table.c.job_id == ownership.package_id,
        table.c.worker_incarnation == ownership.worker_incarnation,
        table.c.admitted_generation == ownership.admitted_generation,
        table.c.ownership_nonce == ownership.ownership_nonce,
    )


def _observation(row: RowMapping) -> AcademyActivityObservation:
    times = (row["started_at"], row["heartbeat_at"], row["lease_expires_at"])
    if not (
        row["resource_id"] == RESOURCE_ID
        and _uuid(row["id"]) and _uuid(row["job_id"])
        and _uuid(row["worker_incarnation"]) and _generation(row["admitted_generation"])
        and row["state"] in {"active", "unresolved"} and _text(row["phase"], 80)
        and all(isinstance(value, datetime) and value.utcoffset() is not None for value in times)
    ):
        raise AcademyActivityRegistryUnavailable("Academy activity row is malformed")
    if (
        row["lease_expires_at"] < row["heartbeat_at"]
        or (row["state"] == "active" and row["unresolved_reason"] is not None)
        or (row["state"] == "unresolved" and not _text(row["unresolved_reason"], 160))
    ):
        raise AcademyActivityRegistryUnavailable("Academy activity row is inconsistent")
    return AcademyActivityObservation(
        activity_id=row["id"], package_id=row["job_id"],
        worker_incarnation=row["worker_incarnation"],
        admitted_generation=row["admitted_generation"], state=row["state"],
        phase=row["phase"], started_at=times[0], heartbeat_at=times[1],
        lease_expires_at=times[2], unresolved_reason=row["unresolved_reason"],
    )


async def _locked_package(session: AsyncSession, package_id: str) -> RowMapping:
    table = cast(Table, AcademyCoursePackage.__table__)
    with session.no_autoflush:
        row = (
            await session.execute(
                select(*(table.c[name] for name in _PACKAGE_COLUMNS))
                .where(table.c.id == package_id).with_for_update()
            )
        ).mappings().one_or_none()
    if row is None:
        raise AcademyActivityOwnershipLost("Academy package is missing")
    return row


async def _locked_activity(
    session: AsyncSession, ownership: AcademyActivityOwnership
) -> RowMapping:
    if session.get_bind().dialect.name != "postgresql":
        raise AcademyActivityRegistryUnavailable("Academy activity requires PostgreSQL")
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    with session.no_autoflush:
        row = (
            await session.execute(
                select(table).where(*_owned_conditions(table, ownership)).with_for_update()
            )
        ).mappings().one_or_none()
    if row is None:
        raise AcademyActivityOwnershipLost("Academy activity ownership does not match")
    _observation(row)
    return row


async def register_academy_activity(
    session: AsyncSession, *, package_id: str, worker_incarnation: str
) -> AcademyActivityOwnership:
    """Insert ownership without commit; caller publishes building in this TX.

    The caller takes admission before its package selection lock. This method
    revalidates that same authority and pristine package under fresh row locks.
    No capability may be used for I/O until the caller's commit succeeds.
    """
    if not _uuid(package_id) or not _uuid(worker_incarnation):
        raise ValueError("Package and worker incarnation must be canonical UUIDs")
    authority = await require_academy_admission(session)
    package = await _locked_package(session, package_id)
    if not is_pristine_queued_package(package):
        raise AcademyActivityOwnershipLost("Academy package is not pristine queued work")
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    prior = await session.scalar(
        select(table.c.id).where(table.c.consumer == CONSUMER, table.c.job_id == package_id)
    )
    if prior is not None:
        raise AcademyActivityOwnershipLost("Academy package already has unfinished activity")
    now = await _database_now(session)
    ownership = AcademyActivityOwnership(
        activity_id=str(uuid4()), package_id=package_id,
        worker_incarnation=worker_incarnation, admitted_generation=authority.generation,
        ownership_nonce=str(uuid4()),
    )
    await session.execute(
        insert(table).values(
            id=ownership.activity_id, resource_id=RESOURCE_ID, consumer=CONSUMER,
            worker_incarnation=ownership.worker_incarnation,
            admitted_generation=ownership.admitted_generation,
            ownership_nonce=ownership.ownership_nonce, state="active", phase="claimed",
            job_id=package_id, started_at=now, heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=ACTIVITY_LEASE_SECONDS),
            unresolved_reason=None,
        )
    )
    return ownership


async def require_owned_academy_activity(
    session: AsyncSession, ownership: AcademyActivityOwnership
) -> None:
    """Fence business updates with package -> activity locks; never commit."""
    _validate_ownership(ownership)
    package = await _locked_package(session, ownership.package_id)
    activity = await _locked_activity(session, ownership)
    if package["status"] != "building" or activity["state"] != "active":
        raise AcademyActivityOwnershipLost("Academy activity cannot publish this package")


async def heartbeat_academy_activity(
    ownership: AcademyActivityOwnership, *, phase: str | None = None,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Refresh only the exact active owner; expiry never permits takeover."""
    _validate_ownership(ownership)
    if phase is not None and not _text(phase, 80):
        raise ValueError("Academy phase must be nonblank and at most 80 characters")
    async with session_factory() as session:
        async with session.begin():
            row = await _locked_activity(session, ownership)
            if row["state"] != "active":
                raise AcademyActivityOwnershipLost("Unresolved academy activity cannot resume")
            now = await _database_now(session)
            values: dict[str, Any] = {
                "heartbeat_at": now,
                "lease_expires_at": now + timedelta(seconds=ACTIVITY_LEASE_SECONDS),
            }
            if phase is not None:
                values["phase"] = phase
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            changed = await session.execute(
                update(table).where(*_owned_conditions(table, ownership))
                .values(**values).returning(table.c.id)
            )
            if changed.scalar_one_or_none() != ownership.activity_id:
                raise AcademyActivityOwnershipLost("Academy activity heartbeat lost ownership")


async def mark_academy_activity_unresolved(
    ownership: AcademyActivityOwnership, *, reason: str,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Retain the exact owner's first uncertainty even when its package is gone."""
    _validate_ownership(ownership)
    if not _text(reason, 160):
        raise ValueError("Academy uncertainty reason must be nonblank and at most 160 characters")
    async with session_factory() as session:
        async with session.begin():
            row = await _locked_activity(session, ownership)
            if row["state"] == "unresolved":
                return
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            changed = await session.execute(
                update(table).where(*_owned_conditions(table, ownership))
                .values(state="unresolved", unresolved_reason=reason).returning(table.c.id)
            )
            if changed.scalar_one_or_none() != ownership.activity_id:
                raise AcademyActivityOwnershipLost("Academy uncertainty lost ownership")


async def finish_academy_activity(
    ownership: AcademyActivityOwnership, *,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Release one exact active owner after terminal commit and settled I/O.

    The separate transaction verifies the already published terminal status.
    This is not unconditional finally cleanup and never resolves uncertainty.
    """
    _validate_ownership(ownership)
    async with session_factory() as session:
        async with session.begin():
            package = await _locked_package(session, ownership.package_id)
            activity = await _locked_activity(session, ownership)
            if package["status"] not in TERMINAL_STATUSES or activity["state"] != "active":
                raise AcademyActivityOwnershipLost("Academy completion is not confirmed terminal work")
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            removed = await session.execute(
                delete(table).where(
                    *_owned_conditions(table, ownership), table.c.state == "active",
                ).returning(table.c.id)
            )
            if removed.scalar_one_or_none() != ownership.activity_id:
                raise AcademyActivityOwnershipLost("Academy completion lost ownership")


async def snapshot_academy_activities(
    session: AsyncSession, *, operation_id: str, expected_generation: int
) -> AcademyActivitySnapshot:
    """Observe all generations and legacy blockers under current closed authority.

    Registry is read before packages. Since new claims are closed and deletion
    follows confirmed terminal publication, concurrent completion can overcount
    unfinished work but cannot hide building work. No ownership nonce is read.
    """
    if not _uuid(operation_id) or not _generation(expected_generation):
        raise ValueError("A canonical operation UUID and positive generation are required")
    authority = await read_admission_snapshot(session, required_scope=CONSUMER)
    if (
        authority.is_open or authority.operation_id != operation_id
        or authority.generation != expected_generation
    ):
        raise HostMaintenanceConflict("Academy observation requires current closed authority")
    observed_at = await _database_now(session)
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    columns = (
        "id", "resource_id", "job_id", "worker_incarnation", "admitted_generation",
        "state", "phase", "started_at", "heartbeat_at", "lease_expires_at", "unresolved_reason",
    )
    with session.no_autoflush:
        rows = (
            await session.execute(
                select(*(table.c[name] for name in columns))
                .where(table.c.consumer == CONSUMER).order_by(table.c.started_at, table.c.id)
            )
        ).mappings().all()
    activities = tuple(_observation(row) for row in rows)
    if any(item.admitted_generation > authority.generation for item in activities):
        raise AcademyActivityRegistryUnavailable("Academy activity has an unknown future generation")
    owned_packages = {item.package_id for item in activities}
    package_table = cast(Table, AcademyCoursePackage.__table__)
    with session.no_autoflush:
        packages = (
            await session.execute(
                select(*(package_table.c[name] for name in _PACKAGE_COLUMNS))
                .order_by(package_table.c.id)
            )
        ).mappings().all()
    unowned_building: list[str] = []
    unknown: list[str] = []
    nonpristine: list[str] = []
    frozen: list[str] = []
    for package in packages:
        package_id, status = package["id"], package["status"]
        if not _uuid(package_id):
            raise AcademyActivityRegistryUnavailable("Academy package identity is malformed")
        if status not in KNOWN_STATUSES:
            unknown.append(package_id)
        elif status == "building" and package_id not in owned_packages:
            unowned_building.append(package_id)
        elif status == "queued":
            if not is_pristine_queued_package(package):
                nonpristine.append(package_id)
            elif package_id not in owned_packages:
                frozen.append(package_id)
    return AcademyActivitySnapshot(
        authority=authority, observed_at=observed_at, activities=activities,
        active_count=sum(item.state == "active" for item in activities),
        unresolved_count=sum(item.state == "unresolved" for item in activities),
        expired_count=sum(item.lease_expires_at <= observed_at for item in activities),
        unowned_building_ids=tuple(unowned_building), unknown_status_ids=tuple(unknown),
        nonpristine_queued_ids=tuple(nonpristine), frozen_queued_ids=tuple(frozen),
    )
