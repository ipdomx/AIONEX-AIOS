"""Real disposable flock loss at executor effect boundaries; no live effects."""
from __future__ import annotations

import fcntl
import json
import os
import stat
from pathlib import Path

import pytest
from scripts.security import fr06_execution_guard as g
from scripts.security import fr06_execution_enrollment as e

SOURCE = '7' * 40
TARGET = '8' * 40
BINDING = g.Binding(SOURCE, SOURCE, '00000000-0000-4000-8000-000000000001',
                    '00000000-0000-4000-8000-000000000002', 41, True, 'closed')
RESULT = g.ObservedResult('observed_complete', '9' * 64)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / 'owned-guard'
    path.mkdir(mode=0o700)
    return path


def rows(root):
    path = root / 'effects.jsonl'
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def lose(fd, other, fault):
    if fault == 'shared':
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        if fault == 'other_description':
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('role', ['interactive', 'scheduled', 'watchdog'])
@pytest.mark.parametrize('phase', ['before_call', 'first_observation', 'second_observation', 'effect_return'])
@pytest.mark.parametrize('fault', ['unlocked', 'shared', 'other_description'])
def test_effect_boundaries_reject_lost_own_flock(root, role, phase, fault):
    effect = root.parent / 'disposable-effect'
    other = None
    try:
        with g.ExecutionGuard(root, run_id='fixture-' + role, invocation_type=role) as guard:
            other = os.open(root / 'execution.lock', os.O_RDWR | os.O_NOFOLLOW)
            observation = [0]
            def observe():
                observation[0] += 1
                if (phase == 'first_observation' and observation[0] == 1
                    or phase == 'second_observation' and observation[0] == 2):
                    lose(guard._lock, other, fault)
                return BINDING
            def invoke():
                effect.write_text('owned fixture only')
                if phase == 'effect_return':
                    lose(guard._lock, other, fault)
                return RESULT
            if phase == 'before_call':
                lose(guard._lock, other, fault)
            with pytest.raises(g.GuardBlocked):
                guard.perform(action='source_merge', target_commit=TARGET,
                              expected=BINDING, observe=observe, invoke=invoke)
            # The check must not silently reacquire or upgrade a lost lock.
            probe = os.open(root / 'execution.lock', os.O_RDWR | os.O_NOFOLLOW)
            try:
                if fault == 'unlocked':
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(probe, fcntl.LOCK_UN)
                elif fault == 'shared':
                    fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    fcntl.flock(probe, fcntl.LOCK_UN)
                else:
                    with pytest.raises(BlockingIOError):
                        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(probe)
    finally:
        if other is not None:
            os.close(other)
    expected_intent = phase in {'second_observation', 'effect_return'}
    assert [r['kind'] for r in rows(root)] == (['intent'] if expected_intent else [])
    assert effect.exists() is (phase == 'effect_return')
    before = (root / 'effects.jsonl').read_bytes()
    with g.ExecutionGuard(root, run_id='later-owner', invocation_type='interactive') as guard:
        assert (guard.pending() is not None) is expected_intent
        if expected_intent:
            with pytest.raises(g.UncertainEffect):
                guard.perform(action='source_merge', target_commit=TARGET, expected=BINDING,
                              observe=lambda: BINDING,
                              invoke=lambda: pytest.fail('uncertain effect was replayed'))
    assert (root / 'effects.jsonl').read_bytes() == before


@pytest.mark.parametrize('fault', ['unlocked', 'shared', 'other_description'])
def test_standalone_enrollment_probe_refuses_loss(root, monkeypatch, fault):
    lock = root / 'execution.lock'
    lock.touch(mode=0o600)
    real_flock = fcntl.flock
    selected = []
    def capture(fd, operation):
        result = real_flock(fd, operation)
        if operation == fcntl.LOCK_EX | fcntl.LOCK_NB and not selected:
            selected.append(fd)
        return result
    monkeypatch.setattr(e.fcntl, 'flock', capture)
    other = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        with pytest.raises(g.GuardBlocked):
            with e.held_probe_lock(root):
                lose(selected[0], other, fault)
    finally:
        os.close(other)
    assert sorted(p.name for p in root.iterdir()) == ['execution.lock']


