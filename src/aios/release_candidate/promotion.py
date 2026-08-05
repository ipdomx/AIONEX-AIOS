from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .models import CandidateState, ReleaseCandidate


class PromotionStage(str, Enum):
    STAGING = "staging"
    CANARY = "canary"
    PRODUCTION = "production"


@dataclass(slots=True)
class PromotionRecord:
    candidate_id: str
    stage: PromotionStage
    owner_id: str
    approved_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, object] = field(default_factory=dict)


class ReleasePromotionService:
    def __init__(self) -> None:
        self._records: list[PromotionRecord] = []

    def promote(
        self,
        candidate: ReleaseCandidate,
        *,
        stage: PromotionStage,
        owner_id: str,
        approved_by: str,
    ) -> PromotionRecord:
        if candidate.owner_id != owner_id:
            raise PermissionError("candidate is not owned by this owner")
        if candidate.state is not CandidateState.APPROVED:
            raise RuntimeError("candidate must be approved before promotion")
        record = PromotionRecord(
            candidate_id=candidate.candidate_id,
            stage=stage,
            owner_id=owner_id,
            approved_by=approved_by,
        )
        self._records.append(record)
        if stage is PromotionStage.PRODUCTION:
            candidate.release()
        return record

    def history(self, candidate_id: str) -> list[PromotionRecord]:
        return [record for record in self._records if record.candidate_id == candidate_id]
