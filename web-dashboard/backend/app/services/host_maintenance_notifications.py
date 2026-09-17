"""Durable partial ownership of external notification dispatch.

One admission-open claim transaction creates processing, a started attempt and
unfinished ownership. The attempt UUID is also the activity UUID. A separate
one-time dispatch transition commits before provider I/O. Expiry never permits
adoption or replay, and ambiguous provider/commit results retain evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, and_, delete, exists, func, insert, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import SessionLocal
from app.db.models import (
    HostMaintenanceWorkCycle,
    NotificationDelivery,
    NotificationDeliveryAttempt,
)
from app.services.host_maintenance_admission import (
    RESOURCE_ID,
    HostMaintenanceConflict,
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
    SessionFactory,
    read_admission_snapshot,
    require_admission_open,
)

CONSUMER = "notification_delivery_dispatch"
EXTERNAL_CHANNELS = ("email", "push", "telegram", "whatsapp")
ACTIVITY_LEASE_SECONDS = 120
DISPATCH_PROTOCOL_VERSION = 1
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
SAFE_RETRY_OUTCOMES = frozenset({"no_send", "rejected"})
SETTLED_OUTCOMES = SAFE_RETRY_OUTCOMES | {"accepted"}
KNOWN_STATUSES = frozenset({
    "queued", "retrying", "processing", "delivered", "acknowledged",
    "skipped", "unconfigured", "dead_letter", "failed",
})
_PHASES = frozenset({"claimed", "dispatching", "settled"})
_NULL_PROVENANCE = (
    "provider_message_id", "error_code", "error_message", "delivered_at",
    "acknowledged_at", "dead_lettered_at", "lease_token", "lease_expires_at",
)
_DELIVERY_COLUMNS = (
    "id", "channel", "status", "attempt_count", "max_attempts", "next_attempt_at",
    *_NULL_PROVENANCE,
)
_ATTEMPT_COLUMNS = (
    "id", "delivery_id", "attempt_number", "status", "dispatch_protocol_version",
    "dispatch_outcome", "started_at", "completed_at", "provider_message_id",
)


@dataclass(frozen=True, slots=True)
class NotificationActivityOwnership:
    activity_id: str
    delivery_id: str
    attempt_number: int
    worker_incarnation: str
    admitted_generation: int
    ownership_nonce: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class NotificationActivityObservation:
    activity_id: str
    delivery_id: str
    worker_incarnation: str
    admitted_generation: int
    state: str
    phase: str
    started_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime
    unresolved_reason: str | None


@dataclass(frozen=True, slots=True)
class NotificationAttemptObservation:
    attempt_id: str
    delivery_id: str
    attempt_number: int
    protocol_version: int | None
    outcome: str | None
    status: str
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationActivitySnapshot:
    """Known family evidence; neither deployment proof nor full-host closure."""

    authority: HostMaintenanceSnapshot
    observed_at: datetime
    activities: tuple[NotificationActivityObservation, ...]
    active_count: int
    unresolved_count: int
    expired_count: int
    unresolved_attempts: tuple[NotificationAttemptObservation, ...]
    unowned_processing_ids: tuple[str, ...]
    unknown_status_ids: tuple[str, ...]
    nonpristine_queued_ids: tuple[str, ...]
    frozen_queued_ids: tuple[str, ...]
    frozen_retrying_ids: tuple[str, ...]
    scope: str = CONSUMER
    coverage_unverified: bool = True
    full_host_closure: bool = False

    @property
    def unfinished_count(self) -> int:
        return len(self.activities)

    @property
    def unresolved_attempt_count(self) -> int:
        return len(self.unresolved_attempts)

    @property
    def blocker_count(self) -> int:
        return len(
            {item.delivery_id for item in self.activities}
            | {item.delivery_id for item in self.unresolved_attempts}
            | set(self.unowned_processing_ids)
            | set(self.unknown_status_ids)
            | set(self.nonpristine_queued_ids)
        )

    @property
    def is_clear(self) -> bool:
        """Observe no known scoped blocker; uninstrumented coverage is unknown."""
        return self.blocker_count == 0


class NotificationActivityOwnershipLost(RuntimeError):
    """Exact ownership or delivery/attempt state no longer permits this action."""


class NotificationActivityRegistryUnavailable(RuntimeError):
    """Durable dispatch evidence is unavailable or malformed."""


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


def _validate_ownership(ownership: NotificationActivityOwnership) -> None:
    if not isinstance(ownership, NotificationActivityOwnership) or not (
        _uuid(ownership.activity_id) and _uuid(ownership.delivery_id)
        and _uuid(ownership.worker_incarnation) and _uuid(ownership.ownership_nonce)
        and _positive(ownership.admitted_generation) and _positive(ownership.attempt_number)
    ):
        raise ValueError("Notification activity ownership is malformed")


def _require_postgresql(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "postgresql":
        raise NotificationActivityRegistryUnavailable("Notification ownership requires PostgreSQL")


async def _database_now(session: AsyncSession) -> datetime:
    _require_postgresql(session)
    value = await session.scalar(select(func.clock_timestamp()))
    if not _aware(value):
        raise NotificationActivityRegistryUnavailable("Database clock is unavailable")
    return cast(datetime, value)


async def require_notification_admission(session: AsyncSession) -> HostMaintenanceSnapshot:
    """Read shared admission in the caller's transaction, without committing."""
    try:
        return await require_admission_open(session, required_scope=CONSUMER)
    except SQLAlchemyError:
        raise HostMaintenanceUnavailable(
            "Notification dispatch admission is currently unavailable"
        ) from None


