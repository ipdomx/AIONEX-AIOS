"""Phase 36E provider-specific image HTTP adapters.

No durable state lives here. The caller owns tenant scope, idempotency, storage,
accounting and retry/fencing authority.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True, slots=True)
class ProviderImageInput:
    body: bytes
    content_type: str
    role: str = "reference"


@dataclass(frozen=True, slots=True)
class ProviderImageRequest:
    provider: str
    model: str
    operation: str
    prompt: str
    output_format: str
    aspect_ratio: str = "1:1"
    image_size: str = "1K"
    quality: str = "auto"
    background: str = "auto"
    references: tuple[ProviderImageInput, ...] = ()
    mask: ProviderImageInput | None = None
    options: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProviderImageResult:
    body: bytes
    content_type: str
    request_id: str | None
    metadata: dict[str, Any]
    usage: dict[str, Any]
    actual_cost_usd: float = 0.0


class ProviderImageFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool, message: str = "Image provider request failed") -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ProviderImageAdapter(Protocol):
    async def invoke(self, request: ProviderImageRequest, *, credential: str, base_url: str) -> ProviderImageResult: ...


def _error_for_status(status: int) -> ProviderImageFailure:
    if status in {401, 403}:
        return ProviderImageFailure("provider_auth", retryable=False)
    if status == 402:
        return ProviderImageFailure("provider_billing", retryable=False)
    if status == 429:
        return ProviderImageFailure("provider_rate_limited", retryable=True)
    if status in {400, 404, 409, 413, 415, 422}:
        return ProviderImageFailure("provider_request", retryable=False)
    if status >= 500:
        return ProviderImageFailure("provider_unavailable", retryable=True)
    return ProviderImageFailure("provider_response", retryable=False)


def _decode_b64(value: str) -> bytes:
    text = value.strip()
    if text.startswith("data:"):
        if "," not in text:
            raise ProviderImageFailure("provider_response", retryable=False)
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ProviderImageFailure("provider_response", retryable=False) from exc


def _content_type(fmt: str) -> str:
    return {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}[fmt]


def _openai_size(request: ProviderImageRequest) -> str:
    explicit = str((request.options or {}).get("size") or "").strip()
    if explicit in {"1024x1024", "1024x1536", "1536x1024", "auto"}:
        return explicit
    if request.aspect_ratio in {"9:16", "4:5", "2:3", "3:4"}:
        return "1024x1536"
    if request.aspect_ratio in {"16:9", "1.91:1", "3:2", "4:3"}:
        return "1536x1024"
    return "1024x1024"


class OpenAIImageAdapter:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, timeout_seconds: float = 180.0) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def invoke(self, request: ProviderImageRequest, *, credential: str, base_url: str) -> ProviderImageResult:
        headers = {"Authorization": f"Bearer {credential}", "Accept": "application/json"}
        root = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False) as client:
                if request.operation == "generate":
                    payload = {
                        "model": request.model,
                        "prompt": request.prompt,
                        "n": 1,
                        "size": _openai_size(request),
                        "quality": request.quality,
                        "background": request.background,
                        "output_format": request.output_format,
                    }
                    response = await client.post(f"{root}/v1/images/generations", headers={**headers, "Content-Type": "application/json"}, json=payload)
                else:
                    if not request.references:
                        raise ProviderImageFailure("provider_input_missing", retryable=False)
                    data: dict[str, str] = {
                        "model": request.model,
                        "prompt": request.prompt,
                        "size": _openai_size(request),
                        "quality": request.quality,
                        "background": "transparent" if request.operation == "background-remove" else request.background,
                        "output_format": request.output_format,
                    }
                    files: list[tuple[str, tuple[str, bytes, str]]] = []
                    for index, item in enumerate(request.references):
                        files.append(("image", (f"image-{index}", item.body, item.content_type)))
                    if request.mask is not None:
                        files.append(("mask", ("mask", request.mask.body, request.mask.content_type)))
                    response = await client.post(f"{root}/v1/images/edits", headers=headers, data=data, files=files)
        except ProviderImageFailure:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderImageFailure("provider_transport", retryable=True) from exc
        if response.status_code >= 400:
            raise _error_for_status(response.status_code)
        try:
            raw_payload = response.json()
            if not isinstance(raw_payload, dict):
                raise ProviderImageFailure("provider_response", retryable=False)
            parsed_payload: dict[str, Any] = raw_payload
            raw_rows = parsed_payload.get("data")
            data_rows = raw_rows if isinstance(raw_rows, list) else []
            first = data_rows[0] if data_rows and isinstance(data_rows[0], dict) else None
            encoded = first.get("b64_json") if first is not None else parsed_payload.get("b64_json")
            if not isinstance(encoded, str):
                raise ProviderImageFailure("provider_response", retryable=False)
            body = _decode_b64(encoded)
            raw_usage = parsed_payload.get("usage")
            usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
            request_id = response.headers.get("x-request-id") or parsed_payload.get("id")
            return ProviderImageResult(
                body=body,
                content_type=_content_type(request.output_format),
                request_id=str(request_id) if request_id else None,
                metadata={"size": parsed_payload.get("size"), "quality": parsed_payload.get("quality"), "background": parsed_payload.get("background")},
                usage=usage,
            )
        except ProviderImageFailure:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderImageFailure("provider_response", retryable=False) from exc


class GeminiImageAdapter:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, timeout_seconds: float = 180.0) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _response_image(payload: dict[str, Any]) -> tuple[str, str] | None:
        top = payload.get("output_image")
        if isinstance(top, dict) and isinstance(top.get("data"), str):
            return str(top["data"]), str(top.get("mime_type") or "image/png")
        for step in payload.get("steps") or []:
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            for block in step.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "image" and isinstance(block.get("data"), str):
                    return str(block["data"]), str(block.get("mime_type") or "image/png")
        return None

    async def invoke(self, request: ProviderImageRequest, *, credential: str, base_url: str) -> ProviderImageResult:
        content: Any = request.prompt
        if request.references:
            content = [
                *[
                    {"type": "image", "mime_type": item.content_type, "data": base64.b64encode(item.body).decode("ascii")}
                    for item in request.references
                ],
                {"type": "text", "text": request.prompt},
            ]
        response_format: dict[str, Any] = {
            "type": "image",
            "mime_type": _content_type(request.output_format),
            "aspect_ratio": request.aspect_ratio,
        }
        if request.image_size in {"512px", "1K", "2K", "4K"}:
            response_format["image_size"] = request.image_size
        payload = {"model": request.model, "input": content, "response_format": response_format}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/v1beta/interactions",
                    headers={"x-goog-api-key": credential, "Content-Type": "application/json", "Accept": "application/json"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderImageFailure("provider_transport", retryable=True) from exc
        if response.status_code >= 400:
            raise _error_for_status(response.status_code)
        try:
            data = response.json()
            image = self._response_image(data)
            if image is None:
                raise ProviderImageFailure("provider_response", retryable=False)
            encoded, mime = image
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            return ProviderImageResult(
                body=_decode_b64(encoded),
                content_type=mime,
                request_id=str(data.get("id")) if data.get("id") else None,
                metadata={"model": data.get("model"), "status": data.get("status")},
                usage=usage,
            )
        except ProviderImageFailure:
            raise
        except (ValueError, TypeError) as exc:
            raise ProviderImageFailure("provider_response", retryable=False) from exc


class FireworksImageAdapter:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 180.0,
        poll_attempts: int = 60,
        poll_seconds: float = 1.0,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.poll_attempts = poll_attempts
        self.poll_seconds = poll_seconds

    async def _json(self, client: httpx.AsyncClient, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise _error_for_status(response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderImageFailure("provider_response", retryable=False) from exc
        if not isinstance(data, dict):
            raise ProviderImageFailure("provider_response", retryable=False)
        return data

    @staticmethod
    def _kontext_result(payload: dict[str, Any]) -> bytes:
        result = payload.get("result")
        if isinstance(result, str):
            if result.startswith("http://") or result.startswith("https://"):
                raise ProviderImageFailure("provider_result_url_unsupported", retryable=False)
            return _decode_b64(result)
        if isinstance(result, dict):
            for key in ("base64", "image", "sample"):
                value = result.get(key)
                if isinstance(value, str) and not value.startswith(("http://", "https://")):
                    return _decode_b64(value)
        raise ProviderImageFailure("provider_response", retryable=False)

    async def invoke(self, request: ProviderImageRequest, *, credential: str, base_url: str) -> ProviderImageResult:
        root = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {credential}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=False) as client:
                if request.model == "flux-1-schnell-fp8":
                    response = await client.post(
                        f"{root}/v1/workflows/accounts/fireworks/models/flux-1-schnell-fp8/text_to_image",
                        headers={**headers, "Accept": _content_type(request.output_format)},
                        json={"prompt": request.prompt, "aspect_ratio": request.aspect_ratio},
                    )
                    if response.status_code >= 400:
                        raise _error_for_status(response.status_code)
                    finish = response.headers.get("finish-reason")
                    if finish and finish.upper() != "SUCCESS":
                        raise ProviderImageFailure("provider_content_filtered", retryable=False)
                    return ProviderImageResult(
                        body=response.content,
                        content_type=response.headers.get("content-type", _content_type(request.output_format)).split(";", 1)[0],
                        request_id=response.headers.get("x-request-id"),
                        metadata={"seed": response.headers.get("seed"), "finish_reason": finish},
                        usage={},
                    )
                input_image = None
                if request.references:
                    input_image = base64.b64encode(request.references[0].body).decode("ascii")
                create_payload: dict[str, Any] = {
                    "prompt": request.prompt,
                    "aspect_ratio": request.aspect_ratio,
                    "output_format": "jpeg" if request.output_format == "jpeg" else "png",
                    "prompt_upsampling": bool((request.options or {}).get("prompt_upsampling", False)),
                    "safety_tolerance": int((request.options or {}).get("safety_tolerance", 2)),
                }
                if input_image is not None:
                    create_payload["input_image"] = input_image
                created = await self._json(client, f"{root}/v1/workflows/accounts/fireworks/models/{request.model}", headers=headers, payload=create_payload)
                request_id = created.get("request_id")
                if not isinstance(request_id, str) or not request_id:
                    raise ProviderImageFailure("provider_response", retryable=False)
                poll_url = f"{root}/v1/workflows/accounts/fireworks/models/{request.model}/get_result"
                for _ in range(self.poll_attempts):
                    result = await self._json(client, poll_url, headers=headers, payload={"id": request_id})
                    status = str(result.get("status") or "")
                    if status == "Ready":
                        return ProviderImageResult(
                            body=self._kontext_result(result),
                            content_type=_content_type(request.output_format),
                            request_id=request_id,
                            metadata={"status": status, "progress": result.get("progress"), "details": result.get("details")},
                            usage={},
                        )
                    if status in {"Request Moderated", "Content Moderated"}:
                        raise ProviderImageFailure("provider_content_filtered", retryable=False)
                    if status in {"Error", "Task not found"}:
                        raise ProviderImageFailure("provider_response", retryable=False)
                    await asyncio.sleep(self.poll_seconds)
                raise ProviderImageFailure("provider_timeout", retryable=True)
        except ProviderImageFailure:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderImageFailure("provider_transport", retryable=True) from exc


def default_image_adapters(*, timeout_seconds: float = 180.0) -> dict[str, ProviderImageAdapter]:
    return {
        "openai": OpenAIImageAdapter(timeout_seconds=timeout_seconds),
        "gemini": GeminiImageAdapter(timeout_seconds=timeout_seconds),
        "fireworks": FireworksImageAdapter(timeout_seconds=timeout_seconds),
    }
