from __future__ import annotations

import pytest

from aios.stable_audio_factory import (
    STABLE_AUDIO_25_ROUTE,
    STABLE_AUDIO_LOW_COST_POLICY,
    StableAudioFactoryError,
    StableAudioRequest,
    StableAudioRightsEvidence,
    build_stable_audio_plan,
)


def rights() -> StableAudioRightsEvidence:
    return StableAudioRightsEvidence(
        commercial_use_authorized=True,
        user_accepts_provider_terms=True,
    )


def request(**overrides) -> StableAudioRequest:
    values = {
        "title": "Governed instrumental draft",
        "prompt": "Original cinematic instrumental music with piano, strings, and a clean ending.",
        "language": "en",
        "rights": rights(),
    }
    values.update(overrides)
    return StableAudioRequest(**values)


def test_stable_audio_25_route_is_fixed_and_non_preview() -> None:
    assert STABLE_AUDIO_25_ROUTE.provider == "stability"
    assert STABLE_AUDIO_25_ROUTE.model == "stable-audio-2.5"
    assert STABLE_AUDIO_25_ROUTE.fixed_cost_usd == 0.20
    assert STABLE_AUDIO_25_ROUTE.credits_per_success == 20
    assert STABLE_AUDIO_25_ROUTE.credit_usd == 0.01
    assert STABLE_AUDIO_25_ROUTE.duration_seconds == 30
    assert STABLE_AUDIO_25_ROUTE.preview is False


def test_stable_audio_plan_is_one_attempt_instrumental_and_private() -> None:
    plan = build_stable_audio_plan(request())
    public = plan.public_snapshot()
    assert plan.max_cost_usd == 0.20
    assert public["provider"] == "stability"
    assert public["model"] == "stable-audio-2.5"
    assert public["max_attempts"] == 1
    assert public["automatic_retry"] is False
    assert public["automatic_cross_provider_fallback"] is False
    assert public["content"]["raw_prompt_returned"] is False
    assert public["content"]["raw_lyrics_returned"] is False
    assert public["rights"]["ai_generated_disclosure_required"] is True
    assert public["rights"]["synthid_disclosure_required"] is False
    assert public["external_gates"] == [
        "valid-funded-stability-credential",
        "stable-audio-2.5-runtime-evidence",
        "music-rights-and-ai-generated-disclosure",
    ]


def test_stable_audio_monthly_policy_is_bounded_to_two_successes() -> None:
    assert STABLE_AUDIO_LOW_COST_POLICY.request_cap_usd == 0.20
    assert STABLE_AUDIO_LOW_COST_POLICY.monthly_user_cap_usd == 0.40
    assert STABLE_AUDIO_LOW_COST_POLICY.max_generations_per_month == 2
    assert STABLE_AUDIO_LOW_COST_POLICY.max_attempts == 1


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"instrumental_only": False}, "vocal generation"),
        ({"duration_seconds": 31}, "30 seconds"),
        ({"max_attempts": 2}, "one attempt"),
        ({"prompt": "Make this sound like a famous singer."}, "imitation"),
        ({"prompt": "Compose in the style of a named celebrity."}, "imitation"),
    ],
)
def test_stable_audio_request_fails_closed(overrides: dict, match: str) -> None:
    with pytest.raises(StableAudioFactoryError, match=match):
        request(**overrides)
