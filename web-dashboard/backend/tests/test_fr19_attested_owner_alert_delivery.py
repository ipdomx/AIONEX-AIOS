"""FR19: Owner-attested finance alerts persist privately to the real Owner audience.

Uses the disposable CI PostgreSQL database only; no provider HTTP, paid keys,
external mail/Telegram/Push or production notification delivery.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.db.base import SessionLocal
from app.db.models import (
    AIProvider,
    AuditEvent,
    Notification,
    NotificationDelivery,
    Organization,
    OwnerControlRecord,
    Role,
    User,
)
from app.services import provider_credit_alerts as credit


@pytest.mark.asyncio
async def test_attested_credit_persists_deduplicated_private_owner_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown funded balance still warns the Owner when billing fails."""
    if os.getenv("ENVIRONMENT", "").strip().lower() != "test":
        pytest.skip("Runs only against disposable test databases")
    database_url = os.getenv("DATABASE_URL", "").strip()
    try:
        url = make_url(database_url)
    except (TypeError, ValueError, ArgumentError):
        pytest.skip("Requires a disposable PostgreSQL test database")
    if (
        url.drivername != "postgresql+asyncpg"
        or "test" not in (url.database or "").lower()
    ):
        pytest.skip("Requires a disposable PostgreSQL test database")

    oid, tid = str(uuid4()), str(uuid4())
    owner_role, member_role = str(uuid4()), str(uuid4())
    owner_id, member_id, provider_id = str(uuid4()), str(uuid4()), str(uuid4())

    # No external channel may be dispatched by this integration test.
    monkeypatch.setattr(credit, "owner_alert_channels", lambda: ["in_app"])

    try:
        async with SessionLocal() as session:
            session.add_all([
                Organization(
                    id=oid, name="FR19 Disposable Owner",
                    slug=f"fr19-attested-owner-{oid[:10]}",
                    plan="enterprise", status="active",
                ),
                Organization(
                    id=tid, name="FR19 Disposable Tenant",
                    slug=f"fr19-attested-tenant-{tid[:10]}",
                    plan="enterprise", status="active",
                ),
            ])
            await session.flush()
            session.add_all([
                Role(
                    id=owner_role, organization_id=oid, name="Super Owner",
                    system=True, status="active",
                ),
                Role(
                    id=member_role, organization_id=tid, name="Member",
                    system=False, status="active",
                ),
            ])
            await session.flush()
            session.add_all([
                User(
                    id=owner_id, organization_id=oid, role_id=owner_role,
                    email=f"fr19-owner-{owner_id[:10]}@example.invalid",
                    name="FR19 Test Owner", password_hash="unused", status="active",
                ),
                User(
                    id=member_id, organization_id=tid, role_id=member_role,
                    email=f"fr19-member-{member_id[:10]}@example.invalid",
                    name="FR19 Test Member", password_hash="unused", status="active",
                ),
                AIProvider(
                    id=provider_id, organization_id=tid,
                    name="No-network synthetic provider", type="synthetic",
                    status="connected", base_url=None,
                    config={"enabled": True, "runtime_spend_microusd": 0},
                ),
            ])
            await session.commit()

        async with SessionLocal() as session:
            await credit.attest_provider_funded(
                session, provider_id=provider_id, enabled=True
            )
            await session.commit()

        async with SessionLocal() as session:
            snapshot = await credit.provider_credit_snapshot(
                session, provider_id=provider_id
            )
            assert snapshot.funding_mode == "owner_attested"
            assert snapshot.public()["remaining_usd"] is None
            assert snapshot.public()["consumed_since_topup_usd"] is None

            await credit._notify_predictive_monitoring_gap(session, snapshot)
            await credit.notify_provider_billing_failure(
                session, provider_id=provider_id,
                failure_code="billing_required", critical=True,
            )
            await credit.notify_provider_billing_failure(
                session, provider_id=provider_id,
                failure_code="quota_limited", critical=False,
            )
            await session.commit()

        async with SessionLocal() as session:
            before = list((await session.scalars(
                select(Notification).where(Notification.source_id == provider_id)
            )).all())
            assert len([n for n in before if n.recipient_id == owner_id]) == 3
            original_ids = {note.id for note in before}

            snapshot = await credit.provider_credit_snapshot(
                session, provider_id=provider_id
            )
            await credit._notify_predictive_monitoring_gap(session, snapshot)
            await credit.notify_provider_billing_failure(
                session, provider_id=provider_id,
                failure_code="billing_required", critical=True,
            )
            await session.commit()

        async with SessionLocal() as session:
            after = list((await session.scalars(
                select(Notification).where(Notification.source_id == provider_id)
            )).all())
            assert {note.id for note in after} == original_ids
            assert all(note.recipient_id != member_id for note in after)
            expected = {
                "project_ai.provider_credit.predictive_monitoring_required":
                    ("warning", "billing"),
                "project_ai.provider_billing.action_required":
                    ("critical", "billing"),
                "project_ai.provider_quota.limited": ("warning", "quota"),
            }
            owner_notes = [n for n in after if n.recipient_id == owner_id]
            assert {n.event_key for n in owner_notes} == set(expected)
            for note in owner_notes:
                assert note.organization_id == oid
                assert note.audience == "platform_owner"
                assert (note.severity, note.category) == expected[note.event_key]
                assert note.dedupe_key is not None
                assert note.dedupe_key.endswith(owner_id)
                assert "encrypted_api_key" not in note.payload
                assert "funded_microusd" not in note.payload
                if note.event_key.endswith("predictive_monitoring_required"):
                    assert note.payload["funded_usd"] is None
                    assert note.payload["remaining_usd"] is None
                    assert note.payload["consumed_since_topup_usd"] is None
                else:
                    assert "funded_usd" not in note.payload
                    assert "remaining_usd" not in note.payload
                    assert "consumed_since_topup_usd" not in note.payload
    finally:
        # Remove only this test's randomly generated entities. The suite may
        # have its own other Super Owner fixture: never delete those users.
        async with SessionLocal() as session:
            owned_notification_ids = select(Notification.id).where(
                Notification.source_id == provider_id
            )
            await session.execute(delete(NotificationDelivery).where(
                NotificationDelivery.notification_id.in_(owned_notification_ids)
            ))
            # Global Super Owner notifications may target other test orgs.
            # Remove only audit records belonging to this synthetic provider.
            await session.execute(delete(AuditEvent).where(
                AuditEvent.resource_type == "notification",
                AuditEvent.resource_id.in_(owned_notification_ids),
            ))
            await session.execute(delete(Notification).where(
                Notification.source_id == provider_id
            ))
            await session.execute(delete(AuditEvent).where(
                AuditEvent.organization_id.in_([oid, tid])
            ))
            await session.execute(delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == credit.PROVIDER_FINANCE_DOMAIN,
                OwnerControlRecord.resource_id == provider_id,
            ))
            await session.execute(delete(AIProvider).where(AIProvider.id == provider_id))
            await session.execute(delete(User).where(User.id.in_([owner_id, member_id])))
            await session.execute(delete(Role).where(Role.id.in_([owner_role, member_role])))
            await session.execute(delete(Organization).where(
                Organization.id.in_([oid, tid])
            ))
            await session.commit()
