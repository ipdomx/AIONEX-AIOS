"""Verify installed Trivy using synthetic files and an explicitly isolated DB.

Use only in a disposable, unprivileged, network-disabled container. The fixture
DB contains a single historic advisory for synthetic metadata, not the current
public feed. Default vulnerability/misconfiguration/secret capabilities remain.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def fingerprint(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def invoke(args: list[str], accepted: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(args, capture_output=True, text=True, timeout=90, check=False)
    if r.returncode not in accepted:
        raise RuntimeError(f"Trivy fixture command failed ({r.returncode}): {r.stderr[-1800:]}")
    return r


def identifiers(data: dict[str, Any], kind: str, field: str) -> set[str]:
    return {v[field] for result in data.get("Results", []) for v in result.get(kind, []) or [] if field in v}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-db", type=Path, required=True)
    args = parser.parse_args()
    from app.services.security_tools import _command_for, _normalize_source_findings, _run_source_tool

    for name in ("trivy.db", "metadata.json"):
        path = args.fixture_db / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Regular synthetic DB inputs required")
    before_fixture = fingerprint(args.fixture_db)
    os.environ.update(TRIVY_SKIP_DB_UPDATE="true", TRIVY_SKIP_JAVA_DB_UPDATE="true",
                      TRIVY_SKIP_CHECK_UPDATE="true", TRIVY_OFFLINE_SCAN="true",
                      TRIVY_DISABLE_TELEMETRY="true", TRIVY_SKIP_VERSION_CHECK="true", TRIVY_NO_PROGRESS="true")
    version = json.loads(invoke(["trivy", "version", "--format", "json"]).stdout)
    assert version["Version"] == "0.74.0+aios.1"
    with tempfile.TemporaryDirectory(prefix="aios-trivy-fixture-") as folder:
        base = Path(folder)
        cache = base / "cache"
        shutil.copytree(args.fixture_db, cache / "db")
        os.environ["TRIVY_CACHE_DIR"] = str(cache)
        secret_config = base / "secret-rules.yaml"
        secret_config.write_text('rules:\n  - id: aios-synthetic-marker\n    category: fixture-only\n    title: Synthetic marker, never a credential\n    severity: HIGH\n    regex: "AIOS_SYNTHETIC_[A-Z]{16}"\n')
        os.environ["TRIVY_SECRET_CONFIG"] = str(secret_config)
        cases = []
        for tag, ver, affected in (("affected", "2.4.24", True), ("fixed", "2.4.25-1", False)):
            root = base / tag
            (root / "var/lib/dpkg").mkdir(parents=True)
            (root / "etc").mkdir()
            (root / "etc/os-release").write_text('ID=debian\nVERSION_ID="12"\nNAME="Synthetic inventory fixture"\n')
            (root / "etc/debian_version").write_text("12.0\n")
            (root / "var/lib/dpkg/status").write_text('Package: apache2\nStatus: install ok installed\nArchitecture: amd64\nVersion: ' + ver + '\nDescription: Synthetic metadata, not installed software\n\n')
            before = fingerprint(root)
            command = _command_for("trivy", root)
            payload = json.loads(invoke(command).stdout)
            ids = identifiers(payload, "Vulnerabilities", "VulnerabilityID")
            assert ids == ({"CVE-2020-11985"} if affected else set()), ids
            normalized = _normalize_source_findings("trivy", payload, "")
            assert bool(normalized) is affected
            runtime = asyncio.run(_run_source_tool("trivy", root, timeout=90))
            assert runtime["status"] == "completed" and runtime["exit_code"] == 0
            assert bool(runtime["findings"]) is affected
            threshold = invoke(command + ["--exit-code", "7"], (7,) if affected else (0,))
            assert threshold.returncode == (7 if affected else 0)
            assert fingerprint(root) == before
            cases.append({"name": tag, "fixture_advisories": sorted(ids), "threshold_exit": threshold.returncode})
        root = base / "capabilities"
        root.mkdir()
        (root / "Dockerfile").write_text('FROM alpine:3.23\nUSER root\nRUN echo synthetic-fixture\n')
        (root / "sample.txt").write_text('AIOS_SYNTHETIC_ABCDEFGHIJKLMNOP\n')
        before = fingerprint(root)
        report = json.loads(invoke(_command_for("trivy", root)).stdout)
        assert "DS-0002" in identifiers(report, "Misconfigurations", "ID"), identifiers(report, "Misconfigurations", "ID")
        assert "aios-synthetic-marker" in identifiers(report, "Secrets", "RuleID")
        accepted = asyncio.run(_run_source_tool("trivy", root, timeout=90))
        assert accepted["status"] == "completed" and len(accepted["findings"]) >= 2
        assert fingerprint(root) == before
        safe_config = base / "safe-config"
        safe_config.mkdir()
        (safe_config / "Dockerfile").write_text("FROM alpine:3.23\nUSER 1000\nHEALTHCHECK CMD true\n")
        safe_report = json.loads(invoke(_command_for("trivy", safe_config)).stdout)
        assert "DS-0002" not in identifiers(safe_report, "Misconfigurations", "ID")
        blank = base / "empty"
        blank.mkdir()
        empty_result = asyncio.run(_run_source_tool("trivy", blank, timeout=90))
        assert empty_result["status"] == "completed" and empty_result["findings"] == []
        malformed = base / "invalid-sbom.json"
        malformed.write_text('{"not-an-sbom":true}')
        assert invoke(["trivy", "sbom", str(malformed), "--format", "json"], (1,)).returncode == 1
        bad_cache = base / "bad-cache"
        shutil.copytree(args.fixture_db, bad_cache / "db")
        metadata = json.loads((bad_cache / "db/metadata.json").read_text())
        metadata["Version"] = 999
        (bad_cache / "db/metadata.json").write_text(json.dumps(metadata))
        os.environ["TRIVY_CACHE_DIR"] = str(bad_cache)
        assert invoke(_command_for("trivy", base / "affected"), (1,)).returncode == 1
        os.environ["TRIVY_CACHE_DIR"] = str(base / "missing-cache")
        assert invoke(_command_for("trivy", base / "affected"), (1,)).returncode == 1
        assert fingerprint(cache / "db") == before_fixture
    assert fingerprint(args.fixture_db) == before_fixture
    print(json.dumps({"status": "PASS", "version": version["Version"], "cases": cases,
                      "native_app_arguments_execution_normalization": True,
                      "default_dockerfile_misconfiguration_detected": True, "nonroot_config_control_passed": True,
                      "synthetic_custom_secret_rule_detected": True,
                      "default_secret_rules_not_disabled": True,
                      "empty_input_and_malformed_sbom_verified": True,
                      "incompatible_and_missing_db_rejected": True,
                      "fixture_database_not_current_public_feed": True,
                      "source_and_fixture_unchanged": True, "network_used": False,
                      "production_changed": False, "full_image_security_passed": False}))


if __name__ == "__main__":
    main()
