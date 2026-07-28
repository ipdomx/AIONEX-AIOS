from datetime import datetime, timedelta, timezone

from aios.stable_release.deployment_controller import (
    DeploymentStage,
    StableDeployment,
    StableDeploymentController,
)
from aios.stable_release.release_gate import (
    StableGateName,
    StableGateResult,
    StableReleaseGate,
)
from aios.stable_release.release_manifest import (
    StableReleaseManifest,
    StableReleaseRegistry,
    StableReleaseState,
)
from aios.stable_release.support_policy import StableSupportRegistry, SupportTier


def test_stable_release_lifecycle() -> None:
    registry = StableReleaseRegistry()
    registry.register(
        StableReleaseManifest(
            release_id="stable-1",
            version="1.0.0",
            owner_id="owner-1",
            commit_sha="abc123",
        )
    )

    registry.start_validation("stable-1", "owner-1")
    registry.approve("stable-1", "owner-1")
    release = registry.mark_released("stable-1", "owner-1")

    assert release.state is StableReleaseState.RELEASED
    assert release.released_at is not None


def test_release_gate_requires_all_checks() -> None:
    gate = StableReleaseGate()
    results = [StableGateResult(name=name, passed=True) for name in StableGateName]
    decision = gate.evaluate(results)

    assert decision.approved is True
    assert decision.missing == ()
    assert decision.failed == ()


def test_failed_gate_blocks_release() -> None:
    gate = StableReleaseGate()
    results = [
        StableGateResult(name=name, passed=name is not StableGateName.SECURITY)
        for name in StableGateName
    ]
    decision = gate.evaluate(results)

    assert decision.approved is False
    assert decision.failed == (StableGateName.SECURITY,)


def test_staged_deployment_and_rollback() -> None:
    controller = StableDeploymentController()
    controller.create(
        StableDeployment(
            deployment_id="deploy-1",
            release_id="stable-1",
            owner_id="owner-1",
        )
    )

    controller.promote_to_canary("deploy-1", "owner-1")
    deployment = controller.promote_to_production("deploy-1", "owner-1")
    assert deployment.stage is DeploymentStage.PRODUCTION

    rolled_back = controller.rollback("deploy-1", "owner-1")
    assert rolled_back.stage is DeploymentStage.ROLLED_BACK


def test_support_policy_and_owner_scope() -> None:
    registry = StableSupportRegistry()
    policy = registry.create("1.0.0", "owner-1", SupportTier.LONG_TERM)

    assert registry.is_supported("1.0.0", "owner-1", policy.released_at + timedelta(days=1000))
    assert not registry.is_supported("1.0.0", "owner-1", policy.released_at + timedelta(days=1200))

    try:
        registry.get("1.0.0", "owner-2")
    except PermissionError:
        pass
    else:
        raise AssertionError("support policies must be owner-isolated")
