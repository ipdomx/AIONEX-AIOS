"""Native Grype matcher checks using an explicitly isolated upstream test DB.

Run only in a disposable, network-disabled image with --fixture-db pointing to
the builder's test output. No real project, current feed, or production database
is used, and the fixture database must never be installed as the runtime feed.
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


def invoke(args: list[str], accepted: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    if result.returncode not in accepted:
        raise RuntimeError(f"Isolated Grype check failed: {args[0]} ({result.returncode}): {result.stderr[-1200:]}")
    return result


def fingerprint(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-db", type=Path, required=True)
    args = parser.parse_args()
    from app.services.security_tools import _command_for, _normalize_source_findings, _run_source_tool

    for name in ("vulnerability.db", "import.json"):
        p = args.fixture_db / "6" / name
        if p.is_symlink() or not p.is_file():
            raise ValueError("Exact local fixture files required")
    original_fixture = fingerprint(args.fixture_db)
    os.environ.update(GRYPE_DB_AUTO_UPDATE="false", GRYPE_CHECK_FOR_APP_UPDATE="false",
                      GRYPE_DB_VALIDATE_AGE="true", GRYPE_DB_VALIDATE_BY_HASH_ON_START="true")
    version = json.loads(invoke(["grype", "version", "-o", "json"]).stdout)
    assert version["version"] == "0.119.0+aios.1" and version["goVersion"] == "go1.27.1"
    with tempfile.TemporaryDirectory(prefix="aios-grype-fixture-") as temp:
        base = Path(temp)
        database = base / "database"
        shutil.copytree(args.fixture_db, database, symlinks=False)
        os.environ["GRYPE_DB_CACHE_DIR"] = str(database)
        status = json.loads(invoke(["grype", "db", "status", "-o", "json"]).stdout)
        before_db = fingerprint(database)
        cases = []
        for name, package_version, expected_match in (("affected", "1.2.5", True), ("fixed", "1.3.5", False)):
            root = base / name
            root.mkdir()
            metadata = root / ("Django-" + package_version + ".dist-info") / "METADATA"
            metadata.parent.mkdir()
            metadata.write_text("Metadata-Version: 2.1\nName: Django\nVersion: " + package_version + "\nSummary: Synthetic inventory only\n")
            before = fingerprint(root)
            raw = invoke(_command_for("grype", root))
            payload = json.loads(raw.stdout)
            ids = {m["vulnerability"]["id"] for m in payload["matches"]}
            assert ids == ({"GHSA-h95j-h2rv-qrg4"} if expected_match else set())
            assert payload["source"] == {"type": "directory", "target": str(root)}
            normalized = _normalize_source_findings("grype", payload, "")
            assert bool(normalized) is expected_match
            assert all(x["state"] == "observed" for x in normalized)
            accepted = asyncio.run(_run_source_tool("grype", root, timeout=60))
            assert accepted["status"] == "completed" and accepted["exit_code"] == 0
            assert bool(accepted["findings"]) is expected_match
            threshold = invoke(_command_for("grype", root) + ["--fail-on", "negligible"], (1, 2) if expected_match else (0,))
            assert bool(threshold.returncode) is expected_match
            assert fingerprint(root) == before
            cases.append({"version": package_version, "expected_affected": expected_match,
                          "matching_ids": sorted(ids), "normalized_findings": len(normalized),
                          "threshold_exit": threshold.returncode})
        empty = base / "empty"
        empty.mkdir()
        assert json.loads(invoke(_command_for("grype", empty)).stdout)["matches"] == []
        malformed = base / "bad-sbom.json"
        malformed.write_text('{"not-a-supported-sbom":true}')
        assert invoke(["grype", "sbom:" + str(malformed), "-o", "json"], (1, 2)).returncode != 0
        assert fingerprint(database) == before_db
        broken = base / "broken-database"
        shutil.copytree(database, broken)
        meta = broken / "6/import.json"
        changed = json.loads(meta.read_text())
        changed["digest"] = "xxh64:" + "0" * 16
        meta.write_text(json.dumps(changed))
        os.environ["GRYPE_DB_CACHE_DIR"] = str(broken)
        assert invoke(["grype", "db", "status", "-o", "json"], (1, 2)).returncode != 0
        refused = invoke(_command_for("grype", base / "affected"), (1, 2))
        assert refused.returncode != 0
        os.environ["GRYPE_DB_CACHE_DIR"] = str(base / "missing-database")
        assert invoke(_command_for("grype", base / "affected"), (1, 2)).returncode != 0
    assert fingerprint(args.fixture_db) == original_fixture
    print(json.dumps({"status": "PASS", "version": version["version"], "cases": cases,
                      "actual_application_argv_execution_and_normalization": True,
                      "fixture_database_status": status, "fixture_database_unchanged": True,
                      "checksum_validation_failure_rejected": True, "missing_database_rejected": True,
                      "empty_and_malformed_inputs_checked": True, "upstream_test_database_not_current_feed": True,
                      "external_network": False, "production_changed": False, "full_image_security_passed": False}))


if __name__ == "__main__":
    main()
