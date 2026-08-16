from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import GrowthSocialAccount, Organization, User
from app.services import growth_paid_campaigns as paid


def _actor(org_id: str, user_id: str, email: str, role: str = "User") -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name="GS08 Test",
        role=role,
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS08",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )


@pytest.mark.asyncio
async def test_paid_campaign_simulation_hard_gates_and_budget_caps(monkeypatch) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs08-org-{suffix}"
    user_id = f"gs08-user-{suffix}"
    email = f"gs08-{suffix}@example.invalid"

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(paid.growth_access, "effective_access", allow)
    actor = _actor(org_id, user_id, email)

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS08 Test",
                slug=f"gs08-{suffix}",
                plan="test",
                status="active",
            )
        )
        session.add(
            User(
                id=user_id,
                organization_id=org_id,
                email=email,
                name="GS08 Test",
                password_hash="unused",
                status="active",
                auth_version=1,
            )
        )
        await session.commit()

        with pytest.raises(
            paid.GrowthPaidCampaignError, match="daily-cap-exceeds-total-budget"
        ):
            await paid.create_campaign(
                session,
                actor,
                {
                    "name": "Bad",
                    "objective": "sales",
                    "total_budget_minor": 1000,
                    "daily_budget_cap_minor": 2000,
                },
            )

        campaign = await paid.create_campaign(
            session,
            actor,
            {
                "name": "Launch",
                "objective": "sales",
                "total_budget_minor": 100000,
                "daily_budget_cap_minor": 25000,
                "currency": "USD",
                "stop_loss_policy": {"max_cpa_minor": 5000, "min_roas": 1.5},
            },
        )
        public = paid.public_campaign(campaign)
        assert public["real_spend_allowed"] is False
        assert public["live_provider_call"] is False
        assert public["live_campaign_mutation"] is False
        assert public["automatic_budget_increase_allowed"] is False
        assert public["owner_approval_required"] is True
        assert public["aios_advice_only"] is True
        assert public["user_budget_preserved"] is True

        adset = await paid.add_ad_set(
            session,
            actor,
            campaign.id,
            {
                "name": "AE",
                "provider": "instagram",
                "audience": {"country": "AE"},
                "placements": ["feed"],
                "daily_budget_cap_minor": 20000,
            },
        )
        c1 = await paid.add_creative(
            session,
            actor,
            campaign.id,
            {"name": "C1", "format": "image", "headline": "One", "approved": True},
        )
        c2 = await paid.add_creative(
            session,
            actor,
            campaign.id,
            {"name": "C2", "format": "image", "headline": "Two", "approved": True},
        )
        a1 = await paid.add_ad(
            session,
            actor,
            campaign.id,
            {"name": "A1", "ad_set_id": adset.id, "creative_id": c1.id},
        )
        a2 = await paid.add_ad(
            session,
            actor,
            campaign.id,
            {"name": "A2", "ad_set_id": adset.id, "creative_id": c2.id},
        )
        exp = await paid.create_experiment(
            session,
            actor,
            campaign.id,
            {"name": "AB", "hypothesis": "C1 wins", "variant_ad_ids": [a2.id, a1.id]},
        )
        assert list(exp.allocation) == sorted([a1.id, a2.id])
        assert abs(sum(exp.allocation.values()) - 1.0) < 0.00001

        # AIOS analyzes the user's chosen budget before owner approval and only advises.
        preapproval_sim, preapproval_decision = await paid.simulate_launch(
            session, actor, campaign.id, days=3
        )
        assert preapproval_sim.real_spend_allowed is False
        assert preapproval_decision.approval_required is True
        assert preapproval_decision.automatic_execution_allowed is False
        assert campaign.total_budget_minor == 100000
        assert campaign.daily_budget_cap_minor == 25000
        assessment = preapproval_decision.metrics["budget_assessment"]
        assert assessment["advisory_only"] is True
        assert assessment["budget_mutated"] is False
        assert assessment["owner_approval_required"] is True
        assert assessment["user_total_budget_minor"] == 100000
        assert assessment["user_daily_budget_minor"] == 25000

        with pytest.raises(
            paid.GrowthPaidCampaignError, match="super-owner-approval-required"
        ):
            await paid.approve_campaign(session, actor, campaign.id)

        owner = _actor(org_id, user_id, email, role="Super Owner")
        await paid.approve_campaign(session, owner, campaign.id)
        sim1, dec1 = await paid.simulate_launch(session, actor, campaign.id, days=3)
        sim2, dec2 = await paid.simulate_launch(session, actor, campaign.id, days=3)
        assert sim1.seed == sim2.seed
        assert sim1.result == sim2.result
        assert dec1.action == dec2.action
        assert sim1.simulated_spend_minor <= min(
            campaign.total_budget_minor, campaign.daily_budget_cap_minor * 3
        )
        assert (
            sim1.real_spend_allowed is False
            and sim1.live_provider_call is False
            and sim1.live_campaign_mutation is False
        )
        assert (
            dec1.automatic_execution_allowed is False
            and dec1.real_spend_allowed is False
            and dec1.approval_required is True
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_access_denied_fail_closed(monkeypatch) -> None:
    actor = _actor("o", "u", "x@example.invalid")

    async def deny(_session, _actor, _capability):
        return SimpleNamespace(allowed=False, reason="owner-deny")

    monkeypatch.setattr(paid.growth_access, "effective_access", deny)
    async with SessionLocal() as session:
        with pytest.raises(
            paid.GrowthPaidCampaignError, match="access-denied:owner-deny"
        ):
            await paid.create_campaign(
                session,
                actor,
                {
                    "name": "No",
                    "objective": "sales",
                    "total_budget_minor": 1000,
                    "daily_budget_cap_minor": 100,
                },
            )


@pytest.mark.asyncio
async def test_prepare_and_simulate_campaign_is_advisory_and_atomic(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs08-prepare-org-{suffix}"
    user_id = f"gs08-prepare-user-{suffix}"
    email = f"gs08-prepare-{suffix}@example.invalid"

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(paid.growth_access, "effective_access", allow)
    actor = _actor(org_id, user_id, email)

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS08 Prepare",
                slug=f"gs08-prepare-{suffix}",
                plan="test",
                status="active",
            )
        )
        await session.flush()
        session.add(
            User(
                id=user_id,
                organization_id=org_id,
                email=email,
                name="GS08 Prepare",
                password_hash="unused",
                status="active",
                auth_version=1,
            )
        )
        await session.flush()

        result = await paid.prepare_and_simulate_campaign(
            session,
            actor,
            {
                "campaign_name": "Atomic Campaign",
                "objective": "sales",
                "currency": "EUR",
                "total_budget_minor": 120000,
                "daily_budget_cap_minor": 20000,
                "max_cpa_minor": 10000,
                "min_roas": 1.5,
                "provider": "instagram",
                "target_countries": ["AE"],
                "placements": ["feed", "stories"],
                "headline": "Atomic",
                "body": "Advisory only",
                "destination_url": "https://example.invalid/landing",
                "days": 3,
            },
        )
        campaign = result["campaign"]
        decision = result["decision"]
        assessment = decision.metrics["budget_assessment"]
        assert campaign.total_budget_minor == 120000
        assert campaign.daily_budget_cap_minor == 20000
        assert campaign.approval_status == "pending_owner"
        assert campaign.status == "awaiting_owner_approval"
        assert campaign.real_spend_allowed is False
        assert campaign.live_provider_call is False
        assert campaign.live_campaign_mutation is False
        assert campaign.automatic_budget_increase_allowed is False
        assert result["ad_set"].status == "draft"
        assert result["creative"].approval_status == "not_requested"
        assert result["ad"].status == "ready"
        assert assessment["advisory_only"] is True
        assert assessment["budget_mutated"] is False
        assert assessment["owner_approval_required"] is True
        assert assessment["analysis_basis"] == "synthetic_prelaunch_v2"
        assert assessment["real_performance_data_used"] is False
        assert assessment["guaranteed_results"] is False
        assert assessment["user_total_budget_minor"] == 120000
        assert assessment["user_daily_budget_minor"] == 20000
        assert decision.metrics["provider_call_executed"] is False
        assert decision.metrics["real_spend_executed"] is False
        await session.rollback()

    async with SessionLocal() as session:
        from app.db.models import GrowthPaidCampaign

        rows = (
            await session.scalars(
                select(GrowthPaidCampaign).where(
                    GrowthPaidCampaign.organization_id == org_id,
                    GrowthPaidCampaign.name == "Atomic Campaign",
                )
            )
        ).all()
        assert rows == []


