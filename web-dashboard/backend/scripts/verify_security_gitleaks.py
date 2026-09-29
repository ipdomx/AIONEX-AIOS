"""Offline Gitleaks acceptance against fresh synthetic files only.

Run in an isolated scanner image with no network. The production application
argument builder and result normalizer are exercised without invoking a worker.
No real key, source project, database, provider or external target is accessed.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import tempfile
import zipfile
from pathlib import Path


def invoke(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=45, check=False)


def main() -> None:
    from app.services.security_tools import _command_for, _normalize_source_findings

    executable = Path("/usr/local/bin/gitleaks")
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == "7c8b599cead7b3c8cd4a55aac3a3c1238814f59d08a88b4078b1a18afa100f5b"
    version = invoke([str(executable), "version"])
    assert version.returncode == 0 and version.stdout.strip() == "8.30.1+aios.1"
    with tempfile.TemporaryDirectory(prefix="aios-gitleaks-synthetic-") as folder:
        root = Path(folder)
        bad, good, archive = (root / name for name in ["bad", "good", "archive"])
        for path in [bad, good, archive]:
            path.mkdir()
        # This value is generated only for a local test and is not valid for any service.
        marker = secrets.token_hex(32)
        payload = 'api_key = "' + marker + '"\n'
        (bad / "fixture.py").write_text(payload)
        (good / "fixture.py").write_text('message = "local safe control"\n')
        outcomes = []
        for path, want in [(bad, True), (good, False)]:
            args = _command_for("gitleaks", path) + ["--no-banner", "--log-level", "error", "--redact"]
            result = invoke(args)
            assert result.returncode == (1 if want else 0)
            parsed = json.loads(result.stdout)
            normalized = _normalize_source_findings("gitleaks", parsed, "")
            assert bool(parsed) is want and bool(normalized) is want
            assert marker not in result.stdout and marker not in result.stderr
            if want:
                assert all(row["state"] == "observed" and row["severity"] == "high" for row in normalized)
                assert all(row["File"].endswith("fixture.py") for row in parsed)
            outcomes.append({"synthetic_unsafe": want, "findings": len(parsed), "normalized": len(normalized)})
        with zipfile.ZipFile(archive / "fixture.zip", "w") as bundle:
            bundle.writestr("nested/fixture.py", payload)
        zipped = invoke(_command_for("gitleaks", archive) + ["--no-banner", "--log-level", "error", "--redact", "--max-archive-depth", "1"])
        assert zipped.returncode == 1 and json.loads(zipped.stdout)
        assert marker not in zipped.stdout
        malformed = root / "invalid.toml"
        malformed.write_text("[this is not a valid TOML table")
        rejection = invoke([str(executable), "dir", str(good), "--config", str(malformed), "--no-banner", "--log-level", "error"])
        assert rejection.returncode != 0
    print(json.dumps({"status": "PASS", "version": version.stdout.strip(), "actual_application_argv_and_normalizer": True,
                      "synthetic_cases": outcomes, "archive_detection_verified": True, "invalid_config_rejected": True,
                      "reports_redacted": True, "external_network_used": False, "production_changed": False,
                      "full_image_security_passed": False}))


if __name__ == "__main__":
    main()
