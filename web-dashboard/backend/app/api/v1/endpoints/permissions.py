"""Permission catalogue and role-assignment endpoints backed by PostgreSQL."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Permission,
    Role,
    RolePermission,
    User,
)

router = APIRouter()


class PermissionAssignment(BaseModel):
    permissions: list[str]


_CATEGORY_BY_RESOURCE = {
    "users": "identity",
    "profile": "identity",
    "organizations": "organization",
    "roles": "access",
    "permissions": "access",
    "audit": "security",
    "security": "security",
    "projects": "projects",
    "tasks": "projects",
    "workflows": "projects",
    "meetings": "collaboration",
    "notifications": "communications",
    "providers": "ai",
    "agents": "ai",
    "monitoring": "operations",
    "backups": "operations",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def permission_category(code: str) -> str:
    if code == "*":
        return "platform"
    resource = code.partition(":")[0]
    return _CATEGORY_BY_RESOURCE.get(resource, resource or "general")


def permission_name(code: str) -> str:
    if code == "*":
        return "Full Platform Control"
    resource, separator, action = code.partition(":")
    resource_name = resource.replace("_", " ").title()
    if not separator:
        return resource_name
    action_name = {
        "read": "Read",
        "write": "Manage",
        "approve": "Approve",
        "execute": "Execute",
    }.get(action, action.replace("_", " ").title())
    return f"{action_name} {resource_name}"


def assert_full_control_scope(
    role_name: str,
    permission_codes: list[str],
) -> None:
    if "*" in permission_codes and role_name != "Super Owner":
        raise HTTPException(
            status_code=422,
            detail=(
                "Full platform control can only be assigned to the protected "
                "Super Owner role"
            ),
        )


def serialize_permission(permission: Permission) -> dict[str, Any]:
    """Preserve the legacy permission response using relational columns."""
    return {
        "id": permission.id,
        "key": permission.code,
        "name": permission_name(permission.code),
        "description": permission.description or "",
        "category": permission_category(permission.code),
    }


async def get_role_permission_codes(
    session: AsyncSession,
    role_id: str,
) -> list[str]:
    return list(
        (
            await session.scalars(
                select(Permission.code)
                .join(
                    RolePermission,
                    RolePermission.permission_id == Permission.id,
                )
                .where(RolePermission.role_id == role_id)
                .order_by(Permission.code)
            )
        ).all()
    )


async def resolve_permissions(
    session: AsyncSession,
    permission_codes: list[str],
) -> list[Permission]:
    requested = sorted(set(permission_codes))
    if not requested:
        return []
    rows = list(
        (
            await session.scalars(
                select(Permission).where(Permission.code.in_(requested))
            )
        ).all()
    )
    by_code = {permission.code: permission for permission in rows}
    unknown = sorted(set(requested) - set(by_code))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={"unknown_permissions": unknown},
        )
    return [by_code[code] for code in requested]


async def get_active_role(session: AsyncSession, role_id: str) -> Role:
    role = await session.scalar(
        select(Role).where(
            Role.id == role_id,
            Role.status == "active",
        )
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


def assert_role_scope(actor: UserRecord, role: Role) -> None:
    if actor.role == "Super Owner":
        return
    if role.organization_id not in (None, actor.organization_id):
        raise HTTPException(
            status_code=403,
            detail="Cannot access roles outside your organization",
        )


async def serialize_role(
    session: AsyncSession,
    role: Role,
) -> dict[str, Any]:
    user_count = await session.scalar(
        select(func.count(User.id)).where(
            User.role_id == role.id,
            User.deleted_at.is_(None),
        )
    )
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description or "",
        "organization_id": role.organization_id,
        "permissions": await get_role_permission_codes(session, role.id),
        "is_system": role.system,
        "created_at": _iso(role.created_at),
        "updated_at": _iso(role.updated_at),
        "user_count": int(user_count or 0),
    }


def _audit(
    actor: UserRecord,
    role: Role,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=role.organization_id or actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="role",
        resource_id=role.id,
        details=details or {},
    )


@router.get("")
async def list_permissions(
    actor: UserRecord = Depends(require_permissions("permissions:read")),
    session: AsyncSession = Depends(get_db),
):
    del actor
    permissions = list(
        (await session.scalars(select(Permission).order_by(Permission.code))).all()
    )
    return sorted(
        (serialize_permission(permission) for permission in permissions),
        key=lambda item: (item["category"], item["name"]),
    )


@router.get("/catalogue")
async def permission_catalogue(
    actor: UserRecord = Depends(require_permissions("permissions:read")),
    session: AsyncSession = Depends(get_db),
):
    del actor
    permissions = list(
        (await session.scalars(select(Permission).order_by(Permission.code))).all()
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for permission in permissions:
        payload = serialize_permission(permission)
        grouped[payload["category"]].append(payload)
    return {"categories": dict(grouped), "total": len(permissions)}


@router.get("/roles/{role_id}")
async def get_role_permissions(
    role_id: str,
    actor: UserRecord = Depends(require_permissions("permissions:read")),
    session: AsyncSession = Depends(get_db),
):
    role = await get_active_role(session, role_id)
    assert_role_scope(actor, role)
    codes = await get_role_permission_codes(session, role.id)
    permissions = list(
        (
            await session.scalars(
                select(Permission)
                .where(Permission.code.in_(codes))
                .order_by(Permission.code)
            )
        ).all()
    )
    return {
        "role_id": role.id,
        "role": role.name,
        "permissions": [serialize_permission(permission) for permission in permissions],
    }


@router.put("/roles/{role_id}")
async def replace_role_permissions(
    role_id: str,
    data: PermissionAssignment,
    actor: UserRecord = Depends(require_permissions("permissions:write")),
    session: AsyncSession = Depends(get_db),
):
    role = await get_active_role(session, role_id)
    assert_role_scope(actor, role)
    if role.system and actor.role != "Super Owner":
        raise HTTPException(
            status_code=403,
            detail="Only the Super Owner can modify system roles",
        )

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
    session.add(
        _audit(
            actor,
            role,
            "replace_permissions",
            {"permissions": permission_codes},
        )
    )
    await session.commit()
    return await serialize_role(session, role)


@router.get("/effective/{user_id}")
async def effective_permissions(
    user_id: str,
    actor: UserRecord = Depends(require_permissions("permissions:read")),
    session: AsyncSession = Depends(get_db),
):
    user = await session.scalar(
        select(User).where(
            User.id == user_id,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot view permissions outside your organization",
        )
    if user.role_id is None:
        raise HTTPException(status_code=404, detail="Role not found")
    role = await get_active_role(session, user.role_id)
    return {
        "user_id": user.id,
        "role_id": role.id,
        "role": role.name,
        "permissions": await get_role_permission_codes(session, role.id),
    }
