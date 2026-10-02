"""Native publication on disposable owned roots, with SYNTHETIC admission.

No test installs to live paths or attests real source/role/history acceptance.
"""
from __future__ import annotations

import copy
import dataclasses
import errno
import fcntl
import multiprocessing as mp
import os
import signal
import stat
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from scripts.security import fr06_executor_preparation as p
from scripts.security import fr06_executor_installation as m
from scripts.security.fr06_execution_guard import Binding, GuardBlocked
from scripts.security.fr06_execution_enrollment import probe_existing_lock


@pytest.fixture
def install_case(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir(mode=0o700)
    env = {'PATH':'/usr/bin:/bin','HOME':str(tmp_path),'LANG':'C',
           'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
    def git(*args):
        return subprocess.check_output(['/usr/bin/git','-C',str(repo),*args],env=env,stderr=subprocess.PIPE).decode().strip()
    git('init','-q')
    for name,(rel,mode) in p.PAYLOAD.items():
        file=repo/rel; file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text('#!/bin/sh\n# synthetic non-production launcher\nexit 23\n' if name in m.ROUTES else '# synthetic inert module\n')
        file.chmod(int(mode[-3:],8))
    git('add','.')
    git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
        '-c','commit.gpgsign=false','commit','-qm','fixture')
    commit=git('rev-parse','HEAD')
    store=tmp_path/'store'; store.mkdir(mode=0o700)
    journal=tmp_path/'journal'; journal.mkdir(mode=0o700)
    for name in ('state-parent','launch-parent'):(tmp_path/name).mkdir(mode=0o700)
    prep=str(uuid4()); p.prepare(source_root=repo,source_commit=commit,store=store,operation_id=prep)
    binding=Binding(commit,commit,str(uuid4()),str(uuid4()),41,True,'closed')
    return {'source_root':repo,'source_commit':commit,'store':store,'preparation_id':prep,
            'journal':journal,'operation_id':str(uuid4()),'guard_root':tmp_path/'state-parent/fr06-executor',
            'launch_root':tmp_path/'launch-parent/fr06','binding':binding,'authorize':lambda:binding}


def tree(path):
    return {str(q.relative_to(path)):(q.lstat().st_ino,stat.S_IMODE(q.lstat().st_mode),
                                      q.read_bytes() if q.is_file() and not q.is_symlink() else None)
            for q in path.rglob('*')}


def test_real_two_root_publication_keeps_enrollment_and_historical_authority_absent(install_case):
    c=install_case; original=tree(c['store'])
    result=m.install_unenrolled(**c)
    assert result['status']=='files_installed_unenrolled'
    assert all(result[k] is False for k in m.NO_AUTHORITY)
    assert set(q.name for q in c['guard_root'].iterdir())=={'execution.lock','receipts'}
    assert set(q.name for q in c['launch_root'].iterdir())==set(m.ROUTES)
    assert stat.S_IMODE(c['guard_root'].stat().st_mode)==0o700
    assert stat.S_IMODE((c['guard_root']/'execution.lock').stat().st_mode)==0o600
    for name in m.ROUTES:
        q=c['launch_root']/name
        assert stat.S_IMODE(q.stat().st_mode)==0o755
        assert q.read_bytes()==(c['source_root']/p.PAYLOAD[name][0]).read_bytes()
    assert tree(c['store'])==original
    assert not any(q.name in {'enrollment.json','bootstrap-evidence.json','effects.jsonl'}
                   for q in c['journal'].parent.rglob('*'))
    assert p.decode((c['journal']/'files-installed.json').read_bytes())==result


@pytest.mark.parametrize('fresh_id',[False,True])
def test_a_completed_initial_installation_cannot_be_replayed(install_case,fresh_id):
    c=install_case; m.install_unenrolled(**c); before=tree(c['journal'].parent)
    if fresh_id:c['operation_id']=str(uuid4())
    with pytest.raises(m.InstallationBlocked,match='already claimed'):m.install_unenrolled(**c)
    assert tree(c['journal'].parent)==before


@pytest.mark.parametrize('kind',['guard_root','launch_root'])
@pytest.mark.parametrize('existing',['file','directory','symlink'])
def test_preexisting_destination_preserved_without_even_an_intent(install_case,kind,existing):
    c=install_case; q=c[kind]
    if existing=='file':q.write_text('foreign sentinel')
    elif existing=='directory':q.mkdir(mode=0o700)
    else:q.symlink_to(c['source_root'])
    original=q.lstat()
    with pytest.raises(m.InstallationBlocked):m.install_unenrolled(**c)
    assert q.lstat()==original and not list(c['journal'].iterdir())


@pytest.mark.parametrize('fault',['not_callable','dict','none','changed_boot','changed_operation','changed_generation','dirty','open'])
def test_missing_changed_or_self_asserted_admission_causes_no_file_effect(install_case,fault):
    c=install_case; b=c['binding']
    values={'not_callable':None,'dict':lambda:dataclasses.asdict(b),'none':lambda:None,
            'changed_boot':lambda:dataclasses.replace(b,boot_id=str(uuid4())),
            'changed_operation':lambda:dataclasses.replace(b,operation_id=str(uuid4())),
            'changed_generation':lambda:dataclasses.replace(b,generation=42),
            'dirty':lambda:dataclasses.replace(b,source_clean=False),
            'open':lambda:dataclasses.replace(b,maintenance_status='open')}
    c['authorize']=values[fault]
    with pytest.raises((m.InstallationBlocked,GuardBlocked)):m.install_unenrolled(**c)
    assert not list(c['journal'].iterdir())
    assert not c['guard_root'].exists() and not c['launch_root'].exists()


@pytest.mark.parametrize('stage',['intent.json','candidates.json','1-guard-intent.json',
                                  '1-guard-observed.json','2-launch-intent.json','2-launch-observed.json','files-installed.json'])
def test_interrupted_write_keeps_partial_installation_and_never_auto_rolls_back_or_replays(install_case,monkeypatch,stage):
    c=install_case; original=m._record
    def interrupt(fd,name,value):
        if name==stage:raise OSError('synthetic log failure')
        return original(fd,name,value)
    monkeypatch.setattr(m,'_record',interrupt)
    with pytest.raises(OSError):m.install_unenrolled(**c)
    assert not (c['journal']/'files-installed.json').exists()
    if stage=='intent.json':
        assert not c['guard_root'].exists() and not c['launch_root'].exists()
        return
    before=tree(c['journal'].parent)
    monkeypatch.setattr(m,'_record',original)
    with pytest.raises(m.InstallationBlocked):m.install_unenrolled(**c)
    assert tree(c['journal'].parent)==before
    if stage in ('1-guard-observed.json','2-launch-intent.json','2-launch-observed.json','files-installed.json'):
        assert c['guard_root'].exists()
    if stage in ('2-launch-observed.json','files-installed.json'):assert c['launch_root'].exists()


@pytest.mark.parametrize('publish',['guard','launch'])
def test_real_no_replace_syscall_preserves_late_foreign_destination(install_case,monkeypatch,publish):
    c=install_case; original=m._rename_no_replace
    def race(src,name,dst,target):
        if name==publish+'-candidate':
            fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600,dir_fd=dst)
            os.write(fd,b'FOREIGN');os.close(fd)
        original(src,name,dst,target)
    monkeypatch.setattr(m,'_rename_no_replace',race)
    with pytest.raises(OSError) as exc:m.install_unenrolled(**c)
    assert exc.value.errno in (errno.EEXIST,errno.ENOTDIR)
    assert c[publish+'_root'].read_bytes()==b'FOREIGN'
    assert not (c['journal']/'files-installed.json').exists()


