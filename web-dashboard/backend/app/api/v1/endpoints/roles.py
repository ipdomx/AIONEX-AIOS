"""Role management endpoints."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import UserRecord, require_permissions
from app.core.identity_store import RoleRecord, identity_store, utc_now

router = APIRouter()


class RoleCreate(BaseModel):
    name: str
    description: str = ""
    organization_id: str | None = None
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


def assert_role_scope(actor: UserRecord, role: RoleRecord) -> None:
    if actor.role == "Super Owner":
        return
    if role.organization_id not in (None, actor.organization_id):
        raise HTTPException(status_code=403, detail="Cannot access roles outside your organization")


def validate_permissions(permission_keys: list[str]) -> list[str]:
    unknown = sorted(set(permission_keys) - set(identity_store.permissions))
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_permissions": unknown})
    return sorted(set(permission_keys))


@router.get("")
async def list_roles(actor: UserRecord = Depends(require_permissions("roles:read"))):
    roles = list(identity_store.roles.values())
    if actor.role != "Super Owner":
        roles = [role for role in roles if role.organization_id in (None, actor.organization_id)]
    roles.sort(key=lambda role: (not role.is_system, role.name.lower()))
    return [identity_store.serialize_role(role) for role in roles]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_role(data: RoleCreate, actor: UserRecord = Depends(require_permissions("roles:write"))):
    organization_id = data.organization_id or actor.organization_id
    if actor.role != "Super Owner" and organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot create roles outside your organization")
    identity_store.get_organization(organization_id)
    if any(role.name.lower() == data.name.strip().lower() and role.organization_id == organization_id for role in identity_store.roles.values()):
        raise HTTPException(status_code=409, detail="Role name already exists in this organization")
    role = RoleRecord(
        id=secrets.token_urlsafe(10),
        name=data.name.strip(),
        description=data.description.strip(),
        organization_id=organization_id,
        permissions=validate_permissions(data.permissions),
    )
    identity_store.roles[role.id] = role
    identity_store.record_audit(actor.id, "create", "role", role.id, {"organization_id": organization_id})
    return identity_store.serialize_role(role)


@router.get("/{role_id}")
async def get_role(role_id: str, actor: UserRecord = Depends(require_permissions("roles:read"))):
    role = identity_store.get_role(role_id)
    assert_role_scope(actor, role)
    return identity_store.serialize_role(role)


@router.put("/{role_id}")
async def update_role(role_id: str, data: RoleUpdate, actor: UserRecord = Depends(require_permissions("roles:write"))):
    role = identity_store.get_role(role_id)
    assert_role_scope(actor, role)
    if role.is_system and actor.role != "Super Owner":
        raise HTTPException(status_code=403, detail="Only the Super Owner can modify system roles")
    if data.name is not None:
        role.name = data.name.strip()
    if data.description is not None:
        role.description = data.description.strip()
    if data.permissions is not None:
        role.permissions = validate_permissions(data.permissions)
    role.updated_at = utc_now()
    identity_store.record_audit(actor.id, "update", "role", role.id)
    return identity_store.serialize_role(role)


@router.delete("/{role_id}")
async def delete_role(role_id: str, actor: UserRecord = Depends(require_permissions("roles:write"))):
    role = identity_store.get_role(role_id)
    assert_role_scope(actor, role)
    if role.is_system:
        raise HTTPException(status_code=422, detail="System roles cannot be deleted")
    if any(user.role_id == role.id and user.deleted_at is None for user in identity_store.users.values()):
        raise HTTPException(status_code=409, detail="Role is assigned to active users")
    del identity_store.roles[role.id]
    identity_store.record_audit(actor.id, "delete", "role", role.id)
    return {"message": "Role deleted successfully"}
