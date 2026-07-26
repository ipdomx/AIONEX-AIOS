"""Batch-one identity, organizations, and RBAC verification tests."""

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def owner_headers() -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "owner@aionex.local", "password": "ChangeMeNow!123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_owner_can_read_identity_catalogues() -> None:
    headers = owner_headers()
    assert client.get("/api/v1/users", headers=headers).status_code == 200
    assert client.get("/api/v1/organizations", headers=headers).status_code == 200
    assert client.get("/api/v1/roles", headers=headers).status_code == 200
    assert client.get("/api/v1/permissions", headers=headers).status_code == 200


def test_owner_can_create_org_role_and_user() -> None:
    headers = owner_headers()
    organization_response = client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Example Enterprise", "slug": "example-enterprise", "plan": "enterprise"},
    )
    assert organization_response.status_code in (201, 409), organization_response.text
    if organization_response.status_code == 201:
        organization_id = organization_response.json()["id"]
    else:
        organizations = client.get("/api/v1/organizations", headers=headers).json()
        organization_id = next(item["id"] for item in organizations if item["slug"] == "example-enterprise")

    role_response = client.post(
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
        roles = client.get("/api/v1/roles", headers=headers).json()
        role_id = next(item["id"] for item in roles if item["name"] == "Batch One Engineer")

    user_response = client.post(
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


def test_unauthenticated_identity_access_is_rejected() -> None:
    assert client.get("/api/v1/users").status_code == 401
    assert client.get("/api/v1/organizations").status_code == 401
    assert client.get("/api/v1/roles").status_code == 401
    assert client.get("/api/v1/permissions").status_code == 401