def _safe_attempt_sql(attempt: Any) -> ColumnElement[bool]:
    return and_(
        attempt.c.dispatch_protocol_version == DISPATCH_PROTOCOL_VERSION,
        attempt.c.id.bool_op("~")(_UUID_PATTERN),
        attempt.c.delivery_id.bool_op("~")(_UUID_PATTERN),
        attempt.c.provider_message_id.is_(None),
        attempt.c.completed_at.is_not(None),
        attempt.c.completed_at >= attempt.c.started_at,
        or_(
            and_(attempt.c.dispatch_outcome == "no_send",
                 attempt.c.status.in_(("failed", "unconfigured"))),
            and_(attempt.c.dispatch_outcome == "rejected", attempt.c.status == "failed"),
        ),
    )


def eligible_notification_delivery_conditions(table: Table) -> tuple[ColumnElement[bool], ...]:
    """Candidate filter and locked recheck share identical conservative history.

    Due time and ordering belong to the worker. This filter never grants a lease
    takeover, even for queued rows changed by a manual retry endpoint.
    """
    attempt = cast(Table, NotificationDeliveryAttempt.__table__).alias("dispatch_history")
    activity = cast(Table, HostMaintenanceWorkCycle.__table__).alias("dispatch_activity")
    count = select(func.count()).select_from(attempt).where(
        attempt.c.delivery_id == table.c.id
    ).correlate(table).scalar_subquery()
    distinct_numbers = select(func.count(func.distinct(attempt.c.attempt_number))).where(
        attempt.c.delivery_id == table.c.id
    ).correlate(table).scalar_subquery()
    bad = exists(select(attempt.c.id).where(
        attempt.c.delivery_id == table.c.id,
        or_(
            _safe_attempt_sql(attempt).is_not(True),
            attempt.c.attempt_number <= 0,
            attempt.c.attempt_number > table.c.attempt_count,
        ),
    ).correlate(table))
    owned = exists(select(activity.c.id).where(
        activity.c.consumer == CONSUMER, activity.c.job_id == table.c.id,
    ).correlate(table))
    never_started = and_(
        table.c.status == "queued", table.c.attempt_count == 0,
        *(table.c[name].is_(None) for name in _NULL_PROVENANCE),
    )
    safe_retry = and_(
        table.c.attempt_count > 0, ~bad,
        *(table.c[name].is_(None) for name in (
            "provider_message_id", "delivered_at", "acknowledged_at",
            "dead_lettered_at", "lease_token", "lease_expires_at",
        )),
    )
    return (
        table.c.id.bool_op("~")(_UUID_PATTERN),
        table.c.channel.in_(EXTERNAL_CHANNELS),
        table.c.status.in_(("queued", "retrying")),
        table.c.attempt_count >= 0,
        table.c.max_attempts > 0,
        count == table.c.attempt_count,
        distinct_numbers == table.c.attempt_count,
        ~owned,
        or_(never_started, safe_retry),
    )


