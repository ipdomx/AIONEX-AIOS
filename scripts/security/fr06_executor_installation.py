"""Initial two-root file publication, WITHOUT enrollment or execution authority.

This library is the publication half of fr06_executor_preparation. It copies
three exact launchers and a fresh empty lock/receipts directory, journals every
namespace effect, and never replaces, adopts, resumes or automatically removes
an earlier attempt. No CLI, default approval, source merge/sync, role enrollment,
service/provider operation or historical-run reconciliation is supplied.

The mandatory authorize callback belongs to a SEPARATELY accepted initial-install
operator: it must validate protected source acceptance, the actual initial-install
window and exclusive ownership independently of these files. A Binding returned
by a test callback is not that evidence. This engine cannot authorize itself.
"""
from __future__ import annotations

import ctypes
import fcntl
import os
import stat
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from scripts.security import fr06_executor_preparation as preparation
from scripts.security.fr06_execution_guard import Binding

SCHEMA = 'aionex.fr06-unenrolled-installation.v1'
ROUTES = ('aionex-fr06-primary', 'aionex-fr06-watchdog', 'aionex-fr06-interactive')
NO_AUTHORITY = {
    'enrolled': False, 'exclusive_execution_accepted': False,
    'historical_effects_reconciled': False, 'production_activation_authorized': False,
}


class InstallationBlocked(RuntimeError):
    pass


def need(ok: bool, message: str) -> None:
    if not ok:
        raise InstallationBlocked(message)


def _ident(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _parent(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
         and stat.S_IMODE(info.st_mode) in (0o700, 0o755), 'unsafe installation parent')
    return _ident(fd)


def _directory(parent: int, name: str, mode: int) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        st = os.fstat(fd)
        need(st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == mode,
             'installation directory metadata differs')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _absent(fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise InstallationBlocked('existing installation cannot be adopted or replaced')


def _file(parent: int, name: str, data: bytes, mode: int) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=parent)
    try:
        offset = 0
        while offset < len(data):
            n = os.write(fd, data[offset:])
            need(n > 0, 'installation write stalled')
            offset += n
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(parent)


def _record(fd: int, name: str, value: dict) -> None:
    _file(fd, name, preparation.canon(value), 0o400)


def _rename_no_replace(source_fd: int, source: str, destination_fd: int, destination: str) -> None:
    """One native atomic namespace operation; no fallback or silent overwrite."""
    lib = ctypes.CDLL(None, use_errno=True)
    fn = getattr(lib, 'renameat2', None)
    need(fn is not None, 'atomic no-replace rename is unavailable')
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(source_fd, os.fsencode(source), destination_fd, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    os.fsync(source_fd)
    os.fsync(destination_fd)


def _snapshot_file(directory: int, name: str, expected: bytes, mode: int) -> dict:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
             and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == mode
             and before.st_size == len(expected), 'installation file metadata differs')
        actual = bytearray()
        while len(actual) < len(expected) + 1:
            part = os.read(fd, min(65536, len(expected) + 1 - len(actual)))
            if not part:
                break
            actual.extend(part)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        need(bytes(actual) == expected and preparation._same(before, after)
             and preparation._same(after, named), 'installation file changed')
        return {'device': before.st_dev, 'inode': before.st_ino,
                'mode': mode, 'bytes': len(expected), 'sha256': preparation.digest(expected)}
    finally:
        os.close(fd)


def _snapshot(fd: int, kind: str, payload: dict[str, bytes]) -> dict:
    info = os.fstat(fd)
    mode = 0o700 if kind == 'guard' else 0o755
    need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == mode,
         'candidate root metadata differs')
    expected = {'execution.lock', 'receipts'} if kind == 'guard' else set(ROUTES)
    need(set(os.listdir(fd)) == expected, 'unexpected installation entry or enrollment')
    if kind == 'guard':
        file_info = {'execution.lock': _snapshot_file(fd, 'execution.lock', b'', 0o600)}
        receipt_fd = _directory(fd, 'receipts', 0o700)
        try:
            need(os.listdir(receipt_fd) == [], 'fresh receipts directory is not empty')
            receipts = _ident(receipt_fd)
        finally:
            os.close(receipt_fd)
    else:
        file_info = {name: _snapshot_file(fd, name, payload[name], 0o755) for name in ROUTES}
        receipts = None
    return {'root': list(_ident(fd)), 'mode': mode, 'files': file_info,
            'receipts': list(receipts) if receipts is not None else None}


