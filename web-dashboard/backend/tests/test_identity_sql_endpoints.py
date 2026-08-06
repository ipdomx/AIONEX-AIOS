"""Relational source-of-truth contracts for identity administration APIs."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    Organization,
    RefreshSession,
    Role,
    RolePermission,
    Team,
    TeamMembership,
    User,
    Workspace,
)
from app.db.seed import seed

ENDPOINTS = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "endpoints"


def _actor(
    *,
    user_id: str = "owner-1",
    role: str = "Super Owner",
    organization_id: str = "aionex-org",
    permissions: list[str] | None = None,
) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.com",
        name="Identity Test Actor",
        role=role,
        password_hash="unused",
        organization_id=organization_id,
        organization_name="Identity Test Organization",
        organization_plan="enterprise",
        permissions=permissions if permissions is not None else ["*"],
    )


def test_identity_endpoints_no_longer_use_the_in_memory_store() -> None:
    for filename in (
        "organizations.py",
        "users.py",
        "roles.py",
        "permissions.py",
        "workspaces.py",
        "teams.py",
    ):
        source = (ENDPOINTS / filename).read_text(encoding="utf-8")
        assert "identity_store" not in source
        assert "app.db.models" in source
        assert "Depends(get_db)" in source


@pytest.mark.asyncio
async def test_identity_lifecycle_is_relational_scoped_and_audited() -> None:
    await seed()
    suffix = uuid4().hex
    actor_holder = {"actor": _actor()}
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor_holder["actor"]

    organization_id: str | None = None
    role_id: str | None = None
    user_id: str | None = None
    refresh_session_id: str | None = None
    workspace_id: str | None = None
    team_id: str | None = None

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            permission_response = await client.get("/api/v1/permissions")
            assert permission_response.status_code == 200, permission_response.text
            permissions_by_key = {
                item["key"]: item for item in permission_response.json()
            }
            assert permissions_by_key["profile:read"]["category"] == "identity"
            assert permissions_by_key["permissions:write"]["name"] == (
                "Manage Permissions"
            )

            organization_response = await client.post(
                "/api/v1/organizations",
                json={
                    "name": f"SQL Identity {suffix}",
                    "slug": f"sql-identity-{suffix}",
                    "plan": "enterprise",
                },
            )
            assert organization_response.status_code == 201, organization_response.text
            organization_id = organization_response.json()["id"]
            assert organization_response.json()["member_count"] == 0

            role_response = await client.post(
                "/api/v1/roles",
                json={
                    "name": f"SQL Manager {suffix}",
                    "description": "Relational identity verification",
                    "organization_id": organization_id,
                    "permissions": [
                        "users:read",
                        "users:write",
                        "profile:read",
                        "audit:read",
                        "projects:read",
                        "projects:write",
                    ],
                },
            )
            assert role_response.status_code == 201, role_response.text
            role_id = role_response.json()["id"]
            assert role_response.json()["permissions"] == [
                "audit:read",
                "profile:read",
                "projects:read",
                "projects:write",
                "users:read",
                "users:write",
            ]

            unsupported_workspace = await client.post(
                "/api/v1/users",
                json={
                    "email": f"workspace-{suffix}@example.com",
                    "name": "Unsupported Workspace",
                    "role_id": role_id,
                    "organization_id": organization_id,
                    "workspace_id": "not-persisted",
                    "password": "SecureWorkspace!123",
                },
            )
            assert unsupported_workspace.status_code == 422

            user_response = await client.post(
                "/api/v1/users",
                json={
                    "email": f"sql-user-{suffix}@example.com",
                    "name": "SQL Identity User",
                    "role_id": role_id,
                    "organization_id": organization_id,
                    "password": "SecureIdentity!123",
                },
            )
            assert user_response.status_code == 201, user_response.text
            user_payload = user_response.json()["user"]
            user_id = user_payload["id"]
            assert user_payload["workspace_id"] is None
            assert user_payload["last_active"] is None
            assert user_response.json()["temporary_password"] is None

            actor_holder["actor"] = _actor(
                user_id=user_id,
                role="Manager",
                organization_id=organization_id,
                permissions=[
                    "organizations:read",
                    "users:read",
                    "users:write",
                    "roles:read",
                    "permissions:read",
                    "projects:read",
                    "projects:write",
                    "audit:read",
                ],
            )
            workspace_response = await client.post(
                "/api/v1/workspaces",
                json={
                    "name": f"Identity Workspace {suffix}",
                    "description": "Persisted workspace assignment",
                },
            )
            assert workspace_response.status_code == 201, workspace_response.text
            workspace_id = workspace_response.json()["id"]

            assigned_workspace = await client.put(
                f"/api/v1/users/{user_id}",
                json={"workspace_id": workspace_id},
            )
            assert assigned_workspace.status_code == 200, assigned_workspace.text
            assert assigned_workspace.json()["workspace_id"] == workspace_id
            assert assigned_workspace.json()["workspace"] == f"Identity Workspace {suffix}"

            filtered_users = await client.get(
                "/api/v1/users", params={"workspace_id": workspace_id}
            )
            assert filtered_users.status_code == 200, filtered_users.text
            assert {item["id"] for item in filtered_users.json()} == {user_id}

            actor_holder["actor"] = _actor()
            team_response = await client.post(
                "/api/v1/teams",
                json={
                    "name": f"Identity Team {suffix}",
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
            )
            assert team_response.status_code == 201, team_response.text
            team_id = team_response.json()["id"]
            assert team_response.json()["organization_id"] == organization_id
            assert team_response.json()["workspace_id"] == workspace_id

            membership_response = await client.put(
                f"/api/v1/teams/{team_id}/members/{user_id}",
                json={"membership_role": "lead"},
            )
            assert membership_response.status_code == 200, membership_response.text
            actor_holder["actor"] = _actor(
                user_id=user_id,
                role="Manager",
                organization_id=organization_id,
                permissions=["users:read", "users:write", "projects:read", "projects:write"],
            )
            members = await client.get(f"/api/v1/teams/{team_id}/members")
            assert members.status_code == 200, members.text
            assert members.json()[0]["id"] == user_id
            assert members.json()[0]["membership_role"] == "lead"

            actor_holder["actor"] = _actor()
            foreign_team = await client.get(f"/api/v1/teams/{team_id}")
            assert foreign_team.status_code == 200

            promote_to_super_owner = await client.put(
                f"/api/v1/users/{user_id}",
                json={"role_id": "super-owner-role"},
            )
            assert promote_to_super_owner.status_code == 422

            members_response = await client.get(
                f"/api/v1/organizations/{organization_id}/members"
            )
            assert members_response.status_code == 200, members_response.text
            assert {item["id"] for item in members_response.json()} == {user_id}

            async with SessionLocal() as session:
                refresh_session = RefreshSession(
                    user_id=user_id,
                    token_hash=hashlib.sha256(
                        f"identity-session-{suffix}".encode()
                    ).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                    ip_address="127.0.0.1",
                    user_agent="identity-test",
                )
                session.add(refresh_session)
                await session.commit()
                refresh_session_id = refresh_session.id

            sessions_response = await client.get(f"/api/v1/users/{user_id}/sessions")
            assert sessions_response.status_code == 200, sessions_response.text
            assert refresh_session_id in {
                item["id"] for item in sessions_response.json()
            }

            replace_permissions = await client.put(
                f"/api/v1/permissions/roles/{role_id}",
                json={"permissions": ["users:read", "projects:read"]},
            )
            assert replace_permissions.status_code == 200, replace_permissions.text
            assert replace_permissions.json()["permissions"] == [
                "projects:read",
                "users:read",
            ]

            effective_response = await client.get(
                f"/api/v1/permissions/effective/{user_id}"
            )
            assert effective_response.status_code == 200, effective_response.text
            assert effective_response.json()["permissions"] == [
                "projects:read",
                "users:read",
            ]

            suspend_response = await client.put(
                f"/api/v1/users/{user_id}",
                json={"status": "suspended"},
            )
            assert suspend_response.status_code == 200, suspend_response.text
            assert suspend_response.json()["status"] == "suspended"

            activity_response = await client.get(f"/api/v1/users/{user_id}/activity")
            assert activity_response.status_code == 200, activity_response.text
            assert {"create", "update"}.issubset(
                {item["action"] for item in activity_response.json()}
            )

            actor_holder["actor"] = _actor(
                user_id=user_id,
                role="Manager",
                organization_id=organization_id,
                permissions=[
                    "organizations:read",
                    "users:read",
                    "users:write",
                    "roles:read",
                    "permissions:read",
                ],
            )
            foreign_scope = await client.get("/api/v1/organizations/aionex-org")
            assert foreign_scope.status_code == 403
            actor_holder["actor"] = _actor(
                user_id="owner-1",
                role="Owner",
                organization_id="aionex-org",
                permissions=["users:read", "users:write"],
            )
            hidden_team = await client.get(f"/api/v1/teams/{team_id}")
            assert hidden_team.status_code == 404
            actor_holder["actor"] = _actor(
                user_id=user_id,
                role="Manager",
                organization_id=organization_id,
                permissions=[
                    "organizations:read",
                    "users:read",
                    "users:write",
                    "roles:read",
                    "permissions:read",
                ],
            )
            cross_organization_create = await client.post(
                "/api/v1/users",
                json={
                    "email": f"cross-org-{suffix}@example.com",
                    "name": "Cross Organization",
                    "role_id": "super-owner-role",
                    "organization_id": "aionex-org",
                    "password": "SecureCrossOrg!123",
                },
            )
            assert cross_organization_create.status_code == 403

            actor_holder["actor"] = _actor(
                user_id=user_id,
                role="Manager",
                organization_id=organization_id,
                permissions=["users:read", "users:write", "projects:read", "projects:write"],
            )
            delete_team_response = await client.delete(f"/api/v1/teams/{team_id}")
            assert delete_team_response.status_code == 200, delete_team_response.text
            clear_workspace = await client.put(
                f"/api/v1/users/{user_id}", json={"workspace_id": None}
            )
            assert clear_workspace.status_code == 200, clear_workspace.text
            assert clear_workspace.json()["workspace_id"] is None

            actor_holder["actor"] = _actor()
            delete_user_response = await client.delete(f"/api/v1/users/{user_id}")
            assert delete_user_response.status_code == 200, delete_user_response.text
            delete_role_response = await client.delete(f"/api/v1/roles/{role_id}")
            assert delete_role_response.status_code == 200, delete_role_response.text
            deactivate_organization = await client.delete(
                f"/api/v1/organizations/{organization_id}"
            )
            assert deactivate_organization.status_code == 200

        async with SessionLocal() as session:
            stored_user = await session.get(User, user_id)
            stored_role = await session.get(Role, role_id)
            stored_organization = await session.get(Organization, organization_id)
            stored_refresh_session = await session.get(
                RefreshSession,
                refresh_session_id,
            )
            assert stored_user is not None
            assert stored_user.deleted_at is not None
            assert stored_user.status == "inactive"
            assert stored_role is not None and stored_role.status == "deleted"
            assert (
                stored_organization is not None
                and stored_organization.status == "inactive"
            )
            assert (
                stored_refresh_session is not None
                and stored_refresh_session.revoked_at is not None
            )

            audit_actions = set(
                (
                    await session.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.resource_id.in_(
                                [organization_id, role_id, user_id]
                            )
                        )
                    )
                ).all()
            )
            assert {
                "create",
                "update",
                "delete",
                "deactivate",
                "replace_permissions",
            }.issubset(audit_actions)
    finally:
        if organization_id is not None:
            async with SessionLocal() as session:
                resource_ids = [
                    resource_id
                    for resource_id in (organization_id, role_id, user_id)
                    if resource_id is not None
                ]
                if resource_ids:
                    await session.execute(
                        delete(AuditEvent).where(
                            AuditEvent.resource_id.in_(resource_ids)
                        )
                    )
                if refresh_session_id is not None:
                    await session.execute(
                        delete(RefreshSession).where(
                            RefreshSession.id == refresh_session_id
                        )
                    )
                if team_id is not None:
                    await session.execute(
                        delete(TeamMembership).where(TeamMembership.team_id == team_id)
                    )
                    await session.execute(delete(Team).where(Team.id == team_id))
                if user_id is not None:
                    await session.execute(delete(User).where(User.id == user_id))
                if workspace_id is not None:
                    await session.execute(
                        delete(Workspace).where(Workspace.id == workspace_id)
                    )
                if role_id is not None:
                    await session.execute(
                        delete(RolePermission).where(RolePermission.role_id == role_id)
                    )
                    await session.execute(delete(Role).where(Role.id == role_id))
                await session.execute(
                    delete(Organization).where(Organization.id == organization_id)
                )
                await session.commit()


@pytest.mark.asyncio
async def test_unknown_permissions_and_super_owner_mutations_are_rejected() -> None:
    await seed()
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: _actor()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        unknown = await client.put(
            "/api/v1/permissions/roles/super-owner-role",
            json={"permissions": ["not:a-real-permission"]},
        )
        assert unknown.status_code == 422

        remove_full_control = await client.put(
            "/api/v1/permissions/roles/super-owner-role",
            json={"permissions": ["users:read"]},
        )
        assert remove_full_control.status_code == 422

        rename_super_owner = await client.put(
            "/api/v1/roles/super-owner-role",
            json={"name": "Former Owner"},
        )
        assert rename_super_owner.status_code == 422

        delete_self = await client.delete("/api/v1/users/owner-1")
        assert delete_self.status_code == 422


@pytest.mark.asyncio
async def test_standard_users_api_protects_super_owner_and_inactive_roles() -> None:
    await seed()
    suffix = uuid4().hex
    replacement_role_id: str | None = None
    suspended_role_id: str | None = None

    try:
        async with SessionLocal() as session:
            replacement_role = Role(
                organization_id="aionex-org",
                name=f"Replacement {suffix}",
                status="active",
            )
            suspended_role = Role(
                organization_id="aionex-org",
                name=f"Suspended {suffix}",
                status="suspended",
            )
            session.add_all([replacement_role, suspended_role])
            await session.commit()
            replacement_role_id = replacement_role.id
            suspended_role_id = suspended_role.id

        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        app.dependency_overrides[current_user] = lambda: _actor(
            user_id="other-super-owner"
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            assign_super_owner = await client.post(
                "/api/v1/users",
                json={
                    "email": f"forbidden-owner-{suffix}@example.com",
                    "name": "Forbidden Owner",
                    "role_id": "super-owner-role",
                    "organization_id": "aionex-org",
                    "password": "SecureForbidden!123",
                },
            )
            assert assign_super_owner.status_code == 422

            assign_suspended_role = await client.post(
                "/api/v1/users",
                json={
                    "email": f"suspended-role-{suffix}@example.com",
                    "name": "Suspended Role User",
                    "role_id": suspended_role_id,
                    "organization_id": "aionex-org",
                    "password": "SecureSuspended!123",
                },
            )
            assert assign_suspended_role.status_code == 404

            create_reserved_role = await client.post(
                "/api/v1/roles",
                json={
                    "name": "Super Owner",
                    "organization_id": "aionex-org",
                    "permissions": [],
                },
            )
            assert create_reserved_role.status_code == 422

            grant_full_control = await client.put(
                f"/api/v1/permissions/roles/{replacement_role_id}",
                json={"permissions": ["*"]},
            )
            assert grant_full_control.status_code == 422

            rename_to_super_owner = await client.put(
                f"/api/v1/roles/{replacement_role_id}",
                json={"name": "Super Owner"},
            )
            assert rename_to_super_owner.status_code == 422

            change_super_owner_role = await client.put(
                "/api/v1/users/owner-1",
                json={"role_id": replacement_role_id},
            )
            assert change_super_owner_role.status_code == 422

            deactivate_super_owner = await client.put(
                "/api/v1/users/owner-1",
                json={"status": "suspended"},
            )
            assert deactivate_super_owner.status_code == 422
    finally:
        async with SessionLocal() as session:
            role_ids = [
                role_id
                for role_id in (replacement_role_id, suspended_role_id)
                if role_id is not None
            ]
            if role_ids:
                await session.execute(delete(Role).where(Role.id.in_(role_ids)))
                await session.commit()
