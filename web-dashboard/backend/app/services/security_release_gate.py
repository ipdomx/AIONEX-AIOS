"""Evidence-based Security Lab release gate.

A release is never approved from scanner silence alone. Confirmed severe findings
block; unresolved severe observations require review; required operational evidence
must also be present and recent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    BackupRecord,
    DisasterRecoveryRun,
    SecurityFinding,
    SecurityReleaseGate,
    SecurityScan,
    SecurityTarget,
    uuid_str,
)
from app.services import security_fabric


def now() -> datetime:
    return datetime.now(UTC)


def _finding_value(
    item: SecurityFinding | dict[str, Any], key: str, default: Any = None
) -> Any:
    return (
        item.get(key, default)
        if isinstance(item, dict)
        else getattr(item, key, default)
    )


def evaluate_release_gate(
    *,
    scan_status: str,
    scan_summary: dict[str, Any],
    findings: Sequence[SecurityFinding | dict[str, Any]],
    policy: dict[str, Any],
    recent_backup: bool,
    recent_dr_restore: bool,
) -> dict[str, Any]:
    gate_policy = dict(policy.get("release_gate") or {})
    blockers: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    if scan_status != "completed":
        blockers.append(
            {
                "code": "SECURITY_SCAN_INCOMPLETE",
                "message": "The selected security scan is not complete.",
            }
        )

    confirmed = [
        item for item in findings if _finding_value(item, "state") == "confirmed"
    ]
    unresolved = [
        item
        for item in findings
        if _finding_value(item, "state") not in {"false_positive", "resolved"}
    ]
    confirmed_counts = {
        level: sum(
            str(_finding_value(item, "severity", "info")).lower() == level
            for item in confirmed
        )
        for level in ("critical", "high", "medium", "low", "info")
    }
    unresolved_counts = {
        level: sum(
            str(_finding_value(item, "severity", "info")).lower() == level
            for item in unresolved
        )
        for level in ("critical", "high", "medium", "low", "info")
    }
    if (
        gate_policy.get("block_confirmed_critical", True)
        and confirmed_counts["critical"]
    ):
        blockers.append(
            {
                "code": "CONFIRMED_CRITICAL_FINDINGS",
                "count": confirmed_counts["critical"],
            }
        )
    if gate_policy.get("block_confirmed_high", True) and confirmed_counts["high"]:
        blockers.append(
            {"code": "CONFIRMED_HIGH_FINDINGS", "count": confirmed_counts["high"]}
        )
    max_medium = max(0, int(gate_policy.get("max_confirmed_medium", 0)))
    if confirmed_counts["medium"] > max_medium:
        blockers.append(
            {
                "code": "CONFIRMED_MEDIUM_THRESHOLD",
                "count": confirmed_counts["medium"],
                "allowed": max_medium,
            }
        )

    observed_severe = sum(
        1
        for item in unresolved
        if _finding_value(item, "state") == "observed"
        and str(_finding_value(item, "severity", "info")).lower()
        in {"critical", "high"}
    )
    if observed_severe:
        review.append({"code": "UNVERIFIED_SEVERE_FINDINGS", "count": observed_severe})
    observed_medium = sum(
        1
        for item in unresolved
        if _finding_value(item, "state") == "observed"
        and str(_finding_value(item, "severity", "info")).lower() == "medium"
    )
    if max_medium == 0 and observed_medium:
        review.append({"code": "UNVERIFIED_MEDIUM_FINDINGS", "count": observed_medium})

    engines = list(scan_summary.get("engines") or [])
    web_engine = next(
        (item for item in engines if item.get("scanner") == "aionex-web-v1"), None
    )
    if gate_policy.get("require_tls", True) or gate_policy.get(
        "require_security_headers", True
    ):
        if not web_engine or web_engine.get("status") != "completed":
            blockers.append(
                {
                    "code": "WEB_SECURITY_EVIDENCE_MISSING",
                    "message": "TLS/header validation did not complete.",
                }
            )
    if gate_policy.get("require_backup_restore_evidence", True):
        if not recent_backup:
            blockers.append({"code": "RECENT_BACKUP_EVIDENCE_MISSING"})
        if not recent_dr_restore:
            blockers.append({"code": "RECENT_RESTORE_EVIDENCE_MISSING"})

    if blockers:
        decision = "blocked"
    elif review:
        decision = "review_required"
    else:
        decision = "passed"
    return {
        "decision": decision,
        "blockers": blockers,
        "review": review,
        "confirmed_severity": confirmed_counts,
        "unresolved_severity": unresolved_counts,
        "assurance": {
            "recent_backup": recent_backup,
            "recent_dr_restore": recent_dr_restore,
        },
    }


async def operational_assurance(
    session: AsyncSession, *, hours: int = 24
) -> dict[str, bool]:
    cutoff = now() - timedelta(hours=max(1, min(hours, 168)))
    backup = await session.scalar(
        select(BackupRecord)
        .where(
            BackupRecord.scope == "platform",
            BackupRecord.status == "completed",
            BackupRecord.completed_at >= cutoff,
        )
        .order_by(BackupRecord.completed_at.desc())
        .limit(1)
    )
    restore_ready = False
    if backup is not None:
        restores = (
            await session.scalars(
                select(DisasterRecoveryRun)
                .where(
                    DisasterRecoveryRun.status == "completed",
                    DisasterRecoveryRun.completed_at >= cutoff,
                    DisasterRecoveryRun.operation.in_(
                        {
                            "restore",
                            "restore_test",
                            "drill",
                            "restore_verify",
                            "restore_validation",
                            "test",
                        }
                    ),
                )
                .order_by(DisasterRecoveryRun.completed_at.desc())
                .limit(100)
            )
        ).all()
        for restore in restores:
            details = restore.details or {}
            if details.get("backup_id") != backup.id:
                continue
            if details.get("validated") is not True:
                continue
            if settings.BACKUP_THREE_D_ASSETS_ENABLED and (
                details.get("three_d_snapshot_required") is not True
                or details.get("three_d_snapshot_validated") is not True
            ):
                continue
            restore_ready = True
            break
    return {
        "recent_backup": backup is not None,
        "recent_dr_restore": restore_ready,
    }


async def create_release_gate(
    session: AsyncSession,
    actor: UserRecord,
    *,
    scan_id: str,
) -> SecurityReleaseGate:
    if actor.role != "Super Owner":
        raise PermissionError(
            "Only the Super Owner can issue a Security Release Gate decision"
        )
    scan = await session.scalar(
        select(SecurityScan).where(
            SecurityScan.id == scan_id,
            SecurityScan.organization_id == actor.organization_id,
        )
    )
    if scan is None:
        raise LookupError("Security scan not found")
    target = await session.get(SecurityTarget, scan.target_id)
    if target is None or target.organization_id != actor.organization_id:
        raise LookupError("Security target not found")
    findings = list(
        (
            await session.scalars(
                select(SecurityFinding).where(SecurityFinding.scan_id == scan.id)
            )
        ).all()
    )
    policy = await security_fabric.get_policy(session)
    assurance = await operational_assurance(session)
    result = evaluate_release_gate(
        scan_status=scan.status,
        scan_summary=dict(scan.summary or {}),
        findings=findings,
        policy=policy,
        recent_backup=assurance["recent_backup"],
        recent_dr_restore=assurance["recent_dr_restore"],
    )
    item = SecurityReleaseGate(
        id=uuid_str(),
        organization_id=actor.organization_id,
        project_id=target.project_id,
        scan_id=scan.id,
        decision=result["decision"],
        policy_snapshot=policy,
        blockers=list(result["blockers"]),
        created_by_id=actor.id,
        created_at=now(),
    )
    # Normalize the optional review wrapper above into an ordinary list entry.
    item.blockers = list(result["blockers"])
    if result["review"]:
        item.blockers.append(
            {"code": "OWNER_REVIEW_REQUIRED", "items": result["review"]}
        )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.release_gate.evaluated",
            resource_type="security_release_gate",
            resource_id=item.id,
            details={
                "scan_id": scan.id,
                "project_id": target.project_id,
                "decision": item.decision,
                "blocker_count": len(item.blockers),
            },
        )
    )
    await session.flush()
    return item


def gate_snapshot(item: SecurityReleaseGate) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "scan_id": item.scan_id,
        "decision": item.decision,
        "policy_snapshot": item.policy_snapshot,
        "blockers": item.blockers,
        "created_by_id": item.created_by_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
