"""Consent-governed LiveKit realtime media API for authenticated portal users."""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Project,
    RealtimeAdmissionGrant,
    RealtimeParticipant,
    RealtimeRecording,
    RealtimeRoom,
    Workspace,
    uuid_str,
)
from app.realtime.admission import RealtimeAdmissionAuthority, RealtimeAdmissionRejected
from app.realtime.livekit_runtime import (
    RealtimeProviderProtocolError,
    RealtimeProviderUnavailable,
    livekit_runtime,
)
from app.services.free_tier import require_non_free_user
from app.services.realtime_media_runtime import (
    RealtimeRecordingError,
    active_participants,
    apply_recording_consent,
    create_recording_request,
    participant_count,
    recording_snapshot,
    room_snapshot,
    update_from_provider_state,
)

router = APIRouter()
admission = RealtimeAdmissionAuthority()
logger = logging.getLogger(__name__)


class RealtimeRoomCreate(BaseModel):
    room_key: str = Field(min_length=2, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)
    workspace_id: str | None = None
    project_id: str | None = None
    room_type: Literal["meeting", "collaboration", "support", "studio"] = "meeting"
    media_mode: Literal["audio", "video", "audio_video"] = "audio_video"
    max_participants: int = Field(default=50, ge=1, le=100)
    allow_screen_share: bool = True


class RealtimeJoinRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    can_publish: bool = True
    can_subscribe: bool = True
    can_screen_share: bool = False


class RealtimeRecordingCreate(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    idempotency_key: str = Field(min_length=8, max_length=160)
    consent_version: str = Field(default="realtime-recording-v1", min_length=4, max_length=80)
    retention_days: int = Field(default=30, ge=1, le=90)


class RealtimeRecordingConsentUpdate(BaseModel):
    consented: bool


def _provider_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RealtimeProviderUnavailable):
        return HTTPException(status_code=503, detail="Realtime media provider is unavailable")
    if isinstance(exc, RealtimeProviderProtocolError):
        return HTTPException(status_code=502, detail="Realtime media provider rejected the request")
    return HTTPException(status_code=409, detail=str(exc))


def _can_manage(actor: UserRecord, room: RealtimeRoom) -> bool:
    granted = set(actor.permissions)
    return (
        room.created_by_id == actor.id
        or "*" in granted
        or "projects:write" in granted
        or "meetings:write" in granted
    )


async def _room_or_404(
    session: AsyncSession, actor: UserRecord, room_id: str, *, lock: bool = False
) -> RealtimeRoom:
    statement = select(RealtimeRoom).where(
        RealtimeRoom.id == room_id,
        RealtimeRoom.organization_id == actor.organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    room = await session.scalar(statement)
    if room is None:
        raise HTTPException(status_code=404, detail="Realtime room not found")
    return room


async def _recording_or_404(
    session: AsyncSession, actor: UserRecord, recording_id: str, *, lock: bool = False
) -> RealtimeRecording:
    statement = select(RealtimeRecording).where(
        RealtimeRecording.id == recording_id,
        RealtimeRecording.organization_id == actor.organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    recording = await session.scalar(statement)
    if recording is None:
        raise HTTPException(status_code=404, detail="Realtime recording not found")
    return recording


async def _validate_scope(
    session: AsyncSession, actor: UserRecord, data: RealtimeRoomCreate
) -> tuple[str | None, str | None]:
    workspace_id = data.workspace_id
    project_id = data.project_id
    if project_id:
        project = await session.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if workspace_id and workspace_id != project.workspace_id:
            raise HTTPException(status_code=422, detail="Realtime workspace does not match project")
        workspace_id = project.workspace_id
    if workspace_id:
        workspace = await session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.organization_id == actor.organization_id,
                Workspace.status == "active",
            )
        )
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace_id, project_id


async def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditEvent(
            id=uuid_str(),
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details={**details, "static_provider_credentials_returned": False},
        )
    )


async def _start_recording_provider(
    session: AsyncSession, actor: UserRecord, recording: RealtimeRecording
) -> RealtimeRecording:
    room = await _room_or_404(session, actor, recording.room_id)
    plan = livekit_runtime.plan_room(
        organization_id=actor.organization_id,
        room_id=room.id,
        max_participants=room.max_participants,
    )
    try:
        state = await livekit_runtime.start_room_recording(
            provider_room_name=plan.provider_room_name,
            output_relpath=recording.output_relpath,
        )
    except (RealtimeProviderUnavailable, RealtimeProviderProtocolError) as exc:
        recording.status = "failed"
        recording.error_code = "provider_start_failed"
        recording.error_message = type(exc).__name__
        recording.completed_at = datetime.now(UTC)
        recording.version += 1
        await session.commit()
        raise _provider_error(exc) from exc
    recording.provider_egress_id = state.egress_id
    recording.started_at = recording.started_at or datetime.now(UTC)
    recording = await update_from_provider_state(session, recording=recording, state=state)
    await _audit(
        session,
        actor,
        "realtime.recording.started",
        "realtime_recording",
        recording.id,
        {"room_id": room.id, "all_participant_consent": True},
    )
    await session.commit()
    return recording


