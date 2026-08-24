"""Durable tenant-scoped realtime admission, backpressure, and presence leases.

This module is deliberately provider-neutral. It does not contact an SFU, issue a
provider token, open TURN/STUN ports, or start recording. The database is the
coordination authority so multiple API nodes make the same fail-closed decisions.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Organization,
    RealtimeAdmissionGrant,
    RealtimeParticipant,
    RealtimeRoom,
    RealtimeTenantQuota,
)

_ACTIVE_ROOM_STATUSES: Final[frozenset[str]] = frozenset({"planned", "open"})
_ACTIVE_PARTICIPANT_STATUSES: Final[frozenset[str]] = frozenset(
    {"admitted", "connected"}
)
_MIN_PRESENCE_LEASE_SECONDS: Final[int] = 5
_MAX_PRESENCE_LEASE_SECONDS: Final[int] = 120


class RealtimeAdmissionRejected(RuntimeError):
    """Fail-closed admission decision with a stable machine-readable code."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class AdmissionGrantResult:
    grant: RealtimeAdmissionGrant
    participant: RealtimeParticipant
    token: str
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class PresenceLeaseResult:
    participant: RealtimeParticipant
    fencing_token: int
    lease_expires_at: datetime
    takeover: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


def _grant_token(grant_id: str, secret: str) -> str:
    payload = f"rtg1.{grant_id}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return f"{payload}.{signature.hexdigest()}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RealtimeAdmissionAuthority:
    """Transactional authority shared by all realtime API nodes."""

    def __init__(self, *, secret_key: str | None = None) -> None:
        secret = secret_key if secret_key is not None else settings.SECRET_KEY
        if len(secret) < 32:
            raise ValueError("realtime admission signing key must contain at least 32 characters")
        self._secret = secret

    async def provision_default_quota(
        self, session: AsyncSession, *, organization_id: str
    ) -> RealtimeTenantQuota:
        organization = await session.scalar(
            select(Organization)
            .where(Organization.id == organization_id)
            .with_for_update()
        )
        if organization is None or organization.status != "active":
            raise RealtimeAdmissionRejected("tenant_unavailable", "tenant is not active")
        quota = await session.scalar(
            select(RealtimeTenantQuota).where(
                RealtimeTenantQuota.organization_id == organization_id
            )
        )
        if quota is None:
            quota = RealtimeTenantQuota(
                id=_new_id(),
                organization_id=organization_id,
                enabled=True,
            )
            session.add(quota)
            await session.flush()
        return quota

    async def create_room(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        created_by_id: str,
        room_key: str,
        idempotency_key: str,
        workspace_id: str | None = None,
        project_id: str | None = None,
        room_type: str = "meeting",
        media_mode: str = "audio_video",
        max_participants: int = 50,
        allow_screen_share: bool = True,
    ) -> RealtimeRoom:
        if not room_key.strip() or not idempotency_key.strip():
            raise RealtimeAdmissionRejected("invalid_room_request", "room keys are required")
        quota = await self._lock_quota(session, organization_id)
        existing = await session.scalar(
            select(RealtimeRoom).where(
                RealtimeRoom.organization_id == organization_id,
                RealtimeRoom.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        if max_participants < 1 or max_participants > quota.max_participants_per_room:
            raise RealtimeAdmissionRejected(
                "room_participant_limit",
                "requested room capacity exceeds tenant policy",
            )
        active_rooms = int(
            await session.scalar(
                select(func.count(RealtimeRoom.id)).where(
                    RealtimeRoom.organization_id == organization_id,
                    RealtimeRoom.status.in_(_ACTIVE_ROOM_STATUSES),
                )
            )
            or 0
        )
        if active_rooms >= quota.max_concurrent_rooms:
            raise RealtimeAdmissionRejected(
                "tenant_room_backpressure", "tenant concurrent room limit reached"
            )
        room = RealtimeRoom(
            id=_new_id(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            created_by_id=created_by_id,
            room_key=room_key.strip(),
            idempotency_key=idempotency_key.strip(),
            room_type=room_type,
            media_mode=media_mode,
            status="planned",
            provider_adapter="unassigned",
            max_participants=max_participants,
            allow_screen_share=allow_screen_share,
            recording_policy="disabled",
            encryption_policy="transport_required",
            admission_policy={},
            fencing_token=0,
        )
        session.add(room)
        await session.flush()
        return room

    async def issue_grant(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        room_id: str,
        user_id: str,
        issued_by_id: str,
        participant_key: str,
        idempotency_key: str,
        role: str = "attendee",
        can_publish: bool = True,
        can_subscribe: bool = True,
        can_screen_share: bool = False,
    ) -> AdmissionGrantResult:
        if not participant_key.strip() or not idempotency_key.strip():
            raise RealtimeAdmissionRejected(
                "invalid_admission_request", "participant and idempotency keys are required"
            )
        now = _utcnow()
        quota = await self._lock_quota(session, organization_id)
        room = await self._lock_room(session, organization_id, room_id)
        if room.status not in _ACTIVE_ROOM_STATUSES:
            raise RealtimeAdmissionRejected("room_unavailable", "room is not admitting users")
        if can_screen_share and not room.allow_screen_share:
            raise RealtimeAdmissionRejected(
                "screen_share_disabled", "screen sharing is disabled for this room"
            )

        await self._expire_unconsumed_grants(session, organization_id, now)
        existing_grant = await session.scalar(
            select(RealtimeAdmissionGrant).where(
                RealtimeAdmissionGrant.organization_id == organization_id,
                RealtimeAdmissionGrant.idempotency_key == idempotency_key,
            )
        )
        if existing_grant is not None:
            if existing_grant.room_id != room_id or existing_grant.user_id != user_id:
                raise RealtimeAdmissionRejected(
                    "idempotency_conflict", "idempotency key is bound to another admission"
                )
            participant = await session.get(
                RealtimeParticipant, existing_grant.participant_id
            )
            if participant is None or participant.organization_id != organization_id:
                raise RealtimeAdmissionRejected(
                    "participant_missing", "idempotent admission participant is unavailable"
                )
            if existing_grant.status != "issued" or existing_grant.expires_at <= now:
                raise RealtimeAdmissionRejected(
                    "grant_not_replayable", "existing admission grant is no longer active"
                )
            token = _grant_token(existing_grant.id, self._secret)
            if not hmac.compare_digest(_digest(token), existing_grant.grant_digest_sha256):
                raise RealtimeAdmissionRejected(
                    "grant_integrity_error", "stored admission digest does not match authority"
                )
            return AdmissionGrantResult(existing_grant, participant, token, True)

        window_start = now - timedelta(seconds=quota.admission_window_seconds)
        recent_admissions = int(
            await session.scalar(
                select(func.count(RealtimeAdmissionGrant.id)).where(
                    RealtimeAdmissionGrant.organization_id == organization_id,
                    RealtimeAdmissionGrant.issued_at >= window_start,
                )
            )
            or 0
        )
        if recent_admissions >= quota.max_admissions_per_window:
            raise RealtimeAdmissionRejected(
                "tenant_admission_backpressure", "tenant admission rate limit reached"
            )

        participant = await session.scalar(
            select(RealtimeParticipant)
            .where(
                RealtimeParticipant.organization_id == organization_id,
                RealtimeParticipant.room_id == room_id,
                RealtimeParticipant.participant_key == participant_key,
            )
            .with_for_update()
        )
        if participant is not None and participant.user_id != user_id:
            raise RealtimeAdmissionRejected(
                "participant_key_conflict", "participant key belongs to another user"
            )

        participant_is_active = bool(
            participant is not None and participant.status in _ACTIVE_PARTICIPANT_STATUSES
        )
        if participant is not None:
            outstanding = await session.scalar(
                select(RealtimeAdmissionGrant.id).where(
                    RealtimeAdmissionGrant.organization_id == organization_id,
                    RealtimeAdmissionGrant.participant_id == participant.id,
                    RealtimeAdmissionGrant.status == "issued",
                    RealtimeAdmissionGrant.expires_at > now,
                )
            )
            if outstanding is not None:
                raise RealtimeAdmissionRejected(
                    "grant_already_issued", "participant already has an active admission grant"
                )

        if not participant_is_active:
            await self._enforce_participant_capacity(
                session,
                quota=quota,
                room=room,
                can_publish=can_publish,
                can_screen_share=can_screen_share,
            )

        if participant is None:
            participant = RealtimeParticipant(
                id=_new_id(),
                organization_id=organization_id,
                room_id=room_id,
                user_id=user_id,
                participant_key=participant_key.strip(),
                role=role,
                status="admitted",
                can_publish=can_publish,
                can_subscribe=can_subscribe,
                can_screen_share=can_screen_share,
                hidden=False,
                connection_count=0,
                presence_fencing_token=0,
                capabilities={},
            )
            session.add(participant)
        else:
            participant.role = role
            participant.status = "admitted" if participant.status == "left" else participant.status
            participant.can_publish = can_publish
            participant.can_subscribe = can_subscribe
            participant.can_screen_share = can_screen_share
            participant.revoked_at = None
            participant.left_at = None
            participant.version += 1
        await session.flush()

        grant_id = _new_id()
        token = _grant_token(grant_id, self._secret)
        permissions = ["subscribe"] if can_subscribe else []
        if can_publish:
            permissions.append("publish")
        if can_screen_share:
            permissions.append("screen_share")
        grant = RealtimeAdmissionGrant(
            id=grant_id,
            organization_id=organization_id,
            room_id=room_id,
            participant_id=participant.id,
            user_id=user_id,
            issued_by_id=issued_by_id,
            idempotency_key=idempotency_key.strip(),
            grant_digest_sha256=_digest(token),
            provider_adapter="unassigned",
            role=role,
            permissions=permissions,
            status="issued",
            single_use=True,
            issued_at=now,
            expires_at=now + timedelta(seconds=quota.grant_ttl_seconds),
        )
        session.add(grant)
        await session.flush()
        return AdmissionGrantResult(grant, participant, token, False)

    async def consume_grant(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        token: str,
        node_id: str,
    ) -> RealtimeAdmissionGrant:
        now = _utcnow()
        digest = _digest(token)
        grant = await session.scalar(
            select(RealtimeAdmissionGrant)
            .where(
                RealtimeAdmissionGrant.organization_id == organization_id,
                RealtimeAdmissionGrant.grant_digest_sha256 == digest,
            )
            .with_for_update()
        )
        if grant is None:
            raise RealtimeAdmissionRejected("grant_invalid", "admission grant is unknown")
        expected = _grant_token(grant.id, self._secret)
        if not hmac.compare_digest(token, expected):
            raise RealtimeAdmissionRejected("grant_invalid", "admission grant signature is invalid")
        if grant.revoked_at is not None or grant.status == "revoked":
            raise RealtimeAdmissionRejected("grant_revoked", "admission grant was revoked")
        if grant.expires_at <= now:
            grant.status = "expired"
            raise RealtimeAdmissionRejected("grant_expired", "admission grant expired")
        if grant.single_use and grant.consumed_at is not None:
            raise RealtimeAdmissionRejected("grant_consumed", "admission grant is single-use")
        grant.consumed_at = now
        grant.consumed_by_node = node_id
        grant.status = "consumed"
        grant.version += 1
        await session.flush()
        return grant

    async def revoke_grant(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        grant_id: str,
    ) -> RealtimeAdmissionGrant:
        grant = await session.scalar(
            select(RealtimeAdmissionGrant)
            .where(
                RealtimeAdmissionGrant.id == grant_id,
                RealtimeAdmissionGrant.organization_id == organization_id,
            )
            .with_for_update()
        )
        if grant is None:
            raise RealtimeAdmissionRejected("grant_missing", "admission grant does not exist")
        if grant.status == "issued":
            grant.status = "revoked"
            grant.revoked_at = _utcnow()
            grant.version += 1
            await session.flush()
        return grant

    async def advance_room_fence(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        room_id: str,
    ) -> int:
        room = await self._lock_room(session, organization_id, room_id)
        room.fencing_token += 1
        room.version += 1
        await session.flush()
        return int(room.fencing_token)

    async def claim_presence(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        participant_id: str,
        node_id: str,
        lease_seconds: int = 30,
    ) -> PresenceLeaseResult:
        self._validate_lease_seconds(lease_seconds)
        now = _utcnow()
        participant = await self._lock_participant(session, organization_id, participant_id)
        if participant.status not in _ACTIVE_PARTICIPANT_STATUSES:
            raise RealtimeAdmissionRejected(
                "participant_unavailable", "participant is not admitted"
            )
        current_expiry = participant.presence_lease_expires_at
        current_live = current_expiry is not None and current_expiry > now
        if current_live and participant.node_id not in {None, node_id}:
            raise RealtimeAdmissionRejected(
                "presence_lease_held", "another node owns the active presence lease"
            )
        if current_live and participant.node_id == node_id:
            participant.presence_lease_expires_at = now + timedelta(seconds=lease_seconds)
            participant.last_seen_at = now
            participant.status = "connected"
            await session.flush()
            return PresenceLeaseResult(
                participant,
                int(participant.presence_fencing_token),
                participant.presence_lease_expires_at,
                False,
            )

        takeover = participant.node_id is not None
        participant.presence_fencing_token += 1
        participant.node_id = node_id
        participant.connection_count = 1
        participant.status = "connected"
        participant.joined_at = participant.joined_at or now
        participant.last_seen_at = now
        participant.left_at = None
        participant.presence_lease_expires_at = now + timedelta(seconds=lease_seconds)
        participant.version += 1
        await session.flush()
        return PresenceLeaseResult(
            participant,
            int(participant.presence_fencing_token),
            participant.presence_lease_expires_at,
            takeover,
        )

    async def heartbeat_presence(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        participant_id: str,
        node_id: str,
        fencing_token: int,
        lease_seconds: int = 30,
    ) -> PresenceLeaseResult:
        self._validate_lease_seconds(lease_seconds)
        now = _utcnow()
        participant = await self._lock_participant(session, organization_id, participant_id)
        if (
            participant.node_id != node_id
            or participant.presence_fencing_token != fencing_token
        ):
            raise RealtimeAdmissionRejected(
                "stale_presence_fence", "presence lease fencing token is stale"
            )
        if (
            participant.presence_lease_expires_at is None
            or participant.presence_lease_expires_at <= now
        ):
            raise RealtimeAdmissionRejected(
                "presence_lease_expired", "presence lease must be reclaimed"
            )
        participant.last_seen_at = now
        participant.presence_lease_expires_at = now + timedelta(seconds=lease_seconds)
        participant.status = "connected"
        await session.flush()
        return PresenceLeaseResult(
            participant,
            int(participant.presence_fencing_token),
            participant.presence_lease_expires_at,
            False,
        )

    async def release_presence(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        participant_id: str,
        node_id: str,
        fencing_token: int,
        leave: bool = False,
    ) -> RealtimeParticipant:
        participant = await self._lock_participant(session, organization_id, participant_id)
        if (
            participant.node_id != node_id
            or participant.presence_fencing_token != fencing_token
        ):
            raise RealtimeAdmissionRejected(
                "stale_presence_fence", "presence release fencing token is stale"
            )
        now = _utcnow()
        participant.presence_fencing_token += 1
        participant.node_id = None
        participant.connection_count = 0
        participant.presence_lease_expires_at = None
        participant.last_seen_at = now
        participant.status = "left" if leave else "admitted"
        participant.left_at = now if leave else None
        participant.version += 1
        await session.flush()
        return participant

    async def reap_stale_presence(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        observed_at = now or _utcnow()
        rows = list(
            (
                await session.scalars(
                    select(RealtimeParticipant)
                    .where(
                        RealtimeParticipant.organization_id == organization_id,
                        RealtimeParticipant.status == "connected",
                        RealtimeParticipant.presence_lease_expires_at.is_not(None),
                        RealtimeParticipant.presence_lease_expires_at <= observed_at,
                    )
                    .order_by(RealtimeParticipant.presence_lease_expires_at.asc())
                    .limit(max(1, min(limit, 1000)))
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for participant in rows:
            participant.presence_fencing_token += 1
            participant.node_id = None
            participant.connection_count = 0
            participant.presence_lease_expires_at = None
            participant.status = "admitted"
            participant.version += 1
        if rows:
            await session.flush()
        return len(rows)

    async def _lock_quota(
        self, session: AsyncSession, organization_id: str
    ) -> RealtimeTenantQuota:
        quota = await session.scalar(
            select(RealtimeTenantQuota)
            .where(RealtimeTenantQuota.organization_id == organization_id)
            .with_for_update()
        )
        if quota is None or not quota.enabled:
            raise RealtimeAdmissionRejected(
                "tenant_realtime_disabled", "tenant realtime admission is not enabled"
            )
        return quota

    async def _lock_room(
        self, session: AsyncSession, organization_id: str, room_id: str
    ) -> RealtimeRoom:
        room = await session.scalar(
            select(RealtimeRoom)
            .where(
                RealtimeRoom.id == room_id,
                RealtimeRoom.organization_id == organization_id,
            )
            .with_for_update()
        )
        if room is None:
            raise RealtimeAdmissionRejected("room_missing", "room does not exist")
        return room

    async def _lock_participant(
        self, session: AsyncSession, organization_id: str, participant_id: str
    ) -> RealtimeParticipant:
        participant = await session.scalar(
            select(RealtimeParticipant)
            .where(
                RealtimeParticipant.id == participant_id,
                RealtimeParticipant.organization_id == organization_id,
            )
            .with_for_update()
        )
        if participant is None:
            raise RealtimeAdmissionRejected(
                "participant_missing", "participant does not exist"
            )
        return participant

    async def _enforce_participant_capacity(
        self,
        session: AsyncSession,
        *,
        quota: RealtimeTenantQuota,
        room: RealtimeRoom,
        can_publish: bool,
        can_screen_share: bool,
    ) -> None:
        tenant_count = int(
            await session.scalar(
                select(func.count(RealtimeParticipant.id)).where(
                    RealtimeParticipant.organization_id == room.organization_id,
                    RealtimeParticipant.status.in_(_ACTIVE_PARTICIPANT_STATUSES),
                )
            )
            or 0
        )
        if tenant_count >= quota.max_concurrent_participants:
            raise RealtimeAdmissionRejected(
                "tenant_participant_backpressure",
                "tenant concurrent participant limit reached",
            )
        room_count = int(
            await session.scalar(
                select(func.count(RealtimeParticipant.id)).where(
                    RealtimeParticipant.organization_id == room.organization_id,
                    RealtimeParticipant.room_id == room.id,
                    RealtimeParticipant.status.in_(_ACTIVE_PARTICIPANT_STATUSES),
                )
            )
            or 0
        )
        room_limit = min(room.max_participants, quota.max_participants_per_room)
        if room_count >= room_limit:
            raise RealtimeAdmissionRejected(
                "room_participant_backpressure", "room participant limit reached"
            )
        if can_publish:
            publishers = int(
                await session.scalar(
                    select(func.count(RealtimeParticipant.id)).where(
                        RealtimeParticipant.organization_id == room.organization_id,
                        RealtimeParticipant.room_id == room.id,
                        RealtimeParticipant.status.in_(_ACTIVE_PARTICIPANT_STATUSES),
                        RealtimeParticipant.can_publish.is_(True),
                    )
                )
                or 0
            )
            if publishers >= quota.max_publishers_per_room:
                raise RealtimeAdmissionRejected(
                    "room_publisher_backpressure", "room publisher limit reached"
                )
        if can_screen_share:
            shares = int(
                await session.scalar(
                    select(func.count(RealtimeParticipant.id)).where(
                        RealtimeParticipant.organization_id == room.organization_id,
                        RealtimeParticipant.room_id == room.id,
                        RealtimeParticipant.status.in_(_ACTIVE_PARTICIPANT_STATUSES),
                        RealtimeParticipant.can_screen_share.is_(True),
                    )
                )
                or 0
            )
            if shares >= quota.max_screen_shares_per_room:
                raise RealtimeAdmissionRejected(
                    "room_screen_share_backpressure",
                    "room screen-share limit reached",
                )

    async def _expire_unconsumed_grants(
        self, session: AsyncSession, organization_id: str, now: datetime
    ) -> None:
        expired = list(
            (
                await session.scalars(
                    select(RealtimeAdmissionGrant)
                    .where(
                        RealtimeAdmissionGrant.organization_id == organization_id,
                        RealtimeAdmissionGrant.status == "issued",
                        RealtimeAdmissionGrant.expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for grant in expired:
            grant.status = "expired"
            grant.version += 1
            if grant.participant_id is None:
                continue
            participant = await session.get(RealtimeParticipant, grant.participant_id)
            if (
                participant is not None
                and participant.organization_id == organization_id
                and participant.status == "admitted"
                and participant.connection_count == 0
            ):
                participant.status = "left"
                participant.left_at = now
                participant.version += 1
        if expired:
            await session.flush()

    @staticmethod
    def _validate_lease_seconds(lease_seconds: int) -> None:
        if not _MIN_PRESENCE_LEASE_SECONDS <= lease_seconds <= _MAX_PRESENCE_LEASE_SECONDS:
            raise RealtimeAdmissionRejected(
                "invalid_presence_lease",
                f"presence lease must be between {_MIN_PRESENCE_LEASE_SECONDS} and {_MAX_PRESENCE_LEASE_SECONDS} seconds",
            )
