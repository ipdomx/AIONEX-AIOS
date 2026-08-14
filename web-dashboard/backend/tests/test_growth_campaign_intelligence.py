from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import growth_campaign_intelligence as intelligence


def _payload() -> dict:
    return {
        "budget_minor": 50000,
        "currency": "USD",
        "target_markets": ["AE", "SA"],
        "audience_hypotheses": [
            {"segment": "SMB owners", "rationale": "Need measurable lead generation"},
            {
                "segment": "Ecommerce managers",
                "rationale": "Need lower acquisition cost",
            },
        ],
        "competitor_hypotheses": [
            {"name": "Competitor A", "rationale": "Targets similar intent"}
        ],
        "offer_hypotheses": [
            {"name": "Free audit", "rationale": "Reduces first-step friction"}
        ],
        "channel_hypotheses": [
            {"channel": "search", "rationale": "Captures high intent"},
            {"channel": "social", "rationale": "Builds retargeting pool"},
        ],
        "evidence": [
            {"source": "first-party-crm", "weight": 3, "reliability": 0.9},
            {"source": "market-research", "weight": 2, "reliability": 0.8},
        ],
    }


def test_simulation_is_deterministic_and_never_allows_real_spend() -> None:
    payload = _payload()
    first = intelligence.simulate_payload(payload, "expected").as_dict()
    second = intelligence.simulate_payload(payload, "expected").as_dict()
    assert first == second
    assert first["real_spend_allowed"] is False
    assert "simulation-only" in first["reason_codes"]
    assert "no-provider-spend" in first["reason_codes"]


def test_scenarios_are_ordered_and_bounded() -> None:
    payload = _payload()
    conservative = intelligence.simulate_payload(payload, "conservative")
    expected = intelligence.simulate_payload(payload, "expected")
    upside = intelligence.simulate_payload(payload, "upside")
    assert conservative.reach_max < expected.reach_max < upside.reach_max
    assert conservative.clicks_max < expected.clicks_max < upside.clicks_max
    assert 0.25 <= expected.confidence <= 0.92
    assert expected.conversions_min <= expected.conversions_max


def test_weak_evidence_reduces_confidence_and_emits_reason_codes() -> None:
    strong = intelligence.simulate_payload(_payload(), "expected")
    weak_payload = _payload()
    weak_payload["evidence"] = []
    weak_payload["competitor_hypotheses"] = []
    weak_payload["offer_hypotheses"] = []
    weak = intelligence.simulate_payload(weak_payload, "expected")
    assert weak.confidence < strong.confidence
    assert "limited-evidence" in weak.reason_codes
    assert "weak-hypothesis-coverage" in weak.reason_codes


def test_invalid_scenario_and_zero_budget_fail_closed() -> None:
    with pytest.raises(intelligence.GrowthCampaignError, match="unsupported-scenario"):
        intelligence.simulate_payload(_payload(), "impossible")
    payload = _payload()
    payload["budget_minor"] = 0
    with pytest.raises(intelligence.GrowthCampaignError, match="budget-required"):
        intelligence.simulate_payload(payload, "expected")


def test_brief_fingerprint_is_stable_and_sensitive() -> None:
    base = {
        "objective": "leads",
        "product_summary": "AI marketing platform",
        "target_markets": ["AE", "SA"],
        "budget_minor": 10000,
        "currency": "USD",
    }
    assert intelligence.brief_fingerprint(base) == intelligence.brief_fingerprint(
        dict(base)
    )
    changed = dict(base)
    changed["budget_minor"] = 20000
    assert intelligence.brief_fingerprint(base) != intelligence.brief_fingerprint(
        changed
    )


@pytest.mark.asyncio
async def test_capability_gate_denies_unentitled_actor(monkeypatch) -> None:
    async def denied(_session, _actor, capability):
        assert capability == "campaign.research"
        return SimpleNamespace(allowed=False, reason="owner-deny")

    monkeypatch.setattr(intelligence.growth_access, "effective_access", denied)
    with pytest.raises(
        intelligence.GrowthCampaignError, match="access-denied:owner-deny"
    ):
        await intelligence._require(None, SimpleNamespace(), "campaign.research")  # type: ignore[arg-type]


def test_global_real_spend_gate_is_false() -> None:
    assert intelligence.REAL_SPEND_ALLOWED is False
