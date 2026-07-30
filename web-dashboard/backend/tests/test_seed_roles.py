from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Organization, Permission, Role, RolePermission
from app.db.seed import (
    ASSIGNABLE_BUILTIN_ROLES,
    BUILTIN_ROLES,
    PERMISSIONS,
    _ensure_builtin_roles,
    _ensure_permission_catalogue,
)


EXPECTED_ROLE_NAMES = {
    "Super Owner",
    "Owner",
    "Administrator",
    "Manager",
    "Engineer",
    "Developer",
    "Support",
}


def test_builtin_role_catalogue_is_complete_and_least_privilege() -> None:
    assert {definition.name for definition in BUILTIN_ROLES} == EXPECTED_ROLE_NAMES
    assert len({definition.name for definition in BUILTIN_ROLES}) == len(BUILTIN_ROLES)

    known_permissions = set(PERMISSIONS)
    for definition in BUILTIN_ROLES:
        assert definition.permissions
        assert set(definition.permissions) <= known_permissions
        if definition.name != "Super Owner":
            assert "*" not in definition.permissions

    owner = next(definition for definition in BUILTIN_ROLES if definition.name == "Owner")
    assert set(owner.permissions) == known_permissions - {"*"}


@pytest.mark.asyncio
async def test_assignable_builtin_roles_are_seeded_idempotently() -> None:
    organization_id = str(uuid4())
    organization = Organization(
        id=organization_id,
        name="Bootstrap Role Test",
        slug=f"bootstrap-role-test-{uuid4().hex}",
        plan="enterprise",
        status="active",
    )

    async with SessionLocal() as session:
        try:
            session.add(organization)
            await session.flush()

            permission_rows = await _ensure_permission_catalogue(session)
            first = await _ensure_builtin_roles(
                session,
                organization,
                permission_rows,
                definitions=ASSIGNABLE_BUILTIN_ROLES,
            )
            await session.flush()
            second = await _ensure_builtin_roles(
                session,
                organization,
                permission_rows,
                definitions=ASSIGNABLE_BUILTIN_ROLES,
            )
            await session.flush()

            assert set(first) == {
                definition.name for definition in ASSIGNABLE_BUILTIN_ROLES
            }
            assert {name: role.id for name, role in first.items()} == {
                name: role.id for name, role in second.items()
            }

            stored_roles = list(
                (
                    await session.scalars(
                        select(Role).where(Role.organization_id == organization_id)
                    )
                ).all()
            )
            assert len(stored_roles) == len(ASSIGNABLE_BUILTIN_ROLES)

            for definition in ASSIGNABLE_BUILTIN_ROLES:
                role = first[definition.name]
                assert role.system is True
                assert role.status == "active"
                permission_codes = set(
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
                assert permission_codes == set(definition.permissions)
                assert "*" not in permission_codes
        finally:
            await session.rollback()
