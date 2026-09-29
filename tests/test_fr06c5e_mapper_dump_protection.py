"""Process-local dump protection: real native state, synthetic crypto effects.

No host sysctl, crash collector, actual mapper, production credential or key
payload is read/changed. The real syscall test is confined to a child process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_creation_disables_dumpability_before_any_crypto_library_work():
    child = r'''
import ctypes, json, os, stat
from types import SimpleNamespace
from scripts.security.fr06c5_memory_mapper import LinuxMapperKernel
import scripts.security.fr06c5_memory_mapper as m
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
libc.prctl.restype = ctypes.c_int
assert libc.prctl(3, 0, 0, 0, 0) == 1
observed = []
def observe(stage):
    observed.append([stage, libc.prctl(3, 0, 0, 0, 0)])
class FakeCrypto:
    def crypt_init(self, context, path):
        observe('init'); context._obj.value = 17; return 0
    def crypt_set_log_callback(self, *args): pass
    def crypt_format(self, *args): observe('format'); return 0
    def crypt_activate_by_volume_key(self, context, name, pointer, size, flags):
        assert isinstance(pointer, ctypes.c_void_p) and size == 64
        observe('activate'); return 0
    def crypt_free(self, *args): observe('free')
k = LinuxMapperKernel()
m.os.geteuid = lambda: 0
m.os.fstat = lambda fd: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(7, 3))
k.sample = lambda op: SimpleNamespace(mapper=None)
def library():
    observe('library'); return FakeCrypto()
k._library = library
k.create(10, 3, 16384, '11111111-1111-4111-8111-111111111111')
observe('after')
print(json.dumps({'observed': observed, 'key_payload_exported': False, 'kernel_mapper_created': False}))
'''
    result = subprocess.run(
        [sys.executable, "-c", child], cwd=ROOT, capture_output=True, text=True,
        timeout=15, check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["observed"] == [[name, 0] for name in ("library", "init", "format", "activate", "free", "after")]
    assert not report["key_payload_exported"] and not report["kernel_mapper_created"]



def _failure_boundary(monkeypatch, failure):
    import stat
    from types import SimpleNamespace

    import scripts.security.fr06c5_memory_mapper as mapper
    import scripts.security.fr06c5_memory_volatile_key as volatile

    events = []

    class Prctl:
        def __call__(self, option, *args):
            assert args == (0, 0, 0, 0)
            events.append("set-dumpable" if option == 4 else "get-dumpable")
            if option == 4:
                return -1 if failure == "set-denied" else 0
            if failure == "get-denied":
                return -1
            return 1 if failure == "still-dumpable" else 0

    reads = 0

    def get_limit(which):
        nonlocal reads
        reads += 1
        assert which == volatile.resource.RLIMIT_CORE
        return (1024 if reads == 1 or failure == "limit-not-changed" else 0, 1024)

    def set_limit(which, value):
        assert which == volatile.resource.RLIMIT_CORE and value == (0, 1024)
        events.append("set-core-limit")
        if failure == "limit-denied":
            raise OSError("Synthetic denied process limit")

    monkeypatch.setattr(volatile.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=Prctl()))
    monkeypatch.setattr(volatile.resource, "getrlimit", get_limit)
    monkeypatch.setattr(volatile.resource, "setrlimit", set_limit)
    monkeypatch.setattr(mapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(mapper.os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(7, 3)))
    kernel = mapper.LinuxMapperKernel()
    monkeypatch.setattr(kernel, "sample", lambda operation: SimpleNamespace(mapper=None))

    def forbidden_library():
        events.append("crypto-library")
        raise AssertionError("Crypto initialized before protection was verified")

    monkeypatch.setattr(kernel, "_library", forbidden_library)
    return kernel, events, volatile


@pytest.mark.parametrize("failure", ["set-denied", "get-denied", "still-dumpable", "limit-denied", "limit-not-changed"])
def test_protection_failure_prevents_crypto_and_key_generation(monkeypatch, failure):
    kernel, events, volatile = _failure_boundary(monkeypatch, failure)
    with pytest.raises((volatile.VolatileKeyRejected, OSError)):
        kernel.create(10, 3, 16384, "11111111-1111-4111-8111-111111111111")
    assert "crypto-library" not in events
    assert events[0] == "set-dumpable"
    if failure == "set-denied":
        assert events == ["set-dumpable"]


def test_both_process_protections_are_verified_without_global_settings(monkeypatch):
    _, events, volatile = _failure_boundary(monkeypatch, None)
    volatile.disable_process_dumps()
    assert events == ["set-dumpable", "get-dumpable", "set-core-limit"]
