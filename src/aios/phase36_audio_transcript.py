"""Phase 36G provider-neutral transcript, caption and dubbing contracts.

This module deliberately performs no provider I/O. Raw transcript and translation
text are private artifacts; public snapshots expose hashes, timing, language and
pseudonymous speaker keys only. Voice bindings are restricted to built-in stock
voices with runtime-evidence hashes and mandatory synthetic-voice disclosure.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Any, Final, Mapping

from aios.audio_factory import AUDIO_OUTPUT_PROFILES

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_SPEAKER_KEY: Final[re.Pattern[str]] = re.compile(r"^speaker-[0-9]{3}$")
_LANGUAGE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?$"
)
_ALLOWED_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/webm",
        "audio/ogg",
        "audio/flac",
    }
)
_MAX_SOURCE_BYTES: Final[int] = 512 * 1024 * 1024
_MAX_DURATION_MS: Final[int] = 6 * 60 * 60 * 1000
_MAX_SEGMENTS: Final[int] = 5_000
_MAX_SPEAKERS: Final[int] = 32
_MAX_SEGMENT_TEXT: Final[int] = 8_000
_MAX_TOTAL_TEXT: Final[int] = 2_000_000
_MAX_TIMELINE_TOLERANCE_MS: Final[int] = 250


class TranscriptContractError(ValueError):
    """A transcript/caption/dubbing contract is unsafe or inconsistent."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_text(value: str, *, label: str, maximum: int) -> str:
    normalized = "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).strip()
    if not 1 <= len(normalized) <= maximum:
        raise TranscriptContractError(f"{label} is outside the allowed range")
    if "\x00" in normalized:
        raise TranscriptContractError(f"{label} contains a null byte")
    return normalized


def _validate_hash(value: str, label: str) -> None:
    if not _SHA256.fullmatch(value):
        raise TranscriptContractError(f"{label} SHA-256 is invalid")


def _validate_language(value: str, label: str) -> None:
    if not _LANGUAGE.fullmatch(value):
        raise TranscriptContractError(f"{label} language is invalid")


def _timestamp_webvtt(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _timestamp_srt(milliseconds: int) -> str:
    return _timestamp_webvtt(milliseconds).replace(".", ",")


def _caption_text(segment: "TranscriptSegment", *, include_speaker_labels: bool) -> str:
    escaped = html.escape(segment.text, quote=False)
    if include_speaker_labels:
        return f"[{segment.speaker_key}] {escaped}"
    return escaped


@dataclass(frozen=True, slots=True)
class GovernedAudioSource:
    """Hash-bound private audio source evidence without a public storage locator."""

    source_sha256: str
    locator_sha256: str
    size_bytes: int
    media_type: str
    duration_ms: int
    sample_rate_hz: int
    channels: int

    def __post_init__(self) -> None:
        _validate_hash(self.source_sha256, "audio source")
        _validate_hash(self.locator_sha256, "audio locator")
        if not 1 <= int(self.size_bytes) <= _MAX_SOURCE_BYTES:
            raise TranscriptContractError(
                "audio source size is outside the allowed range"
            )
        if self.media_type not in _ALLOWED_MEDIA_TYPES:
            raise TranscriptContractError("audio source media type is unsupported")
        if not 1 <= int(self.duration_ms) <= _MAX_DURATION_MS:
            raise TranscriptContractError(
                "audio source duration is outside the allowed range"
            )
        if not 8_000 <= int(self.sample_rate_hz) <= 192_000:
            raise TranscriptContractError(
                "audio source sample rate is outside the allowed range"
            )
        if not 1 <= int(self.channels) <= 8:
            raise TranscriptContractError(
                "audio source channel count is outside the allowed range"
            )

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "locator_sha256": self.locator_sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "duration_ms": self.duration_ms,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "storage_locator_returned": False,
        }


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    segment_id: str
    speaker_key: str
    start_ms: int
    end_ms: int
    text: str
    language: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        segment_id = self.segment_id.strip().lower()
        speaker_key = self.speaker_key.strip().lower()
        text = _normalize_text(
            self.text,
            label="transcript segment text",
            maximum=_MAX_SEGMENT_TEXT,
        )
        if not _SAFE_ID.fullmatch(segment_id):
            raise TranscriptContractError("transcript segment id is invalid")
        if not _SPEAKER_KEY.fullmatch(speaker_key):
            raise TranscriptContractError(
                "transcript speaker key must be a pseudonymous speaker-NNN value"
            )
        if not 0 <= int(self.start_ms) < int(self.end_ms) <= _MAX_DURATION_MS:
            raise TranscriptContractError("transcript segment timing is invalid")
        _validate_language(self.language, "transcript segment")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise TranscriptContractError("transcript segment confidence is invalid")
        object.__setattr__(self, "segment_id", segment_id)
        object.__setattr__(self, "speaker_key", speaker_key)
        object.__setattr__(self, "text", text)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def private_payload(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "speaker_key": self.speaker_key,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "text": self.text,
            "language": self.language,
            "confidence": self.confidence,
        }

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "speaker_key": self.speaker_key,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "text_sha256": _sha256_text(self.text),
            "text_characters": len(self.text),
            "language": self.language,
            "confidence": self.confidence,
            "raw_text_returned": False,
        }


