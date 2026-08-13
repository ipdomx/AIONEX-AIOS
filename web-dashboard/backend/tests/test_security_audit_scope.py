from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user
from app.db.base import SessionLocal
from app.db.models import AuditEvent, Organization


def _actor(*, role: str, organization_id: str) -> UserRecord:
    return UserRecord(
        id=f"audit-actor-{uuid4().hex}",
        email="audit-actor@example.invalid",
        name="Audit Scope Actor",
        role=role,
        password_hash="unused",
        organization_id=organization_id,
        organization_name="Audit Scope Organization",
        organization_plan="enterprise",
        permissions=["audit:read"],
    )


@pytest.mark.asyncio
async def test_security_audit_is_global_only_for_super_owner() -> None:
    suffix = uuid4().hex[:12]
    org_a = Organization(
        id=f"audit-org-a-{suffix}",
        name="Audit Organization A",
        slug=f"audit-organization-a-{suffix}",
        plan="enterprise",
        status="active",
    )
    org_b = Organization(
        id=f"audit-org-b-{suffix}",
        name="Audit Organization B",
        slug=f"audit-organization-b-{suffix}",
        plan="business",
        status="active",
    )
    event_a = AuditEvent(
        organization_id=org_a.id,
        action=f"rc.audit.a.{suffix}",
        resource_type="test",
        resource_id=f"resource-a-{suffix}",
        details={},
    )
    event_b = AuditEvent(
        organization_id=org_b.id,
        action=f"rc.audit.b.{suffix}",
        resource_type="test",
        resource_id=f"resource-b-{suffix}",
        details={},
    )
    global_event = AuditEvent(
        organization_id=None,
        action=f"rc.audit.global.{suffix}",
        resource_type="test",
        resource_id=f"resource-global-{suffix}",
        details={},
    )

    async with SessionLocal() as session:
        session.add_all([org_a, org_b])
        await session.flush()
        session.add_all([event_a, event_b, global_event])
        await session.commit()

    actor_holder = {"actor": _actor(role="Super Owner", organization_id=org_a.id)}
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor_holder["actor"]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/security/audit",
                params={"limit": 500},
            )
            assert response.status_code == 200, response.text
            actions = {item["action"] for item in response.json()}
            assert event_a.action in actions
            assert event_b.action in actions
            assert global_event.action in actions

            actor_holder["actor"] = _actor(
                role="Manager", organization_id=org_a.id
            )
            response = await client.get(
                "/api/v1/security/audit",
                params={"limit": 500},
            )
            assert response.status_code == 200, response.text
            actions = {item["action"] for item in response.json()}
            assert event_a.action in actions
            assert event_b.action not in actions
            assert global_event.action not in actions
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(AuditEvent).where(
                    AuditEvent.action.in_(
                        [event_a.action, event_b.action, global_event.action]
                    )
                )
            )
            await session.execute(
                delete(Organization).where(Organization.id.in_([org_a.id, org_b.id]))
            )
            await session.commit()
