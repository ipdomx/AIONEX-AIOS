"""Pinned local Trivy rebuild with an explicit, offline-tested scanner subset.

Only dependency resolution and the link-time version differ from upstream.
No parser, detector, rule or test assertion is patched. This is not a full
upstream test suite, public-feed certificate or whole-image deployment approval.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from build_gitleaks import extract_verified, fetch, run, sha, source_fingerprint

TEST_PACKAGES = (
    "./pkg/detector/ospkg/debian", "./pkg/detector/library", "./pkg/db", "./pkg/report",
    "./pkg/fanal/analyzer/pkg/dpkg", "./pkg/fanal/analyzer/language/nodejs/npm",
    "./pkg/fanal/analyzer/secret",
)
MODULES = {"google.golang.org/grpc", "golang.org/x/crypto", "golang.org/x/net",
           "golang.org/x/mod", "github.com/go-git/go-git/v5", "oras.land/oras-go/v2"}


def read_lock(folder: Path) -> dict[str, Any]:
    path = folder / "lock.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Regular lock file required")
    lock = json.loads(path.read_text())
    fields = {"upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
              "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "upstream_files",
              "modules", "expected_binary_sha256"}
    if not isinstance(lock, dict) or set(lock) != fields:
        raise ValueError("Complete immutable Trivy lock required")
    if lock["upstream_version"] != "0.74.0" or lock["local_version"] != "0.74.0+aios.1":
        raise ValueError("Explicit local Trivy identity required")
    if not isinstance(lock["upstream_commit"], str) or not re.fullmatch(r"[a-f0-9]{40}", lock["upstream_commit"]):
        raise ValueError("Immutable source commit required")
    if lock["source_url"] != "https://codeload.github.com/aquasecurity/trivy/tar.gz/" + lock["upstream_commit"]:
        raise ValueError("Unexpected Trivy source URL")
    if lock["toolchain_version"] != "go1.26.8" or lock["toolchain_url"] != "https://go.dev/dl/go1.26.8.linux-amd64.tar.gz":
        raise ValueError("Reviewed compiler required")
    for field in ("files", "upstream_files"):
        if not isinstance(lock[field], dict) or set(lock[field]) != {"go.mod", "go.sum"}:
            raise ValueError("Complete module fingerprints required")
    for digest in (lock["source_sha256"], lock["toolchain_sha256"], lock["expected_binary_sha256"],
                   *lock["files"].values(), *lock["upstream_files"].values()):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("SHA256 pins required")
    if not isinstance(lock["modules"], dict) or set(lock["modules"]) != MODULES:
        raise ValueError("Complete reviewed linked-module set required")
    for version in lock["modules"].values():
        if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", version):
            raise ValueError("Pinned stable module required")
    if lock["modules"]["google.golang.org/grpc"] != "v1.83.2":
        raise ValueError("Corrected gRPC required")
    for name, digest in lock["files"].items():
        p = folder / name
        if p.is_symlink() or not p.is_file() or sha(p) != digest:
            raise ValueError("Reviewed module file drift")
    return lock


def prepare_modules(source: Path, folder: Path, lock: dict[str, Any]) -> None:
    # Verify every input first; no partial patch is written on ordinary drift.
    for name, digest in lock["upstream_files"].items():
        p = source / name
        if p.is_symlink() or not p.is_file() or sha(p) != digest:
            raise ValueError("Pristine upstream module files differ")
    for name, digest in lock["files"].items():
        p = folder / name
        if p.is_symlink() or not p.is_file() or sha(p) != digest:
            raise ValueError("Corrected module files differ")
    for name in ("go.mod", "go.sum"):
        shutil.copyfile(folder / name, source / name)


def build_environment(toolchain: Path) -> dict[str, str]:
    return {**os.environ, "PATH": str(toolchain / "bin") + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
            "GOTOOLCHAIN": "local", "GOSUMDB": "sum.golang.org", "GONOSUMDB": "", "GOPRIVATE": "",
            "GONOPROXY": "", "CGO_ENABLED": "0", "GOMAXPROCS": "2", "GOFLAGS": "-mod=readonly", "GOEXPERIMENT": "jsonv2"}


def build_command(go: str, binary: Path, lock: dict[str, Any]) -> list[str]:
    return [go, "build", "-p=2", "-trimpath", "-buildvcs=false", "-ldflags",
            "-s -w -X github.com/aquasecurity/trivy/pkg/version/app.ver=" + lock["local_version"],
            "-o", str(binary), "./cmd/trivy"]


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
    go_root = extract_verified(inputs / "go.tar.gz", lock["toolchain_sha256"], output / "toolchain")
    source = extract_verified(inputs / "source.tar.gz", lock["source_sha256"], output / "source")
    before = source_fingerprint(source)
    prepare_modules(source, args.lock_dir, lock)
    env = build_environment(go_root)
    go = str(go_root / "bin/go")
    if subprocess.check_output([go, "version"], env=env, text=True).strip() != "go version go1.26.8 linux/amd64":
        raise ValueError("Compiler identity differs")
    run([go, "mod", "download", "all"], source, env, output / "download.log")
    run([go, "mod", "verify"], source, env, output / "verify.log")
    run([go, "test", "-p=2", "-count=1", "-timeout=120s", "-json", *TEST_PACKAGES],
        source, env, output / "upstream-tests.jsonl")
    events = [json.loads(line) for line in (output / "upstream-tests.jsonl").read_text().splitlines() if line.startswith("{")]
    counts = {a: sum(e.get("Action") == a and bool(e.get("Test")) for e in events) for a in ("pass", "fail", "skip")}
    if not counts["pass"] or counts["fail"] or counts["skip"]:
        raise RuntimeError("Selected upstream acceptance incomplete")
    binary = output / "trivy"
    run(build_command(go, binary, lock), source, env, output / "build.log")
    if source_fingerprint(source) != before or any(sha(source / n) != h for n, h in lock["files"].items()):
        raise RuntimeError("Source or pinned dependency files drifted")
    if sha(binary) != lock["expected_binary_sha256"]:
        raise RuntimeError("Reproducible executable hash differs")
    linked = subprocess.check_output([go, "version", "-m", str(binary)], env=env, text=True)
    for name, version in lock["modules"].items():
        if "\tdep\t" + name + "\t" + version + "\t" not in linked:
            raise RuntimeError("Required linked module missing")
    (output / "binary-modules.txt").write_text(linked)
    shutil.copyfile(source / "LICENSE", output / "TRIVY-LICENSE")
    proof = {"lock": lock, "source_files_unchanged": before, "selected_packages": TEST_PACKAGES,
             "selected_tests": counts, "all_upstream_tests_claimed": False,
             "binary_sha256": sha(binary), "local_rebuild_not_upstream_binary": True,
             "production_changed": False, "full_image_security_passed": False}
    (output / "trivy-build-provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"lock", "source_files_unchanged"}}))


if __name__ == "__main__":
    main()
