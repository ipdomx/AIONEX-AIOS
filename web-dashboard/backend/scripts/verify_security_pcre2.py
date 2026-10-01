"""Verify the official Debian PCRE2 backport using bounded, synthetic inputs.

Run native checks only in an isolated image, never against customer expressions.
The guarded allocator reserves canary space and intercepts invalid frees for
bounded diagnostics. A vulnerable native call can still crash its disposable
subprocess; this is not a native memory-safety sandbox, ASan or a production
exploitability test.
The 32-bit, huge-pattern CVE is covered by Debian's package fix, not reproduced
on this amd64 target. This verifier does not certify whole-image security.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import resource
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGE = "libpcre2-8-0"
MINIMUM_VERSION = "10.42-1+deb12u1"
TARGET_CVES = ("CVE-2026-86145", "CVE-2026-89157", "CVE-2026-89161")
LIBRARY = Path("/usr/lib/x86_64-linux-gnu/libpcre2-8.so.0")
CASES = ("match", "nonmatch", "lookbehind", "backreference", "unicode", "invalid-pattern",
         "dfa-heap-limit", "jit-copied-subject", "pattern-convert", "grep-cli", "nmap-cli")
MALLOC = C.CFUNCTYPE(C.c_void_p, C.c_size_t, C.c_void_p)
FREE = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, input=input_text, capture_output=True, text=True,
                          timeout=20, check=False)


def package_identity() -> dict[str, str]:
    result = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}", PACKAGE])
    parts = result.stdout.split("\t")
    if result.returncode or len(parts) != 4 or parts[0] != PACKAGE or parts[2] != "amd64" or parts[3].strip() != "ii":
        raise RuntimeError("Installed official amd64 PCRE2 package required")
    if run(["dpkg", "--compare-versions", parts[1], "ge", MINIMUM_VERSION]).returncode:
        raise RuntimeError("Debian PCRE2 security floor not met")
    path = LIBRARY.resolve(strict=True)
    if path.parent != LIBRARY.parent or not path.is_file():
        raise RuntimeError("Unexpected native library location")
    verify = run(["dpkg", "--verify", PACKAGE])
    if verify.returncode or verify.stdout.strip():
        raise RuntimeError("Installed PCRE2 package files differ")
    return {"package": parts[0], "version": parts[1], "architecture": parts[2],
            "library": str(path), "library_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class GuardedHeap:
    """Observe native PCRE2 allocator contracts using bounded private allocations."""

    GUARD = 65536
    MAX_SIZE = 4 * 1024 * 1024
    MAX_BLOCKS = 256

    def __init__(self) -> None:
        self.libc = C.CDLL(None)
        self.libc.malloc.argtypes = [C.c_size_t]
        self.libc.malloc.restype = C.c_void_p
        self.libc.free.argtypes = [C.c_void_p]
        self.libc.free.restype = None
        self.blocks: dict[int, int] = {}
        self.invalid_frees = 0
        self.overruns = 0
        self.denied_allocations = 0
        self.allocate_callback = MALLOC(self.allocate)
        self.free_callback = FREE(self.release)

    def allocate(self, size: int, _user: int) -> int | None:
        if not 0 < size <= self.MAX_SIZE or len(self.blocks) >= self.MAX_BLOCKS:
            self.denied_allocations += 1
            return None
        ptr = self.libc.malloc(size + self.GUARD)
        if not ptr:
            return None
        address = int(ptr)
        C.memset(address, 0, size)
        C.memset(address + size, 0xA5, self.GUARD)
        self.blocks[address] = size
        return address

    def release(self, ptr: int | None, _user: int) -> None:
        if not ptr:
            return
        size = self.blocks.pop(ptr, None)
        if size is None:
            self.invalid_frees += 1
            return  # Never pass a borrowed or unknown pointer to libc.free.
        if C.string_at(ptr + size, self.GUARD) != b"\xa5" * self.GUARD:
            self.overruns += 1
        self.libc.free(ptr)

    def finish(self) -> dict[str, int]:
        leaked = len(self.blocks)
        for ptr in list(self.blocks):
            self.release(ptr, 0)
        return {"invalid_frees": self.invalid_frees, "overruns": self.overruns,
                "unreleased_blocks": leaked, "denied_allocations": self.denied_allocations}


class Native:
    def __init__(self) -> None:
        self.lib = C.CDLL(str(LIBRARY.resolve(strict=True)))
        self.functions: dict[str, Any] = {}
        v, z, u, i = C.c_void_p, C.c_size_t, C.c_uint32, C.c_int
        definitions: dict[str, tuple[Any, list[Any]]] = {
            "general_context_create": (v, [MALLOC, FREE, v]),
            "general_context_free": (None, [v]),
            "compile_context_create": (v, [v]), "compile_context_free": (None, [v]),
            "compile": (v, [C.c_char_p, z, u, C.POINTER(i), C.POINTER(z), v]),
            "code_free": (None, [v]), "match_data_create_from_pattern": (v, [v, v]),
            "match_data_free": (None, [v]), "match": (i, [v, C.c_char_p, z, z, u, v, v]),
            "jit_compile": (i, [v, u]), "jit_match": (i, [v, C.c_char_p, z, z, u, v, v]),
            "dfa_match": (i, [v, C.c_char_p, z, z, u, v, v, C.POINTER(i), z]),
            "pattern_convert": (i, [C.c_char_p, z, u, C.POINTER(v), C.POINTER(z), v]),
            "converted_pattern_free": (None, [v]),
        }
        for name, (restype, args) in definitions.items():
            f = getattr(self.lib, "pcre2_" + name + "_8")
            f.restype, f.argtypes = restype, args
            self.functions[name] = f

    def call(self, name: str, *args: Any) -> Any:
        return self.functions[name](*args)


def native_case(name: str) -> dict[str, Any]:
    if name not in CASES:
        raise ValueError("Unrecognized fixed test case")
    if name == "grep-cli":
        p = run(["grep", "-P", r"^aios-\d+$"], input_text="aios-123\nnot-a-match\n")
        return {"case": name, "passed": p.returncode == 0 and p.stdout == "aios-123\n"}
    if name == "nmap-cli":
        p = run(["nmap", "-sL", "-n", "127.0.0.1"])
        return {"case": name, "passed": p.returncode == 0 and "127.0.0.1" in p.stdout,
                "scope": "loopback list-only, no probes or DNS"}
    api, heap = Native(), GuardedHeap()
    general = context = code = data = None
    accepted = False
    return_codes: list[int] = []
    try:
        general = api.call("general_context_create", heap.allocate_callback, heap.free_callback, None)
        context = api.call("compile_context_create", general)
        if not general or not context:
            raise RuntimeError("Native context allocation failed")
        patterns = {
            "match": (b"^aios-[0-9]+$", b"aios-123", 0),
            "nonmatch": (b"^aios-[0-9]+$", b"other", 0),
            "lookbehind": (b"(?<=aios:)ok", b"aios:ok", 0),
            "backreference": (rb"^(ab)\1$", b"abab", 0),
            "unicode": ("^\\p{L}+$".encode(), "اختبار".encode(), 0x00080000 | 0x00020000),
            "invalid-pattern": (b"[", b"x", 0),
            "dfa-heap-limit": (b"(*LIMIT_HEAP=4)(?=(?=(?=(?=(?=(?=(?=(?=a))(?R))))))).", b"a", 0),
            "jit-copied-subject": (b"^(aios)$", b"aios", 0),
            "pattern-convert": (b"^aios.*$", b"aios.txt", 0),
        }
        pattern, subject, flags = patterns[name]
        error, offset = C.c_int(), C.c_size_t()
        code = api.call("compile", pattern, len(pattern), flags, C.byref(error), C.byref(offset), context)
        if name == "invalid-pattern":
            accepted = not code and error.value > 0
        else:
            if not code:
                raise RuntimeError("Bounded synthetic pattern did not compile")
            data = api.call("match_data_create_from_pattern", code, general)
            if not data:
                raise RuntimeError("Match data allocation failed")
            if name == "dfa-heap-limit":
                workspace = (C.c_int * 1000)()
                rc = api.call("dfa_match", code, subject, len(subject), 0, 0, data, None, workspace, 1000)
                return_codes.append(rc)
                accepted = rc == -63  # PCRE2_ERROR_HEAPLIMIT, from the upstream regression.
            elif name == "jit-copied-subject":
                first = api.call("match", code, subject, len(subject), 0, 0x00002000 | 0x00004000, data, None)
                compiled = api.call("jit_compile", code, 1)
                borrowed = C.create_string_buffer(b"aios")
                second = api.call("jit_match", code, C.cast(borrowed, C.c_char_p), 4, 0, 0, data, None)
                return_codes.extend([first, compiled, second])
                accepted = first > 0 and compiled == 0 and second > 0
            elif name == "pattern-convert":
                converted, length = C.c_void_p(), C.c_size_t()
                glob = b"aios-*.txt"
                rc = api.call("pattern_convert", glob, len(glob), 0x00000010, C.byref(converted), C.byref(length), None)
                return_codes.append(rc)
                accepted = rc == 0 and bool(converted.value) and 0 < length.value < 512
                if converted.value:
                    api.call("converted_pattern_free", converted)
            else:
                rc = api.call("match", code, subject, len(subject), 0, 0, data, None)
                return_codes.append(rc)
                accepted = rc == -1 if name == "nonmatch" else rc > 0
    finally:
        for func, ptr in (("match_data_free", data), ("code_free", code),
                          ("compile_context_free", context), ("general_context_free", general)):
            if ptr:
                api.call(func, ptr)
        alloc = heap.finish()
    return {"case": name, "passed": accepted and not any(alloc.values()),
            "return_codes": return_codes, "allocator": alloc}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-case", choices=CASES)
    parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = C.CDLL(None)
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE; no test core dumps.
        raise RuntimeError("Cannot disable native-test dumpability")
    if args.native_case:
        case = native_case(args.native_case)
        print(json.dumps(case))
        raise SystemExit(0 if case["passed"] else 1)
    identity = package_identity()
    if args.package_only:
        print(json.dumps(identity))
        return
    results = []
    for name in CASES:
        p = run([sys.executable, str(Path(__file__).resolve()), "--native-case", name])
        try:
            case = json.loads(p.stdout)
        except ValueError:
            case = {"case": name, "passed": False, "exit": p.returncode}
        if p.returncode or case.get("passed") is not True:
            raise RuntimeError("Native PCRE2 regression failed: " + name + " " + json.dumps(case))
        results.append(case)
    print(json.dumps({"status": "PASS", "package": identity, "native_cases": results,
                      "native_case_count": len(results), "target_cves": TARGET_CVES,
                      "huge_pattern_32bit_cve_not_reproduced": True,
                      "production_changed": False, "full_image_security_passed": False,
                      "network_targets_contacted": False, "asan_claimed": False}))


if __name__ == "__main__":
    main()
