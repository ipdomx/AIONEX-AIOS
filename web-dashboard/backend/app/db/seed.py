"""Idempotent bootstrap data for the first production deployment."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.auth import pwd_context
from app.db.base import SessionLocal
from app.db.models import Organization, Permission, Role, RolePermission, User, Workspace

OWNER_EMAIL = "owner@aionex.local"
BOOTSTRAP_PASSWORD = "ChangeMeNow!123"

PERMISSIONS = {
    "*": "Full platform control",
    "organizations:read": "Read organizations",
    "organizations:write": "Manage organizations",
    "users:read": "Read users",
    "users:write": "Manage users",
    "roles:read": "Read roles",
    "roles:write": "Manage roles and assignments",
    "projects:read": "Read projects",
    "projects:write": "Manage projects",
    "tasks:read": "Read tasks",
    "tasks:write": "Manage tasks",
    "workflows:read": "Read workflows",
    "workflows:write": "Manage and execute workflows",
    "meetings:read": "Read meetings",
    "meetings:write": "Create and manage meetings",
    "meetings:approve": "Approve meetings as owner",
    "reports:read": "Read reports",
    "agents:read": "Read AI agents",
    "agents:write": "Manage and execute AI agents",
    "providers:read": "Read AI providers",
    "providers:write": "Manage AI providers",
    "notifications:read": "Read notifications",
    "monitoring:read": "Read monitoring data",
    "security:read": "Read security data",
    "backups:read": "Read backup status",
    "backups:write": "Manage backup and recovery",
}


async def seed() -> None:
    async with SessionLocal() as session:
        org = await session.scalar(select(Organization).where(Organization.slug == "aionex"))
        if org is None:
            org = Organization(id="aionex-org", name="AIONEX Corp", slug="aionex", plan="enterprise")
            session.add(org)
            await session.flush()

        role = await session.scalar(
            select(Role).where(Role.organization_id == org.id, Role.name == "Super Owner")
        )
        if role is None:
            role = Role(id="super-owner-role", organization_id=org.id, name="Super Owner", system=True)
            session.add(role)
            await session.flush()

        permission_rows: dict[str, Permission] = {}
        for code, description in PERMISSIONS.items():
            permission = await session.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, description=description)
                session.add(permission)
                await session.flush()
            permission_rows[code] = permission

        for permission in permission_rows.values():
            assignment = await session.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if assignment is None:
                session.add(RolePermission(role_id=role.id, permission_id=permission.id))

        workspace = await session.scalar(
            select(Workspace).where(Workspace.organization_id == org.id, Workspace.slug == "platform")
        )
        if workspace is None:
            session.add(
                Workspace(
                    id="platform-workspace",
                    organization_id=org.id,
                    name="Platform",
                    slug="platform",
                    description="Primary AIONEX AIOS workspace",
                )
            )

        owner = await session.scalar(select(User).where(User.email == OWNER_EMAIL))
        if owner is None:
            session.add(
                User(
                    id="owner-1",
                    organization_id=org.id,
                    role_id=role.id,
                    email=OWNER_EMAIL,
                    name="AIONEX Owner",
                    password_hash=pwd_context.hash(BOOTSTRAP_PASSWORD),
                    status="active",
                )
            )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
