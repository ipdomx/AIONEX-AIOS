"""Super Owner controls for Security Lab entitlements, policy and target inventory."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_super_owner
from app.db.base import get_db
from app.db.models import AuditEvent, SecurityAccessGrant, SecurityTarget
from app.services import security_fabric

router = APIRouter(prefix="/owner/security-lab", tags=["owner-security-lab"])


class GrantRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    level: Literal["standard", "advanced", "elite", "autonomous"]
    profiles: list[Literal["passive", "standard", "advanced", "elite"]] = Field(default_factory=list, max_length=4)
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ReleaseGatePolicy(BaseModel):
    block_confirmed_critical: bool | None = None
    block_confirmed_high: bool | None = None
    max_confirmed_medium: int | None = Field(default=None, ge=0, le=1000)
    require_tls: bool | None = None
    require_security_headers: bool | None = None
    require_backup_restore_evidence: bool | None = None


class PolicyUpdate(BaseModel):
    enabled: bool | None = None
    managed_domain_suffixes: list[str] | None = Field(default=None, max_length=100)
    max_concurrent_scans_per_user: int | None = Field(default=None, ge=1, le=10)
    max_scan_runtime_seconds: int | None = Field(default=None, ge=60, le=7200)
    active_on_verified_targets: bool | None = None
    deep_validation_requires_clone: bool | None = None
    learning_enabled: bool | None = None
    auto_rule_candidates: bool | None = None
    auto_remediation_enabled: bool | None = None
    release_gate: ReleaseGatePolicy | None = None


def grant_snapshot(grant: SecurityAccessGrant) -> dict[str, Any]:
    return {
        "id": grant.id,
        "user_id": grant.user_id,
        "level": grant.level,
        "status": grant.status,
        "profiles": grant.profiles,
        "notes": grant.notes,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
    }


@router.get("")
async def snapshot(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    grants = list((await session.scalars(select(SecurityAccessGrant).where(SecurityAccessGrant.organization_id == actor.organization_id).order_by(SecurityAccessGrant.updated_at.desc()))).all())
    targets = list((await session.scalars(select(SecurityTarget).where(SecurityTarget.organization_id == actor.organization_id).order_by(SecurityTarget.updated_at.desc()).limit(500))).all())
    return {
        "policy": await security_fabric.get_policy(session),
        "grants": [grant_snapshot(item) for item in grants],
        "targets": [security_fabric.target_snapshot(item) for item in targets],
    }


@router.patch("/policy")
async def patch_policy(
    data: PolicyUpdate,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    updates = data.model_dump(exclude_none=True)
    try:
        policy = await security_fabric.update_policy(session, updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id, action="security.policy.updated", resource_type="security_lab_policy", resource_id="default", details={"fields": sorted(updates)}))
    await session.commit()
    return policy


@router.post("/grants")
async def put_grant(
    data: GrantRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        grant = await security_fabric.grant_access(session, actor, **data.model_dump())
        await session.commit()
        await session.refresh(grant)
        return grant_snapshot(grant)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/grants/{user_id}/revoke")
async def revoke_grant(
    user_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        grant = await security_fabric.revoke_access(session, actor, user_id)
        await session.commit()
        await session.refresh(grant)
        return grant_snapshot(grant)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