@pytest.mark.parametrize('stage',['1-guard-intent.json','2-launch-intent.json'])
def test_admission_rollover_immediately_before_publication_stops_next_effect(install_case,monkeypatch,stage):
    c=install_case; live=[c['binding']];c['authorize']=lambda:live[0]; original=m._record
    def change(fd,name,value):
        original(fd,name,value)
        if name==stage:live[0]=dataclasses.replace(live[0],generation=42)
    monkeypatch.setattr(m,'_record',change)
    with pytest.raises(m.InstallationBlocked,match='authority changed'):m.install_unenrolled(**c)
    assert not c['launch_root'].exists()
    assert c['guard_root'].exists()==(stage=='2-launch-intent.json')
    assert not (c['journal']/'files-installed.json').exists()


@pytest.mark.parametrize('fault',['source','package','parent_mode','extra_enrollment'])
def test_post_guard_drift_prevents_launcher_publication(install_case,monkeypatch,fault):
    c=install_case; original=m._record
    def change(fd,name,value):
        original(fd,name,value)
        if name=='1-guard-observed.json':
            if fault=='source':(c['source_root']/p.PAYLOAD['fr06_source_operator.py'][0]).write_text('foreign')
            elif fault=='package':
                q=c['store']/c['preparation_id']/'payload/aionex-fr06-primary';q.chmod(0o600);q.write_text('foreign');q.chmod(0o400)
            elif fault=='parent_mode':c['launch_root'].parent.chmod(0o777)
            else:(c['guard_root']/'enrollment.json').write_text('{}')
    monkeypatch.setattr(m,'_record',change)
    with pytest.raises((m.InstallationBlocked,p.PreparationBlocked)):m.install_unenrolled(**c)
    assert c['guard_root'].exists() and not c['launch_root'].exists()
    assert not (c['journal']/'files-installed.json').exists()