@pytest.mark.asyncio
async def test_prepare_campaign_rejects_invalid_target_before_commit(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs08-invalid-org-{suffix}"
    user_id = f"gs08-invalid-user-{suffix}"
    email = f"gs08-invalid-{suffix}@example.invalid"

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(paid.growth_access, "effective_access", allow)
    actor = _actor(org_id, user_id, email)

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS08 Invalid",
                slug=f"gs08-invalid-{suffix}",
                plan="test",
                status="active",
            )
        )
        await session.flush()
        session.add(
            User(
                id=user_id,
                organization_id=org_id,
                email=email,
                name="GS08 Invalid",
                password_hash="unused",
                status="active",
                auth_version=1,
            )
        )
        await session.flush()
        with pytest.raises(
            paid.GrowthPaidCampaignError, match="target-countries-invalid"
        ):
            await paid.prepare_and_simulate_campaign(
                session,
                actor,
                {
                    "campaign_name": "Invalid Atomic Campaign",
                    "objective": "sales",
                    "currency": "EUR",
                    "total_budget_minor": 10000,
                    "daily_budget_cap_minor": 1000,
                    "provider": "instagram",
                    "target_countries": ["NOT-A-COUNTRY"],
                },
            )
        await session.rollback()


def test_paid_campaign_numeric_limits_are_technical_not_product_caps() -> None:
    paid._safe_budget(100_00, 10_00)
    with pytest.raises(paid.GrowthPaidCampaignError, match="budget-too-large"):
        paid._safe_budget(paid.MAX_MONEY_MINOR + 1, 1)
    with pytest.raises(paid.GrowthPaidCampaignError, match="min-roas-invalid"):
        paid._safe_policy({"min_roas": float("inf")})


