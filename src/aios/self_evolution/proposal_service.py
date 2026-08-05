from __future__ import annotations

from datetime import datetime, timezone

from .models import EvidenceItem, ImprovementProposal, ProposalState


class ImprovementProposalService:
    def __init__(self) -> None:
        self._proposals: dict[str, ImprovementProposal] = {}

    def create(self, proposal: ImprovementProposal) -> ImprovementProposal:
        if proposal.proposal_id in self._proposals:
            raise ValueError(f"duplicate proposal: {proposal.proposal_id}")
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def add_evidence(self, proposal_id: str, owner_id: str, item: EvidenceItem) -> ImprovementProposal:
        proposal = self._require_owner(proposal_id, owner_id)
        if proposal.state not in {ProposalState.DRAFT, ProposalState.UNDER_REVIEW}:
            raise RuntimeError("evidence can only be added before a final decision")
        proposal.evidence.append(item)
        proposal.updated_at = datetime.now(timezone.utc)
        return proposal

    def submit_for_review(self, proposal_id: str, owner_id: str) -> ImprovementProposal:
        proposal = self._require_owner(proposal_id, owner_id)
        if not proposal.evidence:
            raise RuntimeError("proposal requires evidence before review")
        proposal.state = ProposalState.UNDER_REVIEW
        proposal.updated_at = datetime.now(timezone.utc)
        return proposal

    def approve(self, proposal_id: str, owner_id: str) -> ImprovementProposal:
        proposal = self._require_owner(proposal_id, owner_id)
        if proposal.state is not ProposalState.UNDER_REVIEW:
            raise RuntimeError("proposal is not under review")
        if not any(item.verified for item in proposal.evidence):
            raise RuntimeError("proposal requires verified evidence")
        proposal.state = ProposalState.APPROVED
        proposal.updated_at = datetime.now(timezone.utc)
        return proposal

    def reject(self, proposal_id: str, owner_id: str) -> ImprovementProposal:
        proposal = self._require_owner(proposal_id, owner_id)
        if proposal.state is not ProposalState.UNDER_REVIEW:
            raise RuntimeError("proposal is not under review")
        proposal.state = ProposalState.REJECTED
        proposal.updated_at = datetime.now(timezone.utc)
        return proposal

    def get(self, proposal_id: str, owner_id: str) -> ImprovementProposal:
        return self._require_owner(proposal_id, owner_id)

    def _require_owner(self, proposal_id: str, owner_id: str) -> ImprovementProposal:
        proposal = self._proposals[proposal_id]
        if proposal.owner_id != owner_id:
            raise PermissionError("proposal is not owned by this owner")
        return proposal
