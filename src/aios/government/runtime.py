from __future__ import annotations

from .court import ConstitutionCourt
from .councils import CouncilRegistry
from .models import GovernanceCase, GovernanceDecision, Verdict
from .owner import OwnerOffice


class GovernmentRuntime:
    """Coordinates councils, constitutional review, and owner authority."""

    def __init__(self, owner_id: str = "owner") -> None:
        self.court = ConstitutionCourt()
        self.councils = CouncilRegistry()
        self.owner = OwnerOffice(owner_id)

    def review(self, case: GovernanceCase) -> dict:
        opinions = self.councils.deliberate(case)
        court = self.court.review(case)
        support = sum(1 for item in opinions if item.support)
        majority = support > len(opinions) / 2

        final: GovernanceDecision = court
        if court.verdict == Verdict.APPROVED and not majority:
            final = GovernanceDecision(
                case_id=case.case_id,
                verdict=Verdict.RETURNED,
                rationale="The councils did not reach a supporting majority.",
                conditions=("additional_deliberation_required",),
                reviewers=tuple(item.council for item in opinions),
                owner_approval_required=case.requires_owner_approval,
            )

        return {
            "case_id": case.case_id,
            "verdict": final.verdict.value,
            "rationale": final.rationale,
            "conditions": list(final.conditions),
            "supporting_councils": support,
            "total_councils": len(opinions),
            "owner_approval_required": final.owner_approval_required,
            "owner_approved": bool(self.owner.get(case.case_id) and self.owner.get(case.case_id).approved),
        }
