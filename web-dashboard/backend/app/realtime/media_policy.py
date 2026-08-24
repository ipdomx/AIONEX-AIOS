"""Deterministic Phase 36H call, track and adaptive-quality policy.

The policy layer is provider-neutral and network-free.  It converts already
admitted participant permissions plus an SFU room plan into safe media plans.
It never provisions a provider room, resolves credentials, opens a socket or
starts recording.  Runtime signaling/media activation remains a later gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from app.realtime.sfu import SFURoomPlan

CallKind = Literal["one_to_one", "group"]
MediaMode = Literal["audio", "video", "audio_video"]
QualityAction = Literal["maintain", "downshift", "recover"]


class RealtimeMediaPolicyError(ValueError):
    """A requested realtime media action violates the deterministic policy."""


class TrackSource(StrEnum):
    MICROPHONE = "microphone"
    CAMERA = "camera"
    SCREEN_SHARE = "screen_share"


@dataclass(frozen=True, slots=True)
class ParticipantMediaAuthority:
    """Non-secret participant capabilities copied from durable admission state."""

    participant_id: str
    can_publish: bool
    can_subscribe: bool
    can_screen_share: bool
    grant_permissions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.participant_id.strip():
            raise RealtimeMediaPolicyError("participant id is required")
        allowed = {"publish", "subscribe", "screen_share"}
        unknown = set(self.grant_permissions) - allowed
        if unknown:
            raise RealtimeMediaPolicyError("unknown admission permission")
        if self.can_publish != ("publish" in self.grant_permissions):
            raise RealtimeMediaPolicyError("publish authority must match admission grant")
        if self.can_subscribe != ("subscribe" in self.grant_permissions):
            raise RealtimeMediaPolicyError("subscribe authority must match admission grant")
        if self.can_screen_share != ("screen_share" in self.grant_permissions):
            raise RealtimeMediaPolicyError("screen-share authority must match admission grant")
        if self.can_screen_share and not self.can_publish:
            raise RealtimeMediaPolicyError("screen share requires publish authority")


@dataclass(frozen=True, slots=True)
class SimulcastLayer:
    rid: str
    width: int
    height: int
    max_bitrate_kbps: int
    max_fps: int

    def __post_init__(self) -> None:
        if self.rid not in {"q", "h", "f"}:
            raise RealtimeMediaPolicyError("unsupported simulcast RID")
        if min(self.width, self.height, self.max_bitrate_kbps, self.max_fps) <= 0:
            raise RealtimeMediaPolicyError("simulcast layer values must be positive")


CAMERA_SIMULCAST: Final[tuple[SimulcastLayer, ...]] = (
    SimulcastLayer("q", 320, 180, 180, 15),
    SimulcastLayer("h", 640, 360, 500, 24),
    SimulcastLayer("f", 1280, 720, 1_700, 30),
)
SCREEN_SIMULCAST: Final[tuple[SimulcastLayer, ...]] = (
    SimulcastLayer("q", 640, 360, 350, 10),
    SimulcastLayer("h", 1280, 720, 1_200, 15),
    SimulcastLayer("f", 1920, 1080, 2_500, 20),
)


@dataclass(frozen=True, slots=True)
class AdaptiveMediaProfile:
    profile_id: str
    camera_layers: tuple[SimulcastLayer, ...]
    screen_layers: tuple[SimulcastLayer, ...]
    adaptive_stream: bool = True
    dynacast: bool = True
    max_audio_bitrate_kbps: int = 64
    packet_loss_downshift_pct: float = 5.0
    packet_loss_recover_pct: float = 1.5
    jitter_downshift_ms: float = 45.0
    jitter_recover_ms: float = 20.0
    rtt_downshift_ms: float = 350.0
    rtt_recover_ms: float = 180.0

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise RealtimeMediaPolicyError("media profile id is required")
        if not self.camera_layers or not self.screen_layers:
            raise RealtimeMediaPolicyError("adaptive profile requires camera and screen layers")
        if not 16 <= self.max_audio_bitrate_kbps <= 256:
            raise RealtimeMediaPolicyError("audio bitrate is outside the governed range")
        if not 0 <= self.packet_loss_recover_pct < self.packet_loss_downshift_pct <= 100:
            raise RealtimeMediaPolicyError("packet-loss hysteresis is invalid")
        if not 0 <= self.jitter_recover_ms < self.jitter_downshift_ms:
            raise RealtimeMediaPolicyError("jitter hysteresis is invalid")
        if not 0 <= self.rtt_recover_ms < self.rtt_downshift_ms:
            raise RealtimeMediaPolicyError("RTT hysteresis is invalid")


DEFAULT_MEDIA_PROFILE: Final[AdaptiveMediaProfile] = AdaptiveMediaProfile(
    profile_id="balanced-v1",
    camera_layers=CAMERA_SIMULCAST,
    screen_layers=SCREEN_SIMULCAST,
)


@dataclass(frozen=True, slots=True)
class TrackPublicationPlan:
    source: TrackSource
    allowed: bool
    simulcast: bool
    layers: tuple[SimulcastLayer, ...]
    max_audio_bitrate_kbps: int | None
    reason: str

    def safe_snapshot(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "allowed": self.allowed,
            "simulcast": self.simulcast,
            "layers": [
                {
                    "rid": item.rid,
                    "width": item.width,
                    "height": item.height,
                    "max_bitrate_kbps": item.max_bitrate_kbps,
                    "max_fps": item.max_fps,
                }
                for item in self.layers
            ],
            "max_audio_bitrate_kbps": self.max_audio_bitrate_kbps,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CallMediaPlan:
    call_kind: CallKind
    media_mode: MediaMode
    participant_count: int
    provider: str
    provider_room_name: str
    provider_mutation_allowed: bool
    adaptive_stream: bool
    dynacast: bool
    recording_enabled: bool
    tracks: tuple[TrackPublicationPlan, ...]

    def safe_snapshot(self) -> dict[str, object]:
        return {
            "call_kind": self.call_kind,
            "media_mode": self.media_mode,
            "participant_count": self.participant_count,
            "provider": self.provider,
            "provider_room_name": self.provider_room_name,
            "provider_mutation_allowed": self.provider_mutation_allowed,
            "adaptive_stream": self.adaptive_stream,
            "dynacast": self.dynacast,
            "recording_enabled": self.recording_enabled,
            "tracks": [item.safe_snapshot() for item in self.tracks],
        }


@dataclass(frozen=True, slots=True)
class RealtimeQualityObservation:
    packet_loss_pct: float
    jitter_ms: float
    rtt_ms: float
    available_outgoing_bitrate_kbps: int
    active_subscribers: int

    def __post_init__(self) -> None:
        if not 0 <= self.packet_loss_pct <= 100:
            raise RealtimeMediaPolicyError("packet loss must be between 0 and 100")
        if self.jitter_ms < 0 or self.rtt_ms < 0:
            raise RealtimeMediaPolicyError("jitter and RTT must be non-negative")
        if self.available_outgoing_bitrate_kbps < 0 or self.active_subscribers < 0:
            raise RealtimeMediaPolicyError("quality counters must be non-negative")


@dataclass(frozen=True, slots=True)
class AdaptiveQualityDecision:
    action: QualityAction
    target_camera_rid: str
    target_screen_rid: str
    reasons: tuple[str, ...]

    def safe_snapshot(self) -> dict[str, object]:
        return {
            "action": self.action,
            "target_camera_rid": self.target_camera_rid,
            "target_screen_rid": self.target_screen_rid,
            "reasons": list(self.reasons),
        }


class RealtimeMediaPolicy:
    """Pure call/track/quality planner layered over durable admission authority."""

    def __init__(self, profile: AdaptiveMediaProfile = DEFAULT_MEDIA_PROFILE) -> None:
        self._profile = profile

    def plan_call(
        self,
        *,
        sfu_room: SFURoomPlan,
        authority: ParticipantMediaAuthority,
        participant_count: int,
        media_mode: MediaMode = "audio_video",
        screen_share_requested: bool = False,
    ) -> CallMediaPlan:
        if participant_count < 1 or participant_count > sfu_room.max_participants:
            raise RealtimeMediaPolicyError("participant count exceeds room plan")
        call_kind: CallKind = "one_to_one" if participant_count <= 2 else "group"
        if media_mode not in {"audio", "video", "audio_video"}:
            raise RealtimeMediaPolicyError("unsupported media mode")
        if screen_share_requested and media_mode == "audio":
            raise RealtimeMediaPolicyError("screen share is unavailable in audio-only calls")
        if screen_share_requested and not authority.can_screen_share:
            raise RealtimeMediaPolicyError("screen share was not granted at admission")

        microphone = self._microphone_plan(authority, media_mode)
        camera = self._camera_plan(authority, media_mode)
        screen = self._screen_plan(authority, media_mode, screen_share_requested)
        return CallMediaPlan(
            call_kind=call_kind,
            media_mode=media_mode,
            participant_count=participant_count,
            provider=sfu_room.provider,
            provider_room_name=sfu_room.provider_room_name,
            provider_mutation_allowed=sfu_room.provider_mutation_allowed,
            adaptive_stream=self._profile.adaptive_stream,
            dynacast=self._profile.dynacast,
            recording_enabled=False,
            tracks=(microphone, camera, screen),
        )

    def decide_quality(
        self,
        observation: RealtimeQualityObservation,
        *,
        current_camera_rid: str = "f",
        current_screen_rid: str = "f",
    ) -> AdaptiveQualityDecision:
        valid_rids = {"q", "h", "f"}
        if current_camera_rid not in valid_rids or current_screen_rid not in valid_rids:
            raise RealtimeMediaPolicyError("current quality RID is invalid")

        reasons: list[str] = []
        if observation.packet_loss_pct >= self._profile.packet_loss_downshift_pct:
            reasons.append("packet_loss")
        if observation.jitter_ms >= self._profile.jitter_downshift_ms:
            reasons.append("jitter")
        if observation.rtt_ms >= self._profile.rtt_downshift_ms:
            reasons.append("rtt")
        if observation.available_outgoing_bitrate_kbps < 450:
            reasons.append("available_bitrate")
        if reasons:
            return AdaptiveQualityDecision(
                action="downshift",
                target_camera_rid=self._lower(current_camera_rid),
                target_screen_rid=self._lower(current_screen_rid),
                reasons=tuple(reasons),
            )

        recovery_ready = (
            observation.packet_loss_pct <= self._profile.packet_loss_recover_pct
            and observation.jitter_ms <= self._profile.jitter_recover_ms
            and observation.rtt_ms <= self._profile.rtt_recover_ms
            and observation.available_outgoing_bitrate_kbps >= 1_200
        )
        if recovery_ready and (current_camera_rid != "f" or current_screen_rid != "f"):
            return AdaptiveQualityDecision(
                action="recover",
                target_camera_rid=self._higher(current_camera_rid),
                target_screen_rid=self._higher(current_screen_rid),
                reasons=("hysteresis_recovery",),
            )
        return AdaptiveQualityDecision(
            action="maintain",
            target_camera_rid=current_camera_rid,
            target_screen_rid=current_screen_rid,
            reasons=("within_policy",),
        )

    def _microphone_plan(
        self, authority: ParticipantMediaAuthority, media_mode: MediaMode
    ) -> TrackPublicationPlan:
        allowed = authority.can_publish and media_mode in {"audio", "audio_video"}
        return TrackPublicationPlan(
            source=TrackSource.MICROPHONE,
            allowed=allowed,
            simulcast=False,
            layers=(),
            max_audio_bitrate_kbps=self._profile.max_audio_bitrate_kbps if allowed else None,
            reason="admission_and_media_mode" if allowed else "not_authorized_or_not_requested",
        )

    def _camera_plan(
        self, authority: ParticipantMediaAuthority, media_mode: MediaMode
    ) -> TrackPublicationPlan:
        allowed = authority.can_publish and media_mode in {"video", "audio_video"}
        return TrackPublicationPlan(
            source=TrackSource.CAMERA,
            allowed=allowed,
            simulcast=allowed,
            layers=self._profile.camera_layers if allowed else (),
            max_audio_bitrate_kbps=None,
            reason="simulcast_governed" if allowed else "not_authorized_or_not_requested",
        )

    def _screen_plan(
        self,
        authority: ParticipantMediaAuthority,
        media_mode: MediaMode,
        requested: bool,
    ) -> TrackPublicationPlan:
        allowed = (
            requested
            and authority.can_publish
            and authority.can_screen_share
            and media_mode in {"video", "audio_video"}
        )
        return TrackPublicationPlan(
            source=TrackSource.SCREEN_SHARE,
            allowed=allowed,
            simulcast=allowed,
            layers=self._profile.screen_layers if allowed else (),
            max_audio_bitrate_kbps=None,
            reason="screen_share_granted" if allowed else "screen_share_not_active",
        )

    @staticmethod
    def _lower(rid: str) -> str:
        return {"f": "h", "h": "q", "q": "q"}[rid]

    @staticmethod
    def _higher(rid: str) -> str:
        return {"q": "h", "h": "f", "f": "f"}[rid]
