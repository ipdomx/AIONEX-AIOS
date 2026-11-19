"""Plan names shared by billing and Studio, and the plan-usage helpers (no database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import plan_usage, studio_governance
from app.services.studio_governance import canonical_plan, plan_allowed


def test_studio_uses_billing_plan_names():
    # Billing stores "business" (enterprise/team are aliases). Before this fix a
    # paying "business" organization got plan_not_supported for every capability.
    assert canonical_plan("enterprise") == "business"
    assert canonical_plan(" Business ") == "business"
    assert canonical_plan("team") == "professional"
    assert plan_allowed("business", ("starter", "professional", "enterprise"))
    assert plan_allowed("enterprise", ("business",))
    assert not plan_allowed("free", studio_governance.PAID_PLANS)


def test_premium_inherits_professional_in_policies_saved_before_it_existed():
    legacy = ["starter", "professional", "enterprise"]
    assert plan_allowed("premium", legacy)
    # Once the Owner names premium (or leaves professional out) the list is exact.
    assert not plan_allowed("premium", ["starter", "business"])
    assert plan_allowed("premium", ["premium"])


def test_every_default_capability_supports_the_paid_tiers():
    for definition in studio_governance.CAPABILITIES:
        supported = set(definition.supported_plans)
        assert {"professional", "premium", "business"} <= supported, definition.capability_id
        policy = studio_governance.default_policy(definition)
        studio_governance.normalize_policy(definition, policy, enabled=True)


def test_limit_normalization_treats_missing_or_negative_as_unlimited():
    assert plan_usage.normalize_limit(None) is None
    assert plan_usage.normalize_limit("") is None
    assert plan_usage.normalize_limit(-1) is None
    assert plan_usage.normalize_limit(True) is None
    assert plan_usage.normalize_limit("0") == 0
    assert plan_usage.normalize_limit(25_000) == 25_000


def test_usage_period_rolls_over_after_thirty_days():
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    payload, expired = plan_usage.current_period(
        {"period_started_at": old, "period_ends_at": old, "user_messages_used": 9}
    )
    assert expired and payload["user_messages_used"] == 0
    fresh, expired = plan_usage.current_period(None)
    assert not expired and fresh["assistant_responses_used"] == 0
