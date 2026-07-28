from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ReleaseChannel(str, Enum):
    INTERNAL = "internal"
    BETA = "beta"
    PRODUCTION = "production"


@dataclass(slots=True)
class AndroidRelease:
    version_name: str
    version_code: int
    artifact_sha256: str
    channel: ReleaseChannel
    notes: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AndroidReleaseManager:
    def __init__(self) -> None:
        self._releases: list[AndroidRelease] = []

    def publish(self, release: AndroidRelease) -> AndroidRelease:
        if release.version_code <= 0:
            raise ValueError("version code must be positive")
        if len(release.artifact_sha256) != 64:
            raise ValueError("artifact sha256 must be 64 hexadecimal characters")
        try:
            int(release.artifact_sha256, 16)
        except ValueError as exc:
            raise ValueError("artifact sha256 must be hexadecimal") from exc
        if any(item.version_code >= release.version_code for item in self._releases):
            raise ValueError("version code must increase monotonically")
        self._releases.append(release)
        return release

    def latest(self, channel: ReleaseChannel) -> AndroidRelease | None:
        matches = [release for release in self._releases if release.channel is channel]
        return max(matches, key=lambda release: release.version_code, default=None)

    def promote(self, version_code: int, channel: ReleaseChannel) -> AndroidRelease:
        source = next(release for release in self._releases if release.version_code == version_code)
        if channel is ReleaseChannel.PRODUCTION and source.channel is ReleaseChannel.INTERNAL:
            raise RuntimeError("internal releases must pass through beta before production")
        promoted = AndroidRelease(
            version_name=source.version_name,
            version_code=max(item.version_code for item in self._releases) + 1,
            artifact_sha256=source.artifact_sha256,
            channel=channel,
            notes=f"Promoted from {source.channel.value}: {source.notes}",
        )
        return self.publish(promoted)
