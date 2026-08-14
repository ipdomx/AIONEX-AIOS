from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    GrowthLeadConsent,
    GrowthLeadProvenance,
    GrowthLeadRecord,
    GrowthLeadSuppression,
    Organization,
    User,
)
from app.services import growth_lead_intelligence as leads


def _actor(org_id: str, user_id: str, email: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name="GS06 Test User",
        role="User",
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS06 Test",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )


@pytest.mark.asyncio
async def test_lead_dedupe_consent_suppression_and_retention(monkeypatch) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs06-org-{suffix}"
    user_id = f"gs06-user-{suffix}"
    email = f"gs06-{suffix}@example.invalid"

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(leads.growth_access, "effective_access", allow)
    actor = _actor(org_id, user_id, email)

    async with SessionLocal() as session:
        try:
            session.add(
                Organization(
                    id=org_id,
                    name="GS06 Test",
                    slug=f"gs06-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            session.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=email,
                    name="GS06 Test User",
                    password_hash="unused",
                    status="active",
                    auth_version=1,
                )
            )
            await session.commit()

            first, created = await leads.upsert_lead(
                session,
                actor,
                {
                    "display_name": "Lead One",
                    "email": "Person@Example.com",
                    "phone": "+971 50 123 4567",
                    "company_name": "Example LLC",
                    "country_code": "AE",
                    "source_type": "first_party_form",
                    "collection_method": "consented_form",
                    "source_ref": "form:landing-page",
                    "retention_until": datetime.now(timezone.utc) + timedelta(days=30),
                },
            )
            assert created is True
            second, created_again = await leads.upsert_lead(
                session,
                actor,
                {
                    "display_name": "Same person",
                    "email": "person@example.com",
                    "phone": "+971501234567",
                    "company_name": "Example LLC",
                    "source_type": "crm_import",
                    "collection_method": "owner_authorized_import",
                    "source_ref": "crm:batch-1",
                },
            )
            assert created_again is False
            assert first.id == second.id
            await session.commit()

            provenance = (
                await session.scalars(
                    select(GrowthLeadProvenance).where(
                        GrowthLeadProvenance.lead_id == first.id
                    )
                )
            ).all()
            assert len(provenance) == 2

            before = await leads.eligibility(
                session, actor, first.id, purpose="marketing", channel="email"
            )
            assert before["eligible"] is False
            assert "no-active-lawful-basis" in before["reason_codes"]

            consent = await leads.set_consent(
                session,
                actor,
                first.id,
                {
                    "purpose": "marketing",
                    "lawful_basis": "consent",
                    "evidence": {"event": "checkbox", "form_id": "landing-page"},
                },
            )
            allowed = await leads.eligibility(
                session, actor, first.id, purpose="marketing", channel="email"
            )
            assert allowed["eligible"] is True
            assert allowed["lawful_bases"] == ["consent"]
            assert allowed["outbound_outreach_allowed"] is False
            assert allowed["live_audience_upload_allowed"] is False

            await leads.suppress(session, actor, first.id, "email", "user-opt-out")
            blocked = await leads.eligibility(
                session, actor, first.id, purpose="marketing", channel="email"
            )
            assert blocked["eligible"] is False
            assert "suppressed" in blocked["reason_codes"]

            await leads.withdraw_consent(session, actor, consent.id)
            withdrawn = await leads.eligibility(
                session, actor, first.id, purpose="marketing", channel="phone"
            )
            assert withdrawn["eligible"] is False
            assert "no-active-lawful-basis" in withdrawn["reason_codes"]

            row = await session.get(GrowthLeadRecord, first.id)
            assert row is not None
            row.retention_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            expired = await leads.eligibility(
                session, actor, first.id, purpose="sales", channel="phone"
            )
            assert expired["eligible"] is False
            assert "retention-expired" in expired["reason_codes"]
            await session.commit()
        finally:
            await session.rollback()
            await session.execute(
                delete(AuditEvent).where(AuditEvent.organization_id == org_id)
            )
            await session.execute(
                delete(GrowthLeadSuppression).where(
                    GrowthLeadSuppression.organization_id == org_id
                )
            )
            await session.execute(
                delete(GrowthLeadConsent).where(
                    GrowthLeadConsent.organization_id == org_id
                )
            )
            await session.execute(
                delete(GrowthLeadProvenance).where(
                    GrowthLeadProvenance.organization_id == org_id
                )
            )
            await session.execute(
                delete(GrowthLeadRecord).where(
                    GrowthLeadRecord.organization_id == org_id
                )
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.commit()


def test_rejects_unauthorized_source_and_missing_consent_evidence() -> None:
    with pytest.raises(leads.GrowthLeadError, match="unsupported-source-type"):
        leads._validate_source("scraped_private_profile", "manual_verified_entry")
    with pytest.raises(
        leads.GrowthLeadError, match="public-business-source-requires-lawful-method"
    ):
        leads._validate_source("public_business_contact", "manual_verified_entry")
    assert leads.UNAUTHORIZED_SCRAPING_ALLOWED is False
    assert leads.OUTBOUND_OUTREACH_ALLOWED is False
    assert leads.LIVE_AUDIENCE_UPLOAD_ALLOWED is False
    assert leads.LIVE_PROVIDER_CALL_ALLOWED is False


@pytest.mark.asyncio
async def test_consent_requires_evidence(monkeypatch) -> None:
    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(leads.growth_access, "effective_access", allow)
    actor = _actor("org", "user", "u@example.invalid")
    fake = SimpleNamespace(id="lead", organization_id="org")

    class FakeSession:
        async def scalar(self, _stmt):
            return fake

    with pytest.raises(leads.GrowthLeadError, match="consent-evidence-required"):
        await leads.set_consent(
            FakeSession(),
            actor,
            "lead",
            {"purpose": "marketing", "lawful_basis": "consent", "evidence": {}},
        )
