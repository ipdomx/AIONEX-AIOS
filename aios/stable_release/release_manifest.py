from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class StableReleaseState(str, Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    APPROVED = "approved"
    RELEASED = "released"
    WITHDRAWN = "withdrawn"


@dataclass(slots=True)
class StableReleaseManifest:
    release_id: str
    version: str
    owner_id: str
    commit_sha: str
    state: StableReleaseState = StableReleaseState.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: datetime | None = None
    released_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class StableReleaseRegistry:
    def __init__(self) -> None:
        self._releases: dict[str, StableReleaseManifest] = {}

    def register(self, manifest: StableReleaseManifest) -> StableReleaseManifest:
        if manifest.release_id in self._releases:
            raise ValueError(f"duplicate stable release: {manifest.release_id}")
        self._releases[manifest.release_id] = manifest
        return manifest

    def start_validation(self, release_id: str, owner_id: str) -> StableReleaseManifest:
        release = self._require_owner(release_id, owner_id)
        if release.state is not StableReleaseState.DRAFT:
            raise RuntimeError("only draft releases may enter validation")
        release.state = StableReleaseState.VALIDATING
        return release

    def approve(self, release_id: str, owner_id: str) -> StableReleaseManifest:
        release = self._require_owner(release_id, owner_id)
        if release.state is not StableReleaseState.VALIDATING:
            raise RuntimeError("release must be validating before approval")
        release.state = StableReleaseState.APPROVED
        release.approved_at = datetime.now(timezone.utc)
        return release

    def mark_released(self, release_id: str, owner_id: str) -> StableReleaseManifest:
        release = self._require_owner(release_id, owner_id)
        if release.state is not StableReleaseState.APPROVED:
            raise RuntimeError("release must be approved before publication")
        release.state = StableReleaseState.RELEASED
        release.released_at = datetime.now(timezone.utc)
        return release

    def withdraw(self, release_id: str, owner_id: str) -> StableReleaseManifest:
        release = self._require_owner(release_id, owner_id)
        if release.state is StableReleaseState.RELEASED:
            raise RuntimeError("released versions require rollback, not withdrawal")
        release.state = StableReleaseState.WITHDRAWN
        return release

    def _require_owner(self, release_id: str, owner_id: str) -> StableReleaseManifest:
        release = self._releases[release_id]
        if release.owner_id != owner_id:
            raise PermissionError("stable release is not owned by this owner")
        return release
