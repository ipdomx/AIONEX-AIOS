"""Owner licensing adapter backed by shared organization identity state."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import UserRecord, current_user
from app.core.identity_store import OrganizationRecord, identity_store, utc_now

router = APIRouter(prefix="/owner/licenses", tags=["owner-licensing"])

LicensePlan = Literal["enterprise", "professional", "starter"]
LicenseStatus = Literal["active", "expiring", "suspended", "pending"]
LicenseAction = Literal["renew", "suspend", "restore"]


class LicenseRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    organization: str
    plan: LicensePlan
    seats: int = Field(ge=0)
    active_seats: int = Field(alias="activeSeats", ge=0)
    status: LicenseStatus
    expires_at: str = Field(alias="expiresAt")
    monthly_value: float = Field(alias="monthlyValue", ge=0)


class LicenseUpdate(BaseModel):
    action: LicenseAction
    seats: int | None = Field(default=None, ge=1)


def _is_super_owner(actor: UserRecord) -> bool:
    normalized = " ".join(
        actor.role.strip().lower().replace("_", " ").replace("-", " ").split()
    )
    return normalized == "super owner"


def _plan(value: str) -> LicensePlan:
    normalized = value.strip().lower()
    if normalized not in {"enterprise", "professional", "starter"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization has unsupported license plan: {value}",
        )
    return cast(LicensePlan, normalized)


def _status(value: str) -> LicenseStatus:
    normalized = value.strip().lower()
    if normalized in {"active", "online"}:
        return "active"
    if normalized in {"inactive", "suspended", "blocked"}:
        return "suspended"
    return "pending"


def _license_record(organization: OrganizationRecord) -> LicenseRecord:
    members = [
        user
        for user in identity_store.users.values()
        if user.organization_id == organization.id and user.deleted_at is None
    ]
    active_members = sum(1 for user in members if user.status in {"active", "online"})
    return LicenseRecord(
        id=organization.id,
        organization=organization.name,
        plan=_plan(organization.plan),
        seats=len(members),
        active_seats=active_members,
        status=_status(organization.status),
        expires_at="Not configured",
        monthly_value=0,
    )


def build_license_records(actor: UserRecord) -> list[LicenseRecord]:
    organizations = [
        organization
        for organization in identity_store.organizations.values()
        if _is_super_owner(actor) or organization.id == actor.organization_id
    ]
    return [
        _license_record(organization)
        for organization in sorted(organizations, key=lambda item: item.name.lower())
    ]


@router.get("", response_model=list[LicenseRecord])
def list_owner_licenses(
    actor: UserRecord = Depends(current_user),
) -> list[LicenseRecord]:
    return build_license_records(actor)


@router.patch("/{license_id}", response_model=LicenseRecord)
def update_owner_license(
    license_id: str,
    update: LicenseUpdate,
    actor: UserRecord = Depends(current_user),
) -> LicenseRecord:
    organization = identity_store.organizations.get(license_id)
    if organization is None or (
        not _is_super_owner(actor) and organization.id != actor.organization_id
    ):
        raise HTTPException(status_code=404, detail="License not found")
    if update.seats is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seat capacity is not stored by the current organization registry",
        )
    if update.action == "renew":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License renewal requires an entitlement expiry record",
        )

    organization.status = "suspended" if update.action == "suspend" else "active"
    organization.updated_at = utc_now()
    identity_store.record_audit(
        actor.id,
        update.action,
        "organization_license",
        organization.id,
    )
    return _license_record(organization)