@pytest.mark.parametrize('target',['journal','guard_root','launch_root'])
def test_symbolic_or_public_parents_are_rejected(install_case,target):
    c=install_case;q=c[target] if target=='journal' else c[target].parent
    q.chmod(0o777)
    with pytest.raises((m.InstallationBlocked,p.PreparationBlocked)):m.install_unenrolled(**c)
    assert not list(c['journal'].iterdir())


def test_nested_roots_are_not_a_supported_installation(install_case):
    c=install_case;c['launch_root']=c['guard_root']/'launch'
    with pytest.raises(m.InstallationBlocked,match='overlap'):m.install_unenrolled(**c)
    assert not list(c['journal'].iterdir())


def test_directory_inode_binding_rejects_same_name_replacement(install_case,monkeypatch):
    c=install_case; original=m._record
    def replace(fd,name,value):
        original(fd,name,value)
        if name=='1-guard-observed.json':
            c['guard_root'].rename(c['guard_root'].with_name('retained-original'))
            c['guard_root'].mkdir(mode=0o700)
    monkeypatch.setattr(m,'_record',replace)
    with pytest.raises(m.InstallationBlocked):m.install_unenrolled(**c)
    assert not c['launch_root'].exists() and (c['guard_root'].parent/'retained-original').exists()


def test_short_writes_are_completed(install_case,monkeypatch):
    original=m.os.write
    monkeypatch.setattr(m.os,'write',lambda fd,data:original(fd,data[:max(1,min(7,len(data)))]))
    assert m.install_unenrolled(**install_case)['status']=='files_installed_unenrolled'


def test_unsupported_atomic_publication_has_no_weaker_fallback(install_case,monkeypatch):
    monkeypatch.setattr(m.ctypes,'CDLL',lambda *args,**kwargs:object())
    with pytest.raises(m.InstallationBlocked,match='atomic'):m.install_unenrolled(**install_case)
    assert not install_case['guard_root'].exists() and not install_case['launch_root'].exists()
    assert (install_case['journal']/'1-guard-intent.json').exists()


def _contend(c,child):
    try:
        m.install_unenrolled(**c);child.send('installed')
    except BlockingIOError:child.send('busy')
    except m.InstallationBlocked:child.send('claimed')
    finally:child.close()


def test_real_competing_processes_cannot_publish_two_installations(install_case):
    ctx=mp.get_context('fork');children=[]
    for _ in range(2):
        recv,send=ctx.Pipe(duplex=False);proc=ctx.Process(target=_contend,args=(install_case,send));proc.start();send.close();children.append((proc,recv))
    answers=[]
    for proc,recv in children:
        assert recv.poll(20);answers.append(recv.recv());proc.join(20);assert proc.exitcode==0
    assert sorted(answers) in (['busy','installed'],['claimed','installed'])


def _die_after_guard(c,pipe):
    original=m._rename_no_replace
    def stop(src,name,dst,target):
        original(src,name,dst,target)
        if name=='guard-candidate':
            pipe.send('guard-published-before-observed-record');signal.pause()
    m._rename_no_replace=stop
    m.install_unenrolled(**c)


def test_real_process_loss_after_first_namespace_change_is_not_replayed(install_case):
    c=install_case;ctx=mp.get_context('fork');recv,send=ctx.Pipe(duplex=False)
    proc=ctx.Process(target=_die_after_guard,args=(c,send));proc.start();send.close()
    try:
        assert recv.poll(20) and recv.recv()=='guard-published-before-observed-record'
        os.kill(proc.pid,signal.SIGKILL);proc.join(10);assert proc.exitcode==-signal.SIGKILL
    finally:
        if proc.is_alive():proc.kill();proc.join(10)
    assert c['guard_root'].is_dir() and not c['launch_root'].exists()
    assert not (c['journal']/'1-guard-observed.json').exists()
    before=tree(c['journal'].parent)
    with pytest.raises(m.InstallationBlocked):m.install_unenrolled(**c)
    assert tree(c['journal'].parent)==before


def _probe(root,challenge,send):
    send.send(probe_existing_lock(root,'interactive',challenge));send.close()


