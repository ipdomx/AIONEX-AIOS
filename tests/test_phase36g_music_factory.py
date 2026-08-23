from __future__ import annotations

import pytest

from aios.music_factory import (
    LOW_COST_MUSIC_POLICY,
    MusicFactoryError,
    MusicRequest,
    MusicRightsEvidence,
    build_music_plan,
)


RIGHTS_HASH = "a" * 64
DRAFT_HASH = "b" * 64
APPROVAL_HASH = "e" * 64


def instrumental_rights() -> MusicRightsEvidence:
    return MusicRightsEvidence(
        basis="instrumental",
        evidence_sha256=None,
        commercial_use_authorized=True,
        user_accepts_provider_terms=True,
    )


def vocal_rights() -> MusicRightsEvidence:
    return MusicRightsEvidence(
        basis="original-user-owned",
        evidence_sha256=RIGHTS_HASH,
        commercial_use_authorized=True,
        user_accepts_provider_terms=True,
    )


def test_draft_is_the_default_cheapest_route() -> None:
    plan = build_music_plan(
        MusicRequest(
            title="Low-cost launch draft",
            prompt="Bright instrumental electronic music with a clear intro and outro.",
            language="en",
            rights=instrumental_rights(),
        )
    )
    public = plan.public_snapshot()
    assert plan.route.provider == "replicate"
    assert plan.route.model == "google/lyria-3"
    assert plan.route.fixed_cost_usd == 0.04
    assert plan.max_cost_usd == 0.04
    assert public["provider"] == "replicate"
    assert public["external_gates"] == [
        "valid-replicate-credential",
        "replicate-lyria-runtime-evidence",
        "music-rights-and-synthid-disclosure",
    ]
    assert public["default_low_cost_route"] is True
    assert public["max_attempts"] == 1
    assert public["automatic_retry"] is False
    assert public["music_generation_requests"] == 0
    assert public["provider_spend_usd"] == 0.0
    assert public["content"]["raw_prompt_returned"] is False


def test_full_song_requires_prior_draft_and_explicit_approval() -> None:
    request = MusicRequest(
        title="Approved final song",
        prompt="Uplifting pop arrangement with verse, chorus, bridge, and a clean ending.",
        language="en",
        rights=vocal_rights(),
        tier="final",
        instrumental_only=False,
        lyrics="[Verse]\nWe build with care.\n[Chorus]\nEvery step stays clear.",
        final_generation_approved=True,
        final_approval_evidence_sha256=APPROVAL_HASH,
        prior_draft_checksum=DRAFT_HASH,
    )
    plan = build_music_plan(request)
    assert plan.route.provider == "replicate"
    assert plan.route.model == "google/lyria-3-pro"
    assert plan.route.fixed_cost_usd == 0.08
    assert plan.max_cost_usd == 0.08
    assert plan.public_snapshot()["prior_draft_checksum_present"] is True


@pytest.mark.parametrize(
    "kwargs,match",
    [
        (
            {
                "tier": "final",
                "instrumental_only": True,
                "final_generation_approved": False,
                "final_approval_evidence_sha256": APPROVAL_HASH,
                "prior_draft_checksum": DRAFT_HASH,
            },
            "explicit final approval",
        ),
        (
            {
                "tier": "final",
                "instrumental_only": True,
                "final_generation_approved": True,
                "final_approval_evidence_sha256": APPROVAL_HASH,
                "prior_draft_checksum": None,
            },
            "accepted draft checksum",
        ),
        (
            {
                "tier": "final",
                "instrumental_only": True,
                "final_generation_approved": True,
                "final_approval_evidence_sha256": None,
                "prior_draft_checksum": DRAFT_HASH,
            },
            "approval evidence",
        ),
        (
            {"prompt": "Make this sound like a famous chart singer."},
            "style references",
        ),
        (
            {"prompt": "Compose in the style of a named celebrity."},
            "style references",
        ),
        (
            {"max_attempts": 2},
            "exactly one attempt",
        ),
    ],
)
def test_cost_and_identity_safety_fail_closed(kwargs: dict, match: str) -> None:
    values = {
        "title": "Governed music",
        "prompt": "Original cinematic instrumental music with piano and strings.",
        "language": "en",
        "rights": instrumental_rights(),
    }
    values.update(kwargs)
    with pytest.raises(MusicFactoryError, match=match):
        MusicRequest(**values)


def test_vocal_music_requires_rights_evidence_and_never_returns_raw_lyrics() -> None:
    plan = build_music_plan(
        MusicRequest(
            title="Original governed vocals",
            prompt="Warm acoustic folk song with gentle percussion and a hopeful chorus.",
            language="en",
            rights=vocal_rights(),
            instrumental_only=False,
            lyrics="These are original user-owned words.",
        )
    )
    public = plan.public_snapshot()
    assert public["content"]["lyrics_sha256"]
    assert public["content"]["lyrics_characters"] > 0
    assert public["content"]["raw_lyrics_returned"] is False
    assert public["rights"]["evidence_sha256"] == RIGHTS_HASH
    assert public["rights"]["synthid_disclosure_required"] is True


def test_instrumental_route_cannot_claim_lyric_rights() -> None:
    with pytest.raises(MusicFactoryError, match="must not claim lyric rights"):
        MusicRightsEvidence(
            basis="instrumental",
            evidence_sha256=RIGHTS_HASH,
            commercial_use_authorized=True,
            user_accepts_provider_terms=True,
        )


def test_low_cost_policy_cannot_enable_retry_or_raise_default_cap() -> None:
    assert LOW_COST_MUSIC_POLICY.default_tier == "draft"
    assert LOW_COST_MUSIC_POLICY.default_user_request_cap_usd == 0.04
    assert LOW_COST_MUSIC_POLICY.final_user_request_cap_usd == 0.08
    assert LOW_COST_MUSIC_POLICY.automatic_retry is False
