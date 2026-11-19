"""Phase 36F exact provider video transports.

Durable state, tenant authority, arm-before-spend, retries/fencing and storage live
outside this module. This transport layer never retries a video submission on its own.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

_OPENAI_SORA_720_PER_SECOND: dict[str, float] = {
    "sora-2": 0.10,
    "sora-2-pro": 0.30,
}
_OPENAI_SORA_720_SIZES = frozenset({"1280x720", "720x1280"})
_OPENAI_SORA_DURATIONS = frozenset({4, 8, 12})
_OPENAI_VIDEO_STATES = frozenset({"queued", "in_progress", "completed", "failed"})


@dataclass(frozen=True, slots=True)
class ProviderVideoInput:
    body: bytes
    content_type: str
    filename: str = "reference.png"


@dataclass(frozen=True, slots=True)
class ProviderVideoRequest:
    provider: str
    model: str
    operation: str
    prompt: str
    seconds: int
    size: str
    reference: ProviderVideoInput | None = None
    options: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProviderVideoJob:
    job_id: str
    state: str
    progress: int | None
    created_at: int | None
    model: str | None
    seconds: int | None
    size: str | None
    prompt: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderVideoContent:
    body: bytes
    content_type: str


class ProviderVideoFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        safe_to_resubmit: bool = False,
        ambiguous_submission: bool = False,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
        message: str = "Video provider request failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.safe_to_resubmit = safe_to_resubmit
        self.ambiguous_submission = ambiguous_submission
        self.http_status = http_status
        self.metadata = metadata or {}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


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
    for key in ("type", "code", "param"):
        value = error.get(key) if isinstance(error, dict) else None
        if isinstance(value, (str, int, float, bool)):
            safe[key] = str(value)[:160]
    return safe


def _failure_for_response(response: httpx.Response, *, submission: bool) -> ProviderVideoFailure:
    status = response.status_code
    metadata = _safe_error_metadata(response)
    if status in {400, 401, 402, 403, 404, 409, 413, 415, 422}:
        code = "provider_auth" if status in {401, 403} else "provider_billing" if status == 402 else "provider_request"
        return ProviderVideoFailure(code, retryable=False, http_status=status, metadata=metadata)
    if status == 429:
        return ProviderVideoFailure(
            "provider_rate_limited",
            retryable=True,
            safe_to_resubmit=submission,
            http_status=status,
            metadata=metadata,
        )
    if status >= 500:
        return ProviderVideoFailure(
            "provider_submission_ambiguous" if submission else "provider_unavailable",
            retryable=not submission,
            ambiguous_submission=submission,
            http_status=status,
            metadata=metadata,
        )
    return ProviderVideoFailure("provider_response", retryable=False, http_status=status, metadata=metadata)


def _parse_job(payload: Any) -> ProviderVideoJob:
    if not isinstance(payload, dict):
        raise ProviderVideoFailure("provider_response", retryable=False)
    job_id = str(payload.get("id") or "").strip()
    state = str(payload.get("status") or "").strip().lower()
    if not job_id or len(job_id) > 240 or state not in _OPENAI_VIDEO_STATES:
        raise ProviderVideoFailure("provider_response", retryable=False)
    progress = _as_int(payload.get("progress"))
    if progress is not None and not 0 <= progress <= 100:
        progress = None
    created_at = _as_int(payload.get("created_at"))
    seconds = _as_int(payload.get("seconds"))
    model = str(payload.get("model") or "").strip() or None
    size = str(payload.get("size") or "").strip() or None
    prompt = payload.get("prompt")
    prompt_text = str(prompt) if isinstance(prompt, str) else None
    metadata: dict[str, Any] = {
        "object": str(payload.get("object") or "")[:40],
        "status": state,
    }
    if created_at is not None:
        metadata["created_at"] = created_at
    if payload.get("completed_at") is not None:
        completed_at = _as_int(payload.get("completed_at"))
        if completed_at is not None:
            metadata["completed_at"] = completed_at
    if payload.get("expires_at") is not None:
        expires_at = _as_int(payload.get("expires_at"))
        if expires_at is not None:
            metadata["expires_at"] = expires_at
    if payload.get("remixed_from_video_id"):
        metadata["remixed_from_video_id"] = str(payload["remixed_from_video_id"])[:240]
    raw_error = payload.get("error")
    if isinstance(raw_error, dict):
        for key in ("type", "code", "param"):
            value = raw_error.get(key)
            if isinstance(value, (str, int, float, bool)):
                metadata[f"error_{key}"] = str(value)[:160]
    return ProviderVideoJob(
        job_id=job_id,
        state=state,
        progress=progress,
        created_at=created_at,
        model=model,
        seconds=seconds,
        size=size,
        prompt=prompt_text,
        metadata=metadata,
    )


def openai_sora_fixed_cost(request: ProviderVideoRequest) -> tuple[float, dict[str, Any]]:
    if request.model not in _OPENAI_SORA_720_PER_SECOND:
        raise ProviderVideoFailure("provider_pricing_unknown", retryable=False)
    if request.size not in _OPENAI_SORA_720_SIZES or request.seconds not in _OPENAI_SORA_DURATIONS:
        raise ProviderVideoFailure("provider_pricing_unknown", retryable=False)
    per_second = _OPENAI_SORA_720_PER_SECOND[request.model]
    return round(per_second * request.seconds, 9), {
        "pricing_revision": "2026-08-20",
        "pricing_unit": "second",
        "price_per_second_usd": per_second,
        "model": request.model,
        "size": request.size,
        "seconds": request.seconds,
    }


class OpenAIVideoAdapter:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        download_timeout_seconds: float = 180.0,
        max_content_bytes: int = 256 * 1024 * 1024,
        reconcile_window_seconds: int = 180,
        reconcile_limit: int = 20,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.download_timeout_seconds = download_timeout_seconds
        self.max_content_bytes = max_content_bytes
        self.reconcile_window_seconds = reconcile_window_seconds
        self.reconcile_limit = reconcile_limit

    @staticmethod
    def _validate_request(request: ProviderVideoRequest) -> None:
        if request.provider != "openai" or request.model not in _OPENAI_SORA_720_PER_SECOND:
            raise ProviderVideoFailure("provider_operation_unsupported", retryable=False)
        if request.operation not in {"text-to-video", "image-to-video", "logo-to-video", "reference-to-video"}:
            raise ProviderVideoFailure("provider_operation_unsupported", retryable=False)
        if not 1 <= len(request.prompt.strip()) <= 12_000:
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)
        if request.seconds not in _OPENAI_SORA_DURATIONS or request.size not in _OPENAI_SORA_720_SIZES:
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)
        if request.operation == "text-to-video" and request.reference is not None:
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)
        if request.operation != "text-to-video" and request.reference is None:
            raise ProviderVideoFailure("provider_input_missing", retryable=False)
        if request.reference is not None and (
            not request.reference.body
            or len(request.reference.body) > 20 * 1024 * 1024
            or not request.reference.content_type.startswith("image/")
        ):
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        token = credential.strip()
        if not token:
            raise ProviderVideoFailure("provider_unconfigured", retryable=False)
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def submit(
        self,
        request: ProviderVideoRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderVideoJob:
        self._validate_request(request)
        root = base_url.rstrip("/")
        parts: list[tuple[str, Any]] = [
            ("model", (None, request.model)),
            ("prompt", (None, request.prompt)),
            ("seconds", (None, str(request.seconds))),
            ("size", (None, request.size)),
        ]
        if request.reference is not None:
            parts.append(
                (
                    "input_reference",
                    (
                        request.reference.filename,
                        request.reference.body,
                        request.reference.content_type,
                    ),
                )
            )
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{root}/v1/videos",
                    headers=self._headers(credential),
                    files=parts,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderVideoFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response, submission=True)
        try:
            return _parse_job(response.json())
        except (ValueError, ProviderVideoFailure) as exc:
            raise ProviderVideoFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc

    async def retrieve(
        self,
        job_id: str,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderVideoJob:
        safe_id = job_id.strip()
        if not safe_id or len(safe_id) > 240:
            raise ProviderVideoFailure("provider_job_invalid", retryable=False)
        root = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{root}/v1/videos/{safe_id}", headers=self._headers(credential)
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderVideoFailure("provider_transport", retryable=True) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response, submission=False)
        try:
            job = _parse_job(response.json())
        except ValueError as exc:
            raise ProviderVideoFailure("provider_response", retryable=False) from exc
        if job.job_id != safe_id:
            raise ProviderVideoFailure("provider_job_identity", retryable=False)
        return job

    async def reconcile(
        self,
        request: ProviderVideoRequest,
        *,
        submitted_at: datetime,
        credential: str,
        base_url: str,
    ) -> ProviderVideoJob:
        self._validate_request(request)
        if request.reference is not None:
            raise ProviderVideoFailure(
                "provider_submission_ambiguous_reference",
                retryable=False,
                ambiguous_submission=True,
            )
        root = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{root}/v1/videos",
                    headers=self._headers(credential),
                    params={"limit": self.reconcile_limit, "order": "desc"},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderVideoFailure("provider_reconcile_transport", retryable=False) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response, submission=False)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderVideoFailure("provider_reconcile_response", retryable=False) from exc
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ProviderVideoFailure("provider_reconcile_response", retryable=False)
        candidate_ids: list[str] = []
        for item in rows[: self.reconcile_limit]:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("id") or "").strip()
            if job_id and len(job_id) <= 240:
                candidate_ids.append(job_id)
        submitted_epoch = int(submitted_at.astimezone(UTC).timestamp())
        now_epoch = int(datetime.now(UTC).timestamp())
        if now_epoch - submitted_epoch > self.reconcile_window_seconds:
            raise ProviderVideoFailure(
                "provider_submission_reconcile_window_expired",
                retryable=False,
                ambiguous_submission=True,
            )
        lower = submitted_epoch - 5
        upper = min(now_epoch + 5, submitted_epoch + self.reconcile_window_seconds)
        matches: list[ProviderVideoJob] = []
        for job_id in candidate_ids:
            job = await self.retrieve(job_id, credential=credential, base_url=base_url)
            if job.created_at is None or job.created_at < lower or job.created_at > upper:
                continue
            if job.model != request.model or job.seconds != request.seconds or job.size != request.size:
                continue
            if job.prompt != request.prompt:
                continue
            matches.append(job)
        if len(matches) != 1:
            raise ProviderVideoFailure(
                "provider_submission_reconcile_not_unique",
                retryable=False,
                ambiguous_submission=True,
                metadata={"candidate_count": len(matches)},
            )
        return matches[0]

    async def download_content(
        self,
        job_id: str,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderVideoContent:
        safe_id = job_id.strip()
        if not safe_id or len(safe_id) > 240:
            raise ProviderVideoFailure("provider_job_invalid", retryable=False)
        root = base_url.rstrip("/")
        chunks: list[bytes] = []
        total = 0
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.download_timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "GET",
                    f"{root}/v1/videos/{safe_id}/content",
                    headers={"Authorization": self._headers(credential)["Authorization"]},
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _failure_for_response(response, submission=False)
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type != "video/mp4":
                        raise ProviderVideoFailure("provider_content_type", retryable=False)
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_content_bytes:
                            raise ProviderVideoFailure("provider_content_too_large", retryable=False)
                        chunks.append(chunk)
        except ProviderVideoFailure:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderVideoFailure("provider_download_transport", retryable=True) from exc
        body = b"".join(chunks)
        if not body:
            raise ProviderVideoFailure("provider_content_empty", retryable=False)
        return ProviderVideoContent(body=body, content_type="video/mp4")


# --------------------------------------------------------------------------- Gemini Omni
# OpenAI shut down Sora 2 and the Videos API on 2026-09-24; Google discontinued the Veo
# 3.1 previews in the Gemini API on 2026-10-22 and points to Gemini Omni Flash
# (Interactions API). Omni is billed by tokens, so the arm-time estimate is a hard cap
# for the longest clip the model returns (10 s) and the completed cost comes from the
# provider's own usage record. Prices: Gemini API paid tier, 2026-11-19 (O-14 receipt).
_GEMINI_OMNI_PRICING: dict[str, dict[str, float]] = {
    "gemini-omni-1.1-flash": {
        "input_per_million_usd": 1.50,
        "text_output_per_million_usd": 9.00,
        "video_output_per_million_usd": 17.50,
    },
}
_GEMINI_OMNI_VIDEO_TOKENS_PER_SECOND = {"720p": 5792}
_GEMINI_OMNI_SIZES = {"1280x720": ("720p", "16:9"), "720x1280": ("720p", "9:16")}
_GEMINI_OMNI_DURATIONS = frozenset({4, 8})
_GEMINI_OMNI_MAX_SECONDS = 10
_GEMINI_OMNI_THOUGHT_TOKEN_ALLOWANCE = 4_000
_GEMINI_OMNI_INPUT_TOKEN_ALLOWANCE = 4_000
_GEMINI_OMNI_STATES = {
    "in_progress": "in_progress",
    "queued": "queued",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "failed",
    "incomplete": "failed",
}
_GEMINI_HOST = "generativelanguage.googleapis.com"


def video_route_supported(provider: str, model: str) -> bool:
    if provider == "openai":
        return model in _OPENAI_SORA_720_PER_SECOND
    if provider == "gemini":
        return model in _GEMINI_OMNI_PRICING
    return False


def gemini_omni_max_cost(request: ProviderVideoRequest) -> tuple[float, dict[str, Any]]:
    prices = _GEMINI_OMNI_PRICING.get(request.model)
    shape = _GEMINI_OMNI_SIZES.get(request.size)
    if prices is None or shape is None or request.seconds not in _GEMINI_OMNI_DURATIONS:
        raise ProviderVideoFailure("provider_pricing_unknown", retryable=False)
    video_tokens = _GEMINI_OMNI_VIDEO_TOKENS_PER_SECOND[shape[0]] * _GEMINI_OMNI_MAX_SECONDS
    cost = (
        video_tokens * prices["video_output_per_million_usd"]
        + _GEMINI_OMNI_THOUGHT_TOKEN_ALLOWANCE * prices["text_output_per_million_usd"]
        + _GEMINI_OMNI_INPUT_TOKEN_ALLOWANCE * prices["input_per_million_usd"]
    ) / 1_000_000
    return round(cost, 6), {
        "pricing_revision": "2026-11-19",
        "pricing_unit": "token",
        "model": request.model,
        "size": request.size,
        "seconds": request.seconds,
        "cap_seconds": _GEMINI_OMNI_MAX_SECONDS,
        **prices,
    }


def gemini_omni_usage_cost(
    request: ProviderVideoRequest, usage: Any
) -> tuple[float, dict[str, Any]]:
    prices = _GEMINI_OMNI_PRICING.get(request.model)
    if prices is None or not isinstance(usage, dict):
        raise ProviderVideoFailure("provider_usage_missing", retryable=False)
    video_tokens = 0
    for row in usage.get("output_tokens_by_modality") or []:
        if isinstance(row, dict) and str(row.get("modality") or "").lower() == "video":
            video_tokens += max(0, _as_int(row.get("tokens")) or 0)
    total_output = max(0, _as_int(usage.get("total_output_tokens")) or 0)
    thought = max(0, _as_int(usage.get("total_thought_tokens")) or 0)
    text_output = max(0, total_output - video_tokens) + thought
    input_tokens = max(0, _as_int(usage.get("total_input_tokens")) or 0)
    if video_tokens <= 0:
        raise ProviderVideoFailure("provider_usage_missing", retryable=False)
    cost = (
        video_tokens * prices["video_output_per_million_usd"]
        + text_output * prices["text_output_per_million_usd"]
        + input_tokens * prices["input_per_million_usd"]
    ) / 1_000_000
    return round(cost, 6), {
        "pricing_revision": "2026-11-19",
        "pricing_unit": "token",
        "model": request.model,
        "video_output_tokens": video_tokens,
        "text_output_tokens": text_output,
        "input_tokens": input_tokens,
    }


def video_cost_estimate(request: ProviderVideoRequest) -> tuple[float, dict[str, Any]]:
    """Arm-time cost for one provider clip; unknown routes fail before any provider HTTP."""
    if request.provider == "openai":
        return openai_sora_fixed_cost(request)
    if request.provider == "gemini":
        return gemini_omni_max_cost(request)
    raise ProviderVideoFailure("provider_pricing_unknown", retryable=False)


def _parse_gemini_interaction(payload: Any) -> ProviderVideoJob:
    if not isinstance(payload, dict):
        raise ProviderVideoFailure("provider_response", retryable=False)
    job_id = str(payload.get("id") or "").strip()
    raw_state = str(payload.get("status") or "").strip().lower()
    state = _GEMINI_OMNI_STATES.get(raw_state)
    if not job_id or len(job_id) > 240 or state is None:
        raise ProviderVideoFailure("provider_response", retryable=False)
    metadata: dict[str, Any] = {
        "object": str(payload.get("object") or "")[:40],
        "status": raw_state,
        "service_tier": str(payload.get("service_tier") or "")[:40],
    }
    usage = payload.get("usage")
    if isinstance(usage, dict):
        metadata["usage"] = {
            key: usage[key]
            for key in (
                "total_tokens",
                "total_input_tokens",
                "total_output_tokens",
                "total_thought_tokens",
                "output_tokens_by_modality",
            )
            if key in usage
        }
    raw_error = payload.get("error")
    if isinstance(raw_error, dict):
        for key in ("code", "status"):
            value = raw_error.get(key)
            if isinstance(value, (str, int)):
                metadata[f"error_{key}"] = str(value)[:160]
    return ProviderVideoJob(
        job_id=job_id,
        state=state,
        progress=100 if state == "completed" else None,
        created_at=None,
        model=str(payload.get("model") or "").strip() or None,
        seconds=None,
        size=None,
        prompt=None,
        metadata=metadata,
    )


class GeminiOmniVideoAdapter:
    """Gemini Interactions API in background mode: submit returns at once with an id,
    retrieve polls it, and the finished clip is downloaded from the Files URI."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        download_timeout_seconds: float = 180.0,
        max_content_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.download_timeout_seconds = download_timeout_seconds
        self.max_content_bytes = max_content_bytes

    @staticmethod
    def _validate_request(request: ProviderVideoRequest) -> tuple[str, str]:
        if request.provider != "gemini" or request.model not in _GEMINI_OMNI_PRICING:
            raise ProviderVideoFailure("provider_operation_unsupported", retryable=False)
        if request.operation not in {"text-to-video", "image-to-video", "logo-to-video"}:
            raise ProviderVideoFailure("provider_operation_unsupported", retryable=False)
        if not 1 <= len(request.prompt.strip()) <= 12_000:
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)
        shape = _GEMINI_OMNI_SIZES.get(request.size)
        if shape is None or request.seconds not in _GEMINI_OMNI_DURATIONS:
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)
        if request.operation == "text-to-video" and request.reference is not None:
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)
        if request.operation != "text-to-video" and request.reference is None:
            raise ProviderVideoFailure("provider_input_missing", retryable=False)
        if request.reference is not None and (
            not request.reference.body
            or len(request.reference.body) > 20 * 1024 * 1024
            or not request.reference.content_type.startswith("image/")
        ):
            raise ProviderVideoFailure("provider_input_invalid", retryable=False)
        return shape

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        token = credential.strip()
        if not token:
            raise ProviderVideoFailure("provider_unconfigured", retryable=False)
        return {"x-goog-api-key": token, "Accept": "application/json"}

    @staticmethod
    def _root(base_url: str) -> str:
        root = base_url.rstrip("/")
        if httpx.URL(root).host != _GEMINI_HOST:
            raise ProviderVideoFailure("provider_unconfigured", retryable=False)
        return root

    async def submit(
        self, request: ProviderVideoRequest, *, credential: str, base_url: str
    ) -> ProviderVideoJob:
        resolution, aspect_ratio = self._validate_request(request)
        prompt = f"{request.prompt.strip()} Duration: about {request.seconds} seconds."
        content: Any = prompt
        if request.reference is not None:
            content = [
                {
                    "type": "image",
                    "data": base64.b64encode(request.reference.body).decode("ascii"),
                    "mime_type": request.reference.content_type,
                },
                {"type": "text", "text": prompt},
            ]
        body = {
            "model": request.model,
            "input": content,
            "background": True,
            "store": True,
            "response_format": {
                "type": "video",
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "delivery": "uri",
            },
        }
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False
            ) as client:
                response = await client.post(
                    f"{self._root(base_url)}/v1beta/interactions",
                    headers=self._headers(credential),
                    json=body,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderVideoFailure(
                "provider_submission_ambiguous", retryable=False, ambiguous_submission=True
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response, submission=True)
        try:
            return _parse_gemini_interaction(response.json())
        except (ValueError, ProviderVideoFailure) as exc:
            raise ProviderVideoFailure(
                "provider_submission_ambiguous", retryable=False, ambiguous_submission=True
            ) from exc

    async def _get_interaction(self, job_id: str, *, credential: str, base_url: str) -> dict[str, Any]:
        safe_id = job_id.strip()
        if not safe_id or len(safe_id) > 240 or "/" in safe_id:
            raise ProviderVideoFailure("provider_job_invalid", retryable=False)
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False
            ) as client:
                response = await client.get(
                    f"{self._root(base_url)}/v1beta/interactions/{safe_id}",
                    headers=self._headers(credential),
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderVideoFailure("provider_transport", retryable=True) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response, submission=False)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderVideoFailure("provider_response", retryable=False) from exc
        if not isinstance(payload, dict):
            raise ProviderVideoFailure("provider_response", retryable=False)
        return payload

    async def retrieve(self, job_id: str, *, credential: str, base_url: str) -> ProviderVideoJob:
        job = _parse_gemini_interaction(
            await self._get_interaction(job_id, credential=credential, base_url=base_url)
        )
        if job.job_id != job_id.strip():
            raise ProviderVideoFailure("provider_job_identity", retryable=False)
        return job

    async def reconcile(
        self,
        request: ProviderVideoRequest,
        *,
        submitted_at: datetime,
        credential: str,
        base_url: str,
    ) -> ProviderVideoJob:
        # The Interactions API has no listing to match an unacknowledged submission
        # against, so an ambiguous submit ends the clip instead of paying twice.
        raise ProviderVideoFailure(
            "provider_submission_reconcile_unavailable",
            retryable=False,
            ambiguous_submission=True,
        )

    async def download_content(
        self, job_id: str, *, credential: str, base_url: str
    ) -> ProviderVideoContent:
        payload = await self._get_interaction(job_id, credential=credential, base_url=base_url)
        video: dict[str, Any] | None = None
        for step in payload.get("steps") or []:
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            for item in step.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "video":
                    video = item
        if video is None or str(video.get("mime_type") or "").lower() != "video/mp4":
            raise ProviderVideoFailure("provider_content_missing", retryable=False)
        data = video.get("data")
        if isinstance(data, str) and data:
            try:
                body = base64.b64decode(data, validate=True)
            except ValueError as exc:
                raise ProviderVideoFailure("provider_content_invalid", retryable=False) from exc
            if not body:
                raise ProviderVideoFailure("provider_content_empty", retryable=False)
            if len(body) > self.max_content_bytes:
                raise ProviderVideoFailure("provider_content_too_large", retryable=False)
            return ProviderVideoContent(body=body, content_type="video/mp4")
        uri = str(video.get("uri") or "")
        try:
            parsed = httpx.URL(uri)
        except Exception as exc:  # noqa: BLE001 - malformed provider URI
            raise ProviderVideoFailure("provider_content_missing", retryable=False) from exc
        if parsed.scheme != "https" or parsed.host != _GEMINI_HOST:
            raise ProviderVideoFailure("provider_content_missing", retryable=False)
        chunks: list[bytes] = []
        total = 0
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.download_timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream("GET", uri, headers=self._headers(credential)) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _failure_for_response(response, submission=False)
                    content_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    )
                    if content_type != "video/mp4":
                        raise ProviderVideoFailure("provider_content_type", retryable=False)
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_content_bytes:
                            raise ProviderVideoFailure("provider_content_too_large", retryable=False)
                        chunks.append(chunk)
        except ProviderVideoFailure:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderVideoFailure("provider_download_transport", retryable=True) from exc
        body = b"".join(chunks)
        if not body:
            raise ProviderVideoFailure("provider_content_empty", retryable=False)
        return ProviderVideoContent(body=body, content_type="video/mp4")
