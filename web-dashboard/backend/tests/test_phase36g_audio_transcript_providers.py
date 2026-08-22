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
        "operation": "transcribe",
        "response_format": "json",
        "chunking_strategy": None,
        "max_source_bytes": 20_971_520,
        "max_duration_seconds": 600,
    }
    payload.update(overrides)
    return ProviderTranscriptRequest(**payload)


def diarize_request(**overrides) -> ProviderTranscriptRequest:
    payload = {
        "operation": "diarize",
        "model": "gpt-4o-transcribe-diarize",
        "response_format": "diarized_json",
        "chunking_strategy": "auto",
        "prompt": None,
    }
    payload.update(overrides)
    return request(**payload)


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
            json={
                "text": "  Governed transcript output.  ",
                "usage": {
                    "type": "tokens",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "input_token_details": {
                        "audio_tokens": 100,
                        "text_tokens": 0,
                    },
                },
            },
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
    assert result.segments == ()
    assert result.actual_cost_usd is None
    assert result.cost_basis == "official_estimated_per_minute"
    assert result.usage["estimated_cost_usd"] == pytest.approx(0.00025)
    assert result.usage["actual_cost_known"] is False
    assert result.usage["provider_usage_type"] == "tokens"
    assert result.usage["audio_input_tokens"] == 100
    assert result.usage["observed_cost_estimate_usd"] == pytest.approx(0.000225)
    assert len(seen) == 1
    assert seen[0].url == httpx.URL("https://api.openai.com/v1/audio/transcriptions")
    assert seen[0].headers["authorization"] == "Bearer credential"
    body = seen[0].content
    assert b"gpt-4o-mini-transcribe-2025-12-15" in body
    assert b"governed-source.wav" in body
    assert b"en" in body
    assert b"chunking_strategy" not in body


