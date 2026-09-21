"""Permanent provider-resource intent for Realtime host-maintenance drain.

D9B2A only supplies the durable registry. Provider routes are wired later. A
reserved row is committed before a provider capability can be consumed. Starting
provider I/O rechecks the same open admission generation in a separate committed
transaction. Timeouts/cancellation never erase submitted or active ownership.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import RealtimeProviderResourceOwnership
from app.services.host_maintenance_admission import SessionFactory
from app.services.host_maintenance_realtime_admission import require_realtime_admission

_RESOURCE_KINDS = frozenset({"room", "participant_session", "egress", "recording_file"})


class RealtimeProviderOwnershipLost(RuntimeError):
    """Exact permanent provider ownership no longer permits the transition."""


class RealtimeProviderOwnershipUncertain(RuntimeError):
    """Provider resource evidence cannot certify a safe transition."""


@dataclass(frozen=True, slots=True)
class RealtimeProviderOwnership:
    id: str
    organization_id: str
    resource_kind: str
    local_resource_id: str
    owner_incarnation: str
    admitted_generation: int
    admitted_operation_id: str
    nonce: str = field(repr=False)


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _hex64(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _reason(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 160 and "\x00" not in value


async def _now(session: AsyncSession) -> datetime:
    if session.get_bind().dialect.name != "postgresql":
        raise RealtimeProviderOwnershipUncertain("Realtime provider ownership requires PostgreSQL")
    result = await session.scalar(select(func.clock_timestamp()))
    if not _aware(result):
        raise RealtimeProviderOwnershipUncertain("Realtime provider database clock is unavailable")
    return cast(datetime, result)


def _owner(row: RealtimeProviderResourceOwnership) -> RealtimeProviderOwnership:
    if (
        not all(_uuid(v) for v in (
            row.id, row.organization_id, row.local_resource_id, row.owner_incarnation,
            row.admitted_operation_id, row.ownership_nonce,
        ))
        or row.resource_kind not in _RESOURCE_KINDS
        or type(row.admitted_generation) is not int or row.admitted_generation < 1
        or row.state not in {"reserved", "submitted", "active", "unresolved", "settled"}
        or not _aware(row.started_at) or not _aware(row.updated_at)
        or row.updated_at < row.started_at
        or (row.expires_at is not None and (not _aware(row.expires_at) or row.expires_at < row.started_at))
        or (row.provider_started_at is not None and (not _aware(row.provider_started_at) or row.provider_started_at < row.started_at))
        or (row.provider_ref_sha256 is not None and not _hex64(row.provider_ref_sha256))
        or (row.state == "unresolved") != _reason(row.unresolved_reason)
        or (row.state == "settled") != _aware(row.settled_at)
    ):
        raise RealtimeProviderOwnershipUncertain("Realtime provider ownership is malformed")
    if row.state == "reserved" and (
        row.provider_started_at is not None or row.provider_ref_sha256 is not None
    ):
        raise RealtimeProviderOwnershipUncertain("Reserved provider intent already has provider evidence")
    if row.state in {"submitted", "active", "unresolved"} and row.provider_started_at is None:
        raise RealtimeProviderOwnershipUncertain("Started provider ownership lacks its start timestamp")
    if row.state == "active" and row.provider_ref_sha256 is None:
        raise RealtimeProviderOwnershipUncertain("Active provider resource lacks a provider reference hash")
    if row.resource_kind == "participant_session" and row.state == "active" and row.expires_at is None:
        raise RealtimeProviderOwnershipUncertain("Active participant session lacks expiry evidence")
    return RealtimeProviderOwnership(
        row.id, row.organization_id, row.resource_kind, row.local_resource_id,
        row.owner_incarnation, row.admitted_generation, row.admitted_operation_id,
        row.ownership_nonce,
    )


async def _locked(session: AsyncSession, owner: RealtimeProviderOwnership) -> RealtimeProviderResourceOwnership:
    if not isinstance(owner, RealtimeProviderOwnership):
        raise RealtimeProviderOwnershipLost("Realtime provider owner is required")
    with session.no_autoflush:
        row = await session.scalar(select(RealtimeProviderResourceOwnership).where(
            RealtimeProviderResourceOwnership.id == owner.id,
            RealtimeProviderResourceOwnership.organization_id == owner.organization_id,
            RealtimeProviderResourceOwnership.resource_kind == owner.resource_kind,
            RealtimeProviderResourceOwnership.local_resource_id == owner.local_resource_id,
            RealtimeProviderResourceOwnership.owner_incarnation == owner.owner_incarnation,
            RealtimeProviderResourceOwnership.admitted_generation == owner.admitted_generation,
            RealtimeProviderResourceOwnership.admitted_operation_id == owner.admitted_operation_id,
            RealtimeProviderResourceOwnership.ownership_nonce == owner.nonce,
        ).with_for_update().execution_options(populate_existing=True))
    if row is None or _owner(row) != owner:
        raise RealtimeProviderOwnershipLost("Realtime provider ownership differs")
    return row


async def reserve_provider_resource(
    session: AsyncSession, *, organization_id: str, resource_kind: str,
    local_resource_id: str, owner_incarnation: str,
) -> RealtimeProviderOwnership:
    """Reserve provider intent with the caller transaction before any provider I/O."""
    authority = await require_realtime_admission(session)
    if (
        resource_kind not in _RESOURCE_KINDS
        or not all(_uuid(v) for v in (organization_id, local_resource_id, owner_incarnation))
        or not _uuid(authority.operation_id)
    ):
        raise ValueError("Realtime provider reservation identity is invalid")
    existing = await session.scalar(select(RealtimeProviderResourceOwnership.id).where(
        RealtimeProviderResourceOwnership.organization_id == organization_id,
        RealtimeProviderResourceOwnership.resource_kind == resource_kind,
        RealtimeProviderResourceOwnership.local_resource_id == local_resource_id,
        RealtimeProviderResourceOwnership.state != "settled",
    ).limit(1))
    if existing is not None:
        raise RealtimeProviderOwnershipLost("Unfinished provider ownership already exists")
    stamp = await _now(session)
    row = RealtimeProviderResourceOwnership(
        id=str(uuid4()), organization_id=organization_id, resource_kind=resource_kind,
        local_resource_id=local_resource_id, owner_incarnation=owner_incarnation,
        admitted_generation=authority.generation, admitted_operation_id=authority.operation_id,
        ownership_nonce=str(uuid4()), state="reserved", started_at=stamp, updated_at=stamp,
    )
    session.add(row)
    await session.flush()
    return _owner(row)


async def begin_provider_io(
    owner: RealtimeProviderOwnership, *, session_factory: SessionFactory = SessionLocal,
) -> bool:
    """Consume a committed intent only while the same admission generation is open."""
    async with session_factory() as session, session.begin():
        authority = await require_realtime_admission(session)
        row = await _locked(session, owner)
        if (
            authority.generation != owner.admitted_generation
            or authority.operation_id != owner.admitted_operation_id
        ):
            return False
        if row.state != "reserved":
            raise RealtimeProviderOwnershipLost("Provider intent is single-use")
        stamp = await _now(session)
        row.state = "submitted"
        row.provider_started_at = stamp
        row.updated_at = stamp
        return True


async def observe_provider_active(
    owner: RealtimeProviderOwnership, *, provider_ref_sha256: str,
    expires_at: datetime | None = None, session_factory: SessionFactory = SessionLocal,
) -> None:
    if not _hex64(provider_ref_sha256) or (expires_at is not None and not _aware(expires_at)):
        raise ValueError("Provider observation is invalid")
    if owner.resource_kind == "participant_session" and expires_at is None:
        raise ValueError("Participant session observation requires provider expiry")
    async with session_factory() as session, session.begin():
        row = await _locked(session, owner)
        if row.state != "submitted":
            raise RealtimeProviderOwnershipLost("Only submitted provider intent can become active")
        row.state = "active"
        row.provider_ref_sha256 = provider_ref_sha256
        row.expires_at = expires_at
        row.updated_at = await _now(session)


async def mark_provider_unresolved(
    owner: RealtimeProviderOwnership, *, reason: str, expires_at: datetime | None = None,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    if not _reason(reason) or (expires_at is not None and not _aware(expires_at)):
        raise ValueError("Provider uncertainty evidence is invalid")
    async with session_factory() as session, session.begin():
        row = await _locked(session, owner)
        if row.state not in {"submitted", "active", "unresolved"}:
            raise RealtimeProviderOwnershipLost("Provider uncertainty requires started ownership")
        if owner.resource_kind == "participant_session":
            candidate_expiry = row.expires_at or expires_at
            if candidate_expiry is None:
                raise RealtimeProviderOwnershipUncertain(
                    "Participant session uncertainty requires a conservative expiry"
                )
            if candidate_expiry < row.started_at:
                raise RealtimeProviderOwnershipUncertain(
                    "Participant session expiry predates its durable intent"
                )
            row.expires_at = candidate_expiry
        row.state = "unresolved"
        row.unresolved_reason = row.unresolved_reason or reason
        row.updated_at = await _now(session)


async def settle_not_started_in_session(
    session: AsyncSession, owner: RealtimeProviderOwnership,
) -> None:
    """Settle one unconsumed reserved capability inside the caller transaction."""
    row = await _locked(session, owner)
    if row.state != "reserved" or row.provider_started_at is not None:
        raise RealtimeProviderOwnershipLost("Started provider work cannot be settled as not-started")
    stamp = await _now(session)
    row.state = "settled"
    row.settled_at = stamp
    row.updated_at = stamp


async def settle_not_started(
    owner: RealtimeProviderOwnership, *, session_factory: SessionFactory = SessionLocal,
) -> None:
    """Settle only a reserved capability that was never consumed for provider I/O."""
    async with session_factory() as session, session.begin():
        await settle_not_started_in_session(session, owner)


async def find_unfinished_provider_ownership(
    session: AsyncSession, *, organization_id: str, resource_kind: str,
    local_resource_id: str,
) -> RealtimeProviderOwnership | None:
    if resource_kind not in _RESOURCE_KINDS or not all(
        _uuid(v) for v in (organization_id, local_resource_id)
    ):
        raise ValueError("Realtime provider lookup identity is invalid")
    row = await session.scalar(select(RealtimeProviderResourceOwnership).where(
        RealtimeProviderResourceOwnership.organization_id == organization_id,
        RealtimeProviderResourceOwnership.resource_kind == resource_kind,
        RealtimeProviderResourceOwnership.local_resource_id == local_resource_id,
        RealtimeProviderResourceOwnership.state != "settled",
    ).limit(1))
    return _owner(row) if row is not None else None


async def provider_ownership_state(
    owner: RealtimeProviderOwnership, *, session_factory: SessionFactory = SessionLocal,
) -> str:
    async with session_factory() as session:
        row = await _locked(session, owner)
        return row.state


async def settle_room_absent(
    owner: RealtimeProviderOwnership, *, provider_ref_sha256: str,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Settle room ownership only after explicit provider delete/not-found proof."""
    if owner.resource_kind != "room" or not _hex64(provider_ref_sha256):
        raise ValueError("Room settlement identity is invalid")
    async with session_factory() as session, session.begin():
        row = await _locked(session, owner)
        if row.state not in {"active", "unresolved"}:
            raise RealtimeProviderOwnershipLost(
                "Room absence requires completed-or-ambiguous provider observation"
            )
        if row.provider_ref_sha256 not in (None, provider_ref_sha256):
            raise RealtimeProviderOwnershipUncertain("Room provider identity differs")
        stamp = await _now(session)
        row.provider_ref_sha256 = provider_ref_sha256
        row.state = "settled"
        row.unresolved_reason = None
        row.settled_at = stamp
        row.updated_at = stamp


