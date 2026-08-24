from __future__ import annotations

from pathlib import Path

import pytest

from app.realtime.media_policy import (
    DEFAULT_MEDIA_PROFILE,
    ParticipantMediaAuthority,
    RealtimeMediaPolicy,
    RealtimeMediaPolicyError,
    RealtimeQualityObservation,
    TrackSource,
)
from app.realtime.sfu import LiveKitCandidateAdapter, LiveKitCandidateConfig, TurnServerReference

ROOT = Path(__file__).resolve().parents[3]


def _room(max_participants: int = 50):
    adapter = LiveKitCandidateAdapter(
        LiveKitCandidateConfig(
            signaling_url="wss://realtime.invalid",
            api_url="https://realtime-api.invalid",
            api_key_ref="env://LIVEKIT_KEY",
            api_secret_ref="env://LIVEKIT_SECRET",
            turn_servers=(TurnServerReference(urls=("stun://stun.invalid:3478",)),),
        )
    )
    return adapter.plan_room(
        organization_id="tenant-sensitive",
        room_id="room-sensitive",
        max_participants=max_participants,
    )


def _authority(*, screen: bool = True, publish: bool = True, subscribe: bool = True):
    permissions = []
    if subscribe:
        permissions.append("subscribe")
    if publish:
        permissions.append("publish")
    if screen:
        permissions.append("screen_share")
    return ParticipantMediaAuthority(
        participant_id="participant-1",
        can_publish=publish,
        can_subscribe=subscribe,
        can_screen_share=screen,
        grant_permissions=tuple(permissions),
    )


def test_one_to_one_audio_video_plan_is_provider_dormant_and_recording_off() -> None:
    plan = RealtimeMediaPolicy().plan_call(
        sfu_room=_room(), authority=_authority(), participant_count=2
    )
    assert plan.call_kind == "one_to_one"
    assert plan.provider == "livekit"
    assert plan.provider_mutation_allowed is False
    assert plan.recording_enabled is False
    assert plan.adaptive_stream is True
    assert plan.dynacast is True
    tracks = {item.source: item for item in plan.tracks}
    assert tracks[TrackSource.MICROPHONE].allowed is True
    assert tracks[TrackSource.CAMERA].allowed is True
    assert tracks[TrackSource.CAMERA].simulcast is True
    assert tracks[TrackSource.SCREEN_SHARE].allowed is False


def test_group_call_has_same_fail_closed_provider_boundary() -> None:
    plan = RealtimeMediaPolicy().plan_call(
        sfu_room=_room(), authority=_authority(), participant_count=7
    )
    assert plan.call_kind == "group"
    assert plan.participant_count == 7
    assert plan.provider_mutation_allowed is False
    assert plan.recording_enabled is False


def test_screen_share_requires_admission_permission_and_video_mode() -> None:
    policy = RealtimeMediaPolicy()
    with pytest.raises(RealtimeMediaPolicyError, match="not granted"):
        policy.plan_call(
            sfu_room=_room(),
            authority=_authority(screen=False),
            participant_count=2,
            screen_share_requested=True,
        )
    with pytest.raises(RealtimeMediaPolicyError, match="audio-only"):
        policy.plan_call(
            sfu_room=_room(),
            authority=_authority(),
            participant_count=2,
            media_mode="audio",
            screen_share_requested=True,
        )


def test_screen_share_plan_is_bounded_simulcast_and_has_no_recording() -> None:
    plan = RealtimeMediaPolicy().plan_call(
        sfu_room=_room(),
        authority=_authority(),
        participant_count=3,
        screen_share_requested=True,
    )
    screen = next(item for item in plan.tracks if item.source is TrackSource.SCREEN_SHARE)
    assert screen.allowed is True
    assert screen.simulcast is True
    assert [item.rid for item in screen.layers] == ["q", "h", "f"]
    assert max(item.max_bitrate_kbps for item in screen.layers) == 2500
    assert plan.recording_enabled is False


def test_audio_only_and_video_only_track_policy_is_deterministic() -> None:
    policy = RealtimeMediaPolicy()
    audio = policy.plan_call(
        sfu_room=_room(), authority=_authority(screen=False), participant_count=1, media_mode="audio"
    )
    video = policy.plan_call(
        sfu_room=_room(), authority=_authority(screen=False), participant_count=1, media_mode="video"
    )
    audio_tracks = {item.source: item for item in audio.tracks}
    video_tracks = {item.source: item for item in video.tracks}
    assert audio_tracks[TrackSource.MICROPHONE].allowed is True
    assert audio_tracks[TrackSource.CAMERA].allowed is False
    assert video_tracks[TrackSource.MICROPHONE].allowed is False
    assert video_tracks[TrackSource.CAMERA].allowed is True


