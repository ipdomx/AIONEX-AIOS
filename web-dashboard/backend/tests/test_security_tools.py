import json
from pathlib import Path

import pytest

from app.services import security_tools
from app.services.security_tools import (
    catalog_snapshot,
    redact_tool_output,
    scan_source_tree,
)


def test_catalog_contains_defense_in_depth_engines():
    ids = {item["id"] for item in catalog_snapshot()}
    assert {
        "semgrep",
        "codeql",
        "trivy",
        "osv-scanner",
        "trufflehog",
        "gitleaks",
        "syft",
    } <= ids


def test_builtin_source_scanner_finds_risky_patterns_without_returning_secret(
    tmp_path: Path,
):
    (tmp_path / "app.py").write_text(
        "API_KEY = 'abcdefghijklmnop1234'\nvalue = eval(user_input)\n"
    )
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


@pytest.mark.asyncio
async def test_testssl_is_not_applicable_to_plain_http(monkeypatch):
    monkeypatch.setattr(security_tools.shutil, "which", lambda _name: "/usr/local/bin/testssl.sh")
    result = await security_tools.run_network_tool(
        "testssl",
        origin="http://fixture.invalid:8088",
        hostname="fixture.invalid",
        execution_mode="intrusive_clone",
    )
    assert result["status"] == "not_applicable"
    assert result["reason"] == "https_required"
    assert result["findings"] == []


@pytest.mark.asyncio
async def test_nikto_uses_writable_json_report_and_normalizes_findings(monkeypatch):
    monkeypatch.setattr(security_tools.shutil, "which", lambda _name: "/usr/local/bin/nikto")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"nikto completed", b""

        def kill(self):
            self.returncode = -9

    async def fake_exec(*args, **_kwargs):
        assert "-nocheck" in args
        assert args[args.index("-ask") + 1] == "no"
        assert args[args.index("-maxtime") + 1] == "60s"
        output = args[args.index("-output") + 1]
        with open(output, "w", encoding="utf-8") as handle:
            json.dump(
                [
                    {
                        "vulnerabilities": [
                            {
                                "id": "000029",
                                "method": "GET",
                                "url": "/",
                                "msg": "Cookie sessionid created without the httponly flag.",
                            }
                        ]
                    }
                ],
                handle,
            )
        return FakeProcess()

    monkeypatch.setattr(security_tools.asyncio, "create_subprocess_exec", fake_exec)
    result = await security_tools.run_network_tool(
        "nikto",
        origin="http://fixture.invalid:8088",
        hostname="fixture.invalid",
        execution_mode="intrusive_clone",
    )
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["source"] == "nikto"
    assert finding["severity"] == "medium"
    assert finding["evidence"]["nikto_id"] == "000029"


def test_grype_adapter_uses_current_cli(tmp_path: Path):
    command = security_tools._command_for("grype", tmp_path)
    assert command[:3] == ["grype", f"dir:{tmp_path.resolve()}", "-o"]
    assert "--check-for-app-update=false" not in command


@pytest.mark.asyncio
async def test_source_tool_exit_one_without_findings_is_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(security_tools.shutil, "which", lambda _name: "/usr/bin/trivy")
    monkeypatch.setattr(security_tools, "_command_for", lambda _tool, _source: ["trivy"])

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"fatal scanner error"

        def kill(self):
            self.returncode = -9

    async def fake_exec(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(security_tools.asyncio, "create_subprocess_exec", fake_exec)
    result = await security_tools.run_source_tool("trivy", tmp_path)
    assert result["status"] == "failed"
    assert result["finding_count"] == 0


@pytest.mark.asyncio
async def test_source_tool_finding_exit_one_is_completed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(security_tools.shutil, "which", lambda _name: "/usr/bin/bandit")
    monkeypatch.setattr(security_tools, "_command_for", lambda _tool, _source: ["bandit"])

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            payload = {
                "results": [
                    {
                        "test_id": "B307",
                        "filename": "app.py",
                        "line_number": 4,
                        "issue_text": "Use of possibly insecure function",
                        "issue_severity": "HIGH",
                        "issue_confidence": "HIGH",
                    }
                ]
            }
            return json.dumps(payload).encode(), b""

        def kill(self):
            self.returncode = -9

    async def fake_exec(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(security_tools.asyncio, "create_subprocess_exec", fake_exec)
    result = await security_tools.run_source_tool("bandit", tmp_path)
    assert result["status"] == "completed"
    assert result["finding_count"] == 1


@pytest.mark.asyncio
async def test_osv_empty_source_is_completed_without_false_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(security_tools.shutil, "which", lambda _name: "/usr/local/bin/osv-scanner")
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")

    class FakeProcess:
        returncode = 128

        async def communicate(self):
            return b"", b"No package sources found, --help for usage information.\n"

        def kill(self):
            self.returncode = -9

    async def fake_exec(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(security_tools.asyncio, "create_subprocess_exec", fake_exec)
    result = await security_tools.run_source_tool("osv-scanner", tmp_path)
    assert result["status"] == "completed"
    assert result["exit_code"] == 128
    assert result["finding_count"] == 0
