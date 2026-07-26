from aios.enterprise_launch_operations import (
    AdoptionMetric,
    EnterpriseLaunchOperationsPlatform,
    LaunchPlan,
    LaunchStage,
    LaunchStatus,
    RolloutPolicy,
    RolloutWave,
    SupportIncident,
    SupportPriority,
)


def test_enterprise_launch_operations_end_to_end() -> None:
    platform = EnterpriseLaunchOperationsPlatform.build_default()
    plan = LaunchPlan(
        launch_id="launch-1",
        version="3.4.0-beta.1",
        owner_id="owner-1",
        stage=LaunchStage.PILOT,
        required_gates={"security", "performance", "owner_approval"},
    )
    platform.launches.create(plan)
    for gate in plan.required_gates:
        platform.launches.pass_gate(plan.launch_id, gate)
    assert plan.status is LaunchStatus.READY
    platform.launches.activate(plan.launch_id)
    assert plan.status is LaunchStatus.ACTIVE

    platform.rollout.add(
        RolloutWave(
            wave_id="wave-1",
            target="pilot-organizations",
            percentage=10.0,
            policy=RolloutPolicy.ORGANIZATION,
        )
    )
    platform.rollout.approve("wave-1")
    platform.rollout.complete("wave-1")
    assert platform.rollout.progress() == 1.0

    platform.adoption.record(
        AdoptionMetric(name="active_users", value=120.0, organization_id="org-1")
    )
    platform.adoption.record(
        AdoptionMetric(name="active_users", value=180.0, organization_id="org-2")
    )
    assert platform.adoption.average("active_users") == 150.0

    incident = SupportIncident(
        incident_id="incident-1",
        title="Launch latency regression",
        description="Pilot users report increased latency.",
        priority=SupportPriority.HIGH,
    )
    platform.support.open(incident)
    assert platform.support.unresolved()[0].incident_id == "incident-1"
    platform.support.resolve("incident-1")
    assert platform.support.unresolved() == []
    assert platform.validate()["ready"] is True


def test_launch_pause_resume_and_rollback() -> None:
    platform = EnterpriseLaunchOperationsPlatform.build_default()
    plan = LaunchPlan(
        launch_id="launch-2",
        version="3.4.0-beta.1",
        owner_id="owner-1",
        required_gates=set(),
        status=LaunchStatus.READY,
    )
    platform.launches.create(plan)
    platform.launches.activate(plan.launch_id)
    platform.launches.pause(plan.launch_id)
    assert plan.status is LaunchStatus.PAUSED
    platform.launches.activate(plan.launch_id)
    platform.launches.rollback(plan.launch_id)
    assert plan.status is LaunchStatus.ROLLED_BACK
