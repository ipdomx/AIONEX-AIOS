from aios.release_governance import (
    ApprovalDecision,
    ApprovalRecord,
    ArtifactManifest,
    EnvironmentStage,
    ReleaseCandidate,
    ReleaseGate,
    ReleaseGovernancePlatform,
    ReleaseState,
    VerificationEvidence,
)


def test_release_governance_end_to_end() -> None:
    platform = ReleaseGovernancePlatform.build_default()
    release = ReleaseCandidate(
        release_id="rel-18",
        version="3.3.0-beta.1",
        commit_sha="abc123",
    )
    platform.releases.add(release)
    release.transition(ReleaseState.CANDIDATE)

    platform.gates.register(
        ReleaseGate(
            gate_id="tests",
            description="Automated tests",
            check=lambda release_id: (release_id == "rel-18", "tests passed"),
        )
    )
    platform.gates.evaluate(release.release_id)

    platform.artifacts.register(
        ArtifactManifest(
            artifact_id="artifact-18",
            release_id=release.release_id,
            name="aios-release.tar.gz",
            digest="sha256:example",
            size_bytes=1024,
        )
    )

    for evidence_type in {"tests", "security", "compatibility"}:
        platform.verification.add(
            VerificationEvidence(
                evidence_id=f"evidence-{evidence_type}",
                release_id=release.release_id,
                evidence_type=evidence_type,
                passed=True,
                source="pipeline",
                summary=f"{evidence_type} passed",
            )
        )

    for role in {"chief_engineer", "security", "owner"}:
        platform.approvals.submit(
            ApprovalRecord(
                release_id=release.release_id,
                reviewer_id=f"reviewer-{role}",
                role=role,
                decision=ApprovalDecision.APPROVE,
            )
        )

    assert platform.readiness(
        release.release_id,
        {"tests", "security", "compatibility"},
    )["ready"] is True

    release.transition(ReleaseState.APPROVED)
    platform.promotion.promote(release, EnvironmentStage.STAGING, "owner-1")
    platform.promotion.promote(release, EnvironmentStage.PRODUCTION, "owner-1")

    assert release.state is ReleaseState.PROMOTED
    assert platform.promotion.current_stage(release.release_id) is EnvironmentStage.PRODUCTION
    assert platform.validate()["ready"] is True


def test_release_rejection_and_invalid_promotion() -> None:
    platform = ReleaseGovernancePlatform.build_default()
    release = platform.releases.add(
        ReleaseCandidate("rel-rejected", "3.3.0-beta.1", "def456")
    )
    release.transition(ReleaseState.CANDIDATE)
    platform.approvals.submit(
        ApprovalRecord(
            release_id=release.release_id,
            reviewer_id="security-1",
            role="security",
            decision=ApprovalDecision.REJECT,
            reason="security gate failed",
        )
    )

    assert platform.approvals.rejected(release.release_id) is True

    try:
        platform.promotion.promote(release, EnvironmentStage.PRODUCTION, "owner-1")
    except ValueError:
        pass
    else:
        raise AssertionError("production promotion should fail")
