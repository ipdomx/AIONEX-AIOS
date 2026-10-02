"""Real Git/files/flock on disposable owned roots; no production installation.

Payloads are synthetic blobs with the six real fixed filenames. The tests do
not simulate a protected review, live enrollment or historical reconciliation.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import stat
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from scripts.security import fr06_executor_preparation as m


@pytest.fixture
def case(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir(mode=0o700)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': '/dev/null', 'LANG': 'C'}
    def git(*args):
        return subprocess.check_output(['/usr/bin/git', '-C', str(repo), *args], env=env,
                                       stderr=subprocess.PIPE).decode().strip()
    git('init', '-q')
    for name, (rel, mode) in m.PAYLOAD.items():
        p = repo / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# synthetic fixture only: ' + name + '\n')
        p.chmod(int(mode[-3:], 8))
    git('add', '.')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'synthetic fixture')
    store = tmp_path / 'stage'; store.mkdir(mode=0o700)
    return {'source_root': repo, 'source_commit': git('rev-parse', 'HEAD'),
            'store': store, 'operation_id': str(uuid4())}


def files_state(root):
    return {str(p.relative_to(root)): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


def test_real_git_stage_is_inert_and_inspection_does_not_write(case):
    before = files_state(case['source_root'])
    result = m.prepare(**case)
    assert result['status'] == 'prepared_not_installed' and result['files_verified'] == 6
    assert all(result[k] is False for k in m.FALSE_CLAIMS)
    package = case['store'] / case['operation_id']
    assert set(p.name for p in package.iterdir()) == {'intent.json', 'payload', 'ready.json'}
    for p in package.rglob('*'):
        if p.is_file():
            assert stat.S_IMODE(p.stat().st_mode) == 0o400
            assert not p.stat().st_mode & 0o111
    snapshot = files_state(case['store'])
    assert m.inspect_package(**case) == result
    assert files_state(case['store']) == snapshot
    assert files_state(case['source_root']) == before
    assert not any(p.name in {'enrollment.json', 'bootstrap-evidence.json', 'execution.lock'}
                   for p in case['store'].rglob('*'))


@pytest.mark.parametrize('commit', ['', 'a'*39, 'a'*41, 'A'*40, None, True, 13, 'main'])
def test_invalid_source_identity_has_no_stage_effect(case, commit):
    case['source_commit'] = commit
    with pytest.raises(m.PreparationBlocked):
        m.prepare(**case)
    assert list(case['store'].iterdir()) == []


@pytest.mark.parametrize('operation', ['', '../x', '/tmp/x', 'x', None, True,
                                       'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'])
def test_invalid_operation_has_no_stage_effect(case, operation):
    case['operation_id'] = operation
    with pytest.raises(m.PreparationBlocked):
        m.prepare(**case)
    assert list(case['store'].iterdir()) == []


@pytest.mark.parametrize('fault', ['head', 'bytes', 'mode', 'symlink', 'hardlink', 'ancestor_symlink'])
def test_dirty_or_replaced_source_never_becomes_prepared(case, fault):
    p = case['source_root'] / 'scripts/security/fr06_execution_guard.py'
    if fault == 'head': case['source_commit'] = 'f'*40
    elif fault == 'bytes': p.write_text('# different unreviewed bytes\n')
    elif fault == 'mode': p.chmod(0o755)
    elif fault == 'symlink':
        p.rename(p.with_name('kept')); p.symlink_to(p.with_name('kept'))
    elif fault == 'hardlink': os.link(p, p.with_name('alias'))
    else:
        directory = p.parent; directory.rename(directory.with_name('kept'))
        directory.symlink_to(directory.with_name('kept'))
    with pytest.raises((m.PreparationBlocked, OSError)):
        m.prepare(**case)
    assert list(case['store'].iterdir()) == []


@pytest.mark.parametrize('fault', ['public', 'missing', 'symlink'])
def test_preexisting_private_store_required(case, fault):
    store = case['store']
    if fault == 'public': store.chmod(0o755)
    elif fault == 'missing': store.rmdir()
    else:
        kept = store.with_name('kept'); store.rename(kept); store.symlink_to(kept)
    with pytest.raises((m.PreparationBlocked, OSError)):
        m.prepare(**case)
    assert not (store / case['operation_id']).exists()


@pytest.mark.parametrize('existing', ['file', 'directory', 'symlink'])
def test_preexisting_operation_is_never_replaced_or_adopted(case, existing):
    target = case['store'] / case['operation_id']
    if existing == 'file': target.write_text('foreign sentinel')
    elif existing == 'directory': target.mkdir(mode=0o700)
    else: target.symlink_to(case['source_root'])
    original = target.lstat()
    with pytest.raises(FileExistsError): m.prepare(**case)
    assert target.lstat() == original


def test_completed_operation_cannot_be_replayed(case):
    m.prepare(**case); saved = files_state(case['store'])
    with pytest.raises(FileExistsError): m.prepare(**case)
    assert files_state(case['store']) == saved


@pytest.mark.parametrize('fail_at', ['intent.json', 'aionex-fr06-primary', 'fr06_source_operator.py', 'ready.json'])
def test_interruption_before_file_write_retains_partial_without_adoption(case, monkeypatch, fail_at):
    original = m._write_new
    def fail(fd, name, data):
        if name == fail_at: raise OSError('synthetic interruption')
        original(fd, name, data)
    monkeypatch.setattr(m, '_write_new', fail)
    with pytest.raises(OSError): m.prepare(**case)
    package = case['store'] / case['operation_id']
    assert package.is_dir() and not (package / 'ready.json').exists()
    before = files_state(case['store'])
    with pytest.raises(FileExistsError): m.prepare(**case)
    with pytest.raises(m.PreparationBlocked): m.inspect_package(**case)
    assert files_state(case['store']) == before


def test_source_changed_during_copy_leaves_no_ready_record(case, monkeypatch):
    original = m._write_new
    def change(fd, name, data):
        original(fd, name, data)
        if name == 'aionex-fr06-primary':
            (case['source_root'] / m.PAYLOAD['fr06_execution_guard.py'][0]).write_text('changed\n')
    monkeypatch.setattr(m, '_write_new', change)
    with pytest.raises(m.PreparationBlocked): m.prepare(**case)
    assert not (case['store'] / case['operation_id'] / 'ready.json').exists()


@pytest.mark.parametrize('fault', ['bytes', 'mode', 'symlink', 'hardlink', 'extra'])
def test_inspection_rejects_tampered_payload(case, fault):
    m.prepare(**case)
    directory = case['store'] / case['operation_id'] / 'payload'
    p = directory / 'aionex-fr06-primary'
    if fault == 'bytes': p.chmod(0o600); p.write_text('changed\n'); p.chmod(0o400)
    elif fault == 'mode': p.chmod(0o500)
    elif fault == 'symlink': p.unlink(); p.symlink_to(case['source_root'] / m.PAYLOAD[p.name][0])
    elif fault == 'hardlink': os.link(p, directory.parent / 'foreign-alias')
    else: (directory / 'enrollment.json').write_text('{}\n')
    with pytest.raises((m.PreparationBlocked, OSError)): m.inspect_package(**case)


@pytest.mark.parametrize('field', list(m.FALSE_CLAIMS))
def test_ready_cannot_grant_authority_even_with_rehashed_valid_json(case, field):
    m.prepare(**case)
    p = case['store'] / case['operation_id'] / 'ready.json'
    value = json.loads(p.read_bytes()); value[field] = True
    p.chmod(0o600); p.write_bytes(m.canon(value)); p.chmod(0o400)
    with pytest.raises(m.PreparationBlocked): m.inspect_package(**case)


def test_manifest_and_payload_changed_together_still_need_exact_source(case):
    m.prepare(**case)
    directory = case['store'] / case['operation_id']
    manifest = json.loads((directory / 'intent.json').read_bytes())
    name = 'fr06_execution_guard.py'; data = b'forged payload\n'
    manifest['files'][name].update(sha256=m.digest(data), bytes=len(data))
    ready = json.loads((directory / 'ready.json').read_bytes())
    ready['manifest_sha256'] = m.digest(m.canon(manifest))
    for p, raw in [(directory/'payload'/name, data), (directory/'intent.json',m.canon(manifest)),
                   (directory/'ready.json',m.canon(ready))]:
        p.chmod(0o600); p.write_bytes(raw); p.chmod(0o400)
    with pytest.raises(m.PreparationBlocked): m.inspect_package(**case)


def test_git_environment_injection_cannot_replace_source(case, monkeypatch):
    monkeypatch.setenv('GIT_DIR', '/nonexistent/attacker')
    monkeypatch.setenv('GIT_WORK_TREE', '/nonexistent/attacker')
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.worktree')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', '/nonexistent/attacker')
    assert m.prepare(**case)['files_verified'] == 6


def test_actual_short_writes_are_completed_and_synced(case, monkeypatch):
    write, sync = m.os.write, m.os.fsync
    calls = []
    def short(fd, data): return write(fd, data[:3])
    def observe(fd): calls.append(os.fstat(fd).st_mode); return sync(fd)
    monkeypatch.setattr(m.os, 'write', short); monkeypatch.setattr(m.os, 'fsync', observe)
    assert m.prepare(**case)['files_verified'] == 6
    assert sum(stat.S_ISREG(mode) for mode in calls) == 8
    assert sum(stat.S_ISDIR(mode) for mode in calls) >= 10


def test_zero_write_never_yields_readable_ready_receipt(case, monkeypatch):
    monkeypatch.setattr(m.os, 'write', lambda *_: 0)
    with pytest.raises(m.PreparationBlocked): m.prepare(**case)
    assert not (case['store']/case['operation_id']/'ready.json').exists()


def test_package_name_swapped_during_preparation_is_not_accepted(case, monkeypatch):
    original = m._write_new
    def swap(fd, name, data):
        original(fd, name, data)
        if name == 'fr06_source_operator.py':
            p = case['store']/case['operation_id']; p.rename(p.with_name('retained'))
            p.mkdir(mode=0o700)
    monkeypatch.setattr(m, '_write_new', swap)
    with pytest.raises(m.PreparationBlocked): m.prepare(**case)
    assert not (case['store']/'retained'/'ready.json').exists()
    assert not (case['store']/case['operation_id']/'ready.json').exists()


def test_symlink_inserted_before_copy_never_changes_foreign_file(case, monkeypatch):
    victim = case['store']/'foreign'; victim.write_text('preserved')
    original = m._write_new
    def insert(fd, name, data):
        if name == 'aionex-fr06-primary': os.symlink(str(victim), name, dir_fd=fd)
        original(fd, name, data)
    monkeypatch.setattr(m, '_write_new', insert)
    with pytest.raises(FileExistsError): m.prepare(**case)
    assert victim.read_text() == 'preserved'


def _race_prepare(case, barrier, queue):
    barrier.wait(timeout=5)
    try:
        queue.put(m.prepare(**case)['status'])
    except FileExistsError:
        queue.put('already_claimed')


def test_actual_competing_processes_create_exactly_one_package(case):
    ctx=mp.get_context('fork'); barrier=ctx.Barrier(2); queue=ctx.Queue()
    children=[ctx.Process(target=_race_prepare,args=(case,barrier,queue)) for _ in range(2)]
    for child in children: child.start()
    try:
        results=[queue.get(timeout=15) for _ in children]
        assert sorted(results) == ['already_claimed','prepared_not_installed']
        for child in children:
            child.join(5); assert child.exitcode == 0
        assert m.inspect_package(**case)['files_verified'] == 6
    finally:
        for child in children:
            if child.is_alive(): child.kill(); child.join(5)
        queue.close()


def _stop_after_intent(case, pipe):
    original=m._write_new
    def stopped(fd,name,raw):
        original(fd,name,raw)
        if name=='intent.json':
            pipe.send('intent_fsynced')
            signal.pause()
    m._write_new=stopped
    m.prepare(**case)


def test_actual_child_death_retains_intent_and_never_replays(case):
    ctx=mp.get_context('fork'); parent,childpipe=ctx.Pipe(duplex=False)
    child=ctx.Process(target=_stop_after_intent,args=(case,childpipe)); child.start()
    try:
        assert parent.poll(10) and parent.recv()=='intent_fsynced'
        child.kill(); child.join(5); assert child.exitcode == -signal.SIGKILL
        with pytest.raises(FileExistsError): m.prepare(**case)
        with pytest.raises(m.PreparationBlocked): m.inspect_package(**case)
        assert set(p.name for p in (case['store']/case['operation_id']).iterdir()) == {'intent.json'}
    finally:
        if child.is_alive(): child.kill(); child.join(5)
        parent.close(); childpipe.close()


def test_only_prepare_and_inspect_cli_actions_exist():
    script=Path(m.__file__)
    child=subprocess.run(['/usr/bin/python3',str(script),'activate'],capture_output=True,text=True,timeout=10)
    assert child.returncode==2 and 'invalid choice' in child.stderr


def test_missing_package_cli_does_not_create_any_state(case):
    child=subprocess.run(['/usr/bin/python3',str(Path(m.__file__)),'inspect',
        '--source-root',str(case['source_root']),'--source-commit',case['source_commit'],
        '--store',str(case['store']),'--operation-id',case['operation_id']],
        capture_output=True,text=True,timeout=15)
    assert child.returncode==2
    result=json.loads(child.stdout)
    assert result['automatic_retry'] is False and all(result[k] is False for k in m.FALSE_CLAIMS)
    assert list(case['store'].iterdir()) == []


@pytest.mark.parametrize('which', ['store', 'package', 'payload'])
def test_permission_drift_never_publishes_ready_marker(case, monkeypatch, which):
    original = m._write_new
    def drift(fd, name, data):
        original(fd, name, data)
        if name == 'fr06_source_operator.py':
            root = case['store']
            target = root if which == 'store' else root/case['operation_id']
            if which == 'payload': target = target/'payload'
            target.chmod(0o777)
    monkeypatch.setattr(m, '_write_new', drift)
    with pytest.raises(m.PreparationBlocked): m.prepare(**case)
    assert not (case['store']/case['operation_id']/'ready.json').exists()


@pytest.mark.parametrize('kind', ['fifo', 'oversized'])
def test_special_or_oversized_source_does_not_block_or_write(case, kind):
    p=case['source_root']/m.PAYLOAD['fr06_execution_guard.py'][0]
    if kind == 'fifo': p.unlink(); os.mkfifo(p, 0o644)
    else: p.write_bytes(b'x'*(m.MAX_FILE+1))
    with pytest.raises(m.PreparationBlocked): m.prepare(**case)
    assert list(case['store'].iterdir()) == []


def test_only_allowlisted_payload_and_package_records_are_read(case, monkeypatch):
    incident=case['source_root']/'unrelated-private-record.json'
    incident.write_text('synthetic sentinel; not an enrollment input')
    reads=[]; original=m._read
    def recorded(fd,name,mode=None):
        reads.append(name); return original(fd,name,mode)
    monkeypatch.setattr(m,'_read',recorded)
    assert m.prepare(**case)['files_verified'] == 6
    assert set(reads) == set(m.PAYLOAD)|{'ready.json','intent.json'}
    assert incident.read_text() == 'synthetic sentinel; not an enrollment input'
