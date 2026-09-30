"""Build Grype with a reviewed modular-client migration and offline matcher tests.

A new, empty Git repository is used ONLY in the extracted build directory so
upstream DB-fixture tests can fingerprint source. No host repository or daemon
is used. The only upstream source changes migrate Docker completion, remove a
legacy test-only homedir import, and add native completion regression tests.
This is not a full upstream suite or a full image-security approval.
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
    "./grype/presenter/json", "./internal/format",
)
MODULES = {
    "github.com/moby/moby/client", "github.com/moby/moby/api", "github.com/go-git/go-git/v5", "golang.org/x/crypto",
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
              "build_date", "expected_binary_sha256", "upstream_files", "source_patches"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Incomplete build lock")
    if value["upstream_version"] != "0.119.0" or value["local_version"] != "0.119.0+aios.2":
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
    validate_source_patches(folder, value)
    return value


PATCH_TARGETS = {
    "cmd/grype/cli/commands/completion.go": "completion.go",
    "internal/format/writer_test.go": "writer_test.go",
    "cmd/grype/cli/commands/completion_aios_test.go": "completion_aios_test.go",
}


def validate_source_patches(folder: Path, lock: dict[str, Any]) -> None:
    if not isinstance(lock.get("upstream_files"), dict) or set(lock["upstream_files"]) != {"go.mod", "go.sum"}:
        raise ValueError("Pristine upstream module fingerprints required")
    for digest in lock["upstream_files"].values():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Pristine fingerprint missing")
    patches = lock.get("source_patches")
    if not isinstance(patches, dict) or set(patches) != set(PATCH_TARGETS):
        raise ValueError("Exact reviewed migration file set required")
    for target, name in PATCH_TARGETS.items():
        entry = patches[target]
        if not isinstance(entry, dict) or set(entry) != {"before_sha256", "after_sha256", "replacement"} or entry["replacement"] != name:
            raise ValueError("Migration recipe differs")
        before = entry["before_sha256"]
        if target.endswith("completion_aios_test.go"):
            if before is not None:
                raise ValueError("Regression file must be new")
        elif not isinstance(before, str) or not re.fullmatch(r"[0-9a-f]{64}", before):
            raise ValueError("Original migration-file fingerprint required")
        after = entry["after_sha256"]
        file = folder / "patches" / name
        if not isinstance(after, str) or not re.fullmatch(r"[0-9a-f]{64}", after) or file.is_symlink() or not file.is_file() or sha(file) != after:
            raise ValueError("Reviewed migration file changed")


def apply_source_patches(source: Path, folder: Path, lock: dict[str, Any]) -> None:
    validate_source_patches(folder, lock)
    # Validate the entire old state before writing any source file.
    for name, digest in lock["upstream_files"].items():
        if (source / name).is_symlink() or sha(source / name) != digest:
            raise ValueError("Pristine upstream module files changed")
    for target, entry in lock["source_patches"].items():
        file = source / target
        if file.is_symlink():
            raise ValueError("Source patch target is a symlink")
        if entry["before_sha256"] is None:
            if file.exists():
                raise ValueError("Regression file already exists")
        elif not file.is_file() or sha(file) != entry["before_sha256"]:
            raise ValueError("Upstream client source drift")
    for target, entry in lock["source_patches"].items():
        shutil.copyfile(folder / "patches" / entry["replacement"], source / target)
    for name in ("go.mod", "go.sum"):
        shutil.copyfile(folder / name, source / name)


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
    apply_source_patches(source, args.lock_dir, lock)
    expected = dict(before)
    for target, entry in lock["source_patches"].items():
        expected[target] = entry["after_sha256"]
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
    run([go, "test", "-p=2", "-count=1", "-timeout=60s", "-json",
         "./cmd/grype/cli/commands", "-run", "^TestAIOS"], source, env, output / "completion-tests.jsonl")
    completion_events = [json.loads(s) for s in (output / "completion-tests.jsonl").read_text().splitlines() if s.startswith("{")]
    completion_counts = {a: sum(e.get("Action") == a and bool(e.get("Test")) for e in completion_events) for a in ("pass", "fail", "skip")}
    if completion_counts != {"pass": 8, "fail": 0, "skip": 0}:
        raise RuntimeError("Native Docker completion regression failed")
    graph = subprocess.check_output([go, "list", "-m", "all"], env=env, cwd=source, text=True)
    if any(line.split()[0] == "github.com/docker/docker" for line in graph.splitlines()):
        raise RuntimeError("Obsolete Docker module still present in dependency graph")
    (output / "module-graph.txt").write_text(graph)
    binary = output / "grype"
    run(build_command(go, binary, lock), source, env, output / "build.log")
    if fingerprint(source) != expected or any(sha(source / n) != h for n, h in lock["files"].items()):
        raise RuntimeError("Upstream source or locked modules changed")
    if sha(binary) != lock["expected_binary_sha256"]:
        raise RuntimeError("Rebuilt executable differs")
    linked = subprocess.check_output([go, "version", "-m", str(binary)], text=True, env=env)
    for name, version in lock["modules"].items():
        if "\tdep\t" + name + "\t" + version + "\t" not in linked:
            raise RuntimeError("Linked module inventory differs")
    if any(len(fields := line.split()) > 1 and fields[0] == "dep" and fields[1] == "github.com/docker/docker" for line in linked.splitlines()):
        raise RuntimeError("Obsolete Docker code linked into executable")
    (output / "binary-modules.txt").write_text(linked)
    shutil.copyfile(source / "LICENSE", output / "GRYPE-LICENSE")
    fixture = retain_test_fixture(source, output)
    proof = {"lock": lock, "source_before": before, "source_after": expected, "reviewed_source_migration": lock["source_patches"], "completion_tests": completion_counts, "legacy_docker_module_absent": True, "selected_tests": counts,
             "selected_test_packages": TEST_PACKAGES, "all_upstream_tests_claimed": False,
             "private_empty_git_used_for_fixture_root": True, "binary_sha256": sha(binary),
             "test_fixture": fixture, "production_changed": False, "full_image_security_passed": False,
             "docker_module_findings_not_suppressed": True, "local_rebuild_not_upstream_binary": True}
    (output / "grype-build-provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"lock", "source_before", "source_after", "reviewed_source_migration"}}))


if __name__ == "__main__":
    main()
