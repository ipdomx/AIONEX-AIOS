from aios.self_evolution.knowledge_synthesis import KnowledgeFinding, KnowledgeSynthesisService
from aios.self_evolution.policy_guard import EvolutionPolicy, EvolutionPolicyGuard
from aios.self_evolution.promotion_audit import PromotionAuditLog
from aios.self_evolution.release_controller import (
    EvolutionRelease,
    EvolutionReleaseController,
    EvolutionReleaseState,
)
from aios.self_evolution.rollback_manager import RollbackManager, RollbackRecord, RollbackState


def test_knowledge_synthesis_requires_evidence() -> None:
    service = KnowledgeSynthesisService()
    finding = service.publish(
        KnowledgeFinding(
            finding_id="finding-1",
            owner_id="owner-1",
            topic="scheduler",
            statement="least-loaded scheduling improves queue latency",
            confidence=0.91,
            evidence_ids=["evidence-1"],
        )
    )
    assert finding.confidence == 0.91
    assert service.list_for_owner("owner-1", minimum_confidence=0.9)[0].finding_id == "finding-1"


def test_policy_guard_enforces_owner_and_safety() -> None:
    policy = EvolutionPolicy(owner_id="owner-1")
    EvolutionPolicyGuard().validate(
        policy=policy,
        owner_id="owner-1",
        confidence=0.9,
        risk_score=2,
        rollback_plan="restore previous scheduler",
        owner_approved=True,
    )


def test_rollback_lifecycle_and_owner_scope() -> None:
    manager = RollbackManager()
    manager.register(
        RollbackRecord(
            rollback_id="rollback-1",
            owner_id="owner-1",
            experiment_id="experiment-1",
            plan="restore checkpoint",
        )
    )
    assert manager.start("rollback-1", "owner-1").state is RollbackState.EXECUTING
    assert manager.complete("rollback-1", "owner-1").state is RollbackState.COMPLETED


def test_promotion_audit_chain_is_valid() -> None:
    log = PromotionAuditLog()
    log.append(
        entry_id="audit-1",
        owner_id="owner-1",
        proposal_id="proposal-1",
        action="approved",
        actor_id="owner-1",
    )
    log.append(
        entry_id="audit-2",
        owner_id="owner-1",
        proposal_id="proposal-1",
        action="promoted",
        actor_id="owner-1",
    )
    assert log.verify() is True
    assert len(log.list_for_owner("owner-1")) == 2


def test_release_canary_promotion_and_rollback() -> None:
    controller = EvolutionReleaseController()
    controller.register(
        EvolutionRelease(
            release_id="release-1",
            owner_id="owner-1",
            proposal_id="proposal-1",
            experiment_id="experiment-1",
        )
    )
    assert controller.canary("release-1", "owner-1", 10).state is EvolutionReleaseState.CANARY
    assert controller.promote("release-1", "owner-1").state is EvolutionReleaseState.PROMOTED
    assert controller.rollback("release-1", "owner-1").state is EvolutionReleaseState.ROLLED_BACK