@dataclass(frozen=True, slots=True)
class TranscriptDocument:
    source: GovernedAudioSource
    language: str
    segments: tuple[TranscriptSegment, ...]
    diarization_enabled: bool
    transcript_kind: str = "provider-neutral"

    def __post_init__(self) -> None:
        _validate_language(self.language, "transcript document")
        if self.transcript_kind != "provider-neutral":
            raise TranscriptContractError("transcript document kind is unsupported")
        if not 1 <= len(self.segments) <= _MAX_SEGMENTS:
            raise TranscriptContractError(
                "transcript segment count is outside the allowed range"
            )
        if len({item.segment_id for item in self.segments}) != len(self.segments):
            raise TranscriptContractError("transcript segment ids must be unique")
        if sum(len(item.text) for item in self.segments) > _MAX_TOTAL_TEXT:
            raise TranscriptContractError(
                "transcript total text is outside the allowed range"
            )
        previous_end = 0
        for index, segment in enumerate(self.segments):
            if index and segment.start_ms < previous_end:
                raise TranscriptContractError(
                    "caption-safe transcript segments must not overlap"
                )
            if segment.end_ms > self.source.duration_ms + _MAX_TIMELINE_TOLERANCE_MS:
                raise TranscriptContractError(
                    "transcript segment exceeds governed source duration"
                )
            previous_end = segment.end_ms
        speakers = {item.speaker_key for item in self.segments}
        if len(speakers) > _MAX_SPEAKERS:
            raise TranscriptContractError(
                "transcript speaker count is outside the allowed range"
            )
        if not self.diarization_enabled and len(speakers) != 1:
            raise TranscriptContractError(
                "multi-speaker transcript requires diarization evidence"
            )

    @property
    def checksum(self) -> str:
        return _canonical_sha256(self.private_payload())

    @property
    def speaker_keys(self) -> tuple[str, ...]:
        return tuple(sorted({item.speaker_key for item in self.segments}))

    def private_payload(self) -> dict[str, Any]:
        return {
            "schema": "36G.transcript.private.v1",
            "source": self.source.public_snapshot(),
            "language": self.language,
            "diarization_enabled": self.diarization_enabled,
            "transcript_kind": self.transcript_kind,
            "segments": [item.private_payload() for item in self.segments],
        }

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.transcript.public.v1",
            "checksum": self.checksum,
            "source": self.source.public_snapshot(),
            "language": self.language,
            "diarization_enabled": self.diarization_enabled,
            "segment_count": len(self.segments),
            "speaker_count": len(self.speaker_keys),
            "speaker_keys": list(self.speaker_keys),
            "segments": [item.public_snapshot() for item in self.segments],
            "raw_transcript_returned": False,
            "real_speaker_identity_returned": False,
            "storage_locator_returned": False,
        }


