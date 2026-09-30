"""Exercise native Syft against new synthetic files only, without network.

No client source, daemon socket, credential, package registry or production
service is contacted. Inventory is not a vulnerability finding or image gate.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def invoke(command: list[str], *, accepted: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False,
                       env={**os.environ, "SYFT_CHECK_FOR_APP_UPDATE": "false"})
    if p.returncode not in accepted:
        raise RuntimeError(f"Synthetic inventory test failed: {command[0]}, exit {p.returncode}: {p.stderr[-1000:]}")
    return p


def fingerprint(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def identity(items: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {((x["group"] + "/" if x.get("group") else "") + x["name"], x["version"])
            for x in items if x.get("type") not in {"file", "operating-system"}}


def main() -> None:
    from app.services.security_tools import _command_for, _run_source_tool

    version = json.loads(invoke(["syft", "version", "-o", "json"]).stdout)
    assert version["version"] == "1.52.0+aios.1"
    expected = {("fixture", "0.0.1"), ("aios-fixture-py", "1.2.3"), ("@aios/fixture-js", "4.5.6"), ("aios-fixture-deb", "7.8.9-1")}
    os.environ["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
    with tempfile.TemporaryDirectory(prefix="aios-syft-fixture-") as temp:
        base = Path(temp)
        root = base / "rootfs"
        root.mkdir()
        empty = base / "empty"
        empty.mkdir()
        files = {
            "usr/lib/python3.11/site-packages/aios_fixture_py-1.2.3.dist-info/METADATA":
                "Metadata-Version: 2.1\nName: aios-fixture-py\nVersion: 1.2.3\nLicense: MIT\nSummary: Synthetic test only\n",
            "node_modules/@aios/fixture-js/package.json": json.dumps({"name": "@aios/fixture-js", "version": "4.5.6", "license": "MIT"}),
            "package-lock.json": json.dumps({"name": "fixture", "version": "0.0.1", "lockfileVersion": 3, "requires": True, "packages": {"": {"name": "fixture", "version": "0.0.1", "dependencies": {"@aios/fixture-js": "4.5.6"}}, "node_modules/@aios/fixture-js": {"version": "4.5.6", "resolved": "https://registry.example.invalid/unused.tgz", "license": "MIT"}}}),
            "var/lib/dpkg/status": "Package: aios-fixture-deb\nStatus: install ok installed\nPriority: optional\nSection: misc\nArchitecture: amd64\nVersion: 7.8.9-1\nMaintainer: Synthetic <fixture@example.invalid>\nDescription: Synthetic inventory test\n\n",
            "etc/os-release": 'ID=debian\nVERSION_ID="12"\nNAME="Synthetic Debian fixture"\n',
        }
        for name, data in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(data)
        before = fingerprint(root)
        cdx = json.loads(invoke(_command_for("syft", root)).stdout)
        assert cdx["bomFormat"] == "CycloneDX" and identity(cdx["components"]) == expected
        assert all(x.get("purl") for x in cdx["components"] if x.get("type") == "library")
        assert [(x["name"], x["version"]) for x in cdx["components"] if x.get("type") == "operating-system"] == [("debian", "12")]
        assert all(x["name"].startswith(str(root)) for x in cdx["components"] if x.get("type") == "file")
        cdx_again = json.loads(invoke(_command_for("syft", root)).stdout)
        assert identity(cdx_again["components"]) == expected
        native = json.loads(invoke(["syft", "dir:" + str(root), "-o", "syft-json"]).stdout)
        assert identity(native["artifacts"]) == expected
        assert all(x.get("locations") for x in native["artifacts"])
        inventory = base / "inventory.json"
        inventory.write_text(json.dumps(native))
        spdx = json.loads(invoke(["syft", "convert", str(inventory), "-o", "spdx-json"]).stdout)
        assert spdx["spdxVersion"].startswith("SPDX-")
        assert {(x["name"], x["versionInfo"]) for x in spdx["packages"] if x.get("versionInfo")} - {("debian", "12")} == expected
        blank = json.loads(invoke(_command_for("syft", empty)).stdout)
        assert blank.get("components", []) in ([], None)
        result = asyncio.run(_run_source_tool("syft", root, timeout=60))
        assert result["status"] == "completed" and result["exit_code"] == 0
        assert result["findings"] == [] and result["finding_count"] == 0
        invalid = invoke(["syft", "dir:" + str(root), "-o", "aios-invalid-format"], accepted=(1, 2))
        assert invalid.returncode != 0
        malformed = base / "invalid-sbom.json"
        malformed.write_text('{"not-a-supported-sbom":true}')
        rejected = invoke(["syft", "convert", str(malformed), "-o", "spdx-json"], accepted=(1, 2))
        assert rejected.returncode != 0 and fingerprint(root) == before
    print(json.dumps({"status": "PASS", "version": version["version"], "native_inventory_components": len(expected),
                      "ecosystems": ["python", "javascript", "debian"], "formats": ["cyclonedx-json", "syft-json", "spdx-json"],
                      "native_application_argv_and_execution": True, "empty_inventory_verified": True,
                      "invalid_format_and_malformed_input_rejected": True, "source_unchanged": True,
                      "no_fabricated_vulnerability_findings": True, "network_used": False,
                      "production_changed": False, "full_image_security_passed": False}))


if __name__ == "__main__":
    main()
