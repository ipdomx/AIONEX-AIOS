from __future__ import annotations

from .models import GovernanceCase, GovernanceDecision, Verdict


class ConstitutionCourt:
    """Final policy gate. It never executes actions; it only issues a verdict."""

    def review(self, case: GovernanceCase) -> GovernanceDecision:
        violations: list[str] = []
        if not case.evidence:
            violations.append("missing_evidence")
        if case.metadata.get("bypass_audit"):
            violations.append("audit_bypass_forbidden")
        if case.metadata.get("irreversible") and not case.metadata.get("rollback_plan"):
            violations.append("rollback_plan_required")
        if case.metadata.get("external_target") and not case.metadata.get("authorization"):
            violations.append("authorization_required")

        if violations:
            return GovernanceDecision(
                case_id=case.case_id,
                verdict=Verdict.RETURNED,
                rationale="The proposal does not satisfy constitutional safeguards.",
                conditions=tuple(violations),
                reviewers=("constitution_court",),
                owner_approval_required=case.requires_owner_approval,
            )

        return GovernanceDecision(
            case_id=case.case_id,
            verdict=Verdict.APPROVED,
            rationale="The proposal has evidence and no detected constitutional conflict.",
            reviewers=("constitution_court",),
            owner_approval_required=case.requires_owner_approval,
        )
