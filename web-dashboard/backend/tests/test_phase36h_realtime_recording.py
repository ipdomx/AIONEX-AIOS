from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.realtime.recording import (
    ParticipantRecordingConsent,
    RecordingAuthority,
    RecordingPolicy,
    RecordingPolicyError,
    RecordingRuntimeDisabledError,
)

ROOT = Path(__file__).resolve().parents[3]


def _consent(pid: str, *, ok: bool = True) -> ParticipantRecordingConsent:
    return ParticipantRecordingConsent(
        participant_id=pid,
        consented=ok,
        consent_version="rec-v1",
        consented_at=datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc) if ok else None,
    )


def test_recording_requires_explicit_all_participant_consent() -> None:
    authority = RecordingAuthority()
    with pytest.raises(RecordingPolicyError, match="explicitly consent"):
        authority.plan_recording(
            organization_id="tenant-a",
            room_id="room-a",
            provider_room_name="aios-rt-opaque",
            consents=(_consent("p1"), _consent("p2", ok=False)),
            policy=RecordingPolicy(),
        )


def test_duplicate_consent_entries_are_rejected() -> None:
    authority = RecordingAuthority()
    with pytest.raises(RecordingPolicyError, match="duplicate"):
        authority.plan_recording(
            organization_id="tenant-a",
            room_id="room-a",
            provider_room_name="aios-rt-opaque",
            consents=(_consent("p1"), _consent("p1")),
            policy=RecordingPolicy(),
        )


def test_retention_is_bounded_and_deterministic() -> None:
    authority = RecordingAuthority()
    now = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    plan = authority.plan_recording(
        organization_id="tenant-a",
        room_id="room-a",
        provider_room_name="aios-rt-opaque",
        consents=(_consent("p2"), _consent("p1")),
        policy=RecordingPolicy(retention_days=30, max_retention_days=90),
        now=now,
    )
    reversed_plan = authority.plan_recording(
        organization_id="tenant-a",
        room_id="room-a",
        provider_room_name="aios-rt-opaque",
        consents=(_consent("p1"), _consent("p2")),
        policy=RecordingPolicy(retention_days=30, max_retention_days=90),
        now=now,
    )
    assert plan.retention_until.isoformat() == "2026-09-23T14:30:00+00:00"
    assert plan.recording_key == reversed_plan.recording_key
    assert plan.consent_digest_sha256 == reversed_plan.consent_digest_sha256
    assert plan.egress_runtime_enabled is False


def test_policy_rejects_unbounded_or_partial_consent_modes() -> None:
    with pytest.raises(RecordingPolicyError):
        RecordingPolicy(retention_days=366, max_retention_days=366)
    with pytest.raises(RecordingPolicyError, match="mandatory"):
        RecordingPolicy(require_all_participants=False)


def test_safe_snapshot_exposes_no_raw_participant_identity() -> None:
    authority = RecordingAuthority()
    plan = authority.plan_recording(
        organization_id="tenant-sensitive",
        room_id="room-sensitive",
        provider_room_name="aios-rt-opaque",
        consents=(_consent("participant-secret-1"),),
        policy=RecordingPolicy(output_format="webm"),
    )
    snapshot = plan.safe_snapshot()
    text = repr(snapshot)
    assert "tenant-sensitive" not in text
    assert "room-sensitive" not in text
    assert "participant-secret-1" not in text
    assert snapshot["raw_participant_ids_returned"] is False
    assert snapshot["raw_consent_tokens_returned"] is False


def test_studio_ingestion_plan_preserves_provenance_and_retention() -> None:
    authority = RecordingAuthority()
    plan = authority.plan_recording(
        organization_id="tenant-a",
        room_id="room-a",
        provider_room_name="aios-rt-opaque",
        consents=(_consent("p1"),),
        policy=RecordingPolicy(output_format="mp4"),
    )
    studio = authority.plan_studio_ingestion(plan, title="Team recording")
    assert studio.asset_type == "realtime_recording"
    assert studio.media_type == "video/mp4"
    assert studio.filename.endswith(".mp4")
    assert studio.retention_until == plan.retention_until
    assert studio.mutation_allowed is False
    assert any(item["kind"] == "realtime_recording_consent" for item in studio.provenance)
    assert any(item["kind"] == "studio_ingestion_plan" for item in studio.provenance)


@pytest.mark.asyncio
async def test_egress_and_studio_mutations_fail_closed() -> None:
    authority = RecordingAuthority()
    plan = authority.plan_recording(
        organization_id="tenant-a",
        room_id="room-a",
        provider_room_name="aios-rt-opaque",
        consents=(_consent("p1"),),
        policy=RecordingPolicy(),
    )
    studio = authority.plan_studio_ingestion(plan, title="Recording")
    with pytest.raises(RecordingRuntimeDisabledError, match="Egress runtime"):
        await authority.start_egress(plan)
    with pytest.raises(RecordingRuntimeDisabledError, match="Studio recording"):
        await authority.ingest_into_studio(studio)


def test_recording_module_has_no_network_provider_or_storage_side_effects() -> None:
    source = (ROOT / "web-dashboard/backend/app/realtime/recording.py").read_text()
    for forbidden in (
        "import httpx",
        "import requests",
        "urllib.request",
        "from livekit",
        "import livekit",
        "socket.create_connection",
        "open(",
        "SessionLocal",
    ):
        assert forbidden not in source
