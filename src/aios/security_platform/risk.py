from __future__ import annotations

from collections import Counter

from .models import RiskSummary, SecurityFinding, Severity


class RiskEngine:
    WEIGHTS = {
        Severity.INFO: 0.5,
        Severity.LOW: 2.0,
        Severity.MEDIUM: 6.0,
        Severity.HIGH: 15.0,
        Severity.CRITICAL: 30.0,
    }

    def summarize(self, findings: tuple[SecurityFinding, ...]) -> RiskSummary:
        counts = Counter(f.severity.value for f in findings)
        raw = sum(self.WEIGHTS[f.severity] * max(0.1, min(1.0, f.confidence)) for f in findings)
        score = round(min(100.0, raw), 2)
        grade = "A" if score < 5 else "B" if score < 15 else "C" if score < 35 else "D" if score < 60 else "F"
        blockers = tuple(f.id for f in findings if f.severity in {Severity.CRITICAL, Severity.HIGH})
        return RiskSummary(score, grade, dict(sorted(counts.items())), blockers)