async def _refresh_recording_provider(
    session: AsyncSession, actor: UserRecord, recording: RealtimeRecording
) -> RealtimeRecording:
    if recording.status == "starting" and not recording.provider_egress_id:
        return await _start_recording_provider(session, actor, recording)
    if recording.provider_egress_id and recording.status in {"starting", "active", "ending"}:
        try:
            state = await livekit_runtime.list_egress(egress_id=recording.provider_egress_id)
        except (RealtimeProviderUnavailable, RealtimeProviderProtocolError) as exc:
            raise _provider_error(exc) from exc
        recording = await update_from_provider_state(session, recording=recording, state=state)
        await session.commit()
    return recording


@router.get("/media/readiness")
async def readiness(actor: UserRecord = Depends(require_non_free_user)) -> dict[str, Any]:
    del actor
    return livekit_runtime.readiness_snapshot()


@router.get("/media/rooms")
async def list_rooms(
    limit: int = Query(default=50, ge=1, le=100),
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(RealtimeRoom)
                .where(RealtimeRoom.organization_id == actor.organization_id)
                .order_by(RealtimeRoom.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [
        room_snapshot(
            room,
            participant_count=await participant_count(
                session, organization_id=actor.organization_id, room_id=room.id
            ),
        )
        for room in rows
    ]


@router.post("/media/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(
    data: RealtimeRoomCreate,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not livekit_runtime.enabled:
        raise HTTPException(status_code=503, detail="Realtime media runtime is not activated")
    workspace_id, project_id = await _validate_scope(session, actor, data)
    try:
        await admission.provision_default_quota(session, organization_id=actor.organization_id)
        room = await admission.create_room(
            session,
            organization_id=actor.organization_id,
            created_by_id=actor.id,
            room_key=data.room_key,
            idempotency_key=data.idempotency_key,
            workspace_id=workspace_id,
            project_id=project_id,
            room_type=data.room_type,
            media_mode=data.media_mode,
            max_participants=data.max_participants,
            allow_screen_share=data.allow_screen_share,
        )
    except RealtimeAdmissionRejected as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.detail}) from exc
    if room.status == "open" and room.provider_adapter == "livekit":
        await session.commit()
        return room_snapshot(
            room,
            participant_count=await participant_count(
                session, organization_id=actor.organization_id, room_id=room.id
            ),
        )
    plan = livekit_runtime.plan_room(
        organization_id=actor.organization_id,
        room_id=room.id,
        max_participants=room.max_participants,
    )
    provider_created = False
    try:
        await livekit_runtime.provision_room(plan)
        provider_created = True
        room.provider_adapter = "livekit"
        room.provider_room_id_sha256 = hashlib.sha256(
            plan.provider_room_name.encode("utf-8")
        ).hexdigest()
        room.status = "open"
        room.opened_at = room.opened_at or datetime.now(UTC)
        room.version += 1
        await _audit(
            session,
            actor,
            "realtime.room.opened",
            "realtime_room",
            room.id,
            {"media_mode": room.media_mode, "max_participants": room.max_participants},
        )
        await session.commit()
    except (RealtimeProviderUnavailable, RealtimeProviderProtocolError) as exc:
        await session.rollback()
        raise _provider_error(exc) from exc
    except Exception:
        await session.rollback()
        if provider_created:
            try:
                await livekit_runtime.delete_room(plan.provider_room_name)
            except Exception:
                logger.warning(
                    "Failed to delete provider room after transaction rollback",
                    exc_info=True,
                )
        raise
    return room_snapshot(room, participant_count=0)


@router.post("/media/rooms/{room_id}/join")
async def join_room(
    room_id: str,
    data: RealtimeJoinRequest,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    room = await _room_or_404(session, actor, room_id, lock=True)
    if room.status != "open" or room.provider_adapter != "livekit":
        raise HTTPException(status_code=409, detail="Realtime room is not open")
    if data.can_screen_share and not data.can_publish:
        raise HTTPException(status_code=422, detail="Screen share requires publish authority")
    try:
        granted = await admission.issue_grant(
            session,
            organization_id=actor.organization_id,
            room_id=room.id,
            user_id=actor.id,
            issued_by_id=actor.id,
            participant_key=actor.id,
            idempotency_key=data.idempotency_key,
            role="attendee",
            can_publish=data.can_publish,
            can_subscribe=data.can_subscribe,
            can_screen_share=data.can_screen_share,
        )
        plan = livekit_runtime.plan_room(
            organization_id=actor.organization_id,
            room_id=room.id,
            max_participants=room.max_participants,
        )
        provider_session = livekit_runtime.participant_session(
            room_name=plan.provider_room_name,
            participant_id=granted.participant.id,
            participant_name=actor.name,
            can_publish=data.can_publish,
            can_subscribe=data.can_subscribe,
        )
        consumed = await admission.consume_grant(
            session,
            organization_id=actor.organization_id,
            token=granted.token,
            node_id="livekit-token-issuer",
        )
        consumed.provider_adapter = "livekit"
        consumed.provider_token_jti_sha256 = provider_session.token_jti_sha256
        granted.participant.capabilities = {
            "provider": "livekit",
            "can_publish": data.can_publish,
            "can_subscribe": data.can_subscribe,
            "can_screen_share": data.can_screen_share,
        }
        granted.participant.version += 1
        await _audit(
            session,
            actor,
            "realtime.room.join_token.issued",
            "realtime_room",
            room.id,
            {"participant_id": granted.participant.id, "ttl_seconds": 300},
        )
        await session.commit()
    except RealtimeAdmissionRejected as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.detail}) from exc
    except (RealtimeProviderUnavailable, RealtimeProviderProtocolError) as exc:
        await session.rollback()
        raise _provider_error(exc) from exc
    return {
        "room": room_snapshot(
            room,
            participant_count=await participant_count(
                session, organization_id=actor.organization_id, room_id=room.id
            ),
        ),
        "participant_id": granted.participant.id,
        "session": provider_session.response_payload(),
        "admission_grant_returned": False,
    }


