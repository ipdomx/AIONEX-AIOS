"""Security scan admission, execution, evidence persistence and summaries."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    ProjectExecution,
    SecurityFinding,
    SecurityScan,
    SecurityTarget,
    uuid_str,
)
from app.services import (
    adaptive_intelligence,
    security_entitlement,
    security_fabric,
    security_tools,
)
from app.services.security_api_analyzer import analyze_openapi
from app.services.security_web_scanner import scan_web_origin
from app.services.security_zap import run_zap
from app.services.security_deep_validation import build_scenario_plan
from app.services.security_mobile import scan_mobile_source
from app.services.host_maintenance_scan_admission import require_scan_admission
from app.services.security_scan_resources import require_runtime, tracked_thread

ACTIVE_SCAN_STATES = {"queued", "running"}


def now() -> datetime:
    return datetime.now(UTC)


def _profile_mode(profile: str, target: SecurityTarget, policy: dict[str, Any]) -> str:
    environment = str(
        (target.target_metadata or {}).get("environment") or "production"
    ).lower()
    if profile in {"advanced", "elite"}:
        if (
            policy.get("deep_validation_requires_clone", True)
            and environment != "security_clone"
        ):
            raise PermissionError(
                "Advanced and Elite validation requires an isolated security clone"
            )
        return "intrusive_clone"
    if profile == "standard" and target.active_scan_allowed:
        return "active_safe"
    return "passive"


SEVERITY_LEVELS = ("critical", "high", "medium", "low", "info")
RESOLVED_AT_EXECUTION = "resolved_at_execution"


def _severity_bucket(value: Any) -> str:
    """Bucket a severity exactly like the scan report endpoint does."""
    severity = str(value or "info").lower()
    return severity if severity in SEVERITY_LEVELS else "info"


def unique_severity_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    """Count severities over findings that are already deduplicated."""
    counts = Counter(_severity_bucket(item.get("severity")) for item in findings)
    return {key: counts.get(key, 0) for key in SEVERITY_LEVELS}


def finding_fingerprint(raw: dict[str, Any]) -> str:
    """The dedup key persisted as SecurityFinding.fingerprint."""
    return str(
        raw.get("fingerprint")
        or hashlib.sha256(repr(sorted(raw.items())).encode()).hexdigest()
    )


def deduplicate_findings(findings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """First occurrence per fingerprint, in order; mirrors the findings table."""
    unique: dict[str, dict[str, Any]] = {}
    for raw in findings:
        unique.setdefault(finding_fingerprint(raw), raw)
    return unique


def resolve_tool_availability(
    tool_plan: list[dict[str, Any]], runtime_catalog: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Apply the scan worker's reported availability to a tool plan.

    Optional engines are installed in the scan-worker container, not in the API
    process, so availability comes only from the worker's durable runtime
    record. Without such a record the plan says it is resolved at execution.
    """
    runtime = {str(item.get("id")): item for item in runtime_catalog or []}
    resolved: list[dict[str, Any]] = []
    for row in tool_plan:
        item = dict(row)
        if item.get("builtin"):
            item["available"] = True
            item["availability"] = "builtin"
            resolved.append(item)
            continue
        reported = runtime.get(str(item.get("id")))
        if reported is None or reported.get("runtime_status") == "not_reported":
            item["available"] = None
            item["availability"] = RESOLVED_AT_EXECUTION
            item["runtime_checked_at"] = None
        else:
            item["available"] = bool(reported.get("available"))
            item["availability"] = "available" if item["available"] else "unavailable"
            item["runtime_checked_at"] = reported.get("runtime_checked_at")
        resolved.append(item)
    return resolved


