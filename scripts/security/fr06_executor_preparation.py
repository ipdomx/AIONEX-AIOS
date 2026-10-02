"""Create-only inert FR-06 executor package; NOT an installer or authority issuer.

This is the preparation half of initial installation. It copies ONLY six exact
Git blobs into a private non-executable package. No installed launcher, live
execution.lock, enrollment.json, bootstrap-evidence.json, source ref, service,
provider, maintenance record or old run result is created or changed here.

A complete package is still UNACCEPTED SOURCE: protected source review,
independent live installation, authentic role adoption and historical-effect
reconciliation are mandatory separate operations. No CLI can activate it.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

SCHEMA = 'aionex.fr06-inert-executor-package.v1'
PAYLOAD = {
    'fr06_execution_guard.py': ('scripts/security/fr06_execution_guard.py', '100644'),
    'fr06_execution_enrollment.py': ('scripts/security/fr06_execution_enrollment.py', '100644'),
    'fr06_source_operator.py': ('scripts/security/fr06_source_operator.py', '100644'),
    'aionex-fr06-primary': ('deploy/bin/aionex-fr06-primary', '100755'),
    'aionex-fr06-watchdog': ('deploy/bin/aionex-fr06-watchdog', '100755'),
    'aionex-fr06-interactive': ('deploy/bin/aionex-fr06-interactive', '100755'),
}
MAX_FILE = 256 * 1024
MAX_TOTAL = 1024 * 1024
PACKAGE_MODE = 0o400
FALSE_CLAIMS = {
    'installed': False, 'enrolled': False, 'exclusive_execution_accepted': False,
    'historical_effects_reconciled': False, 'production_activation_authorized': False,
}


class PreparationBlocked(RuntimeError):
    pass


def need(ok: bool, reason: str) -> None:
    if not ok:
        raise PreparationBlocked(reason)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _pairs(items: list[tuple]) -> dict:
    result = {}
    for key, value in items:
        need(key not in result, 'duplicate package key')
        result[key] = value
    return result


def decode(raw: bytes) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise PreparationBlocked('invalid package JSON') from exc
    need(isinstance(value, dict) and canon(value) == raw, 'noncanonical package record')
    return value


def valid_identity(commit: str, operation_id: str) -> None:
    need(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit) is not None,
         'exact source commit required')
    try:
        valid = isinstance(operation_id, str) and str(UUID(operation_id)) == operation_id
    except (ValueError, AttributeError):
        valid = False
    need(valid, 'canonical preparation UUID required')


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino, a.st_mode, a.st_uid, a.st_gid, a.st_nlink, a.st_size,
            a.st_mtime_ns, a.st_ctime_ns) == (
            b.st_dev, b.st_ino, b.st_mode, b.st_uid, b.st_gid, b.st_nlink, b.st_size,
            b.st_mtime_ns, b.st_ctime_ns)


@contextmanager
def _root(path: Path, *, private: bool):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'absolute normalized root required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = child
            info = os.fstat(fd)
            # Root-owned sticky ancestors such as /tmp do not authorize a
            # writable package root; that root must separately be owner-private.
            need(info.st_uid in {0, os.geteuid()} and
                 (not info.st_mode & 0o022 or (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)),
                 'untrusted directory ancestor')
        info = os.fstat(fd)
        if private:
            need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                 'preexisting private root required')
        yield fd
        if private:
            _private_directory(fd)
        current = os.stat(path, follow_symlinks=False)
        need((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino) and
             stat.S_ISDIR(current.st_mode), 'root identity changed')
    finally:
        os.close(fd)


def _read(directory: int, name: str, mode: int | None = None) -> bytes:
    need('/' not in name and name not in {'', '.', '..'}, 'fixed leaf name required')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory)
    try:
        initial = os.fstat(fd)
        need(stat.S_ISREG(initial.st_mode) and initial.st_uid == os.geteuid()
             and initial.st_nlink == 1 and 0 < initial.st_size <= MAX_FILE,
             'unsafe package file')
        need(mode is None or stat.S_IMODE(initial.st_mode) == mode, 'package file mode differs')
        value = bytearray()
        while len(value) <= initial.st_size:
            chunk = os.read(fd, min(65536, initial.st_size + 1 - len(value)))
            if not chunk:
                break
            value.extend(chunk)
        final = os.fstat(fd)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        need(len(value) == initial.st_size and _same(initial, final) and _same(final, named),
             'file changed during observation')
        return bytes(value)
    finally:
        os.close(fd)


def _git(root: Path, *args: str) -> bytes:
    # Fixed read-only Git verbs below. Do not inherit GIT_DIR, alternate indexes,
    # command-scope configuration or credentials from the operator environment.
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_OPTIONAL_LOCKS': '0'}
    result = subprocess.run(['/usr/bin/git', '-C', str(root), *args], env=env,
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    need(result.returncode == 0 and len(result.stdout) <= MAX_TOTAL, 'source Git read failed')
    return result.stdout


def collect_source(root: Path, commit: str) -> dict[str, bytes]:
    need(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit) is not None, 'exact source commit required')
    with _root(root, private=False):
        need(_git(root, 'rev-parse', '--show-toplevel').decode().strip() == str(root), 'wrong source root')
        need(_git(root, 'rev-parse', 'HEAD').decode().strip() == commit, 'source HEAD differs')
        result = {}
        for name, (rel, mode) in PAYLOAD.items():
            entry = _git(root, 'ls-tree', commit, '--', rel).decode().strip()
            need(entry.startswith(mode + ' blob ') and entry.endswith('\t' + rel), 'tracked payload mode differs')
            blob = _git(root, 'cat-file', 'blob', commit + ':' + rel)
            need(0 < len(blob) <= MAX_FILE, 'payload size exceeds bound')
            with _root(root / Path(rel).parent, private=False) as directory:
                actual = _read(directory, Path(rel).name, int(mode[-3:], 8))
            need(actual == blob, 'source payload differs from exact Git blob')
            result[name] = blob
        need(sum(map(len, result.values())) <= MAX_TOTAL, 'payload total exceeds bound')
        need(_git(root, 'rev-parse', 'HEAD').decode().strip() == commit, 'source changed during capture')
        return result


def _write_new(directory: int, name: str, raw: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 PACKAGE_MODE, dir_fd=directory)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            need(written > 0, 'short preparation write')
            offset += written
        os.fchmod(fd, PACKAGE_MODE)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(directory)


def _manifest(commit: str, operation_id: str, payload: dict[str, bytes]) -> dict:
    return {'schema': SCHEMA, 'operation_id': operation_id, 'source_commit': commit,
            'purpose': 'inert_source_preparation_only', **FALSE_CLAIMS,
            'files': {n: {'source_path': PAYLOAD[n][0], 'git_mode': PAYLOAD[n][1],
                          'stored_mode': '0400', 'bytes': len(raw), 'sha256': digest(raw)}
                      for n, raw in sorted(payload.items())}}


def _private_directory(fd: int) -> tuple[int, int]:
    s = os.fstat(fd)
    need(stat.S_ISDIR(s.st_mode) and s.st_uid == os.geteuid() and stat.S_IMODE(s.st_mode) == 0o700,
         'package directory not owner-private')
    return s.st_dev, s.st_ino


def _child(parent: int, name: str) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        _private_directory(fd)
        return fd
    except Exception:
        os.close(fd)
        raise


def prepare(*, source_root: Path, source_commit: str, store: Path, operation_id: str) -> dict:
    valid_identity(source_commit, operation_id)
    payload = collect_source(source_root, source_commit)
    manifest = _manifest(source_commit, operation_id, payload)
    with _root(store, private=True) as base:
        # mkdir is the exclusive create-only claim. It is NEVER adopted after
        # an exception, crash, timeout or old heartbeat; partial state is kept.
        os.mkdir(operation_id, mode=0o700, dir_fd=base)
        os.fsync(base)
        package = _child(base, operation_id)
        try:
            fcntl.flock(package, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _write_new(package, 'intent.json', canon(manifest))
            os.mkdir('payload', mode=0o700, dir_fd=package); os.fsync(package)
            files = _child(package, 'payload')
            files_identity = _private_directory(files)
            try:
                for name, raw in sorted(payload.items()):
                    _write_new(files, name, raw)
                need(set(os.listdir(files)) == set(PAYLOAD), 'unexpected payload entry')
                need(all(_read(files, n, PACKAGE_MODE) == raw for n, raw in payload.items()),
                     'staged payload changed')
            finally:
                os.close(files)
            need(collect_source(source_root, source_commit) == payload, 'source changed while preparing')
            need(set(os.listdir(package)) == {'intent.json', 'payload'}, 'unexpected preparation entry')
            need(_read(package, 'intent.json', PACKAGE_MODE) == canon(manifest), 'intent changed')
            named = os.stat(operation_id, dir_fd=base, follow_symlinks=False)
            need((named.st_dev, named.st_ino) == (os.fstat(package).st_dev, os.fstat(package).st_ino),
                 'package directory replaced')
            # Revalidate permissions AND directory identities immediately before
            # publishing the readable-complete marker, not only on inspection.
            _private_directory(base); _private_directory(package)
            with _root(store, private=True) as fresh_base:
                need(_private_directory(fresh_base) == _private_directory(base), 'store replaced before marker')
            fresh_files = _child(package, 'payload')
            try:
                need(_private_directory(fresh_files) == files_identity, 'payload directory replaced')
                need(set(os.listdir(fresh_files)) == set(PAYLOAD) and
                     all(_read(fresh_files, n, PACKAGE_MODE) == raw for n, raw in payload.items()),
                     'payload changed before marker')
            finally:
                os.close(fresh_files)
            ready = {'schema': SCHEMA, 'operation_id': operation_id, 'source_commit': source_commit,
                     'manifest_sha256': digest(canon(manifest)), 'status': 'prepared_not_installed', **FALSE_CLAIMS}
            _write_new(package, 'ready.json', canon(ready))
        finally:
            os.close(package)
    return inspect_package(source_root=source_root, source_commit=source_commit, store=store, operation_id=operation_id)


def inspect_package(*, source_root: Path, source_commit: str, store: Path, operation_id: str) -> dict:
    valid_identity(source_commit, operation_id)
    expected = collect_source(source_root, source_commit)
    manifest = _manifest(source_commit, operation_id, expected)
    with _root(store, private=True) as base:
        package = _child(base, operation_id)
        try:
            fcntl.flock(package, fcntl.LOCK_SH | fcntl.LOCK_NB)
            need(set(os.listdir(package)) == {'intent.json', 'payload', 'ready.json'}, 'package incomplete or unexpected')
            need(_read(package, 'intent.json', PACKAGE_MODE) == canon(manifest), 'manifest not bound to source')
            ready_raw = _read(package, 'ready.json', PACKAGE_MODE)
            ready = decode(ready_raw)
            target = {'schema': SCHEMA, 'operation_id': operation_id, 'source_commit': source_commit,
                      'manifest_sha256': digest(canon(manifest)), 'status': 'prepared_not_installed', **FALSE_CLAIMS}
            need(ready == target and ready_raw == canon(target), 'prepared receipt differs')
            files = _child(package, 'payload')
            try:
                need(set(os.listdir(files)) == set(PAYLOAD), 'payload file set differs')
                need(all(_read(files, n, PACKAGE_MODE) == raw for n, raw in expected.items()),
                     'payload is not exact reviewed-source candidate')
            finally:
                os.close(files)
            named = os.stat(operation_id, dir_fd=base, follow_symlinks=False)
            need((named.st_dev, named.st_ino) == (os.fstat(package).st_dev, os.fstat(package).st_ino),
                 'package name replaced')
            need(_read(package, 'ready.json', PACKAGE_MODE) == ready_raw, 'ready record changed')
        finally:
            os.close(package)
    need(collect_source(source_root, source_commit) == expected, 'source changed while inspecting')
    return {**target, 'files_verified': len(expected), 'staged_payload_executable': False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'inspect'])
    p.add_argument('--source-root', required=True, type=Path)
    p.add_argument('--source-commit', required=True)
    p.add_argument('--store', required=True, type=Path)
    p.add_argument('--operation-id', required=True)
    args = vars(p.parse_args()); action = args.pop('action')
    try:
        print(json.dumps((prepare if action == 'prepare' else inspect_package)(**args), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'blocked_or_incomplete', 'automatic_retry': False, **FALSE_CLAIMS}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
