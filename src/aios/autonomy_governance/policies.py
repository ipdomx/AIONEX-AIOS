from __future__ import annotations

from .models import AutonomyPolicy


class AutonomyPolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, AutonomyPolicy] = {}

    def register(self, policy: AutonomyPolicy) -> AutonomyPolicy:
        if not policy.policy_id.strip() or not policy.scope.strip():
            raise ValueError("policy_id and scope are required")
        if not policy.allowed_actions:
            raise ValueError("allowed_actions cannot be empty")
        if not 0.0 <= policy.max_risk_score <= 1.0:
            raise ValueError("max_risk_score must be between 0 and 1")
        self._policies[policy.policy_id] = policy
        return policy

    def get(self, policy_id: str) -> AutonomyPolicy:
        try:
            return self._policies[policy_id]
        except KeyError as exc:
            raise LookupError(f"policy not found: {policy_id}") from exc

    def list_for_scope(self, scope: str) -> list[AutonomyPolicy]:
        return [policy for policy in self._policies.values() if policy.scope == scope]

    def count(self) -> int:
        return len(self._policies)
