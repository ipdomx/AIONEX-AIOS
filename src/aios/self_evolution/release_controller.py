from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EvolutionReleaseState(str, Enum):
    CANDIDATE = "candidate"
    CANARY = "canary"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


@dataclass(slots=True)
class EvolutionRelease:
    release_id: str
    owner_id: str
    proposal_id: str
    experiment_id: str
    state: EvolutionReleaseState = EvolutionReleaseState.CANDIDATE
    canary_percentage: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    promoted_at: datetime | None = None


class EvolutionReleaseController:
    def __init__(self) -> None:
        self._releases: dict[str, EvolutionRelease] = {}

    def register(self, release: EvolutionRelease) -> EvolutionRelease:
        if release.release_id in self._releases:
            raise ValueError(f"duplicate release: {release.release_id}")
        self._releases[release.release_id] = release
        return release

    def canary(self, release_id: str, owner_id: str, percentage: int) -> EvolutionRelease:
        if not 1 <= percentage <= 50:
            raise ValueError("canary percentage must be between 1 and 50")
        release = self._require_owner(release_id, owner_id)
        if release.state is not EvolutionReleaseState.CANDIDATE:
            raise RuntimeError("release is not a candidate")
        release.state = EvolutionReleaseState.CANARY
        release.canary_percentage = percentage
        return release

    def promote(self, release_id: str, owner_id: str) -> EvolutionRelease:
        release = self._require_owner(release_id, owner_id)
        if release.state not in {EvolutionReleaseState.CANDIDATE, EvolutionReleaseState.CANARY}:
            raise RuntimeError("release cannot be promoted")
        release.state = EvolutionReleaseState.PROMOTED
        release.canary_percentage = 100
        release.promoted_at = datetime.now(timezone.utc)
        return release

    def rollback(self, release_id: str, owner_id: str) -> EvolutionRelease:
        release = self._require_owner(release_id, owner_id)
        release.state = EvolutionReleaseState.ROLLED_BACK
        release.canary_percentage = 0
        return release

    def _require_owner(self, release_id: str, owner_id: str) -> EvolutionRelease:
        release = self._releases[release_id]
        if release.owner_id != owner_id:
            raise PermissionError("release is not owned by this owner")
        return release
