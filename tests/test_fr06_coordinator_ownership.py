"""Real disposable flock regressions; no permit, key, live install or source write.

Only the installed-path boundary is modeled. Every lock is a real kernel lock
on a pytest-owned empty file. Tests never claim actual three-role adoption.
"""
from __future__ import annotations

import fcntl
import os
import select
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from scripts.security import fr06_executor_native_install as m


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    authority = tmp_path / 'authority'
    authority.mkdir(mode=0o700)
    aid = str(uuid4())
    directory = authority / aid
    directory.mkdir(mode=0o700)
    path = directory / 'coordinator.lock'
    path.touch(mode=0o600)
    monkeypatch.setattr(m, 'AUTHORITY', authority)
    monkeypatch.setattr(m.NativeSession, 'require_installed', lambda self: None)
    with m.NativeSession(aid).hold() as session:
        yield session, path


def test_actual_owned_exclusive_descriptor_is_accepted_without_file_writes(coordinator):
    session, path = coordinator
    before = path.stat()
    assert session.coordinator() == {'device': before.st_dev, 'inode': before.st_ino}
    after = path.stat()
    assert before.st_mtime_ns == after.st_mtime_ns and before.st_mode == after.st_mode


def test_other_open_description_on_same_inode_cannot_impersonate_our_lock(coordinator):
    session, path = coordinator
    fcntl.flock(session.lock_fd, fcntl.LOCK_UN)
    other = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(m.AdmissionBlocked):
            session.coordinator()
    finally:
        os.close(other)