@router.post("/media/rooms/{room_id}/leave")
async def leave_room(
    room_id: str,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    room = await _room_or_404(session, actor, room_id)
    participant = await session.scalar(
        select(RealtimeParticipant).where(
            RealtimeParticipant.organization_id == actor.organization_id,
            RealtimeParticipant.room_id == room.id,
            RealtimeParticipant.user_id == actor.id,
            RealtimeParticipant.status.in_(("admitted", "connected")),
        )
    )
    if participant is None:
        return {"room_id": room.id, "left": False}
    plan = livekit_runtime.plan_room(
        organization_id=actor.organization_id,
        room_id=room.id,
        max_participants=room.max_participants,
    )
    try:
        await livekit_runtime.remove_participant(
            provider_room_name=plan.provider_room_name,
            participant_identity=participant.id,
        )
    except RealtimeProviderProtocolError as exc:
        # An already-disconnected participant is safe to finalize locally.
        if "404" not in str(exc) and "not_found" not in str(exc):
            raise _provider_error(exc) from exc
    except RealtimeProviderUnavailable as exc:
        raise _provider_error(exc) from exc
    participant.status = "left"
    participant.left_at = datetime.now(UTC)
    participant.node_id = None
    participant.connection_count = 0
    participant.presence_lease_expires_at = None
    participant.presence_fencing_token += 1
    participant.version += 1
    grants = list(
        (
            await session.scalars(
                select(RealtimeAdmissionGrant).where(
                    RealtimeAdmissionGrant.participant_id == participant.id,
                    RealtimeAdmissionGrant.status == "issued",
                )
            )
        ).all()
    )
    for grant in grants:
        grant.status = "revoked"
        grant.revoked_at = datetime.now(UTC)
        grant.version += 1
    await _audit(session, actor, "realtime.room.left", "realtime_room", room.id, {})
    await session.commit()
    return {"room_id": room.id, "left": True}


@router.post("/media/rooms/{room_id}/close")
async def close_room(
    room_id: str,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    room = await _room_or_404(session, actor, room_id, lock=True)
    if not _can_manage(actor, room):
        raise HTTPException(status_code=403, detail="Only the room manager can close this room")
    if room.status == "closed":
        return room_snapshot(room, participant_count=0)
    plan = livekit_runtime.plan_room(
        organization_id=actor.organization_id,
        room_id=room.id,
        max_participants=room.max_participants,
    )
    try:
        await livekit_runtime.delete_room(plan.provider_room_name)
    except RealtimeProviderProtocolError as exc:
        if "404" not in str(exc) and "not_found" not in str(exc):
            raise _provider_error(exc) from exc
    except RealtimeProviderUnavailable as exc:
        raise _provider_error(exc) from exc
    room.status = "closed"
    room.closed_at = datetime.now(UTC)
    room.version += 1
    for participant in await active_participants(
        session, organization_id=actor.organization_id, room_id=room.id
    ):
        participant.status = "left"
        participant.left_at = datetime.now(UTC)
        participant.version += 1
    await _audit(session, actor, "realtime.room.closed", "realtime_room", room.id, {})
    await session.commit()
    return room_snapshot(room, participant_count=0)


@router.get("/media/rooms/{room_id}/recordings")
async def list_recordings(
    room_id: str,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _room_or_404(session, actor, room_id)
    rows = list(
        (
            await session.scalars(
                select(RealtimeRecording)
                .where(
                    RealtimeRecording.organization_id == actor.organization_id,
                    RealtimeRecording.room_id == room_id,
                )
                .order_by(RealtimeRecording.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    refreshed: list[dict[str, Any]] = []
    for row in rows:
        row = await _refresh_recording_provider(session, actor, row)
        refreshed.append(recording_snapshot(row))
    return refreshed


@router.post("/media/rooms/{room_id}/recordings", status_code=status.HTTP_201_CREATED)
async def request_recording(
    room_id: str,
    data: RealtimeRecordingCreate,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    room = await _room_or_404(session, actor, room_id, lock=True)
    if not _can_manage(actor, room):
        raise HTTPException(status_code=403, detail="Only the room manager can request recording")
    try:
        recording = await create_recording_request(
            session,
            organization_id=actor.organization_id,
            room=room,
            requested_by_id=actor.id,
            title=data.title,
            idempotency_key=data.idempotency_key,
            consent_version=data.consent_version,
            retention_days=data.retention_days,
        )
    except RealtimeRecordingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _audit(
        session,
        actor,
        "realtime.recording.requested",
        "realtime_recording",
        recording.id,
        {
            "room_id": room.id,
            "required_consent_count": recording.required_consent_count,
            "retention_days": data.retention_days,
        },
    )
    await session.commit()
    return recording_snapshot(recording)


@router.post("/media/recordings/{recording_id}/consent")
async def recording_consent(
    recording_id: str,
    data: RealtimeRecordingConsentUpdate,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        transition = await apply_recording_consent(
            session,
            organization_id=actor.organization_id,
            recording_id=recording_id,
            user_id=actor.id,
            consented=data.consented,
        )
    except RealtimeRecordingError as exc:
        code = 403 if "current user" in str(exc) else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    await _audit(
        session,
        actor,
        "realtime.recording.consent.updated",
        "realtime_recording",
        transition.recording.id,
        {"consented": data.consented},
    )
    await session.commit()
    recording = transition.recording
    if transition.start_provider:
        recording = await _start_recording_provider(session, actor, recording)
    return recording_snapshot(recording)


@router.get("/media/recordings/{recording_id}")
async def get_recording(
    recording_id: str,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    recording = await _recording_or_404(session, actor, recording_id)
    room = await _room_or_404(session, actor, recording.room_id)
    participant = await session.scalar(
        select(RealtimeParticipant.id).where(
            RealtimeParticipant.organization_id == actor.organization_id,
            RealtimeParticipant.room_id == room.id,
            RealtimeParticipant.user_id == actor.id,
        )
    )
    if participant is None and not _can_manage(actor, room):
        raise HTTPException(status_code=403, detail="Recording is unavailable to this user")
    recording = await _refresh_recording_provider(session, actor, recording)
    return recording_snapshot(recording)


@router.post("/media/recordings/{recording_id}/stop")
async def stop_recording(
    recording_id: str,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    recording = await _recording_or_404(session, actor, recording_id, lock=True)
    room = await _room_or_404(session, actor, recording.room_id)
    if not _can_manage(actor, room):
        raise HTTPException(status_code=403, detail="Only the room manager can stop recording")
    if recording.status in {"completed", "failed", "declined", "cancelled"}:
        return recording_snapshot(recording)
    if not recording.provider_egress_id:
        recording.status = "cancelled"
        recording.stopped_at = datetime.now(UTC)
        recording.version += 1
        await session.commit()
        return recording_snapshot(recording)
    try:
        state = await livekit_runtime.stop_egress(egress_id=recording.provider_egress_id)
    except RealtimeProviderProtocolError as exc:
        # If provider already completed, refresh is authoritative.
        if "failed_precondition" in str(exc) or "COMPLETE" in str(exc):
            recording = await _refresh_recording_provider(session, actor, recording)
            return recording_snapshot(recording)
        raise _provider_error(exc) from exc
    except RealtimeProviderUnavailable as exc:
        raise _provider_error(exc) from exc
    recording.stopped_at = datetime.now(UTC)
    recording = await update_from_provider_state(session, recording=recording, state=state)
    await _audit(session, actor, "realtime.recording.stop.requested", "realtime_recording", recording.id, {})
    await session.commit()
    return recording_snapshot(recording)
