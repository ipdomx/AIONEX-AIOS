from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.services.audio_music_providers import (
    GeminiLyriaMusicAdapter,
    ProviderMusicFailure,
    ProviderMusicRequest,
    inspect_mp3_bytes,
)


MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15" + b"governed-audio" * 128


def request(**overrides) -> ProviderMusicRequest:
    payload = {
        "provider": "gemini",
        "model": "lyria-3-clip-preview",
        "operation": "generate-music",
        "tier": "draft",
        "prompt": "Bright original instrumental music with piano and a clean ending.",
        "instrumental_only": True,
        "lyrics": "",
        "output_format": "mp3",
    }
    payload.update(overrides)
    return ProviderMusicRequest(**payload)


@pytest.mark.asyncio
async def test_lyria_clip_uses_generate_content_and_returns_fixed_cost_mp3() -> None:
    observed: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        observed["method"] = req.method
        observed["path"] = req.url.path
        observed["api_key"] = req.headers.get("x-goog-api-key")
        payload = json.loads(req.content)
        observed["payload"] = payload
        return httpx.Response(
            200,
            headers={"x-goog-request-id": "req-lyria-clip"},
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "[Instrumental structure]"},
                                {
                                    "inlineData": {
                                        "mimeType": "audio/mpeg",
                                        "data": base64.b64encode(MP3_BYTES).decode(),
                                    }
                                },
                            ]
                        }
                    }
                ],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 8},
            },
        )

    adapter = GeminiLyriaMusicAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.invoke(
        request(),
        credential="gemini-secret",
        base_url="https://generativelanguage.googleapis.com",
    )
    assert observed["method"] == "POST"
    assert observed["path"] == "/v1beta/models/lyria-3-clip-preview:generateContent"
    assert observed["api_key"] == "gemini-secret"
    payload = observed["payload"]
    assert isinstance(payload, dict)
    prompt = payload["contents"][0]["parts"][0]["text"]
    assert "Instrumental only, no vocals." in prompt
    assert result.body == MP3_BYTES
    assert result.content_type == "audio/mpeg"
    assert result.request_id == "req-lyria-clip"
    assert result.actual_cost_usd == 0.04
    assert result.cost_basis == "official_fixed_request"
    assert result.metadata["model"] == "lyria-3-clip-preview"
    assert result.metadata["tier"] == "draft"
    assert result.metadata["provider_sample_rate_hz"] == 44_100
    assert result.metadata["provider_channels"] == 2
    assert result.metadata["nominal_duration_seconds"] == 30
    assert result.metadata["returned_text_sha256"]
    assert result.metadata["raw_returned_text_returned"] is False
    assert result.metadata["synthid_watermark_expected"] is True
    assert result.usage["official_fixed_request_usd"] == 0.04
    rendered = repr({"metadata": result.metadata, "usage": result.usage})
    assert "gemini-secret" not in rendered
    assert "Bright original" not in rendered


@pytest.mark.asyncio
async def test_lyria_pro_supports_governed_custom_lyrics_at_eight_cents() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/mp3",
                                        "data": base64.b64encode(MP3_BYTES).decode(),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    adapter = GeminiLyriaMusicAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.invoke(
        request(
            model="lyria-3-pro-preview",
            tier="final",
            instrumental_only=False,
            lyrics="[Verse]\nThese are original user-owned lyrics.",
        ),
        credential="gemini-secret",
        base_url="https://generativelanguage.googleapis.com",
    )
    assert result.actual_cost_usd == 0.08
    assert result.metadata["tier"] == "final"
    assert result.metadata["nominal_duration_seconds"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_request",
    [
        request(model="lyria-3-pro-preview"),
        request(tier="final"),
        request(operation="voice-clone"),
        request(output_format="wav"),
        request(prompt="short"),
        request(lyrics="not allowed for instrumental"),
        request(instrumental_only=False, lyrics=""),
    ],
)
async def test_music_route_rejects_invalid_requests_before_http(
    bad_request: ProviderMusicRequest,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    adapter = GeminiLyriaMusicAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderMusicFailure):
        await adapter.invoke(
            bad_request,
            credential="gemini-secret",
            base_url="https://generativelanguage.googleapis.com",
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_rate_limit_and_server_error_never_auto_retry() -> None:
    rate = GeminiLyriaMusicAdapter(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                429,
                json={
                    "error": {
                        "code": 429,
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [{"reason": "RATE_LIMIT_EXCEEDED"}],
                    }
                },
            )
        )
    )
    with pytest.raises(ProviderMusicFailure) as rate_error:
        await rate.invoke(
            request(),
            credential="gemini-secret",
            base_url="https://generativelanguage.googleapis.com",
        )
    assert rate_error.value.code == "provider_rate_limited"
    assert rate_error.value.retryable is False
    assert rate_error.value.safe_to_resubmit is False
    assert rate_error.value.ambiguous_submission is False

    server = GeminiLyriaMusicAdapter(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, json={"error": {}}))
    )
    with pytest.raises(ProviderMusicFailure) as server_error:
        await server.invoke(
            request(),
            credential="gemini-secret",
            base_url="https://generativelanguage.googleapis.com",
        )
    assert server_error.value.code == "provider_submission_ambiguous"
    assert server_error.value.ambiguous_submission is True
    assert server_error.value.safe_to_resubmit is False


def test_mp3_inspector_rejects_invalid_or_oversized_audio() -> None:
    assert inspect_mp3_bytes(MP3_BYTES, max_content_bytes=len(MP3_BYTES))["codec"] == "mp3"
    with pytest.raises(ProviderMusicFailure):
        inspect_mp3_bytes(b"not-mp3", max_content_bytes=100)
    with pytest.raises(ProviderMusicFailure):
        inspect_mp3_bytes(MP3_BYTES, max_content_bytes=len(MP3_BYTES) - 1)