def render_webvtt(
    document: TranscriptDocument,
    *,
    include_speaker_labels: bool = True,
) -> str:
    lines = ["WEBVTT", "", f"NOTE transcript-sha256 {document.checksum}", ""]
    for segment in document.segments:
        lines.extend(
            [
                segment.segment_id,
                f"{_timestamp_webvtt(segment.start_ms)} --> {_timestamp_webvtt(segment.end_ms)}",
                _caption_text(segment, include_speaker_labels=include_speaker_labels),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_srt(
    document: TranscriptDocument,
    *,
    include_speaker_labels: bool = True,
) -> str:
    lines: list[str] = []
    for ordinal, segment in enumerate(document.segments, start=1):
        lines.extend(
            [
                str(ordinal),
                f"{_timestamp_srt(segment.start_ms)} --> {_timestamp_srt(segment.end_ms)}",
                _caption_text(segment, include_speaker_labels=include_speaker_labels),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def caption_manifest(document: TranscriptDocument) -> dict[str, Any]:
    webvtt = render_webvtt(document)
    srt = render_srt(document)
    return {
        "schema": "36G.caption-manifest.v1",
        "transcript_checksum": document.checksum,
        "webvtt_sha256": _sha256_text(webvtt),
        "webvtt_size_bytes": len(webvtt.encode("utf-8")),
        "srt_sha256": _sha256_text(srt),
        "srt_size_bytes": len(srt.encode("utf-8")),
        "segment_count": len(document.segments),
        "raw_caption_text_returned": False,
    }


@dataclass(frozen=True, slots=True)
class StockVoiceBinding:
    speaker_key: str
    provider: str
    model: str
    voice: str
    runtime_evidence_sha256: str
    synthetic_voice_disclosure_required: bool = True

    def __post_init__(self) -> None:
        speaker_key = self.speaker_key.strip().lower()
        if not _SPEAKER_KEY.fullmatch(speaker_key):
            raise TranscriptContractError("stock voice speaker key is invalid")
        for label, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("voice", self.voice),
        ):
            if not _SAFE_ID.fullmatch(value.strip().lower()):
                raise TranscriptContractError(f"stock voice {label} is invalid")
        _validate_hash(self.runtime_evidence_sha256, "stock voice runtime evidence")
        if not self.synthetic_voice_disclosure_required:
            raise TranscriptContractError(
                "stock voice binding requires synthetic-voice disclosure"
            )
        object.__setattr__(self, "speaker_key", speaker_key)

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "speaker_key": self.speaker_key,
            "provider": self.provider,
            "model": self.model,
            "voice": self.voice,
            "runtime_evidence_sha256": self.runtime_evidence_sha256,
            "voice_mode": "stock",
            "custom_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
            "synthetic_voice_disclosure_required": True,
        }


@dataclass(frozen=True, slots=True)
class DubbingSegmentPlan:
    source_segment_id: str
    speaker_key: str
    start_ms: int
    end_ms: int
    target_language: str
    translated_text: str
    voice: StockVoiceBinding

    def __post_init__(self) -> None:
        source_segment_id = self.source_segment_id.strip().lower()
        speaker_key = self.speaker_key.strip().lower()
        if not _SAFE_ID.fullmatch(source_segment_id):
            raise TranscriptContractError("dubbing source segment id is invalid")
        if not _SPEAKER_KEY.fullmatch(speaker_key):
            raise TranscriptContractError("dubbing speaker key is invalid")
        if speaker_key != self.voice.speaker_key:
            raise TranscriptContractError(
                "dubbing voice binding has the wrong speaker scope"
            )
        if not 0 <= self.start_ms < self.end_ms <= _MAX_DURATION_MS:
            raise TranscriptContractError("dubbing segment timing is invalid")
        _validate_language(self.target_language, "dubbing target")
        translated = _normalize_text(
            self.translated_text,
            label="dubbing translated text",
            maximum=_MAX_SEGMENT_TEXT,
        )
        object.__setattr__(self, "source_segment_id", source_segment_id)
        object.__setattr__(self, "speaker_key", speaker_key)
        object.__setattr__(self, "translated_text", translated)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def private_payload(self) -> dict[str, Any]:
        return {
            "source_segment_id": self.source_segment_id,
            "speaker_key": self.speaker_key,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "target_language": self.target_language,
            "translated_text": self.translated_text,
            "voice": self.voice.public_snapshot(),
        }

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "source_segment_id": self.source_segment_id,
            "speaker_key": self.speaker_key,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "target_language": self.target_language,
            "translated_text_sha256": _sha256_text(self.translated_text),
            "translated_text_characters": len(self.translated_text),
            "voice": self.voice.public_snapshot(),
            "raw_translated_text_returned": False,
        }


@dataclass(frozen=True, slots=True)
class DubbingPlan:
    transcript_checksum: str
    source_language: str
    target_language: str
    segments: tuple[DubbingSegmentPlan, ...]
    output_profile_id: str
    external_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_hash(self.transcript_checksum, "dubbing transcript")
        _validate_language(self.source_language, "dubbing source")
        _validate_language(self.target_language, "dubbing target")
        if self.source_language == self.target_language:
            raise TranscriptContractError(
                "dubbing target language must differ from source"
            )
        if self.output_profile_id not in AUDIO_OUTPUT_PROFILES:
            raise TranscriptContractError("dubbing output profile is unknown")
        if not self.segments:
            raise TranscriptContractError("dubbing plan requires at least one segment")
        if len({item.source_segment_id for item in self.segments}) != len(
            self.segments
        ):
            raise TranscriptContractError("dubbing source segment ids must be unique")
        if any(item.target_language != self.target_language for item in self.segments):
            raise TranscriptContractError(
                "dubbing segment target language is inconsistent"
            )
        required_gates = {
            "translation-runtime-evidence",
            "segment-stock-tts-execution",
            "timing-fit-and-alignment",
            "final-local-master",
        }
        if set(self.external_gates) != required_gates:
            raise TranscriptContractError("dubbing external gates are incomplete")

    @property
    def checksum(self) -> str:
        return _canonical_sha256(self.private_payload())

    def private_payload(self) -> dict[str, Any]:
        return {
            "schema": "36G.dubbing-plan.private.v1",
            "transcript_checksum": self.transcript_checksum,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "segments": [item.private_payload() for item in self.segments],
            "output_profile_id": self.output_profile_id,
            "external_gates": list(self.external_gates),
        }

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.dubbing-plan.public.v1",
            "checksum": self.checksum,
            "transcript_checksum": self.transcript_checksum,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "segment_count": len(self.segments),
            "speaker_count": len({item.speaker_key for item in self.segments}),
            "segments": [item.public_snapshot() for item in self.segments],
            "output_profile_id": self.output_profile_id,
            "plan_status": "external_gate",
            "render_status": "not_started",
            "external_gates": list(self.external_gates),
            "provider_requests": 0,
            "provider_spend_usd": 0.0,
            "raw_transcript_returned": False,
            "raw_translation_returned": False,
            "custom_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
        }


