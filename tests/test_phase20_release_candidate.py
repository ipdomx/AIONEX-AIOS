from aios.release_candidate.gates import GateStatus
from aios.release_candidate.models import CandidateState, ReleaseCandidate
from aios.release_candidate.promotion import PromotionStage, ReleasePromotionService
from aios.release_candidate.validation import ReleaseCandidateValidator, ValidationInput


def test_release_candidate_happy_path() -> None:
    candidate = ReleaseCandidate(
        candidate_id="rc-1",
        version="1.0.0-rc.1",
        owner_id="owner-1",
        commit_sha="abc123",
    )
    candidate.start_validation()

    report = ReleaseCandidateValidator().validate(
        candidate,
        ValidationInput(
            unit_tests_passed=True,
            integration_tests_passed=True,
            security_scan_passed=True,
            migration_check_passed=True,
            rollback_verified=True,
            documentation_complete=True,
        ),
    )

    assert report.ready is True
    assert candidate.state is CandidateState.APPROVED

    service = ReleasePromotionService()
    service.promote(
        candidate,
        stage=PromotionStage.STAGING,
        owner_id="owner-1",
        approved_by="owner-1",
    )
    service.promote(
        candidate,
        stage=PromotionStage.CANARY,
        owner_id="owner-1",
        approved_by="owner-1",
    )
    service.promote(
        candidate,
        stage=PromotionStage.PRODUCTION,
        owner_id="owner-1",
        approved_by="owner-1",
    )

    assert candidate.state is CandidateState.RELEASED
    assert len(service.history("rc-1")) == 3


def test_release_candidate_blocks_on_failed_gate() -> None:
    candidate = ReleaseCandidate(
        candidate_id="rc-2",
        version="1.0.0-rc.2",
        owner_id="owner-1",
        commit_sha="def456",
    )
    candidate.start_validation()

    report = ReleaseCandidateValidator().validate(
        candidate,
        ValidationInput(
            unit_tests_passed=True,
            integration_tests_passed=False,
            security_scan_passed=True,
            migration_check_passed=True,
            rollback_verified=True,
            documentation_complete=True,
        ),
    )

    assert report.ready is False
    assert report.failures[0].status is GateStatus.FAILED
    assert candidate.state is CandidateState.BLOCKED


def test_release_promotion_enforces_owner_scope() -> None:
    candidate = ReleaseCandidate(
        candidate_id="rc-3",
        version="1.0.0-rc.3",
        owner_id="owner-1",
        commit_sha="ghi789",
    )
    candidate.start_validation()
    ReleaseCandidateValidator().validate(
        candidate,
        ValidationInput(True, True, True, True, True, True),
    )

    service = ReleasePromotionService()
    try:
        service.promote(
            candidate,
            stage=PromotionStage.STAGING,
            owner_id="owner-2",
            approved_by="owner-2",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("cross-owner promotion must be rejected")
