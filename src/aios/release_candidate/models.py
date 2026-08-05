from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class CandidateState(str, Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    BLOCKED = "blocked"
    APPROVED = "approved"
    RELEASED = "released"


@dataclass(slots=True)
class ReleaseCandidate:
    candidate_id: str
    version: str
    owner_id: str
    commit_sha: str
    state: CandidateState = CandidateState.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: datetime | None = None
    released_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def start_validation(self) -> None:
        if self.state is not CandidateState.DRAFT:
            raise RuntimeError("candidate must be draft")
        self.state = CandidateState.VALIDATING

    def block(self, reason: str) -> None:
        if self.state is CandidateState.RELEASED:
            raise RuntimeError("released candidate cannot be blocked")
        self.state = CandidateState.BLOCKED
        self.metadata["block_reason"] = reason

    def approve(self) -> None:
        if self.state is not CandidateState.VALIDATING:
            raise RuntimeError("candidate must be validating")
        self.state = CandidateState.APPROVED
        self.approved_at = datetime.now(timezone.utc)

    def release(self) -> None:
        if self.state is not CandidateState.APPROVED:
            raise RuntimeError("candidate must be approved")
        self.state = CandidateState.RELEASED
        self.released_at = datetime.now(timezone.utc)