def _attempt_observation(row: RowMapping) -> NotificationAttemptObservation:
    if not (
        _uuid(row["id"]) and _uuid(row["delivery_id"]) and _positive(row["attempt_number"])
        and _text(row["status"], 32) and _aware(row["started_at"])
        and (row["completed_at"] is None or _aware(row["completed_at"]))
        and (row["dispatch_protocol_version"] is None
             or _positive(row["dispatch_protocol_version"]))
        and (row["dispatch_outcome"] is None or _text(row["dispatch_outcome"], 32))
    ):
        raise NotificationActivityRegistryUnavailable("Notification attempt identity is malformed")
    # Never discard contradictory provider-acceptance provenance before building
    # the public observation. Its sanitized shape intentionally omits provider IDs.
    provider_id = row["provider_message_id"]
    if (
        provider_id is not None and not _text(provider_id, 255)
    ) or (
        row["dispatch_protocol_version"] == DISPATCH_PROTOCOL_VERSION
        and row["dispatch_outcome"] != "accepted" and provider_id is not None
    ):
        raise NotificationActivityRegistryUnavailable(
            "Notification attempt provider provenance is inconsistent"
        )
    return NotificationAttemptObservation(
        attempt_id=row["id"], delivery_id=row["delivery_id"],
        attempt_number=row["attempt_number"], protocol_version=row["dispatch_protocol_version"],
        outcome=row["dispatch_outcome"], status=row["status"],
        started_at=row["started_at"], completed_at=row["completed_at"],
    )


def _settled_attempt(attempt: NotificationAttemptObservation) -> bool:
    if (
        attempt.protocol_version != DISPATCH_PROTOCOL_VERSION
        or attempt.completed_at is None or attempt.completed_at < attempt.started_at
    ):
        return False
    return (
        (attempt.outcome == "accepted" and attempt.status == "delivered")
        or (attempt.outcome == "no_send" and attempt.status in {"unconfigured", "failed"})
        or (attempt.outcome == "rejected" and attempt.status == "failed")
    )


def _compatible_settlement(delivery: RowMapping, attempt: RowMapping) -> bool:
    proof = _attempt_observation(attempt)
    if not _settled_attempt(proof) or (
        delivery["lease_token"] is not None or delivery["lease_expires_at"] is not None
    ):
        return False
    if proof.outcome == "accepted":
        return (
            delivery["status"] in {"delivered", "acknowledged"}
            and _aware(delivery["delivered_at"])
            and delivery["provider_message_id"] == attempt["provider_message_id"]
            and delivery["error_code"] is None and delivery["error_message"] is None
            and delivery["dead_lettered_at"] is None
            and (delivery["status"] != "acknowledged" or _aware(delivery["acknowledged_at"]))
        )
    return (
        delivery["status"] in {"retrying", "unconfigured", "dead_letter", "failed", "queued"}
        and all(delivery[name] is None for name in (
            "provider_message_id", "delivered_at", "acknowledged_at",
        ))
        and (delivery["status"] == "dead_letter" or delivery["dead_lettered_at"] is None)
        and (delivery["status"] != "dead_letter" or _aware(delivery["dead_lettered_at"]))
    )


def _legacy_accepted(attempt: NotificationAttemptObservation) -> bool:
    return (
        attempt.protocol_version is None and attempt.outcome is None
        and attempt.status == "delivered" and attempt.completed_at is not None
        and attempt.completed_at >= attempt.started_at
    )


