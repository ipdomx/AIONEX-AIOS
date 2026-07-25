from aios.government import GovernanceCase, GovernmentRuntime
from aios.workforce_health import OperationalHealthInstitute, WorkerObservation
from aios.kernel import AIOSKernel


def test_government_requires_evidence_and_owner_authority():
    government = GovernmentRuntime("owner")
    missing = government.review(GovernanceCase("c1", "Deploy", "deploy", "engineering"))
    assert missing["verdict"] == "returned_for_revision"

    case = GovernanceCase(
        "c2", "Deploy", "deploy", "engineering",
        evidence=("tests_passed", "security_review"),
        requires_owner_approval=True,
        metadata={"rollback_plan": "release-previous"},
    )
    reviewed = government.review(case)
    assert reviewed["verdict"] == "approved"
    assert reviewed["owner_approval_required"] is True
    assert reviewed["owner_approved"] is False

    try:
        government.owner.decide("c2", "manager", True)
        assert False, "non-owner approval must be blocked"
    except PermissionError:
        pass

    government.owner.decide("c2", "owner", True)
    assert government.review(case)["owner_approved"] is True


def test_operational_health_tracks_worker_and_advisor():
    institute = OperationalHealthInstitute()
    institute.assign_advisor("worker-1", "advisor-7")
    report = institute.observe(WorkerObservation(
        worker_id="worker-1", project_id="p1",
        quality=96, reliability=94, collaboration=91,
        policy_compliance=98, learning=93,
    ))
    assert institute.advisor_for("worker-1") == "advisor-7"
    assert report.trust >= 90
    assert report.recommendation == "eligible_for_promotion_review"


def test_unreliable_worker_is_restricted_not_silently_accepted():
    institute = OperationalHealthInstitute()
    report = institute.observe(WorkerObservation(
        worker_id="worker-2", project_id="p1",
        quality=58, reliability=50, collaboration=60,
        policy_compliance=55, learning=70,
        incidents=("ignored_evidence", "repeated_failure", "policy_violation"),
    ))
    assert "supervised_execution_only" in report.restrictions
    assert report.recommendation in {
        "academy_retraining_and_increased_review",
        "temporary_suspension_and_recertification",
    }


def test_kernel_exposes_new_phase():
    kernel = AIOSKernel()
    status = kernel.status()
    assert status["version"] == "2.3.0-beta.5"
    assert status["government_runtime"]
    assert status["workforce_health"]
