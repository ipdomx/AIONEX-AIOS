"""Exact governed Lyria 3 transports for Gemini and Replicate.

This module owns only provider submission/poll/download boundaries. Durable
arming, tenant scope, leases, fencing, object storage, local FFmpeg QA, Studio
revisions, and cost approvals live in the runtime/pipeline layers. No adapter
automatically resubmits a generation request.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx

_GEMINI_LYRIA_MODELS = {
    "draft": ("lyria-3-clip-preview", 0.04),
    "final": ("lyria-3-pro-preview", 0.08),
}
_REPLICATE_LYRIA_MODELS = {
    "draft": ("google/lyria-3", 0.04, 30),
    "final": ("google/lyria-3-pro", 0.08, None),
}
_REPLICATE_OUTPUT_HOST = "replicate.delivery"
_REPLICATE_PENDING = frozenset({"starting", "processing"})
_REPLICATE_TERMINAL = frozenset({"succeeded", "failed", "canceled", "aborted"})
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
    output_url: str | None
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
        route = _GEMINI_LYRIA_MODELS.get(request.tier)
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


class ReplicateLyriaMusicAdapter:
    """Durable Replicate route: submit once, then poll the same Prediction ID."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 240.0,
        max_content_bytes: int = 67_108_864,
        poll_seconds: float = 2.0,
        max_polls: int = 180,
    ) -> None:
        if not 0 <= float(poll_seconds) <= 30:
            raise ValueError("Replicate poll interval is outside the allowed range")
        if not 1 <= int(max_polls) <= 600:
            raise ValueError("Replicate poll count is outside the allowed range")
        self.transport = transport
        self.timeout_seconds = float(timeout_seconds)
        self.max_content_bytes = int(max_content_bytes)
        self.poll_seconds = float(poll_seconds)
        self.max_polls = int(max_polls)

    @staticmethod
    def _validate_request(request: ProviderMusicRequest) -> tuple[str, float, int | None]:
        if request.provider != "replicate" or request.operation != "generate-music":
            raise ProviderMusicFailure("provider_operation_unsupported", retryable=False)
        route = _REPLICATE_LYRIA_MODELS.get(request.tier)
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
        token = credential.strip()
        if not token or any(character.isspace() for character in token):
            raise ProviderMusicFailure("provider_unconfigured", retryable=False)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "AIONEX-AIOS/36G",
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

    @staticmethod
    def _payload(response: httpx.Response, *, ambiguous: bool) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderMusicFailure(
                "provider_submission_ambiguous" if ambiguous else "provider_response",
                retryable=False if ambiguous else True,
                safe_to_resubmit=False,
                ambiguous_submission=ambiguous,
                http_status=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderMusicFailure(
                "provider_submission_ambiguous" if ambiguous else "provider_response",
                retryable=False if ambiguous else True,
                safe_to_resubmit=False,
                ambiguous_submission=ambiguous,
                http_status=response.status_code,
            )
        return payload

    @staticmethod
    def _output_url(payload: dict[str, Any]) -> str | None:
        output = payload.get("output")
        if output is None:
            return None
        if isinstance(output, list):
            values = [item.strip() for item in output if isinstance(item, str) and item.strip()]
            if len(values) != 1:
                raise ProviderMusicFailure("provider_audio_multiple", retryable=False)
            output = values[0]
        if not isinstance(output, str) or not output.strip():
            raise ProviderMusicFailure("provider_output_url", retryable=False)
        value = output.strip()
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not (host == _REPLICATE_OUTPUT_HOST or host.endswith("." + _REPLICATE_OUTPUT_HOST))
        ):
            raise ProviderMusicFailure("provider_output_url", retryable=False)
        return value

    @classmethod
    def _prediction(
        cls,
        payload: dict[str, Any],
        *,
        ambiguous: bool,
    ) -> tuple[str, str, str | None, dict[str, Any]]:
        prediction_id = str(payload.get("id") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        if (
            not prediction_id
            or len(prediction_id) > 200
            or status not in (_REPLICATE_PENDING | _REPLICATE_TERMINAL)
        ):
            raise ProviderMusicFailure(
                "provider_submission_ambiguous" if ambiguous else "provider_response",
                retryable=False if ambiguous else True,
                safe_to_resubmit=False,
                ambiguous_submission=ambiguous,
            )
        output_url = cls._output_url(payload)
        raw_metrics = payload.get("metrics")
        metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
        metadata = {
            "prediction_status": status,
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
        model, _fixed_cost, _nominal_duration = self._validate_request(request)
        api_root = base_url.rstrip("/")
        if api_root != "https://api.replicate.com":
            raise ProviderMusicFailure("provider_base_url", retryable=False)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=min(self.timeout_seconds, 90.0),
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{api_root}/v1/models/{model}/predictions",
                    headers={**self._headers(credential), "Prefer": "wait=60"},
                    json={"input": {"prompt": self._prompt(request)}},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure(
                "provider_submission_ambiguous",
                retryable=False,
                safe_to_resubmit=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response)
        data = self._payload(response, ambiguous=True)
        prediction_id, status, output_url, metadata = self._prediction(
            data,
            ambiguous=True,
        )
        return ProviderMusicSubmission(
            prediction_id=prediction_id,
            status=status,
            output_url=output_url,
            metadata={**metadata, "replicate_model": model},
        )

    async def poll(
        self,
        prediction_id: str,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderMusicPoll:
        job_id = prediction_id.strip()
        api_root = base_url.rstrip("/")
        if not job_id or len(job_id) > 200:
            raise ProviderMusicFailure("provider_job_invalid", retryable=False)
        if api_root != "https://api.replicate.com":
            raise ProviderMusicFailure("provider_base_url", retryable=False)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=min(self.timeout_seconds, 90.0),
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{api_root}/v1/predictions/{quote(job_id, safe='')}",
                    headers=self._headers(credential),
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure(
                "provider_poll_network",
                retryable=True,
                safe_to_resubmit=False,
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderMusicFailure(
                "provider_poll_unavailable",
                retryable=True,
                safe_to_resubmit=False,
                http_status=response.status_code,
                metadata=_safe_error_metadata(response),
            )
        if response.status_code >= 400:
            raise _failure_for_response(response)
        data = self._payload(response, ambiguous=False)
        returned_id, status, output_url, metadata = self._prediction(
            data,
            ambiguous=False,
        )
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
    ) -> ProviderMusicResult:
        _model, fixed_cost, nominal_duration = self._validate_request(request)
        validated_url = self._output_url({"output": output_url})
        if validated_url is None:
            raise ProviderMusicFailure("provider_output_url", retryable=False)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=max(self.timeout_seconds, 120.0),
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    validated_url,
                    headers={"Accept": "audio/mpeg", "User-Agent": "AIONEX-AIOS/36G"},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderMusicFailure(
                "provider_output_download",
                retryable=True,
                safe_to_resubmit=False,
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderMusicFailure(
                "provider_output_download",
                retryable=True,
                safe_to_resubmit=False,
                http_status=response.status_code,
            )
        if response.status_code >= 400:
            raise ProviderMusicFailure(
                "provider_output_download",
                retryable=False,
                safe_to_resubmit=False,
                http_status=response.status_code,
            )
        body = bytes(response.content)
        inspected = inspect_mp3_bytes(body, max_content_bytes=self.max_content_bytes)
        return ProviderMusicResult(
            body=body,
            content_type="audio/mpeg",
            request_id=prediction_id,
            metadata={
                "provider": "replicate",
                "model": request.model,
                "tier": request.tier,
                "preview_model": True,
                "provider_output_format": "mp3",
                "provider_sample_rate_hz": 48_000,
                "provider_channels": 2,
                "nominal_duration_seconds": nominal_duration,
                "prediction_id_sha256": hashlib.sha256(prediction_id.encode()).hexdigest(),
                "prediction_status": "succeeded",
                "output_host": _REPLICATE_OUTPUT_HOST,
                "instrumental_only": request.instrumental_only,
                "synthid_watermark_expected": True,
                "raw_output_url_returned": False,
                "raw_returned_text_returned": False,
                **inspected,
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

    async def invoke(
        self,
        request: ProviderMusicRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderMusicResult:
        """Compatibility wrapper; the permanent Worker uses durable submit/poll methods."""
        submission = await self.submit(
            request,
            credential=credential,
            base_url=base_url,
        )
        status = submission.status
        output_url = submission.output_url
        poll_count = 0
        while status in _REPLICATE_PENDING:
            if poll_count >= self.max_polls:
                raise ProviderMusicFailure(
                    "provider_poll_exhausted",
                    retryable=False,
                    safe_to_resubmit=False,
                    metadata={"poll_count": poll_count, "prediction_status": status},
                )
            poll_count += 1
            if self.poll_seconds:
                await asyncio.sleep(self.poll_seconds)
            poll = await self.poll(
                submission.prediction_id,
                credential=credential,
                base_url=base_url,
            )
            status = poll.status
            output_url = poll.output_url
        if status in {"failed", "canceled", "aborted"}:
            raise ProviderMusicFailure(
                f"provider_prediction_{status}",
                retryable=False,
                safe_to_resubmit=False,
                metadata={"poll_count": poll_count, "prediction_status": status},
            )
        if status != "succeeded" or not output_url:
            raise ProviderMusicFailure(
                "provider_poll_response",
                retryable=False,
                safe_to_resubmit=False,
                metadata={"poll_count": poll_count, "prediction_status": status},
            )
        result = await self.download(
            request,
            prediction_id=submission.prediction_id,
            output_url=output_url,
        )
        return ProviderMusicResult(
            body=result.body,
            content_type=result.content_type,
            request_id=result.request_id,
            metadata={
                **result.metadata,
                "poll_count": poll_count,
                "prediction_status": status,
            },
            usage={**result.usage, "poll_count": poll_count},
            actual_cost_usd=result.actual_cost_usd,
            cost_basis=result.cost_basis,
        )


def default_music_adapters(
    *,
    timeout_seconds: float = 180.0,
    max_content_bytes: int = 67_108_864,
    replicate_poll_seconds: float = 2.0,
    replicate_max_polls: int = 180,
) -> dict[str, ProviderMusicAdapter]:
    return {
        "replicate": ReplicateLyriaMusicAdapter(
            timeout_seconds=timeout_seconds,
            max_content_bytes=max_content_bytes,
            poll_seconds=replicate_poll_seconds,
            max_polls=replicate_max_polls,
        ),
        "gemini": GeminiLyriaMusicAdapter(
            timeout_seconds=timeout_seconds,
            max_content_bytes=max_content_bytes,
        ),
    }