async def settle_participant_session_expired(
    owner: RealtimeProviderOwnership, *, session_factory: SessionFactory = SessionLocal,
) -> bool:
    """Settle issued participant credentials only after the whole bundle expires."""
    if owner.resource_kind != "participant_session":
        raise ValueError("Participant-session ownership is required")
    async with session_factory() as session, session.begin():
        row = await _locked(session, owner)
        if row.state == "settled":
            return True
        if row.state not in {"active", "unresolved"} or row.expires_at is None:
            return False
        stamp = await _now(session)
        if stamp < row.expires_at:
            return False
        row.state = "settled"
        row.unresolved_reason = None
        row.settled_at = stamp
        row.updated_at = stamp
        return True


_EGRESS_TERMINAL_STATUSES = frozenset({
    "EGRESS_COMPLETE", "EGRESS_FAILED", "EGRESS_ABORTED",
})


async def verify_provider_reference(
    owner: RealtimeProviderOwnership, *, provider_ref_sha256: str,
    session_factory: SessionFactory = SessionLocal,
) -> str:
    """Verify an observed provider identity without changing settlement state."""
    if not _hex64(provider_ref_sha256):
        raise ValueError("Provider reference digest is invalid")
    async with session_factory() as session:
        row = await _locked(session, owner)
        if row.provider_ref_sha256 != provider_ref_sha256:
            raise RealtimeProviderOwnershipUncertain("Provider resource identity differs")
        return row.state


async def settle_egress_terminal(
    owner: RealtimeProviderOwnership, *, provider_ref_sha256: str, provider_status: str,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    """Settle Egress only from an explicit terminal provider observation."""
    if owner.resource_kind != "egress" or not _hex64(provider_ref_sha256):
        raise ValueError("Egress settlement identity is invalid")
    if provider_status not in _EGRESS_TERMINAL_STATUSES:
        raise ValueError("Egress settlement requires explicit terminal provider status")
    async with session_factory() as session, session.begin():
        row = await _locked(session, owner)
        if row.state not in {"active", "unresolved"}:
            raise RealtimeProviderOwnershipLost(
                "Egress terminal settlement requires active or unresolved ownership"
            )
        if row.provider_ref_sha256 != provider_ref_sha256:
            raise RealtimeProviderOwnershipUncertain("Egress provider identity differs")
        stamp = await _now(session)
        row.state = "settled"
        row.unresolved_reason = None
        row.settled_at = stamp
        row.updated_at = stamp