def test_installed_lock_has_real_kernel_contention_but_is_not_role_adoption(install_case):
    c=install_case;m.install_unenrolled(**c);challenge=str(uuid4())
    with (c['guard_root']/'execution.lock').open('r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ctx=mp.get_context('fork');recv,send=ctx.Pipe(duplex=False);proc=ctx.Process(target=_probe,args=(c['guard_root'],challenge,send));proc.start();send.close()
        assert recv.poll(10);value=recv.recv();proc.join(10);assert proc.exitcode==0
        assert value['result']=='kernel_contention_observed' and value['challenge']==challenge
        assert value['pid']!=os.getpid()
    assert not (c['guard_root']/'enrollment.json').exists()


@pytest.mark.parametrize('kind',['guard','launch'])
@pytest.mark.parametrize('fault',['bytes','extra','replacement'])
def test_change_after_durable_publish_intent_does_not_publish_changed_candidate(install_case,monkeypatch,kind,fault):
    c=install_case; original=m._record
    at={'guard':'1-guard-intent.json','launch':'2-launch-intent.json'}[kind]
    def change(fd,name,value):
        original(fd,name,value)
        if name==at:
            directory=c['journal']/(kind+'-candidate')
            if fault=='bytes':
                leaf='execution.lock' if kind=='guard' else m.ROUTES[0]
                (directory/leaf).write_bytes(b'foreign replacement')
            elif fault=='extra':(directory/'enrollment.json').write_text('{}')
            else:
                import shutil
                old=directory.with_name(kind+'-retained-original');directory.rename(old)
                shutil.copytree(old,directory)
    monkeypatch.setattr(m,'_record',change)
    with pytest.raises((m.InstallationBlocked,p.PreparationBlocked)):m.install_unenrolled(**c)
    assert not c[kind+'_root'].exists(), 'changed candidate must not enter the target namespace'
    assert not (c['journal']/'files-installed.json').exists()


@pytest.mark.parametrize('at',['1-guard-intent.json','2-launch-intent.json'])
def test_rewritten_candidate_journal_is_not_accepted_as_installation_history(install_case,monkeypatch,at):
    c=install_case;original=m._record
    def change(fd,name,value):
        original(fd,name,value)
        if name==at:
            q=c['journal']/'candidates.json';q.chmod(0o600);q.write_bytes(p.canon({'forged':True}));q.chmod(0o400)
    monkeypatch.setattr(m,'_record',change)
    with pytest.raises(m.InstallationBlocked):m.install_unenrolled(**c)
    assert not c['launch_root'].exists()
    assert not (c['journal']/'files-installed.json').exists()


def test_guard_drift_after_second_intent_does_not_publish_launchers(install_case,monkeypatch):
    c=install_case;original=m._record
    def change(fd,name,value):
        original(fd,name,value)
        if name=='2-launch-intent.json':
            (c['guard_root']/'enrollment.json').write_text('{}')
    monkeypatch.setattr(m,'_record',change)
    with pytest.raises(m.InstallationBlocked):m.install_unenrolled(**c)
    assert not c['launch_root'].exists()


@pytest.mark.parametrize('role',['interactive','scheduled','watchdog'])
@pytest.mark.parametrize('action',['source_merge','source_sync'])
@pytest.mark.parametrize('enrollment',['missing','forged'])
def test_published_files_cannot_enter_existing_source_dispatch_without_authentic_enrollment(
        install_case,monkeypatch,role,action,enrollment):
    """Only installation identity is synthetic; exercise actual enrollment denial.

    Actual file ownership stays that of the Unix test user. No privilege or
    source approval is attested; no authority, GitHub, merge or sync is called.
    """
    from scripts.security import fr06_source_operator as operator
    c=install_case;m.install_unenrolled(**c)
    if enrollment=='forged':
        q=c['guard_root']/'enrollment.json';q.write_bytes(b'{}\n');q.chmod(0o600)
    class SyntheticInstalledOS:
        @staticmethod
        def geteuid():return 0
        def __getattr__(self,name):return getattr(os,name)
    monkeypatch.setattr(operator,'os',SyntheticInstalledOS())
    monkeypatch.setattr(operator,'ROOT',c['source_root'])
    monkeypatch.setattr(operator,'GUARD_ROOT',c['guard_root'])
    monkeypatch.setattr(operator,'LAUNCH_ROOT',c['launch_root'])
    monkeypatch.setattr(operator,'__file__',str(c['source_root']/'scripts/security/fr06_source_operator.py'))
    monkeypatch.setattr(operator.NativePort,'local',lambda self:(c['source_commit'],c['source_commit'],True))
    def forbidden(*args,**kwargs):raise AssertionError('unenrolled files must not reach source or provider I/O')
    monkeypatch.setattr(operator,'command',forbidden)
    for name in ('authority','remote','merge','fast_forward','fetch_target','save'):
        monkeypatch.setattr(operator.NativePort,name,forbidden)
    req=operator.Request(action,835,c['source_commit'],c['source_commit'],c['source_commit'],
                         c['binding'].boot_id,c['binding'].operation_id,41)
    with pytest.raises((FileNotFoundError,operator.SourceBlocked)):
        operator.execute(req,run_id='isolated-no-enrollment',invocation_type=role)
    assert not (c['guard_root']/'effects.jsonl').exists()
