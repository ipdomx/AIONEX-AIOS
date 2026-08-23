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


def default_music_adapters(
    *,
    timeout_seconds: float = 180.0,
    max_content_bytes: int = 67_108_864,
) -> dict[str, ProviderMusicAdapter]:
    return {
        "gemini": GeminiLyriaMusicAdapter(
            timeout_seconds=timeout_seconds,
            max_content_bytes=max_content_bytes,
        )
    }
