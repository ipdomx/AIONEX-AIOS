"""Organization management endpoints."""

from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.auth import UserRecord, require_permissions
from app.core.identity_store import OrganizationRecord, identity_store, utc_now

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


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=422, detail="Organization slug is invalid")
    return slug


def assert_scope(actor: UserRecord, organization_id: str) -> None:
    if actor.role != "Super Owner" and actor.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Cannot access organizations outside your scope")


@router.get("")
async def list_organizations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(require_permissions("organizations:read")),
):
    organizations = list(identity_store.organizations.values())
    if actor.role != "Super Owner":
        organizations = [organization for organization in organizations if organization.id == actor.organization_id]
    organizations.sort(key=lambda organization: organization.created_at, reverse=True)
    return [identity_store.serialize_organization(organization) for organization in organizations[skip : skip + limit]]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    actor: UserRecord = Depends(require_permissions("organizations:write")),
):
    if actor.role != "Super Owner":
        raise HTTPException(status_code=403, detail="Only the Super Owner can create additional organizations")
    slug = normalize_slug(data.slug or data.name)
    if any(organization.slug == slug for organization in identity_store.organizations.values()):
        raise HTTPException(status_code=409, detail="Organization slug already exists")
    organization = OrganizationRecord(
        id=secrets.token_urlsafe(10),
        name=data.name.strip(),
        slug=slug,
        plan=data.plan,
    )
    identity_store.organizations[organization.id] = organization
    identity_store.record_audit(actor.id, "create", "organization", organization.id)
    return identity_store.serialize_organization(organization)


@router.get("/{organization_id}")
async def get_organization(
    organization_id: str,
    actor: UserRecord = Depends(require_permissions("organizations:read")),
):
    assert_scope(actor, organization_id)
    return identity_store.serialize_organization(identity_store.get_organization(organization_id))


@router.put("/{organization_id}")
async def update_organization(
    organization_id: str,
    data: OrganizationUpdate,
    actor: UserRecord = Depends(require_permissions("organizations:write")),
):
    assert_scope(actor, organization_id)
    organization = identity_store.get_organization(organization_id)
    if data.name is not None:
        organization.name = data.name.strip()
    if data.slug is not None:
        slug = normalize_slug(data.slug)
        if any(item.id != organization.id and item.slug == slug for item in identity_store.organizations.values()):
            raise HTTPException(status_code=409, detail="Organization slug already exists")
        organization.slug = slug
    if data.plan is not None:
        organization.plan = data.plan
    if data.status is not None:
        organization.status = data.status
    organization.updated_at = utc_now()
    identity_store.record_audit(actor.id, "update", "organization", organization.id)
    return identity_store.serialize_organization(organization)


@router.get("/{organization_id}/members")
async def list_organization_members(
    organization_id: str,
    actor: UserRecord = Depends(require_permissions("users:read")),
):
    assert_scope(actor, organization_id)
    identity_store.get_organization(organization_id)
    return [
        identity_store.serialize_user(user)
        for user in identity_store.users.values()
        if user.organization_id == organization_id and user.deleted_at is None
    ]


@router.delete("/{organization_id}")
async def deactivate_organization(
    organization_id: str,
    actor: UserRecord = Depends(require_permissions("organizations:write")),
):
    if actor.role != "Super Owner":
        raise HTTPException(status_code=403, detail="Only the Super Owner can deactivate organizations")
    if organization_id == "aionex-org":
        raise HTTPException(status_code=422, detail="The platform organization cannot be deactivated")
    organization = identity_store.get_organization(organization_id)
    organization.status = "inactive"
    organization.updated_at = utc_now()
    for user in identity_store.users.values():
        if user.organization_id == organization_id and user.deleted_at is None:
            user.status = "inactive"
            user.updated_at = utc_now()
    identity_store.record_audit(actor.id, "deactivate", "organization", organization.id)
    return {"message": "Organization deactivated successfully"}
