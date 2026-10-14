"""Pinned local httpx rebuild with an explicit offline upstream-test scope.

The official v1.12.0 binary is NOT installed: its embedded Go is older than the
reviewed toolchain. Source/go.mod stay unchanged; go.sum adds verified checksums. The one
local-version marker is explicit. Full upstream network/ASN integration coverage is not
claimed; selected native tests and a separate loopback image verifier are used.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from build_gitleaks import emit_failure_diagnostic, extract_verified, fetch, run, sha, source_fingerprint

RUNNER_TESTS = (
    "TestDetermineMostLikelySchemeOrder", "TestSwitchPortForFallback", "TestSanitizeCPEVersion",
    "TestTechDetectRequired", "TestSetCPEVersion", "TestNormalizeProductName", "TestBuildTechVersionMap",
    "TestProductLookupKeys", "TestFallbackProductLookupKeys", "TestLookupTechVersion", "TestTechnologyTokens",
    "TestStrongTokens", "TestBuildTechnologyVersions", "TestLookupTechVersionRejectsAmbiguousFallback",
    "TestEnrichCPEVersionsIssue2536", "TestBuildTechVersionMapConflict", "TestEnrichCPEVersions",
    "TestEnrichCPEVersionsWithRealWappalyzer", "TestEnrichTomcatCPEWithRealDatasets",
    "TestEnrichVendorPrefixedTechnologiesIndependently", "TestEnrichCPEVersionsNoTechnologies",
    "TestRunner_CSVRow", "TestOptions_hasMatcherOrFilter",
)
MODULES = {"golang.org/x/crypto", "golang.org/x/net", "golang.org/x/text", "golang.org/x/sync", "golang.org/x/sys"}


def read_lock(directory: Path) -> dict[str, Any]:
    lock = json.loads((directory / "lock.json").read_text())
    fields = {"upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
              "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "modules", "expected_binary_sha256"}
    if not isinstance(lock, dict) or set(lock) != fields or set(lock["files"]) != {"go.mod", "go.sum"}:
        raise ValueError("Incomplete httpx build lock")
    if not re.fullmatch(r"[0-9a-f]{40}", lock["upstream_commit"]):
        raise ValueError("Immutable source commit required")
    if lock["source_url"] != "https://codeload.github.com/projectdiscovery/httpx/tar.gz/" + lock["upstream_commit"]:
        raise ValueError("Unexpected httpx source location")
    if not re.fullmatch(r"go\d+\.\d+\.\d+", lock["toolchain_version"]):
        raise ValueError("Stable pinned Go required")
    if lock["toolchain_url"] != "https://go.dev/dl/" + lock["toolchain_version"] + ".linux-amd64.tar.gz":
        raise ValueError("Unexpected Go input")
    if lock["upstream_version"] != "1.12.0" or lock["local_version"] != lock["upstream_version"] + "+aios.1":
        raise ValueError("Explicit local identity required")
    for value in (lock["source_sha256"], lock["toolchain_sha256"], lock["expected_binary_sha256"], *lock["files"].values()):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("SHA256 lock required")
    if set(lock["modules"]) != MODULES or any(not re.fullmatch(r"v\d+\.\d+\.\d+", v) for v in lock["modules"].values()):
        raise ValueError("Pinned linked modules required")
    for name, digest in lock["files"].items():
        p = directory / name
        if p.is_symlink() or not p.is_file() or sha(p) != digest:
            raise ValueError("Module lock differs")
    return lock


def label_source(source: Path, lock: dict[str, Any]) -> dict[str, str]:
    p = source / "runner/banner.go"
    before = p.read_text()
    old = "const Version = `v" + lock["upstream_version"] + "`"
    new = "const Version = `v" + lock["local_version"] + "`"
    if before.count(old) != 1:
        raise ValueError("Upstream version marker changed")
    digest = sha(p)
    p.write_text(before.replace(old, new))
    return {"path": "runner/banner.go", "before_sha256": digest, "after_sha256": sha(p)}


def test_commands(go: str) -> list[list[str]]:
    prefix = [go, "test", "-p=2", "-count=1", "-timeout=60s", "-json"]
    return [prefix + ["./common/authprovider/...", "./common/httputilz", "./common/inputformats"],
            prefix + ["./common/httpx", "-skip", "^TestDo$"],
            prefix + ["./runner", "-run", "^(" + "|".join(RUNNER_TESTS) + ")$"]]



def download_pinned_modules(go: str, source: Path, env: dict[str, str], output: Path,
                            *, runner=subprocess.run, sleeper=time.sleep) -> list[dict[str, Any]]:
    """Retry only the same checksum-pinned Go downloads, never tests/build/hash gates.

    All attempts use the identical immutable public module graph and the same
    verified compiler. Distinct logs and a manifest retain evidence, while a
    persistent error or an integrity/lock error still fails the image build.
    """
    attempts: list[dict[str, Any]] = []
    fatal_markers = (
        b"checksum mismatch", b"security error:", b"invalid version",
        b"unknown revision", b"malformed module path", b"requires go >=",
        b"go: updates to go.mod needed", b"module declares its path as",
        b"not allowed with -mod=readonly",
    )
    manifest = output / "go-module-download-attempts.json"

    for attempt in range(1, 4):
        logpath = output / f"go-download-attempt-{attempt}.log"
        with logpath.open("x+b") as logfile:
            expired = False
            try:
                executed = runner([go, "mod", "download", "all"], cwd=source, env=env,
                                  stdout=logfile, stderr=subprocess.STDOUT,
                                  check=False, timeout=240)
                return_code = executed.returncode
            except subprocess.TimeoutExpired:
                expired = True
                return_code = None
            logfile.flush()
            size = os.fstat(logfile.fileno()).st_size
            tail = os.pread(logfile.fileno(), min(size, 8192), max(0, size - 8192))
            fatal = any(marker in tail.lower() for marker in fatal_markers)
            attempts.append({
                "attempt": attempt,
                "return_code": return_code,
                "timed_out": expired,
                "log_size_bytes": size,
                "log_sha256": sha(logpath),
                "integrity_or_lock_failure": fatal,
            })
            if return_code == 0:
                manifest.write_text(json.dumps({
                    "scope": "immutable_checksum_pinned_go_mod_download_only",
                    "status": "PASS", "attempts": attempts,
                    "source_or_module_locks_changed": False,
                }, sort_keys=True) + "\n")
                if attempt > 1:
                    print("AIONEX_PINNED_GO_DOWNLOAD_RECOVERED " +
                          json.dumps({"attempts": attempt}, sort_keys=True), flush=True)
                return attempts
            if fatal or attempt == 3:
                manifest.write_text(json.dumps({
                    "scope": "immutable_checksum_pinned_go_mod_download_only",
                    "status": "FAIL_CLOSED", "attempts": attempts,
                    "source_or_module_locks_changed": False,
                }, sort_keys=True) + "\n")
                emit_failure_diagnostic(logfile, return_code, timed_out=expired)
                raise RuntimeError("Pinned Go module download failed after bounded attempts")
        sleeper(2 if attempt == 1 else 5)
    raise AssertionError("bounded Go download loop escaped unexpectedly")

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
    before = source_fingerprint(source)
    # go.mod is unchanged; download-all filled missing transitive checksums.
    # Keep every original checksum and pin the completed file before building.
    if sha(source / "go.mod") != lock["files"]["go.mod"]:
        raise ValueError("Upstream dependency graph changed")
    original_sums = set((source / "go.sum").read_text().splitlines())
    completed_sums = set((args.lock_dir / "go.sum").read_text().splitlines())
    if not original_sums <= completed_sums:
        raise ValueError("Original upstream checksums not preserved")
    shutil.copyfile(args.lock_dir / "go.sum", source / "go.sum")
    version_change = label_source(source, lock)
    expected = dict(before)
    expected["runner/banner.go"] = version_change["after_sha256"]
    env = {**os.environ, "PATH": str(toolchain / "bin") + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
           "GOTOOLCHAIN": "local", "GOSUMDB": "sum.golang.org", "GONOSUMDB": "", "GOPRIVATE": "",
           "GONOPROXY": "", "CGO_ENABLED": "0", "GOMAXPROCS": "2", "GOFLAGS": "-mod=readonly"}
    go = str(toolchain / "bin/go")
    compiler = subprocess.check_output([go, "version"], env=env, text=True).strip()
    if compiler != "go version " + lock["toolchain_version"] + " linux/amd64":
        raise ValueError("Compiler identity differs")
    download_pinned_modules(go, source, env, output)
    run([go, "mod", "verify"], source, env, output / "verify.log")
    events: list[dict[str, Any]] = []
    for i, command in enumerate(test_commands(go)):
        log = output / f"upstream-tests-{i}.jsonl"
        run(command, source, env, log)
        events.extend(json.loads(line) for line in log.read_text().splitlines() if line.startswith("{"))
    counts = {a: sum(e.get("Action") == a and bool(e.get("Test")) for e in events) for a in ("pass", "fail", "skip")}
    if not counts["pass"] or counts["fail"] or counts["skip"]:
        raise RuntimeError("Selected upstream tests incomplete")
    binary = output / "pd-httpx"
    run([go, "build", "-p=2", "-trimpath", "-buildvcs=false", "-ldflags", "-s -w", "-o", str(binary), "./cmd/httpx"],
        source, env, output / "build.log")
    if source_fingerprint(source) != expected or any(sha(source / n) != h for n, h in lock["files"].items()):
        raise RuntimeError("Source or module lock changed beyond local marker")
    if sha(binary) != lock["expected_binary_sha256"]:
        raise RuntimeError("Rebuilt binary SHA256 differs")
    linked = subprocess.check_output([go, "version", "-m", str(binary)], text=True, env=env)
    for module, version in lock["modules"].items():
        if "\tdep\t" + module + "\t" + version + "\t" not in linked:
            raise RuntimeError("Required linked module missing")
    (output / "binary-modules.txt").write_text(linked)
    shutil.copyfile(source / "LICENSE.md", output / "HTTPX-LICENSE.md")
    proof = {"lock": lock, "source_before": before, "source_after": expected, "version_marker_only": version_change,
             "binary_sha256": sha(binary), "selected_upstream_tests": counts, "all_upstream_tests_claimed": False,
             "test_commands": test_commands("go"), "external_network_and_ASN_tests_not_executed": True,
             "local_rebuild_not_upstream_binary": True, "production_changed": False, "full_image_security_accepted": False}
    (output / "httpx-build-provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"lock", "source_before", "source_after", "test_commands"}}))


if __name__ == "__main__":
    main()
