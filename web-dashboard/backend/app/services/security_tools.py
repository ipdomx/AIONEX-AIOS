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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

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
    ToolSpec("aionex-tls", "tls", "builtin", builtin=True, description="TLS certificate/protocol posture"),
    ToolSpec("aionex-headers", "headers", "builtin", builtin=True, description="HTTP security headers, cookies and CSP"),
    ToolSpec("aionex-source", "sast", "builtin", builtin=True, requires_source=True, description="Cross-language risky-pattern analysis"),
    ToolSpec("aionex-secrets", "secrets", "builtin", builtin=True, requires_source=True, description="Credential and private-key pattern detection"),
    ToolSpec("aionex-dependencies", "dependencies", "builtin", builtin=True, requires_source=True, description="Dependency manifest inventory"),
    ToolSpec("semgrep", "sast", "semgrep", requires_source=True, description="Semgrep static analysis"),
    ToolSpec("codeql", "sast", "codeql", requires_source=True, description="CodeQL deep source analysis"),
    ToolSpec("bandit", "sast", "bandit", requires_source=True, description="Python security analysis"),
    ToolSpec("trivy", "containers", "trivy", requires_source=True, description="Vulnerabilities, misconfiguration and secrets"),
    ToolSpec("osv-scanner", "dependencies", "osv-scanner", requires_source=True, description="OSV dependency and lockfile analysis"),
    ToolSpec("trufflehog", "secrets", "trufflehog", requires_source=True, description="Verified-capable secret discovery"),
    ToolSpec("gitleaks", "secrets", "gitleaks", requires_source=True, description="Additional secret detection"),
    ToolSpec("syft", "sbom", "syft", requires_source=True, description="CycloneDX/SPDX SBOM generation"),
    ToolSpec("dependency-check", "dependencies", "dependency-check", requires_source=True, description="OWASP Dependency-Check adapter"),
    ToolSpec("npm-audit", "dependencies", "npm", requires_source=True, description="npm audit adapter"),
    ToolSpec("pip-audit", "dependencies", "pip-audit", requires_source=True, description="Python dependency audit"),
    ToolSpec("composer-audit", "dependencies", "composer", requires_source=True, description="Composer advisory audit"),
    ToolSpec("phpstan", "sast", "phpstan", requires_source=True, description="PHP static analysis"),
    ToolSpec("psalm", "sast", "psalm", requires_source=True, description="PHP security/type analysis"),
    ToolSpec("eslint-security", "sast", "eslint", requires_source=True, description="JavaScript security lint adapter"),
    ToolSpec("sonarqube", "sast", "sonar-scanner", requires_source=True, description="Optional SonarQube enterprise integration"),
    ToolSpec("snyk", "dependencies", "snyk", requires_source=True, description="Optional Snyk integration"),
    ToolSpec("clair", "containers", "clairctl", requires_source=True, description="Optional Clair image analysis"),
    ToolSpec("docker-bench", "containers", "docker-bench-security", description="Docker hardening benchmark"),
)

CATALOG_BY_ID = {item.id: item for item in TOOL_CATALOG}