def build_tool_plan(
    profile: str,
    *,
    source_available: bool,
    execution_mode: str,
    runtime_catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rank = security_fabric.PROFILE_RANK[profile]
    selected: list[str] = ["aionex-tls", "aionex-headers"]
    if rank >= 1:
        selected.extend(
            ["katana", "projectdiscovery-httpx", "zap-baseline", "nuclei", "testssl"]
        )
    if source_available:
        selected.extend(
            [
                "aionex-source",
                "aionex-secrets",
                "aionex-dependencies",
                "trivy",
                "osv-scanner",
                "trufflehog",
                "gitleaks",
                "syft",
                "semgrep",
                "codeql",
            ]
        )
    if rank >= 2:
        selected.extend(["schemathesis", "nmap", "nikto"])
    if execution_mode == "intrusive_clone" and rank >= 2:
        selected.extend(["zap-active", "restler", "sqlmap", "xsstrike", "commix"])
    catalog = {item["id"]: item for item in security_tools.catalog_definitions()}
    plan = [catalog[item] for item in dict.fromkeys(selected) if item in catalog]
    return resolve_tool_availability(plan, runtime_catalog)


async def request_scan(
    session: AsyncSession,
    actor: UserRecord,
    *,
    target_id: str,
    profile: str,
) -> SecurityScan:
    await require_scan_admission(session)
    policy = await security_fabric.get_policy(session)
    if not policy["enabled"]:
        raise PermissionError("Security Lab is disabled by the Super Owner")
    access = await security_entitlement.resolve_access(session, actor, policy=policy)
    level = access.level
    if level is None:
        raise access.plan_required()
    if not security_fabric.profile_allowed(level, profile):
        raise security_entitlement.SecurityLabError(
            security_entitlement.PROFILE_NOT_ALLOWED,
            "Security Lab profile is not granted to this account",
        )
    target = await session.scalar(
        select(SecurityTarget).where(
            SecurityTarget.id == target_id,
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.status == "active",
        )
    )
    if target is None or not security_entitlement.subscriber_owns_target(
        access, actor, target
    ):
        raise LookupError("Security target not found")
    if target.authorization_status != "verified":
        raise PermissionError("Security target must be verified before scanning")
    # Re-resolve at admission time to prevent a stale authorization record from
    # becoming an SSRF route after DNS changes.
    security_fabric.assert_target_dns_stable(target)
    execution_mode = _profile_mode(profile, target, policy)
    await security_entitlement.enforce_scan_limits(session, access, actor)
    max_age = int(policy["subscription_access"]["reverify_after_days"])
    if security_fabric.verification_is_stale(target, max_age_days=max_age):
        # Ownership proofs expire: re-check the file or DNS TXT record before a
        # stale authorization can admit another scan.
        try:
            await security_fabric.reverify_external_target(session, target)
        except ValueError as exc:
            raise security_entitlement.SecurityLabError(
                security_entitlement.REVERIFY_FAILED,
                f"Ownership re-verification failed: {exc}",
                status_code=409,
                extra={"target_id": target.id},
            ) from exc
    active = int(
        await session.scalar(
            select(func.count(SecurityScan.id)).where(
                SecurityScan.organization_id == actor.organization_id,
                SecurityScan.requested_by_id == actor.id,
                SecurityScan.status.in_(ACTIVE_SCAN_STATES),
            )
        )
        or 0
    )
    if active >= int(policy["max_concurrent_scans_per_user"]):
        raise RuntimeError("Security Lab concurrency limit reached")
    source_path = str((target.target_metadata or {}).get("source_snapshot") or "")
    if not source_path and target.project_id:
        execution = await session.scalar(
            select(ProjectExecution)
            .where(
                ProjectExecution.project_id == target.project_id,
                ProjectExecution.organization_id == actor.organization_id,
                ProjectExecution.status == "completed",
                ProjectExecution.evidence_path.is_not(None),
            )
            .order_by(
                ProjectExecution.completed_at.desc(), ProjectExecution.created_at.desc()
            )
            .limit(1)
        )
        if (
            execution
            and execution.evidence_path
            and str(execution.evidence_path).startswith(
                "/var/lib/aionex/project-executions/"
            )
        ):
            source_path = str(execution.evidence_path)
            target.target_metadata = {
                **dict(target.target_metadata or {}),
                "source_snapshot": source_path,
                "source_snapshot_kind": "project_execution",
                "source_execution_id": execution.id,
            }
    source_available = bool(source_path)
    scan = SecurityScan(
        id=uuid_str(),
        organization_id=actor.organization_id,
        project_id=target.project_id,
        target_id=target.id,
        requested_by_id=actor.id,
        profile=profile,
        status="queued",
        execution_mode=execution_mode,
        tool_plan=build_tool_plan(
            profile,
            source_available=source_available,
            execution_mode=execution_mode,
            runtime_catalog=await security_tools.runtime_catalog_snapshot(session),
        ),
        summary={
            "access_level": level,
            "access_source": access.source,
            "plan_code": access.plan_code,
            "requested_at": now().isoformat(),
        },
        attempts=0,
        max_attempts=2,
    )
    session.add(scan)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.scan.queued",
            resource_type="security_scan",
            resource_id=scan.id,
            details={
                "target_id": target.id,
                "profile": profile,
                "execution_mode": execution_mode,
            },
        )
    )
    await session.flush()
    return scan


def scan_snapshot(scan: SecurityScan) -> dict[str, Any]:
    return {
        "id": scan.id,
        "project_id": scan.project_id,
        "target_id": scan.target_id,
        "requested_by_id": scan.requested_by_id,
        "profile": scan.profile,
        "status": scan.status,
        "execution_mode": scan.execution_mode,
        "tool_plan": scan.tool_plan,
        "summary": scan.summary,
        "error_code": scan.error_code,
        "error_message": scan.error_message,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        "created_at": scan.created_at.isoformat() if scan.created_at else None,
    }