def _eligible(
    delivery: RowMapping, attempts: tuple[NotificationAttemptObservation, ...], owned: bool
) -> bool:
    count = delivery["attempt_count"]
    if (
        owned or delivery["channel"] not in EXTERNAL_CHANNELS
        or delivery["status"] not in {"queued", "retrying"}
        or type(count) is not int or count < 0 or not _positive(delivery["max_attempts"])
        or len(attempts) != count
        or {item.attempt_number for item in attempts} != set(range(1, count + 1))
    ):
        return False
    if count == 0:
        return delivery["status"] == "queued" and all(
            delivery[name] is None for name in _NULL_PROVENANCE
        )
    return all(
        _settled_attempt(item) and item.outcome in SAFE_RETRY_OUTCOMES for item in attempts
    ) and all(
        delivery[name] is None for name in (
            "provider_message_id", "delivered_at", "acknowledged_at",
            "dead_lettered_at", "lease_token", "lease_expires_at",
        )
    )


def _observation(row: RowMapping) -> NotificationActivityObservation:
    if not (
        row["resource_id"] == RESOURCE_ID and _uuid(row["id"]) and _uuid(row["job_id"])
        and _uuid(row["worker_incarnation"]) and _positive(row["admitted_generation"])
        and row["state"] in {"active", "unresolved"} and row["phase"] in _PHASES
        and all(_aware(row[name]) for name in (
            "started_at", "heartbeat_at", "lease_expires_at",
        ))
    ):
        raise NotificationActivityRegistryUnavailable("Notification activity identity is malformed")
    if (
        row["lease_expires_at"] < row["heartbeat_at"]
        or (row["state"] == "active" and row["unresolved_reason"] is not None)
        or (row["state"] == "unresolved" and not _text(row["unresolved_reason"], 160))
    ):
        raise NotificationActivityRegistryUnavailable("Notification activity state is inconsistent")
    return NotificationActivityObservation(
        activity_id=row["id"], delivery_id=row["job_id"],
        worker_incarnation=row["worker_incarnation"],
        admitted_generation=row["admitted_generation"], state=row["state"], phase=row["phase"],
        started_at=row["started_at"], heartbeat_at=row["heartbeat_at"],
        lease_expires_at=row["lease_expires_at"], unresolved_reason=row["unresolved_reason"],
    )


def _owned_conditions(
    table: Table, ownership: NotificationActivityOwnership
) -> tuple[ColumnElement[bool], ...]:
    return (
        table.c.id == ownership.activity_id, table.c.resource_id == RESOURCE_ID,
        table.c.consumer == CONSUMER, table.c.job_id == ownership.delivery_id,
        table.c.worker_incarnation == ownership.worker_incarnation,
        table.c.admitted_generation == ownership.admitted_generation,
        table.c.ownership_nonce == ownership.ownership_nonce,
    )


async def _locked_delivery(
    session: AsyncSession, delivery_id: str, *, optional: bool = False
) -> RowMapping | None:
    _require_postgresql(session)
    table = cast(Table, NotificationDelivery.__table__)
    with session.no_autoflush:
        row = (await session.execute(
            select(*(table.c[name] for name in _DELIVERY_COLUMNS))
            .where(table.c.id == delivery_id).with_for_update()
        )).mappings().one_or_none()
    if row is None and not optional:
        raise NotificationActivityOwnershipLost("Notification delivery is missing")
    return row


async def _locked_activity(
    session: AsyncSession, ownership: NotificationActivityOwnership
) -> RowMapping:
    _require_postgresql(session)
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    with session.no_autoflush:
        row = (await session.execute(
            select(table).where(*_owned_conditions(table, ownership)).with_for_update()
        )).mappings().one_or_none()
    if row is None:
        raise NotificationActivityOwnershipLost("Notification activity ownership does not match")
    _observation(row)
    return row


