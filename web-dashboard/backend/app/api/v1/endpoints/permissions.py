"""Permission catalogue and role-assignment endpoints."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import UserRecord, require_permissions
from app.core.identity_store import identity_store, utc_now

router = APIRouter()


class PermissionAssignment(BaseModel):
    permissions: list[str]


@router.get("")
async def list_permissions(actor: UserRecord = Depends(require_permissions("permissions:read"))):
    permissions = sorted(identity_store.permissions.values(), key=lambda permission: (permission.category, permission.name))
    return [identity_store.serialize_permission(permission) for permission in permissions]


@router.get("/catalogue")
async def permission_catalogue(actor: UserRecord = Depends(require_permissions("permissions:read"))):
    grouped: dict[str, list[dict]] = defaultdict(list)
    for permission in sorted(identity_store.permissions.values(), key=lambda item: item.name):
        grouped[permission.category].append(identity_store.serialize_permission(permission))
    return {"categories": dict(grouped), "total": len(identity_store.permissions)}


@router.get("/roles/{role_id}")
async def get_role_permissions(role_id: str, actor: UserRecord = Depends(require_permissions("permissions:read"))):
    role = identity_store.get_role(role_id)
    if actor.role != "Super Owner" and role.organization_id not in (None, actor.organization_id):
        raise HTTPException(status_code=403, detail="Cannot view permissions outside your organization")
    return {
        "role_id": role.id,
        "role": role.name,
        "permissions": [identity_store.serialize_permission(identity_store.permissions[key]) for key in role.permissions],
    }


@router.put("/roles/{role_id}")
async def replace_role_permissions(
    role_id: str,
    data: PermissionAssignment,
    actor: UserRecord = Depends(require_permissions("permissions:write")),
):
    role = identity_store.get_role(role_id)
    if actor.role != "Super Owner" and role.organization_id not in (None, actor.organization_id):
        raise HTTPException(status_code=403, detail="Cannot update permissions outside your organization")
    if role.is_system and actor.role != "Super Owner":
        raise HTTPException(status_code=403, detail="Only the Super Owner can modify system roles")
    unknown = sorted(set(data.permissions) - set(identity_store.permissions))
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_permissions": unknown})
    role.permissions = sorted(set(data.permissions))
    role.updated_at = utc_now()
    identity_store.record_audit(actor.id, "replace_permissions", "role", role.id, {"permissions": role.permissions})
    return identity_store.serialize_role(role)


@router.get("/effective/{user_id}")
async def effective_permissions(user_id: str, actor: UserRecord = Depends(require_permissions("permissions:read"))):
    user = identity_store.get_user(user_id)
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot view permissions outside your organization")
    role = identity_store.get_role(user.role_id)
    return {
        "user_id": user.id,
        "role_id": role.id,
        "role": role.name,
        "permissions": role.permissions,
    }
