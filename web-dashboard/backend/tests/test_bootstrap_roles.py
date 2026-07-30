"""Regression coverage for assignable bootstrap organization roles."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.bootstrap_roles import (
    DEFAULT_ROLE_NAMES,
    DEFAULT_ROLE_SPECS,
    PERMISSIONS,
    ensure_default_roles,
)
from app.db.models import Organization, Permission, Role, RolePermission


def test_default_roles_never_receive_global_super_owner_control() -> None:
    assert DEFAULT_ROLE_NAMES == (
        "Owner",
        "Administrator",
        "Manager",
        "Engineer",
        "Developer",
        "Support",
    )
    for spec in DEFAULT_ROLE_SPECS:
        assert "*" not in spec.permission_codes
        assert set(spec.permission_codes) <= set(PERMISSIONS)


@pytest.mark.asyncio
async def test_default_roles_are_created_idempotently_and_assignable() -> None:
    suffix = uuid4().hex
    organization = Organization(
        name=f"Bootstrap Role Test {suffix}",
        slug=f"bootstrap-role-test-{suffix}",
        plan="enterprise",
        status="active",
    )

    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()

        first = await ensure_default_roles(session, organization.id)
        second = await ensure_default_roles(session, organization.id)
        await session.flush()

        roles = list(
            (
                await session.scalars(
                    select(Role)
                    .where(Role.organization_id == organization.id)
                    .order_by(Role.name)
                )
            ).all()
        )
        assert {role.name for role in roles} == set(DEFAULT_ROLE_NAMES)
        assert set(first) == set(DEFAULT_ROLE_NAMES)
        assert {name: role.id for name, role in first.items()} == {
            name: role.id for name, role in second.items()
        }
        assert all(role.system for role in roles)
        assert all(role.status == "active" for role in roles)
        assert all(role.name != "Super Owner" for role in roles)

        permission_rows = (
            await session.execute(
                select(Role.name, Permission.code)
                .join(RolePermission, RolePermission.role_id == Role.id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(Role.organization_id == organization.id)
            )
        ).all()
        permissions_by_role: dict[str, set[str]] = {
            role_name: set() for role_name in DEFAULT_ROLE_NAMES
        }
        for role_name, permission_code in permission_rows:
            permissions_by_role[role_name].add(permission_code)

        assert permissions_by_role["Owner"] == set(PERMISSIONS) - {"*"}
        assert all("*" not in codes for codes in permissions_by_role.values())
        assert all(codes for codes in permissions_by_role.values())

        await session.rollback()
