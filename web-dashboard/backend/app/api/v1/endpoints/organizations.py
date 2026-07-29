"""Organization management endpoints backed by the relational identity schema."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.users import serialize_user
from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    Organization,
    RefreshSession,
    Role,
    User,
)

router = APIRouter()


class OrganizationCreate(BaseModel):
    name: str
    slug: str | None = None
    plan: str = "enterprise"


class OrganizationUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    plan: str | None = None
    status: str | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise HTTPException(
            status_code=422,
            detail="Organization slug is invalid",
        )
    return slug


def assert_scope(actor: UserRecord, organization_id: str) -> None:
    if actor.role != "Super Owner" and actor.organization_id != organization_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot access organizations outside your scope",
        )


async def _get_organization(
    session: AsyncSession,
    organization_id: str,
) -> Organization:
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


async def _serialize_organization(
    session: AsyncSession,
    organization: Organization,
) -> dict[str, Any]:
    member_count = await session.scalar(
        select(func.count(User.id)).where(
            User.organization_id == organization.id,
            User.deleted_at.is_(None),
        )
    )
    role_count = await session.scalar(
        select(func.count(Role.id)).where(
            Role.status != "deleted",
            or_(
                Role.organization_id.is_(None),
                Role.organization_id == organization.id,
            ),
        )
    )
    owner_user_id = await session.scalar(
        select(User.id)
        .join(Role, Role.id == User.role_id)
        .where(
            User.organization_id == organization.id,
            User.deleted_at.is_(None),
            Role.status != "deleted",
            Role.name.in_(("Super Owner", "Owner")),
        )
        .order_by(
            (Role.name == "Super Owner").desc(),
            User.created_at,
        )
        .limit(1)
    )
    return {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "plan": organization.plan,
        "status": organization.status,
        "owner_user_id": owner_user_id,
        "created_at": _iso(organization.created_at),
        "updated_at": _iso(organization.updated_at),
        "member_count": int(member_count or 0),
        "role_count": int(role_count or 0),
    }


def _audit(
    actor: UserRecord,
    organization: Organization,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=organization.id,
        user_id=actor.id,
        action=action,
        resource_type="organization",
        resource_id=organization.id,
        details=details or {},
    )


async def _deactivate_members(
    session: AsyncSession,
    organization_id: str,
) -> None:
    now = datetime.now(UTC)
    user_ids = select(User.id).where(
        User.organization_id == organization_id,
        User.deleted_at.is_(None),
    )
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id.in_(user_ids),
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.execute(
        update(User)
        .where(
            User.organization_id == organization_id,
            User.deleted_at.is_(None),
        )
        .values(status="inactive", updated_at=now)
    )


@router.get("")
async def list_organizations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("organizations:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Organization)
    if actor.role != "Super Owner":
        statement = statement.where(Organization.id == actor.organization_id)
    organizations = list(
        (
            await session.scalars(
                statement.order_by(Organization.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
        ).all()
    )
    return [
        await _serialize_organization(session, organization)
        for organization in organizations
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    actor: UserRecord = Depends(require_permissions("organizations:write")),
    session: AsyncSession = Depends(get_db),
):
    if actor.role != "Super Owner":
        raise HTTPException(
            status_code=403,
            detail="Only the Super Owner can create additional organizations",
        )
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Organization name is required")
    slug = normalize_slug(data.slug or name)
    if (
        await session.scalar(select(Organization.id).where(Organization.slug == slug))
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Organization slug already exists",
        )

    organization = Organization(
        name=name,
        slug=slug,
        plan=data.plan,
        status="active",
    )
    session.add(organization)
    await session.flush()
    session.add(_audit(actor, organization, "create"))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Organization slug already exists",
        ) from exc
    return await _serialize_organization(session, organization)


@router.get("/{organization_id}")
async def get_organization(
    organization_id: str,
    actor: UserRecord = Depends(require_permissions("organizations:read")),
    session: AsyncSession = Depends(get_db),
):
    assert_scope(actor, organization_id)
    organization = await _get_organization(session, organization_id)
    return await _serialize_organization(session, organization)


@router.put("/{organization_id}")
async def update_organization(
    organization_id: str,
    data: OrganizationUpdate,
    actor: UserRecord = Depends(require_permissions("organizations:write")),
    session: AsyncSession = Depends(get_db),
):
    assert_scope(actor, organization_id)
    organization = await _get_organization(session, organization_id)
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(
                status_code=422,
                detail="Organization name is required",
            )
        organization.name = name
    if data.slug is not None:
        slug = normalize_slug(data.slug)
        duplicate_id = await session.scalar(
            select(Organization.id).where(
                Organization.slug == slug,
                Organization.id != organization.id,
            )
        )
        if duplicate_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Organization slug already exists",
            )
        organization.slug = slug
    if data.plan is not None:
        organization.plan = data.plan
    if data.status is not None:
        if organization.id == "aionex-org" and data.status not in {"active", "trial"}:
            raise HTTPException(
                status_code=422,
                detail="The platform organization cannot be deactivated",
            )
        organization.status = data.status
        if data.status not in {"active", "trial"}:
            await _deactivate_members(session, organization.id)

    session.add(_audit(actor, organization, "update"))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Organization slug already exists",
        ) from exc
    return await _serialize_organization(session, organization)


@router.get("/{organization_id}/members")
async def list_organization_members(
    organization_id: str,
    actor: UserRecord = Depends(require_permissions("users:read")),
    session: AsyncSession = Depends(get_db),
):
    assert_scope(actor, organization_id)
    organization = await _get_organization(session, organization_id)
    rows = (
        await session.execute(
            select(User, Role)
            .outerjoin(Role, Role.id == User.role_id)
            .where(
                User.organization_id == organization.id,
                User.deleted_at.is_(None),
            )
            .order_by(User.created_at.desc())
        )
    ).all()
    return [
        await serialize_user(
            session,
            user,
            role=role,
            organization=organization,
        )
        for user, role in rows
    ]


@router.delete("/{organization_id}")
async def deactivate_organization(
    organization_id: str,
    actor: UserRecord = Depends(require_permissions("organizations:write")),
    session: AsyncSession = Depends(get_db),
):
    if actor.role != "Super Owner":
        raise HTTPException(
            status_code=403,
            detail="Only the Super Owner can deactivate organizations",
        )
    if organization_id == "aionex-org":
        raise HTTPException(
            status_code=422,
            detail="The platform organization cannot be deactivated",
        )
    organization = await _get_organization(session, organization_id)
    organization.status = "inactive"
    await _deactivate_members(session, organization.id)
    session.add(_audit(actor, organization, "deactivate"))
    await session.commit()
    return {"message": "Organization deactivated successfully"}
