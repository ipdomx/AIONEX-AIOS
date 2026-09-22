"""Read-only Realtime drain evidence bound to one closed maintenance snapshot.

D9B3A observes durable provider ownership and local Realtime business state in one
repeatable-read PostgreSQL transaction. It performs no provider I/O, no cleanup,
no automatic settlement, and never promotes an empty local snapshot into a
provider-drain or full-host-closure claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import SessionLocal
from app.db.models import (
    RealtimeAdmissionGrant,
    RealtimeParticipant,
    RealtimeProviderResourceOwnership,
    RealtimeRecording,
    RealtimeRoom,
)
from app.services import host_maintenance_realtime_resources as resources
from app.services.host_maintenance_admission import (
    HostMaintenanceSnapshot,
    SessionFactory,
    read_admission_snapshot,
)

_SCOPE = "realtime_media_requests"
_PROVIDER_RECORDING_STATUSES = frozenset({"starting", "active", "ending"})
_LEGACY_AMBIGUOUS_RECORDING_ERRORS = frozenset(
    {"provider_start_failed", "provider_start_uncertain"}
)


class RealtimeDrainUnavailable(RuntimeError):
    """Durable Realtime state cannot support a trustworthy drain observation."""


@dataclass(frozen=True, slots=True)
class RealtimeDrainSnapshot:
    """Sanitized durable blockers under one explicitly closed authority state."""

    authority: HostMaintenanceSnapshot
    observed_at: datetime
    provider_resources: tuple[resources.RealtimeProviderResourceObservation, ...]
    unfinished_provider_ids: tuple[str, ...]
    unresolved_provider_ids: tuple[str, ...]
    expired_unsettled_session_ids: tuple[str, ...]
    active_room_ids: tuple[str, ...]
    connected_participant_ids: tuple[str, ...]
    provider_recording_ids: tuple[str, ...]
    legacy_unowned_room_ids: tuple[str, ...]
    legacy_unowned_session_grant_ids: tuple[str, ...]
    legacy_unowned_egress_recording_ids: tuple[str, ...]
    legacy_unowned_file_recording_ids: tuple[str, ...]
    legacy_ambiguous_recording_ids: tuple[str, ...]
    scope: str = _SCOPE
    coverage_unverified: bool = True
    live_provider_inventory_verified: bool = False
    connected_presence_provider_drain_verified: bool = False
    turn_allocation_drain_verified: bool = False
    provider_drain_verified: bool = False
    full_host_closure: bool = False

    @property
    def known_blocker_count(self) -> int:
        return sum(
            len(values)
            for values in (
                self.unfinished_provider_ids,
                self.active_room_ids,
                self.connected_participant_ids,
                self.provider_recording_ids,
                self.legacy_unowned_room_ids,
                self.legacy_unowned_session_grant_ids,
                self.legacy_unowned_egress_recording_ids,
                self.legacy_unowned_file_recording_ids,
                self.legacy_ambiguous_recording_ids,
            )
        )

    @property
    def is_clear(self) -> bool:
        """Report only that the durable/local known-blocker set is empty."""
        return self.known_blocker_count == 0


async def _database_now(session: AsyncSession) -> datetime:
    if session.get_bind().dialect.name != "postgresql":
        raise RealtimeDrainUnavailable("Realtime drain snapshot requires PostgreSQL")
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise RealtimeDrainUnavailable("Realtime drain database clock is unavailable")
    return value


async def measure_realtime_drain(
    *, session_factory: SessionFactory = SessionLocal
) -> RealtimeDrainSnapshot:
    """Measure durable Realtime blockers without mutating or contacting providers."""
    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            raise RealtimeDrainUnavailable("Realtime drain snapshot requires PostgreSQL")
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        authority = await read_admission_snapshot(session, required_scope=_SCOPE)
        if authority.is_open or authority.operation_id is None:
            raise RealtimeDrainUnavailable(
                "Realtime drain snapshot requires explicitly closed maintenance admission"
            )
        observed_at = await _database_now(session)

        provider_rows = list(
            (
                await session.scalars(
                    select(RealtimeProviderResourceOwnership).order_by(
                        RealtimeProviderResourceOwnership.id
                    )
                )
            ).all()
        )
        provider = tuple(resources.provider_resource_observation(row) for row in provider_rows)
        if any(
            item.admitted_generation >= authority.generation
            or item.admitted_operation_id == authority.operation_id
            for item in provider
        ):
            raise RealtimeDrainUnavailable(
                "Realtime provider ownership is not strictly pre-closure"
            )

        unfinished = tuple(item for item in provider if item.state != "settled")
        unfinished_ids = tuple(item.id for item in unfinished)
        unresolved_ids = tuple(item.id for item in unfinished if item.state == "unresolved")
        expired_sessions = tuple(
            item.id
            for item in unfinished
            if (
                item.resource_kind == "participant_session"
                and item.expires_at is not None
                and item.expires_at <= observed_at
            )
        )

        history = {
            (item.resource_kind, item.local_resource_id)
            for item in provider
        }

        rooms = list((await session.scalars(select(RealtimeRoom).order_by(RealtimeRoom.id))).all())
        participants = list(
            (
                await session.scalars(
                    select(RealtimeParticipant).order_by(RealtimeParticipant.id)
                )
            ).all()
        )
        grants = list(
            (
                await session.scalars(
                    select(RealtimeAdmissionGrant).order_by(RealtimeAdmissionGrant.id)
                )
            ).all()
        )
        recordings = list(
            (
                await session.scalars(
                    select(RealtimeRecording).order_by(RealtimeRecording.id)
                )
            ).all()
        )

        active_room_ids = tuple(
            room.id for room in rooms if room.status in {"planned", "open"}
        )
        connected_participant_ids = tuple(
            participant.id
            for participant in participants
            if (
                participant.status == "connected"
                or participant.connection_count != 0
                or participant.node_id is not None
                or participant.presence_lease_expires_at is not None
            )
        )
        provider_recording_ids = tuple(
            recording.id
            for recording in recordings
            if (
                recording.status in _PROVIDER_RECORDING_STATUSES
                or (
                    recording.provider_egress_id is not None
                    and recording.status not in {"completed", "failed", "declined", "cancelled"}
                )
            )
        )

        legacy_rooms = tuple(
            room.id
            for room in rooms
            if (
                (room.provider_adapter == "livekit" or room.provider_room_id_sha256 is not None)
                and ("room", room.id) not in history
            )
        )
        legacy_sessions = tuple(
            grant.id
            for grant in grants
            if (
                (
                    grant.provider_adapter == "livekit"
                    or grant.provider_token_jti_sha256 is not None
                )
                and ("participant_session", grant.id) not in history
            )
        )
        legacy_egress = tuple(
            recording.id
            for recording in recordings
            if (
                recording.provider_egress_id is not None
                and ("egress", recording.id) not in history
            )
        )
        legacy_files = tuple(
            recording.id
            for recording in recordings
            if (
                recording.provider_egress_id is not None
                and ("recording_file", recording.id) not in history
            )
        )
        legacy_ambiguous = tuple(
            recording.id
            for recording in recordings
            if (
                recording.error_code in _LEGACY_AMBIGUOUS_RECORDING_ERRORS
                and ("egress", recording.id) not in history
            )
        )

        return RealtimeDrainSnapshot(
            authority=authority,
            observed_at=cast(datetime, observed_at),
            provider_resources=provider,
            unfinished_provider_ids=unfinished_ids,
            unresolved_provider_ids=unresolved_ids,
            expired_unsettled_session_ids=expired_sessions,
            active_room_ids=active_room_ids,
            connected_participant_ids=connected_participant_ids,
            provider_recording_ids=provider_recording_ids,
            legacy_unowned_room_ids=legacy_rooms,
            legacy_unowned_session_grant_ids=legacy_sessions,
            legacy_unowned_egress_recording_ids=legacy_egress,
            legacy_unowned_file_recording_ids=legacy_files,
            legacy_ambiguous_recording_ids=legacy_ambiguous,
        )