async def _locked_attempt(
    session: AsyncSession, ownership: NotificationActivityOwnership, *, optional: bool = False
) -> RowMapping | None:
    table = cast(Table, NotificationDeliveryAttempt.__table__)
    with session.no_autoflush:
        row = (await session.execute(
            select(*(table.c[name] for name in _ATTEMPT_COLUMNS))
            .where(table.c.id == ownership.activity_id).with_for_update()
        )).mappings().one_or_none()
    if row is None:
        if optional:
            return None
        raise NotificationActivityOwnershipLost("Notification owned attempt is missing")
    if (
        row["delivery_id"] != ownership.delivery_id
        or row["attempt_number"] != ownership.attempt_number
        or row["dispatch_protocol_version"] != DISPATCH_PROTOCOL_VERSION
    ):
        raise NotificationActivityOwnershipLost("Notification attempt linkage does not match")
    _attempt_observation(row)
    return row


async def register_notification_activity(
    session: AsyncSession, *, delivery_id: str, worker_incarnation: str
) -> NotificationActivityOwnership:
    """Atomically start one owned attempt without committing or doing provider I/O.

    The caller must take admission before its selection lock, and must confirm
    its commit before using the returned capability. A rolled-back capability
    cannot pass the subsequent one-time begin fence.
    """
    if not _uuid(delivery_id) or not _uuid(worker_incarnation):
        raise ValueError("Delivery and worker incarnation must be canonical UUIDs")
    authority = await require_notification_admission(session)
    delivery = await _locked_delivery(session, delivery_id)
    if delivery is None:
        raise NotificationActivityOwnershipLost("Notification delivery is missing")
    table = cast(Table, NotificationDelivery.__table__)
    eligible = await session.scalar(select(table.c.id).where(
        table.c.id == delivery_id, *eligible_notification_delivery_conditions(table),
    ))
    if eligible is None:
        raise NotificationActivityOwnershipLost("Notification history does not permit a new attempt")
    now = await _database_now(session)
    ownership = NotificationActivityOwnership(
        activity_id=str(uuid4()), delivery_id=delivery_id,
        attempt_number=delivery["attempt_count"] + 1, worker_incarnation=worker_incarnation,
        admitted_generation=authority.generation, ownership_nonce=str(uuid4()),
    )
    cycles = cast(Table, HostMaintenanceWorkCycle.__table__)
    await session.execute(insert(cycles).values(
        id=ownership.activity_id, resource_id=RESOURCE_ID, consumer=CONSUMER,
        job_id=delivery_id, worker_incarnation=worker_incarnation,
        admitted_generation=authority.generation, ownership_nonce=ownership.ownership_nonce,
        state="active", phase="claimed", started_at=now, heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=ACTIVITY_LEASE_SECONDS), unresolved_reason=None,
    ))
    attempts = cast(Table, NotificationDeliveryAttempt.__table__)
    await session.execute(insert(attempts).values(
        id=ownership.activity_id, delivery_id=delivery_id,
        attempt_number=ownership.attempt_number, status="started", started_at=now,
        completed_at=None, dispatch_protocol_version=DISPATCH_PROTOCOL_VERSION,
        dispatch_outcome=None, response_metadata={},
    ))
    await session.execute(update(table).where(table.c.id == delivery_id).values(
        status="processing", attempt_count=ownership.attempt_number,
        lease_token=ownership.activity_id,
        lease_expires_at=now + timedelta(seconds=ACTIVITY_LEASE_SECONDS), updated_at=now,
    ))
    return ownership


async def _fenced(
    session: AsyncSession, ownership: NotificationActivityOwnership, *, phase: str
) -> tuple[RowMapping, RowMapping, RowMapping]:
    _validate_ownership(ownership)
    delivery = await _locked_delivery(session, ownership.delivery_id)
    activity = await _locked_activity(session, ownership)
    attempt = await _locked_attempt(session, ownership)
    if delivery is None or attempt is None or (
        activity["state"] != "active" or activity["phase"] != phase
        or delivery["channel"] not in EXTERNAL_CHANNELS
        or delivery["attempt_count"] != ownership.attempt_number
    ):
        raise NotificationActivityOwnershipLost("Notification activity state does not match")
    if phase != "settled" and (
        delivery["status"] != "processing"
        or delivery["lease_token"] != ownership.activity_id
        or attempt["status"] != "started" or attempt["dispatch_outcome"] is not None
        or attempt["completed_at"] is not None
    ):
        raise NotificationActivityOwnershipLost("Notification attempt is not dispatchable")
    return delivery, activity, attempt


