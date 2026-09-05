"""Durable Phase 36H realtime room, consent and recording runtime helpers."""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AuditEvent,
    RealtimeParticipant,
    RealtimeRecording,
    RealtimeRecordingConsent,
    RealtimeRoom,
    RealtimeTenantQuota,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    uuid_str,
)
from app.realtime.livekit_runtime import (
    ProviderEgressState,
    livekit_runtime,
)
from app.services import production_studio

_ACTIVE_PARTICIPANT_STATUSES = ("admitted", "connected")
_ACTIVE_RECORDING_STATUSES = ("awaiting_consent", "starting", "active", "ending")
_TERMINAL_RECORDING_STATUSES = ("completed", "failed", "declined", "cancelled")


class RealtimeRecordingError(RuntimeError):
    """A durable recording transition could not be completed safely."""


@dataclass(frozen=True, slots=True)
class ConsentTransition:
    recording: RealtimeRecording
    start_provider: bool


def room_snapshot(room: RealtimeRoom, *, participant_count: int = 0) -> dict[str, Any]:
    return {
        "id": room.id,
        "room_key": room.room_key,
        "workspace_id": room.workspace_id,
        "project_id": room.project_id,
        "created_by_id": room.created_by_id,
        "room_type": room.room_type,
        "media_mode": room.media_mode,
        "status": room.status,
        "provider": room.provider_adapter,
        "max_participants": room.max_participants,
        "participant_count": participant_count,
        "allow_screen_share": room.allow_screen_share,
        "recording_policy": room.recording_policy,
        "opened_at": room.opened_at.isoformat() if room.opened_at else None,
        "closed_at": room.closed_at.isoformat() if room.closed_at else None,
        "created_at": room.created_at.isoformat(),
        "provider_room_identifier_returned": False,
    }


def recording_snapshot(recording: RealtimeRecording) -> dict[str, Any]:
    return {
        "id": recording.id,
        "room_id": recording.room_id,
        "requested_by_id": recording.requested_by_id,
        "title": recording.title,
        "status": recording.status,
        "provider": recording.provider_adapter,
        "output_format": recording.output_format,
        "media_type": recording.media_type,
        "consent_version": recording.consent_version,
        "required_consent_count": recording.required_consent_count,
        "consented_count": recording.consented_count,
        "retention_until": recording.retention_until.isoformat(),
        "output_checksum_sha256": recording.output_checksum_sha256,
        "output_size_bytes": recording.output_size_bytes,
        "output_duration_ms": recording.output_duration_ms,
        "studio_job_id": recording.studio_job_id,
        "studio_asset_id": recording.studio_asset_id,
        "error_code": recording.error_code,
        "started_at": recording.started_at.isoformat() if recording.started_at else None,
        "completed_at": recording.completed_at.isoformat() if recording.completed_at else None,
        "created_at": recording.created_at.isoformat(),
        "provider_egress_identifier_returned": False,
        "raw_consent_material_returned": False,
    }


async def participant_count(
    session: AsyncSession, *, organization_id: str, room_id: str
) -> int:
    return int(
        await session.scalar(
            select(func.count(RealtimeParticipant.id)).where(
                RealtimeParticipant.organization_id == organization_id,
                RealtimeParticipant.room_id == room_id,
                RealtimeParticipant.status.in_(_ACTIVE_PARTICIPANT_STATUSES),
            )
        )
        or 0
    )


async def active_participants(
    session: AsyncSession, *, organization_id: str, room_id: str
) -> list[RealtimeParticipant]:
    return list(
        (
            await session.scalars(
                select(RealtimeParticipant)
                .where(
                    RealtimeParticipant.organization_id == organization_id,
                    RealtimeParticipant.room_id == room_id,
                    RealtimeParticipant.status.in_(_ACTIVE_PARTICIPANT_STATUSES),
                )
                .order_by(RealtimeParticipant.id)
            )
        ).all()
    )