def finding_snapshot(item: SecurityFinding) -> dict[str, Any]:
    return {
        "id": item.id,
        "scan_id": item.scan_id,
        "target_id": item.target_id,
        "source": item.source,
        "category": item.category,
        "title": item.title,
        "severity": item.severity,
        "confidence": item.confidence,
        "state": item.state,
        "fingerprint": item.fingerprint,
        "cwe": item.cwe,
        "owasp": item.owasp,
        "location": item.location,
        "evidence": item.evidence,
        "remediation": item.remediation,
        "verified_at": item.verified_at.isoformat() if item.verified_at else None,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
    }


def _safe_source_snapshot(target: SecurityTarget) -> Path | None:
    metadata = dict(target.target_metadata or {})
    raw = str(metadata.get("source_snapshot") or "").strip()
    if not raw:
        return None
    candidate = Path(raw).resolve(strict=True)
    kind = str(metadata.get("source_snapshot_kind") or "security_source")
    if kind == "project_execution":
        root = Path("/var/lib/aionex/project-executions").resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(
                "Project execution source is outside the durable execution root"
            )
        if not metadata.get("source_execution_id"):
            raise ValueError("Project execution source is missing execution provenance")
    else:
        root = Path("/var/lib/aionex/security-sources").resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(
                "Source snapshot is outside the isolated Security Lab source root"
            )
        if target.project_id and candidate.name != target.project_id:
            raise ValueError("Source snapshot does not match the target project")
    return candidate


