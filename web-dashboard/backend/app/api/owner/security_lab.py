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
    profiles: list[Literal["passive", "standard", "advanced", "elite"]] = Field(
        default_factory=list, max_length=4
    )
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
    grants = list(
        (
            await session.scalars(
                select(SecurityAccessGrant)
                .where(SecurityAccessGrant.organization_id == actor.organization_id)
                .order_by(SecurityAccessGrant.updated_at.desc())
            )
        ).all()
    )
    targets = list(
        (
            await session.scalars(
                select(SecurityTarget)
                .where(SecurityTarget.organization_id == actor.organization_id)
                .order_by(SecurityTarget.updated_at.desc())
                .limit(500)
            )
        ).all()
    )
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
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.policy.updated",
            resource_type="security_lab_policy",
            resource_id="default",
            details={"fields": sorted(updates)},
        )
    )
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


class FindingDecision(BaseModel):
    state: Literal["confirmed", "false_positive", "resolved"]
    note: str | None = Field(default=None, max_length=5000)


def rule_snapshot(rule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "source_finding_id": rule.source_finding_id,
        "rule_type": rule.rule_type,
        "name": rule.name,
        "signature": rule.signature,
        "detector": rule.detector,
        "status": rule.status,
        "trust_score": rule.trust_score,
        "validation_passes": rule.validation_passes,
        "validation_failures": rule.validation_failures,
        "promoted_at": rule.promoted_at.isoformat() if rule.promoted_at else None,
    }


@router.get("/scans")
async def owner_scans(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityScan
    from app.services.security_scanning import scan_snapshot

    rows = list(
        (
            await session.scalars(
                select(SecurityScan)
                .where(SecurityScan.organization_id == actor.organization_id)
                .order_by(SecurityScan.created_at.desc())
                .limit(500)
            )
        ).all()
    )
    return [scan_snapshot(item) for item in rows]


@router.get("/findings")
async def owner_findings(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityFinding
    from app.services.security_scanning import finding_snapshot

    rows = list(
        (
            await session.scalars(
                select(SecurityFinding)
                .where(SecurityFinding.organization_id == actor.organization_id)
                .order_by(SecurityFinding.created_at.desc())
                .limit(1000)
            )
        ).all()
    )
    return [finding_snapshot(item) for item in rows]


@router.post("/findings/{finding_id}/decision")
async def decide_finding(
    finding_id: str,
    data: FindingDecision,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from datetime import UTC, datetime
    from app.db.models import SecurityFinding
    from app.services import security_rule_forge

    finding = await session.scalar(
        select(SecurityFinding)
        .where(
            SecurityFinding.id == finding_id,
            SecurityFinding.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="Security finding not found")
    finding.state = data.state
    finding.verified_by_id = actor.id
    finding.verified_at = datetime.now(UTC)
    if data.state == "resolved":
        finding.resolved_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=f"security.finding.{data.state}",
            resource_type="security_finding",
            resource_id=finding.id,
            details={"note": data.note},
        )
    )
    rule = None
    policy = await security_fabric.get_policy(session)
    if data.state == "confirmed" and policy.get("auto_rule_candidates", True):
        rule = await security_rule_forge.derive_candidate(session, actor, finding)
    await session.commit()
    return {
        "finding_id": finding.id,
        "state": finding.state,
        "rule": rule_snapshot(rule) if rule else None,
    }


@router.get("/rules")
async def owner_rules(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityRule

    rows = list(
        (
            await session.scalars(
                select(SecurityRule)
                .where(SecurityRule.organization_id == actor.organization_id)
                .order_by(SecurityRule.updated_at.desc())
                .limit(1000)
            )
        ).all()
    )
    return [rule_snapshot(item) for item in rows]


@router.post("/rules/{rule_id}/validate")
async def validate_rule(
    rule_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityRule
    from app.services import security_rule_forge

    rule = await session.scalar(
        select(SecurityRule)
        .where(
            SecurityRule.id == rule_id,
            SecurityRule.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Security rule not found")
    await security_rule_forge.validate_candidate(session, actor, rule)
    await session.commit()
    await session.refresh(rule)
    return rule_snapshot(rule)


@router.post("/rules/{rule_id}/promote")
async def promote_rule(
    rule_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityRule
    from app.services import security_rule_forge

    rule = await session.scalar(
        select(SecurityRule)
        .where(
            SecurityRule.id == rule_id,
            SecurityRule.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Security rule not found")
    try:
        await security_rule_forge.promote_rule(session, actor, rule)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(rule)
    return rule_snapshot(rule)


class ReleaseGateRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=36)


@router.get("/release-gates")
async def release_gates(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityReleaseGate
    from app.services.security_release_gate import gate_snapshot

    rows = list(
        (
            await session.scalars(
                select(SecurityReleaseGate)
                .where(SecurityReleaseGate.organization_id == actor.organization_id)
                .order_by(SecurityReleaseGate.created_at.desc())
                .limit(500)
            )
        ).all()
    )
    return [gate_snapshot(item) for item in rows]


@router.post("/release-gates")
async def evaluate_release_gate(
    data: ReleaseGateRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.services import security_release_gate

    try:
        item = await security_release_gate.create_release_gate(
            session, actor, scan_id=data.scan_id
        )
        await session.commit()
        await session.refresh(item)
        return security_release_gate.gate_snapshot(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/eligible-users")
async def eligible_users(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import Role, User

    rows = (
        await session.execute(
            select(User.id, User.name, User.email, User.status, Role.name.label("role"))
            .outerjoin(Role, Role.id == User.role_id)
            .where(
                User.organization_id == actor.organization_id, User.deleted_at.is_(None)
            )
            .order_by(User.name, User.email)
            .limit(1000)
        )
    ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "email": row.email,
            "status": row.status,
            "role": row.role or "Unassigned",
        }
        for row in rows
    ]


class CloneTargetRequest(BaseModel):
    source_target_id: str = Field(min_length=1, max_length=36)
    origin: str = Field(min_length=8, max_length=500)


@router.post("/clone-targets")
async def register_clone_target(
    data: CloneTargetRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        target = await security_fabric.register_security_clone_target(
            session, actor, source_target_id=data.source_target_id, origin=data.origin
        )
        await session.commit()
        await session.refresh(target)
        return security_fabric.target_snapshot(target)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ManagedTargetRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=36)
    origin: str = Field(min_length=8, max_length=500)
    environment: Literal["production", "staging"] = "production"


@router.get("/eligible-projects")
async def eligible_projects(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import Project

    rows = list(
        (
            await session.scalars(
                select(Project)
                .where(
                    Project.organization_id == actor.organization_id,
                    Project.status != "deleted",
                )
                .order_by(Project.updated_at.desc())
                .limit(1000)
            )
        ).all()
    )
    return [
        {
            "id": item.id,
            "name": item.name,
            "status": item.status,
            "owner_id": item.owner_id,
        }
        for item in rows
    ]


@router.post("/managed-targets")
async def register_owner_managed_target(
    data: ManagedTargetRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    try:
        target = await security_fabric.register_managed_target(
            session, actor, **data.model_dump()
        )
        await session.commit()
        await session.refresh(target)
        return security_fabric.target_snapshot(target)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
