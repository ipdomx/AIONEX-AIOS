import pytest
from types import SimpleNamespace
from app.services.security_remediation import build_remediation_plan, validate_patch_evidence


def test_plan_never_auto_merges_or_claims_production_change():
    finding = SimpleNamespace(id="f", fingerprint="abc", source="aionex", category="headers", title="Missing CSP", severity="high", cwe="CWE-693", owasp=None, location="nginx.conf", remediation="Add CSP")
    target = SimpleNamespace(id="t", project_id="p", kind="managed_project", target_metadata={"environment": "security_clone"})
    plan = build_remediation_plan(finding, target)
    assert plan["acceptance"]["auto_merge"] is False
    assert plan["acceptance"]["production_modified"] is False
    assert plan["acceptance"]["requires_security_retest"] is True


def test_patch_evidence_rejects_sensitive_paths_and_failed_tests():
    with pytest.raises(ValueError):
        validate_patch_evidence(changed_files=[".env"], tests=[{"name": "unit", "passed": True}], patch_digest="a" * 64)
    with pytest.raises(ValueError):
        validate_patch_evidence(changed_files=["src/app.py"], tests=[{"name": "unit", "passed": False}], patch_digest="a" * 64)


def test_patch_evidence_normalizes_and_hashes_only_successful_regression():
    result = validate_patch_evidence(changed_files=["src/app.py", "src/app.py"], tests=[{"name": "unit", "passed": True}, {"name": "security regression", "passed": True}], patch_digest="b" * 64)
    assert result["regression_passed"] is True
    assert result["changed_files"] == ["src/app.py"]
    assert result["production_modified"] is False
    assert len(result["evidence_digest"]) == 64
