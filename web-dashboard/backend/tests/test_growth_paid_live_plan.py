from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    GrowthControlledPilot,
    GrowthSocialProviderCapability,
    Organization,
    User,
)
from app.services import growth_controlled_pilots as pilots
from app.services import growth_paid_campaigns as paid
from app.services import growth_paid_live_plan as live_plan

PAGE_REF = "pageref://meta/sha256/" + "a" * 64


def _actor(org_id: str, user_id: str, role: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.invalid",
        name=role,
        role=role,
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS12 Live Plan",
        organization_plan="test",
        permissions=["*"] if role == "Super Owner" else [],
        status="active",
        auth_version=1,
    )


async def _fixture(session, monkeypatch):
    suffix = uuid4().hex[:10]
    org_id = str(uuid4())
    user_id = str(uuid4())
    owner_id = str(uuid4())
    user = _actor(org_id, user_id, "User")
    owner = _actor(org_id, owner_id, "Super Owner")

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(paid.growth_access, "effective_access", allow)
    session.add(
        Organization(
            id=org_id,
            name="GS12 Live Plan",
            slug=f"gs12-live-plan-{suffix}",
            plan="test",
            status="active",
        )
    )
    await session.flush()
    session.add_all(
        [
            User(
                id=user_id,
                organization_id=org_id,
                email=user.email,
                name=user.name,
                password_hash="unused",
                status="active",
                auth_version=1,
            ),
            User(
                id=owner_id,
                organization_id=org_id,
                email=owner.email,
                name=owner.name,
                password_hash="unused",
                status="active",
                auth_version=1,
            ),
        ]
    )
    await session.flush()

    campaign = await paid.create_campaign(
        session,
        user,
        {
            "name": "Traffic Plan",
            "objective": "traffic",
            "currency": "EUR",
            "total_budget_minor": 1500,
            "daily_budget_cap_minor": 400,
            "stop_loss_policy": {"max_cpa_minor": 250, "min_roas": 1.25},
            "metadata": {"prepared_by": "test"},
        },
    )
    ad_set = await paid.add_ad_set(
        session,
        user,
        campaign.id,
        {
            "name": "Instagram AE",
            "provider": "instagram",
            "audience": {"countries": ["AE"]},
            "placements": ["feed"],
            "daily_budget_cap_minor": 400,
        },
    )
    creative = await paid.add_creative(
        session,
        user,
        campaign.id,
        {
            "name": "Traffic Creative",
            "format": "image",
            "headline": "Traffic",
            "body": "Visit the site",
            "destination_url": "https://example.invalid/traffic",
            "utm": {"source": "aios"},
        },
    )
    ad = await paid.add_ad(
        session,
        user,
        campaign.id,
        {"name": "Traffic Ad", "ad_set_id": ad_set.id, "creative_id": creative.id},
    )
    await paid.approve_campaign(session, owner, campaign.id)

    scope_ref = "accountref://meta/sha256/" + "b" * 64
    pilot = GrowthControlledPilot(
        id=str(uuid4()),
        organization_id=org_id,
        created_by_id=owner_id,
        provider="meta",
        provider_scope="managed_ad_account",
        scope_ref=scope_ref,
        mode="live_spend",
        capability="ads.manage",
        status="controls_configured",
        owner_approved_by_id=owner_id,
        owner_approved_at=pilots._now(),
        owner_approval_reference="test-owner-approval",
        legal_policy_acknowledged=False,
        launch_authorized=False,
        currency="EUR",
        max_total_budget_minor=2000,
        max_daily_budget_minor=500,
        max_cpa_minor=300,
        min_roas=1.5,
        expires_at=pilots._now() + timedelta(hours=24),
        live_provider_mutation_allowed=False,
        real_spend_allowed=False,
        evidence={},
        blocked_reasons=[],
        version=1,
    )
    session.add(pilot)
    session.add(
        GrowthSocialProviderCapability(
            provider="meta",
            capability="ads.manage",
            verification_state="live_write_verified",
            mutation_class="write",
            evidence={
                "mutation_allowed": True,
                "spend_allowed": False,
                "live_no_spend_write_verified": True,
                "live_scope_ref": scope_ref,
                "live_organization_id": org_id,
                "execution_adapter_verified": True,
                "execution_adapter_scope_ref": scope_ref,
                "execution_adapter_organization_id": org_id,
            },
            verified_at=pilots._now(),
            version=1,
        )
    )
    await session.flush()
    return owner, user, campaign, ad_set, creative, ad, pilot


