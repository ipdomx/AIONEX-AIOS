from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RolloutPolicy(str, Enum):
    MANUAL = "manual"
    PERCENTAGE = "percentage"
    ORGANIZATION = "organization"
    REGION = "region"


@dataclass
class RolloutWave:
    wave_id: str
    target: str
    percentage: float = 100.0
    policy: RolloutPolicy = RolloutPolicy.MANUAL
    approved: bool = False
    completed: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


class RolloutCoordinator:
    def __init__(self) -> None:
        self._waves: dict[str, RolloutWave] = {}

    def add(self, wave: RolloutWave) -> RolloutWave:
        if not wave.wave_id.strip() or not wave.target.strip():
            raise ValueError("wave_id and target are required")
        if not 0 < wave.percentage <= 100:
            raise ValueError("percentage must be greater than 0 and at most 100")
        if wave.wave_id in self._waves:
            raise ValueError(f"duplicate wave_id: {wave.wave_id}")
        self._waves[wave.wave_id] = wave
        return wave

    def approve(self, wave_id: str) -> RolloutWave:
        wave = self.get(wave_id)
        wave.approved = True
        return wave

    def complete(self, wave_id: str) -> RolloutWave:
        wave = self.get(wave_id)
        if not wave.approved:
            raise ValueError("rollout wave must be approved")
        wave.completed = True
        return wave

    def get(self, wave_id: str) -> RolloutWave:
        try:
            return self._waves[wave_id]
        except KeyError as exc:
            raise LookupError(f"rollout wave not found: {wave_id}") from exc

    def progress(self) -> float:
        if not self._waves:
            return 0.0
        complete = sum(1 for wave in self._waves.values() if wave.completed)
        return complete / len(self._waves)
