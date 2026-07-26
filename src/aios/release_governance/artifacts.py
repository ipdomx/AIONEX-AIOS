from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    release_id: str
    name: str
    digest: str
    size_bytes: int
    media_type: str = "application/octet-stream"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


class ArtifactRegistry:
    def __init__(self) -> None:
        self._artifacts: dict[str, ArtifactManifest] = {}

    def register(self, artifact: ArtifactManifest) -> ArtifactManifest:
        if not artifact.artifact_id.strip() or not artifact.release_id.strip():
            raise ValueError("artifact_id and release_id are required")
        if not artifact.digest.strip() or artifact.size_bytes < 0:
            raise ValueError("valid digest and size_bytes are required")
        if artifact.artifact_id in self._artifacts:
            raise ValueError(f"duplicate artifact_id: {artifact.artifact_id}")
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> ArtifactManifest:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:
            raise LookupError(f"artifact not found: {artifact_id}") from exc

    def list_for_release(self, release_id: str) -> list[ArtifactManifest]:
        return [item for item in self._artifacts.values() if item.release_id == release_id]

    def verify_digest(self, artifact_id: str, digest: str) -> bool:
        return self.get(artifact_id).digest == digest