_ALLOWED_SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".php", ".rb", ".java", ".kt", ".go", ".rs",
    ".cs", ".c", ".cc", ".cpp", ".h", ".hpp", ".sh", ".bash", ".yml", ".yaml", ".json", ".toml",
    ".ini", ".conf", ".xml", ".properties", ".env.example",
}
_MANIFEST_NAMES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "requirements.txt", "requirements-runtime.txt",
    "pyproject.toml", "poetry.lock", "Pipfile.lock", "composer.json", "composer.lock", "Gemfile.lock", "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock", "pom.xml", "build.gradle", "build.gradle.kts",
}
_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "dist", "build", ".next", "coverage"}
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "critical"),
    ("generic-secret-assignment", re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\n]{12,}['\"]"), "high"),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "critical"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"), "critical"),
)
_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    ("python-eval", re.compile(r"\beval\s*\("), "high", "CWE-95"),
    ("python-exec", re.compile(r"\bexec\s*\("), "high", "CWE-95"),
    ("shell-true", re.compile(r"shell\s*=\s*True"), "high", "CWE-78"),
    ("pickle-load", re.compile(r"\bpickle\.(?:load|loads)\s*\("), "high", "CWE-502"),
    ("php-eval", re.compile(r"(?i)\beval\s*\("), "high", "CWE-95"),
    ("php-system", re.compile(r"(?i)\b(?:system|passthru|shell_exec)\s*\("), "high", "CWE-78"),
    ("node-child-exec", re.compile(r"(?:child_process\.)?exec(?:Sync)?\s*\("), "high", "CWE-78"),
    ("weak-tls-disable", re.compile(r"(?i)(?:verify\s*=\s*False|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0)"), "high", "CWE-295"),
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
        if suffix not in _ALLOWED_SOURCE_SUFFIXES and path.name not in _MANIFEST_NAMES:
            continue
        scanned += 1
        text = _safe_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for marker, pattern, severity in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append({
                        "source": "aionex-secrets",
                        "category": "secret-exposure",
                        "title": f"Potential {marker} in source snapshot",
                        "severity": severity,
                        "confidence": 0.78,
                        "state": "observed",
                        "fingerprint": _fingerprint("secret", relative_path.as_posix(), line_no, marker),
                        "cwe": "CWE-798",
                        "location": f"{relative_path.as_posix()}:{line_no}",
                        "evidence": {"marker": marker, "line": line_no},
                        "remediation": "Remove the credential from source/history, rotate it, and use the configured secret store.",
                    })
            for marker, pattern, severity, cwe in _RISK_PATTERNS:
                if pattern.search(line):
                    findings.append({
                        "source": "aionex-source",
                        "category": "risky-code-pattern",
                        "title": f"Risky code pattern: {marker}",
                        "severity": severity,
                        "confidence": 0.62,
                        "state": "observed",
                        "fingerprint": _fingerprint("sast", relative_path.as_posix(), line_no, marker),
                        "cwe": cwe,
                        "location": f"{relative_path.as_posix()}:{line_no}",
                        "evidence": {"marker": marker, "line": line_no},
                        "remediation": "Replace the risky primitive with a constrained API and validate untrusted inputs before use.",
                    })
    return {
        "scanner": "aionex-source-v1",
        "files_scanned": scanned,
        "truncated": scanned >= max_files,
        "manifests": sorted(set(manifests)),
        "findings": findings,
    }


def redact_tool_output(value: str) -> str:
    return _REDACT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)


def _command_for(tool_id: str, source: Path) -> list[str]:
    source = source.resolve(strict=True)
    if tool_id == "trivy":
        return ["trivy", "fs", "--format", "json", "--scanners", "vuln,misconfig,secret", "--exit-code", "0", "--no-progress", str(source)]
    if tool_id == "osv-scanner":
        return ["osv-scanner", "scan", "source", "-r", str(source), "--format", "json"]
    if tool_id == "trufflehog":
        return ["trufflehog", "filesystem", str(source), "--json", "--no-update"]
    if tool_id == "gitleaks":
        return ["gitleaks", "dir", str(source), "--report-format", "json", "--report-path", "-"]
    if tool_id == "syft":
        return ["syft", f"dir:{source}", "-o", "cyclonedx-json"]
    if tool_id == "bandit":
        return ["bandit", "-r", str(source), "-f", "json", "-q"]
    if tool_id == "semgrep":
        rules = os.getenv("AIOS_SEMGREP_RULESET", "").strip()
        if not rules:
            raise ValueError("Semgrep requires an Owner-configured local AIOS_SEMGREP_RULESET")
        return ["semgrep", "scan", "--config", rules, "--json", "--quiet", str(source)]
    raise ValueError(f"No safe source adapter for {tool_id}")


async def run_source_tool(tool_id: str, source: Path, *, timeout: int = 300) -> dict[str, Any]:
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
    stdout_text = redact_tool_output(stdout.decode("utf-8", errors="replace"))[:5_000_000]
    stderr_text = redact_tool_output(stderr.decode("utf-8", errors="replace"))[:100_000]
    parsed: Any = None
    try:
        parsed = json.loads(stdout_text) if stdout_text.strip() else None
    except json.JSONDecodeError:
        parsed = None
    return {
        "tool": tool_id,
        "status": "completed" if process.returncode in {0, 1} else "failed",
        "exit_code": process.returncode,
        "result": parsed,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr": stderr_text,
    }
