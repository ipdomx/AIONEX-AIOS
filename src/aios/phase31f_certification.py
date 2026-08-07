from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class CertificationFinding:
    path: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class CertificationReport:
    passed: bool
    findings: tuple[CertificationFinding, ...]
    aggregate_sha256: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "findings": [asdict(finding) for finding in self.findings],
                "aggregate_sha256": self.aggregate_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


_ALLOWED_NOT_IMPLEMENTED = {
    "src/aios/models/base.py",
    "src/aios/providers/base.py",
    "src/aios/infrastructure/base.py",
}


def certify_repository(root: Path) -> CertificationReport:
    findings: list[CertificationFinding] = []
    source_roots = [
        root / "src",
        root / "web-dashboard" / "backend" / "app",
        root / "web-dashboard" / "frontend" / "src",
    ]
    for source_root in source_roots:
        if not source_root.exists():
            findings.append(CertificationFinding(str(source_root.relative_to(root)), "missing-source-root", "required source root is missing"))
            continue
        for path in source_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if path.name.endswith((".bak", ".orig", ".rej", "~")) or path.name == ".DS_Store":
                findings.append(CertificationFinding(rel, "stale-artifact", "stale source artifact must not ship"))
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".mjs"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if re.search(r"\bunder development\b", text, re.I):
                findings.append(CertificationFinding(rel, "under-development", "production source advertises an unfinished surface"))
            if re.search(r"\blocal-placeholder\b", text) and rel != "src/aios/backend_zero_dead.py":
                findings.append(CertificationFinding(rel, "placeholder-runtime", "placeholder model/runtime identifier remains"))
            if re.search(r"status_code\s*=\s*501", text):
                findings.append(CertificationFinding(rel, "http-501", "dead HTTP 501 surface remains"))
            if rel != "src/aios/phase31f_certification.py" and "raise NotImplementedError" in text and rel not in _ALLOWED_NOT_IMPLEMENTED:
                findings.append(CertificationFinding(rel, "not-implemented", "concrete runtime path remains unimplemented"))

    required = (
        "src/aios/backend_zero_dead.py",
        "src/aios/live_activation.py",
        "src/aios/phase31e_acceptance.py",
        "src/aios/three_d_web/lifecycle.py",
        "tests/test_phase31a_provider_tool_registry.py",
        "tests/test_phase31b_backend_api_zero_dead.py",
        "tests/test_phase31c_frontend_owner_zero_dead.py",
        "tests/test_phase31d_live_activation.py",
        "tests/test_phase31e_full_end_to_end_acceptance.py",
    )
    for rel in required:
        if not (root / rel).is_file():
            findings.append(CertificationFinding(rel, "missing-capability-evidence", "required capability or retained acceptance evidence is missing"))

    canonical = json.dumps(
        [asdict(finding) for finding in sorted(findings, key=lambda item: (item.path, item.code, item.detail))],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return CertificationReport(not findings, tuple(findings), sha256(canonical).hexdigest())
