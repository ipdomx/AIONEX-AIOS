"""Users endpoints backed by the centralized identity store."""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr

from app.core.auth import UserRecord, pwd_context, require_permissions
from app.core.identity_store import IdentityUserRecord, identity_store, utc_now

router = APIRouter()


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    role_id: str
    organization_id: str
    workspace_id: Optional[str] = None
    password: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role_id: Optional[str] = None
    status: Optional[str] = None
    avatar: Optional[str] = None
    workspace_id: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    avatar: Optional[str]
    role: str
    role_id: str
    permissions: list[str]
    status: str
    organization: str
    organization_id: str
    workspace: Optional[str]
    workspace_id: Optional[str]
    last_active: Optional[str]
    created_at: str
    updated_at: str


@router.get("", response_model=list[UserResponse])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    organization_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    role: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    actor: UserRecord = Depends(require_permissions("users:read")),
):
    users = [user for user in identity_store.users.values() if user.deleted_at is None]
    if actor.role != "Super Owner":
        users = [user for user in users if user.organization_id == actor.organization_id]
    if organization_id:
        users = [user for user in users if user.organization_id == organization_id]
    if workspace_id:
        users = [user for user in users if user.workspace_id == workspace_id]
    if role:
        users = [user for user in users if identity_store.get_role(user.role_id).name.lower() == role.lower()]
    if status_filter:
        users = [user for user in users if user.status == status_filter]
    if search:
        query = search.strip().lower()
        users = [user for user in users if query in user.name.lower() or query in user.email]
    users.sort(key=lambda user: user.created_at, reverse=True)
    return [identity_store.serialize_user(user) for user in users[skip : skip + limit]]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, actor: UserRecord = Depends(require_permissions("users:write"))):
    organization = identity_store.get_organization(data.organization_id)
    if actor.role != "Super Owner" and organization.id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot create users outside your organization")
    identity_store.get_role(data.role_id)
    if identity_store.find_user_by_email(data.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    raw_password = data.password or secrets.token_urlsafe(18)
    user = IdentityUserRecord(
        id=secrets.token_urlsafe(12),
        email=data.email.strip().lower(),
        name=data.name.strip(),
        role_id=data.role_id,
        organization_id=data.organization_id,
        workspace_id=data.workspace_id,
        password_hash=pwd_context.hash(raw_password),
        status="active",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    identity_store.users[user.id] = user
    identity_store.record_audit(actor.id, "create", "user", user.id, {"organization_id": user.organization_id})
    return {"user": identity_store.serialize_user(user), "temporary_password": raw_password if data.password is None else None}


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, actor: UserRecord = Depends(require_permissions("users:read"))):
    user = identity_store.get_user(user_id)
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot view users outside your organization")
    return identity_store.serialize_user(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, data: UserUpdate, actor: UserRecord = Depends(require_permissions("users:write"))):
    user = identity_store.get_user(user_id)
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot update users outside your organization")
    if data.role_id is not None:
        identity_store.get_role(data.role_id)
        user.role_id = data.role_id
    if data.name is not None:
        user.name = data.name.strip()
    if data.status is not None:
        user.status = data.status
    if data.avatar is not None:
        user.avatar = data.avatar
    if data.workspace_id is not None:
        user.workspace_id = data.workspace_id
    user.updated_at = utc_now()
    identity_store.record_audit(actor.id, "update", "user", user.id)
    return identity_store.serialize_user(user)


@router.delete("/{user_id}")
async def delete_user(user_id: str, actor: UserRecord = Depends(require_permissions("users:write"))):
    user = identity_store.get_user(user_id)
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot delete users outside your organization")
    if user.id == actor.id:
        raise HTTPException(status_code=422, detail="You cannot delete your own account")
    user.deleted_at = utc_now()
    user.status = "inactive"
    user.updated_at = utc_now()
    identity_store.record_audit(actor.id, "delete", "user", user.id)
    return {"message": "User deleted successfully"}


@router.get("/{user_id}/activity")
async def get_user_activity(user_id: str, limit: int = Query(20, ge=1, le=100), actor: UserRecord = Depends(require_permissions("audit:read"))):
    user = identity_store.get_user(user_id)
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot view activity outside your organization")
    return [event for event in identity_store.audit_events if event["actor_user_id"] == user_id or event["resource_id"] == user_id][:limit]


@router.get("/{user_id}/sessions")
async def get_user_sessions(user_id: str, actor: UserRecord = Depends(require_permissions("users:read"))):
    user = identity_store.get_user(user_id)
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot view sessions outside your organization")
    return identity_store.sessions.get(user_id, [])
