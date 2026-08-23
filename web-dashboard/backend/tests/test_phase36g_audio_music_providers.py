from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.services.audio_music_providers import (
    GeminiLyriaMusicAdapter,
    ProviderMusicFailure,
    ProviderMusicRequest,
    ReplicateLyriaMusicAdapter,
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


def replicate_request(**overrides) -> ProviderMusicRequest:
    payload = {
        "provider": "replicate",
        "model": "google/lyria-3",
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


@pytest.mark.asyncio
async def test_replicate_clip_submits_once_polls_same_prediction_and_downloads_mp3() -> None:
    calls: list[dict[str, object]] = []
    poll_number = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal poll_number
        calls.append(
            {
                "method": req.method,
                "host": req.url.host,
                "path": req.url.path,
                "authorization": req.headers.get("authorization"),
                "prefer": req.headers.get("prefer"),
                "user_agent": req.headers.get("user-agent"),
            }
        )
        if req.method == "POST":
            payload = json.loads(req.content)
            assert payload["input"]["prompt"].endswith("Instrumental only, no vocals.")
            return httpx.Response(201, json={"id": "pred-1", "status": "starting"})
        if req.url.host == "api.replicate.com":
            assert req.url.path == "/v1/predictions/pred-1"
            poll_number += 1
            if poll_number == 1:
                return httpx.Response(200, json={"id": "pred-1", "status": "processing"})
            return httpx.Response(
                200,
                json={
                    "id": "pred-1",
                    "status": "succeeded",
                    "output": "https://replicate.delivery/music/output.mp3",
                },
            )
        assert req.url.host == "replicate.delivery"
        assert req.headers.get("authorization") is None
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=MP3_BYTES)

    adapter = ReplicateLyriaMusicAdapter(
        transport=httpx.MockTransport(handler),
        poll_seconds=0,
        max_polls=4,
    )
    result = await adapter.invoke(
        replicate_request(),
        credential="replicate-secret-token",
        base_url="https://api.replicate.com",
    )
    assert sum(1 for item in calls if item["method"] == "POST") == 1
    assert sum(1 for item in calls if item["path"] == "/v1/predictions/pred-1") == 2
    assert calls[0]["prefer"] == "wait=60"
    assert calls[0]["user_agent"] == "AIONEX-AIOS/36G"
    assert result.body == MP3_BYTES
    assert result.request_id == "pred-1"
    assert result.actual_cost_usd == 0.04
    assert result.metadata["provider"] == "replicate"
    assert result.metadata["model"] == "google/lyria-3"
    assert result.metadata["provider_sample_rate_hz"] == 48_000
    assert result.metadata["poll_count"] == 2
    assert result.metadata["raw_output_url_returned"] is False
    assert "replicate-secret-token" not in repr(result.metadata)
    assert "https://replicate.delivery" not in repr(result.metadata)


@pytest.mark.asyncio
async def test_replicate_pro_uses_official_model_and_fixed_eight_cent_cost() -> None:
    observed: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            observed["path"] = req.url.path
            observed["prompt"] = json.loads(req.content)["input"]["prompt"]
            return httpx.Response(
                201,
                json={
                    "id": "pred-pro",
                    "status": "succeeded",
                    "output": "https://replicate.delivery/music/pro.mp3",
                },
            )
        return httpx.Response(200, content=MP3_BYTES)

    adapter = ReplicateLyriaMusicAdapter(
        transport=httpx.MockTransport(handler),
        poll_seconds=0,
    )
    result = await adapter.invoke(
        replicate_request(
            model="google/lyria-3-pro",
            tier="final",
            instrumental_only=False,
            lyrics="[Verse]\nOriginal governed words.",
        ),
        credential="replicate-secret-token",
        base_url="https://api.replicate.com",
    )
    assert observed["path"] == "/v1/models/google/lyria-3-pro/predictions"
    assert "Original governed words" in str(observed["prompt"])
    assert result.actual_cost_usd == 0.08
    assert result.metadata["tier"] == "final"
    assert result.metadata["nominal_duration_seconds"] is None


@pytest.mark.asyncio
async def test_replicate_rejects_untrusted_output_url_without_download() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201,
            json={
                "id": "pred-bad-url",
                "status": "succeeded",
                "output": "https://example.invalid/audio.mp3",
            },
        )

    adapter = ReplicateLyriaMusicAdapter(
        transport=httpx.MockTransport(handler),
        poll_seconds=0,
    )
    with pytest.raises(ProviderMusicFailure, match="Music provider request failed") as error:
        await adapter.invoke(
            replicate_request(),
            credential="replicate-secret-token",
            base_url="https://api.replicate.com",
        )
    assert error.value.code == "provider_output_url"
    assert calls == 1


@pytest.mark.asyncio
async def test_replicate_rate_limit_and_post_submit_network_failure_never_resubmit() -> None:
    submit_calls = 0

    def rate_handler(_: httpx.Request) -> httpx.Response:
        nonlocal submit_calls
        submit_calls += 1
        return httpx.Response(429, json={"detail": "rate limited"})

    rate = ReplicateLyriaMusicAdapter(
        transport=httpx.MockTransport(rate_handler),
        poll_seconds=0,
    )
    with pytest.raises(ProviderMusicFailure) as rate_error:
        await rate.invoke(
            replicate_request(),
            credential="replicate-secret-token",
            base_url="https://api.replicate.com",
        )
    assert submit_calls == 1
    assert rate_error.value.code == "provider_rate_limited"
    assert rate_error.value.ambiguous_submission is False
    assert rate_error.value.safe_to_resubmit is False

    calls: list[str] = []

    def ambiguous_handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.method)
        if req.method == "POST":
            return httpx.Response(201, json={"id": "pred-amb", "status": "processing"})
        raise httpx.ReadTimeout("poll failed", request=req)

    ambiguous = ReplicateLyriaMusicAdapter(
        transport=httpx.MockTransport(ambiguous_handler),
        poll_seconds=0,
    )
    with pytest.raises(ProviderMusicFailure) as ambiguous_error:
        await ambiguous.invoke(
            replicate_request(),
            credential="replicate-secret-token",
            base_url="https://api.replicate.com",
        )
    assert calls.count("POST") == 1
    assert ambiguous_error.value.code == "provider_poll_network"
    assert ambiguous_error.value.retryable is True
    assert ambiguous_error.value.ambiguous_submission is False
    assert ambiguous_error.value.safe_to_resubmit is False
