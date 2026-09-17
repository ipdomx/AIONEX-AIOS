"""Durable partial ownership of local security-remediation preparation.

A claim atomically publishes preparing, protocol-v1 incomplete proof and an
unfinished activity. A one-time begin commits before filesystem work. Neither
age nor business status alone permits takeover, release, or a clear snapshot.
Dedicated preparation proof survives later patch/retest metadata replacement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, cast as sql_cast, delete, exists, func, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import SessionLocal
from app.db.models import HostMaintenanceWorkCycle, SecurityRemediation
from app.services.host_maintenance_admission import (
    RESOURCE_ID,
    HostMaintenanceConflict,
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
    SessionFactory,
    read_admission_snapshot,
    require_admission_open,
)

CONSUMER = "security_remediation_preparation"
PREPARATION_PROTOCOL_VERSION = 1
ACTIVITY_LEASE_SECONDS = 120
PREPARED_STATUSES = frozenset({
    "worktree_ready", "patch_ready", "regression_passed", "retest_queued",
    "retest_failed", "verified_fixed", "rejected", "cancelled",
})
KNOWN_STATUSES = PREPARED_STATUSES | {"planned", "preparing", "failed"}
_PHASES = frozenset({"claimed", "preparing", "prepared", "clean_failed"})
_OUTCOMES = frozenset({"prepared", "clean_failed"})
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COLUMNS = (
    "id", "status", "worktree_ref", "plan", "regression_result", "retest_scan_id",
    "verified_fixed_at", "preparation_protocol_version", "preparation_outcome",
)


@dataclass(frozen=True, slots=True)
class RemediationActivityOwnership:
    activity_id: str
    remediation_id: str
    worker_incarnation: str
    admitted_generation: int
    ownership_nonce: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RemediationActivityObservation:
    activity_id: str
    remediation_id: str
    worker_incarnation: str
    admitted_generation: int
    state: str
    phase: str
    started_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime
    unresolved_reason: str | None


@dataclass(frozen=True, slots=True)
class RemediationActivitySnapshot:
    """Known local-preparation evidence, never proof of full-host closure."""

    authority: HostMaintenanceSnapshot
    observed_at: datetime
    activities: tuple[RemediationActivityObservation, ...]
    active_count: int
    unresolved_count: int
    expired_count: int
    unowned_preparing_ids: tuple[str, ...]
    legacy_failed_ids: tuple[str, ...]
    unknown_status_ids: tuple[str, ...]
    nonpristine_planned_ids: tuple[str, ...]
    unresolved_preparation_ids: tuple[str, ...]
    frozen_planned_ids: tuple[str, ...]
    preserved_result_ids: tuple[str, ...]
    scope: str = CONSUMER
    coverage_unverified: bool = True
    full_host_closure: bool = False

    @property
    def unfinished_count(self) -> int:
        return len(self.activities)

    @property
    def blocker_count(self) -> int:
        return len(
            {item.remediation_id for item in self.activities}
            | set(self.unowned_preparing_ids)
            | set(self.legacy_failed_ids)
            | set(self.unknown_status_ids)
            | set(self.nonpristine_planned_ids)
            | set(self.unresolved_preparation_ids)
        )

    @property
    def is_clear(self) -> bool:
        """No known scoped blocker; deployment and other actor coverage remain unknown."""
        return self.blocker_count == 0


class RemediationActivityOwnershipLost(RuntimeError):
    """Exact activity or compatible remediation state no longer permits an action."""


class RemediationActivityRegistryUnavailable(RuntimeError):
    """Durable preparation evidence is unavailable, inconsistent, or malformed."""


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _text(value: Any, limit: int) -> bool:
    return (
        isinstance(value, str) and bool(value.strip())
        and len(value) <= limit and "\x00" not in value
    )


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _validate_ownership(ownership: RemediationActivityOwnership) -> None:
    if not isinstance(ownership, RemediationActivityOwnership) or not (
        _uuid(ownership.activity_id) and _uuid(ownership.remediation_id)
        and _uuid(ownership.worker_incarnation) and _uuid(ownership.ownership_nonce)
        and _positive(ownership.admitted_generation)
    ):
        raise ValueError("Remediation activity ownership is malformed")


def _require_postgresql(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "postgresql":
        raise RemediationActivityRegistryUnavailable("Remediation ownership requires PostgreSQL")


async def _database_now(session: AsyncSession) -> datetime:
    _require_postgresql(session)
    value = await session.scalar(select(func.clock_timestamp()))
    if not _aware(value):
        raise RemediationActivityRegistryUnavailable("Database clock is unavailable")
    return cast(datetime, value)


async def require_remediation_admission(session: AsyncSession) -> HostMaintenanceSnapshot:
    """Hold shared admission in the caller TX; sanitize only authority-read DB errors."""
    try:
        return await require_admission_open(session, required_scope=CONSUMER)
    except SQLAlchemyError:
        raise HostMaintenanceUnavailable(
            "Security remediation preparation admission is currently unavailable"
        ) from None


def is_pristine_planned_remediation(
    row: SecurityRemediation | RowMapping,
) -> bool:
    """Business plan is input; prior preparation/results are never fresh backlog."""
    if isinstance(row, SecurityRemediation):
        values = {name: getattr(row, name) for name in _COLUMNS}
    else:
        values = {name: row[name] for name in _COLUMNS}
    plan = values["plan"]
    return (
        _uuid(values["id"]) and values["status"] == "planned"
        and all(values[name] is None for name in (
            "worktree_ref", "retest_scan_id", "verified_fixed_at",
            "preparation_protocol_version", "preparation_outcome",
        ))
        and isinstance(values["regression_result"], dict)
        and values["regression_result"] == {}
        and isinstance(plan, dict)
        and type(plan.get("schema_version")) is int and plan["schema_version"] == 1
    )


def pristine_planned_remediation_conditions(table: Table) -> tuple[ColumnElement[bool], ...]:
    """Filter untouched planned work, including no activity of any generation.

    The worker must acquire shared admission BEFORE selecting/locking candidates.
    Register rechecks that same transaction; this predicate alone is not admission.
    """
    activity = cast(Table, HostMaintenanceWorkCycle.__table__).alias("remediation_activity")
    owned = exists(select(activity.c.id).where(
        activity.c.consumer == CONSUMER, activity.c.job_id == table.c.id,
    ).correlate(table))
    plan = sql_cast(table.c.plan, JSONB)
    regression = sql_cast(table.c.regression_result, JSONB)
    return (
        table.c.id.bool_op("~")(_UUID_PATTERN),
        table.c.status == "planned",
        *(table.c[name].is_(None) for name in (
            "worktree_ref", "retest_scan_id", "verified_fixed_at",
            "preparation_protocol_version", "preparation_outcome",
        )),
        func.jsonb_typeof(plan) == "object",
        func.jsonb_typeof(plan["schema_version"]) == "number",
        plan["schema_version"].astext == "1",
        func.jsonb_typeof(regression) == "object",
        regression == {},
        ~owned,
    )


def _proof(row: RowMapping) -> tuple[int | None, str | None]:
    version, outcome = row["preparation_protocol_version"], row["preparation_outcome"]
    if version is None and outcome is None:
        return None, None
    if type(version) is not int or version != PREPARATION_PROTOCOL_VERSION or (
        outcome is not None and outcome not in _OUTCOMES
    ):
        raise RemediationActivityRegistryUnavailable("Remediation preparation proof is malformed")
    return version, outcome


def _worktree_ref(remediation_id: str) -> str:
    return f"security-remediation://{remediation_id}/source"


def _preparing_ref(ownership: RemediationActivityOwnership) -> str:
    return f"preparing:{ownership.activity_id}"


def _prepared_evidence(row: RowMapping) -> bool:
    result = row["regression_result"]
    if not isinstance(result, dict) or result.get("production_modified") is not False:
        return False
    evidence = result.get("isolation")
    if not isinstance(evidence, dict):
        return False
    return all(
        type(evidence.get(name)) is int and evidence[name] >= 0 for name in ("files", "bytes")
    ) and all(
        isinstance(evidence.get(name), str) and _SHA256_PATTERN.fullmatch(evidence[name]) is not None
        for name in ("manifest_digest", "plan_digest")
    )


def _failed_evidence(row: RowMapping) -> bool:
    result = row["regression_result"]
    return (
        isinstance(result, dict) and result.get("production_modified") is False
        and _text(result.get("error_type"), 120)
    )


def _compatible_settlement(row: RowMapping, outcome: str) -> bool:
    if _proof(row) != (PREPARATION_PROTOCOL_VERSION, outcome):
        return False
    if outcome == "prepared":
        # Patch evidence legitimately replaces regression_result after publication.
        return row["status"] in PREPARED_STATUSES and row["worktree_ref"] == _worktree_ref(row["id"])
    return (
        outcome == "clean_failed" and row["status"] == "failed"
        and row["worktree_ref"] is None and _failed_evidence(row)
    )


def _observation(row: RowMapping) -> RemediationActivityObservation:
    if not (
        row["resource_id"] == RESOURCE_ID and _uuid(row["id"]) and _uuid(row["job_id"])
        and _uuid(row["worker_incarnation"]) and _positive(row["admitted_generation"])
        and row["state"] in {"active", "unresolved"} and row["phase"] in _PHASES
        and all(_aware(row[name]) for name in ("started_at", "heartbeat_at", "lease_expires_at"))
    ):
        raise RemediationActivityRegistryUnavailable("Remediation activity identity is malformed")
    if (
        row["lease_expires_at"] < row["heartbeat_at"]
        or (row["state"] == "active" and row["unresolved_reason"] is not None)
        or (row["state"] == "unresolved" and not _text(row["unresolved_reason"], 160))
    ):
        raise RemediationActivityRegistryUnavailable("Remediation activity state is inconsistent")
    return RemediationActivityObservation(
        activity_id=row["id"], remediation_id=row["job_id"],
        worker_incarnation=row["worker_incarnation"],
        admitted_generation=row["admitted_generation"], state=row["state"], phase=row["phase"],
        started_at=row["started_at"], heartbeat_at=row["heartbeat_at"],
        lease_expires_at=row["lease_expires_at"], unresolved_reason=row["unresolved_reason"],
    )


def _owned_conditions(
    table: Table, ownership: RemediationActivityOwnership,
) -> tuple[ColumnElement[bool], ...]:
    return (
        table.c.id == ownership.activity_id, table.c.resource_id == RESOURCE_ID,
        table.c.consumer == CONSUMER, table.c.job_id == ownership.remediation_id,
        table.c.worker_incarnation == ownership.worker_incarnation,
        table.c.admitted_generation == ownership.admitted_generation,
        table.c.ownership_nonce == ownership.ownership_nonce,
    )


async def _locked_remediation(session: AsyncSession, remediation_id: str) -> RowMapping:
    _require_postgresql(session)
    table = cast(Table, SecurityRemediation.__table__)
    with session.no_autoflush:
        row = (await session.execute(
            select(*(table.c[name] for name in _COLUMNS))
            .where(table.c.id == remediation_id).with_for_update()
        )).mappings().one_or_none()
    if row is None:
        raise RemediationActivityOwnershipLost("Security remediation is missing")
    _proof(row)
    return row


async def _locked_activity(
    session: AsyncSession, ownership: RemediationActivityOwnership,
) -> RowMapping:
    _require_postgresql(session)
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    with session.no_autoflush:
        row = (await session.execute(
            select(table).where(*_owned_conditions(table, ownership)).with_for_update()
        )).mappings().one_or_none()
    if row is None:
        raise RemediationActivityOwnershipLost("Remediation activity ownership does not match")
    _observation(row)
    return row


async def register_remediation_activity(
    session: AsyncSession, *, remediation_id: str, worker_incarnation: str,
) -> RemediationActivityOwnership:
    """Atomically claim pristine planned work, without commit or filesystem I/O.

    A caller selecting candidates must hold shared admission before its job lock.
    This method also takes admission before its own job lock, never the reverse.
    The returned capability is usable only after the caller confirms commit.
    """
    if not _uuid(remediation_id) or not _uuid(worker_incarnation):
        raise ValueError("Remediation and worker incarnation must be canonical UUIDs")
    authority = await require_remediation_admission(session)
    remediation = await _locked_remediation(session, remediation_id)
    if not is_pristine_planned_remediation(remediation):
        raise RemediationActivityOwnershipLost("Remediation is not untouched planned work")
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    prior = await session.scalar(select(table.c.id).where(
        table.c.consumer == CONSUMER, table.c.job_id == remediation_id,
    ))
    if prior is not None:
        raise RemediationActivityOwnershipLost("Remediation already has unfinished activity")
    now = await _database_now(session)
    ownership = RemediationActivityOwnership(
        activity_id=str(uuid4()), remediation_id=remediation_id,
        worker_incarnation=worker_incarnation, admitted_generation=authority.generation,
        ownership_nonce=str(uuid4()),
    )
    await session.execute(insert(table).values(
        id=ownership.activity_id, resource_id=RESOURCE_ID, consumer=CONSUMER,
        job_id=remediation_id, worker_incarnation=worker_incarnation,
        admitted_generation=authority.generation, ownership_nonce=ownership.ownership_nonce,
        state="active", phase="claimed", started_at=now, heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=ACTIVITY_LEASE_SECONDS), unresolved_reason=None,
    ))
    remediations = cast(Table, SecurityRemediation.__table__)
    await session.execute(update(remediations).where(
        remediations.c.id == remediation_id,
    ).values(
        status="preparing", worktree_ref=_preparing_ref(ownership),
        preparation_protocol_version=PREPARATION_PROTOCOL_VERSION,
        preparation_outcome=None, updated_at=now,
    ))
    return ownership


async def _locked_owner(
    session: AsyncSession, ownership: RemediationActivityOwnership,
) -> tuple[RowMapping, RowMapping]:
    _validate_ownership(ownership)
    remediation = await _locked_remediation(session, ownership.remediation_id)
    activity = await _locked_activity(session, ownership)
    if activity["state"] != "active":
        raise RemediationActivityOwnershipLost("Unresolved remediation cannot resume")
    return remediation, activity


def _require_preparing(
    remediation: RowMapping, activity: RowMapping,
    ownership: RemediationActivityOwnership, *, phase: str,
) -> None:
    if (
        activity["phase"] != phase or remediation["status"] != "preparing"
        or remediation["worktree_ref"] != _preparing_ref(ownership)
        or _proof(remediation) != (PREPARATION_PROTOCOL_VERSION, None)
    ):
        raise RemediationActivityOwnershipLost("Remediation preparation state does not match")


async def begin_remediation_preparation(
    session: AsyncSession, ownership: RemediationActivityOwnership,
) -> None:
    """Consume one committed claim once; caller confirms commit before actual copy."""
    remediation, activity = await _locked_owner(session, ownership)
    _require_preparing(remediation, activity, ownership, phase="claimed")
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    changed = await session.execute(update(table).where(
        *_owned_conditions(table, ownership), table.c.state == "active", table.c.phase == "claimed",
    ).values(phase="preparing").returning(table.c.id))
    if changed.scalar_one_or_none() != ownership.activity_id:
        raise RemediationActivityOwnershipLost("Remediation preparation was already consumed")


async def require_owned_remediation_activity(
    session: AsyncSession, ownership: RemediationActivityOwnership,
) -> None:
    """Fence business mutations with remediation -> activity locks, without commit."""
    remediation, activity = await _locked_owner(session, ownership)
    _require_preparing(remediation, activity, ownership, phase="preparing")


async def settle_remediation_activity(
    session: AsyncSession, ownership: RemediationActivityOwnership, *, outcome: str,
) -> None:
    """Validate flushed business publication and store proof in the same transaction.

    Caller first fences ownership, mutates and flushes the business result, then
    calls this helper. Clean failure is allowed only after no effects or confirmed
    owned cleanup; uncertainty must retain its activity instead.
    """
    if outcome not in _OUTCOMES:
        raise ValueError("Only a confirmed preparation outcome may be settled")
    remediation, activity = await _locked_owner(session, ownership)
    if activity["phase"] != "preparing" or _proof(remediation) != (
        PREPARATION_PROTOCOL_VERSION, None
    ):
        raise RemediationActivityOwnershipLost("Remediation preparation cannot be settled")
    if outcome == "prepared":
        valid = (
            remediation["status"] == "worktree_ready"
            and remediation["worktree_ref"] == _worktree_ref(ownership.remediation_id)
            and _prepared_evidence(remediation)
        )
    else:
        valid = (
            remediation["status"] == "failed" and remediation["worktree_ref"] is None
            and _failed_evidence(remediation)
        )
    if not valid:
        raise RemediationActivityOwnershipLost("Remediation business result is not confirmed")
    table = cast(Table, SecurityRemediation.__table__)
    await session.execute(update(table).where(
        table.c.id == ownership.remediation_id,
    ).values(preparation_outcome=outcome, updated_at=await _database_now(session)))
    cycles = cast(Table, HostMaintenanceWorkCycle.__table__)
    changed = await session.execute(update(cycles).where(
        *_owned_conditions(cycles, ownership), cycles.c.state == "active",
        cycles.c.phase == "preparing",
    ).values(phase=outcome).returning(cycles.c.id))
    if changed.scalar_one_or_none() != ownership.activity_id:
        raise RemediationActivityOwnershipLost("Remediation settlement lost ownership")


async def heartbeat_remediation_activity(
    ownership: RemediationActivityOwnership, *,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Refresh exact ownership; a deadline never authorizes adoption or removal."""
    async with session_factory() as session:
        async with session.begin():
            remediation, activity = await _locked_owner(session, ownership)
            if activity["phase"] in _OUTCOMES:
                if not _compatible_settlement(remediation, activity["phase"]):
                    raise RemediationActivityOwnershipLost("Remediation settlement is inconsistent")
            else:
                _require_preparing(remediation, activity, ownership, phase=activity["phase"])
            now = await _database_now(session)
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            await session.execute(update(table).where(*_owned_conditions(table, ownership)).values(
                heartbeat_at=now, lease_expires_at=now + timedelta(seconds=ACTIVITY_LEASE_SECONDS),
            ))


