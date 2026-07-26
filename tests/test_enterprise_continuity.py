from aios.enterprise_continuity import (
    BusinessImpactAnalyzer,
    ContinuityDecision,
    ContinuityDirective,
    ContinuityPlan,
    ContinuityPlanState,
    EnterpriseContinuityPlatform,
    ExerciseResult,
    ExerciseScenario,
    RecoveryAction,
    RecoveryStatus,
)


def test_enterprise_continuity_end_to_end() -> None:
    platform = EnterpriseContinuityPlatform.build_default()
    plan = ContinuityPlan(
        plan_id="plan-1",
        organization_id="org-1",
        title="Primary service continuity",
        critical_services=["api", "database"],
        recovery_time_objective_minutes=60,
        recovery_point_objective_minutes=15,
        owner_id="owner-1",
    )
    platform.plans.register(plan)
    plan.transition(ContinuityPlanState.APPROVED)

    assessment = platform.impact.assess(
        assessment_id="assessment-1",
        organization_id="org-1",
        service_id="api",
        estimated_users_affected=15000,
        estimated_downtime_minutes=300,
        financial_exposure=250000,
        regulatory_exposure=True,
    )
    decision = platform.command.recommend(assessment)
    assert decision in {ContinuityDecision.ACTIVATE, ContinuityDecision.ESCALATE}

    platform.command.issue(
        ContinuityDirective(
            directive_id="directive-1",
            plan_id=plan.plan_id,
            decision=decision,
            issued_by="owner-1",
            reason="critical service disruption",
            owner_approved=True,
        ),
        plan,
    )
    assert plan.state is ContinuityPlanState.ACTIVE

    first = platform.recovery.add(
        RecoveryAction(
            action_id="action-1",
            plan_id=plan.plan_id,
            service_id="database",
            description="Restore database",
            owner_id="engineer-1",
            sequence=1,
        )
    )
    second = platform.recovery.add(
        RecoveryAction(
            action_id="action-2",
            plan_id=plan.plan_id,
            service_id="api",
            description="Restart API",
            owner_id="engineer-2",
            sequence=2,
        )
    )
    platform.recovery.start(first.action_id)
    platform.recovery.complete(first.action_id, {"checkpoint": "db-restored"})
    platform.recovery.start(second.action_id)
    platform.recovery.complete(second.action_id, {"checkpoint": "api-online"})
    assert first.status is RecoveryStatus.COMPLETED
    assert second.status is RecoveryStatus.COMPLETED
    assert platform.recovery.progress(plan.plan_id) == 1.0

    exercise = platform.exercises.schedule(
        ExerciseScenario(
            exercise_id="exercise-1",
            plan_id=plan.plan_id,
            title="Regional outage simulation",
            scenario_type="tabletop",
            participants=["owner-1", "engineer-1"],
            objectives=["validate escalation", "validate recovery order"],
        )
    )
    platform.exercises.record_result(exercise.exercise_id, ExerciseResult.PASSED)
    assert platform.exercises.readiness_score(plan.plan_id) == 1.0
    assert platform.validate()["ready"] is True


def test_owner_approval_and_recovery_order_are_enforced() -> None:
    platform = EnterpriseContinuityPlatform.build_default()
    plan = ContinuityPlan(
        plan_id="plan-2",
        organization_id="org-2",
        title="Secondary continuity",
        critical_services=["worker"],
        recovery_time_objective_minutes=120,
        recovery_point_objective_minutes=30,
        owner_id="owner-2",
    )
    platform.plans.register(plan)
    plan.transition(ContinuityPlanState.APPROVED)

    try:
        platform.command.issue(
            ContinuityDirective(
                directive_id="directive-2",
                plan_id=plan.plan_id,
                decision=ContinuityDecision.ACTIVATE,
                issued_by="manager-1",
                reason="test activation",
                owner_approved=False,
            ),
            plan,
        )
        assert False, "owner approval should be required"
    except PermissionError:
        pass

    platform.recovery.add(
        RecoveryAction(
            action_id="action-3",
            plan_id=plan.plan_id,
            service_id="storage",
            description="Restore storage",
            owner_id="engineer-1",
            sequence=1,
        )
    )
    platform.recovery.add(
        RecoveryAction(
            action_id="action-4",
            plan_id=plan.plan_id,
            service_id="worker",
            description="Restart worker",
            owner_id="engineer-2",
            sequence=2,
        )
    )
    try:
        platform.recovery.start("action-4")
        assert False, "recovery order should be enforced"
    except RuntimeError:
        pass