def build_dubbing_plan(
    document: TranscriptDocument,
    *,
    target_language: str,
    translations: Mapping[str, str],
    voice_bindings: Mapping[str, StockVoiceBinding],
    output_profile_id: str = "wav-pcm-48k-stereo",
) -> DubbingPlan:
    _validate_language(target_language, "dubbing target")
    expected_segment_ids = {item.segment_id for item in document.segments}
    if set(translations) != expected_segment_ids:
        raise TranscriptContractError(
            "dubbing translations must exactly cover the transcript segments"
        )
    expected_speakers = set(document.speaker_keys)
    if set(voice_bindings) != expected_speakers:
        raise TranscriptContractError(
            "dubbing stock voice bindings must exactly cover transcript speakers"
        )
    segments = tuple(
        DubbingSegmentPlan(
            source_segment_id=segment.segment_id,
            speaker_key=segment.speaker_key,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            target_language=target_language,
            translated_text=translations[segment.segment_id],
            voice=voice_bindings[segment.speaker_key],
        )
        for segment in document.segments
    )
    return DubbingPlan(
        transcript_checksum=document.checksum,
        source_language=document.language,
        target_language=target_language,
        segments=segments,
        output_profile_id=output_profile_id,
        external_gates=(
            "translation-runtime-evidence",
            "segment-stock-tts-execution",
            "timing-fit-and-alignment",
            "final-local-master",
        ),
    )