async def create_recording_request(
    session: AsyncSession,
    *,
    organization_id: str,
    room: RealtimeRoom,
    requested_by_id: str,
    title: str,
    idempotency_key: str,
    consent_version: str,
    retention_days: int,
) -> RealtimeRecording:
    existing = await session.scalar(
        select(RealtimeRecording).where(
            RealtimeRecording.organization_id == organization_id,
            RealtimeRecording.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.room_id != room.id or existing.requested_by_id != requested_by_id:
            raise RealtimeRecordingError("recording idempotency key is bound to another request")
        return existing
    if room.status != "open":
        raise RealtimeRecordingError("room is not open for recording")
    quota = await session.scalar(
        select(RealtimeTenantQuota)
        .where(RealtimeTenantQuota.organization_id == organization_id)
        .with_for_update()
    )
    if quota is None or not quota.enabled or quota.max_concurrent_recordings <= 0:
        raise RealtimeRecordingError("realtime recording is disabled for this tenant")
    concurrent = int(
        await session.scalar(
            select(func.count(RealtimeRecording.id)).where(
                RealtimeRecording.organization_id == organization_id,
                RealtimeRecording.status.in_(_ACTIVE_RECORDING_STATUSES),
            )
        )
        or 0
    )
    if concurrent >= quota.max_concurrent_recordings:
        raise RealtimeRecordingError("tenant concurrent recording limit reached")
    participants = await active_participants(
        session, organization_id=organization_id, room_id=room.id
    )
    if not participants:
        raise RealtimeRecordingError("recording requires at least one admitted participant")
    clean_title = title.strip()
    if not clean_title:
        raise RealtimeRecordingError("recording title is required")
    recording_id = uuid_str()
    recording = RealtimeRecording(
        id=recording_id,
        organization_id=organization_id,
        room_id=room.id,
        requested_by_id=requested_by_id,
        idempotency_key=idempotency_key.strip(),
        title=clean_title[:240],
        status="awaiting_consent",
        provider_adapter="livekit",
        output_format="mp4",
        output_relpath=f"{recording_id}.mp4",
        media_type="video/mp4",
        consent_version=consent_version.strip()[:80],
        required_consent_count=len(participants),
        consented_count=0,
        retention_until=livekit_runtime.retention_deadline(retention_days),
        provider_metadata={"all_participant_consent_required": True},
    )
    session.add(recording)
    for participant in participants:
        session.add(
            RealtimeRecordingConsent(
                id=uuid_str(),
                organization_id=organization_id,
                recording_id=recording_id,
                participant_id=participant.id,
                user_id=participant.user_id,
                status="pending",
                consent_version=recording.consent_version,
            )
        )
    room.recording_policy = "all_participant_consent"
    room.version += 1
    await session.flush()
    return recording


async def apply_recording_consent(
    session: AsyncSession,
    *,
    organization_id: str,
    recording_id: str,
    user_id: str,
    consented: bool,
) -> ConsentTransition:
    recording = await session.scalar(
        select(RealtimeRecording)
        .where(
            RealtimeRecording.id == recording_id,
            RealtimeRecording.organization_id == organization_id,
        )
        .with_for_update()
    )
    if recording is None:
        raise RealtimeRecordingError("recording was not found")
    if recording.status in _TERMINAL_RECORDING_STATUSES:
        return ConsentTransition(recording, False)
    if recording.status not in {"awaiting_consent", "starting"}:
        raise RealtimeRecordingError("recording is no longer accepting consent")
    consent = await session.scalar(
        select(RealtimeRecordingConsent)
        .where(
            RealtimeRecordingConsent.recording_id == recording.id,
            RealtimeRecordingConsent.organization_id == organization_id,
            RealtimeRecordingConsent.user_id == user_id,
        )
        .with_for_update()
    )
    if consent is None:
        raise RealtimeRecordingError("current user is not an admitted recording participant")
    now = datetime.now(UTC)
    if consented:
        if consent.status != "consented":
            consent.status = "consented"
            consent.consented_at = now
            consent.declined_at = None
            consent.version += 1
    else:
        consent.status = "declined"
        consent.declined_at = now
        consent.consented_at = None
        consent.version += 1
        recording.status = "declined"
        recording.error_code = "participant_declined"
        recording.error_message = "A required participant declined recording consent"
        recording.version += 1
    rows = list(
        (
            await session.scalars(
                select(RealtimeRecordingConsent)
                .where(RealtimeRecordingConsent.recording_id == recording.id)
                .order_by(RealtimeRecordingConsent.participant_id)
            )
        ).all()
    )
    recording.required_consent_count = len(rows)
    recording.consented_count = sum(item.status == "consented" for item in rows)
    start_provider = False
    if recording.status == "awaiting_consent" and rows and all(
        item.status == "consented" and item.consented_at is not None for item in rows
    ):
        material = "|".join(
            f"{item.participant_id}:{item.consent_version}:{item.consented_at.astimezone(UTC).isoformat()}"
            for item in rows
            if item.consented_at is not None
        )
        recording.consent_digest_sha256 = hashlib.sha256(material.encode("utf-8")).hexdigest()
        recording.status = "starting"
        recording.error_code = None
        recording.error_message = None
        recording.version += 1
        start_provider = recording.provider_egress_id is None
    await session.flush()
    return ConsentTransition(recording, start_provider)


def _provider_status_to_local(state: ProviderEgressState) -> str:
    if state.status == "EGRESS_STARTING":
        return "starting"
    if state.status == "EGRESS_ACTIVE":
        return "active"
    if state.status == "EGRESS_ENDING":
        return "ending"
    if state.status == "EGRESS_COMPLETE":
        return "completed"
    return "failed"


def _duration_ms(state: ProviderEgressState) -> int | None:
    if not state.file_results:
        return None
    raw = state.file_results[0].get("duration")
    if not isinstance(raw, (str, int, float)):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # LiveKit protobuf file results report nanoseconds.
    return value // 1_000_000 if value >= 1_000_000 else value


def _sha256_path(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    header = b""
    with path.open("rb") as handle:
        header = handle.read(32)
        if len(header) < 12 or header[4:8] != b"ftyp":
            raise RealtimeRecordingError("recording output is not a valid MP4 container")
        digest.update(header)
        size = len(header)
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            if size > settings.REALTIME_RECORDING_MAX_BYTES:
                raise RealtimeRecordingError("recording exceeds configured size limit")
            digest.update(chunk)
    if size < 1024:
        raise RealtimeRecordingError("recording output is implausibly small")
    return digest.hexdigest(), size


def _studio_recording_destination(
    *, organization_id: str, asset_id: str, filename: str
) -> Path:
    root = production_studio.protected_root()
    directory = (root / organization_id / asset_id / "revision-1").resolve()
    if root not in directory.parents:
        raise RealtimeRecordingError("Studio recording path escaped protected root")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / filename
    if destination.parent != directory:
        raise RealtimeRecordingError("Studio recording filename is invalid")
    return destination


async def finalize_completed_recording(
    session: AsyncSession,
    *,
    recording: RealtimeRecording,
    state: ProviderEgressState,
) -> RealtimeRecording:
    if recording.studio_asset_id:
        recording.status = "completed"
        return recording
    existing_studio_asset_id = recording.studio_asset_id
    source = livekit_runtime.recording_path(recording.output_relpath)
    try:
        stat_result = os.lstat(source)
    except OSError as exc:
        raise RealtimeRecordingError("completed recording payload is unavailable") from exc
    if not source.is_file() or source.is_symlink() or stat_result.st_nlink != 1:
        raise RealtimeRecordingError("completed recording payload is unsafe")
    checksum, size = _sha256_path(source)
    job_id = uuid_str()
    asset_id = uuid_str()
    filename = f"{production_studio.slug(recording.title)}-realtime.mp4"
    destination = _studio_recording_destination(
        organization_id=recording.organization_id,
        asset_id=asset_id,
        filename=filename,
    )
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        copied_checksum, copied_size = _sha256_path(destination)
        if copied_checksum != checksum or copied_size != size:
            raise RealtimeRecordingError("Studio recording copy verification failed")
        room = await session.get(RealtimeRoom, recording.room_id)
        project_id = room.project_id if room is not None else None
        workspace_id = room.workspace_id if room is not None else None
        duration_ms = _duration_ms(state)
        now = datetime.now(UTC)
        job = StudioJob(
            id=job_id,
            organization_id=recording.organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            requested_by_id=recording.requested_by_id,
            department="video",
            output_kind="realtime_recording",
            title=recording.title,
            brief="Consent-governed realtime room recording",
            language="und",
            style="realtime",
            provider_mode="livekit_egress",
            provider="livekit",
            status="completed",
            progress=100,
            safety_status="passed",
            safety_findings=[],
            request_metadata={
                "room_id": recording.room_id,
                "all_participant_consent": True,
                "consent_digest_sha256": recording.consent_digest_sha256,
            },
            result_metadata={
                "checksum": checksum,
                "size_bytes": size,
                "duration_ms": duration_ms,
                "source": "realtime-recording",
            },
            attempts=1,
            max_attempts=1,
            started_at=recording.started_at,
            completed_at=now,
        )
        asset = StudioAsset(
            id=asset_id,
            organization_id=recording.organization_id,
            job_id=job_id,
            project_id=project_id,
            created_by_id=recording.requested_by_id,
            department="video",
            asset_type="realtime_recording",
            title=recording.title,
            filename=filename,
            media_type="video/mp4",
            storage_path=str(destination),
            checksum=checksum,
            size_bytes=size,
            status="active",
            current_revision=1,
            asset_metadata={
                "source": "livekit-egress",
                "room_id": recording.room_id,
                "consent_digest_sha256": recording.consent_digest_sha256,
                "retention_until": recording.retention_until.isoformat(),
                "provider_request_identifier_returned": False,
            },
        )
        revision = StudioAssetRevision(
            id=uuid_str(),
            organization_id=recording.organization_id,
            asset_id=asset_id,
            job_id=job_id,
            created_by_id=recording.requested_by_id,
            revision_number=1,
            filename=filename,
            media_type="video/mp4",
            storage_path=str(destination),
            checksum=checksum,
            size_bytes=size,
            change_note="Initial consent-governed realtime recording",
            revision_metadata={"source": "livekit-egress"},
            status="active",
        )
        # These models intentionally avoid ORM relationships. Flush in FK order
        # so PostgreSQL never observes a recording reference before its durable
        # Studio job/asset rows exist.
        session.add(job)
        await session.flush()
        session.add(asset)
        await session.flush()
        session.add(revision)
        await session.flush()
        recording.status = "completed"
        recording.output_checksum_sha256 = checksum
        recording.output_size_bytes = size
        recording.output_duration_ms = duration_ms
        recording.studio_job_id = job_id
        recording.studio_asset_id = asset_id
        recording.provider_metadata = {
            **dict(recording.provider_metadata or {}),
            "provider_status": state.status,
            "file_results": [dict(item) for item in state.file_results],
            "provider_identifier_returned": False,
        }
        recording.completed_at = now
        recording.error_code = None
        recording.error_message = None
        recording.version += 1
        session.add(
            AuditEvent(
                id=uuid_str(),
                organization_id=recording.organization_id,
                user_id=recording.requested_by_id,
                action="realtime.recording.completed",
                resource_type="realtime_recording",
                resource_id=recording.id,
                details={
                    "room_id": recording.room_id,
                    "studio_asset_id": asset_id,
                    "checksum": checksum,
                    "size_bytes": size,
                    "all_participant_consent": True,
                },
            )
        )
        await session.flush()
        source.unlink(missing_ok=True)
        return recording
    except Exception:
        temporary.unlink(missing_ok=True)
        if existing_studio_asset_id is None:
            destination.unlink(missing_ok=True)
        raise


async def update_from_provider_state(
    session: AsyncSession,
    *,
    recording: RealtimeRecording,
    state: ProviderEgressState,
) -> RealtimeRecording:
    recording.provider_metadata = {
        **dict(recording.provider_metadata or {}),
        "provider_status": state.status,
        "provider_error_present": bool(state.error),
        "file_results": [dict(item) for item in state.file_results],
    }
    recording.status = _provider_status_to_local(state)
    recording.error_code = None if not state.error else "provider_egress_error"
    recording.error_message = state.error
    recording.version += 1
    if state.completed:
        return await finalize_completed_recording(session, recording=recording, state=state)
    if state.terminal and not state.completed:
        recording.completed_at = datetime.now(UTC)
    await session.flush()
    return recording
