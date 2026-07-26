from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ExerciseResult(str, Enum):
    PLANNED = "planned"
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class ExerciseScenario:
    exercise_id: str
    plan_id: str
    title: str
    scenario_type: str
    participants: list[str]
    objectives: list[str]
    result: ExerciseResult = ExerciseResult.PLANNED
    findings: list[str] = field(default_factory=list)
    conducted_at: datetime | None = None


class ExerciseProgram:
    def __init__(self) -> None:
        self._exercises: dict[str, ExerciseScenario] = {}

    def schedule(self, exercise: ExerciseScenario) -> ExerciseScenario:
        if not exercise.exercise_id.strip() or not exercise.plan_id.strip() or not exercise.title.strip():
            raise ValueError("exercise_id, plan_id and title are required")
        if not exercise.participants or not exercise.objectives:
            raise ValueError("participants and objectives cannot be empty")
        if exercise.exercise_id in self._exercises:
            raise ValueError(f"duplicate exercise: {exercise.exercise_id}")
        self._exercises[exercise.exercise_id] = exercise
        return exercise

    def record_result(
        self,
        exercise_id: str,
        result: ExerciseResult,
        findings: list[str] | None = None,
    ) -> ExerciseScenario:
        if result is ExerciseResult.PLANNED:
            raise ValueError("result must represent a completed exercise")
        exercise = self.get(exercise_id)
        exercise.result = result
        exercise.findings = list(findings or [])
        exercise.conducted_at = datetime.now(timezone.utc)
        return exercise

    def get(self, exercise_id: str) -> ExerciseScenario:
        try:
            return self._exercises[exercise_id]
        except KeyError as exc:
            raise LookupError(f"exercise not found: {exercise_id}") from exc

    def readiness_score(self, plan_id: str) -> float:
        exercises = [item for item in self._exercises.values() if item.plan_id == plan_id]
        completed = [item for item in exercises if item.result is not ExerciseResult.PLANNED]
        if not completed:
            return 0.0
        values = {
            ExerciseResult.PASSED: 1.0,
            ExerciseResult.PARTIAL: 0.5,
            ExerciseResult.FAILED: 0.0,
        }
        return sum(values[item.result] for item in completed) / len(completed)
