from __future__ import annotations

from dataclasses import dataclass

from .models import CellOpinion, DecisionStatus, VoteChoice


@dataclass(slots=True, frozen=True)
class VotingResult:
    status: DecisionStatus
    score: float
    quorum_reached: bool
    rationale: str


class VotingEngine:
    VALUES = {
        VoteChoice.APPROVE: 1.0,
        VoteChoice.CONDITIONAL: 0.35,
        VoteChoice.ABSTAIN: 0.0,
        VoteChoice.ESCALATE: -0.25,
        VoteChoice.REJECT: -1.0,
    }

    def __init__(self, quorum_ratio: float = 0.60, approval_threshold: float = 0.45) -> None:
        if not 0 < quorum_ratio <= 1:
            raise ValueError("quorum_ratio must be within (0, 1]")
        self.quorum_ratio = quorum_ratio
        self.approval_threshold = approval_threshold

    def tally(self, opinions: tuple[CellOpinion, ...], total_registered: int) -> VotingResult:
        participating = sum(1 for item in opinions if item.vote is not VoteChoice.ABSTAIN)
        quorum = total_registered > 0 and participating / total_registered >= self.quorum_ratio
        total_weight = sum(item.weight for item in opinions) or 1.0
        score = sum(self.VALUES[item.vote] * item.weight for item in opinions) / total_weight
        hard_reject = any(item.vote is VoteChoice.REJECT and item.cell_id in {"security", "governance"} for item in opinions)
        escalated = any(item.vote is VoteChoice.ESCALATE for item in opinions)

        if not quorum or escalated:
            return VotingResult(DecisionStatus.ESCALATED, score, quorum, "Quorum failed or a cell requested escalation")
        if hard_reject or score <= -0.25:
            return VotingResult(DecisionStatus.REJECTED, score, quorum, "A protected cell rejected the proposal or weighted opposition prevailed")
        if score >= self.approval_threshold and all(item.vote is VoteChoice.APPROVE for item in opinions):
            return VotingResult(DecisionStatus.APPROVED, score, quorum, "All participating cells approved and the weighted threshold passed")
        if score >= 0:
            return VotingResult(DecisionStatus.CONDITIONAL, score, quorum, "The proposal may proceed only after recorded conditions are satisfied")
        return VotingResult(DecisionStatus.REJECTED, score, quorum, "Weighted opposition prevailed")
