"""Controlled end-to-end acceptance lab for AIONEX Security & Learning Fabric.

This runner is intentionally restricted to an isolated Docker test network. It
creates only disposable test data, bypasses public-target SSRF checks in-process
for the fixture hostname, and never changes Production, DNS, credentials or live
project data.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    BackupRecord,
    DisasterRecoveryRun,
    Organization,
    Project,
    Role,
    SecurityFinding,
    SecurityReleaseGate,
    SecurityRule,
    SecurityTarget,
    User,
    Workspace,
    uuid_str,
)
from app.db.seed import seed
from app.services import (
    security_fabric,
    security_remediation,
    security_release_gate,
    security_rule_forge,
    security_scanning,
    security_tools,
    security_web_scanner,
)

LAB_ORIGIN = os.getenv("AIONEX_ACCEPTANCE_ORIGIN", "http://fixture:8088").rstrip("/")
LAB_HOST = os.getenv("AIONEX_ACCEPTANCE_HOST", "fixture")
TLS_ORIGIN = os.getenv("AIONEX_ACCEPTANCE_TLS_ORIGIN", "https://tls-fixture:8443").rstrip("/")
TLS_HOST = os.getenv("AIONEX_ACCEPTANCE_TLS_HOST", "tls-fixture")
PROJECT_ID = os.getenv("AIONEX_ACCEPTANCE_PROJECT_ID", "security-acceptance-lab-project")
SOURCE_ROOT = Path(os.getenv("AIONEX_ACCEPTANCE_SOURCE_ROOT", "/var/lib/aionex/security-sources"))
WORKSPACE_ROOT = Path(os.getenv("AIONEX_ACCEPTANCE_WORKSPACE", "/workspace"))
REPORT_PATH = Path(os.getenv("AIONEX_ACCEPTANCE_REPORT", "/var/lib/aionex/security-acceptance/report.json"))
FIXTURE_ROOT = WORKSPACE_ROOT / "web-dashboard/backend/tests/security_acceptance_lab/fixtures"
LAB_IP_EVIDENCE = ["203.0.113.10"]


def now() -> datetime:
    return datetime.now(UTC)


def _copy_source(mode: str) -> Path:
    source = FIXTURE_ROOT / mode
    destination = SOURCE_ROOT / PROJECT_ID
    if not source.is_dir():
        raise RuntimeError(f"Acceptance fixture source missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


async def _fixture_control(action: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{LAB_ORIGIN}/__acceptance__/{action}",
            headers={"X-AIONEX-Acceptance": "1"},
        )
        response.raise_for_status()
        return response.json()


async def _fixture_health() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{LAB_ORIGIN}/health")
        response.raise_for_status()
        return response.json()


async def _behavioral_probe() -> dict[str, Any]:
    marker = "<script>AIONEX_ACCEPTANCE_XSS</script>"
    async with httpx.AsyncClient(timeout=10.0) as client:
        reflected = await client.get(f"{LAB_ORIGIN}/reflect", params={"name": marker})
        search = await client.get(f"{LAB_ORIGIN}/search", params={"q": "' OR '1'='1"})
        cross_user = await client.get(
            f"{LAB_ORIGIN}/api/users/2/profile",
            headers={"Authorization": "Bearer acceptance-user-1"},
        )
        unauthenticated_mutation = await client.post(
            f"{LAB_ORIGIN}/api/projects/acceptance-project/transfer"
        )
    try:
        search_rows = len(search.json().get("rows") or [])
    except (ValueError, AttributeError):
        search_rows = -1
    return {
        "raw_reflected_markup": marker in reflected.text,
        "search_row_count": search_rows,
        "cross_user_status": cross_user.status_code,
        "unauthenticated_mutation_status": unauthenticated_mutation.status_code,
    }


def _assert_vulnerable_behavior(result: dict[str, Any]) -> None:
    if result != {
        "raw_reflected_markup": True,
        "search_row_count": 2,
        "cross_user_status": 200,
        "unauthenticated_mutation_status": 200,
    }:
        raise AssertionError(f"Vulnerable behavioral fixture did not expose the expected test flaws: {result}")


def _assert_fixed_behavior(result: dict[str, Any]) -> None:
    if result != {
        "raw_reflected_markup": False,
        "search_row_count": 0,
        "cross_user_status": 403,
        "unauthenticated_mutation_status": 401,
    }:
        raise AssertionError(f"Fixed behavioral fixture did not enforce the expected controls: {result}")


def _actor(owner: User, role: Role, organization: Organization) -> UserRecord:
    return UserRecord(
        id=owner.id,
        email=owner.email,
        name=owner.name,
        role=role.name,
        password_hash=owner.password_hash,
        organization_id=organization.id,
        organization_name=organization.name,
        organization_plan=organization.plan,
        permissions=["*"],
        status=owner.status,
        auth_version=owner.auth_version,
    )


def _finding_rows(rows: list[SecurityFinding]) -> list[dict[str, Any]]:
    return [security_scanning.finding_snapshot(row) for row in rows]


def _has(rows: list[SecurityFinding], *, source: str | None = None, title: str | None = None, marker: str | None = None) -> bool:
    for row in rows:
        if source is not None and row.source != source:
            continue
        if title is not None and title.lower() not in row.title.lower():
            continue
        if marker is not None and marker != str((row.evidence or {}).get("marker") or ""):
            continue
        return True
    return False


def _required_detection_matrix(rows: list[SecurityFinding], scan_summary: dict[str, Any]) -> dict[str, bool]:
    deep = dict(scan_summary.get("deep_validation") or {})
    scenarios = {str(item.get("id")) for item in deep.get("scenarios") or [] if item.get("ready")}
    return {
        "transport_http": _has(rows, source="aionex-tls", title="does not use HTTPS"),
        "missing_csp": _has(rows, source="aionex-headers", title="Missing content-security-policy"),
        "insecure_cookie": _has(rows, source="aionex-headers", title="Cookie missing Secure"),
        "api_no_security_scheme": _has(rows, source="aionex-api-contract", title="declares no security schemes"),
        "api_mutation_without_auth": _has(rows, source="aionex-api-contract", title="Mutating API operation has no declared security"),
        "source_eval": _has(rows, source="aionex-source", marker="python-eval"),
        "source_shell_true": _has(rows, source="aionex-source", marker="shell-true"),
        "source_pickle": _has(rows, source="aionex-source", marker="pickle-load"),
        "source_tls_bypass": _has(rows, source="aionex-source", marker="weak-tls-disable"),
        "secret_exposure": _has(rows, source="aionex-secrets", title="Potential generic-secret-assignment"),
        "container_no_user": _has(rows, source="aionex-source", title="no explicit non-root USER"),
        "container_latest": _has(rows, source="aionex-source", title="mutable latest tag"),
        "compose_privileged": _has(rows, source="aionex-source", title="privileged-container"),
        "compose_host_network": _has(rows, source="aionex-source", title="host-network"),
        "compose_docker_socket": _has(rows, source="aionex-source", title="docker-socket"),
        "semgrep_dynamic_eval": _has(rows, source="semgrep", title="Dynamic eval"),
        "semgrep_shell_true": _has(rows, source="semgrep", title="shell=True"),
        "semgrep_tls_bypass": _has(rows, source="semgrep", title="TLS verification is disabled"),
        "zap_reflected_xss": _has(rows, source="owasp-zap", title="Cross Site Scripting (Reflected)"),
        "zap_sql_injection": _has(rows, source="owasp-zap", title="SQL Injection"),
        "nuclei_exposed_git": _has(rows, source="nuclei", title="AIONEX acceptance exposed Git metadata"),
        "nikto_missing_csp": _has(rows, source="nikto", title="security header missing: content-security-policy"),
        "deep_authz_matrix": "authz-object-matrix" in scenarios,
        "deep_financial_concurrency": "financial-concurrency" in scenarios,
        "deep_csrf_origin": "csrf-origin-boundary" in scenarios,
    }


def _engine_statuses(summary: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in summary.get("engines") or []:
        result.append(
            {
                "engine": item.get("scanner") or item.get("tool") or "unknown",
                "status": item.get("status", "completed"),
                "finding_count": item.get("finding_count"),
                "exit_code": item.get("exit_code"),
            }
        )
    return result


def _unexpected_engine_failures(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in _engine_statuses(summary)
        if item["status"] in {"failed", "timeout", "unavailable", "not_configured"}
        or (item["status"] == "not_applicable" and item["engine"] != "testssl")
    ]


async def _testssl_smoke() -> dict[str, Any]:
    result: dict[str, Any] = {}
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 3):
        result = await security_tools.run_network_tool(
            "testssl",
            origin=TLS_ORIGIN,
            hostname=TLS_HOST,
            execution_mode="active_safe",
            timeout=180,
        )
        attempts.append(
            {
                "attempt": attempt,
                "status": result.get("status"),
                "exit_code": result.get("exit_code"),
                "stderr": str(result.get("stderr") or "")[:2000],
            }
        )
        if result.get("status") == "completed" and result.get("exit_code") == 0:
            break
        await asyncio.sleep(2.0)
    return {
        "status": result.get("status"),
        "exit_code": result.get("exit_code"),
        "finding_count": result.get("finding_count", 0),
        "stdout_sha256": result.get("stdout_sha256"),
        "stderr": str(result.get("stderr") or "")[:4000],
        "attempts": attempts,
    }


async def _scan(session, actor: UserRecord, target: SecurityTarget, profile: str = "elite"):
    scan = await security_scanning.request_scan(
        session,
        actor,
        target_id=target.id,
        profile=profile,
    )
    scan.status = "running"
    scan.started_at = now()
    scan.attempts = max(1, scan.attempts)
    await session.flush()
    await security_scanning.execute_scan(session, scan)
    await session.commit()
    await session.refresh(scan)
    rows = list(
        (
            await session.scalars(
                select(SecurityFinding)
                .where(SecurityFinding.scan_id == scan.id)
                .order_by(SecurityFinding.severity, SecurityFinding.source, SecurityFinding.title)
            )
        ).all()
    )
    return scan, rows


async def _prepare_database(session):
    await seed()
    role = await session.scalar(select(Role).where(Role.name == "Super Owner").limit(1))
    if role is None:
        raise RuntimeError("Seeded Super Owner role not found")
    owner = await session.scalar(
        select(User)
        .where(User.role_id == role.id, User.deleted_at.is_(None))
        .limit(1)
    )
    if owner is None:
        raise RuntimeError("Seeded Super Owner user not found")
    organization = await session.get(Organization, owner.organization_id)
    if organization is None:
        raise RuntimeError("Seeded owner organization not found")
    workspace = await session.scalar(
        select(Workspace)
        .where(Workspace.organization_id == organization.id)
        .order_by(Workspace.created_at)
        .limit(1)
    )
    if workspace is None:
        raise RuntimeError("Seeded workspace not found")
    actor = _actor(owner, role, organization)

    # Disposable acceptance records only. The database container is isolated, but
    # deterministic IDs also make reruns idempotent if the container is retained.
    await session.execute(delete(SecurityReleaseGate).where(SecurityReleaseGate.project_id == PROJECT_ID))
    for target in list(
        (
            await session.scalars(
                select(SecurityTarget).where(SecurityTarget.project_id == PROJECT_ID)
            )
        ).all()
    ):
        await session.delete(target)
    project = await session.get(Project, PROJECT_ID)
    if project is None:
        project = Project(
            id=PROJECT_ID,
            organization_id=organization.id,
            workspace_id=workspace.id,
            owner_id=owner.id,
            name="AIONEX Security Acceptance Lab",
            slug="aionex-security-acceptance-lab",
            description="Disposable isolated Security Fabric acceptance fixture",
            status="active",
            priority="high",
            progress=100,
            tags=["security", "acceptance", "disposable"],
        )
        session.add(project)
        await session.flush()

    managed = SecurityTarget(
        id=uuid_str(),
        organization_id=organization.id,
        project_id=project.id,
        created_by_id=owner.id,
        verified_by_id=owner.id,
        kind="managed_project",
        origin="https://managed.acceptance.invalid",
        hostname="managed.acceptance.invalid",
        authorization_status="verified",
        verification_method="acceptance_fixture",
        active_scan_allowed=True,
        status="active",
        target_metadata={"environment": "staging", "verified_addresses": LAB_IP_EVIDENCE},
        verified_at=now(),
    )
    session.add(managed)
    await session.flush()

    clone = SecurityTarget(
        id=uuid_str(),
        organization_id=organization.id,
        project_id=project.id,
        created_by_id=owner.id,
        verified_by_id=owner.id,
        kind="security_clone",
        origin=LAB_ORIGIN,
        hostname=LAB_HOST,
        authorization_status="verified",
        verification_method="acceptance_fixture",
        active_scan_allowed=True,
        status="active",
        target_metadata={
            "environment": "security_clone",
            "source_target_id": managed.id,
            "source_snapshot": str(SOURCE_ROOT / PROJECT_ID),
            "source_snapshot_kind": "security_source",
            "verified_addresses": LAB_IP_EVIDENCE,
            "security_fixture_roles": ["user", "user_a", "user_b", "admin", "owner"],
        },
        verified_at=now(),
    )
    session.add(clone)
    await security_fabric.update_policy(
        session,
        {
            "enabled": True,
            "auto_remediation_enabled": True,
            "learning_enabled": True,
            "auto_rule_candidates": True,
            "deep_validation_requires_clone": True,
            "release_gate": {
                "block_confirmed_critical": True,
                "block_confirmed_high": True,
                "max_confirmed_medium": 0,
                "require_tls": True,
                "require_security_headers": True,
                "require_backup_restore_evidence": True,
            },
        },
    )
    backup_id = uuid_str()
    session.add(
        BackupRecord(
            id=backup_id,
            kind="acceptance_lab",
            scope="platform",
            status="completed",
            location="acceptance://backup",
            checksum="0" * 64,
            size_bytes=1,
            completed_at=now(),
        )
    )
    session.add(
        DisasterRecoveryRun(
            id=uuid_str(),
            operation="restore_test",
            status="completed",
            region="acceptance-lab",
            details={
                "disposable": True,
                "backup_id": backup_id,
                "validated": True,
                "three_d_snapshot_required": True,
                "three_d_snapshot_validated": True,
            },
            completed_at=now(),
        )
    )
    await session.commit()
    return actor, managed, clone


async def main() -> int:
    started = now()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": started.isoformat(),
        "origin": LAB_ORIGIN,
        "production_modified": False,
        "dns_modified": False,
        "external_target_used": False,
    }

    # These two overrides exist only inside this disposable acceptance process.
    # Production code retains its public-routable-address enforcement unchanged.
    security_fabric.assert_target_dns_stable = lambda _target: LAB_IP_EVIDENCE
    security_web_scanner.assert_public_target = lambda _hostname: LAB_IP_EVIDENCE

    tls_smoke = await _testssl_smoke()
    report["tool_smoke"] = {"testssl": tls_smoke}
    if tls_smoke["status"] != "completed" or tls_smoke["exit_code"] != 0:
        raise AssertionError(f"testssl runtime smoke failed: {tls_smoke}")

    await _fixture_control("reset")
    health = await _fixture_health()
    if health.get("mode") != "vulnerable":
        raise RuntimeError("Acceptance runtime did not enter vulnerable mode")
    vulnerable_behavior = await _behavioral_probe()
    _assert_vulnerable_behavior(vulnerable_behavior)
    report["behavioral_validation"] = {"vulnerable": vulnerable_behavior}
    _copy_source("vulnerable")

    async with SessionLocal() as session:
        actor, managed, clone = await _prepare_database(session)

        first_scan, first_findings = await _scan(session, actor, clone, "elite")
        first_matrix = _required_detection_matrix(first_findings, dict(first_scan.summary or {}))
        missing = sorted(name for name, detected in first_matrix.items() if not detected)
        engine_statuses = _engine_statuses(dict(first_scan.summary or {}))
        unexpected_engine_failures = _unexpected_engine_failures(dict(first_scan.summary or {}))
        report["vulnerable_scan"] = {
            "scan_id": first_scan.id,
            "finding_count": len(first_findings),
            "severity": dict((first_scan.summary or {}).get("severity") or {}),
            "required_detection_matrix": first_matrix,
            "required_detection_coverage": round(sum(first_matrix.values()) / len(first_matrix), 4),
            "missing_required": missing,
            "engine_statuses": engine_statuses,
            "unexpected_engine_failures": unexpected_engine_failures,
            "findings": _finding_rows(first_findings),
        }
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        if missing:
            raise AssertionError(f"Required acceptance detections missing: {missing}")
        if unexpected_engine_failures:
            raise AssertionError(f"Acceptance engines failed unexpectedly: {unexpected_engine_failures}")

        # Run the vulnerable state again and ensure the deterministic acceptance
        # detector fingerprints repeat instead of passing by accident.
        second_scan, second_findings = await _scan(session, actor, clone, "elite")
        second_matrix = _required_detection_matrix(second_findings, dict(second_scan.summary or {}))
        if second_matrix != first_matrix:
            raise AssertionError("Required detection matrix was not reproducible")
        required_sources = {
            row.fingerprint
            for row in first_findings
            if row.source in {"aionex-tls", "aionex-headers", "aionex-api-contract", "aionex-source", "aionex-secrets", "semgrep"}
        }
        repeated_sources = {
            row.fingerprint
            for row in second_findings
            if row.source in {"aionex-tls", "aionex-headers", "aionex-api-contract", "aionex-source", "aionex-secrets", "semgrep"}
        }
        if required_sources != repeated_sources:
            raise AssertionError("Deterministic security fingerprints changed between identical scans")
        report["repeatability"] = {
            "scan_id": second_scan.id,
            "required_matrix_identical": True,
            "deterministic_fingerprints_identical": True,
            "fingerprint_count": len(required_sources),
        }

        # Confirm a real deterministic finding and prove the release gate blocks it.
        tracked = next(
            row
            for row in first_findings
            if row.source == "aionex-headers" and row.title == "Missing content-security-policy"
        )
        tracked.state = "confirmed"
        tracked.verified_by_id = actor.id
        tracked.verified_at = now()
        await session.commit()
        initial_gate = await security_release_gate.create_release_gate(
            session, actor, scan_id=first_scan.id
        )
        await session.commit()
        if initial_gate.decision != "blocked":
            raise AssertionError("Confirmed vulnerable fixture did not block the release gate")
        report["initial_release_gate"] = {
            "decision": initial_gate.decision,
            "blockers": initial_gate.blockers,
        }

        # Security Genome: finding -> quarantine candidate -> validation corpus -> promotion.
        rule = await security_rule_forge.derive_candidate(session, actor, tracked)
        await security_rule_forge.validate_candidate(session, actor, rule, corpus_id="acceptance-lab-v1")
        await session.flush()
        if rule.status != "validated":
            raise AssertionError("Security Genome rule did not pass validation")
        await security_rule_forge.promote_rule(session, actor, rule)
        await session.commit()
        await session.refresh(rule)
        if rule.status != "promoted":
            raise AssertionError("Validated Security Genome rule was not promoted")
        report["learning_cycle"] = {
            "finding_id": tracked.id,
            "rule_id": rule.id,
            "status": rule.status,
            "trust_score": rule.trust_score,
            "validation_passes": rule.validation_passes,
            "validation_failures": rule.validation_failures,
        }

        # Remediation admission must work for a finding discovered on the isolated
        # clone while remaining tied to the verified managed project source target.
        remediation = await security_remediation.request_remediation(
            session, actor, finding_id=tracked.id
        )
        remediation.status = "worktree_ready"
        remediation.worktree_ref = "acceptance://isolated-remediation-copy"
        await session.commit()

        # Apply the known-good acceptance fixture only inside the disposable source
        # snapshot and switch the runtime fixture without changing the target origin.
        _copy_source("fixed")
        fixed_digest = hashlib.sha256((FIXTURE_ROOT / "fixed/app.py").read_bytes()).hexdigest()
        remediation = await session.get(type(remediation), remediation.id)
        assert remediation is not None
        await security_remediation.record_patch_evidence(
            session,
            actor,
            remediation,
            changed_files=["app.py", "Dockerfile", "docker-compose.yml", "requirements.txt"],
            tests=[
                {"name": "acceptance fixed source regression", "passed": True},
                {"name": "acceptance runtime contract", "passed": True},
            ],
            patch_digest=fixed_digest,
        )
        await _fixture_control("fix")
        fixed_health = await _fixture_health()
        if fixed_health.get("mode") != "fixed":
            raise RuntimeError("Acceptance runtime did not enter fixed mode")
        fixed_behavior = await _behavioral_probe()
        _assert_fixed_behavior(fixed_behavior)
        report["behavioral_validation"]["fixed"] = fixed_behavior
        report["behavioral_validation"]["status"] = "PASS"
        retest = await security_remediation.queue_retest(session, actor, remediation)
        retest.status = "running"
        retest.started_at = now()
        await session.flush()
        await security_scanning.execute_scan(session, retest)
        await session.commit()
        remediation = await session.get(type(remediation), remediation.id)
        assert remediation is not None
        await security_remediation.finalize_retest(session, actor, remediation)
        await session.commit()
        await session.refresh(remediation)
        if remediation.status != "verified_fixed":
            raise AssertionError(f"Remediation did not verify fixed: {remediation.status}")

        fixed_findings = list(
            (
                await session.scalars(
                    select(SecurityFinding)
                    .where(SecurityFinding.scan_id == retest.id)
                    .order_by(SecurityFinding.severity, SecurityFinding.source, SecurityFinding.title)
                )
            ).all()
        )
        if any(row.fingerprint == tracked.fingerprint for row in fixed_findings):
            raise AssertionError("Tracked vulnerability fingerprint survived the fixed retest")
        fixed_engine_statuses = _engine_statuses(dict(retest.summary or {}))
        fixed_engine_failures = _unexpected_engine_failures(dict(retest.summary or {}))
        if fixed_engine_failures:
            raise AssertionError(f"Security engines failed fixed retest: {fixed_engine_failures}")

        # Local HTTP is deliberate in this closed Docker lab. Mark only that transport
        # artifact as lab-only; any other high/medium residual remains a failure.
        lab_transport = [
            row
            for row in fixed_findings
            if row.source in {"aionex-tls", "aionex-headers"}
            and row.category == "transport-security"
            and (
                row.title == "Target does not use HTTPS"
                or row.title == "Redirect chain ended on HTTP"
            )
        ]
        for row in lab_transport:
            row.state = "false_positive"
            row.verified_by_id = actor.id
            row.verified_at = now()
        await session.commit()
        residual = [
            row
            for row in fixed_findings
            if row.state not in {"false_positive", "resolved"}
            and row.severity in {"critical", "high", "medium"}
        ]
        report["remediation_cycle"] = {
            "remediation_id": remediation.id,
            "status": remediation.status,
            "retest_scan_id": retest.id,
            "tracked_fingerprint_absent": True,
            "fixed_finding_count": len(fixed_findings),
            "fixed_severity": dict((retest.summary or {}).get("severity") or {}),
            "engine_statuses": fixed_engine_statuses,
            "unexpected_engine_failures": fixed_engine_failures,
            "lab_transport_exceptions": len(lab_transport),
            "residual_high_medium": _finding_rows(residual),
            "findings": _finding_rows(fixed_findings),
        }
        if residual:
            raise AssertionError(
                "Fixed acceptance fixture retained high/medium findings: "
                + ", ".join(f"{row.source}:{row.title}" for row in residual)
            )

        final_gate = await security_release_gate.create_release_gate(
            session, actor, scan_id=retest.id
        )
        await session.commit()
        if final_gate.decision != "passed":
            raise AssertionError(
                f"Fixed acceptance fixture did not pass release gate: {final_gate.decision}"
            )
        report["final_release_gate"] = {
            "decision": final_gate.decision,
            "blockers": final_gate.blockers,
        }

        promoted = await session.scalar(
            select(SecurityRule).where(SecurityRule.id == rule.id)
        )
        report["database_evidence"] = {
            "promoted_rule_persisted": bool(promoted and promoted.status == "promoted"),
            "remediation_verified_fixed": remediation.status == "verified_fixed",
            "initial_gate_blocked": initial_gate.decision == "blocked",
            "final_gate_passed": final_gate.decision == "passed",
        }

    report["completed_at"] = now().isoformat()
    report["status"] = "PASS"
    report["production_modified"] = False
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "vulnerable_findings": report["vulnerable_scan"]["finding_count"],
        "coverage": report["vulnerable_scan"]["required_detection_coverage"],
        "repeatable": report["repeatability"]["deterministic_fingerprints_identical"],
        "learning_rule": report["learning_cycle"]["status"],
        "remediation": report["remediation_cycle"]["status"],
        "final_gate": report["final_release_gate"]["decision"],
        "report": str(REPORT_PATH),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
