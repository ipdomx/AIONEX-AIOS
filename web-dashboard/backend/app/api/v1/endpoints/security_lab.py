"""Entitlement-gated Security Lab API for authorized project targets.

Access: the Super Owner always; Owner ``SecurityAccessGrant`` overrides; and,
automatically, subscribers whose active plan is entitled to website scanning
(see ``app.services.security_entitlement``). Subscribers are scoped to their own
external targets and bounded by usage limits. Reports a user already owns stay
readable after access lapses; only new scans require current access.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import SecurityFinding, SecurityScan, SecurityTarget
from app.services import (
    security_dns_verification,
    security_entitlement,
    security_fabric,
    security_scanning,
)
from app.services.host_maintenance_scan_admission import require_scan_admission
from app.services.host_maintenance_admission import (
    HostMaintenanceClosed,
    HostMaintenanceUnavailable,
)
from app.services.security_entitlement import SecurityAccess, SecurityLabError

router = APIRouter()

SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


class ManagedTargetRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=36)
    origin: str = Field(min_length=8, max_length=500)
    environment: Literal["production", "staging"] = "production"


class ExternalTargetRequest(BaseModel):
    origin: str = Field(min_length=8, max_length=500)


class ExternalVerifyRequest(BaseModel):
    challenge: str = Field(min_length=20, max_length=300)
    method: Literal["http_file", "dns_txt"] = "http_file"


class ScanRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=36)
    profile: Literal["passive", "standard", "advanced", "elite"] = "passive"


def _lab_error(exc: SecurityLabError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


async def _resolve(session: AsyncSession, actor: UserRecord) -> SecurityAccess:
    return await security_entitlement.resolve_access(session, actor)


async def _require_access(session: AsyncSession, actor: UserRecord) -> SecurityAccess:
    access = await _resolve(session, actor)
    if access.level is None:
        raise _lab_error(access.plan_required())
    return access


def _own_targets(stmt: Any, access: SecurityAccess, actor: UserRecord) -> Any:
    if security_entitlement.privileged_inventory(access, actor):
        return stmt
    return stmt.where(
        SecurityTarget.created_by_id == actor.id,
        SecurityTarget.kind == "external_authorized",
    )


@router.get("/access")
async def access(
    actor: UserRecord = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    policy = await security_fabric.get_policy(session)
    decision = await security_entitlement.resolve_access(session, actor, policy=policy)
    settings = policy["subscription_access"]
    reports = int(
        await session.scalar(
            select(func.count(SecurityScan.id)).where(
                SecurityScan.organization_id == actor.organization_id,
                SecurityScan.requested_by_id == actor.id,
            )
        )
        or 0
    )
    denial = None
    if not policy["enabled"]:
        denial = security_entitlement.LAB_DISABLED
    elif decision.level is None:
        denial = security_entitlement.PLAN_REQUIRED
    return {
        "enabled": bool(policy["enabled"]),
        "granted": decision.level is not None,
        "level": decision.level,
        "source": decision.source,
        "profiles": decision.profiles(),
        "deep_validation_requires_clone": policy["deep_validation_requires_clone"],
        "denial_code": denial,
        "upgrade_required": denial == security_entitlement.PLAN_REQUIRED,
        "plan_code": decision.plan_code,
        "entitled_plans": list(decision.entitled_plan_codes),
        "limits": security_entitlement.limits(decision),
        "usage": await security_entitlement.usage(session, actor),
        "reports_available": reports > 0,
        "verification": {
            "methods": list(security_fabric.VERIFICATION_METHODS),
            "http_file_path": security_fabric.HTTP_VERIFICATION_PATH,
            "dns_record_prefix": security_dns_verification.DNS_RECORD_PREFIX,
            "dns_value_prefix": security_dns_verification.DNS_VALUE_PREFIX,
            "reverify_after_days": settings["reverify_after_days"],
        },
    }


@router.get("/tools")
async def tools(
    actor: UserRecord = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    await _require_access(session, actor)
    from app.services.security_tools import runtime_catalog_snapshot

    return await runtime_catalog_snapshot(session)


@router.get("/targets")
async def targets(
    actor: UserRecord = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    # Readable without current access so lapsed subscribers keep their history;
    # non-privileged callers only ever see targets they registered themselves.
    access = await _resolve(session, actor)
    stmt = select(SecurityTarget).where(
        SecurityTarget.organization_id == actor.organization_id,
        SecurityTarget.status == "active",
    )
    rows = list(
        (
            await session.scalars(
                _own_targets(stmt, access, actor).order_by(
                    SecurityTarget.updated_at.desc()
                )
            )
        ).all()
    )
    return [security_fabric.target_snapshot(item) for item in rows]


@router.post("/targets/managed", status_code=status.HTTP_201_CREATED)
async def managed_target(
    data: ManagedTargetRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    await _require_access(session, actor)
    try:
        target = await security_fabric.register_managed_target(
            session, actor, **data.model_dump()
        )
        await session.commit()
        await session.refresh(target)
        return security_fabric.target_snapshot(target)
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/targets/external", status_code=status.HTTP_201_CREATED)
async def external_target(
    data: ExternalTargetRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    access = await _require_access(session, actor)
    try:
        normalized, _hostname = security_fabric.normalize_origin(data.origin)
        if access.is_subscriber:
            existing = await session.scalar(
                select(SecurityTarget).where(
                    SecurityTarget.organization_id == actor.organization_id,
                    SecurityTarget.origin == normalized,
                    SecurityTarget.status == "active",
                )
            )
            if existing is not None and not security_entitlement.subscriber_owns_target(
                access, actor, existing
            ):
                raise ValueError(
                    "This website is already registered by another account in your organization"
                )
            await security_entitlement.enforce_target_limit(
                session, access, actor, origin=normalized
            )
        target, challenge = await security_fabric.register_external_target(
            session, actor, origin=data.origin
        )
        await session.commit()
        await session.refresh(target)
        return {
            **security_fabric.target_snapshot(target),
            "verification": security_fabric.verification_instructions(
                target, challenge
            ),
        }
    except SecurityLabError as exc:
        await session.rollback()
        raise _lab_error(exc) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/targets/{target_id}/verify")
async def verify_target(
    target_id: str,
    data: ExternalVerifyRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    access = await _require_access(session, actor)
    target = await session.scalar(
        select(SecurityTarget)
        .where(
            SecurityTarget.id == target_id,
            SecurityTarget.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if target is None or not security_entitlement.subscriber_owns_target(
        access, actor, target
    ):
        raise HTTPException(status_code=404, detail="Security target not found")
    try:
        if target.authorization_status != "verified":
            await security_entitlement.enforce_target_limit(
                session, access, actor, verifying=True
            )
        await security_fabric.verify_external_target(
            session, actor, target, challenge=data.challenge, method=data.method
        )
        await session.commit()
        await session.refresh(target)
        return security_fabric.target_snapshot(target)
    except SecurityLabError as exc:
        await session.rollback()
        raise _lab_error(exc) from exc
    except security_dns_verification.DnsVerificationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/targets/{target_id}")
async def archive_target(
    target_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    # Removing a site frees a subscriber's target allowance; it needs no current
    # entitlement, only ownership. Scans and findings stay readable.
    target = await session.scalar(
        select(SecurityTarget)
        .where(
            SecurityTarget.id == target_id,
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.status == "active",
        )
        .with_for_update()
    )
    if target is None or (
        actor.role != "Super Owner"
        and (target.kind != "external_authorized" or target.created_by_id != actor.id)
    ):
        raise HTTPException(status_code=404, detail="Security target not found")
    active = int(
        await session.scalar(
            select(func.count(SecurityScan.id)).where(
                SecurityScan.target_id == target.id,
                SecurityScan.status.in_(security_scanning.ACTIVE_SCAN_STATES),
            )
        )
        or 0
    )
    if active:
        raise HTTPException(
            status_code=409, detail="Cancel the running scan before removing this site"
        )
    target.status = "archived"
    target.authorization_status = "revoked"
    target.active_scan_allowed = False
    target.challenge_hash = None
    target.revoked_at = security_fabric.now()
    await session.commit()
    await session.refresh(target)
    return security_fabric.target_snapshot(target)


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
async def create_scan(
    data: ScanRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        scan = await security_scanning.request_scan(
            session, actor, target_id=data.target_id, profile=data.profile
        )
        await session.commit()
        await session.refresh(scan)
        return security_scanning.scan_snapshot(scan)
    except HostMaintenanceClosed:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Security scan admission is temporarily closed for maintenance.",
        ) from None
    except HostMaintenanceUnavailable:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Security scan admission is currently unavailable.",
        ) from None
    except SecurityLabError as exc:
        await session.rollback()
        raise _lab_error(exc) from exc
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scans")
async def scans(
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    # Past reports stay readable after a subscription lapses: the requester
    # filter below, not current entitlement, authorizes reading history.
    stmt = select(SecurityScan).where(
        SecurityScan.organization_id == actor.organization_id
    )
    if actor.role != "Super Owner":
        stmt = stmt.where(SecurityScan.requested_by_id == actor.id)
    rows = list(
        (
            await session.scalars(
                stmt.order_by(SecurityScan.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [security_scanning.scan_snapshot(item) for item in rows]


async def _owned_scan(
    session: AsyncSession, actor: UserRecord, scan_id: str
) -> SecurityScan:
    scan = await session.scalar(
        select(SecurityScan).where(
            SecurityScan.id == scan_id,
            SecurityScan.organization_id == actor.organization_id,
        )
    )
    if scan is None or (
        actor.role != "Super Owner" and scan.requested_by_id != actor.id
    ):
        raise HTTPException(status_code=404, detail="Security scan not found")
    return scan


async def _scan_findings(
    session: AsyncSession, scan: SecurityScan
) -> list[SecurityFinding]:
    return list(
        (
            await session.scalars(
                select(SecurityFinding)
                .where(SecurityFinding.scan_id == scan.id)
                .order_by(SecurityFinding.severity, SecurityFinding.created_at)
            )
        ).all()
    )


@router.get("/scans/{scan_id}/findings")
async def findings(
    scan_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    scan = await _owned_scan(session, actor, scan_id)
    rows = await _scan_findings(session, scan)
    return [security_scanning.finding_snapshot(item) for item in rows]


@router.get("/scans/{scan_id}/report")
async def scan_report(
    scan_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Printable report: the scan, its target and findings grouped by severity."""

    scan = await _owned_scan(session, actor, scan_id)
    target = await session.get(SecurityTarget, scan.target_id)
    rows = [security_scanning.finding_snapshot(item) for item in await _scan_findings(session, scan)]
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in SEVERITY_ORDER}
    for item in rows:
        severity = str(item.get("severity") or "info").lower()
        grouped.setdefault(severity if severity in grouped else "info", []).append(item)
    counts = Counter({key: len(value) for key, value in grouped.items()})
    return {
        "scan": security_scanning.scan_snapshot(scan),
        "target": (
            {
                "id": target.id,
                "origin": target.origin,
                "hostname": target.hostname,
                "verification_method": target.verification_method,
                "verified_at": target.verified_at.isoformat() if target.verified_at else None,
            }
            if target is not None
            else None
        ),
        "severity_counts": {key: counts.get(key, 0) for key in SEVERITY_ORDER},
        "findings_by_severity": grouped,
        "generated_at": security_fabric.now().isoformat(),
    }


