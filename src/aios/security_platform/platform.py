from __future__ import annotations

from pathlib import Path

from .configuration import ConfigurationSecurityAnalyzer
from .dependencies import DependencySecurityAnalyzer
from .ledger import SecurityLedger
from .models import SecurityAssessment, SecurityFinding
from .risk import RiskEngine
from .scanner import SourceSecurityScanner


class SecurityPlatform:
    """Authorized defensive assessment platform with evidence-based remediation."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self.source = SourceSecurityScanner()
        self.dependencies = DependencySecurityAnalyzer()
        self.configuration = ConfigurationSecurityAnalyzer()
        self.risk = RiskEngine()
        self.ledger = SecurityLedger(ledger_path) if ledger_path else None

    def assess(self, project: str, root: str | Path, *, authorization: bool) -> SecurityAssessment:
        if not authorization:
            raise PermissionError("explicit authorization is required for security assessment")
        root_path = Path(root).resolve()
        findings = self._deduplicate((
            *self.source.scan(root_path),
            *self.dependencies.analyze(root_path),
            *self.configuration.analyze(root_path),
        ))
        risk = self.risk.summarize(findings)
        remediation = self._ordered_unique(step for finding in findings for step in finding.remediation)
        verification = self._ordered_unique(step for finding in findings for step in finding.verification)
        assessment = SecurityAssessment(project, str(root_path), True, findings, risk, remediation, verification)
        if self.ledger:
            self.ledger.append(assessment)
        return assessment

    @staticmethod
    def _deduplicate(findings) -> tuple[SecurityFinding, ...]:
        unique: dict[tuple[str, str, str, str], SecurityFinding] = {}
        for finding in findings:
            unique.setdefault((finding.title, finding.category, finding.location, finding.evidence), finding)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        return tuple(sorted(unique.values(), key=lambda f: (severity_order[f.severity.value], f.location, f.title)))

    @staticmethod
    def _ordered_unique(items) -> tuple[str, ...]:
        return tuple(dict.fromkeys(items))

    def status(self) -> dict:
        return {
            "mode": "authorized-defensive-only",
            "source_scanning": "enabled",
            "dependency_analysis": "offline-manifest-analysis",
            "configuration_analysis": "containers-cloud-runtime",
            "risk_scoring": "evidence-weighted",
            "remediation": "multi-step-with-verification",
            "audit_ledger": "hash-chained" if self.ledger else "optional",
        }
