from __future__ import annotations

from statistics import fmean

from .models import DecisionOutcome, DecisionStatus, Proposal
from .registry import CellRegistry
from .voting import VotingEngine


class DeliberationEngine:
    def __init__(self, registry: CellRegistry, voting: VotingEngine | None = None, max_rounds: int = 2) -> None:
        self.registry = registry
        self.voting = voting or VotingEngine()
        self.max_rounds = max_rounds

    def deliberate(self, proposal: Proposal) -> DecisionOutcome:
        last_opinions = ()
        voting_result = None
        for round_number in range(1, self.max_rounds + 1):
            last_opinions = tuple(cell.review(proposal, round_number) for cell in self.registry.all())
            voting_result = self.voting.tally(last_opinions, len(self.registry))
            if voting_result.status is not DecisionStatus.ESCALATED:
                break

        assert voting_result is not None
        conditions = tuple(dict.fromkeys(condition for opinion in last_opinions for condition in opinion.conditions))
        risks = tuple(dict.fromkeys(risk for opinion in last_opinions for risk in opinion.risks))
        confidence = fmean(opinion.confidence for opinion in last_opinions) if last_opinions else 0.0
        consequential = proposal.risk_level in {"high", "critical"} or voting_result.status is not DecisionStatus.APPROVED
        return DecisionOutcome(
            proposal_id=proposal.id,
            status=voting_result.status,
            score=round(voting_result.score, 4),
            confidence=round(confidence, 4),
            quorum_reached=voting_result.quorum_reached,
            round_number=round_number,
            opinions=last_opinions,
            conditions=conditions,
            risks=risks,
            human_approval_required=consequential,
            rationale=voting_result.rationale,
        )
