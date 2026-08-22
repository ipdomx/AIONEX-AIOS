from __future__ import annotations

import io
import json
import wave

import httpx
import pytest

from app.services.audio_speech_providers import (
    OpenAIStockSpeechAdapter,
    ProviderSpeechFailure,
    ProviderSpeechRequest,
    inspect_pcm_wav,
)


def wav_bytes(
    *,
    frames: int = 24_000,
    sample_rate: int = 24_000,
    channels: int = 1,
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frames * channels)
    return output.getvalue()


def request(**overrides) -> ProviderSpeechRequest:
    payload = {
        "provider": "openai",
        "model": "gpt-4o-mini-tts-2025-12-15",
        "operation": "synthesize-speech",
        "input_text": "Welcome to AIONEX.",
        "voice": "marin",
        "instructions": "Speak clearly and warmly.",
        "response_format": "wav",
        "speed": 1.0,
        "max_duration_seconds": 20.0,
    }
    payload.update(overrides)
    return ProviderSpeechRequest(**payload)


@pytest.mark.asyncio
async def test_openai_stock_speech_uses_exact_endpoint_payload_and_returns_bounded_wav() -> None:
    observed: dict[str, object] = {}
    body = wav_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        observed["method"] = req.method
        observed["path"] = req.url.path
        observed["authorization"] = req.headers.get("authorization")
        payload = json.loads(req.content)
        observed["payload"] = payload
        return httpx.Response(
            200,
            headers={"x-request-id": "req-stock-tts"},
            content=body,
        )

    adapter = OpenAIStockSpeechAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.invoke(
        request(),
        credential="secret-token",
        base_url="https://api.openai.com",
    )
    assert observed["method"] == "POST"
    assert observed["path"] == "/v1/audio/speech"
    assert observed["authorization"] == "Bearer secret-token"
    payload = observed["payload"]
    assert isinstance(payload, dict)
    assert payload == {
        "model": "gpt-4o-mini-tts-2025-12-15",
        "input": "Welcome to AIONEX.",
        "voice": "marin",
        "response_format": "wav",
        "speed": 1.0,
        "stream_format": "audio",
        "instructions": "Speak clearly and warmly.",
    }
    assert result.body == body
    assert result.content_type == "audio/wav"
    assert result.request_id == "req-stock-tts"
    assert result.metadata["duration_seconds"] == pytest.approx(1.0)
    assert result.metadata["sample_rate_hz"] == 24_000
    assert result.metadata["channels"] == 1
    assert result.actual_cost_usd is None
    assert result.cost_basis == "official_rate_cap"
    assert result.usage["provider_usage_reported"] is False
    assert result.usage["billing_exact"] is False
    rendered = repr({"metadata": result.metadata, "usage": result.usage})
    assert "Welcome to AIONEX" not in rendered
    assert "secret-token" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_request",
    [
        request(model="gpt-4o-mini-tts"),
        request(voice="custom-voice-id"),
        request(operation="voice-clone"),
        request(response_format="mp3"),
        request(input_text=""),
        request(speed=5.0),
    ],
)
async def test_stock_speech_rejects_unpinned_custom_or_invalid_requests_before_http(
    bad_request: ProviderSpeechRequest,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=wav_bytes())

    adapter = OpenAIStockSpeechAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderSpeechFailure):
        await adapter.invoke(
            bad_request,
            credential="secret-token",
            base_url="https://api.openai.com",
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_rate_limit_is_definitive_and_bounded_resubmit_safe() -> None:
    adapter = OpenAIStockSpeechAdapter(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                429,
                json={"error": {"type": "rate_limit_error", "code": "rate_limit"}},
            )
        )
    )
    with pytest.raises(ProviderSpeechFailure) as caught:
        await adapter.invoke(
            request(),
            credential="secret-token",
            base_url="https://api.openai.com",
        )
    assert caught.value.code == "provider_rate_limited"
    assert caught.value.retryable is True
    assert caught.value.safe_to_resubmit is True
    assert caught.value.ambiguous_submission is False
    assert caught.value.metadata == {
        "http_status": 429,
        "type": "rate_limit_error",
        "code": "rate_limit",
    }


@pytest.mark.asyncio
async def test_server_error_and_transport_failure_are_ambiguous_not_auto_retryable() -> None:
    server = OpenAIStockSpeechAdapter(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, json={"error": {}}))
    )
    with pytest.raises(ProviderSpeechFailure) as server_error:
        await server.invoke(
            request(),
            credential="secret-token",
            base_url="https://api.openai.com",
        )
    assert server_error.value.code == "provider_submission_ambiguous"
    assert server_error.value.ambiguous_submission is True
    assert server_error.value.safe_to_resubmit is False

    def network_error(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset", request=req)

    transport = OpenAIStockSpeechAdapter(transport=httpx.MockTransport(network_error))
    with pytest.raises(ProviderSpeechFailure) as caught:
        await transport.invoke(
            request(),
            credential="secret-token",
            base_url="https://api.openai.com",
        )
    assert caught.value.code == "provider_submission_ambiguous"
    assert caught.value.ambiguous_submission is True
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not-a-wave",
        b"RIFF" + b"\x00" * 40,
    ],
)
def test_wav_inspector_rejects_invalid_provider_audio(body: bytes) -> None:
    with pytest.raises(ProviderSpeechFailure):
        inspect_pcm_wav(body, max_duration_seconds=20.0)


def test_wav_inspector_enforces_duration_cap() -> None:
    with pytest.raises(ProviderSpeechFailure, match="failed"):
        inspect_pcm_wav(wav_bytes(frames=48_000), max_duration_seconds=1.0)