@pytest.mark.parametrize('fault', ['unlocked', 'shared', 'other_description'])
def test_active_guard_enrollment_probe_refuses_loss(root, fault):
    other = None
    try:
        with g.ExecutionGuard(root, run_id='active-probe', invocation_type='interactive') as guard:
            other = os.open(root / 'execution.lock', os.O_RDWR | os.O_NOFOLLOW)
            with pytest.raises(g.GuardBlocked):
                with e.held_probe_lock(root, active_guard=guard):
                    lose(guard._lock, other, fault)
    finally:
        if other is not None:
            os.close(other)
    assert rows(root) == []


@pytest.mark.parametrize('role', ['interactive', 'scheduled', 'watchdog'])
def test_actual_exclusive_owner_still_completes(root, role):
    with g.ExecutionGuard(root, run_id='valid-' + role, invocation_type=role) as guard:
        result = guard.perform(action='source_merge', target_commit=TARGET,
                               expected=BINDING, observe=lambda: BINDING, invoke=lambda: RESULT)
    assert result['payload']['outcome'] == 'observed_complete'
    assert [r['kind'] for r in rows(root)] == ['intent', 'result']


@pytest.mark.parametrize('operation', ['unlocked', 'shared'])
def test_unproven_acquisition_cannot_create_effect_journal(root, monkeypatch, operation):
    real_flock = fcntl.flock
    def not_exclusive(fd, request):
        if request == fcntl.LOCK_EX | fcntl.LOCK_NB:
            return None if operation == 'unlocked' else real_flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return real_flock(fd, request)
    monkeypatch.setattr(g.fcntl, 'flock', not_exclusive)
    with pytest.raises(g.GuardBlocked):
        with g.ExecutionGuard(root, run_id='fixture-acquisition', invocation_type='interactive'):
            pytest.fail('unproven acquisition entered guard')
    assert not (root / 'effects.jsonl').exists()


@pytest.mark.parametrize('fault', ['absent', 'truncated', 'too_large', 'non_ascii', 'shared',
    'posix', 'ofd', 'mandatory', 'owner', 'major', 'minor', 'inode', 'range',
    'duplicate_lock', 'duplicate_inode', 'different_inode'])
def test_kernel_descriptor_evidence_rejects_malformed_or_foreign_lock(root, fault):
    lock = root / 'execution.lock'; lock.touch(mode=0o600)
    meta = lock.stat(); pid = os.getpid()
    inode = f'ino:\t{meta.st_ino}\n'
    line = (f'lock:\t1: FLOCK ADVISORY WRITE {pid} '
            f'{os.major(meta.st_dev):x}:{os.minor(meta.st_dev):x}:{meta.st_ino} 0 EOF\n')
    raw = (inode + line).encode()
    if fault == 'absent': raw = inode.encode()
    elif fault == 'truncated': raw = raw[:-1]
    elif fault == 'too_large': raw = b'x' * 4097 + b'\n'
    elif fault == 'non_ascii': raw = b'\xff\n'
    elif fault == 'shared': raw = raw.replace(b'WRITE', b'READ')
    elif fault == 'posix': raw = raw.replace(b'FLOCK', b'POSIX')
    elif fault == 'ofd': raw = raw.replace(b'FLOCK', b'OFDLCK')
    elif fault == 'mandatory': raw = raw.replace(b'ADVISORY', b'MANDATORY')
    elif fault == 'owner': raw = raw.replace(f'WRITE {pid} '.encode(), f'WRITE {pid + 1} '.encode())
    elif fault == 'major': raw = raw.replace(f'{os.major(meta.st_dev):x}:'.encode(), b'ffff:')
    elif fault == 'minor': raw = raw.replace(f':{os.minor(meta.st_dev):x}:'.encode(), b':ffff:')
    elif fault == 'inode': raw = raw.replace(f':{meta.st_ino} '.encode(), f':{meta.st_ino + 1} '.encode())
    elif fault == 'range': raw = raw.replace(b' 0 EOF', b' 1 EOF')
    elif fault == 'duplicate_lock': raw += line.encode()
    elif fault == 'duplicate_inode': raw += inode.encode()
    else: raw = raw.replace(inode.encode(), f'ino:\t{meta.st_ino + 1}\n'.encode())
    with pytest.raises(g.GuardBlocked):
        g._verify_owned_flock(raw, meta, pid)