async def begin_notification_dispatch(
    session: AsyncSession, ownership: NotificationActivityOwnership
) -> None:
    """Consume a committed claim once; caller confirms commit before provider I/O.

    This starts no new attempt and therefore may finish an admitted claim after
    closure. Failed or ambiguous commit never authorizes provider invocation.
    """
    await _fenced(session, ownership, phase="claimed")
    table = cast(Table, HostMaintenanceWorkCycle.__table__)
    changed = await session.execute(update(table).where(
        *_owned_conditions(table, ownership), table.c.state == "active", table.c.phase == "claimed",
    ).values(phase="dispatching").returning(table.c.id))
    if changed.scalar_one_or_none() != ownership.activity_id:
        raise NotificationActivityOwnershipLost("Notification dispatch has already been consumed")


async def require_owned_notification_activity(
    session: AsyncSession, ownership: NotificationActivityOwnership
) -> None:
    """Fence publication using delivery -> activity -> attempt locks, no commit."""
    await _fenced(session, ownership, phase="dispatching")


async def settle_notification_dispatch(
    session: AsyncSession, ownership: NotificationActivityOwnership, *,
    outcome: str, delivery_status: str, provider_message_id: str | None = None,
    error_code: str | None = None, error_message: str | None = None,
    next_attempt_at: datetime | None = None,
) -> None:
    """Publish explicit settled proof in the caller TX after I/O and cleanup.

    The caller still owns the commit. Ambiguous results use mark-unresolved;
    neither that case nor cancellation may be converted into a retry outcome.
    """
    if outcome not in SETTLED_OUTCOMES:
        raise ValueError("Only an explicitly settled notification outcome may be published")
    if outcome == "accepted":
        valid_status = delivery_status == "delivered"
    else:
        valid_status = delivery_status in {"retrying", "unconfigured", "dead_letter", "failed"}
    if not valid_status or (
        provider_message_id is not None and (
            outcome != "accepted" or not _text(provider_message_id, 255)
        )
    ) or (error_code is not None and not _text(error_code, 120)) or (
        error_message is not None and not _text(error_message, 2000)
    ) or (next_attempt_at is not None and (
        delivery_status != "retrying" or not _aware(next_attempt_at)
    )):
        raise ValueError("Notification settlement fields are inconsistent")
    await _fenced(session, ownership, phase="dispatching")
    now = await _database_now(session)
    attempt_status = (
        "delivered" if outcome == "accepted"
        else "unconfigured" if outcome == "no_send" and delivery_status == "unconfigured"
        else "failed"
    )
    attempts = cast(Table, NotificationDeliveryAttempt.__table__)
    await session.execute(update(attempts).where(
        attempts.c.id == ownership.activity_id,
        attempts.c.delivery_id == ownership.delivery_id,
        attempts.c.attempt_number == ownership.attempt_number,
    ).values(
        status=attempt_status, dispatch_outcome=outcome, completed_at=now,
        provider_message_id=provider_message_id, error_code=error_code,
    ))
    deliveries = cast(Table, NotificationDelivery.__table__)
    await session.execute(update(deliveries).where(
        deliveries.c.id == ownership.delivery_id,
    ).values(
        status=delivery_status, provider_message_id=provider_message_id,
        error_code=error_code, error_message=error_message,
        delivered_at=now if outcome == "accepted" else None,
        acknowledged_at=None, dead_lettered_at=now if delivery_status == "dead_letter" else None,
        next_attempt_at=next_attempt_at, lease_token=None, lease_expires_at=None, updated_at=now,
    ))
    cycles = cast(Table, HostMaintenanceWorkCycle.__table__)
    await session.execute(update(cycles).where(
        *_owned_conditions(cycles, ownership),
    ).values(phase="settled"))


