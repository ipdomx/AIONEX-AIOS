"""Phase 36G exact stock-voice text-to-speech provider transports.

Durable tenant authority, arm-before-spend, lease/fencing, storage and downstream
media rendering live outside this module. The transport never retries a speech
request on its own because the synchronous endpoint has no provider job identity
that can be reconciled after an ambiguous network failure.
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

_OPENAI_STOCK_TTS_MODELS = frozenset({"gpt-4o-mini-tts-2025-12-15"})
_OPENAI_STOCK_VOICES = frozenset(
    {
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "nova",
        "onyx",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    }
)
_OPENAI_TEXT_INPUT_USD_PER_MILLION_TOKENS = 0.60
_OPENAI_AUDIO_OUTPUT_USD_PER_MILLION_TOKENS = 12.00
_OPENAI_PCM_SAMPLE_RATE_HZ = 24_000
_OPENAI_PCM_CHANNELS = 1
_OPENAI_PCM_SAMPLE_WIDTH_BYTES = 2


@dataclass(frozen=True, slots=True)
class ProviderSpeechRequest:
    provider: str
    model: str
    operation: str
    input_text: str
    voice: str
    instructions: str = ""
    response_format: str = "wav"
    speed: float = 1.0
    max_duration_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class ProviderSpeechResult:
    body: bytes
    content_type: str
    request_id: str | None
    metadata: dict[str, Any]
    usage: dict[str, Any]
    actual_cost_usd: float | None = None
    cost_basis: str = "official_rate_cap"


class ProviderSpeechFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        safe_to_resubmit: bool = False,
        ambiguous_submission: bool = False,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
        message: str = "Speech provider request failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.safe_to_resubmit = safe_to_resubmit
        self.ambiguous_submission = ambiguous_submission
        self.http_status = http_status
        self.metadata = metadata or {}


class ProviderSpeechAdapter(Protocol):
    async def invoke(
        self,
        request: ProviderSpeechRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderSpeechResult:
        ...


def inspect_pcm_wav(body: bytes, *, max_duration_seconds: float) -> dict[str, Any]:
    """Return bounded WAV evidence without retaining audio samples."""
    if not body or len(body) < 44 or body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise ProviderSpeechFailure("provider_audio_invalid", retryable=False)
    try:
        with wave.open(io.BytesIO(body), "rb") as reader:
            channels = int(reader.getnchannels())
            sample_width = int(reader.getsampwidth())
            sample_rate = int(reader.getframerate())
            frame_count = int(reader.getnframes())
            compression = str(reader.getcomptype())
    except (wave.Error, EOFError, OSError) as exc:
        raise ProviderSpeechFailure("provider_audio_invalid", retryable=False) from exc
    if compression != "NONE":
        raise ProviderSpeechFailure("provider_audio_compression", retryable=False)
    if channels not in {1, 2}:
        raise ProviderSpeechFailure("provider_audio_channels", retryable=False)
    if sample_width not in {2, 3, 4}:
        raise ProviderSpeechFailure("provider_audio_sample_width", retryable=False)
    if not 8_000 <= sample_rate <= 96_000 or frame_count <= 0:
        raise ProviderSpeechFailure("provider_audio_format", retryable=False)
    duration = frame_count / sample_rate
    if duration <= 0 or duration > float(max_duration_seconds):
        raise ProviderSpeechFailure("provider_audio_duration", retryable=False)
    return {
        "container": "wav",
        "codec": "pcm",
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "frame_count": frame_count,
        "duration_seconds": round(duration, 6),
    }


def inspect_pcm_s16le(body: bytes, *, max_duration_seconds: float) -> dict[str, Any]:
    """Validate the provider's documented raw 24 kHz signed 16-bit mono PCM."""
    frame_width = _OPENAI_PCM_CHANNELS * _OPENAI_PCM_SAMPLE_WIDTH_BYTES
    if not body or len(body) % frame_width != 0:
        raise ProviderSpeechFailure("provider_audio_invalid", retryable=False)
    frame_count = len(body) // frame_width
    duration = frame_count / _OPENAI_PCM_SAMPLE_RATE_HZ
    if frame_count <= 0 or duration <= 0 or duration > float(max_duration_seconds):
        raise ProviderSpeechFailure("provider_audio_duration", retryable=False)
    return {
        "container": "pcm",
        "codec": "pcm_s16le",
        "channels": _OPENAI_PCM_CHANNELS,
        "sample_width_bytes": _OPENAI_PCM_SAMPLE_WIDTH_BYTES,
        "sample_rate_hz": _OPENAI_PCM_SAMPLE_RATE_HZ,
        "frame_count": frame_count,
        "duration_seconds": round(duration, 6),
        "provider_response_format": "pcm",
    }


def canonical_wav_from_pcm(body: bytes) -> bytes:
    """Wrap validated provider PCM in a canonical finite-length WAV container."""
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(_OPENAI_PCM_CHANNELS)
        writer.setsampwidth(_OPENAI_PCM_SAMPLE_WIDTH_BYTES)
        writer.setframerate(_OPENAI_PCM_SAMPLE_RATE_HZ)
        writer.writeframes(body)
    return output.getvalue()


