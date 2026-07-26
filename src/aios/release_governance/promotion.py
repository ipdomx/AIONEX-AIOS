from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .releases import ReleaseCandidate, ReleaseState


class EnvironmentStage(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass(frozen=True)
class PromotionRecord:
    release_id: str
    from_stage: EnvironmentStage
    to_stage: EnvironmentStage
    actor_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


class ReleasePromotionManager:
    def __init__(self) -> None:
        self._stage: dict[str, EnvironmentStage] = {}
        self._records: list[PromotionRecord] = []

    def current_stage(self, release_id: str) -> EnvironmentStage:
        return self._stage.get(release_id, EnvironmentStage.DEVELOPMENT)

    def promote(
        self,
        release: ReleaseCandidate,
        to_stage: EnvironmentStage,
        actor_id: str,
    ) -> PromotionRecord:
        if not actor_id.strip():
            raise ValueError("actor_id is required")
        current = self.current_stage(release.release_id)
        allowed = {
            EnvironmentStage.DEVELOPMENT: {EnvironmentStage.STAGING},
            EnvironmentStage.STAGING: {EnvironmentStage.PRODUCTION},
            EnvironmentStage.PRODUCTION: set(),
        }
        if to_stage not in allowed[current]:
            raise ValueError(f"invalid promotion: {current.value} -> {to_stage.value}")
        if to_stage is EnvironmentStage.PRODUCTION and release.state is not ReleaseState.APPROVED:
            raise ValueError("release must be approved before production promotion")
        record = PromotionRecord(release.release_id, current, to_stage, actor_id)
        self._stage[release.release_id] = to_stage
        self._records.append(record)
        if to_stage is EnvironmentStage.PRODUCTION:
            release.transition(ReleaseState.PROMOTED)
        return record

    def history(self, release_id: str) -> list[PromotionRecord]:
        return [record for record in self._records if record.release_id == release_id]