async def heartbeat_notification_activity(
    ownership: NotificationActivityOwnership, *,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Refresh the exact active owner, including the settled-before-finish gap."""
    _validate_ownership(ownership)
    async with session_factory() as session:
        async with session.begin():
            delivery = await _locked_delivery(session, ownership.delivery_id)
            row = await _locked_activity(session, ownership)
            attempt = await _locked_attempt(session, ownership)
            if (
                row["state"] != "active" or delivery is None or attempt is None
                or delivery["attempt_count"] != ownership.attempt_number
                or delivery["channel"] not in EXTERNAL_CHANNELS
            ):
                raise NotificationActivityOwnershipLost("Unresolved notification cannot resume")
            if row["phase"] == "settled":
                if not _compatible_settlement(delivery, attempt):
                    raise NotificationActivityOwnershipLost("Notification settlement is inconsistent")
            elif (
                delivery["status"] != "processing"
                or delivery["lease_token"] != ownership.activity_id
                or attempt["status"] != "started" or attempt["dispatch_outcome"] is not None
                or attempt["completed_at"] is not None
            ):
                raise NotificationActivityOwnershipLost("Notification heartbeat linkage is inconsistent")
            now = await _database_now(session)
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            await session.execute(update(table).where(*_owned_conditions(table, ownership)).values(
                heartbeat_at=now, lease_expires_at=now + timedelta(seconds=ACTIVITY_LEASE_SECONDS),
            ))


async def mark_notification_activity_unresolved(
    ownership: NotificationActivityOwnership, *, reason: str,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Retain first uncertainty, including orphan ownership and accepted results."""
    _validate_ownership(ownership)
    if not _text(reason, 160):
        raise ValueError("Notification uncertainty reason must be nonblank and at most 160 characters")
    async with session_factory() as session:
        async with session.begin():
            await _locked_delivery(session, ownership.delivery_id, optional=True)
            row = await _locked_activity(session, ownership)
            attempt = await _locked_attempt(session, ownership, optional=True)
            if row["state"] != "unresolved":
                table = cast(Table, HostMaintenanceWorkCycle.__table__)
                await session.execute(update(table).where(*_owned_conditions(table, ownership)).values(
                    state="unresolved", unresolved_reason=reason,
                ))
            if attempt is not None and (
                attempt["status"] == "started" and attempt["dispatch_outcome"] is None
                and attempt["completed_at"] is None
            ):
                attempts = cast(Table, NotificationDeliveryAttempt.__table__)
                await session.execute(update(attempts).where(
                    attempts.c.id == ownership.activity_id,
                ).values(status="uncertain", dispatch_outcome="uncertain"))


async def finish_notification_activity(
    ownership: NotificationActivityOwnership, *,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Delete only exact active ownership after confirmed settlement and joined I/O.

    Independently committed attempt proof survives removal. Manual queued status
    cannot erase uncertainty; it is compatible only with a proven safe outcome.
    """
    _validate_ownership(ownership)
    async with session_factory() as session:
        async with session.begin():
            delivery, _, attempt = await _fenced(session, ownership, phase="settled")
            if not _compatible_settlement(delivery, attempt):
                raise NotificationActivityOwnershipLost("Notification settlement is not confirmed")
            table = cast(Table, HostMaintenanceWorkCycle.__table__)
            removed = await session.execute(delete(table).where(
                *_owned_conditions(table, ownership),
                table.c.state == "active", table.c.phase == "settled",
            ).returning(table.c.id))
            if removed.scalar_one_or_none() != ownership.activity_id:
                raise NotificationActivityOwnershipLost("Notification completion lost ownership")


async def read_notification_activity_snapshot(
    session: AsyncSession, *, operation_id: str, expected_generation: int
) -> NotificationActivitySnapshot:
    """Observe independent evidence of every generation under closed admission.

    Ownership is read before attempts/deliveries. New attempts cannot start under
    closed admission; deletion follows committed proof, so completion can only
    overcount. Generic producers remain outside this explicitly partial scope.
    """
    if not _uuid(operation_id) or not _positive(expected_generation):
        raise ValueError("A canonical operation UUID and positive generation are required")
    authority = await read_admission_snapshot(session, required_scope=CONSUMER)
    if (
        authority.is_open or authority.operation_id != operation_id
        or authority.generation != expected_generation
    ):
        raise HostMaintenanceConflict("Notification observation requires current closed authority")
    observed_at = await _database_now(session)
    cycles = cast(Table, HostMaintenanceWorkCycle.__table__)
    columns = (
        "id", "resource_id", "job_id", "worker_incarnation", "admitted_generation",
        "state", "phase", "started_at", "heartbeat_at", "lease_expires_at", "unresolved_reason",
    )
    with session.no_autoflush:
        rows = (await session.execute(
            select(*(cycles.c[name] for name in columns))
            .where(cycles.c.consumer == CONSUMER).order_by(cycles.c.started_at, cycles.c.id)
        )).mappings().all()
    activities = tuple(_observation(row) for row in rows)
    if any(item.admitted_generation > authority.generation for item in activities):
        raise NotificationActivityRegistryUnavailable("Notification activity has a future generation")
    owned = {item.delivery_id for item in activities}
    attempts = cast(Table, NotificationDeliveryAttempt.__table__)
    deliveries = cast(Table, NotificationDelivery.__table__)
    with session.no_autoflush:
        attempt_rows = (await session.execute(
            select(*(attempts.c[name] for name in _ATTEMPT_COLUMNS))
            .join(deliveries, deliveries.c.id == attempts.c.delivery_id)
            .where(deliveries.c.channel.in_(EXTERNAL_CHANNELS))
            .order_by(attempts.c.delivery_id, attempts.c.attempt_number)
        )).mappings().all()
        delivery_rows = (await session.execute(
            select(*(deliveries.c[name] for name in _DELIVERY_COLUMNS))
            .where(deliveries.c.channel.in_(EXTERNAL_CHANNELS)).order_by(deliveries.c.id)
        )).mappings().all()
    observations = tuple(_attempt_observation(row) for row in attempt_rows)
    unresolved_attempts = tuple(
        item for item in observations if not (_settled_attempt(item) or _legacy_accepted(item))
    )
    by_delivery: dict[str, list[NotificationAttemptObservation]] = {}
    for item in observations:
        by_delivery.setdefault(item.delivery_id, []).append(item)
    unowned_processing: list[str] = []
    unknown: list[str] = []
    nonpristine: list[str] = []
    frozen_queued: list[str] = []
    frozen_retrying: list[str] = []
    for delivery in delivery_rows:
        delivery_id, status = delivery["id"], delivery["status"]
        if not _uuid(delivery_id):
            raise NotificationActivityRegistryUnavailable("Notification delivery identity is malformed")
        if status not in KNOWN_STATUSES:
            unknown.append(delivery_id)
        elif status == "processing" and delivery_id not in owned:
            unowned_processing.append(delivery_id)
        elif status in {"queued", "retrying"}:
            history = tuple(by_delivery.get(delivery_id, ()))
            if delivery_id in owned:
                continue
            if not _eligible(delivery, history, owned=False):
                nonpristine.append(delivery_id)
            elif status == "queued":
                frozen_queued.append(delivery_id)
            else:
                frozen_retrying.append(delivery_id)
    return NotificationActivitySnapshot(
        authority=authority, observed_at=observed_at, activities=activities,
        active_count=sum(item.state == "active" for item in activities),
        unresolved_count=sum(item.state == "unresolved" for item in activities),
        expired_count=sum(item.lease_expires_at <= observed_at for item in activities),
        unresolved_attempts=unresolved_attempts, unowned_processing_ids=tuple(unowned_processing),
        unknown_status_ids=tuple(unknown), nonpristine_queued_ids=tuple(nonpristine),
        frozen_queued_ids=tuple(frozen_queued), frozen_retrying_ids=tuple(frozen_retrying),
    )
