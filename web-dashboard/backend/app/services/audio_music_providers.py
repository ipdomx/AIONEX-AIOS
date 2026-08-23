"""Exact Gemini Lyria 3 music-generation transport.

This module owns only the synchronous provider boundary. Durable arming, tenant
scope, leases, fencing, object storage, local FFmpeg QA, Studio revisions, and
cost approvals live in the runtime/pipeline layers. The transport never retries.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

_LYRIA_MODELS = {
    "draft": ("lyria-3-clip-preview", 0.04),
    "final": ("lyria-3-pro-preview", 0.08),
}
_ALLOWED_MEDIA_TYPES = frozenset({"audio/mpeg", "audio/mp3"})


@dataclass(frozen=True, slots=True)
class ProviderMusicRequest:
    provider: str
    model: str
    operation: str
    tier: str
    prompt: str
    instrumental_only: bool
    lyrics: str
    output_format: str = "mp3"


@dataclass(frozen=True, slots=True)
class ProviderMusicSubmission:
    prediction_id: str
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderMusicPoll:
    prediction_id: str
    status: str
    output_url: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderMusicResult:
    body: bytes
    content_type: str
    request_id: str | None
    metadata: dict[str, Any]
    usage: dict[str, Any]
    actual_cost_usd: float
    cost_basis: str = "official_fixed_request"


class ProviderMusicFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        safe_to_resubmit: bool = False,
        ambiguous_submission: bool = False,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
        message: str = "Music provider request failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.safe_to_resubmit = safe_to_resubmit
        self.ambiguous_submission = ambiguous_submission
        self.http_status = http_status
        self.metadata = metadata or {}


class ProviderMusicAdapter(Protocol):
    async def invoke(
        self,
        request: ProviderMusicRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderMusicResult:
        ...


def _safe_error_metadata(response: httpx.Response) -> dict[str, Any]:
    result: dict[str, Any] = {"http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        return result
    if not isinstance(payload, dict):
        return result
    error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    for key in ("status", "code"):
        value = error.get(key) if isinstance(error, dict) else None
        if isinstance(value, (str, int, float, bool)):
            result[key] = str(value)[:160]
    details = error.get("details") if isinstance(error, dict) else None
    if isinstance(details, list):
        reasons: list[str] = []
        for item in details[:16]:
            if not isinstance(item, dict):
                continue
            value = item.get("reason") or item.get("@type")
            if isinstance(value, str) and value:
                reasons.append(value[:160])
        if reasons:
            result["reasons"] = sorted(set(reasons))
    return result


def _failure_for_response(response: httpx.Response) -> ProviderMusicFailure:
    status = response.status_code
    metadata = _safe_error_metadata(response)
    if status in {400, 401, 402, 403, 404, 409, 413, 415, 422, 429}:
        if status in {401, 403}:
            code = "provider_auth"
        elif status == 402:
            code = "provider_billing"
        elif status == 429:
            code = "provider_rate_limited"
        else:
            code = "provider_request"
        # Cost minimization is strict: even a normally retryable 429 is not
        # automatically resubmitted. The user must create a new explicit request.
        return ProviderMusicFailure(
            code,
            retryable=False,
            safe_to_resubmit=False,
            http_status=status,
            metadata=metadata,
        )
    if status >= 500:
        return ProviderMusicFailure(
            "provider_submission_ambiguous",
            retryable=False,
            ambiguous_submission=True,
            http_status=status,
            metadata=metadata,
        )
    return ProviderMusicFailure(
        "provider_response",
        retryable=False,
        http_status=status,
        metadata=metadata,
    )


def inspect_mp3_bytes(body: bytes, *, max_content_bytes: int) -> dict[str, Any]:
    if not body or len(body) < 4 or len(body) > int(max_content_bytes):
        raise ProviderMusicFailure("provider_audio_size", retryable=False)
    prefix = body[:4096]
    valid = body.startswith(b"ID3") or any(
        prefix[index] == 0xFF and prefix[index + 1] & 0xE0 == 0xE0
        for index in range(len(prefix) - 1)
    )
    if not valid:
        raise ProviderMusicFailure("provider_audio_invalid", retryable=False)
    return {
        "container": "mp3",
        "codec": "mp3",
        "size_bytes": len(body),
    }


def _text_hash(parts: list[str]) -> tuple[str | None, int]:
    text = "\n".join(item.strip() for item in parts if item.strip()).strip()
    if not text:
        return None, 0
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text)


class GeminiLyriaMusicAdapter:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 180.0,
        max_content_bytes: int = 67_108_864,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = float(timeout_seconds)
        self.max_content_bytes = int(max_content_bytes)

    @staticmethod
    def _validate_request(request: ProviderMusicRequest) -> tuple[str, float]:
        if request.provider != "gemini" or request.operation != "generate-music":
            raise ProviderMusicFailure("provider_operation_unsupported", retryable=False)
        route = _LYRIA_MODELS.get(request.tier)
        if route is None or route[0] != request.model:
            raise ProviderMusicFailure("provider_model_unsupported", retryable=False)
        if request.output_format != "mp3":
            raise ProviderMusicFailure("provider_format_unsupported", retryable=False)
        if not 8 <= len(request.prompt.strip()) <= 32_000 or "\x00" in request.prompt:
            raise ProviderMusicFailure("provider_prompt_invalid", retryable=False)
        if request.instrumental_only:
            if request.lyrics.strip():
                raise ProviderMusicFailure("provider_lyrics_invalid", retryable=False)
        elif not 1 <= len(request.lyrics.strip()) <= 20_000:
            raise ProviderMusicFailure("provider_lyrics_invalid", retryable=False)
        return route

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        key = credential.strip()
        if not key:
            raise ProviderMusicFailure("provider_unconfigured", retryable=False)
        return {
            "x-goog-api-key": key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _prompt(request: ProviderMusicRequest) -> str:
        sections = [request.prompt.strip()]
        if request.instrumental_only:
            sections.append("Instrumental only, no vocals.")
        else:
            sections.append("Use only the following original or licensed lyrics:")
            sections.append(request.lyrics.strip())
        return "\n\n".join(sections)

    async def invoke(
        self,
        request: ProviderMusicRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderMusicResult:
        model, fixed_cost = self._validate_request(request)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": self._prompt(request)}],
                }
            ]
        }
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent",
                    headers=self._headers(credential),
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderMusicFailure("provider_response", retryable=False) from exc
        if not isinstance(data, dict):
            raise ProviderMusicFailure("provider_response", retryable=False)
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderMusicFailure("provider_response", retryable=False)
        audio_body: bytes | None = None
        audio_type = ""
        text_parts: list[str] = []
        for candidate in candidates[:4]:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text)
                inline = part.get("inlineData")
                if not isinstance(inline, dict):
                    inline = part.get("inline_data")
                if not isinstance(inline, dict):
                    continue
                mime = str(inline.get("mimeType") or inline.get("mime_type") or "").lower()
                encoded = inline.get("data")
                if mime not in _ALLOWED_MEDIA_TYPES or not isinstance(encoded, str):
                    continue
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError) as exc:
                    raise ProviderMusicFailure("provider_audio_invalid", retryable=False) from exc
                if audio_body is not None:
                    raise ProviderMusicFailure("provider_audio_multiple", retryable=False)
                audio_body = decoded
                audio_type = "audio/mpeg"
        if audio_body is None:
            raise ProviderMusicFailure("provider_audio_size", retryable=False)
        inspect_mp3_bytes(audio_body, max_content_bytes=self.max_content_bytes)
        returned_text_sha256, returned_text_characters = _text_hash(text_parts)
        usage = data.get("usageMetadata")
        usage_metadata = usage if isinstance(usage, dict) else {}
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-goog-request-id")
        )
        return ProviderMusicResult(
            body=audio_body,
            content_type=audio_type,
            request_id=request_id,
            metadata={
                "model": model,
                "tier": request.tier,
                "preview_model": True,
                "provider_output_format": "mp3",
                "provider_sample_rate_hz": 44_100,
                "provider_channels": 2,
                "nominal_duration_seconds": 30 if request.tier == "draft" else None,
                "returned_text_sha256": returned_text_sha256,
                "returned_text_characters": returned_text_characters,
                "raw_returned_text_returned": False,
                "instrumental_only": request.instrumental_only,
                "synthid_watermark_expected": True,
            },
            usage={
                **usage_metadata,
                "provider_usage_reported": bool(usage_metadata),
                "official_fixed_request_usd": fixed_cost,
                "pricing_revision": "2026-08-23",
                "preview_model": True,
            },
            actual_cost_usd=fixed_cost,
        )



_REPLICATE_MODELS = {
    "lyria-3-clip-preview": ("google", "lyria-3", 0.04),
    "lyria-3-pro-preview": ("google", "lyria-3-pro", 0.08),
}
_REPLICATE_PENDING = frozenset({"starting", "processing"})
_REPLICATE_TERMINAL = frozenset({"succeeded", "failed", "canceled"})


class ReplicateLyriaMusicAdapter:
    """Durable asynchronous Replicate route for the official Google Lyria models."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        max_content_bytes: int = 67_108_864,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = float(timeout_seconds)
        self.max_content_bytes = int(max_content_bytes)

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        token = credential.strip()
        if not token:
            raise ProviderMusicFailure("provider_unconfigured", retryable=False)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _route(request: ProviderMusicRequest) -> tuple[str, str, float]:
        if request.provider != "replicate" or request.operation != "generate-music":
            raise ProviderMusicFailure("provider_operation_unsupported", retryable=False)
        route = _REPLICATE_MODELS.get(request.model)
        if route is None:
            raise ProviderMusicFailure("provider_model_unsupported", retryable=False)
        expected_model = "lyria-3-clip-preview" if request.tier == "draft" else "lyria-3-pro-preview"
        if request.model != expected_model or request.output_format != "mp3":
            raise ProviderMusicFailure("provider_model_unsupported", retryable=False)
        if not 8 <= len(request.prompt.strip()) <= 32_000 or "\x00" in request.prompt:
            raise ProviderMusicFailure("provider_prompt_invalid", retryable=False)
        if request.instrumental_only:
            if request.lyrics.strip():
                raise ProviderMusicFailure("provider_lyrics_invalid", retryable=False)
        elif not 1 <= len(request.lyrics.strip()) <= 20_000:
            raise ProviderMusicFailure("provider_lyrics_invalid", retryable=False)
        return route

    @staticmethod
    def _prompt(request: ProviderMusicRequest) -> str:
        parts = [request.prompt.strip()]
        if request.instrumental_only:
            parts.append("Instrumental only, no vocals.")
        else:
            parts.extend((
                "Use only these original, licensed, or public-domain lyrics:",
                request.lyrics.strip(),
            ))
        return "\n\n".join(parts)

    @staticmethod
    def _prediction(payload: Any) -> tuple[str, str, str | None, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ProviderMusicFailure("provider_response", retryable=False)
        prediction_id = str(payload.get("id") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        if not prediction_id or status not in (_REPLICATE_PENDING | _REPLICATE_TERMINAL):
            raise ProviderMusicFailure("provider_response", retryable=False)
        raw_output = payload.get("output")
        output_url: str | None = None
        if isinstance(raw_output, str) and raw_output.strip():
            output_url = raw_output.strip()
        elif isinstance(raw_output, list):
            candidates = [str(item).strip() for item in raw_output if isinstance(item, str) and str(item).strip()]
            if len(candidates) == 1:
                output_url = candidates[0]
            elif len(candidates) > 1:
                raise ProviderMusicFailure("provider_audio_multiple", retryable=False)
        raw_metrics = payload.get("metrics")
        metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
        metadata = {
            "status": status,
            "poll_count": 0,
            "predict_time_seconds": metrics.get("predict_time"),
            "total_time_seconds": metrics.get("total_time"),
            "output_url_recorded": bool(output_url),
            "raw_output_url_returned": False,
        }
        return prediction_id, status, output_url, metadata

    async def submit(
        self,
        request: ProviderMusicRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderMusicSubmission:
        owner, name, _fixed_cost = self._route(request)
        payload = {"input": {"prompt": self._prompt(request)}}
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1/models/{owner}/{name}/predictions",
                    headers=self._headers(credential),
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderMusicFailure(
                "provider_submission_ambiguous", retryable=False, ambiguous_submission=True
            ) from exc
        prediction_id, status, _output_url, metadata = self._prediction(data)
        return ProviderMusicSubmission(
            prediction_id=prediction_id,
            status=status,
            metadata={**metadata, "replicate_model": f"{owner}/{name}"},
        )

    async def poll(
        self,
        prediction_id: str,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderMusicPoll:
        job_id = prediction_id.strip()
        if not job_id or len(job_id) > 200:
            raise ProviderMusicFailure("provider_job_invalid", retryable=False)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/v1/predictions/{job_id}",
                    headers=self._headers(credential),
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure(
                "provider_poll_network",
                retryable=True,
                safe_to_resubmit=False,
            ) from exc
        if response.status_code >= 400:
            failure = _failure_for_response(response)
            if response.status_code >= 500:
                failure.ambiguous_submission = False
                failure.retryable = True
            raise failure
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderMusicFailure("provider_poll_response", retryable=True) from exc
        returned_id, status, output_url, metadata = self._prediction(data)
        if returned_id != job_id:
            raise ProviderMusicFailure("provider_job_mismatch", retryable=False)
        return ProviderMusicPoll(
            prediction_id=job_id,
            status=status,
            output_url=output_url,
            metadata=metadata,
        )

    async def download(
        self,
        request: ProviderMusicRequest,
        *,
        prediction_id: str,
        output_url: str,
        credential: str,
    ) -> ProviderMusicResult:
        _owner, _name, fixed_cost = self._route(request)
        parsed = urlsplit(output_url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "replicate.delivery" or host.endswith(".replicate.delivery")):
            raise ProviderMusicFailure("provider_output_url_invalid", retryable=False)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=max(self.timeout_seconds, 120.0),
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    output_url,
                    headers={"Accept": "audio/mpeg"},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure("provider_output_download", retryable=True) from exc
        if response.status_code >= 400:
            raise ProviderMusicFailure(
                "provider_output_download", retryable=response.status_code >= 500, http_status=response.status_code
            )
        body = bytes(response.content)
        inspect_mp3_bytes(body, max_content_bytes=self.max_content_bytes)
        return ProviderMusicResult(
            body=body,
            content_type="audio/mpeg",
            request_id=prediction_id,
            metadata={
                "model": request.model,
                "tier": request.tier,
                "preview_model": True,
                "provider_output_format": "mp3",
                "provider_sample_rate_hz": 44_100,
                "provider_channels": 2,
                "nominal_duration_seconds": 30 if request.tier == "draft" else None,
                "returned_text_sha256": None,
                "returned_text_characters": 0,
                "raw_returned_text_returned": False,
                "instrumental_only": request.instrumental_only,
                "synthid_watermark_expected": True,
                "output_url_recorded": True,
                "raw_output_url_returned": False,
            },
            usage={
                "provider_usage_reported": False,
                "official_fixed_request_usd": fixed_cost,
                "pricing_revision": "2026-08-23",
                "preview_model": True,
                "billing_route": "replicate-official-google-model",
            },
            actual_cost_usd=fixed_cost,
        )



class StabilityStableAudioMusicAdapter:
    """Synchronous one-attempt Stable Audio 2.5 text-to-audio transport."""

    _MODEL = "stable-audio-2.5"
    _FIXED_COST_USD = 0.20
    _CREDITS_PER_SUCCESS = 20
    _CREDIT_USD = 0.01
    _DURATION_SECONDS = 30

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 240.0,
        max_content_bytes: int = 67_108_864,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = float(timeout_seconds)
        self.max_content_bytes = int(max_content_bytes)

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        token = credential.strip()
        if not token:
            raise ProviderMusicFailure("provider_unconfigured", retryable=False)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "audio/*",
            "stability-client-id": "AIONEX",
            "stability-client-version": "36G-stage7d",
        }

    @classmethod
    def _validate_request(cls, request: ProviderMusicRequest) -> None:
        if request.provider != "stability" or request.operation != "generate-music":
            raise ProviderMusicFailure("provider_operation_unsupported", retryable=False)
        if request.model != cls._MODEL or request.tier != "draft":
            raise ProviderMusicFailure("provider_model_unsupported", retryable=False)
        if request.output_format != "mp3":
            raise ProviderMusicFailure("provider_format_unsupported", retryable=False)
        if not 8 <= len(request.prompt.strip()) <= 10_000 or "\x00" in request.prompt:
            raise ProviderMusicFailure("provider_prompt_invalid", retryable=False)
        if not request.instrumental_only or request.lyrics.strip():
            raise ProviderMusicFailure("provider_lyrics_invalid", retryable=False)

    async def invoke(
        self,
        request: ProviderMusicRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderMusicResult:
        self._validate_request(request)
        root = base_url.rstrip("/")
        if root != "https://api.stability.ai":
            raise ProviderMusicFailure("provider_base_url_invalid", retryable=False)
        data = {
            "prompt": request.prompt.strip() + "\n\nInstrumental only, no vocals.",
            "output_format": "mp3",
            "duration": str(self._DURATION_SECONDS),
            "model": self._MODEL,
        }
        # A dummy empty multipart file mirrors Stability's official text-to-audio
        # request shape and lets httpx own the multipart Content-Type boundary.
        files = {"none": ("", b"")}
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{root}/v2beta/audio/stable-audio-2/text-to-audio",
                    headers=self._headers(credential),
                    data=data,
                    files=files,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            # Stability documents billing only for successful generations.
            # Every HTTP error remains terminal for this user request; 5xx is
            # conservatively ambiguous because the synchronous POST crossed the
            # provider boundary and must never be auto-resubmitted.
            if response.status_code >= 500:
                raise ProviderMusicFailure(
                    "provider_submission_ambiguous",
                    retryable=False,
                    ambiguous_submission=True,
                    http_status=response.status_code,
                    metadata=_safe_error_metadata(response),
                )
            failure = _failure_for_response(response)
            failure.retryable = False
            failure.safe_to_resubmit = False
            failure.ambiguous_submission = False
            raise failure
        content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if content_type not in {"audio/mpeg", "audio/mp3", "application/octet-stream"}:
            raise ProviderMusicFailure("provider_audio_type", retryable=False)
        body = bytes(response.content)
        inspected = inspect_mp3_bytes(body, max_content_bytes=self.max_content_bytes)
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-stability-request-id")
        )
        return ProviderMusicResult(
            body=body,
            content_type="audio/mpeg",
            request_id=request_id,
            metadata={
                "provider": "stability",
                "model": self._MODEL,
                "tier": "draft",
                "preview_model": False,
                "provider_output_format": "mp3",
                "provider_sample_rate_hz": 44_100,
                "provider_channels": 2,
                "nominal_duration_seconds": self._DURATION_SECONDS,
                "returned_text_sha256": None,
                "returned_text_characters": 0,
                "raw_returned_text_returned": False,
                "instrumental_only": True,
                "ai_generated_disclosure_required": True,
                "synthid_watermark_expected": False,
                **inspected,
            },
            usage={
                "provider_usage_reported": False,
                "official_credits_per_success": self._CREDITS_PER_SUCCESS,
                "official_credit_usd": self._CREDIT_USD,
                "official_fixed_request_usd": self._FIXED_COST_USD,
                "failed_generations_charged": False,
                "pricing_revision": "2026-08-23",
                "preview_model": False,
                "billing_route": "stability-stable-audio-2.5",
            },
            actual_cost_usd=self._FIXED_COST_USD,
        )

def default_music_adapters(
    *,
    timeout_seconds: float = 180.0,
    max_content_bytes: int = 67_108_864,
) -> dict[str, Any]:
    return {
        "gemini": GeminiLyriaMusicAdapter(
            timeout_seconds=timeout_seconds,
            max_content_bytes=max_content_bytes,
        ),
        "replicate": ReplicateLyriaMusicAdapter(
            timeout_seconds=min(timeout_seconds, 60.0),
            max_content_bytes=max_content_bytes,
        ),
        "stability": StabilityStableAudioMusicAdapter(
            timeout_seconds=max(timeout_seconds, 240.0),
            max_content_bytes=max_content_bytes,
        ),
    }