def _authority(authorize: Callable[[], Binding], binding: Binding) -> None:
    need(callable(authorize), 'independent initial-install authority reader required')
    live = authorize()
    need(type(live) is Binding and type(binding) is Binding, 'typed current binding required')
    live.validate(); binding.validate()
    need(asdict(live) == asdict(binding), 'source, boot or maintenance authority changed')


def _target(path: Path) -> Path:
    need(isinstance(path, Path) and path.is_absolute() and '..' not in path.parts
         and path.name not in ('', '.', '..'), 'absolute installation target required')
    return path


def install_unenrolled(*, source_root: Path, source_commit: str, store: Path,
                       preparation_id: str, journal: Path, operation_id: str,
                       guard_root: Path, launch_root: Path, binding: Binding,
                       authorize: Callable[[], Binding]) -> dict:
    """Publish only files; the caller must supply independent installation admission.

    The dedicated journal root is single-use even for a different operation UUID.
    Exceptions retain both partial files and intent. A new invocation NEVER infers
    no effect from old timestamps, missing PIDs, a free flock or an absent receipt.
    No exception handler performs rollback, retry or historical reconciliation.
    """
    preparation.valid_identity(source_commit, operation_id)
    preparation.valid_identity(source_commit, preparation_id)
    _authority(authorize, binding)
    need(binding.source_commit == source_commit, 'package source and admitted source differ')
    paths = [source_root, store, journal, _target(guard_root), _target(launch_root)]
    for i, p in enumerate(paths):
        _target(p)
        for q in paths[:i]:
            need(p != q and not p.is_relative_to(q) and not q.is_relative_to(p),
                 'installation roots must not overlap')
    package = preparation.inspect_package(source_root=source_root, source_commit=source_commit,
                                          store=store, operation_id=preparation_id)
    payload = preparation.collect_source(source_root, source_commit)
    with ExitStack() as stack:
        log = stack.enter_context(preparation._root(journal, private=True))
        fcntl.flock(log, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parents = {kind: stack.enter_context(preparation._root(path.parent, private=False))
                   for kind, path in (('guard', guard_root), ('launch', launch_root))}
        parent_ids = {kind: _parent(fd) for kind, fd in parents.items()}
        need(all(device == _ident(log)[0] for device, _ in parent_ids.values()),
             'publication requires one filesystem; no copy fallback')
        need(os.listdir(log) == [], 'initial installation journal already claimed')
        for kind, target in (('guard', guard_root), ('launch', launch_root)):
            _absent(parents[kind], target.name)
        _authority(authorize, binding)
        intent = {'schema': SCHEMA, 'operation_id': operation_id, 'preparation_id': preparation_id,
                  'manifest_sha256': package['manifest_sha256'], 'binding': asdict(binding),
                  'guard_root': str(guard_root), 'launch_root': str(launch_root),
                  'status': 'initial_install_intent', **NO_AUTHORITY}
        _record(log, 'intent.json', intent)
        candidates = {}
        for kind, mode in (('guard', 0o700), ('launch', 0o755)):
            name = kind + '-candidate'
            os.mkdir(name, 0o700, dir_fd=log); os.fsync(log)
            fd = _directory(log, name, 0o700)
            try:
                if kind == 'guard':
                    _file(fd, 'execution.lock', b'', 0o600)
                    os.mkdir('receipts', 0o700, dir_fd=fd); os.fsync(fd)
                else:
                    for route in ROUTES:
                        _file(fd, route, payload[route], 0o755)
                os.fchmod(fd, mode); os.fsync(fd)
                candidates[kind] = _snapshot(fd, kind, payload)
            finally:
                os.close(fd)
        candidate_record = {'schema': SCHEMA, 'operation_id': operation_id, 'objects': candidates}
        _record(log, 'candidates.json', candidate_record)
        records = {'intent.json': intent, 'candidates.json': candidate_record}
        published = {}

        def write_record(name: str, value: dict) -> None:
            _record(log, name, value)
            records[name] = value

        def recheck() -> None:
            _authority(authorize, binding)
            need(preparation.inspect_package(source_root=source_root, source_commit=source_commit,
                 store=store, operation_id=preparation_id) == package, 'source package changed')
            preparation._private_directory(log)
            with preparation._root(journal, private=True) as current:
                need(_ident(current) == _ident(log), 'journal root replaced')
            for kind, path in (('guard', guard_root), ('launch', launch_root)):
                need(_parent(parents[kind]) == parent_ids[kind], 'target parent changed')
                with preparation._root(path.parent, private=False) as current:
                    need(_parent(current) == parent_ids[kind], 'target parent path replaced')
            for name, value in records.items():
                need(preparation._read(log, name, 0o400) == preparation.canon(value),
                     'installation journal changed')
            # Recheck BOTH objects after the durable intent and authorization
            # read, not just before them. A callback interruption or concurrent
            # path change must not publish unverified bytes or a different inode.
            for kind, target in (('guard', guard_root), ('launch', launch_root)):
                parent = parents[kind] if kind in published else log
                name = target.name if kind in published else kind + '-candidate'
                fd = _directory(parent, name, candidates[kind]['mode'])
                try:
                    need(_snapshot(fd, kind, payload) == candidates[kind],
                         'candidate or installed object changed before next effect')
                finally:
                    os.close(fd)

        for ordinal, (kind, target) in enumerate((('guard', guard_root), ('launch', launch_root)), 1):
            recheck()
            for prior_kind, prior_target in published.items():
                fd = _directory(parents[prior_kind], prior_target.name, candidates[prior_kind]['mode'])
                try:
                    need(_snapshot(fd, prior_kind, payload) == candidates[prior_kind],
                         'previously published root changed')
                finally:
                    os.close(fd)
            candidate_name = kind + '-candidate'
            fd = _directory(log, candidate_name, candidates[kind]['mode'])
            try:
                need(_snapshot(fd, kind, payload) == candidates[kind], 'candidate identity changed')
            finally:
                os.close(fd)
            _absent(parents[kind], target.name)
            record = {'schema': SCHEMA, 'operation_id': operation_id, 'kind': kind,
                      'objects': candidates[kind], **NO_AUTHORITY}
            write_record(f'{ordinal}-{kind}-intent.json', record)
            recheck()
            _rename_no_replace(log, candidate_name, parents[kind], target.name)
            published[kind] = target
            fd = _directory(parents[kind], target.name, candidates[kind]['mode'])
            try:
                need(_snapshot(fd, kind, payload) == candidates[kind], 'published identity differs')
            finally:
                os.close(fd)
            recheck()
            write_record(f'{ordinal}-{kind}-observed.json', record)
        recheck()
        for kind, target in published.items():
            fd = _directory(parents[kind], target.name, candidates[kind]['mode'])
            try:
                need(_snapshot(fd, kind, payload) == candidates[kind], 'final installation differs')
            finally:
                os.close(fd)
        expected = {'intent.json', 'candidates.json', '1-guard-intent.json', '1-guard-observed.json',
                    '2-launch-intent.json', '2-launch-observed.json'}
        need(set(os.listdir(log)) == expected, 'unexpected installation journal entry')
        result = {'schema': SCHEMA, 'operation_id': operation_id, 'source_commit': source_commit,
                  'status': 'files_installed_unenrolled', 'objects': candidates, **NO_AUTHORITY}
        _record(log, 'files-installed.json', result)
    return result
