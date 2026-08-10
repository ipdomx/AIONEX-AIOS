"""Role management endpoints backed by the relational identity schema."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.permissions import (
    assert_full_control_scope,
    assert_role_scope,
    resolve_permissions,
    serialize_role,
)
from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Organization,
    Role,
    RolePermission,
    User,
)

router = APIRouter()


class RoleCreate(BaseModel):
    name: str
    description: str = ""
    organization_id: str | None = None
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


async def _get_role(session: AsyncSession, role_id: str) -> Role:
    role = await session.scalar(
        select(Role).where(
            Role.id == role_id,
            Role.status != "deleted",
        )
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


def _audit(
    actor: UserRecord,
    role: Role,
    action: str,
    details: dict | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=role.organization_id or actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="role",
        resource_id=role.id,
        details=details or {},
    )


async def _role_name_exists(
    session: AsyncSession,
    organization_id: str | None,
    name: str,
    *,
    exclude_id: str | None = None,
) -> bool:
    statement = select(Role.id).where(
        Role.status != "deleted",
        Role.organization_id == organization_id,
        func.lower(Role.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        statement = statement.where(Role.id != exclude_id)
    return await session.scalar(statement) is not None


@router.get("")
async def list_roles(
    actor: UserRecord = Depends(require_permissions("roles:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Role).where(Role.status != "deleted")
    if actor.role != "Super Owner":
        statement = statement.where(
            or_(
                Role.organization_id.is_(None),
                Role.organization_id == actor.organization_id,
            )
        )
    roles = list(
        (
            await session.scalars(
                statement.order_by(Role.system.desc(), func.lower(Role.name))
            )
        ).all()
    )
    return [await serialize_role(session, role) for role in roles]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    actor: UserRecord = Depends(require_permissions("roles:write")),
    session: AsyncSession = Depends(get_db),
):
    organization_id = data.organization_id or actor.organization_id
    if actor.role != "Super Owner" and organization_id != actor.organization_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot create roles outside your organization",
        )
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Role name is required")
    if name.casefold() == "super owner":
        raise HTTPException(
            status_code=422,
            detail="The Super Owner role is protected and cannot be created",
        )
    if await _role_name_exists(session, organization_id, name):
        raise HTTPException(
            status_code=409,
            detail="Role name already exists in this organization",
        )
    permissions = await resolve_permissions(session, data.permissions)
    assert_full_control_scope(
        name,
        [permission.code for permission in permissions],
    )

    role = Role(
        organization_id=organization_id,
        name=name,
        description=data.description.strip(),
        system=False,
        status="active",
    )
    session.add(role)
    await session.flush()
    session.add_all(
        [
            RolePermission(role_id=role.id, permission_id=permission.id)
            for permission in permissions
        ]
    )
    session.add(
        _audit(
            actor,
            role,
            "create",
            {"organization_id": organization_id},
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Role name already exists in this organization",
        ) from exc
    return await serialize_role(session, role)


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    actor: UserRecord = Depends(require_permissions("roles:read")),
    session: AsyncSession = Depends(get_db),
):
    role = await _get_role(session, role_id)
    assert_role_scope(actor, role)
    return await serialize_role(session, role)


@router.put("/{role_id}")
async def update_role(
    role_id: str,
    data: RoleUpdate,
    actor: UserRecord = Depends(require_permissions("roles:write")),
    session: AsyncSession = Depends(get_db),
):
    role = await _get_role(session, role_id)
    assert_role_scope(actor, role)
    if role.system and actor.role != "Super Owner":
        raise HTTPException(
            status_code=403,
            detail="Only the Super Owner can modify system roles",
        )

    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Role name is required")
        if name.casefold() == "super owner" and role.name != "Super Owner":
            raise HTTPException(
                status_code=422,
                detail="The Super Owner role name is reserved",
            )
        if role.name == "Super Owner" and name != role.name:
            raise HTTPException(
                status_code=422,
                detail="The Super Owner role cannot be renamed",
            )
        if await _role_name_exists(
            session,
            role.organization_id,
            name,
            exclude_id=role.id,
        ):
            raise HTTPException(
                status_code=409,
                detail="Role name already exists in this organization",
            )
        role.name = name
    if data.description is not None:
        role.description = data.description.strip()

    permission_codes: list[str] | None = None
    if data.permissions is not None:
        permissions = await resolve_permissions(session, data.permissions)
        permission_codes = [permission.code for permission in permissions]
        assert_full_control_scope(role.name, permission_codes)
        if role.name == "Super Owner" and "*" not in permission_codes:
            raise HTTPException(
                status_code=422,
                detail="The Super Owner role must retain full platform control",
            )
        await session.execute(
            delete(RolePermission).where(RolePermission.role_id == role.id)
        )
        session.add_all(
            [
                RolePermission(role_id=role.id, permission_id=permission.id)
                for permission in permissions
            ]
        )

    details = {"permissions": permission_codes} if permission_codes is not None else {}
    session.add(_audit(actor, role, "update", details))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Role name already exists in this organization",
        ) from exc
    return await serialize_role(session, role)


@router.delete("/{role_id}")
async def delete_role(
    role_id: str,
    actor: UserRecord = Depends(require_permissions("roles:write")),
    session: AsyncSession = Depends(get_db),
):
    role = await _get_role(session, role_id)
    assert_role_scope(actor, role)
    if role.system:
        raise HTTPException(
            status_code=422,
            detail="System roles cannot be deleted",
        )
    assigned_user_id = await session.scalar(
        select(User.id)
        .where(
            User.role_id == role.id,
            User.deleted_at.is_(None),
        )
        .limit(1)
    )
    if assigned_user_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Role is assigned to active users",
        )

    role.status = "deleted"
    session.add(_audit(actor, role, "delete"))
    await session.commit()
    return {"message": "Role deleted successfully"}