@pytest.mark.asyncio
async def test_openai_diarization_uses_exact_route_and_keeps_raw_labels_transient() -> None:
    seen: list[httpx.Request] = []

    async def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-diarize-1"},
            json={
                "task": "transcribe",
                "duration": 5.0,
                "text": "First speaker. Second speaker. First again.",
                "segments": [
                    {
                        "type": "transcript.text.segment",
                        "id": "seg_001",
                        "start": 0.0,
                        "end": 1.5,
                        "text": "First speaker.",
                        "speaker": "provider-speaker-alpha",
                    },
                    {
                        "type": "transcript.text.segment",
                        "id": "seg_002",
                        "start": 1.5,
                        "end": 3.2,
                        "text": "Second speaker.",
                        "speaker": "provider-speaker-beta",
                    },
                    {
                        "type": "transcript.text.segment",
                        "id": "seg_003",
                        "start": 3.2,
                        "end": 5.0,
                        "text": "First again.",
                        "speaker": "provider-speaker-alpha",
                    },
                ],
                "usage": {"type": "duration", "seconds": 5.0},
            },
        )

    adapter = OpenAITranscriptAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.invoke(
        diarize_request(),
        credential="credential",
        base_url="https://api.openai.com",
    )
    assert result.request_id == "req-diarize-1"
    assert result.text == "First speaker. Second speaker. First again."
    assert [item.provider_segment_id for item in result.segments] == [
        "seg_001",
        "seg_002",
        "seg_003",
    ]
    assert [item.speaker_label for item in result.segments] == [
        "provider-speaker-alpha",
        "provider-speaker-beta",
        "provider-speaker-alpha",
    ]
    assert result.metadata["operation"] == "diarize"
    assert result.metadata["response_format"] == "diarized_json"
    assert result.metadata["chunking_strategy"] == "auto"
    assert result.metadata["segment_count"] == 3
    assert result.metadata["speaker_count"] == 2
    assert result.metadata["raw_speaker_labels_returned"] is False
    assert "provider-speaker-alpha" not in repr(result.metadata)
    assert "provider-speaker-beta" not in repr(result.usage)
    assert result.usage["provider_usage_type"] == "duration"
    assert result.usage["provider_usage_seconds"] == pytest.approx(5.0)
    assert result.usage["observed_cost_estimate_usd"] == pytest.approx(0.0005)
    assert result.actual_cost_usd is None
    assert len(seen) == 1
    body = seen[0].content
    assert b"gpt-4o-transcribe-diarize" in body
    assert b"diarized_json" in body
    assert b"chunking_strategy" in body and b"auto" in body
    assert b"prompt" not in body


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
        diarize_request(model="gpt-4o-mini-transcribe-2025-12-15"),
        diarize_request(response_format="json"),
        diarize_request(chunking_strategy=None),
        diarize_request(prompt="unsupported diarization prompt"),
        request(operation="diarize"),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "segments",
    [
        [
            {
                "type": "transcript.text.segment",
                "id": "seg_001",
                "start": 0.0,
                "end": 2.5,
                "text": "Only one speaker.",
                "speaker": "A",
            },
            {
                "type": "transcript.text.segment",
                "id": "seg_002",
                "start": 2.5,
                "end": 5.0,
                "text": "Still one speaker.",
                "speaker": "A",
            },
        ],
        [
            {
                "type": "transcript.text.segment",
                "id": "seg_001",
                "start": 0.0,
                "end": 3.0,
                "text": "Overlap one.",
                "speaker": "A",
            },
            {
                "type": "transcript.text.segment",
                "id": "seg_002",
                "start": 2.0,
                "end": 4.0,
                "text": "Overlap two.",
                "speaker": "B",
            },
        ],
        [
            {
                "type": "transcript.text.segment",
                "id": "seg_001",
                "start": 0.0,
                "end": 2.5,
                "text": "First.",
                "speaker": "A",
            },
            {
                "type": "transcript.text.segment",
                "id": "seg_002",
                "start": 2.5,
                "end": 5.5,
                "text": "Past source duration.",
                "speaker": "B",
            },
        ],
    ],
)
async def test_diarization_rejects_unproven_or_invalid_segments(segments: list[dict]) -> None:
    adapter = OpenAITranscriptAdapter(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "task": "transcribe",
                    "duration": 5.0,
                    "text": "unsafe",
                    "segments": segments,
                    "usage": {"type": "duration", "seconds": 5.0},
                },
            )
        )
    )
    with pytest.raises(ProviderTranscriptFailure):
        await adapter.invoke(
            diarize_request(),
            credential="credential",
            base_url="https://api.openai.com",
        )


def test_openai_transcript_pricing_is_duration_bounded_not_fabricated_usage() -> None:
    estimate, evidence = estimate_openai_transcription_cost(60_000)
    assert estimate == pytest.approx(0.003)
    assert evidence["pricing_revision"] == "2026-08-23"
    assert evidence["pricing_basis"] == "official_published_per_minute_estimate"
    assert evidence["estimated_price_per_minute_usd"] == 0.003
    assert evidence["input_usd_per_million_tokens"] == 1.25
    assert evidence["output_usd_per_million_tokens"] == 5.0
    diarize_estimate, diarize_evidence = estimate_openai_transcription_cost(
        60_000,
        model="gpt-4o-transcribe-diarize",
    )
    assert diarize_estimate == pytest.approx(0.006)
    assert (
        diarize_evidence["pricing_basis"]
        == "official_model_rate_equivalent_estimate"
    )
    assert diarize_evidence["input_usd_per_million_tokens"] == 2.5
    assert diarize_evidence["output_usd_per_million_tokens"] == 10.0
    assert "not a fabricated bill" in diarize_evidence["billing_note"]
    with pytest.raises(ProviderTranscriptFailure, match="Transcript provider"):
        estimate_openai_transcription_cost(0)
    with pytest.raises(ProviderTranscriptFailure, match="Transcript provider"):
        estimate_openai_transcription_cost(60_000, model="invented")
