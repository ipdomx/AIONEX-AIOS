from __future__ import annotations

import json

import httpx
import pytest

from app.services.audio_dubbing_providers import (
    DubbingTranslationSourceSegment,
    OpenAIDubbingTranslationAdapter,
    ProviderDubbingTranslationFailure,
    ProviderDubbingTranslationRequest,
    estimate_openai_translation_cost,
)


def request(**overrides) -> ProviderDubbingTranslationRequest:
    payload = {
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "source_language": "en",
        "target_language": "es",
        "segments": (
            DubbingTranslationSourceSegment(
                segment_id="segment-001",
                speaker_key="speaker-001",
                start_ms=0,
                end_ms=2_000,
                text="Governed private source one.",
            ),
            DubbingTranslationSourceSegment(
                segment_id="segment-002",
                speaker_key="speaker-002",
                start_ms=2_200,
                end_ms=4_600,
                text="Governed private source two.",
            ),
        ),
        "max_output_tokens": 1_024,
    }
    payload.update(overrides)
    return ProviderDubbingTranslationRequest(**payload)


@pytest.mark.asyncio
async def test_openai_dubbing_translation_uses_responses_strict_schema_and_authoritative_usage() -> (
    None
):
    seen: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        output = json.dumps(
            {
                "translations": [
                    {
                        "segment_id": "segment-001",
                        "translated_text": "Fuente privada gobernada uno.",
                    },
                    {
                        "segment_id": "segment-002",
                        "translated_text": "Fuente privada gobernada dos.",
                    },
                ]
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            headers={"x-request-id": "req-dubbing-translation-1"},
            json={
                "id": "resp-dubbing-translation-1",
                "status": "completed",
                "output_text": output,
                "usage": {
                    "input_tokens": 1_000,
                    "output_tokens": 500,
                    "total_tokens": 1_500,
                },
            },
        )

    adapter = OpenAIDubbingTranslationAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.invoke(
        request(),
        credential="credential",
        base_url="https://api.openai.com",
    )
    assert result.translations == {
        "segment-001": "Fuente privada gobernada uno.",
        "segment-002": "Fuente privada gobernada dos.",
    }
    assert result.request_id == "req-dubbing-translation-1"
    assert result.actual_cost_usd == pytest.approx(0.0008)
    assert result.cost_basis == "provider_usage_official_rates"
    assert result.usage["actual_cost_known"] is True
    assert len(seen) == 1
    assert seen[0].url == httpx.URL("https://api.openai.com/v1/responses")
    assert seen[0].headers["authorization"] == "Bearer credential"
    body = json.loads(seen[0].content)
    assert body["model"] == "gpt-5.6-luna"
    assert body["store"] is False
    assert body["reasoning"] == {"effort": "none"}
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    schema = body["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["translations"]["minItems"] == 2
    assert set(
        schema["properties"]["translations"]["items"]["properties"]["segment_id"][
            "enum"
        ]
    ) == {"segment-001", "segment-002"}
    private_input = json.loads(body["input"])
    assert private_input["source_language"] == "en"
    assert private_input["target_language"] == "es"
    assert [item["speaker_key"] for item in private_input["segments"]] == [
        "speaker-001",
        "speaker-002",
    ]


@pytest.mark.asyncio
async def test_translation_cost_remains_unknown_without_authoritative_usage() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "translations": [
                            {
                                "segment_id": "segment-001",
                                "translated_text": "Uno.",
                            },
                            {
                                "segment_id": "segment-002",
                                "translated_text": "Dos.",
                            },
                        ]
                    }
                ),
            },
        )

    result = await OpenAIDubbingTranslationAdapter(
        transport=httpx.MockTransport(handler)
    ).invoke(
        request(),
        credential="credential",
        base_url="https://api.openai.com",
    )
    assert result.actual_cost_usd is None
    assert result.cost_basis == "official_rate_cap"
    assert result.usage["actual_cost_known"] is False


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
async def test_translation_http_failure_mapping_is_sanitized(
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
                    "param": "input",
                    "message": "raw private content must not persist",
                }
            },
        )

    adapter = OpenAIDubbingTranslationAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderDubbingTranslationFailure) as caught:
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
    assert "message" not in failure.metadata
    assert "raw private content" not in repr(failure.metadata)


@pytest.mark.asyncio
async def test_translation_network_failure_is_ambiguous_and_never_auto_retryable() -> (
    None
):
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("ambiguous private translation outcome")

    adapter = OpenAIDubbingTranslationAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderDubbingTranslationFailure) as caught:
        await adapter.invoke(
            request(),
            credential="credential",
            base_url="https://api.openai.com",
        )
    assert caught.value.code == "provider_submission_ambiguous"
    assert caught.value.ambiguous_submission is True
    assert caught.value.safe_to_resubmit is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_request",
    [
        request(model="invented-translation-model"),
        request(source_language="en", target_language="en"),
        request(segments=()),
        request(
            segments=(
                DubbingTranslationSourceSegment(
                    "segment-001", "real-person-name", 0, 1_000, "Text."
                ),
            )
        ),
        request(
            segments=(
                DubbingTranslationSourceSegment(
                    "segment-001", "speaker-001", 1_000, 2_000, "One."
                ),
                DubbingTranslationSourceSegment(
                    "segment-002", "speaker-002", 1_500, 2_500, "Two."
                ),
            )
        ),
    ],
)
async def test_translation_invalid_requests_fail_before_http(
    bad_request: ProviderDubbingTranslationRequest,
) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    adapter = OpenAIDubbingTranslationAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderDubbingTranslationFailure):
        await adapter.invoke(
            bad_request,
            credential="credential",
            base_url="https://api.openai.com",
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_translation_requires_exact_nonduplicate_segment_coverage() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "translations": [
                            {
                                "segment_id": "segment-001",
                                "translated_text": "Uno.",
                            }
                        ]
                    }
                ),
            },
        )

    with pytest.raises(ProviderDubbingTranslationFailure):
        await OpenAIDubbingTranslationAdapter(
            transport=httpx.MockTransport(handler)
        ).invoke(
            request(),
            credential="credential",
            base_url="https://api.openai.com",
        )


def test_translation_pricing_is_conservative_estimate_only() -> None:
    estimate, evidence = estimate_openai_translation_cost(
        source_characters=1_000,
        segment_count=4,
    )
    assert estimate > 0
    assert evidence["model"] == "gpt-5.6-luna"
    assert evidence["input_usd_per_million_tokens"] == 0.20
    assert evidence["output_usd_per_million_tokens"] == 1.20
    assert evidence["estimate_only"] is True
    assert evidence["authoritative_usage_required_for_actual_cost"] is True
    with pytest.raises(ProviderDubbingTranslationFailure):
        estimate_openai_translation_cost(source_characters=0, segment_count=1)
