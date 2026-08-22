"""Phase 36G exact provider transports for governed transcription and diarization.

Durable state, tenancy, arm-before-request, ambiguity handling, private storage and
public redaction live outside this module. The synchronous transport never retries.
Raw provider speaker labels exist only in the in-memory result and must be
pseudonymized before durable completion.
"""
from __future__ import annotations

import hashlib
import io
import math
import re
import wave
from dataclasses import dataclass
from typing import Any

import httpx

_OPENAI_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe-2025-12-15"
_OPENAI_DIARIZE_MODEL = "gpt-4o-transcribe-diarize"
_OPENAI_ESTIMATED_PER_MINUTE_USD = {
    _OPENAI_TRANSCRIBE_MODEL: 0.003,
    _OPENAI_DIARIZE_MODEL: 0.006,
}
_OPENAI_INPUT_USD_PER_MILLION_TOKENS = {
    _OPENAI_TRANSCRIBE_MODEL: 1.25,
    _OPENAI_DIARIZE_MODEL: 2.50,
}
_OPENAI_OUTPUT_USD_PER_MILLION_TOKENS = {
    _OPENAI_TRANSCRIBE_MODEL: 5.00,
    _OPENAI_DIARIZE_MODEL: 10.00,
}
_OPENAI_PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"
_OPENAI_DIARIZE_MODEL_SOURCE = (
    "https://developers.openai.com/api/docs/models/gpt-4o-transcribe-diarize"
)
_OPENAI_TRANSCRIPTION_API_SOURCE = (
    "https://developers.openai.com/api/reference/resources/audio/"
    "subresources/transcriptions/methods/create"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_PROVIDER_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_ALLOWED_MEDIA_TYPES = frozenset({"audio/wav", "audio/x-wav"})
_SUFFIXES = {"audio/wav": ".wav", "audio/x-wav": ".wav"}
_MAX_PROVIDER_SEGMENTS = 5_000
_MAX_PROVIDER_SPEAKERS = 32
_MAX_SEGMENT_TEXT = 8_000
_TIMELINE_TOLERANCE_SECONDS = 0.250


def inspect_governed_wav(
    body: bytes,
    *,
    max_duration_seconds: int,
) -> dict[str, Any]:
    """Validate a bounded finite PCM WAV before provider transmission."""
    if not body or len(body) < 44 or body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
    try:
        with wave.open(io.BytesIO(body), "rb") as reader:
            channels = int(reader.getnchannels())
            sample_width = int(reader.getsampwidth())
            sample_rate = int(reader.getframerate())
            frame_count = int(reader.getnframes())
            compression = str(reader.getcomptype())
    except (wave.Error, EOFError, OSError) as exc:
        raise ProviderTranscriptFailure(
            "provider_input_invalid", retryable=False
        ) from exc
    if compression != "NONE" or channels not in {1, 2}:
        raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
    if sample_width not in {1, 2, 3, 4}:
        raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
    if not 8_000 <= sample_rate <= 96_000 or frame_count <= 0:
        raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
    duration_seconds = frame_count / sample_rate
    if not 0 < duration_seconds <= float(max_duration_seconds):
        raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
    return {
        "container": "wav",
        "codec": "pcm",
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "frame_count": frame_count,
        "duration_ms": round(duration_seconds * 1_000),
    }


@dataclass(frozen=True, slots=True)
class ProviderTranscriptRequest:
    provider: str
    model: str
    audio: bytes
    media_type: str
    source_sha256: str
    duration_ms: int
    language: str
    operation: str = "transcribe"
    response_format: str = "json"
    chunking_strategy: str | None = None
    prompt: str | None = None
    max_source_bytes: int = 20_971_520
    max_duration_seconds: int = 600


@dataclass(frozen=True, slots=True)
class ProviderDiarizedSegmentResult:
    provider_segment_id: str
    speaker_label: str
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class ProviderTranscriptResult:
    text: str
    language: str
    request_id: str | None
    metadata: dict[str, Any]
    usage: dict[str, Any]
    segments: tuple[ProviderDiarizedSegmentResult, ...] = ()
    actual_cost_usd: float | None = None
    cost_basis: str = "official_estimated_per_minute"


class ProviderTranscriptFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        safe_to_resubmit: bool = False,
        ambiguous_submission: bool = False,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
        message: str = "Transcript provider request failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.safe_to_resubmit = safe_to_resubmit
        self.ambiguous_submission = ambiguous_submission
        self.http_status = http_status
        self.metadata = metadata or {}


def estimate_openai_transcription_cost(
    duration_ms: int,
    *,
    model: str = _OPENAI_TRANSCRIBE_MODEL,
) -> tuple[float, dict[str, Any]]:
    rate = _OPENAI_ESTIMATED_PER_MINUTE_USD.get(model)
    if rate is None or not 1 <= int(duration_ms) <= 3_600_000:
        raise ProviderTranscriptFailure("provider_pricing_unknown", retryable=False)
    minutes = float(duration_ms) / 60_000.0
    estimate = round(minutes * rate, 9)
    pricing_basis = (
        "official_published_per_minute_estimate"
        if model == _OPENAI_TRANSCRIBE_MODEL
        else "official_model_rate_equivalent_estimate"
    )
    note = (
        "The provider publishes an estimated per-minute cost, while this endpoint "
        "may return token or duration usage but not an account invoice."
    )
    if model == _OPENAI_DIARIZE_MODEL:
        note = (
            "The diarization model publishes the same $2.50 input / $10.00 output "
            "token rates as gpt-4o-transcribe; the $0.006/minute value is retained "
            "as a conservative rate-equivalent estimate, not a fabricated bill."
        )
    return estimate, {
        "pricing_revision": "2026-08-23",
        "pricing_source": _OPENAI_PRICING_SOURCE,
        "model_source": (
            _OPENAI_DIARIZE_MODEL_SOURCE
            if model == _OPENAI_DIARIZE_MODEL
            else _OPENAI_PRICING_SOURCE
        ),
        "api_source": _OPENAI_TRANSCRIPTION_API_SOURCE,
        "pricing_basis": pricing_basis,
        "pricing_unit": "audio_minute_estimate",
        "estimated_price_per_minute_usd": rate,
        "input_usd_per_million_tokens": (
            _OPENAI_INPUT_USD_PER_MILLION_TOKENS[model]
        ),
        "output_usd_per_million_tokens": (
            _OPENAI_OUTPUT_USD_PER_MILLION_TOKENS[model]
        ),
        "duration_ms": int(duration_ms),
        "billing_note": note,
    }


def _safe_error_metadata(response: httpx.Response) -> dict[str, Any]:
    safe: dict[str, Any] = {"http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        return safe
    if not isinstance(payload, dict):
        return safe
    raw_error = payload.get("error")
    error = raw_error if isinstance(raw_error, dict) else payload
    if not isinstance(error, dict):
        return safe
    for key in ("type", "code", "param"):
        value = error.get(key)
        if isinstance(value, (str, int, float, bool)):
            safe[key] = str(value)[:160]
    return safe


def _failure_for_response(response: httpx.Response) -> ProviderTranscriptFailure:
    status = response.status_code
    metadata = _safe_error_metadata(response)
    if status in {401, 403}:
        return ProviderTranscriptFailure(
            "provider_auth",
            retryable=False,
            http_status=status,
            metadata=metadata,
        )
    if status == 402:
        return ProviderTranscriptFailure(
            "provider_billing",
            retryable=False,
            http_status=status,
            metadata=metadata,
        )
    if status == 429:
        return ProviderTranscriptFailure(
            "provider_rate_limited",
            retryable=True,
            safe_to_resubmit=True,
            http_status=status,
            metadata=metadata,
        )
    if status in {400, 404, 409, 413, 415, 422}:
        return ProviderTranscriptFailure(
            "provider_request",
            retryable=False,
            http_status=status,
            metadata=metadata,
        )
    if status >= 500:
        return ProviderTranscriptFailure(
            "provider_submission_ambiguous",
            retryable=False,
            ambiguous_submission=True,
            http_status=status,
            metadata=metadata,
        )
    return ProviderTranscriptFailure(
        "provider_response",
        retryable=False,
        http_status=status,
        metadata=metadata,
    )


def _normalized_text(value: Any, *, maximum: int = 2_000_000) -> str:
    if not isinstance(value, str):
        raise ProviderTranscriptFailure("provider_response", retryable=False)
    normalized = "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).strip()
    if not 1 <= len(normalized) <= maximum or "\x00" in normalized:
        raise ProviderTranscriptFailure("provider_response", retryable=False)
    return normalized


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _diarized_segments(
    payload: dict[str, Any],
    *,
    source_duration_seconds: float,
) -> tuple[ProviderDiarizedSegmentResult, ...]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not 2 <= len(raw_segments) <= _MAX_PROVIDER_SEGMENTS:
        raise ProviderTranscriptFailure("provider_response", retryable=False)
    rows: list[ProviderDiarizedSegmentResult] = []
    provider_ids: set[str] = set()
    raw_speakers: set[str] = set()
    previous_end = 0.0
    for raw in raw_segments:
        if not isinstance(raw, dict):
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        segment_type = raw.get("type")
        if segment_type is not None and segment_type != "transcript.text.segment":
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        provider_segment_id = raw.get("id")
        speaker = raw.get("speaker")
        if (
            not isinstance(provider_segment_id, str)
            or not _SAFE_PROVIDER_SEGMENT_ID.fullmatch(provider_segment_id)
            or provider_segment_id in provider_ids
        ):
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        if (
            not isinstance(speaker, str)
            or not 1 <= len(speaker.strip()) <= 80
            or "\x00" in speaker
        ):
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        start = _finite_number(raw.get("start"))
        end = _finite_number(raw.get("end"))
        if (
            start is None
            or end is None
            or start < 0
            or end <= start
            or start + 1e-9 < previous_end
            or end > source_duration_seconds + _TIMELINE_TOLERANCE_SECONDS
        ):
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        label = speaker.strip()
        rows.append(
            ProviderDiarizedSegmentResult(
                provider_segment_id=provider_segment_id,
                speaker_label=label,
                start_seconds=start,
                end_seconds=end,
                text=_normalized_text(raw.get("text"), maximum=_MAX_SEGMENT_TEXT),
            )
        )
        provider_ids.add(provider_segment_id)
        raw_speakers.add(label)
        previous_end = end
    if not 2 <= len(raw_speakers) <= _MAX_PROVIDER_SPEAKERS:
        raise ProviderTranscriptFailure("provider_diarization_invalid", retryable=False)
    return tuple(rows)


def _safe_usage(
    payload: dict[str, Any],
    *,
    request: ProviderTranscriptRequest,
    estimate: float,
    pricing: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        **pricing,
        "estimated_cost_usd": estimate,
        "actual_cost_known": False,
    }
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        result["provider_usage_reported"] = False
        return result
    usage_type = raw.get("type")
    if usage_type == "duration":
        seconds = _finite_number(raw.get("seconds"))
        if (
            seconds is None
            or seconds <= 0
            or seconds > request.duration_ms / 1_000 + _TIMELINE_TOLERANCE_SECONDS
        ):
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        result.update(
            {
                "provider_usage_reported": True,
                "provider_usage_type": "duration",
                "provider_usage_seconds": seconds,
                "observed_cost_estimate_usd": round(
                    seconds
                    / 60.0
                    * _OPENAI_ESTIMATED_PER_MINUTE_USD[request.model],
                    9,
                ),
            }
        )
        return result
    if usage_type == "tokens":
        input_tokens = _positive_int(raw.get("input_tokens"))
        output_tokens = _positive_int(raw.get("output_tokens"))
        total_tokens = _positive_int(raw.get("total_tokens"))
        if input_tokens is None or output_tokens is None or total_tokens is None:
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        details = raw.get("input_token_details")
        audio_tokens = None
        text_tokens = None
        if isinstance(details, dict):
            audio_tokens = _positive_int(details.get("audio_tokens"))
            text_tokens = _positive_int(details.get("text_tokens"))
        observed = round(
            input_tokens
            * _OPENAI_INPUT_USD_PER_MILLION_TOKENS[request.model]
            / 1_000_000
            + output_tokens
            * _OPENAI_OUTPUT_USD_PER_MILLION_TOKENS[request.model]
            / 1_000_000,
            9,
        )
        result.update(
            {
                "provider_usage_reported": True,
                "provider_usage_type": "tokens",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "audio_input_tokens": audio_tokens,
                "text_input_tokens": text_tokens,
                "observed_cost_estimate_usd": observed,
            }
        )
        return result
    raise ProviderTranscriptFailure("provider_response", retryable=False)


class OpenAITranscriptAdapter:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _validate_request(request: ProviderTranscriptRequest) -> None:
        if request.provider != "openai":
            raise ProviderTranscriptFailure(
                "provider_operation_unsupported", retryable=False
            )
        launch_matrix = {
            ("transcribe", _OPENAI_TRANSCRIBE_MODEL, "json", None),
            ("diarize", _OPENAI_DIARIZE_MODEL, "diarized_json", "auto"),
        }
        route = (
            request.operation,
            request.model,
            request.response_format,
            request.chunking_strategy,
        )
        if route not in launch_matrix:
            raise ProviderTranscriptFailure(
                "provider_operation_unsupported", retryable=False
            )
        if request.operation == "diarize" and request.prompt is not None:
            raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
        if request.media_type not in _ALLOWED_MEDIA_TYPES:
            raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
        if not request.audio or len(request.audio) > request.max_source_bytes:
            raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
        if not _SHA256.fullmatch(request.source_sha256):
            raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
        if hashlib.sha256(request.audio).hexdigest() != request.source_sha256:
            raise ProviderTranscriptFailure("provider_input_integrity", retryable=False)
        audio = inspect_governed_wav(
            request.audio,
            max_duration_seconds=request.max_duration_seconds,
        )
        if abs(int(audio["duration_ms"]) - int(request.duration_ms)) > 20:
            raise ProviderTranscriptFailure("provider_input_integrity", retryable=False)
        if not request.language.strip() or len(request.language) > 32:
            raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)
        if request.prompt is not None and len(request.prompt) > 1_000:
            raise ProviderTranscriptFailure("provider_input_invalid", retryable=False)

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        token = credential.strip()
        if not token:
            raise ProviderTranscriptFailure("provider_unconfigured", retryable=False)
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def invoke(
        self,
        request: ProviderTranscriptRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderTranscriptResult:
        self._validate_request(request)
        root = base_url.rstrip("/")
        data: dict[str, str] = {
            "model": request.model,
            "response_format": request.response_format,
            "language": request.language.split("-", 1)[0].lower(),
        }
        if request.chunking_strategy is not None:
            data["chunking_strategy"] = request.chunking_strategy
        if request.prompt:
            data["prompt"] = request.prompt
        filename = f"governed-source{_SUFFIXES[request.media_type]}"
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{root}/v1/audio/transcriptions",
                    headers=self._headers(credential),
                    data=data,
                    files={"file": (filename, request.audio, request.media_type)},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTranscriptFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderTranscriptFailure(
                "provider_response", retryable=False
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderTranscriptFailure("provider_response", retryable=False)

        audio = inspect_governed_wav(
            request.audio,
            max_duration_seconds=request.max_duration_seconds,
        )
        source_duration_seconds = int(audio["duration_ms"]) / 1_000.0
        segments: tuple[ProviderDiarizedSegmentResult, ...] = ()
        speaker_count = 1
        if request.operation == "diarize":
            segments = _diarized_segments(
                payload,
                source_duration_seconds=source_duration_seconds,
            )
            speaker_count = len({item.speaker_label for item in segments})
            raw_text = payload.get("text")
            normalized = (
                _normalized_text(raw_text)
                if isinstance(raw_text, str) and raw_text.strip()
                else "\n".join(item.text for item in segments)
            )
            reported_duration = _finite_number(payload.get("duration"))
            if (
                reported_duration is not None
                and abs(reported_duration - source_duration_seconds)
                > _TIMELINE_TOLERANCE_SECONDS
            ):
                raise ProviderTranscriptFailure("provider_response", retryable=False)
        else:
            normalized = _normalized_text(payload.get("text"))
            reported_duration = None

        estimate, pricing = estimate_openai_transcription_cost(
            int(audio["duration_ms"]),
            model=request.model,
        )
        usage = _safe_usage(
            payload,
            request=request,
            estimate=estimate,
            pricing=pricing,
        )
        request_id = response.headers.get("x-request-id")
        return ProviderTranscriptResult(
            text=normalized,
            language=request.language,
            request_id=request_id,
            metadata={
                "model": request.model,
                "operation": request.operation,
                "response_format": request.response_format,
                "chunking_strategy": request.chunking_strategy,
                "source_bytes": len(request.audio),
                "provider_reported_duration_seconds": reported_duration,
                "segment_count": len(segments) if segments else 1,
                "speaker_count": speaker_count,
                "raw_speaker_labels_returned": False,
                **audio,
            },
            usage=usage,
            segments=segments,
            actual_cost_usd=None,
            cost_basis="official_estimated_per_minute",
        )


def default_transcript_adapters(
    *, timeout_seconds: float = 120.0
) -> dict[str, OpenAITranscriptAdapter]:
    return {
        "openai": OpenAITranscriptAdapter(timeout_seconds=timeout_seconds),
    }
