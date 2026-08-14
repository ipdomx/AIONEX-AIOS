from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import Organization, User
from app.services import growth_paid_campaigns as paid


def _actor(org_id: str, user_id: str, email: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name="GS08 Test",
        role="User",
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

        with pytest.raises(
            paid.GrowthPaidCampaignError, match="campaign-approval-required"
        ):
            await paid.simulate_launch(session, actor, campaign.id, days=3)

        await paid.approve_campaign(session, actor, campaign.id)
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