async def mark_remediation_activity_unresolved(
    ownership: RemediationActivityOwnership, *, reason: str,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Persist first uncertainty even after the business row is deleted or replaced."""
    _validate_ownership(ownership)
    if not _text(reason, 160):
        raise ValueError("Remediation uncertainty reason must be nonblank and at most 160 characters")
    async with session_factory() as session:
        async with session.begin():
            row = await _locked_activity(session, ownership)
            if row["state"] == "unresolved":
                return
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            await session.execute(update(table).where(*_owned_conditions(table, ownership)).values(
                state="unresolved", unresolved_reason=reason,
            ))


async def finish_remediation_activity(
    ownership: RemediationActivityOwnership, *,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Remove exact active ownership after confirmed business commit and joined I/O."""
    async with session_factory() as session:
        async with session.begin():
            remediation, activity = await _locked_owner(session, ownership)
            if activity["phase"] not in _OUTCOMES or not _compatible_settlement(
                remediation, activity["phase"]
            ):
                raise RemediationActivityOwnershipLost("Remediation completion is not confirmed")
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            removed = await session.execute(delete(table).where(
                *_owned_conditions(table, ownership), table.c.state == "active",
                table.c.phase == activity["phase"],
            ).returning(table.c.id))
            if removed.scalar_one_or_none() != ownership.activity_id:
                raise RemediationActivityOwnershipLost("Remediation completion lost ownership")


async def read_remediation_activity_snapshot(
    session: AsyncSession, *, operation_id: str, expected_generation: int,
) -> RemediationActivitySnapshot:
    """Read every generation and independent proof under current closed admission.

    Read ownership before business rows: no new claims can start, and removal
    follows committed settlement, so concurrent completion can only overcount.
    This neither gates security scans/retests nor inventories unowned files.
    """
    if not _uuid(operation_id) or not _positive(expected_generation):
        raise ValueError("A canonical operation UUID and positive generation are required")
    authority = await read_admission_snapshot(session, required_scope=CONSUMER)
    if (
        authority.is_open or authority.operation_id != operation_id
        or authority.generation != expected_generation
    ):
        raise HostMaintenanceConflict("Remediation observation requires current closed authority")
    observed_at = await _database_now(session)
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    columns = (
        "id", "resource_id", "job_id", "worker_incarnation", "admitted_generation",
        "state", "phase", "started_at", "heartbeat_at", "lease_expires_at", "unresolved_reason",
    )
    with session.no_autoflush:
        rows = (await session.execute(
            select(*(table.c[name] for name in columns))
            .where(table.c.consumer == CONSUMER).order_by(table.c.started_at, table.c.id)
        )).mappings().all()
    activities = tuple(_observation(row) for row in rows)
    if any(item.admitted_generation > authority.generation for item in activities):
        raise RemediationActivityRegistryUnavailable("Remediation activity has a future generation")
    owned = {item.remediation_id for item in activities}
    remediations = cast(Table, SecurityRemediation.__table__)
    with session.no_autoflush:
        records = (await session.execute(
            select(*(remediations.c[name] for name in _COLUMNS)).order_by(remediations.c.id)
        )).mappings().all()
    unowned_preparing: list[str] = []
    legacy_failed: list[str] = []
    unknown: list[str] = []
    nonpristine: list[str] = []
    unresolved_proof: list[str] = []
    frozen: list[str] = []
    preserved: list[str] = []
    for remediation in records:
        remediation_id, status = remediation["id"], remediation["status"]
        if not _uuid(remediation_id):
            raise RemediationActivityRegistryUnavailable("Remediation identity is malformed")
        version, outcome = _proof(remediation)
        if status not in KNOWN_STATUSES:
            unknown.append(remediation_id)
        if status == "preparing" and remediation_id not in owned:
            unowned_preparing.append(remediation_id)
        if version == PREPARATION_PROTOCOL_VERSION:
            if outcome is None or not _compatible_settlement(remediation, outcome):
                unresolved_proof.append(remediation_id)
            elif remediation_id not in owned and outcome == "prepared":
                preserved.append(remediation_id)
        elif status == "failed":
            # The legacy worker ignored cleanup errors before publishing failed.
            legacy_failed.append(remediation_id)
        elif status in PREPARED_STATUSES:
            if remediation["worktree_ref"] == _worktree_ref(remediation_id):
                if remediation_id not in owned:
                    preserved.append(remediation_id)
            else:
                unresolved_proof.append(remediation_id)
        if status == "planned":
            if not is_pristine_planned_remediation(remediation):
                nonpristine.append(remediation_id)
            elif remediation_id not in owned:
                frozen.append(remediation_id)
    return RemediationActivitySnapshot(
        authority=authority, observed_at=observed_at, activities=activities,
        active_count=sum(item.state == "active" for item in activities),
        unresolved_count=sum(item.state == "unresolved" for item in activities),
        expired_count=sum(item.lease_expires_at <= observed_at for item in activities),
        unowned_preparing_ids=tuple(unowned_preparing), legacy_failed_ids=tuple(legacy_failed),
        unknown_status_ids=tuple(unknown), nonpristine_planned_ids=tuple(nonpristine),
        unresolved_preparation_ids=tuple(unresolved_proof), frozen_planned_ids=tuple(frozen),
        preserved_result_ids=tuple(preserved),
    )