def _safe_error_metadata(response: httpx.Response) -> dict[str, Any]:
    result: dict[str, Any] = {"http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        return result
    if not isinstance(payload, dict):
        return result
    raw_error = payload.get("error")
    error = raw_error if isinstance(raw_error, dict) else payload
    for key in ("type", "code", "param"):
        value = error.get(key) if isinstance(error, dict) else None
        if isinstance(value, (str, int, float, bool)):
            result[key] = str(value)[:160]
    return result


def _failure_for_response(response: httpx.Response) -> ProviderSpeechFailure:
    status = response.status_code
    metadata = _safe_error_metadata(response)
    if status in {400, 401, 402, 403, 404, 409, 413, 415, 422}:
        code = (
            "provider_auth"
            if status in {401, 403}
            else "provider_billing"
            if status == 402
            else "provider_request"
        )
        return ProviderSpeechFailure(
            code,
            retryable=False,
            http_status=status,
            metadata=metadata,
        )
    if status == 429:
        return ProviderSpeechFailure(
            "provider_rate_limited",
            retryable=True,
            safe_to_resubmit=True,
            http_status=status,
            metadata=metadata,
        )
    if status >= 500:
        return ProviderSpeechFailure(
            "provider_submission_ambiguous",
            retryable=False,
            ambiguous_submission=True,
            http_status=status,
            metadata=metadata,
        )
    return ProviderSpeechFailure(
        "provider_response",
        retryable=False,
        http_status=status,
        metadata=metadata,
    )


class OpenAIStockSpeechAdapter:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 90.0,
        max_content_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_content_bytes = max_content_bytes

    @staticmethod
    def _validate_request(request: ProviderSpeechRequest) -> None:
        if (
            request.provider != "openai"
            or request.model not in _OPENAI_STOCK_TTS_MODELS
            or request.operation != "synthesize-speech"
        ):
            raise ProviderSpeechFailure(
                "provider_operation_unsupported", retryable=False
            )
        if not 1 <= len(request.input_text) <= 4_096:
            raise ProviderSpeechFailure("provider_input_invalid", retryable=False)
        if len(request.instructions) > 4_096:
            raise ProviderSpeechFailure(
                "provider_instructions_invalid", retryable=False
            )
        if request.voice not in _OPENAI_STOCK_VOICES:
            raise ProviderSpeechFailure("provider_voice_unsupported", retryable=False)
        if request.response_format != "wav":
            raise ProviderSpeechFailure("provider_format_unsupported", retryable=False)
        if not 0.25 <= float(request.speed) <= 4.0:
            raise ProviderSpeechFailure("provider_speed_invalid", retryable=False)
        if not 1.0 <= float(request.max_duration_seconds) <= 300.0:
            raise ProviderSpeechFailure(
                "provider_duration_cap_invalid", retryable=False
            )

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        token = credential.strip()
        if not token:
            raise ProviderSpeechFailure("provider_unconfigured", retryable=False)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/octet-stream",
            "Content-Type": "application/json",
        }

    async def invoke(
        self,
        request: ProviderSpeechRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderSpeechResult:
        self._validate_request(request)
        payload: dict[str, Any] = {
            "model": request.model,
            "input": request.input_text,
            "voice": request.voice,
            # Raw PCM has no streamed RIFF length placeholder. The adapter wraps it
            # into a canonical finite WAV only after byte-length duration validation.
            "response_format": "pcm",
            "speed": float(request.speed),
            "stream_format": "audio",
        }
        if request.instructions.strip():
            payload["instructions"] = request.instructions.strip()
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1/audio/speech",
                    headers=self._headers(credential),
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderSpeechFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response)
        provider_pcm = bytes(response.content)
        if not provider_pcm or len(provider_pcm) > self.max_content_bytes:
            raise ProviderSpeechFailure("provider_audio_size", retryable=False)
        audio = inspect_pcm_s16le(
            provider_pcm,
            max_duration_seconds=float(request.max_duration_seconds),
        )
        body = canonical_wav_from_pcm(provider_pcm)
        canonical = inspect_pcm_wav(
            body,
            max_duration_seconds=float(request.max_duration_seconds),
        )
        request_id = response.headers.get("x-request-id")
        usage = {
            "provider_usage_reported": False,
            "input_characters": len(request.input_text),
            "official_text_input_usd_per_million_tokens": (
                _OPENAI_TEXT_INPUT_USD_PER_MILLION_TOKENS
            ),
            "official_audio_output_usd_per_million_tokens": (
                _OPENAI_AUDIO_OUTPUT_USD_PER_MILLION_TOKENS
            ),
            "pricing_revision": "2026-08-22",
            "billing_exact": False,
            "cost_basis": "official_rate_cap",
        }
        return ProviderSpeechResult(
            body=body,
            content_type="audio/wav",
            request_id=request_id,
            metadata={
                **canonical,
                "provider_response_format": audio["provider_response_format"],
                "provider_pcm_size_bytes": len(provider_pcm),
                "canonical_output_format": request.response_format,
                "model": request.model,
                "voice": request.voice,
                "response_format": request.response_format,
                "speed": float(request.speed),
            },
            usage=usage,
            actual_cost_usd=None,
            cost_basis="official_rate_cap",
        )


def default_speech_adapters(
    *,
    timeout_seconds: float = 90.0,
    max_content_bytes: int = 32 * 1024 * 1024,
) -> dict[str, ProviderSpeechAdapter]:
    return {
        "openai": OpenAIStockSpeechAdapter(
            timeout_seconds=timeout_seconds,
            max_content_bytes=max_content_bytes,
        )
    }
