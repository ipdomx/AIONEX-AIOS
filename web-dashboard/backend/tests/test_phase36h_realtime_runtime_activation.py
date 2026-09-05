from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.db.base import Base, SessionLocal
from app.db.models import (
    Organization,
    RealtimeParticipant,
    RealtimeRecording,
    RealtimeRecordingConsent,
    RealtimeRoom,
    RealtimeTenantQuota,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
)
from app.realtime.livekit_runtime import (
    LiveKitRuntime,
    ProviderEgressState,
    RealtimeProviderUnavailable,
)
from app.services.realtime_media_runtime import (
    apply_recording_consent,
    create_recording_request,
    finalize_completed_recording,
)


def _secret(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[LiveKitRuntime, str, str]:
    api_key = "test-livekit-key"
    api_secret = "test-livekit-secret-0123456789abcdef"
    turn_secret = "test-coturn-secret-0123456789abcdef"
    key_file = _secret(tmp_path / "api-key", api_key)
    secret_file = _secret(tmp_path / "api-secret", api_secret)
    turn_file = _secret(tmp_path / "turn-secret", turn_secret)
    monkeypatch.setattr(settings, "REALTIME_MEDIA_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "REALTIME_SIGNALING_URL", "wss://api.vip-e.net/livekit")
    monkeypatch.setattr(settings, "REALTIME_LIVEKIT_INTERNAL_URL", "http://realtime-livekit:7880")
    monkeypatch.setattr(settings, "REALTIME_LIVEKIT_API_KEY_FILE", str(key_file))
    monkeypatch.setattr(settings, "REALTIME_LIVEKIT_API_SECRET_FILE", str(secret_file))
    monkeypatch.setattr(settings, "REALTIME_TURN_SHARED_SECRET_FILE", str(turn_file))
    monkeypatch.setattr(settings, "REALTIME_TURN_PUBLIC_HOST", "203.0.113.25")
    monkeypatch.setattr(settings, "REALTIME_TURN_PORT", 3478)
    monkeypatch.setattr(settings, "REALTIME_PROVIDER_TOKEN_TTL_SECONDS", 300)
    monkeypatch.setattr(settings, "REALTIME_TURN_CREDENTIAL_TTL_SECONDS", 600)
    return LiveKitRuntime(), api_secret, turn_secret


def test_livekit_session_is_short_lived_and_static_secrets_never_return(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, api_secret, turn_secret = _runtime(monkeypatch, tmp_path)
    before = int(time.time())
    session = runtime.participant_session(
        room_name="aios-rt-test-room",
        participant_id="participant-1",
        participant_name="Realtime User",
        can_publish=True,
        can_subscribe=True,
    )
    payload = jwt.decode(session.token, api_secret, algorithms=["HS256"])
    assert payload["sub"] == "participant-1"
    assert payload["video"]["roomJoin"] is True
    assert payload["video"]["room"] == "aios-rt-test-room"
    assert before + 295 <= payload["exp"] <= before + 305
    assert session.token_jti_sha256 == hashlib.sha256(payload["jti"].encode()).hexdigest()
    response = session.response_payload()
    assert response["server_url"] == "wss://api.vip-e.net/livekit"
    assert api_secret not in repr(response)
    assert turn_secret not in repr(response)
    assert "test-livekit-key" not in repr(response)
    turn = response["ice_servers"][1]
    credential_name = turn["username"]
    expiry_text, opaque_label = credential_name.split(":", 1)
    assert "participant-1" not in credential_name
    assert len(opaque_label) == 32
    assert all(ch in "0123456789abcdef" for ch in opaque_label)
    assert int(expiry_text) <= before + 605
    decoded_credential = base64.b64decode(turn["credential"], validate=True)
    # Coturn REST HMAC-SHA1 credentials are 20-byte MACs; the protocol
    # compatibility primitive is exercised in runtime code, not reimplemented
    # here over any identifier-like test value.
    assert len(decoded_credential) == 20
    readiness = runtime.readiness_snapshot()
    assert readiness["enabled"] is True
    assert readiness["static_provider_credentials_returned"] is False


def test_realtime_secret_files_must_be_private(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _, _ = _runtime(monkeypatch, tmp_path)
    os.chmod(Path(settings.REALTIME_LIVEKIT_API_SECRET_FILE), 0o640)
    with pytest.raises(RealtimeProviderUnavailable, match="group/world accessible"):
        runtime.participant_session(
            room_name="aios-rt-test-room",
            participant_id="participant-1",
            participant_name="Realtime User",
            can_publish=True,
            can_subscribe=True,
        )


@pytest.mark.asyncio
async def test_room_service_admin_mutations_use_livekit_113_admin_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _, _ = _runtime(monkeypatch, tmp_path)
    calls: list[dict[str, object]] = []

    async def fake_twirp(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(runtime, "_twirp", fake_twirp)
    await runtime.delete_room("aios-rt-room")
    await runtime.remove_participant(
        provider_room_name="aios-rt-room", participant_identity="participant-1"
    )

    expected = {
        "roomCreate": True,
        "roomList": True,
        "roomAdmin": True,
        "roomRecord": True,
    }
    assert len(calls) == 2
    assert all(call["video_grant"] == expected for call in calls)
    assert calls[0]["method"] == "DeleteRoom"
    assert calls[1]["method"] == "RemoveParticipant"


def test_realtime_recording_schema_contains_no_raw_credentials_or_consent_tokens() -> None:
    recording = Base.metadata.tables["realtime_recordings"]
    consent = Base.metadata.tables["realtime_recording_consents"]
    forbidden = {
        "token",
        "provider_token",
        "api_key",
        "api_secret",
        "turn_secret",
        "credential",
        "consent_token",
        "raw_consent",
    }
    assert forbidden.isdisjoint(recording.c.keys())
    assert forbidden.isdisjoint(consent.c.keys())
    assert "consent_digest_sha256" in recording.c
    assert "provider_egress_id" in recording.c
    assert "status" in consent.c
    assert "consented_at" in consent.c


async def _seed_scope(suffix: str, *, participants: int = 2) -> tuple[str, list[str], str]:
    organization_id = str(uuid4())
    user_ids = [str(uuid4()) for _ in range(participants)]
    room_id = str(uuid4())
    async with SessionLocal() as session:
        session.add(
            Organization(
                id=organization_id,
                name=f"Realtime activation {suffix}",
                slug=f"rt-activation-{suffix}",
                plan="enterprise",
                status="active",
            )
        )
        await session.flush()
        session.add_all(
            [
                User(
                    id=user_id,
                    organization_id=organization_id,
                    email=f"{suffix}-{index}@realtime.invalid",
                    name=f"Realtime User {index}",
                    password_hash="unused",
                    status="active",
                )
                for index, user_id in enumerate(user_ids)
            ]
        )
        # RealtimeRoom has a tenant-composite creator FK. Flush users first so
        # PostgreSQL validates the real production ordering rather than relying
        # on ORM relationship metadata that these schema-only models do not use.
        await session.flush()
        session.add(
            RealtimeTenantQuota(
                id=str(uuid4()),
                organization_id=organization_id,
                enabled=True,
                max_concurrent_recordings=2,
            )
        )
        session.add(
            RealtimeRoom(
                id=room_id,
                organization_id=organization_id,
                created_by_id=user_ids[0],
                room_key=f"room-{suffix}",
                idempotency_key=f"room-idempotency-{suffix}",
                room_type="meeting",
                media_mode="audio_video",
                status="open",
                provider_adapter="livekit",
                max_participants=50,
                allow_screen_share=True,
            )
        )
        await session.flush()
        session.add_all(
            [
                RealtimeParticipant(
                    id=str(uuid4()),
                    organization_id=organization_id,
                    room_id=room_id,
                    user_id=user_id,
                    participant_key=user_id,
                    role="attendee",
                    status="admitted",
                    can_publish=True,
                    can_subscribe=True,
                    can_screen_share=False,
                    hidden=False,
                    connection_count=0,
                    capabilities={},
                )
                for user_id in user_ids
            ]
        )
        await session.commit()
    return organization_id, user_ids, room_id


async def _cleanup_scope(organization_id: str) -> None:
    async with SessionLocal() as session:
        # Organization cascades realtime and Studio rows; explicit delete keeps the
        # test deterministic even on SQLite-like fallback engines.
        for model in (StudioAssetRevision, StudioAsset, StudioJob):
            await session.execute(delete(model).where(model.organization_id == organization_id))
        await session.execute(delete(RealtimeRecordingConsent).where(RealtimeRecordingConsent.organization_id == organization_id))
        await session.execute(delete(RealtimeRecording).where(RealtimeRecording.organization_id == organization_id))
        await session.execute(delete(RealtimeParticipant).where(RealtimeParticipant.organization_id == organization_id))
        await session.execute(delete(RealtimeRoom).where(RealtimeRoom.organization_id == organization_id))
        await session.execute(delete(RealtimeTenantQuota).where(RealtimeTenantQuota.organization_id == organization_id))
        await session.execute(delete(User).where(User.organization_id == organization_id))
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()


@pytest.mark.asyncio
async def test_recording_waits_for_every_admitted_participant_consent() -> None:
    suffix = uuid4().hex[:10]
    organization_id, user_ids, room_id = await _seed_scope(suffix)
    try:
        async with SessionLocal() as session:
            room = await session.get(RealtimeRoom, room_id)
            assert room is not None
            recording = await create_recording_request(
                session,
                organization_id=organization_id,
                room=room,
                requested_by_id=user_ids[0],
                title="Consent governed meeting",
                idempotency_key=f"recording-{suffix}",
                consent_version="realtime-recording-v1",
                retention_days=30,
            )
            await session.commit()
            recording_id = recording.id

        async with SessionLocal() as session:
            first = await apply_recording_consent(
                session,
                organization_id=organization_id,
                recording_id=recording_id,
                user_id=user_ids[0],
                consented=True,
            )
            assert first.start_provider is False
            assert first.recording.status == "awaiting_consent"
            assert first.recording.consented_count == 1
            await session.commit()

        async with SessionLocal() as session:
            second = await apply_recording_consent(
                session,
                organization_id=organization_id,
                recording_id=recording_id,
                user_id=user_ids[1],
                consented=True,
            )
            assert second.start_provider is True
            assert second.recording.status == "starting"
            assert second.recording.consented_count == 2
            assert second.recording.consent_digest_sha256
            await session.commit()
    finally:
        await _cleanup_scope(organization_id)


@pytest.mark.asyncio
async def test_completed_recording_requires_mp4_and_moves_verified_asset_to_studio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suffix = uuid4().hex[:10]
    organization_id, user_ids, room_id = await _seed_scope(suffix, participants=1)
    recording_root = tmp_path / "recordings"
    studio_root = tmp_path / "studio"
    recording_root.mkdir(mode=0o700)
    monkeypatch.setattr(settings, "REALTIME_RECORDING_ROOT", str(recording_root))
    monkeypatch.setattr(settings, "REALTIME_RECORDING_MAX_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(settings, "STUDIO_ASSET_ROOT", str(studio_root))
    try:
        async with SessionLocal() as session:
            room = await session.get(RealtimeRoom, room_id)
            assert room is not None
            recording = await create_recording_request(
                session,
                organization_id=organization_id,
                room=room,
                requested_by_id=user_ids[0],
                title="Verified realtime recording",
                idempotency_key=f"recording-{suffix}",
                consent_version="realtime-recording-v1",
                retention_days=30,
            )
            consent = await apply_recording_consent(
                session,
                organization_id=organization_id,
                recording_id=recording.id,
                user_id=user_ids[0],
                consented=True,
            )
            recording = consent.recording
            recording.provider_egress_id = "EG_test"
            recording.started_at = recording.created_at
            await session.commit()
            recording_id = recording.id
            output_relpath = recording.output_relpath

        # ISO BMFF MP4 signature plus a bounded payload. The runtime performs the
        # lightweight container gate here; real production acceptance also ffprobes
        # the provider output before the final gate is signed.
        body = (24).to_bytes(4, "big") + b"ftyp" + b"isom" + b"\x00" * 12 + b"A" * 4096
        source = recording_root / output_relpath
        source.write_bytes(body)
        os.chmod(source, 0o600)
        state = ProviderEgressState(
            egress_id="EG_test",
            status="EGRESS_COMPLETE",
            error=None,
            file_results=(
                {"duration": 5_000_000_000, "size": len(body), "filename": output_relpath},
            ),
        )
        async with SessionLocal() as session:
            recording = await session.get(RealtimeRecording, recording_id)
            assert recording is not None
            completed = await finalize_completed_recording(
                session, recording=recording, state=state
            )
            await session.commit()
            assert completed.status == "completed"
            assert completed.output_checksum_sha256 == hashlib.sha256(body).hexdigest()
            assert completed.output_size_bytes == len(body)
            assert completed.output_duration_ms == 5000
            assert completed.studio_asset_id is not None
            asset = await session.get(StudioAsset, completed.studio_asset_id)
            assert asset is not None
            assert asset.checksum == completed.output_checksum_sha256
            assert Path(asset.storage_path).is_file()
            assert Path(asset.storage_path).read_bytes() == body
        assert not source.exists()
    finally:
        await _cleanup_scope(organization_id)
