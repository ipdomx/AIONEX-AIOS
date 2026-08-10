"""Entitlement-gated Security Lab API for authorized project targets."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, get_current_user
from app.db.base import get_db
from app.db.models import SecurityFinding, SecurityScan, SecurityTarget
from app.services import security_fabric, security_scanning

router = APIRouter()


class ManagedTargetRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=36)
    origin: str = Field(min_length=8, max_length=500)
    environment: Literal["production", "staging", "security_clone"] = "production"


class ExternalTargetRequest(BaseModel):
    origin: str = Field(min_length=8, max_length=500)


class ExternalVerifyRequest(BaseModel):
    challenge: str = Field(min_length=20, max_length=300)


class ScanRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=36)
    profile: Literal["passive", "standard", "advanced", "elite"] = "passive"


async def _require_access(session: AsyncSession, actor: UserRecord) -> str:
    level = await security_fabric.access_level(session, actor)
    if level is None:
        raise HTTPException(status_code=403, detail="Security Lab access is controlled by the Super Owner")
    return level


@router.get("/access")
async def access(actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    policy = await security_fabric.get_policy(session)
    level = await security_fabric.access_level(session, actor)
    return {
        "enabled": bool(policy["enabled"]),
        "granted": level is not None,
        "level": level,
        "profiles": [profile for profile in security_fabric.PROFILE_RANK if security_fabric.profile_allowed(level, profile)],
        "deep_validation_requires_clone": policy["deep_validation_requires_clone"],
    }


@router.get("/tools")
async def tools(actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    from app.services.security_tools import catalog_snapshot
    return catalog_snapshot()


@router.get("/targets")
async def targets(actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    rows = list((await session.scalars(select(SecurityTarget).where(SecurityTarget.organization_id == actor.organization_id, SecurityTarget.status == "active").order_by(SecurityTarget.updated_at.desc()))).all())
    return [security_fabric.target_snapshot(item) for item in rows]


@router.post("/targets/managed", status_code=status.HTTP_201_CREATED)
async def managed_target(data: ManagedTargetRequest, actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    try:
        target = await security_fabric.register_managed_target(session, actor, **data.model_dump())
        await session.commit()
        await session.refresh(target)
        return security_fabric.target_snapshot(target)
    except PermissionError as exc:
        await session.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback(); raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback(); raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/targets/external", status_code=status.HTTP_201_CREATED)
async def external_target(data: ExternalTargetRequest, actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    try:
        target, challenge = await security_fabric.register_external_target(session, actor, origin=data.origin)
        await session.commit(); await session.refresh(target)
        return {**security_fabric.target_snapshot(target), "verification": {"method": "http_file", "path": "/.well-known/aionex-security-verification.txt", "challenge": challenge}}
    except ValueError as exc:
        await session.rollback(); raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/targets/{target_id}/verify")
async def verify_target(target_id: str, data: ExternalVerifyRequest, actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    target = await session.scalar(select(SecurityTarget).where(SecurityTarget.id == target_id, SecurityTarget.organization_id == actor.organization_id).with_for_update())
    if target is None: raise HTTPException(status_code=404, detail="Security target not found")
    try:
        await security_fabric.verify_external_target(session, actor, target, challenge=data.challenge)
        await session.commit(); await session.refresh(target)
        return security_fabric.target_snapshot(target)
    except PermissionError as exc:
        await session.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback(); raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
async def create_scan(data: ScanRequest, actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    try:
        scan = await security_scanning.request_scan(session, actor, target_id=data.target_id, profile=data.profile)
        await session.commit(); await session.refresh(scan)
        return security_scanning.scan_snapshot(scan)
    except PermissionError as exc:
        await session.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback(); raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        await session.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback(); raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scans")
async def scans(limit: int = Query(default=100, ge=1, le=500), actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    stmt = select(SecurityScan).where(SecurityScan.organization_id == actor.organization_id)
    if actor.role != "Super Owner": stmt = stmt.where(SecurityScan.requested_by_id == actor.id)
    rows = list((await session.scalars(stmt.order_by(SecurityScan.created_at.desc()).limit(limit))).all())
    return [security_scanning.scan_snapshot(item) for item in rows]


@router.get("/scans/{scan_id}/findings")
async def findings(scan_id: str, actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    scan = await session.scalar(select(SecurityScan).where(SecurityScan.id == scan_id, SecurityScan.organization_id == actor.organization_id))
    if scan is None or (actor.role != "Super Owner" and scan.requested_by_id != actor.id): raise HTTPException(status_code=404, detail="Security scan not found")
    rows = list((await session.scalars(select(SecurityFinding).where(SecurityFinding.scan_id == scan.id).order_by(SecurityFinding.severity, SecurityFinding.created_at))).all())
    return [security_scanning.finding_snapshot(item) for item in rows]


@router.post("/scans/{scan_id}/cancel")
async def cancel_scan(scan_id: str, actor: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    await _require_access(session, actor)
    scan = await session.scalar(select(SecurityScan).where(SecurityScan.id == scan_id, SecurityScan.organization_id == actor.organization_id).with_for_update())
    if scan is None or (actor.role != "Super Owner" and scan.requested_by_id != actor.id): raise HTTPException(status_code=404, detail="Security scan not found")
    if scan.status in {"queued", "running"}:
        from app.services.security_scanning import now
        scan.status = "cancelled"; scan.cancelled_at = now(); scan.lease_token = None
        await session.commit(); await session.refresh(scan)
    return security_scanning.scan_snapshot(scan)
