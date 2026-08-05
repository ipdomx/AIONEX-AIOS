from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvolutionPolicy:
    owner_id: str
    minimum_confidence: float = 0.8
    require_rollback_plan: bool = True
    require_owner_approval: bool = True
    maximum_risk_score: int = 3


class EvolutionPolicyGuard:
    def validate(
        self,
        *,
        policy: EvolutionPolicy,
        owner_id: str,
        confidence: float,
        risk_score: int,
        rollback_plan: str | None,
        owner_approved: bool,
    ) -> None:
        if owner_id != policy.owner_id:
            raise PermissionError("policy is not owned by this owner")
        if confidence < policy.minimum_confidence:
            raise RuntimeError("confidence is below the promotion threshold")
        if risk_score > policy.maximum_risk_score:
            raise RuntimeError("risk score exceeds policy limit")
        if policy.require_rollback_plan and not rollback_plan:
            raise RuntimeError("rollback plan is required")
        if policy.require_owner_approval and not owner_approved:
            raise RuntimeError("owner approval is required")
