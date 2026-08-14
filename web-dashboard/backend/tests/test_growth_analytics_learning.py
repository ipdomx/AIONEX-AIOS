from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import Organization, User
from app.services import growth_analytics_learning as analytics


def test_metric_normalization_is_deterministic() -> None:
    payload = {
        "impressions": 10_000,
        "reach": 8_000,
        "engagements": 600,
        "clicks": 300,
        "conversions": 30,
        "spend_minor": 30_000,
        "revenue_minor": 120_000,
    }
    first = analytics.normalize_metrics(payload)
    second = analytics.normalize_metrics(payload)
    assert first == second
    assert first["ctr"] == 0.03
    assert first["engagement_rate"] == 0.06
    assert first["conversion_rate"] == 0.1
    assert first["cpc_minor"] == 100
    assert first["cpa_minor"] == 1000
    assert first["roas"] == 4.0


def test_negative_metrics_and_sensitive_context_are_rejected() -> None:
    with pytest.raises(analytics.GrowthAnalyticsError, match="negative-metric:clicks"):
        analytics.normalize_metrics({"clicks": -1})
    with pytest.raises(
        analytics.GrowthAnalyticsError, match="sensitive-field-rejected"
    ):
        analytics._assert_safe({"nested": {"access_token": "never-store"}})


def test_classification_success_failure_and_inconclusive_are_explainable() -> None:
    context = {
        "targets": {
            "min_impressions": 100,
            "min_ctr": 0.01,
            "min_conversion_rate": 0.05,
            "max_cpa_minor": 2_000,
            "min_roas": 2.0,
        }
    }
    success = analytics.normalize_metrics(
        {
            "impressions": 10_000,
            "clicks": 300,
            "conversions": 30,
            "spend_minor": 30_000,
            "revenue_minor": 120_000,
        }
    )
    outcome, score, reasons = analytics.classify_metrics(success, context, 0.9)
    assert outcome == "success"
    assert score > 0.9
    assert reasons == ["targets-met"]

    failure = analytics.normalize_metrics(
        {
            "impressions": 10_000,
            "clicks": 20,
            "conversions": 0,
            "spend_minor": 50_000,
            "revenue_minor": 10_000,
        }
    )
    outcome, _, reasons = analytics.classify_metrics(failure, context, 0.9)
    assert outcome == "failure"
    assert "low-ctr" in reasons
    assert "low-conversion-rate" in reasons
    assert "no-conversions" in reasons
    assert "high-cpa" in reasons
    assert "negative-roas" in reasons
    assert "roas-below-target" in reasons

    weak = analytics.normalize_metrics({"impressions": 50, "clicks": 5})
    outcome, _, reasons = analytics.classify_metrics(weak, context, 0.3)
    assert outcome == "inconclusive"
    assert "insufficient-sample" in reasons


def test_recommendation_never_auto_executes() -> None:
    success = analytics.recommendation_for_pattern(
        outcome="success",
        sample_quality=0.9,
        success_count=1,
        failure_count=0,
        reason_codes=["targets-met"],
    )
    assert success["action"] == "replay_candidate"
    assert success["replay_eligible"] is True
    assert success["auto_optimization_allowed"] is False
    assert success["auto_replay_allowed"] is False
    assert "manual-approval-required" in success["reason_codes"]

    repeated_failure = analytics.recommendation_for_pattern(
        outcome="failure",
        sample_quality=0.9,
        success_count=0,
        failure_count=2,
        reason_codes=["low-ctr"],
    )
    assert repeated_failure["action"] == "avoid"
    assert repeated_failure["replay_eligible"] is False
    assert "repeat-failure-blocked" in repeated_failure["reason_codes"]
    assert repeated_failure["auto_replay_allowed"] is False


@pytest.mark.asyncio
async def test_analytics_access_denial_fails_before_persistence(monkeypatch) -> None:
    async def denied(_session, _actor, _capability):
        return SimpleNamespace(allowed=False, reason="owner-deny")

    monkeypatch.setattr(analytics.growth_access, "effective_access", denied)
    actor = SimpleNamespace(id="user", organization_id="org")
    now = datetime.now(timezone.utc)
    with pytest.raises(
        analytics.GrowthAnalyticsError, match="access-denied:owner-deny"
    ):
        await analytics.record_observation(  # type: ignore[arg-type]
            None,
            actor,
            {
                "subject_type": "campaign",
                "subject_id": "campaign-1",
                "period_start": now - timedelta(days=1),
                "period_end": now,
            },
        )


