from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import AuditEvent, Organization, User
from app.services import growth_paid_campaigns as paid


def actor(org_id: str, user_id: str, role: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.invalid",
        name=role,
        role=role,
        password_hash="unused",
        organization_id=org_id,
        organization_name="Owner Approval Test",
        organization_plan="test",
        permissions=["*"] if role == "Super Owner" else [],
        status="active",
        auth_version=1,
    )


@pytest.mark.asyncio
async def test_user_budget_is_advisory_only_and_super_owner_is_only_approver(
    monkeypatch,
):
    suffix = uuid4().hex[:10]
    org_id = f"approval-org-{suffix}"
    user_id = f"approval-user-{suffix}"
    owner_id = f"approval-owner-{suffix}"
    user = actor(org_id, user_id, "User")
    owner = actor(org_id, owner_id, "Super Owner")

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(paid.growth_access, "effective_access", allow)

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="Owner Approval Test",
                slug=f"approval-{suffix}",
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
                "name": "User Chosen Budget",
                "objective": "sales",
                "currency": "EUR",
                "total_budget_minor": 250000,
                "daily_budget_cap_minor": 50000,
                "stop_loss_policy": {"max_cpa_minor": 15000, "min_roas": 1.5},
            },
        )
        adset = await paid.add_ad_set(
            session,
            user,
            campaign.id,
            {
                "name": "AE",
                "provider": "instagram",
                "daily_budget_cap_minor": 50000,
            },
        )
        creative = await paid.add_creative(
            session,
            user,
            campaign.id,
            {"name": "Creative", "approved": True},
        )
        await paid.add_ad(
            session,
            user,
            campaign.id,
            {"name": "Ad", "ad_set_id": adset.id, "creative_id": creative.id},
        )

        _, decision = await paid.simulate_launch(session, user, campaign.id, days=3)
        assessment = decision.metrics["budget_assessment"]
        assert assessment["advisory_only"] is True
        assert assessment["budget_mutated"] is False
        assert assessment["owner_approval_required"] is True
        assert campaign.total_budget_minor == 250000
        assert campaign.daily_budget_cap_minor == 50000
        assert campaign.approval_status == "pending_owner"
        assert campaign.real_spend_allowed is False

        with pytest.raises(
            paid.GrowthPaidCampaignError, match="super-owner-approval-required"
        ):
            await paid.approve_campaign(session, user, campaign.id)

        approved = await paid.approve_campaign(session, owner, campaign.id)
        assert approved.approval_status == "approved"
        assert approved.approved_by_id == owner.id
        assert approved.total_budget_minor == 250000
        assert approved.daily_budget_cap_minor == 50000
        assert approved.real_spend_allowed is False
        assert approved.live_provider_call is False
        assert approved.live_campaign_mutation is False
        assert approved.automatic_budget_increase_allowed is False

        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "growth.paid_campaign.owner_approved",
                AuditEvent.resource_id == campaign.id,
            )
        )
        assert audit is not None
        assert audit.user_id == owner.id
        assert audit.details["user_budget_preserved"] is True
        assert audit.details["automatic_execution_allowed"] is False
        await session.rollback()
