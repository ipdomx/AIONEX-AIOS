import pytest

from aios.autonomy_governance import (
    AutonomyLevel,
    AutonomyPolicy,
    AutonomousDecision,
    DecisionStatus,
    EnterpriseAutonomyGovernancePlatform,
)


def test_autonomy_governance_end_to_end() -> None:
    platform = EnterpriseAutonomyGovernancePlatform.build_default()
    platform.policies.register(
        AutonomyPolicy(
            policy_id="policy-1",
            scope="project:alpha",
            level=AutonomyLevel.SUPERVISED,
            allowed_actions=frozenset({"restart_worker", "rebalance_queue"}),
            requires_owner_approval=True,
            max_risk_score=0.3,
        )
    )
    decision = platform.decisions.propose(
        AutonomousDecision(
            decision_id="decision-1",
            policy_id="policy-1",
            action="restart_worker",
            rationale="Worker health checks failed repeatedly.",
            risk_score=0.2,
            evidence=["health-check-17", "incident-44"],
        )
    )
    platform.audit.record_decision(decision, "proposed", "runtime")
    platform.decisions.approve(decision.decision_id, "owner-1")
    platform.audit.record_decision(decision, "approved", "owner-1")
    platform.decisions.execute(decision.decision_id)
    platform.audit.record_decision(decision, "executed", "runtime")
    finding = platform.oversight.inspect(decision)

    assert decision.status is DecisionStatus.EXECUTED
    assert finding.compliant is True
    assert platform.audit.count() == 3
    assert platform.validate()["ready"] is True


def test_autonomy_controls_and_rollback() -> None:
    platform = EnterpriseAutonomyGovernancePlatform.build_default()
    platform.policies.register(
        AutonomyPolicy(
            policy_id="policy-2",
            scope="infrastructure",
            level=AutonomyLevel.CONTROLLED,
            allowed_actions=frozenset({"scale_service"}),
            requires_owner_approval=False,
            max_risk_score=0.1,
        )
    )

    with pytest.raises(PermissionError):
        platform.decisions.propose(
            AutonomousDecision(
                decision_id="decision-risky",
                policy_id="policy-2",
                action="scale_service",
                rationale="Capacity threshold exceeded.",
                risk_score=0.5,
            )
        )

    decision = platform.decisions.propose(
        AutonomousDecision(
            decision_id="decision-2",
            policy_id="policy-2",
            action="scale_service",
            rationale="Verified demand requires one additional replica.",
            risk_score=0.05,
        )
    )
    platform.decisions.execute(decision.decision_id)
    platform.decisions.rollback(decision.decision_id, "rollback-2")

    assert decision.status is DecisionStatus.ROLLED_BACK
    assert decision.rollback_reference == "rollback-2"
