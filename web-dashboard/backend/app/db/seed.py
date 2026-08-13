"""Idempotent bootstrap data for the first production deployment."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.core.auth import pwd_context
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import (
    Organization,
    Permission,
    RefreshSession,
    Role,
    RolePermission,
    User,
    Workspace,
)

OWNER_EMAIL = (
    os.getenv("AIOS_BOOTSTRAP_OWNER_EMAIL", "owner@aionex.local").strip().lower()
)
CONFIGURED_PASSWORD = os.getenv("AIOS_BOOTSTRAP_OWNER_PASSWORD")
RESET_CONFIGURED_PASSWORD = os.getenv(
    "AIOS_BOOTSTRAP_RESET_OWNER_PASSWORD", "false"
).strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_TEST_PASSWORD = "ChangeMeNow!123"
BOOTSTRAP_PASSWORD = CONFIGURED_PASSWORD or DEFAULT_TEST_PASSWORD

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
    "projects:approve": "Approve project review and release transitions",
    "tasks:read": "Read tasks",
    "tasks:write": "Manage tasks",
    "workflows:read": "Read workflows",
    "workflows:write": "Manage and execute workflows",
    "meetings:read": "Read meetings",
    "meetings:write": "Create and manage meetings",
    "meetings:approve": "Approve meetings as owner",
    "reports:read": "Read reports",
    "reports:write": "Create and manage reports",
    "workforce:read": "Read governed workforce, assignments, health, and history",
    "workforce:write": "Create and transition workforce assignments",
    "workforce:manage": "Manage workforce lifecycle, performance, health, and incidents",
    "academy:read": "Read academy courses, enrollments, assessments, and certifications",
    "academy:write": "Manage academy courses and enrollments",
    "academy:assess": "Assess enrollments and manage certifications",
    "knowledge:read": "Read tenant-scoped verified knowledge, memory, and lessons",
    "knowledge:write": "Ingest knowledge, memory, and learning evidence",
    "knowledge:verify": "Verify knowledge and learning and promote lessons",
    "knowledge:manage": "Archive knowledge and revoke scoped memory",
    "agents:read": "Read AI agents",
    "agents:write": "Manage and execute AI agents",
    "providers:read": "Read AI providers",
    "providers:write": "Manage AI providers",
    "notifications:read": "Read notifications",
    "notifications:write": "Create notifications and retry delivery",
    "communications:read": "Read communication channels, endpoints, and delivery state",
    "communications:write": "Manage verified communication endpoints and delivery",
    "support:read": "Read support requests",
    "support:write": "Create and reply to support requests",
    "support:manage": "Assign, escalate, resolve, and close support requests",
    "incidents:read": "Read incidents and escalation state",
    "incidents:write": "Create, acknowledge, escalate, and resolve incidents",
    "governance:read": "Read councils, ministries, policies, decisions, and votes",
    "governance:write": "Manage governance bodies, policies, decisions, and membership",
    "governance:approve": "Approve, reject, retire, and ratify governance records",
    "approvals:read": "Read and create approval requests",
    "approvals:decide": "Approve, reject, or request changes",
    "monitoring:read": "Read monitoring data",
    "security:read": "Read security data",
    "security:write": "Manage security events, threats, and session revocation",
    "backups:read": "Read backup status",
    "backups:write": "Manage backup and recovery",
    "billing:read": "Read organization billing, invoices, usage, and licenses",
    "billing:write": "Manage organization checkout, subscriptions, and payment methods",
    "billing:admin": "Administer plans, refunds, wallets, taxes, coupons, and reconciliation",
}


@dataclass(frozen=True, slots=True)
class BuiltinRoleDefinition:
    name: str
    description: str
    permissions: tuple[str, ...]
    id: str | None = None


OWNER_PERMISSIONS = tuple(code for code in PERMISSIONS if code != "*")

BUILTIN_ROLES = (
    BuiltinRoleDefinition(
        id="super-owner-role",
        name="Super Owner",
        description="Protected global platform owner with unrestricted control.",
        permissions=tuple(PERMISSIONS),
    ),
    BuiltinRoleDefinition(
        name="Owner",
        description=(
            "Organization owner with every explicit platform permission, including "
            "meeting approval and backup recovery."
        ),
        permissions=OWNER_PERMISSIONS,
    ),
    BuiltinRoleDefinition(
        name="Administrator",
        description=(
            "Organization administrator for identity, access, projects, AI services, "
            "operations visibility and configuration."
        ),
        permissions=(
            "organizations:read",
            "organizations:write",
            "users:read",
            "users:write",
            "roles:read",
            "roles:write",
            "permissions:read",
            "permissions:write",
            "profile:read",
            "audit:read",
            "projects:read",
            "projects:write",
            "projects:approve",
            "tasks:read",
            "tasks:write",
            "workflows:read",
            "workflows:write",
            "meetings:read",
            "meetings:write",
            "reports:read",
            "reports:write",
            "workforce:read",
            "workforce:write",
            "workforce:manage",
            "academy:read",
            "academy:write",
            "academy:assess",
            "knowledge:read",
            "knowledge:write",
            "knowledge:verify",
            "knowledge:manage",
            "agents:read",
            "agents:write",
            "providers:read",
            "providers:write",
            "notifications:read",
            "notifications:write",
            "communications:read",
            "communications:write",
            "support:read",
            "support:write",
            "support:manage",
            "incidents:read",
            "incidents:write",
            "governance:read",
            "governance:write",
            "approvals:read",
            "approvals:decide",
            "monitoring:read",
            "security:read",
            "security:write",
            "backups:read",
            "billing:read",
            "billing:write",
        ),
    ),
    BuiltinRoleDefinition(
        name="Manager",
        description=(
            "Delivery manager for projects, tasks, workflows, meetings and reports."
        ),
        permissions=(
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
            "workforce:read",
            "workforce:write",
            "workforce:manage",
            "academy:read",
            "academy:write",
            "academy:assess",
            "knowledge:read",
            "knowledge:write",
            "knowledge:verify",
            "agents:read",
            "providers:read",
            "notifications:read",
            "notifications:write",
            "communications:read",
            "communications:write",
            "support:read",
            "support:write",
            "support:manage",
            "incidents:read",
            "governance:read",
            "governance:write",
            "approvals:read",
            "monitoring:read",
            "billing:read",
        ),
    ),
    BuiltinRoleDefinition(
        name="Engineer",
        description=(
            "Engineering role for project delivery, automation, AI agents and "
            "operational diagnostics."
        ),
        permissions=(
            "organizations:read",
            "users:read",
            "profile:read",
            "projects:read",
            "projects:write",
            "tasks:read",
            "tasks:write",
            "workflows:read",
            "workflows:write",
            "reports:read",
            "reports:write",
            "workforce:read",
            "workforce:write",
            "academy:read",
            "academy:assess",
            "knowledge:read",
            "knowledge:write",
            "knowledge:verify",
            "agents:read",
            "agents:write",
            "providers:read",
            "notifications:read",
            "communications:read",
            "support:read",
            "support:write",
            "incidents:read",
            "governance:read",
            "approvals:read",
            "monitoring:read",
            "security:read",
        ),
    ),
    BuiltinRoleDefinition(
        name="Developer",
        description=(
            "Development role for implementation work, workflows and AI-agent "
            "execution without administrative control."
        ),
        permissions=(
            "organizations:read",
            "users:read",
            "profile:read",
            "projects:read",
            "tasks:read",
            "tasks:write",
            "workflows:read",
            "workflows:write",
            "reports:read",
            "workforce:read",
            "academy:read",
            "knowledge:read",
            "knowledge:write",
            "agents:read",
            "agents:write",
            "providers:read",
            "notifications:read",
            "communications:read",
            "support:read",
            "support:write",
            "incidents:read",
            "governance:read",
            "approvals:read",
            "monitoring:read",
        ),
    ),
    BuiltinRoleDefinition(
        name="Support",
        description=(
            "Read-oriented support role for users, projects, meetings, reports and "
            "operational status."
        ),
        permissions=(
            "organizations:read",
            "users:read",
            "profile:read",
            "projects:read",
            "tasks:read",
            "meetings:read",
            "reports:read",
            "workforce:read",
            "academy:read",
            "knowledge:read",
            "notifications:read",
            "communications:read",
            "support:read",
            "support:write",
            "incidents:read",
            "governance:read",
            "approvals:read",
            "monitoring:read",
            "billing:read",
        ),
    ),
)

ASSIGNABLE_BUILTIN_ROLES = tuple(
    definition for definition in BUILTIN_ROLES if definition.name != "Super Owner"
)

BOOTSTRAP_ADVISORY_LOCK_ID = 1_095_327_060


async def _ensure_permission_catalogue(session) -> dict[str, Permission]:
    permission_rows: dict[str, Permission] = {}
    for code, description in PERMISSIONS.items():
        permission = await session.scalar(
            select(Permission).where(Permission.code == code)
        )
        if permission is None:
            permission = Permission(code=code, description=description)
            session.add(permission)
            await session.flush()
        elif permission.description != description:
            permission.description = description
        permission_rows[code] = permission
    return permission_rows


async def _ensure_builtin_roles(
    session,
    organization: Organization,
    permission_rows: dict[str, Permission],
    *,
    definitions: tuple[BuiltinRoleDefinition, ...] = BUILTIN_ROLES,
) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for definition in definitions:
        role = await session.scalar(
            select(Role).where(
                Role.organization_id == organization.id,
                Role.name == definition.name,
            )
        )
        if role is None:
            values = {
                "organization_id": organization.id,
                "name": definition.name,
                "description": definition.description,
                "system": True,
                "status": "active",
            }
            if definition.id is not None:
                values["id"] = definition.id
            role = Role(**values)
            session.add(role)
            await session.flush()
        else:
            role.description = definition.description
            role.system = True
            role.status = "active"

        assigned_permission_ids = set(
            (
                await session.scalars(
                    select(RolePermission.permission_id).where(
                        RolePermission.role_id == role.id
                    )
                )
            ).all()
        )
        for code in definition.permissions:
            permission = permission_rows[code]
            if permission.id not in assigned_permission_ids:
                session.add(
                    RolePermission(role_id=role.id, permission_id=permission.id)
                )
                assigned_permission_ids.add(permission.id)

        roles[definition.name] = role
    return roles


async def _backfill_existing_organization_builtin_roles(
    session,
    *,
    platform_organization_id: str,
    permission_rows: dict[str, Permission],
) -> None:
    """Add newly introduced permissions to existing tenant built-in roles.

    Tenant organizations can predate additions to the permission catalogue. This
    synchronization is intentionally additive and narrow: it updates only
    non-deleted roles whose names already match an assignable built-in role. It
    never creates missing tenant roles, never creates a tenant Super Owner, and
    never removes tenant-defined permissions.
    """

    definitions = {definition.name: definition for definition in ASSIGNABLE_BUILTIN_ROLES}
    roles = list(
        (
            await session.scalars(
                select(Role).where(
                    Role.organization_id != platform_organization_id,
                    Role.status != "deleted",
                    Role.name.in_(tuple(definitions)),
                )
            )
        ).all()
    )
    for role in roles:
        definition = definitions[role.name]
        role.description = definition.description
        role.system = True
        assigned_permission_ids = set(
            (
                await session.scalars(
                    select(RolePermission.permission_id).where(
                        RolePermission.role_id == role.id
                    )
                )
            ).all()
        )
        for code in definition.permissions:
            permission = permission_rows[code]
            if permission.id not in assigned_permission_ids:
                session.add(
                    RolePermission(role_id=role.id, permission_id=permission.id)
                )
                assigned_permission_ids.add(permission.id)


async def seed() -> None:
    created_owner = False
    reset_owner_password = False
    if RESET_CONFIGURED_PASSWORD and not CONFIGURED_PASSWORD:
        raise RuntimeError(
            "AIOS_BOOTSTRAP_OWNER_PASSWORD is required when "
            "AIOS_BOOTSTRAP_RESET_OWNER_PASSWORD is enabled"
        )
    if CONFIGURED_PASSWORD and len(CONFIGURED_PASSWORD) < settings.PASSWORD_MIN_LENGTH:
        raise RuntimeError(
            "AIOS_BOOTSTRAP_OWNER_PASSWORD must contain at least "
            f"{settings.PASSWORD_MIN_LENGTH} characters"
        )

    async with SessionLocal() as session:
        if session.get_bind().dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": BOOTSTRAP_ADVISORY_LOCK_ID},
            )

        org = await session.scalar(
            select(Organization).where(Organization.slug == "aionex")
        )
        if org is None:
            org = Organization(
                id="aionex-org", name="AIONEX Corp", slug="aionex", plan="enterprise"
            )
            session.add(org)
            await session.flush()

        permission_rows = await _ensure_permission_catalogue(session)
        roles = await _ensure_builtin_roles(session, org, permission_rows)
        await _backfill_existing_organization_builtin_roles(
            session,
            platform_organization_id=org.id,
            permission_rows=permission_rows,
        )
        role = roles["Super Owner"]

        workspace = await session.scalar(
            select(Workspace).where(
                Workspace.organization_id == org.id, Workspace.slug == "platform"
            )
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
            if settings.ENVIRONMENT != "test" and not CONFIGURED_PASSWORD:
                raise RuntimeError(
                    "AIOS_BOOTSTRAP_OWNER_PASSWORD is required for the first "
                    "production bootstrap"
                )
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
            created_owner = True
        elif settings.ENVIRONMENT == "test" or RESET_CONFIGURED_PASSWORD:
            owner.password_hash = pwd_context.hash(BOOTSTRAP_PASSWORD)
            owner.auth_version += 1
            now = datetime.now(UTC)
            active_sessions = (
                await session.scalars(
                    select(RefreshSession).where(
                        RefreshSession.user_id == owner.id,
                        RefreshSession.revoked_at.is_(None),
                    )
                )
            ).all()
            for refresh_session in active_sessions:
                refresh_session.revoked_at = now
            owner.status = "active"
            reset_owner_password = True

        await session.commit()

    if created_owner:
        print("AIONEX bootstrap owner created successfully.")
        print(f"Email: {OWNER_EMAIL}")
        print("The bootstrap password was accepted without being written to logs.")
        print("Change it immediately after the first successful login.")
    elif reset_owner_password:
        print("AIONEX bootstrap owner password reset successfully.")
        print(f"Email: {OWNER_EMAIL}")
        print("The password was updated from the configured bootstrap password.")
    else:
        print(f"Bootstrap data already exists. Owner account: {OWNER_EMAIL}")
        print(
            "Set AIOS_BOOTSTRAP_OWNER_PASSWORD and "
            "AIOS_BOOTSTRAP_RESET_OWNER_PASSWORD=true to reset it explicitly."
        )


if __name__ == "__main__":
    asyncio.run(seed())
