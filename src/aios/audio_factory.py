"""Phase 36G provider-neutral audio planning, rights and QA contracts.

This module is deliberately planning-only. It never calls an external provider, never
claims that speech, music or a transformed voice was rendered, and never stores raw
identity, consent recordings, credentials, signed URLs or provider secrets.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Final, Iterable


class AudioFactoryError(ValueError):
    """An audio request cannot be represented by the governed contract."""


_ALLOWED_PROJECT_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "transcription",
        "speech",
        "dubbing",
        "narration",
        "podcast",
        "jingle",
        "song",
        "cleanup-master",
        "voice-transform",
        "voice-clone",
    }
)
_ALLOWED_TASK_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "ingest-audio",
        "analyze-audio",
        "transcribe",
        "diarize",
        "translate",
        "script",
        "synthesize-speech",
        "align",
        "compose-music",
        "generate-vocals",
        "generate-sfx",
        "voice-rights-gate",
        "voice-transform",
        "voice-clone",
        "cleanup",
        "mix",
        "master",
        "qa",
        "package",
    }
)
_PROVIDER_TASK_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "analyze-audio",
        "transcribe",
        "diarize",
        "translate",
        "synthesize-speech",
        "compose-music",
        "generate-vocals",
        "generate-sfx",
        "voice-transform",
        "voice-clone",
    }
)
_ALLOWED_USE_CASES: Final[frozenset[str]] = frozenset(
    {
        "general",
        "accessibility",
        "localization",
        "advertisement",
        "education",
        "podcast",
        "audiobook",
        "music",
        "customer-support",
    }
)
_ALLOWED_VOICE_MODES: Final[frozenset[str]] = frozenset(
    {"none", "stock", "user-owned", "licensed"}
)
_ALLOWED_RUNTIME_STATES: Final[frozenset[str]] = frozenset(
    {"inventory_visible", "ready", "external_gate", "disabled", "unknown"}
)
_ALLOWED_RIGHTS_BASES: Final[frozenset[str]] = frozenset(
    {"self", "licensed-performer", "verified-provider-share"}
)
_ALLOWED_RIGHTS_OPERATIONS: Final[frozenset[str]] = frozenset(
    {"voice-transform", "voice-clone"}
)
_ALLOWED_MODALITIES: Final[frozenset[str]] = frozenset({"text", "audio"})
_ALLOWED_EXECUTION_MODES: Final[frozenset[str]] = frozenset(
    {"batch", "streaming", "realtime"}
)
_ALLOWED_ROLES: Final[frozenset[str]] = frozenset(
    {"narration", "host", "guest", "dialogue", "vocal", "music", "sfx", "intro", "outro"}
)
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_LANGUAGE = re.compile(r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AudioOutputProfile:
    profile_id: str
    extension: str
    media_type: str
    container: str
    audio_codec: str
    sample_rate_hz: int
    channels: int
    bitrate_kbps: int | None
    runtime_state: str

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.profile_id):
            raise AudioFactoryError("audio output profile id is invalid")
        if not self.extension or not self.media_type.startswith("audio/"):
            raise AudioFactoryError("audio output profile media contract is invalid")
        if not 8_000 <= self.sample_rate_hz <= 192_000:
            raise AudioFactoryError("audio output profile sample rate is invalid")
        if self.channels not in {1, 2}:
            raise AudioFactoryError("audio output profile channel count is invalid")
        if self.bitrate_kbps is not None and not 16 <= self.bitrate_kbps <= 1_536:
            raise AudioFactoryError("audio output profile bitrate is invalid")
        if self.runtime_state not in {"planned", "source_built", "runtime_verified"}:
            raise AudioFactoryError("audio output profile runtime state is invalid")

    @property
    def filename_suffix(self) -> str:
        return self.extension


AUDIO_OUTPUT_PROFILES: Final[dict[str, AudioOutputProfile]] = {
    "wav-pcm-48k-stereo": AudioOutputProfile(
        profile_id="wav-pcm-48k-stereo",
        extension="wav",
        media_type="audio/wav",
        container="wav",
        audio_codec="pcm_s16le",
        sample_rate_hz=48_000,
        channels=2,
        bitrate_kbps=None,
        runtime_state="runtime_verified",
    ),
    "wav-pcm-48k-mono": AudioOutputProfile(
        profile_id="wav-pcm-48k-mono",
        extension="wav",
        media_type="audio/wav",
        container="wav",
        audio_codec="pcm_s16le",
        sample_rate_hz=48_000,
        channels=1,
        bitrate_kbps=None,
        runtime_state="source_built",
    ),
    "m4a-aac-48k-stereo": AudioOutputProfile(
        profile_id="m4a-aac-48k-stereo",
        extension="m4a",
        media_type="audio/mp4",
        container="mp4",
        audio_codec="aac",
        sample_rate_hz=48_000,
        channels=2,
        bitrate_kbps=192,
        runtime_state="source_built",
    ),
    "webm-opus-48k-stereo": AudioOutputProfile(
        profile_id="webm-opus-48k-stereo",
        extension="webm",
        media_type="audio/webm",
        container="webm",
        audio_codec="libopus",
        sample_rate_hz=48_000,
        channels=2,
        bitrate_kbps=128,
        runtime_state="source_built",
    ),
}


@dataclass(frozen=True, slots=True)
class AudioProviderCapability:
    provider: str
    model: str
    operations: frozenset[str]
    input_modalities: frozenset[str]
    output_modalities: frozenset[str]
    official_source: str
    evidence_date: str
    execution_modes: frozenset[str] = frozenset({"batch"})
    streaming: bool = False
    speaker_diarization: bool = False
    multi_speaker_tts: bool = False
    verified_voice_clone: bool = False
    preview: bool = False

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise AudioFactoryError("audio provider identity is invalid")
        if not self.operations or not self.operations <= _PROVIDER_TASK_OPERATIONS:
            raise AudioFactoryError("audio provider operation is invalid")
        if not self.input_modalities or not self.input_modalities <= _ALLOWED_MODALITIES:
            raise AudioFactoryError("audio provider input modality is invalid")
        if not self.output_modalities or not self.output_modalities <= _ALLOWED_MODALITIES:
            raise AudioFactoryError("audio provider output modality is invalid")
        if not self.execution_modes or not self.execution_modes <= _ALLOWED_EXECUTION_MODES:
            raise AudioFactoryError("audio provider execution mode is invalid")
        if not self.official_source.startswith("https://"):
            raise AudioFactoryError("audio provider official source is invalid")
        try:
            datetime.fromisoformat(self.evidence_date).date()
        except ValueError:
            raise AudioFactoryError("audio provider evidence date is invalid") from None
        if self.verified_voice_clone and "voice-clone" not in self.operations:
            raise AudioFactoryError("voice-clone verification requires voice-clone capability")


AUDIO_PROVIDER_CAPABILITIES: Final[tuple[AudioProviderCapability, ...]] = (
    AudioProviderCapability(
        provider="openai",
        model="gpt-4o-mini-transcribe-2025-12-15",
        operations=frozenset({"transcribe"}),
        input_modalities=frozenset({"audio"}),
        output_modalities=frozenset({"text"}),
        official_source=(
            "https://developers.openai.com/api/docs/models/"
            "gpt-4o-mini-transcribe"
        ),
        evidence_date="2026-08-22",
        execution_modes=frozenset({"batch"}),
    ),
    AudioProviderCapability(
        provider="openai",
        model="gpt-4o-mini-tts-2025-12-15",
        operations=frozenset({"synthesize-speech"}),
        input_modalities=frozenset({"text"}),
        output_modalities=frozenset({"audio"}),
        official_source=(
            "https://developers.openai.com/api/docs/models/gpt-4o-mini-tts"
        ),
        evidence_date="2026-08-22",
        execution_modes=frozenset({"batch", "streaming"}),
        streaming=True,
    ),
    AudioProviderCapability(
        provider="openai",
        model="gpt-audio",
        operations=frozenset(
            {"analyze-audio", "transcribe", "translate", "synthesize-speech"}
        ),
        input_modalities=frozenset({"text", "audio"}),
        output_modalities=frozenset({"text", "audio"}),
        official_source="https://developers.openai.com/api/docs/models/gpt-audio",
        evidence_date="2026-08-21",
        execution_modes=frozenset({"batch", "streaming"}),
        streaming=True,
    ),
    AudioProviderCapability(
        provider="openai",
        model="gpt-realtime-1.5",
        operations=frozenset(
            {"analyze-audio", "transcribe", "translate", "synthesize-speech"}
        ),
        input_modalities=frozenset({"text", "audio"}),
        output_modalities=frozenset({"text", "audio"}),
        official_source="https://developers.openai.com/api/docs/models/gpt-realtime-1.5",
        evidence_date="2026-08-21",
        execution_modes=frozenset({"realtime"}),
        streaming=True,
    ),
    AudioProviderCapability(
        provider="gemini",
        model="gemini-3.7-flash",
        operations=frozenset({"analyze-audio", "transcribe", "translate", "diarize"}),
        input_modalities=frozenset({"audio", "text"}),
        output_modalities=frozenset({"text"}),
        official_source="https://ai.google.dev/gemini-api/docs/audio",
        evidence_date="2026-08-21",
        speaker_diarization=True,
    ),
    AudioProviderCapability(
        provider="gemini",
        model="gemini-2.5-flash-preview-tts",
        operations=frozenset({"synthesize-speech"}),
        input_modalities=frozenset({"text"}),
        output_modalities=frozenset({"audio"}),
        official_source=(
            "https://ai.google.dev/gemini-api/docs/models/"
            "gemini-2.5-flash-preview-tts"
        ),
        evidence_date="2026-08-21",
        multi_speaker_tts=True,
        preview=True,
    ),
    AudioProviderCapability(
        provider="gemini",
        model="gemini-2.5-pro-preview-tts",
        operations=frozenset({"synthesize-speech"}),
        input_modalities=frozenset({"text"}),
        output_modalities=frozenset({"audio"}),
        official_source=(
            "https://ai.google.dev/gemini-api/docs/models/"
            "gemini-2.5-pro-preview-tts"
        ),
        evidence_date="2026-08-21",
        multi_speaker_tts=True,
        preview=True,
    ),
)


@dataclass(frozen=True, slots=True)
class AudioRuntimeEvidence:
    provider: str
    model: str
    state: str
    proven_operations: frozenset[str] = frozenset()
    verified_output_profiles: frozenset[str] = frozenset()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.state not in _ALLOWED_RUNTIME_STATES:
            raise AudioFactoryError("audio runtime evidence state is invalid")
        if not self.proven_operations <= _PROVIDER_TASK_OPERATIONS:
            raise AudioFactoryError("audio runtime evidence operation is invalid")
        if not self.verified_output_profiles <= AUDIO_OUTPUT_PROFILES.keys():
            raise AudioFactoryError("audio runtime evidence output profile is invalid")
        if self.state == "ready" and not self.proven_operations:
            raise AudioFactoryError("ready audio runtime evidence requires proven operations")
        if len(self.reason) > 500:
            raise AudioFactoryError("audio runtime evidence reason is too long")


@dataclass(frozen=True, slots=True)
class VoiceRightsEvidence:
    subject_ref_hash: str
    consent_evidence_sha256: str
    rights_basis: str
    allowed_operations: frozenset[str]
    allowed_purposes: tuple[str, ...]
    issued_at: str
    expires_at: str
    revocable: bool = True
    revoked_at: str | None = None
    provider_verification_ref_hash: str | None = None

    def __post_init__(self) -> None:
        for value in (self.subject_ref_hash, self.consent_evidence_sha256):
            if not _SHA256.fullmatch(value):
                raise AudioFactoryError("voice rights evidence hash is invalid")
        if self.provider_verification_ref_hash is not None and not _SHA256.fullmatch(
            self.provider_verification_ref_hash
        ):
            raise AudioFactoryError("voice provider verification reference hash is invalid")
        if self.rights_basis not in _ALLOWED_RIGHTS_BASES:
            raise AudioFactoryError("voice rights basis is invalid")
        if not self.allowed_operations or not self.allowed_operations <= _ALLOWED_RIGHTS_OPERATIONS:
            raise AudioFactoryError("voice rights operation is invalid")
        if not 1 <= len(self.allowed_purposes) <= 20:
            raise AudioFactoryError("voice rights purpose scope is invalid")
        if any(not item.strip() or len(item) > 160 for item in self.allowed_purposes):
            raise AudioFactoryError("voice rights purpose is invalid")
        issued = _parse_utc(self.issued_at, "voice rights issued_at")
        expires = _parse_utc(self.expires_at, "voice rights expires_at")
        if expires <= issued:
            raise AudioFactoryError("voice rights expiry must follow issuance")
        if self.revoked_at is not None:
            revoked = _parse_utc(self.revoked_at, "voice rights revoked_at")
            if revoked < issued:
                raise AudioFactoryError("voice rights revocation predates issuance")
        if self.rights_basis == "verified-provider-share" and not self.provider_verification_ref_hash:
            raise AudioFactoryError("verified provider share requires a verification reference")

    def allows(self, *, operation: str, purpose: str, at: datetime | None = None) -> bool:
        current = (at or datetime.now(UTC)).astimezone(UTC)
        issued = _parse_utc(self.issued_at, "voice rights issued_at")
        expires = _parse_utc(self.expires_at, "voice rights expires_at")
        revoked = (
            _parse_utc(self.revoked_at, "voice rights revoked_at")
            if self.revoked_at is not None
            else None
        )
        return (
            operation in self.allowed_operations
            and purpose in self.allowed_purposes
            and issued <= current < expires
            and (revoked is None or current < revoked)
        )

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "subject_ref_hash": self.subject_ref_hash,
            "consent_evidence_sha256": self.consent_evidence_sha256,
            "rights_basis": self.rights_basis,
            "allowed_operations": sorted(self.allowed_operations),
            "allowed_purposes": list(self.allowed_purposes),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "revocable": self.revocable,
            "revoked": self.revoked_at is not None,
            "revoked_at": self.revoked_at,
            "provider_verification_ref_hash": self.provider_verification_ref_hash,
        }


@dataclass(frozen=True, slots=True)
class AudioSegment:
    segment_id: str
    role: str
    text: str
    language: str
    speaker_ref: str | None = None
    start_ms: int | None = None
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        segment_id = self.segment_id.strip().lower()
        if not _SAFE_ID.fullmatch(segment_id):
            raise AudioFactoryError("audio segment id is invalid")
        if self.role not in _ALLOWED_ROLES:
            raise AudioFactoryError("audio segment role is invalid")
        if not 1 <= len(self.text.strip()) <= 8_000:
            raise AudioFactoryError("audio segment text is invalid")
        if not _LANGUAGE.fullmatch(self.language):
            raise AudioFactoryError("audio segment language is invalid")
        if self.speaker_ref is not None and not _SAFE_ID.fullmatch(self.speaker_ref):
            raise AudioFactoryError("audio segment speaker reference is invalid")
        if self.start_ms is not None and not 0 <= self.start_ms <= 86_400_000:
            raise AudioFactoryError("audio segment start is invalid")
        if self.duration_ms is not None and not 1 <= self.duration_ms <= 3_600_000:
            raise AudioFactoryError("audio segment duration is invalid")
        object.__setattr__(self, "segment_id", segment_id)


@dataclass(frozen=True, slots=True)
class AudioRequest:
    title: str
    brief: str
    operation: str = "narration"
    use_case: str = "general"
    language: str = "en-US"
    target_language: str | None = None
    purpose: str = "general"
    script: str = ""
    speaker_count: int = 1
    voice_mode: str = "stock"
    source_count: int = 0
    output_profile_id: str = "wav-pcm-48k-stereo"
    include_music: bool = False
    include_sfx: bool = False
    segments: tuple[AudioSegment, ...] = ()

    def __post_init__(self) -> None:
        if not 2 <= len(self.title.strip()) <= 200:
            raise AudioFactoryError("audio title is invalid")
        if not 8 <= len(self.brief.strip()) <= 12_000:
            raise AudioFactoryError("audio brief is invalid")
        if self.operation not in _ALLOWED_PROJECT_OPERATIONS:
            raise AudioFactoryError("audio operation is unsupported")
        if self.use_case not in _ALLOWED_USE_CASES:
            raise AudioFactoryError("audio use case is unsupported")
        if not _LANGUAGE.fullmatch(self.language):
            raise AudioFactoryError("audio language is invalid")
        if self.target_language is not None and not _LANGUAGE.fullmatch(self.target_language):
            raise AudioFactoryError("audio target language is invalid")
        if not self.purpose.strip() or len(self.purpose) > 160:
            raise AudioFactoryError("audio purpose is invalid")
        if len(self.script) > 50_000:
            raise AudioFactoryError("audio script is too long")
        if not 1 <= self.speaker_count <= 16:
            raise AudioFactoryError("audio speaker count is invalid")
        if self.voice_mode not in _ALLOWED_VOICE_MODES:
            raise AudioFactoryError("audio voice mode is invalid")
        if not 0 <= self.source_count <= 100:
            raise AudioFactoryError("audio source count is invalid")
        if self.output_profile_id not in AUDIO_OUTPUT_PROFILES:
            raise AudioFactoryError("audio output profile is unknown")
        if len(self.segments) > 200:
            raise AudioFactoryError("audio segment count is outside the allowed range")
        if len({item.segment_id for item in self.segments}) != len(self.segments):
            raise AudioFactoryError("audio segment ids must be unique")
        if self.operation in {"transcription", "cleanup-master", "dubbing"} and self.source_count < 1:
            raise AudioFactoryError("audio operation requires at least one governed source")
        if self.operation == "dubbing" and self.target_language is None:
            raise AudioFactoryError("dubbing requires a target language")
        if self.operation in {"voice-transform", "voice-clone"}:
            if self.source_count != 1:
                raise AudioFactoryError("voice operation requires exactly one governed source")
            if self.speaker_count != 1:
                raise AudioFactoryError("voice operation requires exactly one subject")
            if self.voice_mode not in {"user-owned", "licensed"}:
                raise AudioFactoryError("voice operation requires owned or licensed voice mode")
        if self.operation in {"speech", "narration", "podcast", "jingle", "song"}:
            if not (self.script.strip() or self.brief.strip()):
                raise AudioFactoryError("audio generation requires governed text")


@dataclass(frozen=True, slots=True)
class AudioTask:
    task_id: str
    operation: str
    depends_on: tuple[str, ...] = ()
    provider_required: bool = False
    native_multi_speaker_required: bool = False
    execution_mode: str = "batch"
    output_profile_id: str | None = None

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.task_id):
            raise AudioFactoryError("audio task id is invalid")
        if self.operation not in _ALLOWED_TASK_OPERATIONS:
            raise AudioFactoryError("audio task operation is invalid")
        if self.provider_required != (self.operation in _PROVIDER_TASK_OPERATIONS):
            raise AudioFactoryError("audio task provider boundary is inconsistent")
        if self.execution_mode not in _ALLOWED_EXECUTION_MODES:
            raise AudioFactoryError("audio task execution mode is invalid")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise AudioFactoryError("audio task dependencies must be unique")
        if any(not _SAFE_ID.fullmatch(item) for item in self.depends_on):
            raise AudioFactoryError("audio task dependency is invalid")
        if self.output_profile_id is not None and self.output_profile_id not in AUDIO_OUTPUT_PROFILES:
            raise AudioFactoryError("audio task output profile is unknown")


@dataclass(frozen=True, slots=True)
class AudioQAContract:
    output_profile_id: str
    target_integrated_lufs: float
    max_true_peak_dbtp: float
    max_loudness_range_lu: float
    require_waveform: bool = True
    require_ebur128_scan: bool = True
    require_silence_scan: bool = True
    require_clipping_scan: bool = True
    require_transcript: bool = False

    def __post_init__(self) -> None:
        if self.output_profile_id not in AUDIO_OUTPUT_PROFILES:
            raise AudioFactoryError("audio QA output profile is unknown")
        if not -32.0 <= self.target_integrated_lufs <= -8.0:
            raise AudioFactoryError("audio QA loudness target is invalid")
        if not -6.0 <= self.max_true_peak_dbtp <= 0.0:
            raise AudioFactoryError("audio QA true-peak target is invalid")
        if not 1.0 <= self.max_loudness_range_lu <= 40.0:
            raise AudioFactoryError("audio QA loudness range is invalid")


@dataclass(frozen=True, slots=True)
class AudioPlan:
    request: AudioRequest
    segments: tuple[AudioSegment, ...]
    tasks: tuple[AudioTask, ...]
    task_provider_candidates: tuple[tuple[str, tuple[AudioProviderCapability, ...]], ...]
    output_profile: AudioOutputProfile
    qa_contract: AudioQAContract
    rights_evidence: VoiceRightsEvidence | None
    plan_status: str
    render_status: str
    external_gates: tuple[str, ...]
    checksum: str

    def public_snapshot(self) -> dict[str, Any]:
        provider_inventory = [
            {
                "provider": item.provider,
                "model": item.model,
                "operations": sorted(item.operations),
                "input_modalities": sorted(item.input_modalities),
                "output_modalities": sorted(item.output_modalities),
                "execution_modes": sorted(item.execution_modes),
                "streaming": item.streaming,
                "speaker_diarization": item.speaker_diarization,
                "multi_speaker_tts": item.multi_speaker_tts,
                "verified_voice_clone": item.verified_voice_clone,
                "preview": item.preview,
                "inventory_state": "inventory_visible",
                "official_source": item.official_source,
                "evidence_date": item.evidence_date,
            }
            for item in AUDIO_PROVIDER_CAPABILITIES
        ]
        candidates_by_task = {
            task_id: [
                {
                    "provider": item.provider,
                    "model": item.model,
                    "inventory_state": "inventory_visible",
                }
                for item in candidates
            ]
            for task_id, candidates in self.task_provider_candidates
        }
        script = self.request.script or self.request.brief
        return {
            "schema": "36G.audio-plan.v1",
            "plan_status": self.plan_status,
            "render_status": self.render_status,
            "external_requests": 0,
            "external_cost_usd": 0.0,
            "estimated_external_cost_usd": None,
            "checksum": self.checksum,
            "request": {
                "title": self.request.title,
                "operation": self.request.operation,
                "use_case": self.request.use_case,
                "language": self.request.language,
                "target_language": self.request.target_language,
                "purpose": self.request.purpose,
                "speaker_count": self.request.speaker_count,
                "voice_mode": self.request.voice_mode,
                "source_count": self.request.source_count,
                "include_music": self.request.include_music,
                "include_sfx": self.request.include_sfx,
                "output_profile_id": self.request.output_profile_id,
                "script_sha256": _sha256_text(script),
                "script_length": len(script),
            },
            "segments": [
                {
                    "segment_id": item.segment_id,
                    "role": item.role,
                    "language": item.language,
                    "speaker_ref": item.speaker_ref,
                    "start_ms": item.start_ms,
                    "duration_ms": item.duration_ms,
                    "text_sha256": _sha256_text(item.text),
                    "text_length": len(item.text),
                }
                for item in self.segments
            ],
            "tasks": [
                {
                    **asdict(item),
                    "provider_candidates": candidates_by_task.get(item.task_id, []),
                    "state": (
                        "external_gate"
                        if item.provider_required and not candidates_by_task.get(item.task_id)
                        else "planned"
                    ),
                }
                for item in self.tasks
            ],
            "provider_inventory": provider_inventory,
            "output_profile": asdict(self.output_profile),
            "qa_contract": asdict(self.qa_contract),
            "rights": {
                "required": self.request.operation in _ALLOWED_RIGHTS_OPERATIONS,
                "present": self.rights_evidence is not None,
                "evidence": (
                    self.rights_evidence.public_snapshot()
                    if self.rights_evidence is not None
                    else None
                ),
            },
            "external_gates": list(self.external_gates),
        }


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AudioFactoryError(f"{label} is invalid") from None
    if parsed.tzinfo is None:
        raise AudioFactoryError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def default_segments(request: AudioRequest) -> tuple[AudioSegment, ...]:
    source = (request.script or request.brief).strip()
    if request.operation == "podcast":
        return tuple(
            AudioSegment(
                segment_id=f"speaker-{index}",
                role="host" if index == 1 else "guest",
                text=source,
                language=request.language,
                speaker_ref=f"speaker-{index}",
            )
            for index in range(1, request.speaker_count + 1)
        )
    if request.operation in {"song", "jingle"}:
        return (
            AudioSegment(
                segment_id="intro",
                role="intro",
                text=f"Instrumental direction: {source}",
                language=request.language,
            ),
            AudioSegment(
                segment_id="vocal",
                role="vocal",
                text=source,
                language=request.language,
                speaker_ref="vocal-1",
            ),
            AudioSegment(
                segment_id="outro",
                role="outro",
                text=f"Resolve the governed musical concept: {request.title}",
                language=request.language,
            ),
        )
    role = "dialogue" if request.operation == "dubbing" else "narration"
    return (
        AudioSegment(
            segment_id="primary",
            role=role,
            text=source,
            language=request.target_language or request.language,
            speaker_ref="speaker-1" if request.voice_mode != "none" else None,
        ),
    )


def _task(
    task_id: str,
    operation: str,
    *depends_on: str,
    native_multi_speaker_required: bool = False,
    output_profile_id: str | None = None,
    execution_mode: str = "batch",
) -> AudioTask:
    return AudioTask(
        task_id=task_id,
        operation=operation,
        depends_on=tuple(depends_on),
        provider_required=operation in _PROVIDER_TASK_OPERATIONS,
        native_multi_speaker_required=native_multi_speaker_required,
        execution_mode=execution_mode,
        output_profile_id=output_profile_id,
    )


def build_task_graph(request: AudioRequest) -> tuple[AudioTask, ...]:
    final_profile = request.output_profile_id
    if request.operation == "transcription":
        tasks = [
            _task("ingest", "ingest-audio"),
            _task("analyze", "analyze-audio", "ingest"),
            _task("transcript", "transcribe", "analyze"),
        ]
        if request.speaker_count > 1:
            tasks.append(_task("diarization", "diarize", "transcript"))
            qa_dependency = "diarization"
        else:
            qa_dependency = "transcript"
        tasks.extend(
            [
                _task("qa", "qa", qa_dependency),
                _task("package", "package", "qa"),
            ]
        )
        return tuple(tasks)
    if request.operation in {"speech", "narration"}:
        return (
            _task("script", "script"),
            _task("speech", "synthesize-speech", "script"),
            _task("cleanup", "cleanup", "speech"),
            _task("master", "master", "cleanup"),
            _task("qa", "qa", "master"),
            _task("package", "package", "qa", output_profile_id=final_profile),
        )
    if request.operation == "dubbing":
        tasks = [
            _task("ingest", "ingest-audio"),
            _task("analyze", "analyze-audio", "ingest"),
            _task("transcript", "transcribe", "analyze"),
        ]
        transcript_dependency = "transcript"
        if request.speaker_count > 1:
            tasks.append(_task("diarization", "diarize", "transcript"))
            transcript_dependency = "diarization"
        tasks.extend(
            [
                _task("translation", "translate", transcript_dependency),
                _task(
                    "speech",
                    "synthesize-speech",
                    "translation",
                    native_multi_speaker_required=request.speaker_count > 1,
                ),
                _task("alignment", "align", "speech", "ingest"),
                _task("mix", "mix", "alignment"),
                _task("master", "master", "mix"),
                _task("qa", "qa", "master"),
                _task("package", "package", "qa", output_profile_id=final_profile),
            ]
        )
        return tuple(tasks)
    if request.operation == "podcast":
        return (
            _task("script", "script"),
            _task(
                "speech",
                "synthesize-speech",
                "script",
                native_multi_speaker_required=request.speaker_count > 1,
            ),
            *(
                (_task("music", "compose-music", "script"),)
                if request.include_music
                else ()
            ),
            *(
                (_task("sfx", "generate-sfx", "script"),)
                if request.include_sfx
                else ()
            ),
            _task(
                "mix",
                "mix",
                *tuple(
                    item
                    for item in ("speech", "music" if request.include_music else None, "sfx" if request.include_sfx else None)
                    if item is not None
                ),
            ),
            _task("master", "master", "mix"),
            _task("qa", "qa", "master"),
            _task("package", "package", "qa", output_profile_id=final_profile),
        )
    if request.operation in {"jingle", "song"}:
        return (
            _task("script", "script"),
            _task("music", "compose-music", "script"),
            _task("vocals", "generate-vocals", "script", "music"),
            *(
                (_task("sfx", "generate-sfx", "script"),)
                if request.include_sfx
                else ()
            ),
            _task(
                "mix",
                "mix",
                *tuple(
                    item
                    for item in ("music", "vocals", "sfx" if request.include_sfx else None)
                    if item is not None
                ),
            ),
            _task("master", "master", "mix"),
            _task("qa", "qa", "master"),
            _task("package", "package", "qa", output_profile_id=final_profile),
        )
    if request.operation == "cleanup-master":
        return (
            _task("ingest", "ingest-audio"),
            _task("cleanup", "cleanup", "ingest"),
            _task("master", "master", "cleanup"),
            _task("qa", "qa", "master"),
            _task("package", "package", "qa", output_profile_id=final_profile),
        )
    if request.operation in _ALLOWED_RIGHTS_OPERATIONS:
        return (
            _task("ingest", "ingest-audio"),
            _task("rights", "voice-rights-gate", "ingest"),
            _task("voice", request.operation, "rights"),
            _task("qa", "qa", "voice"),
            _task("package", "package", "qa", output_profile_id=final_profile),
        )
    raise AudioFactoryError("audio operation has no governed task graph")


def _validate_task_graph(tasks: tuple[AudioTask, ...]) -> None:
    ids = [item.task_id for item in tasks]
    if len(set(ids)) != len(ids):
        raise AudioFactoryError("audio task ids must be unique")
    available: set[str] = set()
    for task in tasks:
        if not set(task.depends_on) <= available:
            raise AudioFactoryError("audio task graph is not topologically ordered")
        available.add(task.task_id)
    if not tasks or tasks[-1].operation != "package":
        raise AudioFactoryError("audio task graph must end in packaging")


def provider_candidates_for_task(
    task: AudioTask,
) -> tuple[AudioProviderCapability, ...]:
    if not task.provider_required:
        return ()
    candidates = tuple(
        item
        for item in AUDIO_PROVIDER_CAPABILITIES
        if task.operation in item.operations
        and task.execution_mode in item.execution_modes
        and (
            not task.native_multi_speaker_required
            or (task.operation == "synthesize-speech" and item.multi_speaker_tts)
        )
    )
    return candidates


def runtime_ready_provider(
    task: AudioTask,
    *,
    evidence: Iterable[AudioRuntimeEvidence],
) -> AudioProviderCapability:
    """Route only when operation-specific live evidence exists.

    Official inventory visibility, a connected generic AI provider, or a static model
    capability never means an audio operation is live-ready.
    """
    candidates = provider_candidates_for_task(task)
    evidence_by_key: dict[tuple[str, str], AudioRuntimeEvidence] = {}
    for item in evidence:
        key = (item.provider, item.model)
        if key in evidence_by_key:
            raise AudioFactoryError("duplicate audio runtime evidence")
        evidence_by_key[key] = item
    for capability in candidates:
        row = evidence_by_key.get((capability.provider, capability.model))
        if row is None or row.state != "ready":
            continue
        if task.operation not in row.proven_operations:
            continue
        if task.output_profile_id is not None and (
            task.output_profile_id not in row.verified_output_profiles
        ):
            continue
        return capability
    raise AudioFactoryError("no live-proven audio provider supports the task contract")


def _rights_gate(
    request: AudioRequest,
    rights: VoiceRightsEvidence | None,
    *,
    at: datetime | None,
) -> tuple[str, ...]:
    if request.operation not in _ALLOWED_RIGHTS_OPERATIONS:
        return ()
    if rights is None:
        raise AudioFactoryError("voice operation requires consent and rights evidence")
    if not rights.allows(operation=request.operation, purpose=request.purpose, at=at):
        raise AudioFactoryError("voice rights evidence does not authorize this operation and purpose")
    if request.operation == "voice-clone" and rights.rights_basis not in {
        "self",
        "verified-provider-share",
    }:
        raise AudioFactoryError("voice cloning requires self or verified-provider-share rights")
    if request.operation == "voice-clone" and rights.rights_basis == "self":
        if rights.provider_verification_ref_hash is None:
            return ("voice-clone-provider-identity-verification",)
    return ()


def default_qa_contract(request: AudioRequest) -> AudioQAContract:
    music = request.operation in {"jingle", "song"} or request.use_case == "music"
    return AudioQAContract(
        output_profile_id=request.output_profile_id,
        target_integrated_lufs=-14.0 if music else -16.0,
        max_true_peak_dbtp=-1.0,
        max_loudness_range_lu=20.0 if music else 12.0,
        require_transcript=request.operation
        in {"transcription", "speech", "dubbing", "narration", "podcast"},
    )


def build_audio_plan(
    request: AudioRequest,
    *,
    rights_evidence: VoiceRightsEvidence | None = None,
    at: datetime | None = None,
) -> AudioPlan:
    segments = request.segments or default_segments(request)
    tasks = build_task_graph(request)
    _validate_task_graph(tasks)
    task_candidates = tuple(
        (task.task_id, provider_candidates_for_task(task))
        for task in tasks
        if task.provider_required
    )
    gates = list(_rights_gate(request, rights_evidence, at=at))
    for task_id, candidates in task_candidates:
        if candidates:
            continue
        task = next(item for item in tasks if item.task_id == task_id)
        gates.append(f"provider-runtime:{task.operation}")
    gates = list(dict.fromkeys(gates))
    output_profile = AUDIO_OUTPUT_PROFILES[request.output_profile_id]
    qa = default_qa_contract(request)
    safe_rights = rights_evidence.public_snapshot() if rights_evidence is not None else None
    canonical = {
        "request": asdict(request),
        "segments": [asdict(item) for item in segments],
        "tasks": [asdict(item) for item in tasks],
        "candidates": {
            task_id: [(item.provider, item.model) for item in candidates]
            for task_id, candidates in task_candidates
        },
        "output_profile": asdict(output_profile),
        "qa": asdict(qa),
        "rights": safe_rights,
        "external_gates": gates,
    }
    checksum = _sha256_text(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return AudioPlan(
        request=request,
        segments=segments,
        tasks=tasks,
        task_provider_candidates=task_candidates,
        output_profile=output_profile,
        qa_contract=qa,
        rights_evidence=rights_evidence,
        plan_status="external_gate" if gates else "planned",
        render_status="not_started",
        external_gates=tuple(gates),
        checksum=checksum,
    )


def ssml_template(plan: AudioPlan) -> str:
    """Return editable provider-neutral SSML; it is not rendered audio."""
    lines = [f'<speak xml:lang="{html.escape(plan.request.target_language or plan.request.language)}">']
    for segment in plan.segments:
        lines.append(
            f'  <p data-segment="{html.escape(segment.segment_id)}">'
            f'<prosody rate="medium" pitch="medium">{html.escape(segment.text)}</prosody></p>'
        )
    lines.append("</speak>")
    return "\n".join(lines) + "\n"


def cue_sheet_payload(plan: AudioPlan) -> dict[str, Any]:
    return {
        "schema": "36G.audio-cue-sheet.v1",
        "plan_checksum": plan.checksum,
        "render_status": plan.render_status,
        "segments": [
            {
                "segment_id": item.segment_id,
                "role": item.role,
                "speaker_ref": item.speaker_ref,
                "language": item.language,
                "start_ms": item.start_ms,
                "duration_ms": item.duration_ms,
                "text_sha256": _sha256_text(item.text),
                "text_length": len(item.text),
            }
            for item in plan.segments
        ],
    }


def mix_plan_markdown(plan: AudioPlan) -> str:
    lines = [
        f"# {plan.request.title} — governed audio production plan",
        "",
        f"Plan checksum: `{plan.checksum}`",
        f"Plan status: **{plan.plan_status}**",
        f"Render status: **{plan.render_status}** (no rendered audio is claimed)",
        "External provider requests: **0**",
        "External provider cost: **$0.00**",
        "Estimated external cost: **unknown until a provider-specific bounded route is armed**",
        "",
        "## Task graph",
        "",
    ]
    candidates = dict(plan.task_provider_candidates)
    for task in plan.tasks:
        provider_labels = [f"{item.provider}/{item.model}" for item in candidates.get(task.task_id, ())]
        providers = ", ".join(provider_labels) if provider_labels else "local plan or external gate"
        dependencies = ", ".join(task.depends_on) if task.depends_on else "none"
        lines.append(
            f"- `{task.task_id}` — `{task.operation}`; depends on: {dependencies}; candidates: {providers}."
        )
    lines.extend(
        [
            "",
            "## QA contract",
            "",
            f"- Output profile: `{plan.output_profile.profile_id}` ({plan.output_profile.runtime_state})",
            f"- Sample rate: `{plan.output_profile.sample_rate_hz}` Hz",
            f"- Channels: `{plan.output_profile.channels}`",
            f"- Integrated loudness policy target: `{plan.qa_contract.target_integrated_lufs}` LUFS",
            f"- Maximum true peak: `{plan.qa_contract.max_true_peak_dbtp}` dBTP",
            f"- Maximum loudness range: `{plan.qa_contract.max_loudness_range_lu}` LU",
            "- Required scans: waveform, EBU R128, silence and clipping.",
            "",
            "## Rights boundary",
            "",
            (
                "Voice transformation/cloning is outside this plan."
                if plan.request.operation not in _ALLOWED_RIGHTS_OPERATIONS
                else "Voice rights evidence is hashed and must remain valid through execution."
            ),
        ]
    )
    if plan.external_gates:
        lines.extend(["", "## External gates", ""])
        lines.extend(f"- `{item}`" for item in plan.external_gates)
    return "\n".join(lines) + "\n"