@pytest.mark.asyncio
async def test_live_plan_blocks_missing_page_binding_but_not_live_legal_or_launch(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, _, campaign, _, _, _, pilot = await _fixture(session, monkeypatch)
        result = await live_plan.evaluate_live_plan(
            session, owner, campaign.id, pilot.id
        )
        assert result["plan_compilable"] is False
        assert result["provider_gate"] is True
        assert result["execution_adapter_gate"] is True
        assert result["budget_gate"] is True
        assert result["stop_loss_gate"] is True
        assert result["live_legal_gate"] is False
        assert result["launch_gate"] is False
        assert result["blocked_reasons"] == ["meta-page-binding-missing"]
        assert result["provider_call_executed"] is False
        assert result["spend_executed"] is False
        await session.rollback()


@pytest.mark.asyncio
async def test_live_plan_persists_digest_and_detects_post_plan_mutation(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, _, campaign, _, creative, _, pilot = await _fixture(session, monkeypatch)
        prepared = await live_plan.prepare_live_plan(
            session,
            owner,
            campaign.id,
            pilot.id,
            creative_identity_ref=PAGE_REF,
        )
        assert prepared["plan_compilable"] is True
        assert prepared["plan_persisted"] is True
        assert prepared["live_legal_gate"] is False
        assert prepared["launch_gate"] is False
        assert prepared["live_execution_authorized"] is False
        assert prepared["provider_call_executed"] is False
        assert prepared["spend_executed"] is False
        assert prepared["automatic_execution_allowed"] is False

        valid = await live_plan.validate_prepared_plan(session, owner, campaign.id)
        assert valid["plan_valid"] is True
        creative.body = "Changed after plan"
        creative.version += 1
        await session.flush()
        invalid = await live_plan.validate_prepared_plan(session, owner, campaign.id)
        assert invalid["plan_valid"] is False
        assert invalid["plan_digest_matches"] is False
        await session.rollback()


@pytest.mark.asyncio
async def test_live_plan_blocks_wrong_objective_provider_and_budget(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, _, campaign, ad_set, _, _, pilot = await _fixture(session, monkeypatch)
        campaign.objective = "sales"
        ad_set.provider = "tiktok"
        campaign.total_budget_minor = 2500
        await session.flush()
        result = await live_plan.evaluate_live_plan(
            session,
            owner,
            campaign.id,
            pilot.id,
            creative_identity_ref=PAGE_REF,
        )
        assert result["plan_compilable"] is False
        assert "meta-live-objective-not-supported" in result["blocked_reasons"]
        assert "campaign-provider-not-meta" in result["blocked_reasons"]
        assert "campaign-budget-exceeds-pilot-cap" in result["blocked_reasons"]
        await session.rollback()


@pytest.mark.asyncio
async def test_config_change_invalidates_owner_approval_and_prepared_plan(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, user, campaign, _, _, _, pilot = await _fixture(session, monkeypatch)
        await live_plan.prepare_live_plan(
            session,
            owner,
            campaign.id,
            pilot.id,
            creative_identity_ref=PAGE_REF,
        )
        assert "live_execution_plan" in campaign.campaign_metadata
        await paid.add_creative(
            session,
            user,
            campaign.id,
            {
                "name": "Post approval creative",
                "headline": "Changed",
                "destination_url": "https://example.invalid/new",
            },
        )
        assert campaign.approval_status == "pending_owner"
        assert campaign.approved_by_id is None
        assert campaign.approved_at is None
        assert "live_execution_plan" not in campaign.campaign_metadata
        await session.rollback()


@pytest.mark.asyncio
async def test_adset_aggregate_budget_cap_and_secret_json_are_fail_closed(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, user, campaign, _, _, _, _ = await _fixture(session, monkeypatch)
        with pytest.raises(
            paid.GrowthPaidCampaignError,
            match="adset-aggregate-daily-cap-exceeds-campaign",
        ):
            await paid.add_ad_set(
                session,
                user,
                campaign.id,
                {
                    "name": "Overflow",
                    "provider": "instagram",
                    "audience": {"countries": ["AE"]},
                    "placements": ["feed"],
                    "daily_budget_cap_minor": 1,
                },
            )
        with pytest.raises(
            paid.GrowthPaidCampaignError, match="credential-material-forbidden"
        ):
            paid._safe_campaign_json({"access_token": "must-not-store"}, "metadata")
        with pytest.raises(
            paid.GrowthPaidCampaignError, match="credential-material-forbidden"
        ):
            paid._safe_campaign_json({"nested": {"api_key": "x"}}, "audience")
        assert owner.role == "Super Owner"
        await session.rollback()


def test_live_plan_page_reference_and_non_owner_fail_closed() -> None:
    with pytest.raises(
        live_plan.GrowthPaidLivePlanError, match="meta-page-reference-invalid"
    ):
        live_plan._safe_page_ref("123456")
    assert live_plan._safe_page_ref(PAGE_REF) == PAGE_REF
