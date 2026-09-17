"""Durable admission authority with explicitly versioned partial coverage.

Legacy schema 1 covers project execution claims and lease reaping. Schema 2 also
covers backup worker cycles and their guarded enqueue APIs. Schema 3 adds
academy course-package production and owned builds. Schema 4 adds owned external
notification dispatch, without guarding generic notification creation or realtime.
Coverage remains partial;
no schema version proves deployment or full-host closure. There is no automatic
reopening.

Admission holds FOR SHARE in the caller's transaction. The caller must keep that
transaction through the protected claim and commit or roll it back afterwards.
Control transitions use separate short transactions and return only after commit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table, select, text, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import OwnerControlRecord

DOMAIN = "host-maintenance-admission"
RESOURCE_ID = "runtime-node"
SCHEMA_VERSION = 1
SCOPE = "project_execution"
COVERAGE_SCHEMA_VERSION = 2
COVERAGE_SCOPE = "project_execution+backup_cycles"
ACADEMY_SCHEMA_VERSION = 3
ACADEMY_COVERAGE_SCOPE = "project_execution+backup_cycles+academy_course_packages"
NOTIFICATION_SCHEMA_VERSION = 4
NOTIFICATION_COVERAGE_SCOPE = (
    "project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch"
)
_REQUIRED_SCOPES = frozenset(
    {"project_execution", "backup_cycles", "academy_course_packages",
     "notification_delivery_dispatch"}
)
_CONTROL_LOCK_TIMEOUT = "5s"

_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "scope",
        "generation",
        "operation_id",
        "reason",
        "changed_at",
        "full_host_closure",
    }
)
SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True, slots=True)
class HostMaintenanceSnapshot:
    """Validated immutable authority state, never a full-host drain receipt."""

    schema_version: int
    scope: str
    generation: int
    status: str
    enabled: bool
    operation_id: str | None
    reason: str
    changed_at: datetime | None
    full_host_closure: bool = False

    @property
    def is_open(self) -> bool:
        return self.status == "open" and self.enabled

    @property
    def covered_scopes(self) -> tuple[str, ...]:
        if self.schema_version == NOTIFICATION_SCHEMA_VERSION:
            return (
                "project_execution", "backup_cycles", "academy_course_packages",
                "notification_delivery_dispatch",
            )
        if self.schema_version == ACADEMY_SCHEMA_VERSION:
            return ("project_execution", "backup_cycles", "academy_course_packages")
        if self.schema_version == COVERAGE_SCHEMA_VERSION:
            return ("project_execution", "backup_cycles")
        return ("project_execution",)


class HostMaintenanceUnavailable(RuntimeError):
    """The durable authority is missing, malformed, or cannot provide row locks."""


class HostMaintenanceClosed(RuntimeError):
    """The validated authority denies admission for its covered consumers."""

    def __init__(self, snapshot: HostMaintenanceSnapshot):
        super().__init__("Maintenance admission is closed")
        self.snapshot = snapshot


class HostMaintenanceConflict(RuntimeError):
    """A control operation does not own the current authority generation."""


def _canonical_operation_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _valid_generation(value: Any) -> bool:
    return type(value) is int and value >= 1


def _valid_reason(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 500
        and "\x00" not in value
    )


def _snapshot(row: RowMapping) -> HostMaintenanceSnapshot:
    payload = row["payload"]
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        raise HostMaintenanceUnavailable("Maintenance authority payload is malformed")
    if (
        type(payload["schema_version"]) is not int
        or (payload["schema_version"], payload["scope"])
        not in (
            (SCHEMA_VERSION, SCOPE),
            (COVERAGE_SCHEMA_VERSION, COVERAGE_SCOPE),
            (ACADEMY_SCHEMA_VERSION, ACADEMY_COVERAGE_SCOPE),
            (NOTIFICATION_SCHEMA_VERSION, NOTIFICATION_COVERAGE_SCOPE),
        )
        or payload["full_host_closure"] is not False
        or not _valid_generation(payload["generation"])
        or not _valid_generation(row["version"])
        or payload["generation"] != row["version"]
        or row["status"] not in ("open", "closed")
        or type(row["enabled"]) is not bool
        or row["enabled"] != (row["status"] == "open")
        or not _valid_reason(payload["reason"])
    ):
        raise HostMaintenanceUnavailable("Maintenance authority state is inconsistent")

    generation = payload["generation"]
    operation_id = payload["operation_id"]
    changed_at = payload["changed_at"]
    if generation == 1:
        if (
            payload["schema_version"] != SCHEMA_VERSION
            or row["status"] != "open"
            or operation_id is not None
            or changed_at is not None
            or payload["reason"] != "migration-seed"
        ):
            raise HostMaintenanceUnavailable("Maintenance authority seed is malformed")
        parsed_changed_at = None
    else:
        if not _canonical_operation_id(operation_id) or not isinstance(changed_at, str):
            raise HostMaintenanceUnavailable("Maintenance authority operation is malformed")
        try:
            parsed_changed_at = datetime.fromisoformat(changed_at)
        except ValueError as exc:
            raise HostMaintenanceUnavailable(
                "Maintenance authority timestamp is malformed"
            ) from exc
        if parsed_changed_at.utcoffset() is None:
            raise HostMaintenanceUnavailable("Maintenance authority timestamp lacks timezone")

    return HostMaintenanceSnapshot(
        schema_version=payload["schema_version"],
        scope=payload["scope"],
        generation=generation,
        status=row["status"],
        enabled=row["enabled"],
        operation_id=operation_id,
        reason=payload["reason"],
        changed_at=parsed_changed_at,
    )


def _require_postgresql(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "postgresql":
        raise HostMaintenanceUnavailable("Maintenance admission requires PostgreSQL row locks")


async def _locked_snapshot(
    session: AsyncSession, *, exclusive: bool
) -> tuple[str, HostMaintenanceSnapshot]:
    _require_postgresql(session)
    table = cast(Table, OwnerControlRecord.__table__)
    statement = (
        select(
            table.c.id,
            table.c.status,
            table.c.enabled,
            table.c.payload,
            table.c.version,
        )
        .where(table.c.domain == DOMAIN, table.c.resource_id == RESOURCE_ID)
        .with_for_update(read=not exclusive)
    )
    # Select raw columns, not a cached ORM entity. Suppress autoflush so no
    # pending caller mutations run before this admission check.
    with session.no_autoflush:
        row = (await session.execute(statement)).mappings().one_or_none()
    if row is None:
        raise HostMaintenanceUnavailable("Maintenance authority has not been seeded")
    return row["id"], _snapshot(row)


async def read_admission_snapshot(
    session: AsyncSession, *, required_scope: str = "project_execution"
) -> HostMaintenanceSnapshot:
    """Lock and validate the requested coverage without requiring open state."""
    if not isinstance(required_scope, str) or required_scope not in _REQUIRED_SCOPES:
        raise ValueError("Unknown maintenance admission scope")
    _, snapshot = await _locked_snapshot(session, exclusive=False)
    if required_scope not in snapshot.covered_scopes:
        raise HostMaintenanceUnavailable("Maintenance authority does not cover this consumer")
    return snapshot


async def require_admission_open(
    session: AsyncSession, *, required_scope: str = "project_execution"
) -> HostMaintenanceSnapshot:
    """Hold shared admission until the caller commits or rolls back its claim.

    This function never commits, rolls back, seeds, or repairs authority state.
    Database errors propagate so callers cannot mistake a failed check for open.
    """
    snapshot = await read_admission_snapshot(session, required_scope=required_scope)
    if not snapshot.is_open:
        raise HostMaintenanceClosed(snapshot)
    return snapshot


async def is_admission_open(
    session: AsyncSession, *, required_scope: str = "project_execution"
) -> bool:
    """Return false only for an explicitly closed or unavailable authority."""
    try:
        await require_admission_open(session, required_scope=required_scope)
    except (HostMaintenanceClosed, HostMaintenanceUnavailable):
        return False
    return True


def _payload(snapshot: HostMaintenanceSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "scope": snapshot.scope,
        "generation": snapshot.generation,
        "operation_id": snapshot.operation_id,
        "reason": snapshot.reason,
        "changed_at": (
            snapshot.changed_at.isoformat() if snapshot.changed_at is not None else None
        ),
        "full_host_closure": False,
    }


async def _transition(
    *,
    target_status: str,
    operation_id: str,
    expected_generation: int,
    reason: str,
    session_factory: SessionFactory,
) -> HostMaintenanceSnapshot:
    if not _canonical_operation_id(operation_id):
        raise ValueError("operation_id must be a canonical UUID")
    if not _valid_generation(expected_generation):
        raise ValueError("expected_generation must be a positive integer")
    if not _valid_reason(reason):
        raise ValueError("reason must contain between 1 and 500 non-NUL characters")

    async with session_factory() as session:
        async with session.begin():
            _require_postgresql(session)
            # Bound waiting on a stuck admission holder. A timeout propagates as
            # a database error; it never reports closure or starts a retry.
            await session.execute(
                text("SELECT set_config('lock_timeout', :timeout, true)"),
                {"timeout": _CONTROL_LOCK_TIMEOUT},
            )
            row_id, current = await _locked_snapshot(session, exclusive=True)
            if current.generation != expected_generation:
                raise HostMaintenanceConflict("Maintenance authority generation has changed")
            if target_status == "open" and (
                current.is_open or current.operation_id != operation_id
            ):
                raise HostMaintenanceConflict(
                    "Reopening requires the current closed operation and generation"
                )

            changed_at = datetime.now(timezone.utc)
            result = replace(
                current,
                generation=current.generation + 1,
                status=target_status,
                enabled=target_status == "open",
                operation_id=operation_id,
                reason=reason,
                changed_at=changed_at,
            )
            table = cast(Table, OwnerControlRecord.__table__)
            changed = await session.execute(
                update(table)
                .where(table.c.id == row_id, table.c.version == expected_generation)
                .values(
                    status=result.status,
                    enabled=result.enabled,
                    version=result.generation,
                    payload=_payload(result),
                    updated_at=changed_at,
                )
                .returning(table.c.id)
            )
            if changed.scalar_one_or_none() != row_id:
                raise HostMaintenanceConflict("Maintenance authority update lost its generation")
        # Exiting begin() commits before the immutable result leaves this method.
        return result


async def close_admission(
    *,
    operation_id: str,
    expected_generation: int,
    reason: str,
    session_factory: SessionFactory = SessionLocal,
) -> HostMaintenanceSnapshot:
    """Commit closed admission at the current generation, without claiming drain.

    A new operation may supersede a prior closed operation only with its current
    generation. Every successful transition advances generation; retries with a
    stale generation fail instead of replaying or reopening anything.
    """
    return await _transition(
        target_status="closed",
        operation_id=operation_id,
        expected_generation=expected_generation,
        reason=reason,
        session_factory=session_factory,
    )


async def open_admission(
    *,
    operation_id: str,
    expected_generation: int,
    reason: str,
    session_factory: SessionFactory = SessionLocal,
) -> HostMaintenanceSnapshot:
    """Explicitly reopen only the current closed operation and generation."""
    return await _transition(
        target_status="open",
        operation_id=operation_id,
        expected_generation=expected_generation,
        reason=reason,
        session_factory=session_factory,
    )
