from __future__ import annotations

from datetime import datetime, timezone

from .models import AutonomousDecision, DecisionStatus
from .policies import AutonomyPolicyRegistry


class AutonomyDecisionEngine:
    def __init__(self, policies: AutonomyPolicyRegistry) -> None:
        self.policies = policies
        self._decisions: dict[str, AutonomousDecision] = {}

    def propose(self, decision: AutonomousDecision) -> AutonomousDecision:
        if not decision.decision_id.strip() or not decision.action.strip():
            raise ValueError("decision_id and action are required")
        if not decision.rationale.strip():
            raise ValueError("rationale is required")
        if not 0.0 <= decision.risk_score <= 1.0:
            raise ValueError("risk_score must be between 0 and 1")
        policy = self.policies.get(decision.policy_id)
        if decision.action not in policy.allowed_actions:
            raise PermissionError(f"action not allowed by policy: {decision.action}")
        if decision.risk_score > policy.max_risk_score:
            raise PermissionError("decision risk exceeds policy threshold")
        if decision.decision_id in self._decisions:
            raise ValueError(f"duplicate decision_id: {decision.decision_id}")
        self._decisions[decision.decision_id] = decision
        return decision

    def approve(self, decision_id: str, approver: str) -> AutonomousDecision:
        decision = self.get(decision_id)
        if decision.status is not DecisionStatus.PROPOSED:
            raise ValueError("only proposed decisions can be approved")
        if not approver.strip():
            raise ValueError("approver is required")
        decision.status = DecisionStatus.APPROVED
        decision.approved_by = approver
        return decision

    def reject(self, decision_id: str) -> AutonomousDecision:
        decision = self.get(decision_id)
        if decision.status is not DecisionStatus.PROPOSED:
            raise ValueError("only proposed decisions can be rejected")
        decision.status = DecisionStatus.REJECTED
        return decision

    def execute(self, decision_id: str) -> AutonomousDecision:
        decision = self.get(decision_id)
        policy = self.policies.get(decision.policy_id)
        if policy.requires_owner_approval and decision.status is not DecisionStatus.APPROVED:
            raise PermissionError("owner approval is required")
        if not policy.requires_owner_approval and decision.status is DecisionStatus.PROPOSED:
            decision.status = DecisionStatus.APPROVED
            decision.approved_by = "policy:auto"
        if decision.status is not DecisionStatus.APPROVED:
            raise ValueError("decision is not executable")
        decision.status = DecisionStatus.EXECUTED
        decision.executed_at = datetime.now(timezone.utc)
        return decision

    def rollback(self, decision_id: str, reference: str) -> AutonomousDecision:
        decision = self.get(decision_id)
        if decision.status is not DecisionStatus.EXECUTED:
            raise ValueError("only executed decisions can be rolled back")
        if not reference.strip():
            raise ValueError("rollback reference is required")
        decision.status = DecisionStatus.ROLLED_BACK
        decision.rollback_reference = reference
        return decision

    def get(self, decision_id: str) -> AutonomousDecision:
        try:
            return self._decisions[decision_id]
        except KeyError as exc:
            raise LookupError(f"decision not found: {decision_id}") from exc

    def list_by_status(self, status: DecisionStatus) -> list[AutonomousDecision]:
        return [decision for decision in self._decisions.values() if decision.status is status]