async def _openapi_scan(origin: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        for path in ("/openapi.json", "/api/openapi.json"):
            try:
                response = await client.get(
                    origin.rstrip("/") + path,
                    headers={"User-Agent": "AIONEX-Security-Lab/1.0"},
                )
            except httpx.HTTPError:
                continue
            if (
                response.status_code == 200
                and "json" in response.headers.get("content-type", "").lower()
            ):
                try:
                    payload = response.json()
                except ValueError:
                    continue
                result = analyze_openapi(payload if isinstance(payload, dict) else {})
                return {**result, "path": path}
    return {
        "scanner": "aionex-api-contract-v1",
        "status": "not_discovered",
        "operations": 0,
        "findings": [],
    }


async def execute_scan(session: AsyncSession, scan: SecurityScan) -> SecurityScan:
    runtime = require_runtime(scan.id)
    await runtime.checkpoint()
    target = await session.get(SecurityTarget, scan.target_id)
    if (
        target is None
        or target.authorization_status != "verified"
        or target.status != "active"
    ):
        raise RuntimeError("Security target authorization is no longer valid")
    await tracked_thread("target-authorization-dns", security_fabric.assert_target_dns_stable, target)
    results: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    web_result = await runtime.async_io("web-origin", lambda: scan_web_origin(target.origin))
    results.append(
        {key: value for key, value in web_result.items() if key != "findings"}
    )
    all_findings.extend(web_result.get("findings", []))
    if security_fabric.PROFILE_RANK.get(scan.profile, 0) >= 1:
        api_result = await runtime.async_io("openapi-origin", lambda: _openapi_scan(target.origin))
        results.append(
            {key: value for key, value in api_result.items() if key != "findings"}
        )
        all_findings.extend(api_result.get("findings", []))
    source = await tracked_thread("source-resolution", _safe_source_snapshot, target)
    if source is not None:
        built_in = await tracked_thread("source-inventory", security_tools.scan_source_tree, source)
        results.append(
            {key: value for key, value in built_in.items() if key != "findings"}
        )
        all_findings.extend(built_in.get("findings", []))
        mobile_result = await tracked_thread("mobile-inventory", scan_mobile_source, source)
        results.append(
            {key: value for key, value in mobile_result.items() if key != "findings"}
        )
        all_findings.extend(mobile_result.get("findings", []))
        for tool_id in (
            "semgrep",
            "bandit",
            "trivy",
            "osv-scanner",
            "grype",
            "trufflehog",
            "gitleaks",
            "syft",
        ):
            tool_result = await security_tools.run_source_tool(
                tool_id, source, timeout=300
            )
            results.append(
                {key: value for key, value in tool_result.items() if key != "findings"}
            )
            all_findings.extend(tool_result.get("findings", []))
    # Optional engines run only through fixed adapters and only after target
    # authorization. Missing tools are reported as unavailable, never as passes.
    if security_fabric.PROFILE_RANK.get(scan.profile, 0) >= 1:
        for tool_id in (
            "testssl",
            "katana",
            "projectdiscovery-httpx",
            "nuclei",
        ):
            result = await security_tools.run_network_tool(
                tool_id,
                origin=target.origin,
                hostname=target.hostname,
                execution_mode=scan.execution_mode,
            )
            results.append(
                {key: value for key, value in result.items() if key != "findings"}
            )
            all_findings.extend(result.get("findings", []))
        zap_passive = await run_zap(
            target.origin, execution_mode=scan.execution_mode, active=False
        )
        results.append(
            {key: value for key, value in zap_passive.items() if key != "findings"}
        )
        all_findings.extend(zap_passive.get("findings", []))
    if security_fabric.PROFILE_RANK.get(scan.profile, 0) >= 2:
        for tool_id in (
            "nmap",
            "nikto",
            "schemathesis",
            "restler",
            "sqlmap",
            "xsstrike",
            "commix",
        ):
            try:
                result = await security_tools.run_network_tool(
                    tool_id,
                    origin=target.origin,
                    hostname=target.hostname,
                    execution_mode=scan.execution_mode,
                )
            except ValueError:
                result = {
                    "tool": tool_id,
                    "status": "scenario_required",
                    "findings": [],
                }
            results.append(
                {key: value for key, value in result.items() if key != "findings"}
            )
            all_findings.extend(result.get("findings", []))
        if scan.execution_mode == "intrusive_clone":
            zap_active = await run_zap(
                target.origin, execution_mode=scan.execution_mode, active=True
            )
            results.append(
                {key: value for key, value in zap_active.items() if key != "findings"}
            )
            all_findings.extend(zap_active.get("findings", []))
    deep_plan = (
        build_scenario_plan(
            environment=str(
                (target.target_metadata or {}).get("environment") or "production"
            ),
            available_roles=list(
                (target.target_metadata or {}).get("security_fixture_roles") or []
            ),
        )
        if scan.profile in {"advanced", "elite"}
        else None
    )
    await runtime.checkpoint()
    deduplicated = deduplicate_findings(all_findings)
    seen = set(deduplicated)
    unique_findings = list(deduplicated.values())
    for fingerprint, raw in deduplicated.items():
        session.add(
            SecurityFinding(
                id=uuid_str(),
                organization_id=scan.organization_id,
                scan_id=scan.id,
                target_id=scan.target_id,
                source=str(raw.get("source") or "aionex"),
                category=str(raw.get("category") or "general"),
                title=str(raw.get("title") or "Security finding")[:300],
                severity=str(raw.get("severity") or "info").lower(),
                confidence=float(raw.get("confidence") or 0.5),
                state=str(raw.get("state") or "observed"),
                fingerprint=fingerprint,
                cwe=(str(raw.get("cwe")) if raw.get("cwe") else None),
                owasp=(str(raw.get("owasp")) if raw.get("owasp") else None),
                location=(str(raw.get("location")) if raw.get("location") else None),
                evidence=dict(raw.get("evidence") or {}),
                remediation=(
                    str(raw.get("remediation")) if raw.get("remediation") else None
                ),
            )
        )
    # Availability is read from the scan worker's own runtime record, never
    # from a binary probe in the API process that admitted the scan.
    scan.tool_plan = resolve_tool_availability(
        list(scan.tool_plan or []),
        await security_tools.runtime_catalog_snapshot(session),
    )
    scan.summary = {
        **dict(scan.summary or {}),
        "finding_count": len(seen),
        "severity": unique_severity_counts(unique_findings),
        "engines": results,
        "deep_validation": deep_plan,
        "optional_tools": [
            {
                "id": item["id"],
                "available": item["available"],
                "availability": item["availability"],
            }
            for item in scan.tool_plan
            if not item.get("builtin")
        ],
    }
    scan.status = "completed"
    scan.completed_at = now()
    scan.lease_token = None
    await adaptive_intelligence.record_system_experience(
        session,
        organization_id=scan.organization_id,
        user_id=scan.requested_by_id,
        action="security.scan.completed",
        context={
            "profile": scan.profile,
            "execution_mode": scan.execution_mode,
            "target_kind": target.kind,
            "severity": scan.summary["severity"],
        },
        outcome="success",
        evidence=sorted(seen),
        project_id=scan.project_id,
        lesson=f"Security scan completed with {len(seen)} unique findings; evidence remains quarantined until verification.",
    )
    session.add(
        AuditEvent(
            organization_id=scan.organization_id,
            user_id=scan.requested_by_id,
            action="security.scan.completed",
            resource_type="security_scan",
            resource_id=scan.id,
            details={"finding_count": len(seen), "severity": scan.summary["severity"]},
        )
    )
    await session.flush()
    return scan
