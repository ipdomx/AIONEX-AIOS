"""Idempotent bootstrap data for the first production deployment."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.core.auth import pwd_context
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.bootstrap_roles import (
    PERMISSIONS,
    ensure_default_roles,
    ensure_permission_catalog,
)
from app.db.models import (
    Organization,
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

BOOTSTRAP_ADVISORY_LOCK_ID = 1_095_327_060


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

        role = await session.scalar(
            select(Role).where(
                Role.organization_id == org.id, Role.name == "Super Owner"
            )
        )
        if role is None:
            role = Role(
                id="super-owner-role",
                organization_id=org.id,
                name="Super Owner",
                description="Protected global platform owner",
                system=True,
                status="active",
            )
            session.add(role)
            await session.flush()
        else:
            role.system = True
            role.status = "active"
            if not role.description:
                role.description = "Protected global platform owner"

        permission_rows = await ensure_permission_catalog(session)

        for permission in permission_rows.values():
            assignment = await session.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if assignment is None:
                session.add(
                    RolePermission(role_id=role.id, permission_id=permission.id)
                )

        organizations = list((await session.scalars(select(Organization))).all())
        for organization in organizations:
            await ensure_default_roles(
                session,
                organization.id,
                permission_rows=permission_rows,
            )

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
    print(
        "Default organization roles verified: "
        + ", ".join(spec.name for spec in __import__(
            "app.db.bootstrap_roles", fromlist=["DEFAULT_ROLE_SPECS"]
        ).DEFAULT_ROLE_SPECS)
    )


if __name__ == "__main__":
    asyncio.run(seed())
