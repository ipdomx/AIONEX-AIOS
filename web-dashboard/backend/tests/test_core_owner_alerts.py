"""Core owner project and lifecycle alert contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    BillingAccount,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    Organization,
    Report,
    Role,
    User,
    Workspace,
)
from app.services import lifecycle_alerts
from app.api.v1.endpoints import projects as projects_endpoint


def actor(user: User, organization: Organization) -> UserRecord:
    return UserRecord(
        id=user.id,
        email=user.email,
        name=user.name,
        role="Member",
        password_hash=user.password_hash,
        organization_id=organization.id,
        organization_name=organization.name,
        organization_plan=organization.plan,
        permissions=["projects:read", "projects:write", "billing:read"],
    )


async def create_identity(suffix: str):
    customer = Organization(
        name=f"Owner Alert Customer {suffix}",
        slug=f"owner-alert-customer-{suffix}",
        plan="business",
        status="active",
    )
    platform = Organization(
        name=f"Owner Alert Platform {suffix}",
        slug=f"owner-alert-platform-{suffix}",
        plan="enterprise",
        status="active",
    )
    async with SessionLocal() as session:
        session.add_all([customer, platform])
        await session.flush()
        member_role = Role(
            organization_id=customer.id,
            name=f"Alert Member {suffix}",
            status="active",
        )
        owner_role = Role(
            organization_id=platform.id,
            name="Super Owner",
            status="active",
        )
        session.add_all([member_role, owner_role])
        await session.flush()
        member = User(
            organization_id=customer.id,
            role_id=member_role.id,
            email=f"alert-member-{suffix}@example.com",
            name="Alert Customer",
            password_hash=pwd_context.hash(f"AlertMember!{suffix}Aa1"),
            status="active",
        )
        owner = User(
            organization_id=platform.id,
            role_id=owner_role.id,
            email=f"alert-owner-{suffix}@example.com",
            name="Alert Super Owner",
            password_hash=pwd_context.hash(f"AlertOwner!{suffix}Aa1"),
            status="active",
        )
        workspace = Workspace(
            organization_id=customer.id,
            name="Alert Workspace",
            slug=f"alert-workspace-{suffix}",
            status="active",
        )
        account = BillingAccount(
            organization_id=customer.id,
            status="active",
            licensed_seats=1,
            limits={},
            entitlements=[],
        )
        session.add_all([member, owner, workspace, account])
        await session.commit()
        return customer, platform, member, owner, workspace, account


async def cleanup(customer_id: str, platform_id: str, correlations: list[str]) -> None:
    async with SessionLocal() as session:
        if correlations:
            await session.execute(
                delete(Notification).where(Notification.correlation_id.in_(correlations))
            )
        for organization_id in (customer_id, platform_id):
            stored = await session.get(Organization, organization_id)
            if stored is not None:
                await session.delete(stored)
        await session.commit()


@pytest.mark.asyncio
async def test_every_project_creation_notifies_platform_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    customer, platform, member, owner, workspace, _ = await create_identity(suffix)
    project_id: str | None = None
    monkeypatch.setattr(projects_endpoint, "owner_alert_channels", lambda: ["in_app"])
    holder = {"actor": actor(member, customer)}
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: holder["actor"]
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/projects",
                json={
                    "name": f"Any Project Type {suffix}",
                    "description": "A universal project-start notification contract.",
                    "workspace_id": workspace.id,
                    "tags": ["arbitrary-project-type"],
                },
            )
            assert response.status_code == 201, response.text
            project_id = response.json()["id"]

        async with SessionLocal() as session:
            alert = await session.scalar(
                select(Notification).where(
                    Notification.recipient_id == owner.id,
                    Notification.event_key == "project.started",
                    Notification.source_id == project_id,
                )
            )
            assert alert is not None
            assert alert.payload["user_id"] == member.id
            assert alert.payload["project_id"] == project_id
            assert alert.payload["tags"] == ["arbitrary-project-type"]
            channels = set(
                (
                    await session.scalars(
                        select(NotificationDelivery.channel).where(
                            NotificationDelivery.notification_id == alert.id
                        )
                    )
                ).all()
            )
            assert channels == {"in_app"}
    finally:
        await cleanup(
            customer.id,
            platform.id,
            [project_id] if project_id else [],
        )


@pytest.mark.asyncio
async def test_subscription_and_storage_alerts_are_deduped_and_force_owner_external_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    customer, platform, member, owner, _, account = await create_identity(suffix)
    correlation = account.id
    monkeypatch.setattr(
        lifecycle_alerts, "owner_alert_channels", lambda: ["in_app", "email"]
    )
    try:
        async with SessionLocal() as session:
            locked_account = await session.get(BillingAccount, account.id)
            assert locked_account is not None
            locked_account.current_period_end = datetime.now(UTC) + timedelta(days=6)
            locked_account.limits = {"storage_bytes": 100}
            session.add(
                Report(
                    organization_id=customer.id,
                    name="Storage alert evidence",
                    type="usage",
                    status="ready",
                    content={},
                    size_bytes=85,
                )
            )
            session.add(
                NotificationPreference(
                    organization_id=platform.id,
                    user_id=owner.id,
                    category="*",
                    enabled=False,
                    channels=["in_app"],
                    minimum_severity="critical",
                )
            )
            await session.flush()

            first = await lifecycle_alerts.run_account_lifecycle_alerts(session)
            second = await lifecycle_alerts.run_account_lifecycle_alerts(session)
            assert first
            assert second
            await session.commit()

        async with SessionLocal() as session:
            user_events = list(
                (
                    await session.scalars(
                        select(Notification).where(
                            Notification.recipient_id == member.id,
                            Notification.correlation_id == correlation,
                        )
                    )
                ).all()
            )
            assert {item.event_key for item in user_events} == {
                "billing.subscription.expiring_7d",
                "storage.capacity.near_80",
            }
            assert all(item.audience == "organization" for item in user_events)
            for item in user_events:
                channels = set(
                    (
                        await session.scalars(
                            select(NotificationDelivery.channel).where(
                                NotificationDelivery.notification_id == item.id
                            )
                        )
                    ).all()
                )
                assert channels == {"in_app"}

            owner_events = list(
                (
                    await session.scalars(
                        select(Notification).where(
                            Notification.recipient_id == owner.id,
                            Notification.correlation_id == correlation,
                        )
                    )
                ).all()
            )
            assert {item.event_key for item in owner_events} == {
                "billing.subscription.expiring_7d",
                "storage.capacity.near_80",
            }
            for item in owner_events:
                channels = set(
                    (
                        await session.scalars(
                            select(NotificationDelivery.channel).where(
                                NotificationDelivery.notification_id == item.id
                            )
                        )
                    ).all()
                )
                assert channels == {"in_app", "email"}

            for recipient_id in (member.id, owner.id):
                for event_key in (
                    "billing.subscription.expiring_7d",
                    "storage.capacity.near_80",
                ):
                    count = int(
                        await session.scalar(
                            select(func.count(Notification.id)).where(
                                Notification.recipient_id == recipient_id,
                                Notification.correlation_id == correlation,
                                Notification.event_key == event_key,
                            )
                        )
                        or 0
                    )
                    assert count == 1
    finally:
        await cleanup(customer.id, platform.id, [correlation])
