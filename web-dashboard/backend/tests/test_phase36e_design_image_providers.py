from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.services.design_image_providers import (
    FireworksImageAdapter,
    GeminiImageAdapter,
    OpenAIImageAdapter,
    ProviderImageFailure,
    ProviderImageInput,
    ProviderImageRequest,
)


def req(provider: str, model: str, operation: str = "generate", *, refs=()) -> ProviderImageRequest:
    return ProviderImageRequest(
        provider=provider,
        model=model,
        operation=operation,
        prompt="Governed design prompt",
        output_format="png",
        aspect_ratio="1:1",
        references=tuple(refs),
    )


@pytest.mark.asyncio
async def test_openai_generate_uses_images_generation_and_b64_result() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/generations"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-image-2"
        assert payload["output_format"] == "png"
        return httpx.Response(
            200,
            headers={"x-request-id": "req-openai"},
            json={"data": [{"b64_json": base64.b64encode(b"openai-png").decode()}], "usage": {"total_tokens": 9}},
        )

    result = await OpenAIImageAdapter(transport=httpx.MockTransport(handler)).invoke(
        req("openai", "gpt-image-2"), credential="test", base_url="https://api.openai.com"
    )
    assert result.body == b"openai-png"
    assert result.request_id == "req-openai"
    assert result.usage["total_tokens"] == 9


@pytest.mark.asyncio
async def test_openai_edit_is_multipart_and_requires_reference() -> None:
    reference = ProviderImageInput(b"ref", "image/png")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/edits"
        assert "multipart/form-data" in request.headers["content-type"]
        body = await request.aread()
        assert b"gpt-image-2" in body
        assert b"Governed design prompt" in body
        assert b"ref" in body
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"edited").decode()}]})

    result = await OpenAIImageAdapter(transport=httpx.MockTransport(handler)).invoke(
        req("openai", "gpt-image-2", "edit", refs=(reference,)),
        credential="test",
        base_url="https://api.openai.com",
    )
    assert result.body == b"edited"


@pytest.mark.asyncio
async def test_gemini_uses_interactions_and_inline_reference() -> None:
    reference = ProviderImageInput(b"gem-ref", "image/png")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/interactions"
        assert request.headers["x-goog-api-key"] == "test"
        payload = json.loads(request.content)
        assert payload["model"] == "gemini-3.1-flash-image"
        assert payload["input"][0]["type"] == "image"
        assert base64.b64decode(payload["input"][0]["data"]) == b"gem-ref"
        return httpx.Response(
            200,
            json={"id": "gem-1", "output_image": {"data": base64.b64encode(b"gemini").decode(), "mime_type": "image/png"}},
        )

    result = await GeminiImageAdapter(transport=httpx.MockTransport(handler)).invoke(
        req("gemini", "gemini-3.1-flash-image", "edit", refs=(reference,)),
        credential="test",
        base_url="https://generativelanguage.googleapis.com",
    )
    assert result.body == b"gemini"
    assert result.request_id == "gem-1"


@pytest.mark.asyncio
async def test_fireworks_schnell_returns_binary_image() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/flux-1-schnell-fp8/text_to_image")
        return httpx.Response(200, headers={"content-type": "image/png", "finish-reason": "SUCCESS", "seed": "42"}, content=b"fw")

    result = await FireworksImageAdapter(transport=httpx.MockTransport(handler)).invoke(
        req("fireworks", "flux-1-schnell-fp8"), credential="test", base_url="https://api.fireworks.ai/inference"
    )
    assert result.body == b"fw"
    assert result.metadata["seed"] == "42"


@pytest.mark.asyncio
async def test_fireworks_kontext_async_poll_is_bounded() -> None:
    polls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.url.path.endswith("/flux-kontext-pro"):
            return httpx.Response(200, json={"request_id": "fw-job"})
        assert request.url.path.endswith("/flux-kontext-pro/get_result")
        polls += 1
        if polls == 1:
            return httpx.Response(200, json={"id": "fw-job", "status": "Pending", "progress": 10})
        encoded = "data:image/png;base64," + base64.b64encode(b"kontext").decode()
        return httpx.Response(200, json={"id": "fw-job", "status": "Ready", "result": {"base64": encoded}, "progress": 100})

    result = await FireworksImageAdapter(
        transport=httpx.MockTransport(handler), poll_attempts=3, poll_seconds=0
    ).invoke(
        req("fireworks", "flux-kontext-pro"), credential="test", base_url="https://api.fireworks.ai/inference"
    )
    assert result.body == b"kontext"
    assert result.request_id == "fw-job"
    assert polls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(401, "provider_auth", False), (402, "provider_billing", False), (429, "provider_rate_limited", True), (503, "provider_unavailable", True)],
)
async def test_http_errors_are_mapped_without_response_body_leak(status: int, code: str, retryable: bool) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="secret provider response must not leak")

    with pytest.raises(ProviderImageFailure) as caught:
        await OpenAIImageAdapter(transport=httpx.MockTransport(handler)).invoke(
            req("openai", "gpt-image-2"), credential="test", base_url="https://api.openai.com"
        )
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "secret provider response" not in str(caught.value)
