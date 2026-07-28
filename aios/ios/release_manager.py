from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class IOSReleaseStage(str, Enum):
    INTERNAL = "internal"
    TESTFLIGHT = "testflight"
    PHASED = "phased"
    PRODUCTION = "production"
    HALTED = "halted"


@dataclass(slots=True)
class IOSRelease:
    release_id: str
    version: str
    build_number: int
    stage: IOSReleaseStage = IOSReleaseStage.INTERNAL
    rollout_percent: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IOSReleaseManager:
    def __init__(self) -> None:
        self._releases: dict[str, IOSRelease] = {}

    def create(self, release: IOSRelease) -> IOSRelease:
        if release.release_id in self._releases:
            raise ValueError(f"duplicate release: {release.release_id}")
        if release.build_number <= 0:
            raise ValueError("build_number must be positive")
        self._releases[release.release_id] = release
        return release

    def promote(self, release_id: str, stage: IOSReleaseStage, *, rollout_percent: int | None = None) -> IOSRelease:
        release = self._releases[release_id]
        allowed = {
            IOSReleaseStage.INTERNAL: {IOSReleaseStage.TESTFLIGHT, IOSReleaseStage.HALTED},
            IOSReleaseStage.TESTFLIGHT: {IOSReleaseStage.PHASED, IOSReleaseStage.PRODUCTION, IOSReleaseStage.HALTED},
            IOSReleaseStage.PHASED: {IOSReleaseStage.PRODUCTION, IOSReleaseStage.HALTED},
            IOSReleaseStage.PRODUCTION: {IOSReleaseStage.HALTED},
            IOSReleaseStage.HALTED: set(),
        }
        if stage not in allowed[release.stage]:
            raise RuntimeError(f"invalid release transition: {release.stage.value} -> {stage.value}")
        if rollout_percent is not None and not 0 <= rollout_percent <= 100:
            raise ValueError("rollout_percent must be between 0 and 100")
        release.stage = stage
        if stage is IOSReleaseStage.PRODUCTION:
            release.rollout_percent = 100
        elif rollout_percent is not None:
            release.rollout_percent = rollout_percent
        release.updated_at = datetime.now(timezone.utc)
        return release
