"""Build a locally labelled Gitleaks from pinned source, Go and module locks.

Only public build inputs are used. Detection code, rules, reports and licenses
are not patched; go.mod/go.sum and the link-time local version are explicit.
The final binary checksum is pinned as well. Use in an isolated build stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, TextIO


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_lock(directory: Path) -> dict[str, Any]:
    lock = json.loads((directory / "lock.json").read_text())
    required = {"upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
                "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "modules", "expected_binary_sha256"}
    if set(lock) != required or set(lock["files"]) != {"go.mod", "go.sum"}:
        raise ValueError("Incomplete build lock")
    if not re.fullmatch(r"[0-9a-f]{40}", lock["upstream_commit"]):
        raise ValueError("Immutable upstream commit required")
    if lock["source_url"] != "https://codeload.github.com/gitleaks/gitleaks/tar.gz/" + lock["upstream_commit"]:
        raise ValueError("Unexpected source location")
    if not re.fullmatch(r"go\d+\.\d+\.\d+", lock["toolchain_version"]):
        raise ValueError("Stable Go toolchain required")
    if lock["toolchain_url"] != "https://go.dev/dl/" + lock["toolchain_version"] + ".linux-amd64.tar.gz":
        raise ValueError("Unexpected toolchain location")
    if lock["local_version"] != lock["upstream_version"] + "+aios.1":
        raise ValueError("Explicit local build version required")
    for digest in [lock["source_sha256"], lock["toolchain_sha256"], lock["expected_binary_sha256"], *lock["files"].values()]:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Pinned SHA256 required")
    if set(lock["modules"]) != {"golang.org/x/crypto", "golang.org/x/text", "golang.org/x/sync", "golang.org/x/sys"}:
        raise ValueError("Unexpected module correction scope")
    for name, digest in lock["files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise ValueError("Module lock changed: " + name)
    return lock


def fetch(url: str, target: Path, expected: str) -> None:
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("HTTPS build inputs required")
    with urllib.request.urlopen(url, timeout=120) as response, target.open("xb") as stream:
        total = 0
        while chunk := response.read(1024**2):
            total += len(chunk)
            if total > 128 * 1024**2:
                raise ValueError("Build archive too large")
            stream.write(chunk)
    if sha(target) != expected:
        raise ValueError("Downloaded build input hash differs")


def extract_verified(archive: Path, expected: str, destination: Path) -> Path:
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 128 * 1024**2 or sha(archive) != expected:
        raise ValueError("Unverified build archive")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Extraction destination already exists")
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        names: set[str] = set()
        roots: set[str] = set()
        if len(members) > 40000 or sum(m.size for m in members) > 1024**3:
            raise ValueError("Expanded archive bounds exceeded")
        for member in members:
            name = member.name.rstrip("/")
            path = PurePosixPath(name)
            if not name or name in names or path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unsafe or duplicate archive path")
            names.add(name)
            roots.add(path.parts[0])
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("Special file or hardlink not allowed")
            if member.issym():
                linked = posixpath.normpath(posixpath.join(str(path.parent), member.linkname))
                if member.linkname.startswith("/") or "\\" in member.linkname or not linked.startswith(path.parts[0] + "/"):
                    raise ValueError("Symlink escapes source root")
        if len(roots) != 1:
            raise ValueError("Single archive root required")
        destination.mkdir(parents=True)
        bundle.extractall(destination, filter="data")
    return destination / next(iter(roots))


def source_fingerprint(root: Path) -> dict[str, str]:
    # Include code, embedded rules/templates, and licenses. Mutable test fixtures
    # are checked by upstream tests rather than mistaken for application changes.
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink() and "testdata" not in p.relative_to(root).parts
            and p.name not in {"go.mod", "go.sum"}}


# Only fixed labels are emitted. Raw logs, URLs, argv and environment values
# stay private to the build stage; an unsuccessful Docker layer is not an artifact.
FAILURE_MARKERS = {
    "checksum_mismatch": (b"checksum mismatch", b"security error"),
    "http_429": (b"429 too many requests",),
    "http_5xx": (b"500 internal server error", b"502 bad gateway",
                 b"503 service unavailable", b"504 gateway timeout"),
    "http_403": (b"403 forbidden",),
    "http_404": (b"404 not found",),
    "network_timeout": (b"i/o timeout", b"tls handshake timeout", b"context deadline exceeded"),
    "dns_failure": (b"no such host", b"temporary failure in name resolution"),
    "connection_reset": (b"connection reset by peer",),
    "tls_certificate": (b"x509:",),
    "disk_full": (b"no space left on device",),
    "permission_denied": (b"permission denied",),
    "module_revision_missing": (b"unknown revision",),
}
FAILURE_TAIL_BYTES = 64 * 1024


def emit_failure_diagnostic(log: TextIO, return_code: int | None, *, timed_out: bool) -> None:
    """Read a bounded tail from the owned open descriptor, never from its path.

    Categories are observations of the retained tail, not proven root causes or
    retry permission. No command is retried and no unsuccessful step is accepted.
    """
    log.flush()
    size = os.fstat(log.fileno()).st_size
    tail = os.pread(log.fileno(), FAILURE_TAIL_BYTES, max(0, size - FAILURE_TAIL_BYTES))
    lower = tail.lower()
    categories = [name for name, markers in FAILURE_MARKERS.items()
                  if any(marker in lower for marker in markers)] or ["unclassified"]
    result = {"schema_version": 1, "event": "pinned_build_step_failure",
              "return_code": return_code, "timed_out": timed_out,
              "log_bytes": size, "bytes_examined": len(tail), "tail_only": size > len(tail),
              "tail_sha256": hashlib.sha256(tail).hexdigest(), "error_categories": categories}
    print("AIONEX_BUILD_FAILURE " + json.dumps(result, ensure_ascii=True), file=sys.stderr, flush=True)


def run(args: list[str], cwd: Path, env: dict[str, str], output: Path, timeout: int = 600) -> None:
    with output.open("x+") as log:
        try:
            result = subprocess.run(args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            emit_failure_diagnostic(log, None, timed_out=True)
            raise
        if result.returncode:
            emit_failure_diagnostic(log, result.returncode, timed_out=False)
            raise RuntimeError("Pinned build step failed; retained log: " + output.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, help="Optional verified archive cache: go.tar.gz and source.tar.gz")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ValueError("This reviewed build targets Linux amd64 only")
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
    original = source_fingerprint(source)
    for name in ("go.mod", "go.sum"):
        shutil.copyfile(args.lock_dir / name, source / name)
    env = {**os.environ, "PATH": str(toolchain / "bin") + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
           "GOTOOLCHAIN": "local", "GOSUMDB": "sum.golang.org", "CGO_ENABLED": "0", "GOMAXPROCS": "2",
           "GOFLAGS": "-mod=readonly", "GONOSUMDB": "", "GOPRIVATE": "", "GONOPROXY": ""}
    go = str(toolchain / "bin/go")
    version = subprocess.check_output([go, "version"], env=env, text=True).strip()
    if version != "go version " + lock["toolchain_version"] + " linux/amd64":
        raise RuntimeError("Unexpected compiler identity")
    run([go, "mod", "download", "all"], source, env, output / "download.log")
    run([go, "mod", "verify"], source, env, output / "verify.log")
    run([go, "test", "-p=2", "-count=1", "-json", "./..."], source, env, output / "upstream-tests.jsonl")
    binary = output / "gitleaks"
    run([go, "build", "-p=2", "-trimpath", "-buildvcs=false", "-ldflags",
         "-s -w -X=github.com/zricethezav/gitleaks/v8/version.Version=" + lock["local_version"],
         "-o", str(binary), "."], source, env, output / "build.log")
    if source_fingerprint(source) != original:
        raise RuntimeError("Upstream code/rules/templates changed")
    if any(sha(source / name) != digest for name, digest in lock["files"].items()):
        raise RuntimeError("Module graph changed during build")
    if sha(binary) != lock["expected_binary_sha256"]:
        raise RuntimeError("Reproducible binary digest differs")
    module_text = subprocess.check_output([go, "version", "-m", str(binary)], text=True, env=env)
    for name, version in lock["modules"].items():
        if "\tdep\t" + name + "\t" + version + "\t" not in module_text:
            raise RuntimeError("Required corrected module not linked: " + name)
    (output / "binary-modules.txt").write_text(module_text)
    shutil.copyfile(source / "LICENSE", output / "GITLEAKS-LICENSE")
    events = [json.loads(line) for line in (output / "upstream-tests.jsonl").read_text().splitlines() if line.startswith("{")]
    counts = {a: sum(e.get("Action") == a and bool(e.get("Test")) for e in events) for a in ("pass", "fail", "skip")}
    if not counts["pass"] or counts["fail"] or counts["skip"]:
        raise RuntimeError("Upstream tests incomplete")
    proof = {"lock": lock, "compiler": lock["toolchain_version"], "upstream_files_unchanged": original,
             "binary_sha256": sha(binary), "upstream_tests": counts, "production_changed": False,
             "full_image_security_accepted": False, "local_rebuild_not_upstream_release": True}
    (output / "gitleaks-build-provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"lock", "upstream_files_unchanged"}}))


if __name__ == "__main__":
    main()
