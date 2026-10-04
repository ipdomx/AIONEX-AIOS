from __future__ import annotations

import asyncio

import httpx
import pytest

from aios.audio_factory import STABILITY_SFX_SOURCE_CAPABILITY
from app.services.audio_music_providers import (
    ProviderMusicFailure,
    ProviderMusicRequest,
    StabilityStableAudioMusicAdapter,
)
from app.services.audio_music_runtime import (
    AudioMusicExecutionError,
    AudioMusicExecutionSpec,
    _validate_spec,
)
from app.services.audio_music_worker import _sfx_duration_from_request_options


MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15" + b"governed-sfx" * 128
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _sfx_request(**overrides) -> ProviderMusicRequest:
    payload = {
        "provider": "stability",
        "model": "stable-audio-2.5",
        "operation": "generate-sfx",
        "tier": "draft",
        "prompt": "Short clean glass chime with a fast natural decay.",
        "instrumental_only": False,
        "lyrics": "",
        "output_format": "mp3",
        "duration_seconds": 7.5,
    }
    payload.update(overrides)
    return ProviderMusicRequest(**payload)


def _sfx_spec(**overrides) -> AudioMusicExecutionSpec:
    payload = {
        "organization_id": "org-fr15",
        "requested_by_id": "user-fr15",
        "graph_id": "graph-fr15",
        "target_node_id": "node-fr15",
        "plan_checksum": HASH_A,
        "runtime_evidence_sha256": HASH_B,
        "pricing_evidence_sha256": HASH_C,
        "prompt": "Short clean glass chime with a fast natural decay.",
        "lyrics": "",
        "instrumental_only": False,
        "rights_basis": "sfx",
        "rights_evidence_sha256": None,
        "tier": "draft",
        "provider": "stability",
        "model": "stable-audio-2.5",
        "idempotency_key": "fr15-sfx-idempotency-001",
        "request_options": {"duration_seconds": 7.5},
        "final_generation_approved": False,
        "final_approval_evidence_sha256": None,
        "prior_draft_checksum": None,
        "estimated_cost_usd": 0.20,
        "max_cost_usd": 0.20,
        "operation": "generate-sfx",
        "output_format": "mp3",
        "max_attempts": 1,
        "preview_model": False,
        "synthid_disclosure_required": False,
        "ai_generated_disclosure_required": True,
    }
    payload.update(overrides)
    return AudioMusicExecutionSpec(**payload)


def test_factory_exposes_source_bound_stability_sfx_capability_without_runtime_claim() -> None:
    capability = STABILITY_SFX_SOURCE_CAPABILITY
    assert capability.provider == "stability"
    assert capability.model == "stable-audio-2.5"
    assert capability.operations == frozenset({"generate-sfx"})
    assert capability.input_modalities == frozenset({"text"})
    assert capability.output_modalities == frozenset({"audio"})
    assert capability.preview is False


def test_stability_sfx_uses_explicit_duration_verbatim_prompt_and_truthful_quality_metadata() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["body"] = request.content
        return httpx.Response(
            200,
            headers={
                "content-type": "audio/mpeg",
                "x-request-id": "fr15-sfx-request-1",
            },
            content=MP3_BYTES,
        )

    adapter = StabilityStableAudioMusicAdapter(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        adapter.invoke(
            _sfx_request(),
            credential="test-only-token",
            base_url="https://api.stability.ai",
        )
    )

    payload = bytes(observed["body"])
    assert observed["method"] == "POST"
    assert observed["path"] == "/v2beta/audio/stable-audio-2/text-to-audio"
    assert b'stable-audio-2.5' in payload
    assert b'7.5' in payload
    assert b'mp3' in payload
    assert b'Short clean glass chime with a fast natural decay.' in payload
    assert b'Instrumental only, no vocals.' not in payload
    assert result.actual_cost_usd == 0.20
    assert result.usage["official_credits_per_success"] == 20
    assert result.metadata["operation"] == "generate-sfx"
    assert result.metadata["nominal_duration_seconds"] == 7.5
    assert result.metadata["provider_sample_rate_hz"] is None
    assert result.metadata["provider_channels"] is None
    assert result.metadata["decoded_quality_measured"] is False


@pytest.mark.parametrize("duration", [None, True, 0, 31])
def test_stability_sfx_invalid_duration_fails_before_transport(duration: object) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=MP3_BYTES)

    adapter = StabilityStableAudioMusicAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderMusicFailure):
        asyncio.run(
            adapter.invoke(
                _sfx_request(duration_seconds=duration),
                credential="test-only-token",
                base_url="https://api.stability.ai",
            )
        )
    assert calls == 0


def test_stability_sfx_ambiguous_transport_failure_is_one_attempt_no_replay() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("simulated timeout after request crossing", request=request)

    adapter = StabilityStableAudioMusicAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderMusicFailure) as captured:
        asyncio.run(
            adapter.invoke(
                _sfx_request(),
                credential="test-only-token",
                base_url="https://api.stability.ai",
            )
        )
    assert calls == 1
    assert captured.value.ambiguous_submission is True
    assert captured.value.safe_to_resubmit is False


def test_runtime_admits_only_bounded_stability_sfx_with_fixed_tariff_semantics() -> None:
    assert _validate_spec(_sfx_spec()) == ("stable-audio-2.5", 0.20)
    assert _sfx_duration_from_request_options(
        "generate-sfx", {"duration_seconds": 7.5}
    ) == 7.5
    assert _sfx_duration_from_request_options("generate-music", {}) is None

    for bad in (
        _sfx_spec(provider="gemini", model="lyria-3-clip-preview", estimated_cost_usd=0.04, max_cost_usd=0.04),
        _sfx_spec(request_options={}),
        _sfx_spec(request_options={"duration_seconds": 31}),
        _sfx_spec(instrumental_only=True),
        _sfx_spec(lyrics="not allowed"),
        _sfx_spec(output_format="wav"),
        _sfx_spec(max_attempts=2),
        _sfx_spec(ai_generated_disclosure_required=False),
    ):
        with pytest.raises(AudioMusicExecutionError):
            _validate_spec(bad)


def test_existing_stability_music_contract_stays_fixed_30_seconds() -> None:
    request = ProviderMusicRequest(
        provider="stability",
        model="stable-audio-2.5",
        operation="generate-music",
        tier="draft",
        prompt="Original governed instrumental music with a clean ending.",
        instrumental_only=True,
        lyrics="",
        output_format="mp3",
    )
    assert StabilityStableAudioMusicAdapter._validate_request(request) == 30.0
