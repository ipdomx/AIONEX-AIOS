from pathlib import Path
from app.services.security_tools import catalog_snapshot, redact_tool_output, scan_source_tree


def test_catalog_contains_defense_in_depth_engines():
    ids = {item["id"] for item in catalog_snapshot()}
    assert {"semgrep", "codeql", "trivy", "osv-scanner", "trufflehog", "gitleaks", "syft"} <= ids


def test_builtin_source_scanner_finds_risky_patterns_without_returning_secret(tmp_path: Path):
    (tmp_path / "app.py").write_text("API_KEY = 'abcdefghijklmnop1234'\nvalue = eval(user_input)\n")
    (tmp_path / "requirements.txt").write_text("fastapi==1.0\n")
    result = scan_source_tree(tmp_path)
    categories = {item["category"] for item in result["findings"]}
    assert "secret-exposure" in categories
    assert "risky-code-pattern" in categories
    assert "requirements.txt" in result["manifests"]
    assert all("abcdefghijklmnop1234" not in str(item) for item in result["findings"])


def test_external_output_redaction():
    text = "api_key=supersecretvalue token: anothersecretvalue"
    redacted = redact_tool_output(text)
    assert "supersecretvalue" not in redacted
    assert "anothersecretvalue" not in redacted
    assert redacted.count("[REDACTED]") == 2
