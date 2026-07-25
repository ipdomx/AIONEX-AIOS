from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class PipelineStep:
    name: str
    command: str
    required: bool = True
    timeout_seconds: int = 900
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    status: PipelineStatus
    exit_code: int
    output: str = ""


@dataclass(frozen=True, slots=True)
class PipelineResult:
    pipeline_id: str
    status: PipelineStatus
    steps: tuple[StepResult, ...]


class PipelinePolicyError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, pipeline_id: str, steps: tuple[PipelineStep, ...],
                 protected_environment: bool = False) -> None:
        if not pipeline_id.strip() or not steps:
            raise ValueError("pipeline_id and at least one step are required")
        self.pipeline_id = pipeline_id
        self.steps = steps
        self.protected_environment = protected_environment

    def run(self, executor: Callable[[PipelineStep], StepResult], *, approved: bool = False) -> PipelineResult:
        if self.protected_environment and not approved:
            raise PipelinePolicyError("owner approval required for protected deployment pipeline")
        results: list[StepResult] = []
        failed = False
        for step in self.steps:
            if failed:
                results.append(StepResult(step.name, PipelineStatus.SKIPPED, -1, "blocked by previous failure"))
                continue
            result = executor(step)
            if result.name != step.name:
                raise ValueError("executor returned result for a different step")
            results.append(result)
            if result.status is PipelineStatus.FAILED and step.required:
                failed = True
        status = PipelineStatus.FAILED if failed else PipelineStatus.SUCCEEDED
        return PipelineResult(self.pipeline_id, status, tuple(results))


class PipelineFactory:
    @staticmethod
    def release_pipeline(*, include_security: bool = True) -> Pipeline:
        steps = [
            PipelineStep("lint", "python -m compileall -q src"),
            PipelineStep("unit-tests", "pytest -q"),
        ]
        if include_security:
            steps.append(PipelineStep("security-gate", "python -m aios.security.cli scan"))
        steps.extend([
            PipelineStep("build", "docker build -t $IMAGE ."),
            PipelineStep("publish", "docker push $IMAGE"),
            PipelineStep("deploy", "python -m aios.infrastructure.cli deploy", timeout_seconds=1800),
        ])
        return Pipeline("release", tuple(steps), protected_environment=True)
