"""Users endpoints backed by the consolidated relational identity schema."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.permissions import (
    get_active_role,
    get_role_permission_codes,
)
from app.core.auth import UserRecord, pwd_context, require_permissions
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Organization,
    RefreshSession,
    Role,
    User,
)

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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _workspace_not_supported(workspace_id: str | None) -> None:
    if workspace_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "User workspace assignment is not persisted by the current "
                "identity schema"
            ),
        )


async def serialize_user(
    session: AsyncSession,
    user: User,
    *,
    role: Role | None = None,
    organization: Organization | None = None,
) -> dict[str, Any]:
    if role is None and user.role_id is not None:
        role = await session.get(Role, user.role_id)
    if organization is None:
        organization = await session.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=500, detail="User organization is missing")
    permission_codes = (
        await get_role_permission_codes(session, role.id) if role is not None else []
    )
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar": user.avatar,
        "role": role.name if role is not None else "Unassigned",
        "role_id": role.id if role is not None else (user.role_id or ""),
        "permissions": permission_codes,
        "status": user.status,
        "organization": organization.name,
        "organization_id": organization.id,
        # The current relational User model has no workspace or last-active
        # column. Return an honest null instead of an in-memory value.
        "workspace": None,
        "workspace_id": None,
        "last_active": None,
        "created_at": _iso(user.created_at),
        "updated_at": _iso(user.updated_at),
    }


async def get_user(
    session: AsyncSession,
    user_id: str,
) -> User:
    user = await session.scalar(
        select(User).where(
            User.id == user_id,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def assert_user_scope(actor: UserRecord, user: User, action: str) -> None:
    if actor.role != "Super Owner" and user.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot {action} users outside your organization",
        )


async def _target_role(session: AsyncSession, user: User) -> Role | None:
    return await session.get(Role, user.role_id) if user.role_id is not None else None


def _reject_super_owner_assignment(role: Role) -> None:
    if role.name == "Super Owner":
        raise HTTPException(
            status_code=422,
            detail=(
                "Super Owner assignments must be managed through the owner "
                "control plane"
            ),
        )


def _is_super_owner_role(role: Role | None) -> bool:
    return role is not None and role.name == "Super Owner"


def _audit(
    actor: UserRecord,
    user: User,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=user.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="user",
        resource_id=user.id,
        details=details or {},
    )


async def _revoke_sessions(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


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
    session: AsyncSession = Depends(get_db),
):
    # No workspace assignment exists in the current User schema, so a
    # workspace-filtered query has no honest matches.
    if workspace_id:
        return []

    statement = (
        select(User, Role, Organization)
        .outerjoin(Role, Role.id == User.role_id)
        .join(Organization, Organization.id == User.organization_id)
        .where(User.deleted_at.is_(None))
    )
    if actor.role != "Super Owner":
        statement = statement.where(User.organization_id == actor.organization_id)
    if organization_id:
        statement = statement.where(User.organization_id == organization_id)
    if role:
        statement = statement.where(Role.name.ilike(role.strip()))
    if status_filter:
        statement = statement.where(User.status == status_filter)
    if search:
        query = f"%{search.strip()}%"
        statement = statement.where(
            or_(User.name.ilike(query), User.email.ilike(query))
        )

    rows = (
        await session.execute(
            statement.order_by(User.created_at.desc()).offset(skip).limit(limit)
        )
    ).all()
    return [
        await serialize_user(
            session,
            user,
            role=user_role,
            organization=organization,
        )
        for user, user_role, organization in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    _workspace_not_supported(data.workspace_id)
    organization = await session.get(Organization, data.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if actor.role != "Super Owner" and organization.id != actor.organization_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot create users outside your organization",
        )
    role = await get_active_role(session, data.role_id)
    if role.organization_id not in (None, organization.id):
        raise HTTPException(
            status_code=422,
            detail="Role does not belong to the selected organization",
        )
    _reject_super_owner_assignment(role)

    normalized_email = data.email.strip().lower()
    if (
        await session.scalar(select(User.id).where(User.email == normalized_email))
        is not None
    ):
        raise HTTPException(status_code=409, detail="Email already registered")
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="User name is required")

    raw_password = data.password or secrets.token_urlsafe(18)
    user = User(
        email=normalized_email,
        name=name,
        role_id=role.id,
        organization_id=organization.id,
        password_hash=pwd_context.hash(raw_password),
        status="active",
    )
    session.add(user)
    await session.flush()
    session.add(
        _audit(
            actor,
            user,
            "create",
            {"organization_id": user.organization_id},
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Email already registered",
        ) from exc
    return {
        "user": await serialize_user(
            session,
            user,
            role=role,
            organization=organization,
        ),
        "temporary_password": raw_password if data.password is None else None,
    }


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_endpoint(
    user_id: str,
    actor: UserRecord = Depends(require_permissions("users:read")),
    session: AsyncSession = Depends(get_db),
):
    user = await get_user(session, user_id)
    assert_user_scope(actor, user, "view")
    return await serialize_user(session, user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: UserUpdate,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    _workspace_not_supported(data.workspace_id)
    user = await get_user(session, user_id)
    assert_user_scope(actor, user, "update")
    existing_role = await _target_role(session, user)

    if data.role_id is not None:
        if user.id == actor.id and data.role_id != user.role_id:
            raise HTTPException(
                status_code=422,
                detail="You cannot change your own role",
            )
        role = await get_active_role(session, data.role_id)
        if role.organization_id not in (None, user.organization_id):
            raise HTTPException(
                status_code=422,
                detail="Role does not belong to the user's organization",
            )
        if _is_super_owner_role(existing_role) and role.id != existing_role.id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Super Owner role changes must be managed through the owner "
                    "control plane"
                ),
            )
        if not _is_super_owner_role(existing_role):
            _reject_super_owner_assignment(role)
        user.role_id = role.id
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="User name is required")
        user.name = name
    if data.status is not None:
        if _is_super_owner_role(existing_role) and data.status not in {
            "active",
            "online",
        }:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Super Owner accounts cannot be deactivated through the "
                    "standard users API"
                ),
            )
        if user.id == actor.id and data.status not in {"active", "online"}:
            raise HTTPException(
                status_code=422,
                detail="You cannot deactivate your own account",
            )
        user.status = data.status
        if data.status not in {"active", "online"}:
            await _revoke_sessions(session, user.id)
    if data.avatar is not None:
        user.avatar = data.avatar

    session.add(_audit(actor, user, "update"))
    await session.commit()
    return await serialize_user(session, user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    user = await get_user(session, user_id)
    assert_user_scope(actor, user, "delete")
    if user.id == actor.id:
        raise HTTPException(
            status_code=422,
            detail="You cannot delete your own account",
        )
    role = await _target_role(session, user)
    if _is_super_owner_role(role):
        raise HTTPException(
            status_code=422,
            detail="Super Owner accounts cannot be deleted",
        )

    user.deleted_at = datetime.now(UTC)
    user.status = "inactive"
    await _revoke_sessions(session, user.id)
    session.add(_audit(actor, user, "delete"))
    await session.commit()
    return {"message": "User deleted successfully"}


def _serialize_audit(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "actor_user_id": event.user_id,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "metadata": event.details or {},
        "timestamp": _iso(event.created_at),
    }


@router.get("/{user_id}/activity")
async def get_user_activity(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("audit:read")),
    session: AsyncSession = Depends(get_db),
):
    user = await get_user(session, user_id)
    assert_user_scope(actor, user, "view activity for")
    events = list(
        (
            await session.scalars(
                select(AuditEvent)
                .where(
                    or_(
                        AuditEvent.user_id == user_id,
                        AuditEvent.resource_id == user_id,
                    )
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [_serialize_audit(event) for event in events]


@router.get("/{user_id}/sessions")
async def get_user_sessions(
    user_id: str,
    actor: UserRecord = Depends(require_permissions("users:read")),
    session: AsyncSession = Depends(get_db),
):
    user = await get_user(session, user_id)
    assert_user_scope(actor, user, "view sessions for")
    sessions = list(
        (
            await session.scalars(
                select(RefreshSession)
                .where(RefreshSession.user_id == user.id)
                .order_by(RefreshSession.created_at.desc())
            )
        ).all()
    )
    return [
        {
            "id": refresh_session.id,
            "user_id": refresh_session.user_id,
            "expires_at": _iso(refresh_session.expires_at),
            "revoked_at": _iso(refresh_session.revoked_at),
            "ip_address": refresh_session.ip_address,
            "user_agent": refresh_session.user_agent,
            "created_at": _iso(refresh_session.created_at),
            "updated_at": _iso(refresh_session.updated_at),
        }
        for refresh_session in sessions
    ]
