"""Build a pinned, explicitly local Grype and test its offline matcher subset.

A new, empty Git repository is used ONLY in the extracted build directory so
upstream DB-fixture tests can fingerprint source. No host repository or daemon
is used. This is not a full upstream suite or a full image-security approval.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from build_gitleaks import extract_verified, fetch, run, sha, source_fingerprint

TEST_PACKAGES = (
    "./grype/version", "./grype/match", "./grype/cpe", "./grype/db/v6",
    "./grype/matcher/python", "./grype/matcher/javascript", "./grype/matcher/dpkg",
    "./grype/presenter/json",
)
MODULES = {
    "github.com/docker/docker", "github.com/go-git/go-git/v5", "golang.org/x/crypto",
    "golang.org/x/mod", "golang.org/x/net", "google.golang.org/grpc",
}
FIXTURE_ID = "GHSA-h95j-h2rv-qrg4"


def read_lock(folder: Path) -> dict[str, Any]:
    p = folder / "lock.json"
    if p.is_symlink() or not p.is_file():
        raise ValueError("Regular lock file required")
    value = json.loads(p.read_text())
    fields = {"upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
              "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "modules",
              "build_date", "expected_binary_sha256"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Incomplete build lock")
    if value["upstream_version"] != "0.119.0" or value["local_version"] != "0.119.0+aios.1":
        raise ValueError("Explicit local identity required")
    if not isinstance(value["upstream_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["upstream_commit"]):
        raise ValueError("Immutable source required")
    if value["source_url"] != "https://codeload.github.com/anchore/grype/tar.gz/" + value["upstream_commit"]:
        raise ValueError("Unexpected source location")
    if not isinstance(value["toolchain_version"], str) or not re.fullmatch(r"go\d+\.\d+\.\d+", value["toolchain_version"]):
        raise ValueError("Stable pinned compiler required")
    if value["toolchain_url"] != "https://go.dev/dl/" + value["toolchain_version"] + ".linux-amd64.tar.gz":
        raise ValueError("Unexpected compiler location")
    if not isinstance(value["build_date"], str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value["build_date"]):
        raise ValueError("Fixed build time required")
    if not isinstance(value["files"], dict) or set(value["files"]) != {"go.mod", "go.sum"}:
        raise ValueError("Complete module files required")
    for digest in (value["source_sha256"], value["toolchain_sha256"], value["expected_binary_sha256"], *value["files"].values()):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("SHA256 pin required")
    if not isinstance(value["modules"], dict) or set(value["modules"]) != MODULES:
        raise ValueError("Complete linked-module inventory required")
    for version in value["modules"].values():
        if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+(?:\+incompatible)?", version):
            raise ValueError("Pinned module version required")
    for name, digest in value["files"].items():
        p = folder / name
        if p.is_symlink() or not p.is_file() or sha(p) != digest:
            raise ValueError("Module input drift")
    return value


def build_environment(toolchain: Path) -> dict[str, str]:
    return {**os.environ, "PATH": str(toolchain / "bin") + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
            "GOTOOLCHAIN": "local", "GOSUMDB": "sum.golang.org", "GONOSUMDB": "", "GOPRIVATE": "",
            "GONOPROXY": "", "CGO_ENABLED": "0", "GOMAXPROCS": "2", "GOFLAGS": "-mod=readonly",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def fingerprint(source: Path) -> dict[str, str]:
    # Only the private, newly initialized .git and generated testdata are excluded.
    # Tests and every other source file remain in the digest set.
    return {n: h for n, h in source_fingerprint(source).items() if ".git" not in Path(n).parts}


def build_command(go: str, output: Path, lock: dict[str, Any]) -> list[str]:
    flags = "-s -w -X main.version=" + lock["local_version"] + " -X main.gitCommit=" + lock["upstream_commit"]
    flags += " -X main.buildDate=" + lock["build_date"] + " -X main.gitDescription=v" + lock["local_version"]
    return [go, "build", "-p=2", "-trimpath", "-buildvcs=false", "-ldflags", flags, "-o", str(output), "./cmd/grype"]


def retain_test_fixture(source: Path, output: Path) -> dict[str, Any]:
    candidates = []
    for db in source.glob("grype/matcher/python/testdata/cache/db/python-name-and-vex/selected/*/v6/vulnerability.db"):
        if db.is_symlink() or not db.is_file():
            raise ValueError("Unexpected fixture DB")
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            names = [r[0] for r in conn.execute("SELECT name FROM vulnerability_handles ORDER BY name")]
        if names == [FIXTURE_ID]:
            candidates.append(db.parent)
    if len(candidates) != 1:
        raise ValueError("Exact isolated vulnerability fixture missing or ambiguous")
    dest = output / "test-fixture-db" / "6"
    dest.mkdir(parents=True, exist_ok=False)
    for name in ("vulnerability.db", "import.json"):
        p = candidates[0] / name
        if p.is_symlink() or not p.is_file():
            raise ValueError("Fixture metadata missing")
        shutil.copyfile(p, dest / name)
    return {"database_files": {n: sha(dest / n) for n in ("vulnerability.db", "import.json")},
            "vulnerability_ids": [FIXTURE_ID], "upstream_test_fixture_not_production_feed": True,
            "not_installed_as_runtime_database": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ValueError("Reviewed target is Linux amd64")
    lock = read_lock(args.lock_dir)
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    inputs = args.inputs
    if inputs is None:
        inputs = output / "inputs"
        inputs.mkdir()
        fetch(lock["source_url"], inputs / "source.tar.gz", lock["source_sha256"])
        fetch(lock["toolchain_url"], inputs / "go.tar.gz", lock["toolchain_sha256"])
    toolchain = extract_verified(inputs / "go.tar.gz", lock["toolchain_sha256"], output / "toolchain")
    source = extract_verified(inputs / "source.tar.gz", lock["source_sha256"], output / "source")
    if (source / ".git").exists() or (source / ".git").is_symlink():
        raise ValueError("Archive must not provide repository control files")
    before = fingerprint(source)
    if sha(source / "go.mod") != lock["files"]["go.mod"]:
        raise ValueError("Upstream dependency graph changed")
    original = set((source / "go.sum").read_text().splitlines())
    if not original <= set((args.lock_dir / "go.sum").read_text().splitlines()):
        raise ValueError("Original module checksums removed")
    shutil.copyfile(args.lock_dir / "go.sum", source / "go.sum")
    env = build_environment(toolchain)
    go = str(toolchain / "bin/go")
    compiler = subprocess.check_output([go, "version"], env=env, text=True).strip()
    if compiler != "go version " + lock["toolchain_version"] + " linux/amd64":
        raise ValueError("Compiler identity differs")
    run(["git", "init", "--quiet", "--template=", "."], source, env, output / "fixture-repository.log")
    run([go, "mod", "download", "all"], source, env, output / "download.log")
    run([go, "mod", "verify"], source, env, output / "verify.log")
    run([go, "test", "-p=2", "-count=1", "-timeout=120s", "-json", *TEST_PACKAGES], source, env, output / "upstream-tests.jsonl")
    events = [json.loads(s) for s in (output / "upstream-tests.jsonl").read_text().splitlines() if s.startswith("{")]
    counts = {a: sum(e.get("Action") == a and bool(e.get("Test")) for e in events) for a in ("pass", "fail", "skip")}
    if not counts["pass"] or counts["fail"] or counts["skip"]:
        raise RuntimeError("Selected upstream tests incomplete")
    binary = output / "grype"
    run(build_command(go, binary, lock), source, env, output / "build.log")
    if fingerprint(source) != before or any(sha(source / n) != h for n, h in lock["files"].items()):
        raise RuntimeError("Upstream source or locked modules changed")
    if sha(binary) != lock["expected_binary_sha256"]:
        raise RuntimeError("Rebuilt executable differs")
    linked = subprocess.check_output([go, "version", "-m", str(binary)], text=True, env=env)
    for name, version in lock["modules"].items():
        if "\tdep\t" + name + "\t" + version + "\t" not in linked:
            raise RuntimeError("Linked module inventory differs")
    (output / "binary-modules.txt").write_text(linked)
    shutil.copyfile(source / "LICENSE", output / "GRYPE-LICENSE")
    fixture = retain_test_fixture(source, output)
    proof = {"lock": lock, "source_files_unchanged": before, "selected_tests": counts,
             "selected_test_packages": TEST_PACKAGES, "all_upstream_tests_claimed": False,
             "private_empty_git_used_for_fixture_root": True, "binary_sha256": sha(binary),
             "test_fixture": fixture, "production_changed": False, "full_image_security_passed": False,
             "docker_module_findings_not_suppressed": True, "local_rebuild_not_upstream_binary": True}
    (output / "grype-build-provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"lock", "source_files_unchanged"}}))


if __name__ == "__main__":
    main()
