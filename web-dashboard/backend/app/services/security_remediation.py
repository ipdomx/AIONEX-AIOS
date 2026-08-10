"""Isolated remediation orchestration for confirmed Security Lab findings.

The remediation boundary deliberately separates source preparation, patch production,
regression evidence, and security retesting. No code is ever applied to production
or merged merely because an AI model proposed a change.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    SecurityFinding,
    SecurityRemediation,
    SecurityScan,
    SecurityTarget,
    uuid_str,
)
from app.services import security_fabric, security_scanning

TERMINAL = {"verified_fixed", "rejected", "failed", "cancelled"}


def now() -> datetime:
    return datetime.now(UTC)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def remediation_snapshot(item: SecurityRemediation) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "finding_id": item.finding_id,
        "requested_by_id": item.requested_by_id,
        "status": item.status,
        "worktree_ref": item.worktree_ref,
        "plan": item.plan,
        "regression_result": item.regression_result,
        "retest_scan_id": item.retest_scan_id,
        "verified_fixed_at": (
            item.verified_fixed_at.isoformat() if item.verified_fixed_at else None
        ),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def build_remediation_plan(
    finding: SecurityFinding, target: SecurityTarget
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "finding": {
            "id": finding.id,
            "fingerprint": finding.fingerprint,
            "source": finding.source,
            "category": finding.category,
            "title": finding.title,
            "severity": finding.severity,
            "cwe": finding.cwe,
            "owasp": finding.owasp,
            "location": finding.location,
        },
        "target": {
            "id": target.id,
            "project_id": target.project_id,
            "kind": target.kind,
            "environment": str(
                (target.target_metadata or {}).get("environment") or "production"
            ),
        },
        "instructions": [
            finding.remediation
            or "Apply the smallest project-compatible fix for the confirmed finding.",
            "Work only inside the isolated remediation copy.",
            "Preserve public contracts and existing tests unless a security contract intentionally changes.",
            "Add a regression test that fails before the fix and passes after it.",
            "Do not alter production, secrets, DNS, credentials, or unrelated project files.",
        ],
        "acceptance": {
            "requires_changed_file_manifest": True,
            "requires_regression_pass": True,
            "requires_security_retest": True,
            "requires_finding_absent_or_owner_resolved": True,
            "auto_merge": False,
            "production_modified": False,
        },
    }


async def request_remediation(
    session: AsyncSession,
    actor: UserRecord,
    *,
    finding_id: str,
) -> SecurityRemediation:
    policy = await security_fabric.get_policy(session)
    if not policy.get("auto_remediation_enabled", False):
        raise PermissionError(
            "Autonomous remediation is disabled by the Super Owner policy"
        )
    level = await security_fabric.access_level(session, actor)
    if level not in {"autonomous", "owner"}:
        raise PermissionError("Autonomous remediation is controlled by the Super Owner")
    finding = await session.scalar(
        select(SecurityFinding).where(
            SecurityFinding.id == finding_id,
            SecurityFinding.organization_id == actor.organization_id,
        )
    )
    if finding is None:
        raise LookupError("Security finding not found")
    if finding.state != "confirmed":
        raise ValueError("Only confirmed findings can enter autonomous remediation")
    target = await session.scalar(
        select(SecurityTarget).where(
            SecurityTarget.id == finding.target_id,
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.status == "active",
        )
    )
    if target is None or target.project_id is None or target.kind != "managed_project":
        raise ValueError(
            "Autonomous remediation is limited to managed AIONEX project targets"
        )
    existing = await session.scalar(
        select(SecurityRemediation).where(
            SecurityRemediation.organization_id == actor.organization_id,
            SecurityRemediation.finding_id == finding.id,
            SecurityRemediation.status.notin_(TERMINAL),
        )
    )
    if existing is not None:
        return existing
    item = SecurityRemediation(
        id=uuid_str(),
        organization_id=actor.organization_id,
        project_id=target.project_id,
        finding_id=finding.id,
        requested_by_id=actor.id,
        status="planned",
        plan=build_remediation_plan(finding, target),
        regression_result={},
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.remediation.planned",
            resource_type="security_remediation",
            resource_id=item.id,
            details={"finding_id": finding.id, "project_id": target.project_id},
        )
    )
    await session.flush()
    return item


def validate_patch_evidence(
    *,
    changed_files: list[str],
    tests: list[dict[str, Any]],
    patch_digest: str,
) -> dict[str, Any]:
    normalized_files = sorted(
        {path.strip().replace("\\", "/") for path in changed_files if path.strip()}
    )
    if not normalized_files or len(normalized_files) > 500:
        raise ValueError("A bounded changed-file manifest is required")
    for path in normalized_files:
        parts = Path(path).parts
        if (
            path.startswith("/")
            or ".." in parts
            or any(part in {".git", ".env", "secrets"} for part in parts)
        ):
            raise ValueError("Patch evidence contains a forbidden path")
    if (
        not patch_digest
        or len(patch_digest) != 64
        or any(c not in "0123456789abcdef" for c in patch_digest.lower())
    ):
        raise ValueError("A SHA-256 patch digest is required")
    normalized_tests = []
    for raw in tests[:200]:
        name = str(raw.get("name") or "").strip()[:300]
        passed = raw.get("passed") is True
        if not name:
            raise ValueError("Every regression check requires a name")
        normalized_tests.append({"name": name, "passed": passed})
    if not normalized_tests or not all(item["passed"] for item in normalized_tests):
        raise ValueError("All submitted regression checks must pass before retesting")
    return {
        "changed_files": normalized_files,
        "tests": normalized_tests,
        "patch_digest": patch_digest.lower(),
        "regression_passed": True,
        "production_modified": False,
        "evidence_digest": _digest(
            {
                "changed_files": normalized_files,
                "tests": normalized_tests,
                "patch_digest": patch_digest.lower(),
            }
        ),
    }


async def record_patch_evidence(
    session: AsyncSession,
    actor: UserRecord,
    remediation: SecurityRemediation,
    *,
    changed_files: list[str],
    tests: list[dict[str, Any]],
    patch_digest: str,
) -> SecurityRemediation:
    if remediation.organization_id != actor.organization_id:
        raise PermissionError("Remediation is not available")
    level = await security_fabric.access_level(session, actor)
    if level not in {"autonomous", "owner"}:
        raise PermissionError(
            "Autonomous remediation evidence requires Owner-granted access"
        )
    if remediation.status not in {"worktree_ready", "patch_ready"}:
        raise ValueError("Remediation is not ready for regression evidence")
    result = validate_patch_evidence(
        changed_files=changed_files, tests=tests, patch_digest=patch_digest
    )
    remediation.regression_result = result
    remediation.status = "regression_passed"
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.remediation.regression_passed",
            resource_type="security_remediation",
            resource_id=remediation.id,
            details={
                "evidence_digest": result["evidence_digest"],
                "changed_files": len(result["changed_files"]),
            },
        )
    )
    return remediation


async def queue_retest(
    session: AsyncSession,
    actor: UserRecord,
    remediation: SecurityRemediation,
) -> SecurityScan:
    if remediation.status != "regression_passed":
        raise ValueError("Regression must pass before the security retest")
    finding = await session.get(SecurityFinding, remediation.finding_id)
    if finding is None:
        raise LookupError("Security finding not found")
    original_scan = await session.get(SecurityScan, finding.scan_id)
    if original_scan is None:
        raise LookupError("Original security scan not found")
    retest = await security_scanning.request_scan(
        session,
        actor,
        target_id=finding.target_id,
        profile=original_scan.profile,
    )
    remediation.retest_scan_id = retest.id
    remediation.status = "retest_queued"
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.remediation.retest_queued",
            resource_type="security_remediation",
            resource_id=remediation.id,
            details={"scan_id": retest.id, "finding_fingerprint": finding.fingerprint},
        )
    )
    return retest


async def finalize_retest(
    session: AsyncSession,
    actor: UserRecord,
    remediation: SecurityRemediation,
) -> SecurityRemediation:
    if remediation.status != "retest_queued" or not remediation.retest_scan_id:
        raise ValueError("Remediation has no completed retest")
    retest = await session.get(SecurityScan, remediation.retest_scan_id)
    finding = await session.get(SecurityFinding, remediation.finding_id)
    if retest is None or finding is None:
        raise LookupError("Remediation evidence is incomplete")
    if retest.status != "completed":
        raise ValueError("Security retest is not complete")
    repeated = await session.scalar(
        select(SecurityFinding.id)
        .where(
            SecurityFinding.scan_id == retest.id,
            SecurityFinding.fingerprint == finding.fingerprint,
        )
        .limit(1)
    )
    if repeated is not None:
        remediation.status = "retest_failed"
        session.add(
            AuditEvent(
                organization_id=actor.organization_id,
                user_id=actor.id,
                action="security.remediation.retest_failed",
                resource_type="security_remediation",
                resource_id=remediation.id,
                details={
                    "scan_id": retest.id,
                    "finding_fingerprint": finding.fingerprint,
                },
            )
        )
        return remediation
    remediation.status = "verified_fixed"
    remediation.verified_fixed_at = now()
    finding.state = "resolved"
    finding.resolved_at = now()
    finding.verified_by_id = actor.id
    finding.verified_at = now()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.remediation.verified_fixed",
            resource_type="security_remediation",
            resource_id=remediation.id,
            details={
                "scan_id": retest.id,
                "finding_id": finding.id,
                "production_modified": False,
            },
        )
    )
    return remediation
