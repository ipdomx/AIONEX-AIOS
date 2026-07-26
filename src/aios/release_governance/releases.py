from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ReleaseState(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


@dataclass
class ReleaseCandidate:
    release_id: str
    version: str
    commit_sha: str
    state: ReleaseState = ReleaseState.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)

    def transition(self, target: ReleaseState) -> None:
        allowed = {
            ReleaseState.DRAFT: {ReleaseState.CANDIDATE, ReleaseState.REJECTED},
            ReleaseState.CANDIDATE: {ReleaseState.APPROVED, ReleaseState.REJECTED},
            ReleaseState.APPROVED: {ReleaseState.PROMOTED, ReleaseState.REJECTED},
            ReleaseState.PROMOTED: {ReleaseState.ROLLED_BACK},
            ReleaseState.REJECTED: set(),
            ReleaseState.ROLLED_BACK: set(),
        }
        if target not in allowed[self.state]:
            raise ValueError(f"invalid release transition: {self.state.value} -> {target.value}")
        self.state = target


class ReleaseStore:
    def __init__(self) -> None:
        self._releases: dict[str, ReleaseCandidate] = {}

    def add(self, release: ReleaseCandidate) -> ReleaseCandidate:
        if not release.release_id.strip() or not release.version.strip() or not release.commit_sha.strip():
            raise ValueError("release_id, version, and commit_sha are required")
        if release.release_id in self._releases:
            raise ValueError(f"duplicate release_id: {release.release_id}")
        self._releases[release.release_id] = release
        return release

    def get(self, release_id: str) -> ReleaseCandidate:
        try:
            return self._releases[release_id]
        except KeyError as exc:
            raise LookupError(f"release not found: {release_id}") from exc

    def list_by_state(self, state: ReleaseState) -> list[ReleaseCandidate]:
        return [release for release in self._releases.values() if release.state is state]
