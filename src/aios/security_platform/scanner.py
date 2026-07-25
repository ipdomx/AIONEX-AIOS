from __future__ import annotations

from pathlib import Path
import re

from .models import SecurityFinding, Severity


class SourceSecurityScanner:
    """Defensive, local source scanner. It never performs network exploitation."""

    SECRET_PATTERNS = (
        ("Private key material", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
        ("Credential assignment", re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password|passwd|pwd)\b\s*[=:]\s*['\"][^'\"\n]{8,}['\"]"
        )),
        ("Cloud access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        ("GitHub token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    )
    CODE_PATTERNS = (
        ("Dynamic code execution", "injection", Severity.HIGH,
         re.compile(r"\b(?:eval|exec)\s*\("),
         ("Remove dynamic execution or strictly constrain input using an allow-list.",),
         ("Add negative tests with untrusted input.", "Run static analysis after remediation.")),
        ("Shell execution with interpolation", "command-injection", Severity.HIGH,
         re.compile(r"(?:shell\s*=\s*True|os\.system\s*\(|Runtime\.getRuntime\(\)\.exec)"),
         ("Use argument arrays and avoid shell interpretation.", "Validate all externally influenced arguments."),
         ("Test hostile metacharacters and verify no shell expansion occurs.",)),
        ("Weak cryptographic hash", "cryptography", Severity.MEDIUM,
         re.compile(r"\b(?:md5|sha1)\s*\(", re.IGNORECASE),
         ("Use a modern algorithm suitable for the purpose, such as SHA-256 or a password KDF.",),
         ("Verify compatibility and add known-answer tests.",)),
        ("TLS verification disabled", "transport-security", Severity.CRITICAL,
         re.compile(r"(?:verify\s*=\s*False|CERT_NONE|rejectUnauthorized\s*:\s*false)"),
         ("Enable certificate validation and configure an approved trust store.",),
         ("Test connection rejection with an invalid certificate.",)),
    )
    TEXT_EXTENSIONS = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".swift", ".go",
        ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb", ".sh",
        ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env", ".sql",
        ".xml", ".properties", ".gradle", ".tf", ".md",
    }
    IGNORED_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}

    def scan(self, root: str | Path) -> tuple[SecurityFinding, ...]:
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ValueError("project root must be an existing directory")
        findings: list[SecurityFinding] = []
        for path in root_path.rglob("*"):
            if not path.is_file() or any(part in self.IGNORED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in self.TEXT_EXTENSIONS and path.name not in {"Dockerfile", "Containerfile"}:
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            relative = str(path.relative_to(root_path))
            for title, pattern in self.SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append(SecurityFinding(
                        title=title,
                        category="secrets",
                        severity=Severity.CRITICAL,
                        location=relative,
                        evidence="A credential-like value or private key pattern was detected; value is redacted.",
                        remediation=("Remove the secret from source control.", "Rotate or revoke the exposed credential.", "Load it from the approved secrets vault."),
                        verification=("Run secret scanning again.", "Verify the old credential is revoked.", "Confirm repository history is remediated when required."),
                        confidence=0.96,
                    ))
                    break
            for title, category, severity, pattern, remediation, verification in self.CODE_PATTERNS:
                if pattern.search(text):
                    findings.append(SecurityFinding(title, category, severity, relative,
                        f"Pattern associated with {category} was detected.", remediation, verification, 0.88))
        return tuple(findings)
