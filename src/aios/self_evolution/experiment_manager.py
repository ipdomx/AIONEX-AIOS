from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ExperimentState(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass(slots=True)
class Experiment:
    experiment_id: str
    owner_id: str
    proposal_id: str
    control_version: str
    candidate_version: str
    success_metric: str
    rollback_version: str
    state: ExperimentState = ExperimentState.PLANNED
    observations: list[float] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExperimentManager:
    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}

    def create(self, experiment: Experiment) -> Experiment:
        if experiment.experiment_id in self._experiments:
            raise ValueError(f"duplicate experiment: {experiment.experiment_id}")
        self._experiments[experiment.experiment_id] = experiment
        return experiment

    def start(self, experiment_id: str, owner_id: str) -> Experiment:
        experiment = self._require_owner(experiment_id, owner_id)
        if experiment.state is not ExperimentState.PLANNED:
            raise RuntimeError("experiment cannot be started")
        experiment.state = ExperimentState.RUNNING
        experiment.started_at = datetime.now(timezone.utc)
        return experiment

    def observe(self, experiment_id: str, owner_id: str, value: float) -> Experiment:
        experiment = self._require_owner(experiment_id, owner_id)
        if experiment.state is not ExperimentState.RUNNING:
            raise RuntimeError("experiment is not running")
        experiment.observations.append(value)
        return experiment

    def finish(self, experiment_id: str, owner_id: str, *, succeeded: bool) -> Experiment:
        experiment = self._require_owner(experiment_id, owner_id)
        if experiment.state is not ExperimentState.RUNNING:
            raise RuntimeError("experiment is not running")
        experiment.state = ExperimentState.SUCCEEDED if succeeded else ExperimentState.FAILED
        experiment.completed_at = datetime.now(timezone.utc)
        return experiment

    def abort(self, experiment_id: str, owner_id: str) -> Experiment:
        experiment = self._require_owner(experiment_id, owner_id)
        if experiment.state not in {ExperimentState.PLANNED, ExperimentState.RUNNING}:
            raise RuntimeError("experiment cannot be aborted")
        experiment.state = ExperimentState.ABORTED
        experiment.completed_at = datetime.now(timezone.utc)
        return experiment

    def _require_owner(self, experiment_id: str, owner_id: str) -> Experiment:
        experiment = self._experiments[experiment_id]
        if experiment.owner_id != owner_id:
            raise PermissionError("experiment is not owned by this owner")
        return experiment