def test_shared_lock_is_not_exclusive_ownership_even_when_child_contends(coordinator):
    session, _ = coordinator
    fcntl.flock(session.lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    with pytest.raises(m.AdmissionBlocked):
        session.coordinator()


def test_unowned_descriptor_to_same_file_is_rejected(coordinator):
    session, path = coordinator
    original = session.lock_fd
    other = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        session.lock_fd = other
        with pytest.raises(m.AdmissionBlocked):
            session.coordinator()
    finally:
        session.lock_fd = original
        os.close(other)


def test_duplicated_descriptor_to_same_owned_description_remains_valid(coordinator):
    session, path = coordinator
    original = session.lock_fd
    duplicate = os.dup(original)
    try:
        session.lock_fd = duplicate
        assert session.coordinator()['inode'] == path.stat().st_ino
    finally:
        session.lock_fd = original
        os.close(duplicate)


@pytest.mark.parametrize('other_holds', [False, True])
def test_loss_after_contention_probe_is_not_accepted_or_reacquired(coordinator, monkeypatch, other_holds):
    session, path = coordinator
    other = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    real = m.subprocess.run
    def lose_after_probe(*args, **kwargs):
        result = real(*args, **kwargs)
        if result.returncode == 73:
            fcntl.flock(session.lock_fd, fcntl.LOCK_UN)
            if other_holds:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return result
    monkeypatch.setattr(m.subprocess, 'run', lose_after_probe)
    try:
        with pytest.raises(m.AdmissionBlocked):
            session.coordinator()
        if not other_holds:
            # A validation failure must not silently reacquire a lost lock.
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(other)


def test_independent_child_holder_does_not_prove_parent_ownership(coordinator):
    session, path = coordinator
    fcntl.flock(session.lock_fd, fcntl.LOCK_UN)
    code = ('import fcntl,os,signal,sys; signal.alarm(8); '
            'f=os.open(sys.argv[1],os.O_RDWR|os.O_NOFOLLOW); '
            'fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); '
            'print("held",flush=True); sys.stdin.buffer.read(1); os.close(f)')
    child = subprocess.Popen([sys.executable, '-I', '-c', code, str(path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env=m.ENV)
    try:
        assert select.select([child.stdout], [], [], 3)[0], 'owned fixture child did not acknowledge'
        assert child.stdout.readline() == b'held\n'
        with pytest.raises(m.AdmissionBlocked):
            session.coordinator()
    finally:
        child.communicate(b'x', timeout=10)
    assert child.returncode == 0


def test_unlocked_descriptor_is_rejected_before_starting_probe_and_not_reacquired(coordinator, monkeypatch):
    session, path = coordinator
    fcntl.flock(session.lock_fd, fcntl.LOCK_UN)
    def forbidden(*args, **kwargs):
        raise AssertionError('an unowned coordinator must be rejected before probing')
    monkeypatch.setattr(m.subprocess, 'run', forbidden)
    with pytest.raises(m.AdmissionBlocked):
        session.coordinator()
    other = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(other)


@pytest.mark.parametrize('error', [FileNotFoundError, PermissionError, OSError])
def test_missing_kernel_ownership_evidence_is_not_silently_accepted(coordinator, monkeypatch, error):
    session, _ = coordinator
    def unavailable(fd):
        raise error('synthetic procfs read refusal')
    monkeypatch.setattr(m, '_read_coordinator_fdinfo', unavailable)
    with pytest.raises(m.AdmissionBlocked, match='unavailable'):
        session.coordinator()


@pytest.mark.parametrize('fault', [
    'absent', 'duplicate', 'shared', 'posix', 'ofd', 'pid', 'major', 'minor',
    'lock_inode', 'fd_inode', 'duplicate_inode', 'waiter', 'range_start',
    'range_end', 'truncated', 'oversized', 'non_ascii',
])
def test_malformed_or_other_kernel_lock_identity_is_rejected(coordinator, monkeypatch, fault):
    session, _ = coordinator
    st = os.fstat(session.lock_fd)
    pid = os.getpid()
    device = f'{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}'
    ino = f'ino:\t{st.st_ino}\n'
    line = f'lock:\t1: FLOCK ADVISORY WRITE {pid} {device}:{st.st_ino} 0 EOF\n'
    prefix = 'pos:\t0\nflags:\t02000002\nmnt_id:\t1\n'
    if fault == 'absent':
        line = ''
    elif fault == 'duplicate':
        line += line
    elif fault == 'shared':
        line = line.replace('WRITE', 'READ')
    elif fault == 'posix':
        line = line.replace('FLOCK', 'POSIX')
    elif fault == 'ofd':
        line = line.replace('FLOCK', 'OFDLCK')
    elif fault == 'pid':
        line = line.replace(f'WRITE {pid} ', f'WRITE {pid+1} ')
    elif fault == 'major':
        line = line.replace(device+':', f'{os.major(st.st_dev)+1:02x}:{os.minor(st.st_dev):02x}:')
    elif fault == 'minor':
        line = line.replace(device+':', f'{os.major(st.st_dev):02x}:{os.minor(st.st_dev)+1:02x}:')
    elif fault == 'lock_inode':
        line = line.replace(f':{st.st_ino} ', f':{st.st_ino+1} ')
    elif fault == 'fd_inode':
        ino = f'ino:\t{st.st_ino+1}\n'
    elif fault == 'duplicate_inode':
        ino += ino
    elif fault == 'waiter':
        line = line.replace('1: FLOCK', '1: -> FLOCK')
    elif fault == 'range_start':
        line = line.replace(' 0 EOF', ' 1 EOF')
    elif fault == 'range_end':
        line = line.replace(' EOF', ' 10')
    raw = (prefix+ino+line).encode()
    if fault == 'truncated':
        raw = raw[:-1]
    elif fault == 'oversized':
        raw = b'x'*4097+b'\n'+raw
    elif fault == 'non_ascii':
        raw += b'\xff\n'
    monkeypatch.setattr(m, '_read_coordinator_fdinfo', lambda fd: raw)
    with pytest.raises(m.AdmissionBlocked):
        session.coordinator()


@pytest.mark.parametrize('fault', ['mode', 'extra_link', 'nonempty'])
def test_held_lock_metadata_drift_is_rejected(coordinator, fault):
    session, path = coordinator
    if fault == 'mode':
        path.chmod(0o644)
    elif fault == 'extra_link':
        os.link(path, path.with_name('fixture-alias'))
    else:
        os.write(session.lock_fd, b'changed')
    with pytest.raises(m.AdmissionBlocked):
        session.coordinator()
