from pathlib import Path

import pytest

from aios.security_platform import SecurityLedger, SecurityPlatform, Severity


def test_assessment_requires_authorization(tmp_path: Path):
    with pytest.raises(PermissionError):
        SecurityPlatform().assess("p", tmp_path, authorization=False)


def test_detects_secrets_code_and_container_risks(tmp_path: Path):
    (tmp_path / "app.py").write_text('API_KEY="abcdefgh12345678"\neval(user_input)\n', encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:latest\nCOPY . /app\nCMD python app.py\n", encoding="utf-8")
    assessment = SecurityPlatform().assess("p", tmp_path, authorization=True)
    titles = {finding.title for finding in assessment.findings}
    assert "Credential assignment" in titles
    assert "Dynamic code execution" in titles
    assert "Container may run as root" in titles
    assert "Unpinned container base image" in titles
    assert assessment.risk.grade in {"D", "F"}
    assert assessment.risk.blockers


def test_dependency_analysis_and_reproducibility(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests>=2\nflask\n", encoding="utf-8")
    assessment = SecurityPlatform().assess("p", tmp_path, authorization=True)
    assert sum(f.title == "Unpinned dependency" for f in assessment.findings) == 2
    assert any(f.title == "Dependency lock file missing" for f in assessment.findings)


def test_hash_chained_ledger_verifies(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("print('safe')\n", encoding="utf-8")
    ledger_path = tmp_path / "security.jsonl"
    platform = SecurityPlatform(ledger_path)
    platform.assess("p", root, authorization=True)
    platform.assess("p", root, authorization=True)
    assert SecurityLedger(ledger_path).verify()
    text = ledger_path.read_text(encoding="utf-8")
    ledger_path.write_text(text.replace('"project": "p"', '"project": "x"', 1), encoding="utf-8")
    assert not SecurityLedger(ledger_path).verify()


def test_findings_include_fix_and_verification_paths(tmp_path: Path):
    (tmp_path / "client.py").write_text("requests.get(url, verify=False)\n", encoding="utf-8")
    assessment = SecurityPlatform().assess("p", tmp_path, authorization=True)
    finding = next(f for f in assessment.findings if f.severity is Severity.CRITICAL)
    assert finding.remediation
    assert finding.verification
    assert assessment.remediation_plan
    assert assessment.verification_plan
