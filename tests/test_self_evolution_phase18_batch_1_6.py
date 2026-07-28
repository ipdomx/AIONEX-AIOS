from aios.self_evolution.experiment_manager import Experiment, ExperimentManager, ExperimentState
from aios.self_evolution.models import EvidenceItem, ImprovementProposal, ProposalState
from aios.self_evolution.promotion_gate import PromotionGate
from aios.self_evolution.proposal_service import ImprovementProposalService
from aios.self_evolution.research_engine import ResearchEngine, ResearchQuestion


def test_proposal_requires_verified_evidence() -> None:
    service = ImprovementProposalService()
    proposal = service.create(
        ImprovementProposal(
            proposal_id="p-1",
            owner_id="owner-1",
            title="Improve scheduler",
            hypothesis="new policy lowers latency",
            target_component="scheduler",
            risk_level="medium",
            expected_benefit="lower p95 latency",
        )
    )
    service.add_evidence("p-1", "owner-1", EvidenceItem("benchmark", "latency improved", 0.9, True))
    service.submit_for_review("p-1", "owner-1")
    approved = service.approve("p-1", "owner-1")
    assert approved.state is ProposalState.APPROVED


def test_research_confidence_uses_verified_evidence_only() -> None:
    engine = ResearchEngine()
    engine.open(ResearchQuestion(question_id="q-1", owner_id="owner-1", question="Is change safe?"))
    engine.add_evidence("q-1", "owner-1", EvidenceItem("source-a", "safe", 0.8, True))
    engine.add_evidence("q-1", "owner-1", EvidenceItem("source-b", "uncertain", 0.2, False))
    assert engine.confidence("q-1", "owner-1") == 0.8


def test_experiment_and_promotion_gate() -> None:
    proposal = ImprovementProposal(
        proposal_id="p-2",
        owner_id="owner-1",
        title="Improve router",
        hypothesis="candidate improves quality",
        target_component="router",
        risk_level="low",
        expected_benefit="better score",
        state=ProposalState.APPROVED,
    )
    manager = ExperimentManager()
    experiment = manager.create(
        Experiment(
            experiment_id="e-1",
            owner_id="owner-1",
            proposal_id="p-2",
            control_version="v1",
            candidate_version="v2",
            success_metric="quality",
            rollback_version="v1",
        )
    )
    manager.start("e-1", "owner-1")
    manager.observe("e-1", "owner-1", 0.95)
    manager.finish("e-1", "owner-1", succeeded=True)
    assert experiment.state is ExperimentState.SUCCEEDED
    decision = PromotionGate().evaluate(proposal, experiment)
    assert decision.approved is True


def test_owner_scope_is_enforced() -> None:
    service = ImprovementProposalService()
    service.create(
        ImprovementProposal(
            proposal_id="p-3",
            owner_id="owner-1",
            title="Test",
            hypothesis="test",
            target_component="runtime",
            risk_level="low",
            expected_benefit="test",
        )
    )
    try:
        service.get("p-3", "owner-2")
    except PermissionError:
        pass
    else:
        raise AssertionError("cross-owner access must fail")
