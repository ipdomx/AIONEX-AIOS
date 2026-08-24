"""Phase 36H provider-neutral realtime transport and admission primitives."""

from app.realtime.admission import (
    AdmissionGrantResult,
    PresenceLeaseResult,
    RealtimeAdmissionAuthority,
    RealtimeAdmissionRejected,
)
from app.realtime.backplane import RedisRealtimeBackplane, RealtimeBackplane
from app.realtime.hub import DistributedRealtimeHub
from app.realtime.media_policy import (
    AdaptiveMediaProfile,
    AdaptiveQualityDecision,
    CallMediaPlan,
    ParticipantMediaAuthority,
    RealtimeMediaPolicy,
    RealtimeMediaPolicyError,
    RealtimeQualityObservation,
    TrackPublicationPlan,
    TrackSource,
)
from app.realtime.sfu import (
    LiveKitCandidateAdapter,
    LiveKitCandidateConfig,
    RealtimeMediaConfigurationError,
    RealtimeMediaDisabledError,
    SFUAdapter,
    SFURoomPlan,
    TurnServerReference,
)

__all__ = [
    "AdaptiveMediaProfile",
    "AdaptiveQualityDecision",
    "CallMediaPlan",
    "ParticipantMediaAuthority",
    "RealtimeMediaPolicy",
    "RealtimeMediaPolicyError",
    "RealtimeQualityObservation",
    "TrackPublicationPlan",
    "TrackSource",
    "AdmissionGrantResult",
    "DistributedRealtimeHub",
    "PresenceLeaseResult",
    "RedisRealtimeBackplane",
    "RealtimeAdmissionAuthority",
    "RealtimeAdmissionRejected",
    "RealtimeBackplane",
    "LiveKitCandidateAdapter",
    "LiveKitCandidateConfig",
    "RealtimeMediaConfigurationError",
    "RealtimeMediaDisabledError",
    "SFUAdapter",
    "SFURoomPlan",
    "TurnServerReference",
]

from app.realtime.recording import (
    ParticipantRecordingConsent,
    RecordingAuthority,
    RecordingPlan,
    RecordingPolicy,
    RecordingPolicyError,
    RecordingRuntimeDisabledError,
    StudioRecordingIngestionPlan,
)
