from app.services.adaptive_intelligence import assess_experience_trust


def test_user_statement_never_promotes_without_verification_and_evidence():
    result = assess_experience_trust(
        source="user",
        evidence_count=0,
        direct_evidence=False,
        verified=False,
    )
    assert result.promotable is False
    assert result.score < 0.8
    assert "quarantine" in result.reasons


def test_repeatable_verified_security_evidence_can_promote():
    result = assess_experience_trust(
        source="security_scan",
        evidence_count=2,
        direct_evidence=True,
        successful_repetitions=2,
        verified=True,
    )
    assert result.promotable is True
    assert result.score >= 0.8


def test_contradictions_drive_candidate_back_below_promotion_threshold():
    result = assess_experience_trust(
        source="security_scan",
        evidence_count=3,
        direct_evidence=True,
        successful_repetitions=2,
        contradictions=3,
        verified=True,
    )
    assert result.promotable is False
    assert result.score < 0.8
