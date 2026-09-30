"""Verify the Debian liblzma backport and bounded, offline Python compatibility.

The package floor covers GHSA-5qpq-xqfv-j9pg. These smoke cases do not recreate
allocator-failure corruption, certify all XZ consumers, or replace an image scan.
Run in a disposable build/test image, not against customer archives.
"""
from __future__ import annotations

import hashlib
import json
import lzma
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

PACKAGE = "liblzma5"
MINIMUM_VERSION = "5.4.1-1+deb12u2"
ADVISORY = "GHSA-5qpq-xqfv-j9pg"
LIBRARY = Path("/usr/lib/x86_64-linux-gnu/liblzma.so.5")
PAYLOAD = (b"AIONEX synthetic compression compatibility\n" * 128) + bytes(range(256))
MEMORY_LIMIT = 16 * 1024 * 1024
CASES = ("xz-crc32", "xz-crc64", "xz-sha256", "legacy-alone", "streaming",
         "corrupt-check", "truncated-stream", "invalid-header", "memory-limit")


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)


def loaded_libraries() -> set[Path]:
    paths = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and "liblzma.so" in fields[5]:
            if fields[5].endswith(" (deleted)"):
                raise RuntimeError("Loaded liblzma was deleted")
            paths.add(Path(fields[5]).resolve(strict=True))
    return paths


def native_manifest_digest(path: Path) -> str:
    """Require explicit native-file coverage in dpkg's installed metadata.

    dpkg --verify silently omits files without an MD5 entry. This comparison
    detects missing metadata/file drift, not malicious replacement of both the
    trusted package database and the library by root. APT authenticates packages;
    MD5 here follows dpkg's format and is not a provenance/security signature.
    """
    result = run(["dpkg-query", "--control-show", f"{PACKAGE}:amd64", "md5sums"])
    if result.returncode or result.stderr.strip() or not result.stdout.strip():
        raise RuntimeError("Native liblzma checksum metadata missing")
    if len(result.stdout) > 1024 * 1024:
        raise RuntimeError("Native liblzma checksum metadata oversized")
    expected_paths = {path.relative_to("/").as_posix()}
    # Bookworm may record /lib while the merged-/usr filesystem resolves it
    # to /usr/lib. No arbitrary path alias is accepted as native coverage.
    if path.is_relative_to("/usr/lib"):
        expected_paths.add(path.relative_to("/usr").as_posix())
    matches: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split("  ", 1)
        if (len(parts) != 2 or len(parts[0]) != 32
                or any(c not in "0123456789abcdef" for c in parts[0])):
            raise RuntimeError("Native liblzma checksum metadata malformed")
        name = parts[1]
        relative = PurePosixPath(name)
        if (not name or relative.is_absolute() or ".." in relative.parts
                or relative.as_posix() != name or "\\" in name or "\x00" in name
                or name in seen):
            raise RuntimeError("Native liblzma checksum metadata path invalid")
        seen.add(name)
        if name in expected_paths:
            if Path("/", name).resolve(strict=True) != path:
                raise RuntimeError("Native liblzma checksum path does not match")
            matches.append(parts[0])
    if len(matches) != 1:
        raise RuntimeError("Native liblzma checksum coverage not unique")
    return matches[0]


def package_identity() -> dict[str, str]:
    result = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}", PACKAGE])
    parts = result.stdout.split("\t")
    if (result.returncode or result.stderr.strip() or len(parts) != 4 or parts[0] != PACKAGE
            or parts[2] != "amd64" or parts[3].strip() != "ii"):
        raise RuntimeError("Installed official amd64 liblzma package required")
    if run(["dpkg", "--compare-versions", parts[1], "ge", MINIMUM_VERSION]).returncode:
        raise RuntimeError("Debian liblzma security floor not met")
    path = LIBRARY.resolve(strict=True)
    if path.parent != LIBRARY.parent or not path.is_file():
        raise RuntimeError("Unexpected native liblzma location")
    verified = run(["dpkg", "--verify", PACKAGE])
    if verified.returncode or verified.stdout.strip() or verified.stderr.strip():
        raise RuntimeError("Installed liblzma package files differ")
    if loaded_libraries() != {path}:
        raise RuntimeError("Python is not using exactly the verified liblzma")
    expected_digest = native_manifest_digest(path)
    data = path.read_bytes()
    if hashlib.md5(data, usedforsecurity=False).hexdigest() != expected_digest:
        raise RuntimeError("Native liblzma content checksum differs")
    return {"package": parts[0], "version": parts[1], "architecture": parts[2],
            "library": str(path), "library_sha256": hashlib.sha256(data).hexdigest(),
            "library_package_md5": expected_digest}


def expect_rejection(data: bytes, *, memlimit: int = MEMORY_LIMIT) -> None:
    try:
        lzma.decompress(data, memlimit=memlimit)
    except lzma.LZMAError:
        return
    raise RuntimeError("Invalid or over-budget synthetic archive accepted")


def native_case(name: str) -> dict[str, Any]:
    if name not in CASES:
        raise ValueError("Unrecognized fixed LZMA case")
    checks = {"xz-crc32": lzma.CHECK_CRC32, "xz-crc64": lzma.CHECK_CRC64,
              "xz-sha256": lzma.CHECK_SHA256}
    if name in checks:
        data = lzma.compress(PAYLOAD, preset=0, check=checks[name])
        if lzma.decompress(data, memlimit=MEMORY_LIMIT) != PAYLOAD:
            raise RuntimeError("XZ round trip differs")
    elif name == "legacy-alone":
        data = lzma.compress(PAYLOAD, format=lzma.FORMAT_ALONE, preset=0)
        if lzma.decompress(data, memlimit=MEMORY_LIMIT) != PAYLOAD:
            raise RuntimeError("Legacy LZMA round trip differs")
    else:
        data = lzma.compress(PAYLOAD, preset=0)
        if name == "streaming":
            decoder = lzma.LZMADecompressor(memlimit=MEMORY_LIMIT)
            output = bytearray()
            for offset in range(0, len(data), 7):
                output.extend(decoder.decompress(data[offset:offset + 7], max_length=len(PAYLOAD) + 1 - len(output)))
                if len(output) > len(PAYLOAD):
                    raise RuntimeError("Synthetic decode exceeded output budget")
            if bytes(output) != PAYLOAD or not decoder.eof or decoder.unused_data:
                raise RuntimeError("Streaming LZMA decode incomplete")
        elif name == "corrupt-check":
            damaged = bytearray(data)
            damaged[-13] ^= 1
            expect_rejection(bytes(damaged))
        elif name == "truncated-stream":
            expect_rejection(data[:-8])
        elif name == "invalid-header":
            expect_rejection(b"not-an-xz-archive")
        else:
            expect_rejection(data, memlimit=1)
    return {"case": name, "passed": True}


def main() -> None:
    identity = package_identity()
    results = [native_case(name) for name in CASES]
    print(json.dumps({"status": "PASS", "package": identity, "advisory": ADVISORY,
                      "native_cases": results, "native_case_count": len(results),
                      "allocator_failure_regression_reproduced": False,
                      "full_image_security_passed": False, "network_targets_contacted": False}))


if __name__ == "__main__":
    main()
