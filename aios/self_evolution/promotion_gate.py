from __future__ import annotations

from dataclasses import dataclass

from .experiment_manager import Experiment, ExperimentState
from .models import ImprovementProposal, ProposalState


@dataclass(slots=True)
class PromotionDecision:
    approved: bool
    reason: str
    rollback_version: str


class PromotionGate:
    def evaluate(self, proposal: ImprovementProposal, experiment: Experiment) -> PromotionDecision:
        if proposal.proposal_id != experiment.proposal_id:
            return PromotionDecision(False, "proposal and experiment do not match", experiment.rollback_version)
        if proposal.state is not ProposalState.APPROVED:
            return PromotionDecision(False, "proposal is not approved", experiment.rollback_version)
        if experiment.state is not ExperimentState.SUCCEEDED:
            return PromotionDecision(False, "experiment did not succeed", experiment.rollback_version)
        if not experiment.observations:
            return PromotionDecision(False, "experiment has no observations", experiment.rollback_version)
        return PromotionDecision(True, "promotion criteria satisfied", experiment.rollback_version)