def test_missing_proc_evidence_prevents_journal_creation(root, monkeypatch):
    def denied(fd): raise PermissionError('synthetic unreadable fdinfo')
    monkeypatch.setattr(g, '_read_lock_fdinfo', denied)
    with pytest.raises(g.GuardBlocked, match='unavailable'):
        with g.ExecutionGuard(root, run_id='unavailable-evidence', invocation_type='interactive'):
            pytest.fail('missing evidence accepted')
    assert not (root / 'effects.jsonl').exists()


@pytest.mark.parametrize('short_write', [False, True])
def test_lost_lock_during_journal_write_is_not_reacquired_or_completed(root, monkeypatch, short_write):
    real_write = os.write
    count = [0]
    with g.ExecutionGuard(root, run_id='journal-loss', invocation_type='interactive') as guard:
        def write(fd, data):
            if fd == guard._journal:
                count[0] += 1
                n = real_write(fd, data[:10] if short_write else data)
                fcntl.flock(guard._lock, fcntl.LOCK_UN)
                return n
            return real_write(fd, data)
        monkeypatch.setattr(g.os, 'write', write)
        with pytest.raises(g.GuardBlocked):
            guard.perform(action='source_merge', target_commit=TARGET, expected=BINDING,
                          observe=lambda: BINDING, invoke=lambda: pytest.fail('effect after journal loss'))
    assert count == [1]
    before = (root / 'effects.jsonl').read_bytes()
    if short_write:
        assert len(before) == 10 and not before.endswith(b'\n')
        with pytest.raises(g.GuardBlocked, match='partial'):
            with g.ExecutionGuard(root, run_id='after-partial', invocation_type='watchdog'):
                pass
    else:
        assert [r['kind'] for r in rows(root)] == ['intent']
    assert (root / 'effects.jsonl').read_bytes() == before


@pytest.mark.parametrize('role', ['interactive', 'scheduled', 'watchdog'])
def test_real_child_can_release_inherited_lock_but_parent_never_accepts_it(root, role):
    import subprocess
    import sys
    with g.ExecutionGuard(root, run_id='child-release-' + role, invocation_type=role) as guard:
        result = subprocess.run([sys.executable, '-I', '-c',
            'import fcntl,sys; fcntl.flock(int(sys.argv[1]),fcntl.LOCK_UN)', str(guard._lock)],
            pass_fds=(guard._lock,), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env={'PATH':'/usr/bin:/bin'}, timeout=5)
        assert result.returncode == 0
        with pytest.raises(g.GuardBlocked):
            guard.perform(action='source_merge', target_commit=TARGET, expected=BINDING,
                          observe=lambda: BINDING, invoke=lambda: pytest.fail('effect after child unlock'))
    assert rows(root) == []


def test_genuine_duplicate_open_description_retains_same_owner(root):
    with g.ExecutionGuard(root, run_id='dup-owner', invocation_type='interactive') as guard:
        duplicate = os.dup(guard._lock)
        try:
            g._require_owned_flock(duplicate)
            guard._assert_held()
        finally:
            os.close(duplicate)
        guard.perform(action='source_merge', target_commit=TARGET, expected=BINDING,
                      observe=lambda: BINDING, invoke=lambda: RESULT)
    assert len(rows(root)) == 2