@router.post("/scans/{scan_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_scan(
    scan_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    from app.services.host_maintenance_scan_execution import request_scan_cancellation

    # Revocation must not prevent a user stopping an already-owned scan. The
    # authenticated actor and strict organization/requester filters authorize
    # cancellation; no profile grant or open maintenance admission is needed.
    scan = await session.scalar(
        select(SecurityScan).where(
            SecurityScan.id == scan_id,
            SecurityScan.organization_id == actor.organization_id,
        ).with_for_update().execution_options(populate_existing=True)
    )
    if scan is None or (actor.role != "Super Owner" and scan.requested_by_id != actor.id):
        raise HTTPException(status_code=404, detail="Security scan not found")
    try:
        answer = await request_scan_cancellation(
            session, scan_id=scan_id, organization_id=actor.organization_id,
            user_id=actor.id,
        )
        await session.commit()
        await session.refresh(scan)
        return {**security_scanning.scan_snapshot(scan), "cancellation": answer}
    except BaseException:
        await session.rollback()
        raise


class RemediationRequest(BaseModel):
    finding_id: str = Field(min_length=1, max_length=36)


class PatchEvidenceRequest(BaseModel):
    changed_files: list[str] = Field(min_length=1, max_length=500)
    tests: list[dict] = Field(min_length=1, max_length=200)
    patch_digest: str = Field(min_length=64, max_length=64)


@router.get("/remediations")
async def remediations(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    await _require_access(session, actor)
    from app.db.models import SecurityRemediation
    from app.services.security_remediation import remediation_snapshot

    stmt = select(SecurityRemediation).where(
        SecurityRemediation.organization_id == actor.organization_id
    )
    if actor.role != "Super Owner":
        stmt = stmt.where(SecurityRemediation.requested_by_id == actor.id)
    rows = list(
        (
            await session.scalars(
                stmt.order_by(SecurityRemediation.updated_at.desc()).limit(500)
            )
        ).all()
    )
    return [remediation_snapshot(item) for item in rows]


@router.post("/remediations", status_code=status.HTTP_202_ACCEPTED)
async def create_remediation(
    data: RemediationRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    from app.services import security_remediation

    try:
        item = await security_remediation.request_remediation(
            session, actor, finding_id=data.finding_id
        )
        await session.commit()
        await session.refresh(item)
        return security_remediation.remediation_snapshot(item)
    except HostMaintenanceClosed:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Security remediation admission is temporarily closed for maintenance.",
        ) from None
    except HostMaintenanceUnavailable:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Security remediation admission is currently unavailable.",
        ) from None
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/remediations/{remediation_id}/patch-evidence")
async def submit_patch_evidence(
    remediation_id: str,
    data: PatchEvidenceRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityRemediation
    from app.services import security_remediation

    item = await session.scalar(
        select(SecurityRemediation)
        .where(
            SecurityRemediation.id == remediation_id,
            SecurityRemediation.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if item is None or (
        actor.role != "Super Owner" and item.requested_by_id != actor.id
    ):
        raise HTTPException(status_code=404, detail="Security remediation not found")
    try:
        await security_remediation.record_patch_evidence(
            session, actor, item, **data.model_dump()
        )
        await session.commit()
        await session.refresh(item)
        return security_remediation.remediation_snapshot(item)
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/remediations/{remediation_id}/retest", status_code=status.HTTP_202_ACCEPTED
)
async def remediation_retest(
    remediation_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityRemediation
    from app.services import security_remediation

    try:
        await require_scan_admission(session)
        item = await session.scalar(
            select(SecurityRemediation)
            .where(
                SecurityRemediation.id == remediation_id,
                SecurityRemediation.organization_id == actor.organization_id,
            )
            .with_for_update()
        )
        if item is None or (
            actor.role != "Super Owner" and item.requested_by_id != actor.id
        ):
            raise HTTPException(status_code=404, detail="Security remediation not found")
        scan = await security_remediation.queue_retest(session, actor, item)
        await session.commit()
        await session.refresh(item)
        await session.refresh(scan)
        return {
            "remediation": security_remediation.remediation_snapshot(item),
            "scan": security_scanning.scan_snapshot(scan),
        }
    except HostMaintenanceClosed:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Security scan admission is temporarily closed for maintenance.",
        ) from None
    except HostMaintenanceUnavailable:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Security scan admission is currently unavailable.",
        ) from None
    except SecurityLabError as exc:
        await session.rollback()
        raise _lab_error(exc) from exc
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/remediations/{remediation_id}/finalize")
async def finalize_remediation(
    remediation_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    from app.db.models import SecurityRemediation
    from app.services import security_remediation

    item = await session.scalar(
        select(SecurityRemediation)
        .where(
            SecurityRemediation.id == remediation_id,
            SecurityRemediation.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if item is None or (
        actor.role != "Super Owner" and item.requested_by_id != actor.id
    ):
        raise HTTPException(status_code=404, detail="Security remediation not found")
    try:
        await security_remediation.finalize_retest(session, actor, item)
        await session.commit()
        await session.refresh(item)
        return security_remediation.remediation_snapshot(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
