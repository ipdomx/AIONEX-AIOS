from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import BillingAccount, Organization, User
from app.services import growth_full_system_acceptance as gs11


def _actor(org_id: str, user_id: str, email: str, role: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name=f"GS11 {role}",
        role=role,
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS11 Synthetic",
        organization_plan="synthetic",
        permissions=[],
        status="active",
        auth_version=1,
    )


@pytest.mark.asyncio
async def test_full_system_synthetic_acceptance_and_transaction_cleanup() -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs11-org-{suffix}"
    owner_id = f"gs11-owner-{suffix}"
    user_id = f"gs11-user-{suffix}"
    other_org_id = f"gs11-other-org-{suffix}"
    other_user_id = f"gs11-other-user-{suffix}"

    owner = _actor(org_id, owner_id, f"owner-{suffix}@example.invalid", "Super Owner")
    actor = _actor(org_id, user_id, f"user-{suffix}@example.invalid", "Admin")
    isolation_actor = _actor(
        other_org_id,
        other_user_id,
        f"other-{suffix}@example.invalid",
        "Super Owner",
    )

    async with SessionLocal() as session:
        session.add_all(
            [
                Organization(
                    id=org_id,
                    name="GS11 Synthetic",
                    slug=f"gs11-{suffix}",
                    plan="synthetic",
                    status="active",
                ),
                Organization(
                    id=other_org_id,
                    name="GS11 Isolation",
                    slug=f"gs11-other-{suffix}",
                    plan="synthetic",
                    status="active",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                User(
                    id=owner_id,
                    organization_id=org_id,
                    email=owner.email,
                    name=owner.name,
                    password_hash="unused",
                    status="active",
                    auth_version=1,
                ),
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=actor.email,
                    name=actor.name,
                    password_hash="unused",
                    status="active",
                    auth_version=1,
                ),
                User(
                    id=other_user_id,
                    organization_id=other_org_id,
                    email=isolation_actor.email,
                    name=isolation_actor.name,
                    password_hash="unused",
                    status="active",
                    auth_version=1,
                ),
                BillingAccount(
                    organization_id=org_id,
                    status="active",
                    licensed_seats=2,
                    limits={},
                    entitlements=[],
                    provider_customers={},
                ),
                BillingAccount(
                    organization_id=other_org_id,
                    status="active",
                    licensed_seats=1,
                    limits={},
                    entitlements=["growth.campaign.simulation"],
                    provider_customers={},
                ),
            ]
        )
        await session.flush()

        result = await gs11.run_synthetic_acceptance(
            session,
            owner=owner,
            actor=actor,
            isolation_actor=isolation_actor,
            seed=suffix,
        )

        assert result["status"] == "GS11_SYNTHETIC_ACCEPTANCE_OK"
        assert result["capabilities_granted"] == result["capabilities_revoked"]
        assert result["tenant_isolation_enforced"] is True
        assert result["campaign_simulation_deterministic"] is True
        assert result["content_publish_simulated"] is True
        assert result["paid_campaign_simulation_deterministic"] is True
        assert result["lead_eligible"] is True
        assert result["inbox_event_simulated"] is True
        assert result["failure_learning_action"] == "iterate"
        assert result["successful_replay_action"] == "replay_candidate"
        assert result["successful_replay_eligible"] is True
        assert result["report_formats"] == ["csv", "json", "pdf", "xlsx"]
        assert result["report_aggregate_only"] is True
        assert result["owner_revocation_enforced"] is True
        for key in (
            "quick_reply_external_send_allowed",
            "auto_replay_allowed",
            "auto_optimization_allowed",
            "integration_external_delivery_allowed",
            "team_routing_mutation_applied",
            "raw_credentials_exported",
            "lead_contact_pii_exported",
            "live_provider_call",
            "live_publish_allowed",
            "external_send_allowed",
            "live_audience_upload_allowed",
            "live_campaign_mutation",
            "real_spend_allowed",
            "automatic_execution_allowed",
        ):
            assert result[key] is False

        await session.rollback()

    async with SessionLocal() as verification:
        assert (
            await verification.scalar(
                select(Organization.id).where(Organization.id == org_id)
            )
            is None
        )
        assert (
            await verification.scalar(
                select(Organization.id).where(Organization.id == other_org_id)
            )
            is None
        )