@pytest.mark.asyncio
async def test_durable_learning_replay_candidate_and_repeated_failure_block(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs05-org-{suffix}"
    user_id = f"gs05-user-{suffix}"
    email = f"gs05-{suffix}@example.invalid"

    async def allowed(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="owner-grant")

    monkeypatch.setattr(analytics.growth_access, "effective_access", allowed)
    actor = UserRecord(
        id=user_id,
        email=email,
        name="GS05 Test User",
        role="User",
        password_hash="not-used",
        organization_id=org_id,
        organization_name="GS05 Test",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )
    now = datetime.now(timezone.utc)
    base_context = {
        "objective": "qualified_leads",
        "audience_key": "uae-smb",
        "creative_key": "video-v1",
        "offer_key": "demo",
        "geo_key": "AE",
        "targets": {
            "min_impressions": 100,
            "min_ctr": 0.01,
            "min_conversion_rate": 0.05,
            "max_cpa_minor": 2_000,
            "min_roas": 2.0,
        },
    }
    evidence = [{"source": "gs05-test", "reliability": 0.95}]

    async with SessionLocal() as session:
        try:
            session.add(
                Organization(
                    id=org_id,
                    name="GS05 Test",
                    slug=f"gs05-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            session.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=email,
                    name="GS05 Test User",
                    password_hash="not-used",
                    status="active",
                    auth_version=1,
                )
            )
            await session.commit()

            success_observation = await analytics.record_observation(
                session,
                actor,
                {
                    "subject_type": "campaign",
                    "subject_id": "successful-campaign",
                    "provider": "facebook",
                    "source": "simulation",
                    "period_start": now - timedelta(days=7),
                    "period_end": now,
                    "impressions": 10_000,
                    "reach": 8_500,
                    "engagements": 700,
                    "clicks": 300,
                    "conversions": 30,
                    "spend_minor": 30_000,
                    "revenue_minor": 120_000,
                    "evidence": evidence,
                    "context": {**base_context, "creative_key": "success-video-v1"},
                },
            )
            success_learning, success_recommendation = (
                await analytics.analyze_observation(
                    session, actor, success_observation.id
                )
            )
            await session.commit()
            assert success_learning.outcome == "success"
            assert success_recommendation.action == "replay_candidate"
            assert success_recommendation.replay_eligible is True
            assert success_recommendation.auto_replay_allowed is False
            assert success_recommendation.auto_optimization_allowed is False

            # Analyzing the same observation is idempotent.
            same_learning, same_recommendation = await analytics.analyze_observation(
                session, actor, success_observation.id
            )
            assert same_learning.id == success_learning.id
            assert same_recommendation.id == success_recommendation.id

            failure_payload = {
                "subject_type": "campaign",
                "provider": "facebook",
                "source": "simulation",
                "period_start": now - timedelta(days=7),
                "period_end": now,
                "impressions": 10_000,
                "reach": 8_000,
                "engagements": 100,
                "clicks": 20,
                "conversions": 0,
                "spend_minor": 50_000,
                "revenue_minor": 10_000,
                "evidence": evidence,
                "context": base_context,
            }
            first_failure = await analytics.record_observation(
                session,
                actor,
                {**failure_payload, "subject_id": "failure-run-1"},
            )
            first_learning, first_recommendation = await analytics.analyze_observation(
                session, actor, first_failure.id
            )
            await session.commit()
            assert first_learning.outcome == "failure"
            assert first_recommendation.action == "iterate"
            assert first_recommendation.replay_eligible is False
            assert first_learning.failure_count == 1

            second_failure = await analytics.record_observation(
                session,
                actor,
                {**failure_payload, "subject_id": "failure-run-2"},
            )
            second_learning, second_recommendation = (
                await analytics.analyze_observation(session, actor, second_failure.id)
            )
            await session.commit()
            assert second_learning.outcome == "failure"
            assert second_learning.fingerprint == first_learning.fingerprint
            assert second_learning.failure_count == 2
            assert second_recommendation.action == "avoid"
            assert second_recommendation.replay_eligible is False
            assert "repeat-failure-blocked" in second_recommendation.reason_codes
            assert "do-not-repeat-same-pattern" in second_recommendation.reason_codes
            assert second_recommendation.auto_replay_allowed is False

            weak_observation = await analytics.record_observation(
                session,
                actor,
                {
                    "subject_type": "content",
                    "subject_id": "weak-sample",
                    "provider": "instagram",
                    "source": "simulation",
                    "period_start": now - timedelta(hours=1),
                    "period_end": now,
                    "impressions": 50,
                    "clicks": 5,
                    "conversions": 0,
                    "evidence": [],
                    "context": base_context,
                },
            )
            weak_learning, weak_recommendation = await analytics.analyze_observation(
                session, actor, weak_observation.id
            )
            await session.commit()
            assert weak_learning.outcome == "inconclusive"
            assert weak_recommendation.action == "measure"
            assert weak_recommendation.replay_eligible is False

            patterns = await analytics.pattern_summary(session, actor)
            failed_pattern = next(
                item
                for item in patterns
                if item["fingerprint"] == second_learning.fingerprint
            )
            assert failed_pattern["occurrences"] == 2
            assert failed_pattern["failures"] == 2

            recommendations = await analytics.list_recommendations(session, actor)
            assert len(recommendations) == 4
            assert all(item["auto_replay_allowed"] is False for item in recommendations)
            assert all(
                item["auto_optimization_allowed"] is False for item in recommendations
            )
        finally:
            await session.rollback()
            org = await session.get(Organization, org_id)
            if org is not None:
                await session.delete(org)
            await session.commit()
