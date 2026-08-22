from __future__ import annotations

import hashlib
import io
import json
import wave

import httpx
import pytest

from app.services.audio_transcript_providers import (
    OpenAITranscriptAdapter,
    ProviderTranscriptFailure,
    ProviderTranscriptRequest,
    estimate_openai_transcription_cost,
)


def wav_bytes(
    *,
    frames: int = 120_000,
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


def request(**overrides) -> ProviderTranscriptRequest:
    audio = wav_bytes()
    payload = {
        "provider": "openai",
        "model": "gpt-4o-mini-transcribe-2025-12-15",
        "audio": audio,
        "media_type": "audio/wav",
        "source_sha256": hashlib.sha256(audio).hexdigest(),
        "duration_ms": 5_000,
        "language": "en-US",
        "response_format": "json",
        "max_source_bytes": 20_971_520,
        "max_duration_seconds": 600,
    }
    payload.update(overrides)
    return ProviderTranscriptRequest(**payload)


@pytest.mark.asyncio
async def test_openai_transcript_adapter_returns_private_text_and_truthful_unknown_cost() -> (
    None
):
    seen: list[httpx.Request] = []

    async def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request)
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "x-request-id": "req-transcript-1",
            },
            json={"text": "  Governed transcript output.  "},
        )

    adapter = OpenAITranscriptAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.invoke(
        request(),
        credential="credential",
        base_url="https://api.openai.com",
    )
    assert result.text == "Governed transcript output."
    assert result.language == "en-US"
    assert result.request_id == "req-transcript-1"
    assert result.actual_cost_usd is None
    assert result.cost_basis == "official_estimated_per_minute"
    assert result.usage["estimated_cost_usd"] == pytest.approx(0.00025)
    assert result.usage["actual_cost_known"] is False
    assert len(seen) == 1
    assert seen[0].url == httpx.URL("https://api.openai.com/v1/audio/transcriptions")
    assert seen[0].headers["authorization"] == "Bearer credential"
    body = seen[0].content
    assert b"gpt-4o-mini-transcribe-2025-12-15" in body
    assert b"governed-source.wav" in body
    assert b"en" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable", "safe", "ambiguous"),
    [
        (401, "provider_auth", False, False, False),
        (402, "provider_billing", False, False, False),
        (422, "provider_request", False, False, False),
        (429, "provider_rate_limited", True, True, False),
        (503, "provider_submission_ambiguous", False, False, True),
    ],
)
async def test_openai_transcript_adapter_maps_http_failures_without_raw_messages(
    status: int,
    code: str,
    retryable: bool,
    safe: bool,
    ambiguous: bool,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "error": {
                    "type": "safe-type",
                    "code": "safe-code",
                    "param": "file",
                    "message": "must-not-persist",
                }
            },
        )

    adapter = OpenAITranscriptAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderTranscriptFailure) as caught:
        await adapter.invoke(
            request(),
            credential="credential",
            base_url="https://api.openai.com",
        )
    failure = caught.value
    assert failure.code == code
    assert failure.retryable is retryable
    assert failure.safe_to_resubmit is safe
    assert failure.ambiguous_submission is ambiguous
    assert failure.metadata["http_status"] == status
    assert failure.metadata["type"] == "safe-type"
    assert "message" not in failure.metadata
    assert "must-not-persist" not in json.dumps(failure.metadata)


@pytest.mark.asyncio
async def test_openai_transcript_network_failure_is_ambiguous_and_never_retried() -> (
    None
):
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("ambiguous")

    adapter = OpenAITranscriptAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderTranscriptFailure) as caught:
        await adapter.invoke(
            request(),
            credential="credential",
            base_url="https://api.openai.com",
        )
    assert caught.value.code == "provider_submission_ambiguous"
    assert caught.value.ambiguous_submission is True
    assert caught.value.retryable is False
    assert caught.value.safe_to_resubmit is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_request",
    [
        request(model="invented-transcribe"),
        request(response_format="verbose_json"),
        request(media_type="application/octet-stream"),
        request(audio=b""),
        request(duration_ms=0),
        request(duration_ms=600_001),
        request(duration_ms=4_000),
        request(audio=b"RIFF" + b"\x00" * 128),
        request(source_sha256="bad"),
    ],
)
async def test_openai_transcript_request_validation_fails_before_http(
    bad_request: ProviderTranscriptRequest,
) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "unexpected"})

    adapter = OpenAITranscriptAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderTranscriptFailure, match="Transcript provider"):
        await adapter.invoke(
            bad_request,
            credential="credential",
            base_url="https://api.openai.com",
        )
    assert calls == 0


def test_openai_transcript_pricing_is_duration_bounded_not_fabricated_usage() -> None:
    estimate, evidence = estimate_openai_transcription_cost(60_000)
    assert estimate == pytest.approx(0.003)
    assert evidence == {
        "pricing_revision": "2026-08-22",
        "pricing_source": "https://developers.openai.com/api/docs/pricing",
        "pricing_unit": "audio_minute_estimate",
        "estimated_price_per_minute_usd": 0.003,
        "audio_input_usd_per_million_tokens": 1.25,
        "text_output_usd_per_million_tokens": 5.0,
        "duration_ms": 60_000,
        "billing_note": (
            "The provider publishes an estimated per-minute cost, while this "
            "endpoint does not return authoritative per-request usage."
        ),
    }
    with pytest.raises(ProviderTranscriptFailure, match="Transcript provider"):
        estimate_openai_transcription_cost(0)