def test_paid_campaign_destination_url_is_http_only_and_has_no_credentials() -> None:
    assert (
        paid._safe_destination_url("https://example.invalid/path")
        == "https://example.invalid/path"
    )
    with pytest.raises(paid.GrowthPaidCampaignError, match="destination-url-invalid"):
        paid._safe_destination_url("javascript:alert(1)")
    with pytest.raises(
        paid.GrowthPaidCampaignError, match="destination-url-credentials-forbidden"
    ):
        paid._safe_destination_url("https://user:pass@example.invalid/path")


@pytest.mark.asyncio
async def test_campaign_readiness_requires_linked_ad_account_and_derives_currency(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs08-ready-org-{suffix}"
    user_id = f"gs08-ready-user-{suffix}"
    email = f"gs08-ready-{suffix}@example.invalid"

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(paid.growth_access, "effective_access", allow)
    actor = _actor(org_id, user_id, email)

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS08 Ready",
                slug=f"gs08-ready-{suffix}",
                plan="test",
                status="active",
            )
        )
        session.add(
            User(
                id=user_id,
                organization_id=org_id,
                email=email,
                name="GS08 Ready",
                password_hash="unused",
                status="active",
                auth_version=1,
            )
        )
        await session.flush()

        empty = await paid.campaign_readiness(session, actor)
        assert empty["campaigns_visible"] is False
        assert empty["reason"] == "no-linked-ad-account"

        page = GrowthSocialAccount(
            organization_id=org_id,
            created_by_id=user_id,
            provider="facebook",
            account_kind="page",
            external_account_id=f"page-{suffix}",
            display_name="Page is not an ad account",
            credential_ref="file:/run/operator-secrets/social/page-test",
            status="active",
            health_state="healthy",
            health_reasons=[],
            provider_metadata={"currency": "USD"},
            settings={},
        )
        session.add(page)
        await session.flush()
        still_empty = await paid.campaign_readiness(session, actor)
        assert still_empty["campaigns_visible"] is False
        assert still_empty["reason"] == "no-linked-ad-account"

        ad_account = GrowthSocialAccount(
            organization_id=org_id,
            created_by_id=user_id,
            provider="facebook",
            account_kind="ad_account",
            external_account_id=f"act-{suffix}",
            display_name="Meta Ads UAE",
            credential_ref="file:/run/operator-secrets/social/meta-ad-test",
            status="active",
            health_state="healthy",
            health_reasons=[],
            provider_metadata={"currency": "eur"},
            settings={},
        )
        session.add(ad_account)
        await session.flush()

        ready = await paid.campaign_readiness(session, actor)
        assert ready["campaigns_visible"] is True
        assert ready["reason"] == "ready"
        assert ready["linked_ad_accounts"] == [
            {
                "id": ad_account.id,
                "provider": "facebook",
                "display_name": "Meta Ads UAE",
                "currency": "EUR",
                "live_objectives": ["traffic"],
            }
        ]
        assert ready["objectives"]["traffic"] == "live-meta-ready"
        assert ready["objectives"]["sales"] == "analysis-only"

        binding = await paid.resolve_linked_ad_account(session, actor, ad_account.id)
        assert binding["provider"] == "facebook"
        assert binding["currency"] == "EUR"
        assert binding["live_objectives"] == ["traffic"]
        await session.rollback()


@pytest.mark.asyncio
async def test_campaign_readiness_denied_is_safe_and_non_throwing(monkeypatch) -> None:
    actor = _actor("org-denied", "user-denied", "denied@example.invalid")

    async def deny(_session, _actor, capability):
        return SimpleNamespace(
            allowed=False, reason="not-entitled", capability=capability
        )

    monkeypatch.setattr(paid.growth_access, "effective_access", deny)
    async with SessionLocal() as session:
        result = await paid.campaign_readiness(session, actor)
    assert result["campaigns_visible"] is False
    assert result["linked_ad_accounts"] == []
    assert result["reason"] == "ads-manage-not-entitled"
