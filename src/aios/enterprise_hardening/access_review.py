from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ReviewDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"


@dataclass(slots=True)
class AccessGrant:
    grant_id: str
    owner_id: str
    principal_id: str
    permission: str
    privileged: bool = False
    decision: ReviewDecision = ReviewDecision.PENDING
    reviewed_at: datetime | None = None
    evidence: list[str] = field(default_factory=list)


class AccessReviewService:
    def __init__(self) -> None:
        self._grants: dict[str, AccessGrant] = {}

    def register(self, grant: AccessGrant) -> AccessGrant:
        if grant.grant_id in self._grants:
            raise ValueError(f"duplicate access grant: {grant.grant_id}")
        self._grants[grant.grant_id] = grant
        return grant

    def decide(
        self,
        grant_id: str,
        owner_id: str,
        decision: ReviewDecision,
        evidence: str,
    ) -> AccessGrant:
        grant = self._require_owner(grant_id, owner_id)
        if grant.decision is not ReviewDecision.PENDING:
            raise RuntimeError("access review decision is immutable")
        if decision is ReviewDecision.PENDING:
            raise ValueError("final decision required")
        grant.decision = decision
        grant.reviewed_at = datetime.now(timezone.utc)
        grant.evidence.append(evidence)
        return grant

    def pending_privileged(self, owner_id: str) -> list[AccessGrant]:
        return [
            grant
            for grant in self._grants.values()
            if grant.owner_id == owner_id
            and grant.privileged
            and grant.decision is ReviewDecision.PENDING
        ]

    def _require_owner(self, grant_id: str, owner_id: str) -> AccessGrant:
        grant = self._grants[grant_id]
        if grant.owner_id != owner_id:
            raise PermissionError("access grant is not owned by this owner")
        return grant
