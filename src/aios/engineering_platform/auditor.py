from __future__ import annotations

from pathlib import Path
import re

from .models import AuditFinding


class ProjectAuditor:
    SECRET_PATTERNS = (
        re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*['\"][^'\"]{6,}['\"]"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )

    def audit(self, root: str | Path) -> tuple[AuditFinding, ...]:
        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            raise ValueError("project root must be an existing directory")
        findings: list[AuditFinding] = []
        files = [path for path in root_path.rglob("*") if path.is_file() and ".git" not in path.parts]
        if not any(path.name.lower().startswith("readme") for path in files):
            findings.append(self._finding("quality", "medium", "Missing README", str(root_path),
                                         ("Add project purpose, setup, operation and recovery instructions.",),
                                         ("Review README against a clean installation.",)))
        if not any("test" in path.parts or path.name.startswith("test_") for path in files):
            findings.append(self._finding("quality", "high", "No automated tests detected", str(root_path),
                                         ("Add unit and integration tests for critical paths.",),
                                         ("Run the test suite twice from a clean environment.",)))
        for path in files:
            if path.stat().st_size > 1_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for pattern in self.SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append(self._finding("security", "critical", "Possible embedded secret", str(path),
                                                 ("Remove the secret and load it from the approved vault.", "Rotate the exposed credential."),
                                                 ("Run secret scanning.", "Verify the old credential is revoked.")))
                    break
            if "TODO" in text or "FIXME" in text:
                findings.append(self._finding("maintainability", "low", "Unresolved implementation marker", str(path),
                                             ("Convert markers into tracked work items or resolve them.",),
                                             ("Re-run source scan and confirm no untracked marker remains.",)))
        return tuple(findings)

    @staticmethod
    def _finding(category, severity, title, evidence, remediation, verification):
        return AuditFinding(category, severity, title, evidence, remediation, verification)
