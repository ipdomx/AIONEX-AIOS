"""Official package-floor, bounded allocator and build-integration contracts.

These tests never load the PCRE2 library or execute a customer's expression.
Native before/after acceptance is kept separately in the isolated-image proof.
"""
from __future__ import annotations

import ctypes
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'web-dashboard/backend/scripts/verify_security_pcre2.py'
spec = importlib.util.spec_from_file_location('pcre2_verifier_contract', FILE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def package_fixture(tmp_path, monkeypatch):
    directory = tmp_path / 'lib'
    directory.mkdir()
    library = directory / 'libpcre2-8.so.0'
    library.write_bytes(b'synthetic library identity only')
    monkeypatch.setattr(m, 'LIBRARY', library)
    responses = {'query_rc': 0, 'query': 'libpcre2-8-0\t10.42-1+deb12u1\tamd64\tii ',
                 'compare_rc': 0, 'verify_rc': 0, 'verify': ''}
    commands = []

    def invoke(args, *, input_text=None):
        commands.append(args)
        if args[0] == 'dpkg-query':
            return subprocess.CompletedProcess(args, responses['query_rc'], responses['query'], '')
        if '--compare-versions' in args:
            return subprocess.CompletedProcess(args, responses['compare_rc'], '', '')
        assert args == ['dpkg', '--verify', 'libpcre2-8-0']
        return subprocess.CompletedProcess(args, responses['verify_rc'], responses['verify'], '')

    monkeypatch.setattr(m, 'run', invoke)
    return library, responses, commands


def test_real_floor_passed_to_dpkg_and_installed_bytes_hashed(package_fixture):
    library, _, commands = package_fixture
    result = m.package_identity()
    assert result['package'] == 'libpcre2-8-0'
    assert result['library_sha256'] == m.hashlib.sha256(library.read_bytes()).hexdigest()
    assert ['dpkg', '--compare-versions', '10.42-1+deb12u1', 'ge', '10.42-1+deb12u1'] in commands
    assert commands[-1] == ['dpkg', '--verify', 'libpcre2-8-0']


@pytest.mark.parametrize('query', ['', 'wrong-package\t10.42-1+deb12u1\tamd64\tii ',
    'libpcre2-8-0\t10.42-1+deb12u1\tarm64\tii ', 'libpcre2-8-0\t10.42-1+deb12u1\tamd64\tiU ',
    'libpcre2-8-0\t10.42-1+deb12u1\tamd64', 'libpcre2-8-0\t10.42-1+deb12u1\tamd64\tii \textra'])
def test_unaccepted_package_metadata_stops_before_library_load(package_fixture, query):
    _, responses, commands = package_fixture
    responses['query'] = query
    with pytest.raises(RuntimeError):
        m.package_identity()
    assert len(commands) == 1


@pytest.mark.parametrize('fault', ['query-failure', 'below-floor', 'comparator-failure', 'changed-file', 'verify-failure'])
def test_package_or_integrity_failure_never_yields_acceptance(package_fixture, fault):
    _, responses, _ = package_fixture
    if fault == 'query-failure':
        responses['query_rc'] = 1
    elif fault == 'below-floor':
        responses['query'] = 'libpcre2-8-0\t10.42-1\tamd64\tii '
        responses['compare_rc'] = 1
    elif fault == 'comparator-failure':
        responses['compare_rc'] = 2
    elif fault == 'changed-file':
        responses['verify'] = '??5?????? /usr/lib/libpcre2.so\n'
    else:
        responses['verify_rc'] = 1
    with pytest.raises(RuntimeError):
        m.package_identity()


def test_library_symlink_outside_accepted_directory_is_rejected(package_fixture, tmp_path):
    library, _, _ = package_fixture
    outside = tmp_path / 'outside-library'
    outside.write_bytes(b'not accepted')
    library.unlink()
    library.symlink_to(outside)
    with pytest.raises(RuntimeError, match='location'):
        m.package_identity()


def test_guarded_allocator_normal_lifecycle_has_no_leak():
    heap = m.GuardedHeap()
    pointer = heap.allocate(64, 0)
    assert pointer
    ctypes.memset(pointer, 0x11, 64)
    heap.release(pointer, 0)
    assert not any(heap.finish().values())


def test_guard_corruption_is_observed_within_reserved_allocation():
    heap = m.GuardedHeap()
    pointer = heap.allocate(16, 0)
    assert pointer
    ctypes.memset(pointer + 16, 0, 1)  # Allocated canary area, not an actual overflow.
    heap.release(pointer, 0)
    assert heap.finish() == {'invalid_frees': 0, 'overruns': 1, 'unreleased_blocks': 0, 'denied_allocations': 0}


def test_unknown_free_is_recorded_without_freeing_external_memory():
    heap = m.GuardedHeap()
    external = ctypes.create_string_buffer(b'synthetic')
    heap.release(ctypes.addressof(external), 0)
    assert external.value == b'synthetic'
    assert heap.finish()['invalid_frees'] == 1


def test_unreleased_blocks_are_recorded_then_physically_released():
    heap = m.GuardedHeap()
    assert heap.allocate(32, 0)
    assert heap.finish()['unreleased_blocks'] == 1
    assert heap.blocks == {}


@pytest.mark.parametrize('size', [0, -1, 4 * 1024 * 1024 + 1])
def test_oversized_or_invalid_allocations_are_not_attempted(size):
    heap = m.GuardedHeap()
    assert heap.allocate(size, 0) is None
    assert heap.finish()['denied_allocations'] == 1


def test_allocator_block_count_is_bounded(monkeypatch):
    heap = m.GuardedHeap()
    monkeypatch.setattr(heap, 'MAX_BLOCKS', 1)
    first = heap.allocate(16, 0)
    assert first
    assert heap.allocate(16, 0) is None
    heap.release(first, 0)
    assert heap.finish()['denied_allocations'] == 1


def test_unrecognized_expression_case_cannot_reach_native_library():
    with pytest.raises(ValueError):
        m.native_case('user-provided-pattern')


def test_build_upgrades_official_package_and_retains_complete_integrity_check():
    dockerfile = (ROOT / 'web-dashboard/backend/Dockerfile.security-tools').read_text()
    runtime = dockerfile.split(' AS runtime\n', 1)[1]
    assert 'unzip libpcre2-8-0' in runtime
    assert "ge '10.42-1+deb12u1'" in runtime
    assert 'zz-aios-pcre2-integrity' in runtime
    assert 'path-include=/usr/share/doc/libpcre2-8-0/*' in runtime
    assert runtime.index('USER 1000:1000') < runtime.index('RUN python /app/scripts/verify_security_pcre2.py')
    for prohibited in ['--allow-unauthenticated', 'AllowInsecureRepositories', 'trusted=yes', '--force-yes']:
        assert prohibited not in runtime


def test_native_acceptance_keeps_both_regressions_and_explicit_scope_limits():
    assert len(m.CASES) == 11 and len(set(m.CASES)) == 11
    assert {'dfa-heap-limit', 'jit-copied-subject', 'grep-cli', 'nmap-cli'} <= set(m.CASES)
    assert m.TARGET_CVES == ('CVE-2026-86145', 'CVE-2026-89157', 'CVE-2026-89161')
    source = FILE.read_text()
    assert 'huge_pattern_32bit_cve_not_reproduced' in source
    assert '"full_image_security_passed": False' in source
    assert '"asan_claimed": False' in source
    assert 'resource.RLIMIT_CORE' in source and 'libc.prctl(4, 0, 0, 0, 0)' in source
    assert 'dpkg", "--verify"' in source
