"""Security tool registry and source-analysis adapters.

External tools are capability-detected and invoked only through fixed argument
builders. User input is never interpolated into a shell command. Built-in analysis
remains available when an optional engine is not installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


ToolCategory = Literal[
    "tls",
    "headers",
    "attack_surface",
    "dast",
    "api",
    "sast",
    "dependencies",
    "secrets",
    "containers",
    "infrastructure",
    "dns",
    "mobile",
    "sbom",
    "supply_chain",
]


@dataclass(frozen=True)
class ToolSpec:
    id: str
    category: ToolCategory
    adapter: str
    builtin: bool = False
    active: bool = False
    intrusive: bool = False
    requires_source: bool = False
    requires_clone: bool = False
    description: str = ""


TOOL_CATALOG: tuple[ToolSpec, ...] = (
    ToolSpec(
        "aionex-tls",
        "tls",
        "builtin",
        builtin=True,
        description="TLS certificate/protocol posture",
    ),
    ToolSpec(
        "aionex-headers",
        "headers",
        "builtin",
        builtin=True,
        description="HTTP security headers, cookies and CSP",
    ),
    ToolSpec(
        "aionex-source",
        "sast",
        "builtin",
        builtin=True,
        requires_source=True,
        description="Cross-language risky-pattern analysis",
    ),
    ToolSpec(
        "aionex-secrets",
        "secrets",
        "builtin",
        builtin=True,
        requires_source=True,
        description="Credential and private-key pattern detection",
    ),
    ToolSpec(
        "aionex-dependencies",
        "dependencies",
        "builtin",
        builtin=True,
        requires_source=True,
        description="Dependency manifest inventory",
    ),
    ToolSpec(
        "semgrep",
        "sast",
        "semgrep",
        requires_source=True,
        description="Semgrep static analysis",
    ),
    ToolSpec(
        "codeql",
        "sast",
        "codeql",
        requires_source=True,
        description="CodeQL deep source analysis",
    ),
    ToolSpec(
        "bandit",
        "sast",
        "bandit",
        requires_source=True,
        description="Python security analysis",
    ),
    ToolSpec(
        "trivy",
        "containers",
        "trivy",
        requires_source=True,
        description="Vulnerabilities, misconfiguration and secrets",
    ),
    ToolSpec(
        "osv-scanner",
        "dependencies",
        "osv-scanner",
        requires_source=True,
        description="OSV dependency and lockfile analysis",
    ),
    ToolSpec(
        "trufflehog",
        "secrets",
        "trufflehog",
        requires_source=True,
        description="Verified-capable secret discovery",
    ),
    ToolSpec(
        "gitleaks",
        "secrets",
        "gitleaks",
        requires_source=True,
        description="Additional secret detection",
    ),
    ToolSpec(
        "syft",
        "sbom",
        "syft",
        requires_source=True,
        description="CycloneDX/SPDX SBOM generation",
    ),
    ToolSpec(
        "grype",
        "dependencies",
        "grype",
        requires_source=True,
        description="SBOM/filesystem vulnerability matching",
    ),
    ToolSpec(
        "dependency-check",
        "dependencies",
        "dependency-check",
        requires_source=True,
        description="OWASP Dependency-Check adapter",
    ),
    ToolSpec(
        "npm-audit",
        "dependencies",
        "npm",
        requires_source=True,
        description="npm audit adapter",
    ),
    ToolSpec(
        "pip-audit",
        "dependencies",
        "pip-audit",
        requires_source=True,
        description="Python dependency audit",
    ),
    ToolSpec(
        "composer-audit",
        "dependencies",
        "composer",
        requires_source=True,
        description="Composer advisory audit",
    ),
    ToolSpec(
        "phpstan",
        "sast",
        "phpstan",
        requires_source=True,
        description="PHP static analysis",
    ),
    ToolSpec(
        "psalm",
        "sast",
        "psalm",
        requires_source=True,
        description="PHP security/type analysis",
    ),
    ToolSpec(
        "eslint-security",
        "sast",
        "eslint",
        requires_source=True,
        description="JavaScript security lint adapter",
    ),
    ToolSpec(
        "sonarqube",
        "sast",
        "sonar-scanner",
        requires_source=True,
        description="Optional SonarQube enterprise integration",
    ),
    ToolSpec(
        "snyk",
        "dependencies",
        "snyk",
        requires_source=True,
        description="Optional Snyk integration",
    ),
    ToolSpec(
        "clair",
        "containers",
        "clairctl",
        requires_source=True,
        description="Optional Clair image analysis",
    ),
    ToolSpec(
        "docker-bench",
        "containers",
        "docker-bench-security",
        description="Docker hardening benchmark",
    ),
    ToolSpec(
        "testssl",
        "tls",
        "testssl.sh",
        active=True,
        description="TLS protocol/cipher validation",
    ),
    ToolSpec(
        "zap-baseline",
        "dast",
        "zap-baseline.py",
        active=True,
        description="OWASP ZAP passive/baseline web scan",
    ),
    ToolSpec(
        "zap-active",
        "dast",
        "zap-full-scan.py",
        active=True,
        intrusive=True,
        requires_clone=True,
        description="OWASP ZAP active validation on an authorized security clone",
    ),
    ToolSpec(
        "nuclei",
        "dast",
        "nuclei",
        active=True,
        description="Template-driven authorized vulnerability validation",
    ),
    ToolSpec(
        "katana",
        "attack_surface",
        "katana",
        active=True,
        description="Web attack-surface crawler",
    ),
    ToolSpec(
        "projectdiscovery-httpx",
        "attack_surface",
        "pd-httpx",
        active=True,
        description="HTTP service fingerprinting",
    ),
    ToolSpec(
        "nmap",
        "infrastructure",
        "nmap",
        active=True,
        description="Bounded service/port discovery",
    ),
    ToolSpec(
        "nikto",
        "dast",
        "nikto",
        active=True,
        description="Web server misconfiguration scanner",
    ),
    ToolSpec(
        "schemathesis",
        "api",
        "schemathesis",
        active=True,
        description="OpenAPI/GraphQL property-based API testing",
    ),
    ToolSpec(
        "restler",
        "api",
        "restler",
        active=True,
        requires_clone=True,
        description="Stateful REST API fuzzing on authorized clones",
    ),
    ToolSpec(
        "sqlmap",
        "dast",
        "sqlmap",
        active=True,
        intrusive=True,
        requires_clone=True,
        description="Focused SQL injection validation on authorized clones",
    ),
    ToolSpec(
        "xsstrike",
        "dast",
        "xsstrike",
        active=True,
        intrusive=True,
        requires_clone=True,
        description="Focused XSS validation on authorized clones",
    ),
    ToolSpec(
        "commix",
        "dast",
        "commix",
        active=True,
        intrusive=True,
        requires_clone=True,
        description="Focused command-injection validation on authorized clones",
    ),
    ToolSpec(
        "lynis",
        "infrastructure",
        "lynis",
        active=True,
        description="Linux hardening audit for managed infrastructure",
    ),
    ToolSpec(
        "openscap",
        "infrastructure",
        "oscap",
        active=True,
        description="SCAP compliance validation",
    ),
    ToolSpec(
        "mobsf",
        "mobile",
        "mobsfscan",
        requires_source=True,
        description="Mobile application static security integration",
    ),
    ToolSpec(
        "jadx",
        "mobile",
        "jadx",
        requires_source=True,
        description="Android decompilation support for authorized artifacts",
    ),
    ToolSpec(
        "apkleaks",
        "mobile",
        "apkleaks",
        requires_source=True,
        description="Android secret/reference discovery",
    ),
    ToolSpec(
        "dependency-track",
        "supply_chain",
        "dependency-track",
        requires_source=True,
        description="Dependency-Track SBOM portfolio integration",
    ),
    ToolSpec(
        "cosign",
        "supply_chain",
        "cosign",
        requires_source=True,
        description="Artifact signature/provenance verification",
    ),
)

CATALOG_BY_ID = {item.id: item for item in TOOL_CATALOG}

_ALLOWED_SOURCE_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".php",
    ".rb",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".cs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".bash",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".conf",
    ".xml",
    ".properties",
    ".env.example",
}
_SPECIAL_SOURCE_NAMES = {
    "Dockerfile",
    "Containerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "AndroidManifest.xml",
}
_MANIFEST_NAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "requirements-runtime.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile.lock",
    "composer.json",
    "composer.lock",
    "Gemfile.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
}
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "coverage",
}
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        "critical",
    ),
    (
        "generic-secret-assignment",
        re.compile(
            r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\n]{12,}['\"]"
        ),
        "high",
    ),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "critical"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"), "critical"),
)
_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    ("python-eval", re.compile(r"\beval\s*\("), "high", "CWE-95"),
    ("python-exec", re.compile(r"\bexec\s*\("), "high", "CWE-95"),
    ("shell-true", re.compile(r"shell\s*=\s*True"), "high", "CWE-78"),
    ("pickle-load", re.compile(r"\bpickle\.(?:load|loads)\s*\("), "high", "CWE-502"),
    ("php-eval", re.compile(r"(?i)\beval\s*\("), "high", "CWE-95"),
    (
        "php-system",
        re.compile(r"(?i)\b(?:system|passthru|shell_exec)\s*\("),
        "high",
        "CWE-78",
    ),
    (
        "node-child-exec",
        re.compile(r"(?:child_process\.)?exec(?:Sync)?\s*\("),
        "high",
        "CWE-78",
    ),
    (
        "weak-tls-disable",
        re.compile(
            r"(?i)(?:verify\s*=\s*False|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0)"
        ),
        "high",
        "CWE-295",
    ),
)
_REDACT = re.compile(r"(?i)(api[_-]?key|secret|token|password)(\s*[:=]\s*)([^\s,;]+)")


def catalog_snapshot() -> list[dict[str, Any]]:
    result = []
    for item in TOOL_CATALOG:
        row = asdict(item)
        row["available"] = item.builtin or shutil.which(item.adapter) is not None
        result.append(row)
    return result


def _safe_text(path: Path, max_bytes: int = 1_000_000) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
        if b"\x00" in data:
            return None
        return data.decode("utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None


def _fingerprint(kind: str, relative: str, line: int, marker: str) -> str:
    return hashlib.sha256(f"{kind}|{relative}|{line}|{marker}".encode()).hexdigest()


def scan_source_tree(root: Path, *, max_files: int = 20_000) -> dict[str, Any]:
    """Perform bounded built-in SAST/secrets/manifest inventory without executing source."""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Source snapshot must be a directory")
    findings: list[dict[str, Any]] = []
    manifests: list[str] = []
    scanned = 0
    for path in root.rglob("*"):
        if scanned >= max_files:
            break
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in relative_path.parts):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        if path.name in _MANIFEST_NAMES:
            manifests.append(relative_path.as_posix())
        suffix = path.suffix.lower()
        if (
            suffix not in _ALLOWED_SOURCE_SUFFIXES
            and path.name not in _MANIFEST_NAMES
            and path.name not in _SPECIAL_SOURCE_NAMES
        ):
            continue
        scanned += 1
        text = _safe_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for marker, pattern, severity in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        {
                            "source": "aionex-secrets",
                            "category": "secret-exposure",
                            "title": f"Potential {marker} in source snapshot",
                            "severity": severity,
                            "confidence": 0.78,
                            "state": "observed",
                            "fingerprint": _fingerprint(
                                "secret", relative_path.as_posix(), line_no, marker
                            ),
                            "cwe": "CWE-798",
                            "location": f"{relative_path.as_posix()}:{line_no}",
                            "evidence": {"marker": marker, "line": line_no},
                            "remediation": "Remove the credential from source/history, rotate it, and use the configured secret store.",
                        }
                    )
            for marker, pattern, severity, cwe in _RISK_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        {
                            "source": "aionex-source",
                            "category": "risky-code-pattern",
                            "title": f"Risky code pattern: {marker}",
                            "severity": severity,
                            "confidence": 0.62,
                            "state": "observed",
                            "fingerprint": _fingerprint(
                                "sast", relative_path.as_posix(), line_no, marker
                            ),
                            "cwe": cwe,
                            "location": f"{relative_path.as_posix()}:{line_no}",
                            "evidence": {"marker": marker, "line": line_no},
                            "remediation": "Replace the risky primitive with a constrained API and validate untrusted inputs before use.",
                        }
                    )
        if path.name in {"Dockerfile", "Containerfile"}:
            lowered = text.lower()
            if "user " not in lowered:
                findings.append(
                    {
                        "source": "aionex-source",
                        "category": "container-hardening",
                        "title": "Container build has no explicit non-root USER",
                        "severity": "medium",
                        "confidence": 0.75,
                        "state": "observed",
                        "fingerprint": _fingerprint(
                            "container", relative_path.as_posix(), 0, "no-user"
                        ),
                        "cwe": "CWE-250",
                        "location": relative_path.as_posix(),
                        "evidence": {"marker": "missing-user"},
                        "remediation": "Create an unprivileged runtime user and switch with USER before the final command.",
                    }
                )
            if re.search(r"(?im)^\s*from\s+[^\s:]+:latest(?:\s|$)", text):
                findings.append(
                    {
                        "source": "aionex-source",
                        "category": "supply-chain",
                        "title": "Container base image uses the mutable latest tag",
                        "severity": "medium",
                        "confidence": 0.95,
                        "state": "observed",
                        "fingerprint": _fingerprint(
                            "container", relative_path.as_posix(), 0, "latest-tag"
                        ),
                        "cwe": "CWE-1104",
                        "location": relative_path.as_posix(),
                        "evidence": {"marker": "latest-tag"},
                        "remediation": "Pin the base image to an explicit version and preferably an immutable digest.",
                    }
                )
        if path.name in {
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        }:
            lowered = text.lower()
            for marker, token in (
                ("privileged-container", "privileged: true"),
                ("host-network", "network_mode: host"),
                ("docker-socket", "/var/run/docker.sock"),
            ):
                if token in lowered:
                    findings.append(
                        {
                            "source": "aionex-source",
                            "category": "container-hardening",
                            "title": f"Container configuration exposes {marker}",
                            "severity": "high",
                            "confidence": 0.95,
                            "state": "observed",
                            "fingerprint": _fingerprint(
                                "compose", relative_path.as_posix(), 0, marker
                            ),
                            "cwe": "CWE-250",
                            "location": relative_path.as_posix(),
                            "evidence": {"marker": marker},
                            "remediation": "Remove elevated host/container access unless it is strictly required and separately isolated.",
                        }
                    )
    return {
        "scanner": "aionex-source-v1",
        "files_scanned": scanned,
        "truncated": scanned >= max_files,
        "manifests": sorted(set(manifests)),
        "findings": findings,
    }


def redact_tool_output(value: str) -> str:
    return _REDACT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value
    )


def _command_for(tool_id: str, source: Path) -> list[str]:
    source = source.resolve(strict=True)
    if tool_id == "trivy":
        return [
            "trivy",
            "fs",
            "--format",
            "json",
            "--scanners",
            "vuln,misconfig,secret",
            "--exit-code",
            "0",
            "--no-progress",
            str(source),
        ]
    if tool_id == "osv-scanner":
        return ["osv-scanner", "scan", "source", "-r", str(source), "--format", "json"]
    if tool_id == "trufflehog":
        return ["trufflehog", "filesystem", str(source), "--json", "--no-update"]
    if tool_id == "gitleaks":
        return [
            "gitleaks",
            "dir",
            str(source),
            "--report-format",
            "json",
            "--report-path",
            "/dev/stdout",
        ]
    if tool_id == "syft":
        return ["syft", f"dir:{source}", "-o", "cyclonedx-json"]
    if tool_id == "grype":
        return ["grype", f"dir:{source}", "-o", "json"]
    if tool_id == "bandit":
        return ["bandit", "-r", str(source), "-f", "json", "-q"]
    if tool_id == "semgrep":
        rules = os.getenv("AIOS_SEMGREP_RULESET", "").strip()
        if not rules:
            raise ValueError(
                "Semgrep requires an Owner-configured local AIOS_SEMGREP_RULESET"
            )
        return ["semgrep", "scan", "--config", rules, "--json", "--quiet", str(source)]
    raise ValueError(f"No safe source adapter for {tool_id}")


def _severity(value: Any, default: str = "medium") -> str:
    raw = str(value or default).lower()
    aliases = {
        "error": "high",
        "warning": "medium",
        "warn": "medium",
        "unknown": "medium",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in {"critical", "high", "medium", "low", "info"} else default


def _external_finding(
    tool: str,
    *,
    marker: str,
    title: str,
    severity: str,
    location: str | None = None,
    evidence: dict[str, Any] | None = None,
    cwe: str | None = None,
    remediation: str | None = None,
    confidence: float = 0.78,
) -> dict[str, Any]:
    safe_evidence = {
        str(k): v
        for k, v in (evidence or {}).items()
        if k.lower() not in {"secret", "match", "raw", "code", "line"}
    }
    return {
        "source": tool,
        "category": "external-tool",
        "title": title[:300],
        "severity": _severity(severity),
        "confidence": confidence,
        "state": "observed",
        "fingerprint": hashlib.sha256(
            f"{tool}|{marker}|{location or ''}".encode()
        ).hexdigest(),
        "cwe": cwe,
        "owasp": None,
        "location": location,
        "evidence": safe_evidence,
        "remediation": remediation
        or "Confirm the finding against project/runtime evidence and apply the smallest compatible security fix.",
    }


def _normalize_source_findings(
    tool_id: str, parsed: Any, stdout_text: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if tool_id == "semgrep" and isinstance(parsed, dict):
        for row in parsed.get("results") or []:
            if not isinstance(row, dict):
                continue
            extra = _as_dict(row.get("extra"))
            start = _as_dict(row.get("start"))
            check_id = str(row.get("check_id") or "semgrep")
            location = f"{row.get('path', '')}:{start.get('line', '')}".rstrip(":")
            metadata = _as_dict(extra.get("metadata"))
            cwe_value = metadata.get("cwe")
            if isinstance(cwe_value, list):
                cwe_value = cwe_value[0] if cwe_value else None
            findings.append(
                _external_finding(
                    "semgrep",
                    marker=check_id,
                    title=str(extra.get("message") or check_id),
                    severity=str(extra.get("severity") or "warning"),
                    location=location,
                    evidence={"check_id": check_id},
                    cwe=str(cwe_value) if cwe_value else None,
                    confidence=0.84,
                )
            )
    elif tool_id == "bandit" and isinstance(parsed, dict):
        for row in parsed.get("results") or []:
            if not isinstance(row, dict):
                continue
            test_id = str(row.get("test_id") or "bandit")
            location = f"{row.get('filename', '')}:{row.get('line_number', '')}".rstrip(
                ":"
            )
            findings.append(
                _external_finding(
                    "bandit",
                    marker=test_id,
                    title=str(row.get("issue_text") or test_id),
                    severity=str(row.get("issue_severity") or "medium"),
                    location=location,
                    evidence={
                        "test_id": test_id,
                        "confidence": row.get("issue_confidence"),
                    },
                    confidence=0.82,
                )
            )
    elif tool_id == "trivy" and isinstance(parsed, dict):
        for result in parsed.get("Results") or []:
            if not isinstance(result, dict):
                continue
            target = str(result.get("Target") or "")
            for row in result.get("Vulnerabilities") or []:
                if not isinstance(row, dict):
                    continue
                vuln_id = str(row.get("VulnerabilityID") or "trivy-vuln")
                findings.append(
                    _external_finding(
                        "trivy",
                        marker=vuln_id,
                        title=str(row.get("Title") or vuln_id),
                        severity=str(row.get("Severity") or "medium"),
                        location=target,
                        evidence={
                            "vulnerability_id": vuln_id,
                            "package": row.get("PkgName"),
                            "installed_version": row.get("InstalledVersion"),
                            "fixed_version": row.get("FixedVersion"),
                        },
                        confidence=0.90,
                    )
                )
            for row in result.get("Misconfigurations") or []:
                if not isinstance(row, dict):
                    continue
                rule_id = str(row.get("ID") or "trivy-misconfig")
                findings.append(
                    _external_finding(
                        "trivy",
                        marker=rule_id,
                        title=str(row.get("Title") or row.get("Message") or rule_id),
                        severity=str(row.get("Severity") or "medium"),
                        location=target,
                        evidence={"rule_id": rule_id},
                        confidence=0.86,
                    )
                )
            for row in result.get("Secrets") or []:
                if not isinstance(row, dict):
                    continue
                rule_id = str(
                    row.get("RuleID") or row.get("Category") or "trivy-secret"
                )
                location = f"{target}:{row.get('StartLine', '')}".rstrip(":")
                findings.append(
                    _external_finding(
                        "trivy",
                        marker=rule_id,
                        title=str(row.get("Title") or "Potential secret exposure"),
                        severity=str(row.get("Severity") or "high"),
                        location=location,
                        evidence={"rule_id": rule_id},
                        cwe="CWE-798",
                        confidence=0.88,
                    )
                )
    elif tool_id == "gitleaks" and isinstance(parsed, list):
        for row in parsed:
            if not isinstance(row, dict):
                continue
            rule_id = str(row.get("RuleID") or "gitleaks")
            location = f"{row.get('File', '')}:{row.get('StartLine', '')}".rstrip(":")
            findings.append(
                _external_finding(
                    "gitleaks",
                    marker=str(row.get("Fingerprint") or rule_id),
                    title=f"Potential secret: {rule_id}",
                    severity="high",
                    location=location,
                    evidence={"rule_id": rule_id},
                    cwe="CWE-798",
                    confidence=0.88,
                )
            )
    elif tool_id == "trufflehog":
        for line in stdout_text.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            detector = str(
                row.get("DetectorName") or row.get("DetectorType") or "trufflehog"
            )
            meta = _as_dict(row.get("SourceMetadata"))
            data = _as_dict(meta.get("Data"))
            fs = _as_dict(data.get("Filesystem"))
            secret_location = str(fs.get("file") or "") or None
            verified = bool(row.get("Verified"))
            findings.append(
                _external_finding(
                    "trufflehog",
                    marker=f"{detector}|{secret_location}|{verified}",
                    title=f"Potential secret detected by {detector}",
                    severity="critical" if verified else "high",
                    location=secret_location,
                    evidence={"detector": detector, "verified": verified},
                    cwe="CWE-798",
                    confidence=0.98 if verified else 0.80,
                )
            )
    elif tool_id == "grype" and isinstance(parsed, dict):
        for row in parsed.get("matches") or []:
            if not isinstance(row, dict):
                continue
            vuln = _as_dict(row.get("vulnerability"))
            artifact = _as_dict(row.get("artifact"))
            vuln_id = str(vuln.get("id") or "grype-vuln")
            locations = artifact.get("locations") or []
            location = None
            if locations and isinstance(locations[0], dict):
                location = str(locations[0].get("path") or "") or None
            fix = _as_dict(vuln.get("fix"))
            findings.append(
                _external_finding(
                    "grype",
                    marker=f"{vuln_id}|{artifact.get('name')}|{artifact.get('version')}",
                    title=f"{vuln_id} in {artifact.get('name') or 'dependency'}",
                    severity=str(vuln.get("severity") or "medium"),
                    location=location,
                    evidence={
                        "vulnerability_id": vuln_id,
                        "package": artifact.get("name"),
                        "version": artifact.get("version"),
                        "fix_versions": fix.get("versions"),
                    },
                    confidence=0.90,
                )
            )
    elif tool_id == "osv-scanner" and isinstance(parsed, dict):

        def walk(value: Any, package: str | None = None) -> None:
            if isinstance(value, dict):
                package_name = package
                pkg = value.get("package")
                if isinstance(pkg, dict):
                    package_name = str(pkg.get("name") or package_name or "") or None
                vuln_id = value.get("id")
                aliases = value.get("aliases")
                if isinstance(vuln_id, str) and (
                    vuln_id.startswith("CVE-")
                    or vuln_id.startswith("GHSA-")
                    or vuln_id.startswith("OSV-")
                ):
                    findings.append(
                        _external_finding(
                            "osv-scanner",
                            marker=f"{vuln_id}|{package_name}",
                            title=f"{vuln_id} in {package_name or 'dependency'}",
                            severity="high" if vuln_id.startswith("CVE-") else "medium",
                            evidence={
                                "vulnerability_id": vuln_id,
                                "package": package_name,
                                "aliases": aliases if isinstance(aliases, list) else [],
                            },
                            confidence=0.90,
                        )
                    )
                for child in value.values():
                    walk(child, package_name)
            elif isinstance(value, list):
                for child in value:
                    walk(child, package)

        walk(parsed)
    # Syft is inventory only; it intentionally produces no vulnerability finding.
    return findings


async def run_source_tool(
    tool_id: str, source: Path, *, timeout: int = 300
) -> dict[str, Any]:
    spec = CATALOG_BY_ID.get(tool_id)
    if spec is None or not spec.requires_source:
        raise ValueError("Unsupported source tool")
    if spec.builtin:
        if tool_id in {"aionex-source", "aionex-secrets", "aionex-dependencies"}:
            return scan_source_tree(source)
        raise ValueError("Unsupported builtin source tool")
    if shutil.which(spec.adapter) is None:
        return {"tool": tool_id, "status": "unavailable", "findings": []}
    command = _command_for(tool_id, source)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NO_COLOR": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return {"tool": tool_id, "status": "timeout", "findings": []}
    # Parse the complete tool output before any bounded diagnostic handling. Large
    # Bandit/Trivy/Gitleaks reports can legitimately exceed diagnostic limits;
    # parsing a truncated JSON stream would silently lose findings.
    raw_stdout_text = stdout.decode("utf-8", errors="replace")
    parsed: Any = None
    if tool_id != "trufflehog":
        try:
            parsed = json.loads(raw_stdout_text) if raw_stdout_text.strip() else None
        except json.JSONDecodeError:
            parsed = None
    normalized = _normalize_source_findings(tool_id, parsed, raw_stdout_text)
    stderr_text = redact_tool_output(stderr.decode("utf-8", errors="replace"))[:100_000]
    finding_exit_tools = {"bandit", "osv-scanner", "gitleaks"}
    no_package_sources = (
        tool_id == "osv-scanner"
        and process.returncode == 128
        and "No package sources found" in stderr_text
    )
    completed = (
        process.returncode == 0
        or (process.returncode == 1 and tool_id in finding_exit_tools and bool(normalized))
        or no_package_sources
    )
    return {
        "tool": tool_id,
        "status": "completed" if completed else "failed",
        "exit_code": process.returncode,
        "finding_count": len(normalized),
        "findings": normalized,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr": stderr_text,
    }


def _network_command(tool_id: str, origin: str, hostname: str) -> list[str]:
    """Return fixed, bounded reconnaissance/validation commands for authorized targets."""
    if tool_id == "nuclei":
        templates = os.getenv("AIOS_NUCLEI_TEMPLATES", "/opt/nuclei-templates").strip()
        command = [
            "nuclei",
            "-u",
            origin,
            "-jsonl",
            "-silent",
            "-no-color",
            "-disable-update-check",
            "-etags",
            "dos,fuzz,intrusive",
            "-rl",
            "5",
            "-c",
            "2",
            "-timeout",
            "5",
            "-retries",
            "1",
        ]
        if templates and Path(templates).is_dir():
            command.extend(["-t", templates])
        return command
    if tool_id == "katana":
        return [
            "katana",
            "-u",
            origin,
            "-jsonl",
            "-silent",
            "-d",
            "2",
            "-jc",
            "-fs",
            "fqdn",
        ]
    if tool_id == "projectdiscovery-httpx":
        return [
            "pd-httpx",
            "-u",
            origin,
            "-json",
            "-silent",
            "-no-color",
            "-follow-redirects",
            "-maxr",
            "3",
        ]
    if tool_id == "nmap":
        return [
            "nmap",
            "-Pn",
            "-sT",
            "--top-ports",
            "100",
            "--version-light",
            "-oX",
            "-",
            hostname,
        ]
    if tool_id == "testssl":
        return ["testssl.sh", "--quiet", "--warnings", "off", "--color", "0", origin]
    if tool_id == "zap-baseline":
        return ["zap-baseline.py", "-t", origin, "-I", "-m", "2"]
    raise ValueError(f"No bounded network adapter for {tool_id}")


async def run_network_tool(
    tool_id: str,
    *,
    origin: str,
    hostname: str,
    execution_mode: str,
    timeout: int = 180,
) -> dict[str, Any]:
    spec = CATALOG_BY_ID.get(tool_id)
    if spec is None or not spec.active or spec.requires_source:
        raise ValueError("Unsupported network tool")
    if spec.intrusive or spec.requires_clone:
        if execution_mode != "intrusive_clone":
            return {"tool": tool_id, "status": "blocked_requires_clone", "findings": []}
        # Intrusive engines require a focused, finding-specific scenario instead of
        # blind global execution. The deep-validation planner supplies those cases.
        return {"tool": tool_id, "status": "scenario_required", "findings": []}
    if shutil.which(spec.adapter) is None:
        return {"tool": tool_id, "status": "unavailable", "findings": []}
    if tool_id == "testssl" and urlsplit(origin).scheme.lower() != "https":
        return {
            "tool": tool_id,
            "status": "not_applicable",
            "reason": "https_required",
            "findings": [],
        }
    nikto_output: Path | None = None
    if tool_id == "nikto":
        handle = tempfile.NamedTemporaryFile(
            prefix="aionex-nikto-", suffix=".json", dir="/tmp", delete=False
        )
        handle.close()
        nikto_output = Path(handle.name)
        command = [
            "nikto",
            "-h",
            origin,
            "-nointeractive",
            "-nocheck",
            "-ask",
            "no",
            "-maxtime",
            "60s",
            "-Format",
            "json",
            "-output",
            str(nikto_output),
        ]
    else:
        command = _network_command(tool_id, origin, hostname)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NO_COLOR": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        if nikto_output is not None:
            try:
                nikto_output.unlink(missing_ok=True)
            except OSError:
                nikto_output = None
        return {"tool": tool_id, "status": "timeout", "findings": []}
    stdout_text = redact_tool_output(stdout.decode("utf-8", errors="replace"))[
        :5_000_000
    ]
    stderr_text = redact_tool_output(stderr.decode("utf-8", errors="replace"))[:100_000]
    findings: list[dict[str, Any]] = []
    if tool_id == "nikto" and nikto_output is not None:
        try:
            raw_report = nikto_output.read_text(encoding="utf-8", errors="replace")
            parsed_report = json.loads(raw_report) if raw_report.strip() else []
        except (OSError, json.JSONDecodeError):
            parsed_report = []
        finally:
            try:
                nikto_output.unlink(missing_ok=True)
            except OSError:
                nikto_output = None
        reports = parsed_report if isinstance(parsed_report, list) else []
        for report in reports:
            if not isinstance(report, dict):
                continue
            for row in report.get("vulnerabilities") or []:
                if not isinstance(row, dict):
                    continue
                nikto_id = str(row.get("id") or "nikto")
                method = str(row.get("method") or "GET").upper()
                path = str(row.get("url") or "/")
                message = str(row.get("msg") or f"Nikto finding {nikto_id}")[:300]
                lowered = message.lower()
                if "without the secure" in lowered:
                    severity = "high"
                elif "without the httponly" in lowered or "security header missing" in lowered or "header is not set" in lowered:
                    severity = "medium"
                elif "outdated" in lowered or "deprecated" in lowered:
                    severity = "low"
                else:
                    severity = "low"
                location = origin.rstrip("/") + (path if path.startswith("/") else "/" + path)
                findings.append(
                    _external_finding(
                        "nikto",
                        marker=f"{nikto_id}|{method}|{path}|{message}",
                        title=message,
                        severity=severity,
                        location=location,
                        evidence={"nikto_id": nikto_id, "method": method},
                        confidence=0.76,
                    )
                )
    if tool_id == "nuclei":
        for line in stdout_text.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            info = _as_dict(row.get("info"))
            severity = str(info.get("severity") or "info").lower()
            template_id = str(
                row.get("template-id") or row.get("templateID") or "nuclei"
            )
            matched = str(row.get("matched-at") or row.get("host") or origin)
            title = str(info.get("name") or template_id)[:300]
            findings.append(
                {
                    "source": "nuclei",
                    "category": "template-validation",
                    "title": title,
                    "severity": (
                        severity
                        if severity in {"critical", "high", "medium", "low", "info"}
                        else "info"
                    ),
                    "confidence": 0.82,
                    "state": "observed",
                    "fingerprint": hashlib.sha256(
                        f"nuclei|{template_id}|{matched}".encode()
                    ).hexdigest(),
                    "cwe": None,
                    "owasp": None,
                    "location": matched,
                    "evidence": {
                        "template_id": template_id,
                        "matcher": row.get("matcher-name"),
                    },
                    "remediation": "Review the matched condition, confirm it against source/runtime evidence, then apply the relevant hardening or patch.",
                }
            )
    successful_codes = {0, 1, 2} if tool_id == "zap-baseline" else {0}
    return {
        "tool": tool_id,
        "status": "completed" if process.returncode in successful_codes else "failed",
        "exit_code": process.returncode,
        "finding_count": len(findings),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr": stderr_text,
        "findings": findings,
    }


async def runtime_catalog_snapshot(session) -> list[dict[str, Any]]:
    """Overlay the last durable scanner-worker capability heartbeat on the catalog."""
    from sqlalchemy import select
    from app.db.models import OwnerControlRecord

    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == "security-tools-runtime",
            OwnerControlRecord.resource_id == "default",
        )
    )
    payload = dict(record.payload or {}) if record is not None else {}
    available_ids = {str(value) for value in payload.get("available_ids", [])}
    checked_at = payload.get("checked_at")
    status = record.status if record is not None else "not_reported"
    result = []
    for row in catalog_snapshot():
        item = dict(row)
        item["available"] = (
            item["id"] in available_ids if record is not None else bool(item["builtin"])
        )
        item["runtime_status"] = status
        item["runtime_checked_at"] = checked_at
        result.append(item)
    return result
