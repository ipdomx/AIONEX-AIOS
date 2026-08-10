"""Authenticated Owner Operations smoke covering the visible CRUD lifecycle."""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.auth import pwd_context
from app.db.base import SessionLocal
from app.db.models import Organization, Project, Role, User, uuid_str
from app.db.redis import close_redis, init_redis
from app.db.seed import seed
from main import app


@pytest.mark.asyncio
async def test_owner_login_and_protected_entity_crud_e2e(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    suffix = uuid4().hex[:12]
    owner_password = f"OwnerE2E!{suffix}Aa1"
    organization_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None

    monkeypatch.setenv("AIOS_CONTROL_HOST", "owner.test")
    async with SessionLocal() as session:
        owner = await session.scalar(
            select(User)
            .join(Role, Role.id == User.role_id)
            .where(Role.name == "Super Owner", User.deleted_at.is_(None))
            .limit(1)
        )
        assert owner is not None
        owner.password_hash = pwd_context.hash(owner_password)
        owner.status = "active"
        await session.commit()
        owner_email = owner.email

    await init_redis()
    try:
        headers = {
            "x-aios-auth-channel": "private",
            "Origin": "https://owner.test",
            "Sec-Fetch-Site": "same-origin",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                data={"username": owner_email, "password": owner_password},
            )
            assert login.status_code == 200, login.text
            assert client.cookies.get("aionex_access")
            assert client.cookies.get("aionex_refresh")

            created_org = await client.post(
                "/api/v1/owner/operations",
                json={
                    "entity": "organization",
                    "operation": "create",
                    "payload": {
                        "name": f"Owner E2E {suffix}",
                        "plan": "enterprise",
                    },
                },
            )
            assert created_org.status_code == 200, created_org.text
            async with SessionLocal() as session:
                organization = await session.scalar(
                    select(Organization).where(Organization.name == f"Owner E2E {suffix}")
                )
                assert organization is not None
                organization_id = organization.id
                role = Role(
                    id=uuid_str(),
                    organization_id=organization_id,
                    name=f"Owner E2E Operator {suffix}",
                    status="active",
                )
                session.add(role)
                await session.commit()
                role_id = role.id

            created_user = await client.post(
                "/api/v1/owner/operations",
                json={
                    "entity": "user",
                    "operation": "create",
                    "payload": {
                        "name": "Owner E2E User",
                        "email": f"owner-e2e-{suffix}@example.com",
                        "password": f"OwnerE2EUser!{suffix}Aa1",
                        "role_id": role_id,
                        "organization_id": organization_id,
                    },
                },
            )
            assert created_user.status_code == 200, created_user.text
            async with SessionLocal() as session:
                created_user_row = await session.scalar(
                    select(User).where(User.email == f"owner-e2e-{suffix}@example.com")
                )
                assert created_user_row is not None
                user_id = created_user_row.id

            created_project = await client.post(
                "/api/v1/owner/operations",
                json={
                    "entity": "project",
                    "operation": "create",
                    "payload": {
                        "name": f"Owner E2E Project {suffix}",
                        "organization_id": organization_id,
                        "priority": "medium",
                    },
                },
            )
            assert created_project.status_code == 200, created_project.text
            async with SessionLocal() as session:
                created_project_row = await session.scalar(
                    select(Project).where(Project.name == f"Owner E2E Project {suffix}")
                )
                assert created_project_row is not None
                project_id = created_project_row.id

            for operation, payload in (
                ("update", {"name": f"Owner E2E Project Updated {suffix}", "progress": 25}),
                ("suspend", {}),
                ("restore", {}),
                ("delete", {}),
            ):
                response = await client.post(
                    "/api/v1/owner/operations",
                    json={
                        "entity": "project",
                        "operation": operation,
                        "id": project_id,
                        "payload": payload,
                    },
                )
                assert response.status_code == 200, (operation, response.text)

            for operation in ("suspend", "restore", "delete"):
                response = await client.post(
                    "/api/v1/owner/operations",
                    json={
                        "entity": "user",
                        "operation": operation,
                        "id": user_id,
                        "payload": {},
                    },
                )
                assert response.status_code == 200, (operation, response.text)

            for operation in ("suspend", "restore", "delete"):
                response = await client.post(
                    "/api/v1/owner/operations",
                    json={
                        "entity": "organization",
                        "operation": operation,
                        "id": organization_id,
                        "payload": {},
                    },
                )
                assert response.status_code == 200, (operation, response.text)

            async with SessionLocal() as session:
                stored_project = await session.get(Project, project_id)
                stored_user = await session.get(User, user_id)
                stored_org = await session.get(Organization, organization_id)
                assert stored_project is not None and stored_project.status == "deleted"
                assert stored_user is not None and stored_user.deleted_at is not None
                assert stored_org is not None and stored_org.status == "inactive"
    finally:
        await close_redis()
        if organization_id:
            async with SessionLocal() as session:
                organization = await session.get(Organization, organization_id)
                if organization is not None:
                    await session.delete(organization)
                    await session.commit()
