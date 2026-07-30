"""Idempotent permission catalogue and default organization role provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Permission, Role, RolePermission

PERMISSIONS = {
    "*": "Full platform control",
    "organizations:read": "Read organizations",
    "organizations:write": "Manage organizations",
    "users:read": "Read users",
    "users:write": "Manage users",
    "roles:read": "Read roles",
    "roles:write": "Manage roles and assignments",
    "permissions:read": "Read permission catalogue",
    "permissions:write": "Manage role permission assignments",
    "profile:read": "Read own profile",
    "audit:read": "Read identity and access audit events",
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
    "reports:write": "Create and manage reports",
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


@dataclass(frozen=True, slots=True)
class DefaultRoleSpec:
    """A protected platform role that remains assignable to organization users."""

    name: str
    description: str
    permission_codes: tuple[str, ...]


ALL_ORGANIZATION_PERMISSIONS = tuple(code for code in PERMISSIONS if code != "*")

DEFAULT_ROLE_SPECS = (
    DefaultRoleSpec(
        name="Owner",
        description=(
            "Organization owner with all explicit organization-level permissions; "
            "global Super Owner control remains excluded."
        ),
        permission_codes=ALL_ORGANIZATION_PERMISSIONS,
    ),
    DefaultRoleSpec(
        name="Administrator",
        description="Organization administrator for identity, access and operations.",
        permission_codes=(
            "organizations:read",
            "users:read",
            "users:write",
            "roles:read",
            "roles:write",
            "permissions:read",
            "profile:read",
            "audit:read",
            "projects:read",
            "projects:write",
            "tasks:read",
            "tasks:write",
            "workflows:read",
            "workflows:write",
            "meetings:read",
            "meetings:write",
            "reports:read",
            "reports:write",
            "agents:read",
            "agents:write",
            "providers:read",
            "providers:write",
            "notifications:read",
            "monitoring:read",
            "security:read",
            "backups:read",
        ),
    ),
    DefaultRoleSpec(
        name="Manager",
        description="Team and project manager with delivery and reporting controls.",
        permission_codes=(
            "organizations:read",
            "users:read",
            "roles:read",
            "profile:read",
            "projects:read",
            "projects:write",
            "tasks:read",
            "tasks:write",
            "workflows:read",
            "workflows:write",
            "meetings:read",
            "meetings:write",
            "reports:read",
            "reports:write",
            "notifications:read",
            "monitoring:read",
        ),
    ),
    DefaultRoleSpec(
        name="Engineer",
        description="Engineering role for project, workflow and AI execution.",
        permission_codes=(
            "profile:read",
            "projects:read",
            "projects:write",
            "tasks:read",
            "tasks:write",
            "workflows:read",
            "workflows:write",
            "reports:read",
            "agents:read",
            "agents:write",
            "providers:read",
            "providers:write",
            "monitoring:read",
            "security:read",
        ),
    ),
    DefaultRoleSpec(
        name="Developer",
        description="Application developer with implementation and AI tool access.",
        permission_codes=(
            "profile:read",
            "projects:read",
            "projects:write",
            "tasks:read",
            "tasks:write",
            "workflows:read",
            "workflows:write",
            "agents:read",
            "agents:write",
            "providers:read",
            "providers:write",
            "monitoring:read",
        ),
    ),
    DefaultRoleSpec(
        name="Support",
        description="Support role for user assistance, task handling and diagnostics.",
        permission_codes=(
            "organizations:read",
            "users:read",
            "roles:read",
            "profile:read",
            "projects:read",
            "tasks:read",
            "tasks:write",
            "meetings:read",
            "reports:read",
            "notifications:read",
            "monitoring:read",
            "security:read",
        ),
    ),
)

DEFAULT_ROLE_NAMES = tuple(spec.name for spec in DEFAULT_ROLE_SPECS)

for _spec in DEFAULT_ROLE_SPECS:
    unknown_codes = set(_spec.permission_codes) - set(PERMISSIONS)
    if unknown_codes:
        raise RuntimeError(
            f"Default role {_spec.name} references unknown permissions: "
            f"{', '.join(sorted(unknown_codes))}"
        )
    if "*" in _spec.permission_codes:
        raise RuntimeError(
            f"Default role {_spec.name} cannot receive global platform control"
        )


async def ensure_permission_catalog(
    session: AsyncSession,
) -> dict[str, Permission]:
    """Create any missing global permission rows without deleting custom entries."""

    rows = list(
        (
            await session.scalars(
                select(Permission).where(Permission.code.in_(tuple(PERMISSIONS)))
            )
        ).all()
    )
    by_code = {permission.code: permission for permission in rows}

    for code, description in PERMISSIONS.items():
        permission = by_code.get(code)
        if permission is None:
            permission = Permission(code=code, description=description)
            session.add(permission)
            by_code[code] = permission
        elif not permission.description:
            permission.description = description

    await session.flush()
    return by_code


async def ensure_default_roles(
    session: AsyncSession,
    organization_id: str,
    *,
    permission_rows: Mapping[str, Permission] | None = None,
) -> dict[str, Role]:
    """Provision assignable system roles and their minimum permission baselines.

    Existing roles and extra permission assignments are preserved. Missing baseline
    assignments are restored, making this safe for upgrades of already-running
    installations as well as first-time organization creation.
    """

    permissions = (
        dict(permission_rows)
        if permission_rows is not None
        else await ensure_permission_catalog(session)
    )
    role_names = tuple(spec.name for spec in DEFAULT_ROLE_SPECS)
    existing_roles = list(
        (
            await session.scalars(
                select(Role).where(
                    Role.organization_id == organization_id,
                    Role.name.in_(role_names),
                )
            )
        ).all()
    )
    roles_by_name = {role.name: role for role in existing_roles}

    for spec in DEFAULT_ROLE_SPECS:
        role = roles_by_name.get(spec.name)
        if role is None:
            role = Role(
                organization_id=organization_id,
                name=spec.name,
                description=spec.description,
                system=True,
                status="active",
            )
            session.add(role)
            await session.flush()
            roles_by_name[spec.name] = role
        elif role.system and role.status == "deleted":
            role.status = "active"

        existing_codes = set(
            (
                await session.scalars(
                    select(Permission.code)
                    .join(
                        RolePermission,
                        RolePermission.permission_id == Permission.id,
                    )
                    .where(RolePermission.role_id == role.id)
                )
            ).all()
        )
        for code in spec.permission_codes:
            if code not in existing_codes:
                session.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permissions[code].id,
                    )
                )

    await session.flush()
    return roles_by_name
