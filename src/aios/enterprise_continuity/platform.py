from __future__ import annotations

from dataclasses import dataclass

from .command import ContinuityCommandCenter
from .continuity import ContinuityRegistry
from .exercises import ExerciseProgram
from .impact import BusinessImpactAnalyzer
from .recovery import RecoveryCoordinator


@dataclass
class EnterpriseContinuityPlatform:
    plans: ContinuityRegistry
    impact: BusinessImpactAnalyzer
    command: ContinuityCommandCenter
    recovery: RecoveryCoordinator
    exercises: ExerciseProgram

    @classmethod
    def build_default(cls) -> "EnterpriseContinuityPlatform":
        return cls(
            plans=ContinuityRegistry(),
            impact=BusinessImpactAnalyzer(),
            command=ContinuityCommandCenter(),
            recovery=RecoveryCoordinator(),
            exercises=ExerciseProgram(),
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "continuity_registry": self.plans is not None,
            "business_impact_analyzer": self.impact is not None,
            "continuity_command_center": self.command is not None,
            "recovery_coordinator": self.recovery is not None,
            "exercise_program": self.exercises is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
