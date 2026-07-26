from __future__ import annotations

from dataclasses import dataclass

from .audit import AutonomyAuditLog
from .engine import AutonomyDecisionEngine
from .oversight import AutonomyOversightBoard
from .policies import AutonomyPolicyRegistry


@dataclass
class EnterpriseAutonomyGovernancePlatform:
    policies: AutonomyPolicyRegistry
    decisions: AutonomyDecisionEngine
    audit: AutonomyAuditLog
    oversight: AutonomyOversightBoard

    @classmethod
    def build_default(cls) -> "EnterpriseAutonomyGovernancePlatform":
        policies = AutonomyPolicyRegistry()
        return cls(
            policies=policies,
            decisions=AutonomyDecisionEngine(policies),
            audit=AutonomyAuditLog(),
            oversight=AutonomyOversightBoard(),
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "policy_registry": self.policies is not None,
            "decision_engine": self.decisions is not None,
            "audit_log": self.audit is not None,
            "oversight_board": self.oversight is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
