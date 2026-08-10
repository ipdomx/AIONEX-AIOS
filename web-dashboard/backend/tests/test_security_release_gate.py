from app.services.security_release_gate import evaluate_release_gate

POLICY = {
    "release_gate": {
        "block_confirmed_critical": True,
        "block_confirmed_high": True,
        "max_confirmed_medium": 0,
        "require_tls": True,
        "require_security_headers": True,
        "require_backup_restore_evidence": True,
    }
}
ENGINE = {"engines": [{"scanner": "aionex-web-v1", "status": "completed"}]}


def test_confirmed_high_blocks_release():
    result = evaluate_release_gate(
        scan_status="completed",
        scan_summary=ENGINE,
        findings=[{"state": "confirmed", "severity": "high"}],
        policy=POLICY,
        recent_backup=True,
        recent_dr_restore=True,
    )
    assert result["decision"] == "blocked"
    assert any(item["code"] == "CONFIRMED_HIGH_FINDINGS" for item in result["blockers"])


def test_unverified_high_requires_owner_review_instead_of_fake_pass():
    result = evaluate_release_gate(
        scan_status="completed",
        scan_summary=ENGINE,
        findings=[{"state": "observed", "severity": "high"}],
        policy=POLICY,
        recent_backup=True,
        recent_dr_restore=True,
    )
    assert result["decision"] == "review_required"
    assert result["review"]


def test_missing_backup_or_restore_blocks_even_with_clean_scan():
    result = evaluate_release_gate(
        scan_status="completed",
        scan_summary=ENGINE,
        findings=[],
        policy=POLICY,
        recent_backup=False,
        recent_dr_restore=False,
    )
    assert result["decision"] == "blocked"
    codes = {item["code"] for item in result["blockers"]}
    assert {
        "RECENT_BACKUP_EVIDENCE_MISSING",
        "RECENT_RESTORE_EVIDENCE_MISSING",
    } <= codes


def test_clean_verified_scan_with_assurance_passes():
    result = evaluate_release_gate(
        scan_status="completed",
        scan_summary=ENGINE,
        findings=[
            {"state": "false_positive", "severity": "high"},
            {"state": "resolved", "severity": "critical"},
        ],
        policy=POLICY,
        recent_backup=True,
        recent_dr_restore=True,
    )
    assert result["decision"] == "passed"
    assert result["blockers"] == []
    assert result["review"] == []
