from __future__ import annotations

from dataclasses import dataclass

from .models import GovernanceCase


@dataclass(frozen=True)
class CouncilOpinion:
    council: str
    support: bool
    confidence: float
    rationale: str


class CouncilRegistry:
    COUNCILS = ("executive", "wisdom", "future", "research", "crisis")

    def deliberate(self, case: GovernanceCase) -> tuple[CouncilOpinion, ...]:
        has_evidence = bool(case.evidence)
        low_risk = len(case.risks) <= 2
        return tuple(
            CouncilOpinion(
                council=name,
                support=has_evidence and (low_risk or name in {"crisis", "research"}),
                confidence=0.90 if has_evidence else 0.35,
                rationale=(
                    "Evidence is sufficient for controlled progression."
                    if has_evidence
                    else "More evidence is required before support."
                ),
            )
            for name in self.COUNCILS
        )
