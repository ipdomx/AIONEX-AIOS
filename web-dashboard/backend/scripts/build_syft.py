"""Pinned Syft source rebuild; selected offline cataloger/format tests only.

Three absolute symlink fixtures belonging exclusively to the unselected upstream
fileresolver test suite are recorded but never materialized. No source file,
cataloger rule, parser or selected test is edited. Not a full upstream-test claim.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import posixpath
import re
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from build_gitleaks import extract_verified, fetch, run, sha, source_fingerprint

OMITTED_LINKS = {
    "syft/internal/fileresolver/testdata/symlinks-base/baz": "/../../base",
    "syft/internal/fileresolver/testdata/symlinks-base/chain": "/foo",
    "syft/internal/fileresolver/testdata/symlinks-base/foo": "/base",
}
TEST_PACKAGES = (
    "./syft/pkg", "./syft/pkg/cataloger/python", "./syft/pkg/cataloger/javascript",
    "./syft/pkg/cataloger/debian", "./syft/format/cyclonedxjson", "./syft/format/syftjson",
)
EXTERNAL_TESTS = (
    "Test_PackageCataloger_SitePackageRelationships", "TestDpkgCataloger", "TestDpkgArchiveCataloger",
    "TestCycloneDxImageEncoder", "Test_EncodeDecodeCycle", "Test_JSONSchemaConventions",
)
MODULES = {"golang.org/x/crypto", "golang.org/x/mod", "golang.org/x/net", "google.golang.org/grpc"}


def read_lock(folder: Path) -> dict[str, Any]:
    lock = json.loads((folder / "lock.json").read_text())
    fields = {"upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
              "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "modules",
              "build_date", "expected_binary_sha256"}
    if not isinstance(lock, dict) or set(lock) != fields or set(lock["files"]) != {"go.mod", "go.sum"}:
        raise ValueError("Incomplete Syft source lock")
    if lock["upstream_version"] != "1.52.0" or lock["local_version"] != "1.52.0+aios.1":
        raise ValueError("Explicit local identity required")
    if not re.fullmatch(r"[0-9a-f]{40}", lock["upstream_commit"]):
        raise ValueError("Immutable source commit required")
    if lock["source_url"] != "https://codeload.github.com/anchore/syft/tar.gz/" + lock["upstream_commit"]:
        raise ValueError("Unexpected source URL")
    if not re.fullmatch(r"go\d+\.\d+\.\d+", lock["toolchain_version"]):
        raise ValueError("Stable pinned toolchain required")
    if lock["toolchain_url"] != "https://go.dev/dl/" + lock["toolchain_version"] + ".linux-amd64.tar.gz":
        raise ValueError("Unexpected toolchain URL")
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", lock["build_date"]):
        raise ValueError("Fixed local build timestamp required")
    for value in (lock["source_sha256"], lock["toolchain_sha256"], lock["expected_binary_sha256"], *lock["files"].values()):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("SHA256 input/output pins required")
    if set(lock["modules"]) != MODULES or any(not re.fullmatch(r"v\d+\.\d+\.\d+", v) for v in lock["modules"].values()):
        raise ValueError("Required module inventory missing")
    for name, digest in lock["files"].items():
        p = folder / name
        if p.is_symlink() or not p.is_file() or sha(p) != digest:
            raise ValueError("Module lock drift")
    return lock


def extract_source(archive: Path, expected: str, destination: Path) -> Path:
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 128 * 1024**2 or sha(archive) != expected:
        raise ValueError("Unverified source archive")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination exists")
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) > 40000 or sum(m.size for m in members) > 1024**3:
            raise ValueError("Archive size bound")
        roots = {PurePosixPath(m.name).parts[0] for m in members if m.name}
        if len(roots) != 1:
            raise ValueError("Expected one source root")
        root = next(iter(roots))
        names: set[str] = set()
        omitted: dict[str, str] = {}
        selected = []
        for m in members:
            name = m.name.rstrip("/")
            p = PurePosixPath(name)
            if not name or name in names or p.is_absolute() or ".." in p.parts or "\\" in name:
                raise ValueError("Unsafe or duplicate member")
            names.add(name)
            if not (m.isdir() or m.isfile() or m.issym()):
                raise ValueError("Special file rejected")
            relative = name.removeprefix(root + "/")
            if relative in OMITTED_LINKS:
                if not m.issym() or m.linkname != OMITTED_LINKS[relative]:
                    raise ValueError("Omitted fixture identity changed")
                omitted[relative] = m.linkname
                continue
            if m.issym():
                target = posixpath.normpath(posixpath.join(str(p.parent), m.linkname))
                if m.linkname.startswith("/") or "\\" in m.linkname or not target.startswith(root + "/"):
                    raise ValueError("Symlink escape rejected")
            selected.append(m)
        if omitted != OMITTED_LINKS:
            raise ValueError("Pinned fixture set differs")
        destination.mkdir(parents=True)
        bundle.extractall(destination, members=selected, filter="data")
    return destination / root


def build_environment(toolchain: Path) -> dict[str, str]:
    return {**os.environ, "PATH": str(toolchain / "bin") + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
            "GOTOOLCHAIN": "local", "GOSUMDB": "sum.golang.org", "GONOSUMDB": "", "GOPRIVATE": "",
            "GONOPROXY": "", "CGO_ENABLED": "0", "GOMAXPROCS": "2", "GOFLAGS": "-mod=readonly"}


def build_command(go: str, output: Path, lock: dict[str, Any]) -> list[str]:
    flags = "-s -w -X main.version=" + lock["local_version"] + " -X main.gitCommit=" + lock["upstream_commit"]
    flags += " -X main.buildDate=" + lock["build_date"] + " -X main.gitDescription=v" + lock["local_version"]
    return [go, "build", "-p=2", "-trimpath", "-buildvcs=false", "-ldflags", flags, "-o", str(output), "./cmd/syft"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ValueError("Reviewed platform is Linux amd64")
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
    source = extract_source(inputs / "source.tar.gz", lock["source_sha256"], output / "source")
    before = source_fingerprint(source)
    if sha(source / "go.mod") != lock["files"]["go.mod"]:
        raise ValueError("Upstream module graph differs")
    original = set((source / "go.sum").read_text().splitlines())
    if not original <= set((args.lock_dir / "go.sum").read_text().splitlines()):
        raise ValueError("Original checksums removed")
    shutil.copyfile(args.lock_dir / "go.sum", source / "go.sum")
    env = build_environment(toolchain)
    go = str(toolchain / "bin/go")
    compiler = subprocess.check_output([go, "version"], env=env, text=True).strip()
    if compiler != "go version " + lock["toolchain_version"] + " linux/amd64":
        raise ValueError("Compiler identity differs")
    run([go, "mod", "download", "all"], source, env, output / "download.log")
    run([go, "mod", "verify"], source, env, output / "verify.log")
    run([go, "test", "-p=2", "-count=1", "-timeout=120s", "-json", "-skip", "^(" + "|".join(EXTERNAL_TESTS) + ")$", *TEST_PACKAGES], source, env, output / "upstream-tests.jsonl")
    events = [json.loads(s) for s in (output / "upstream-tests.jsonl").read_text().splitlines() if s.startswith("{")]
    counts = {a: sum(e.get("Action") == a and bool(e.get("Test")) for e in events) for a in ("pass", "fail", "skip")}
    if not counts["pass"] or counts["fail"] or counts["skip"]:
        raise RuntimeError("Selected test scope incomplete")
    binary = output / "syft"
    run(build_command(go, binary, lock), source, env, output / "build.log")
    if source_fingerprint(source) != before or any(sha(source / n) != h for n, h in lock["files"].items()):
        raise RuntimeError("Source or module lock changed")
    if sha(binary) != lock["expected_binary_sha256"]:
        raise RuntimeError("Reproducible binary digest differs")
    linked = subprocess.check_output([go, "version", "-m", str(binary)], env=env, text=True)
    for name, version in lock["modules"].items():
        if "\tdep\t" + name + "\t" + version + "\t" not in linked:
            raise RuntimeError("Expected module absent from binary")
    (output / "binary-modules.txt").write_text(linked)
    shutil.copyfile(source / "LICENSE", output / "SYFT-LICENSE")
    proof = {"lock": lock, "compiler": lock["toolchain_version"], "source_files_unchanged": before,
             "unmaterialized_absolute_fixture_links": OMITTED_LINKS, "selected_test_packages": TEST_PACKAGES,
             "selected_tests": counts, "all_upstream_tests_claimed": False, "excluded_image_and_git_tests": EXTERNAL_TESTS, "binary_sha256": sha(binary),
             "local_rebuild_not_upstream_binary": True, "production_changed": False, "full_image_security_passed": False}
    (output / "syft-build-provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"lock", "source_files_unchanged"}}))


if __name__ == "__main__":
    main()