def test_subscribe_only_participant_cannot_publish_tracks() -> None:
    plan = RealtimeMediaPolicy().plan_call(
        sfu_room=_room(),
        authority=_authority(screen=False, publish=False),
        participant_count=2,
    )
    assert all(item.allowed is False for item in plan.tracks)


def test_authority_rejects_permission_drift() -> None:
    with pytest.raises(RealtimeMediaPolicyError, match="publish authority"):
        ParticipantMediaAuthority(
            participant_id="p",
            can_publish=True,
            can_subscribe=True,
            can_screen_share=False,
            grant_permissions=("subscribe",),
        )
    with pytest.raises(RealtimeMediaPolicyError, match="screen share requires publish"):
        ParticipantMediaAuthority(
            participant_id="p",
            can_publish=False,
            can_subscribe=True,
            can_screen_share=True,
            grant_permissions=("subscribe", "screen_share"),
        )


def test_participant_capacity_is_never_allowed_above_sfu_room_plan() -> None:
    with pytest.raises(RealtimeMediaPolicyError, match="exceeds"):
        RealtimeMediaPolicy().plan_call(
            sfu_room=_room(max_participants=4), authority=_authority(), participant_count=5
        )


def test_quality_downshifts_on_packet_loss_jitter_rtt_or_low_bitrate() -> None:
    policy = RealtimeMediaPolicy()
    decision = policy.decide_quality(
        RealtimeQualityObservation(
            packet_loss_pct=7.0,
            jitter_ms=55.0,
            rtt_ms=420.0,
            available_outgoing_bitrate_kbps=300,
            active_subscribers=4,
        )
    )
    assert decision.action == "downshift"
    assert decision.target_camera_rid == "h"
    assert decision.target_screen_rid == "h"
    assert set(decision.reasons) == {"packet_loss", "jitter", "rtt", "available_bitrate"}


def test_quality_downshift_is_bounded_at_lowest_layer() -> None:
    decision = RealtimeMediaPolicy().decide_quality(
        RealtimeQualityObservation(8.0, 10.0, 50.0, 2000, 2),
        current_camera_rid="q",
        current_screen_rid="q",
    )
    assert decision.action == "downshift"
    assert decision.target_camera_rid == "q"
    assert decision.target_screen_rid == "q"


def test_quality_recovers_one_layer_only_after_hysteresis_thresholds() -> None:
    decision = RealtimeMediaPolicy().decide_quality(
        RealtimeQualityObservation(0.5, 10.0, 100.0, 1800, 2),
        current_camera_rid="q",
        current_screen_rid="h",
    )
    assert decision.action == "recover"
    assert decision.target_camera_rid == "h"
    assert decision.target_screen_rid == "f"
    assert decision.reasons == ("hysteresis_recovery",)


def test_quality_maintains_when_between_downshift_and_recovery_bands() -> None:
    decision = RealtimeMediaPolicy().decide_quality(
        RealtimeQualityObservation(2.5, 25.0, 220.0, 900, 5),
        current_camera_rid="h",
        current_screen_rid="h",
    )
    assert decision.action == "maintain"
    assert decision.target_camera_rid == "h"
    assert decision.target_screen_rid == "h"


def test_quality_observation_rejects_impossible_values() -> None:
    with pytest.raises(RealtimeMediaPolicyError, match="packet loss"):
        RealtimeQualityObservation(101.0, 1.0, 1.0, 1000, 1)
    with pytest.raises(RealtimeMediaPolicyError, match="non-negative"):
        RealtimeQualityObservation(0.0, -1.0, 1.0, 1000, 1)


def test_safe_snapshots_contain_no_tenant_or_grant_secret_material() -> None:
    plan = RealtimeMediaPolicy().plan_call(
        sfu_room=_room(), authority=_authority(), participant_count=2, screen_share_requested=True
    )
    text = repr(plan.safe_snapshot())
    assert "tenant-sensitive" not in text
    assert "room-sensitive" not in text
    assert "LIVEKIT_SECRET" not in text


def test_default_profile_has_bounded_layers_and_hysteresis() -> None:
    profile = DEFAULT_MEDIA_PROFILE
    assert profile.adaptive_stream is True
    assert profile.dynacast is True
    assert [item.rid for item in profile.camera_layers] == ["q", "h", "f"]
    assert [item.rid for item in profile.screen_layers] == ["q", "h", "f"]
    assert profile.packet_loss_recover_pct < profile.packet_loss_downshift_pct
    assert profile.jitter_recover_ms < profile.jitter_downshift_ms
    assert profile.rtt_recover_ms < profile.rtt_downshift_ms


def test_media_policy_source_is_network_free_and_recording_dormant() -> None:
    source = (ROOT / "web-dashboard/backend/app/realtime/media_policy.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import httpx",
        "import requests",
        "urllib.request",
        "import socket",
        "from livekit",
        "import livekit",
    ):
        assert forbidden not in source
    assert "recording_enabled=False" in source
