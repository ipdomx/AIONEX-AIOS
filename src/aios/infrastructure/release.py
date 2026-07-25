from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ReleaseStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    REVOKED = "revoked"


@dataclass(slots=True)
class ReleaseArtifact:
    name: str
    version: str
    digest: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_bytes(cls, name: str, version: str, payload: bytes,
                   metadata: dict[str, Any] | None = None) -> "ReleaseArtifact":
        return cls(name, version, hashlib.sha256(payload).hexdigest(), dict(metadata or {}))


@dataclass(slots=True)
class ReleaseRecord:
    release_id: str
    version: str
    artifacts: list[ReleaseArtifact] = field(default_factory=list)
    status: ReleaseStatus = ReleaseStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_by: str | None = None
    notes: str = ""

    def manifest(self) -> str:
        payload = {
            "release_id": self.release_id,
            "version": self.version,
            "status": self.status.value,
            "artifacts": [
                {"name": artifact.name, "version": artifact.version, "digest": artifact.digest,
                 "metadata": artifact.metadata}
                for artifact in self.artifacts
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class ReleaseManager:
    def __init__(self) -> None:
        self._releases: dict[str, ReleaseRecord] = {}

    def create(self, release_id: str, version: str, notes: str = "") -> ReleaseRecord:
        if release_id in self._releases:
            raise ValueError(f"release already exists: {release_id}")
        record = ReleaseRecord(release_id, version, notes=notes)
        self._releases[release_id] = record
        return record

    def add_artifact(self, release_id: str, artifact: ReleaseArtifact) -> None:
        record = self.get(release_id)
        if record.status is not ReleaseStatus.DRAFT:
            raise RuntimeError("artifacts can only be added to draft releases")
        record.artifacts.append(artifact)

    def approve(self, release_id: str, owner_id: str) -> ReleaseRecord:
        record = self.get(release_id)
        if not record.artifacts:
            raise RuntimeError("release cannot be approved without artifacts")
        record.status = ReleaseStatus.APPROVED
        record.approved_by = owner_id
        return record

    def publish(self, release_id: str) -> ReleaseRecord:
        record = self.get(release_id)
        if record.status is not ReleaseStatus.APPROVED:
            raise PermissionError("release must be owner-approved before publishing")
        record.status = ReleaseStatus.PUBLISHED
        return record

    def get(self, release_id: str) -> ReleaseRecord:
        try:
            return self._releases[release_id]
        except KeyError as exc:
            raise KeyError(f"unknown release: {release_id}") from exc
