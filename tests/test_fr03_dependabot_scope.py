from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
VULNERABLE = ROOT / "web-dashboard/backend/tests/security_acceptance_lab/fixtures/vulnerable/requirements.txt"
FIXED = ROOT / "web-dashboard/backend/tests/security_acceptance_lab/fixtures/fixed/requirements.txt"


def test_dependabot_excludes_only_intentionally_vulnerable_fixture_path():
    assert 'directory: "/web-dashboard/backend"' in CONFIG
    assert 'exclude-paths:' in CONFIG
    assert '"tests/security_acceptance_lab/fixtures/vulnerable/**"' in CONFIG
    assert 'fixtures/fixed' not in CONFIG


def test_negative_control_fixture_remains_explicit_and_isolated():
    vulnerable = VULNERABLE.read_text(encoding="utf-8")
    fixed = FIXED.read_text(encoding="utf-8")
    assert "requests==2.19.0" in vulnerable
    assert "flask==0.12.2" in vulnerable
    assert vulnerable != fixed


def test_exclusion_does_not_disable_backend_dependency_updates():
    assert 'package-ecosystem: pip' in CONFIG
    assert 'open-pull-requests-limit: 10' in CONFIG
    assert 'python-runtime:' in CONFIG
    assert 'update-types: ["minor", "patch"]' in CONFIG
