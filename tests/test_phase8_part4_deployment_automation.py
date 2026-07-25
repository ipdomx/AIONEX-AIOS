import pytest

from aios.infrastructure import (
    DeploymentEngine, DeploymentPlan, DeploymentState, DeploymentStrategy, DeploymentTarget,
    InfrastructureValidator, PipelineFactory, PipelinePolicyError, PipelineStatus, StepResult,
    ReleaseArtifact, ReleaseManager, ReleaseStatus, RollbackManager, RollbackRequest, RollbackStatus,
)


def test_blue_green_plan_generates_safe_sequence():
    engine = DeploymentEngine()
    plan = DeploymentPlan(
        release_id="rel-1", service="api", version="2.3.0", image="registry/api:2.3.0",
        target=DeploymentTarget("production", cluster="main", namespace="aios"),
        strategy=DeploymentStrategy.BLUE_GREEN,
    )
    engine.plan(plan)
    commands = engine.commands(plan)
    assert [command["action"] for command in commands] == ["deploy_slot", "health_check", "switch_traffic"]
    assert engine.history("rel-1")[0].state is DeploymentState.PLANNED


def test_canary_percent_is_validated():
    plan = DeploymentPlan(
        release_id="rel-2", service="api", version="2.3.0", image="registry/api:2.3.0",
        target=DeploymentTarget("production"), strategy=DeploymentStrategy.CANARY, canary_percent=0,
    )
    with pytest.raises(ValueError):
        plan.validate()


def test_protected_pipeline_requires_approval_and_stops_after_failure():
    pipeline = PipelineFactory.release_pipeline(include_security=False)
    with pytest.raises(PipelinePolicyError):
        pipeline.run(lambda step: StepResult(step.name, PipelineStatus.SUCCEEDED, 0))

    def executor(step):
        if step.name == "unit-tests":
            return StepResult(step.name, PipelineStatus.FAILED, 1, "failure")
        return StepResult(step.name, PipelineStatus.SUCCEEDED, 0)

    result = pipeline.run(executor, approved=True)
    assert result.status is PipelineStatus.FAILED
    assert result.steps[-1].status is PipelineStatus.SKIPPED


def test_release_requires_artifact_and_owner_approval():
    manager = ReleaseManager()
    manager.create("rel-3", "2.3.0")
    with pytest.raises(RuntimeError):
        manager.approve("rel-3", "owner")
    manager.add_artifact("rel-3", ReleaseArtifact.from_bytes("api", "2.3.0", b"image"))
    manager.approve("rel-3", "owner")
    record = manager.publish("rel-3")
    assert record.status is ReleaseStatus.PUBLISHED
    assert "release_id" in record.manifest()


def test_rollback_requires_owner_approval():
    manager = RollbackManager()
    manager.request(RollbackRequest("rel-4", "2.3.0", "2.2.9", "health regression", "system"))
    with pytest.raises(PermissionError):
        manager.execute("rel-4", lambda request: True)
    manager.approve("rel-4", "owner")
    result = manager.execute("rel-4", lambda request: request.target_version == "2.2.9")
    assert result.status is RollbackStatus.SUCCEEDED


def test_infrastructure_validation_blocks_invalid_release():
    validator = InfrastructureValidator.default()
    invalid = validator.validate({"image": "api:latest", "replicas": 0})
    assert not invalid.valid
    assert {issue.code for issue in invalid.issues} >= {"environment.missing", "replicas.invalid", "image.latest"}
    valid = validator.validate({"environment": "production", "image": "api:2.3.0", "replicas": 2})
    assert valid.valid
