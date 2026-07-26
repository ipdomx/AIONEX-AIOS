from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import AutonomousDecision, DecisionStatus


@dataclass(frozen=True)
class OversightFinding:
    finding_id: str
    decision_id: str
    compliant: bool
    reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AutonomyOversightBoard:
    def __init__(self) -> None:
        self._findings: list[OversightFinding] = []

    def inspect(self, decision: AutonomousDecision) -> OversightFinding:
        compliant = bool(decision.rationale.strip()) and 0.0 <= decision.risk_score <= 1.0
        if decision.status in {DecisionStatus.EXECUTED, DecisionStatus.ROLLED_BACK}:
            compliant = compliant and decision.executed_at is not None
        reason = "decision satisfies oversight controls" if compliant else "decision failed oversight controls"
        finding = OversightFinding(
            finding_id=f"finding-{len(self._findings) + 1}",
            decision_id=decision.decision_id,
            compliant=compliant,
            reason=reason,
        )
        self._findings.append(finding)
        return finding

    def list_for_decision(self, decision_id: str) -> list[OversightFinding]:
        return [finding for finding in self._findings if finding.decision_id == decision_id]

    def readiness_score(self) -> float:
        if not self._findings:
            return 1.0
        return sum(1 for finding in self._findings if finding.compliant) / len(self._findings)
