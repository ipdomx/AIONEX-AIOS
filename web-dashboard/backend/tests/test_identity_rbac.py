"""Batch-one identity, organizations, and RBAC verification tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from app.db.seed import seed


@pytest.mark.asyncio
async def test_owner_can_read_identity_catalogues() -> None:
    await seed()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                data={
                    "username": "owner@aionex.local",
                    "password": "ChangeMeNow!123",
                },
            )
            assert response.status_code == 200, response.text
            headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

            assert (
                await client.get("/api/v1/users", headers=headers)
            ).status_code == 200
            assert (
                await client.get("/api/v1/organizations", headers=headers)
            ).status_code == 200
            assert (
                await client.get("/api/v1/roles", headers=headers)
            ).status_code == 200
            assert (
                await client.get("/api/v1/permissions", headers=headers)
            ).status_code == 200


@pytest.mark.asyncio
async def test_owner_can_create_org_role_and_user() -> None:
    await seed()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                data={
                    "username": "owner@aionex.local",
                    "password": "ChangeMeNow!123",
                },
            )
            assert response.status_code == 200, response.text
            headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

            organization_response = await client.post(
                "/api/v1/organizations",
                headers=headers,
                json={
                    "name": "Example Enterprise",
                    "slug": "example-enterprise",
                    "plan": "enterprise",
                },
            )
            assert organization_response.status_code in (
                201,
                409,
            ), organization_response.text
            if organization_response.status_code == 201:
                organization_id = organization_response.json()["id"]
            else:
                organizations = (
                    await client.get("/api/v1/organizations", headers=headers)
                ).json()
                organization_id = next(
                    item["id"]
                    for item in organizations
                    if item["slug"] == "example-enterprise"
                )

            role_response = await client.post(
                "/api/v1/roles",
                headers=headers,
                json={
                    "name": "Batch One Engineer",
                    "description": "Batch-one verification role",
                    "organization_id": organization_id,
                    "permissions": ["projects:read", "profile:read"],
                },
            )
            assert role_response.status_code in (201, 409), role_response.text
            if role_response.status_code == 201:
                role_id = role_response.json()["id"]
            else:
                roles = (await client.get("/api/v1/roles", headers=headers)).json()
                role_id = next(
                    item["id"] for item in roles if item["name"] == "Batch One Engineer"
                )

            user_response = await client.post(
                "/api/v1/users",
                headers=headers,
                json={
                    "email": "batch1@example.com",
                    "name": "Batch One User",
                    "role_id": role_id,
                    "organization_id": organization_id,
                    "password": "SecureBatchOne!123",
                },
            )
            assert user_response.status_code in (201, 409), user_response.text


@pytest.mark.asyncio
async def test_unauthenticated_identity_access_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/users")).status_code == 401
        assert (await client.get("/api/v1/organizations")).status_code == 401
        assert (await client.get("/api/v1/roles")).status_code == 401
        assert (await client.get("/api/v1/permissions")).status_code == 401
