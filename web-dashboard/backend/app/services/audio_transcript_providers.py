"""Phase 36G exact provider transports for governed speech-to-text.

Durable state, tenancy, arm-before-request, ambiguity handling, private storage and
public redaction live outside this module. The synchronous transport never retries.
"""
from __future__ import annotations

import hashlib
import io
import re
import wave
from dataclasses import dataclass
from typing import Any

import httpx

_OPENAI_MODEL = "gpt-4o-mini-transcribe-2025-12-15"
_OPENAI_TRANSCRIPTION_PER_MINUTE_USD = 0.003
_OPENAI_AUDIO_INPUT_USD_PER_MILLION_TOKENS = 1.25
_OPENAI_TEXT_OUTPUT_USD_PER_MILLION_TOKENS = 5.00
_OPENAI_PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MEDIA_TYPES = frozenset({"audio/wav", "audio/x-wav"})
_SUFFIXES = {"audio/wav": ".wav", "audio/x-wav": ".wav"}


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
    response_format: str = "json"
    prompt: str | None = None
    max_source_bytes: int = 20_971_520
    max_duration_seconds: int = 600


@dataclass(frozen=True, slots=True)
class ProviderTranscriptResult:
    text: str
    language: str
    request_id: str | None
    metadata: dict[str, Any]
    usage: dict[str, Any]
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
) -> tuple[float, dict[str, Any]]:
    if not 1 <= int(duration_ms) <= 3_600_000:
        raise ProviderTranscriptFailure("provider_pricing_unknown", retryable=False)
    minutes = float(duration_ms) / 60_000.0
    estimate = round(minutes * _OPENAI_TRANSCRIPTION_PER_MINUTE_USD, 9)
    return estimate, {
        "pricing_revision": "2026-08-22",
        "pricing_source": _OPENAI_PRICING_SOURCE,
        "pricing_unit": "audio_minute_estimate",
        "estimated_price_per_minute_usd": _OPENAI_TRANSCRIPTION_PER_MINUTE_USD,
        "audio_input_usd_per_million_tokens": (
            _OPENAI_AUDIO_INPUT_USD_PER_MILLION_TOKENS
        ),
        "text_output_usd_per_million_tokens": (
            _OPENAI_TEXT_OUTPUT_USD_PER_MILLION_TOKENS
        ),
        "duration_ms": int(duration_ms),
        "billing_note": (
            "The provider publishes an estimated per-minute cost, while this "
            "endpoint does not return authoritative per-request usage."
        ),
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
        if request.provider != "openai" or request.model != _OPENAI_MODEL:
            raise ProviderTranscriptFailure(
                "provider_operation_unsupported", retryable=False
            )
        if request.response_format != "json":
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
        text = payload.get("text")
        if not isinstance(text, str):
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        normalized = "\n".join(
            line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
        ).strip()
        if not 1 <= len(normalized) <= 2_000_000 or "\x00" in normalized:
            raise ProviderTranscriptFailure("provider_response", retryable=False)
        audio = inspect_governed_wav(
            request.audio,
            max_duration_seconds=request.max_duration_seconds,
        )
        estimate, pricing = estimate_openai_transcription_cost(
            int(audio["duration_ms"])
        )
        request_id = response.headers.get("x-request-id")
        return ProviderTranscriptResult(
            text=normalized,
            language=request.language,
            request_id=request_id,
            metadata={
                "model": request.model,
                "response_format": request.response_format,
                "source_bytes": len(request.audio),
                **audio,
            },
            usage={
                **pricing,
                "estimated_cost_usd": estimate,
                "actual_cost_known": False,
            },
            actual_cost_usd=None,
            cost_basis="official_estimated_per_minute",
        )


def default_transcript_adapters(
    *, timeout_seconds: float = 120.0
) -> dict[str, OpenAITranscriptAdapter]:
    return {
        "openai": OpenAITranscriptAdapter(timeout_seconds=timeout_seconds),
    }
