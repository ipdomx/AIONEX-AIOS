"""Synthetic owner signatures and native file/flock tests, never live approval.

Fixture private keys exist only in pytest-owned temporary paths. Native source,
DB, role-adoption and independent-history decisions are modeled explicitly;
no test writes a production trust key, permit, enrollment or installation.
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from scripts.security import fr06_executor_native_install as m
from scripts.security.fr06_execution_guard import Binding, GuardBlocked


@pytest.fixture(scope='module')
def signing(tmp_path_factory):
    root = tmp_path_factory.mktemp('synthetic-independent-signer')
    key = root/'fixture-private.pem'
    subprocess.run(['/usr/bin/openssl','genpkey','-algorithm','Ed25519','-out',str(key)],
                   env=m.ENV,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    public = subprocess.check_output(['/usr/bin/openssl','pkey','-in',str(key),'-pubout'],
                                     env=m.ENV,stderr=subprocess.DEVNULL)
    def sign(raw):
        with m.sealed(raw) as fd:
            return subprocess.check_output(['/usr/bin/openssl','pkeyutl','-sign','-inkey',str(key),
                '-rawin','-in',f'/proc/self/fd/{fd}'],env=m.ENV,pass_fds=(fd,),stderr=subprocess.DEVNULL)
    return public, sign


@pytest.fixture
def case(signing):
    now=datetime(2026,10,2,12,0,tzinfo=timezone.utc)
    aid=str(uuid4()); binding=asdict(Binding('a'*40,'a'*40,str(uuid4()),str(uuid4()),41,True,'closed'))
    ident={'device':2,'inode':90}; anchor={'byte_count':3,'sha256':m.sha(b'{}\n')}
    control={'schema':'aionex.fr06-independent-install-control.v1','authorization_id':aid,
        'binding':binding,'coordinator_identity':ident,'roles':{
            role:{'task_id':task,'disposition':'fenced_for_this_installation','evidence_sha256':'b'*64}
            for role,task in m.ROLES.items()},'evidence_reference':'c'*64}
    history={'schema':'aionex.fr06-independent-history-review.v1','authorization_id':aid,
             'journal_anchor':anchor,'disposition':'effects_reconciled','unresolved_runs':[],
             'evidence_reference':'d'*64}
    permit={'schema':m.SCHEMA,'authorization_id':aid,'task_id':m.TASK,'repository':m.REPOSITORY,
        'action':'initial_install_unenrolled','binding':binding,'source_pr':123,'reviewed_head':'e'*40,
        'preparation_id':str(uuid4()),'issued_at':(now-timedelta(seconds=5)).isoformat(),
        'expires_at':(now+timedelta(seconds=300)).isoformat(),'coordinator_identity':ident,
        'journal_anchor':anchor,'control_sha256':m.sha(m.prep.canon(control)),
        'history_sha256':m.sha(m.prep.canon(history))}
    return {'permit':permit,'control':control,'history':history,'now':now,'signing':signing}


def packed(case, refresh=True):
    p=case['permit']; c=m.prep.canon(case['control']); h=m.prep.canon(case['history'])
    if refresh:p.update(control_sha256=m.sha(c),history_sha256=m.sha(h))
    raw=m.prep.canon(p); public,sign=case['signing']
    return public,raw,sign(raw),c,h


def verify(case, values=None):
    key,raw,sig,c,h=packed(case) if values is None else values
    return m.verify_permit(raw,sig,key,c,h,now=case['now'],authorization_id=case['permit']['authorization_id'])


def test_real_synthetic_signature_is_verified_without_issuing_authority(case):
    result=verify(case)
    assert result==case['permit']
    assert result['action']=='initial_install_unenrolled'
    assert 'enrolled' not in result and 'production_activation_authorized' not in result


@pytest.mark.parametrize('fault',['signature','message','key','short_signature','missing_signature','control','history'])
def test_corrupted_or_unsigned_inputs_never_pass(case,fault):
    values=list(packed(case))
    if fault=='signature':values[2]=bytes([values[2][0]^1])+values[2][1:]
    elif fault=='message':values[1]=values[1].replace(b'initial_install_unenrolled',b'initial_install_unenrollex')
    elif fault=='key':
        der=bytes.fromhex('302a300506032b6570032100')+b'z'*32
        import base64
        values[0]=b'-----BEGIN PUBLIC KEY-----\n'+base64.b64encode(der)+b'\n-----END PUBLIC KEY-----\n'
    elif fault=='short_signature':values[2]=values[2][:-1]
    elif fault=='missing_signature':values[2]=b''
    elif fault=='control':values[3]+=b' '
    else:values[4]+=b' '
    with pytest.raises(m.AdmissionBlocked):verify(case,values)


@pytest.mark.parametrize('field,value',[
    ('schema','different'),('task_id','other'),('repository','other/repo'),('action','source_merge'),
    ('source_pr',True),('source_pr',0),('reviewed_head','main'),('reviewed_head','F'*40),
    ('preparation_id','../x'),('authorization_id','../x'),('coordinator_identity',{'device':True,'inode':1}),
    ('coordinator_identity',{'device':1,'inode':0}),('journal_anchor',{'byte_count':True,'sha256':'a'*64}),
    ('journal_anchor',{'byte_count':10,'sha256':'wrong'}),('issued_at','not-time'),
    ('expires_at','2026-10-02T12:10:00'),
])
def test_even_authentically_signed_wrong_scope_is_rejected(case,field,value):
    case['permit'][field]=value
    with pytest.raises((m.AdmissionBlocked,GuardBlocked)):verify(case)


@pytest.mark.parametrize('field,value',[
    ('source_commit','b'*40),('generation',True),('source_clean',False),('maintenance_status','open'),
    ('boot_id','not-uuid'),('operation_id','not-uuid'),
])
def test_invalid_binding_is_not_fixed_by_signature(case,field,value):
    case['permit']['binding'][field]=value
    with pytest.raises((m.AdmissionBlocked,GuardBlocked)):verify(case)


@pytest.mark.parametrize('seconds',[-10,300,600])
def test_real_clock_outside_window_is_rejected(case,seconds):
    case['now']+=timedelta(seconds=seconds)
    with pytest.raises(m.AdmissionBlocked):verify(case)


def test_long_signed_validity_window_is_rejected(case):
    case['permit']['expires_at']=(case['now']+timedelta(hours=1)).isoformat()
    with pytest.raises(m.AdmissionBlocked):verify(case)


@pytest.mark.parametrize('fault',['role_missing','role_task','role_state','role_proof','control_epoch','history_unknown','history_state','history_anchor','review_reference'])
def test_signed_review_cannot_suppress_missing_role_or_unknown_history(case,fault):
    if fault=='role_missing':del case['control']['roles']['watchdog']
    elif fault=='role_task':case['control']['roles']['watchdog']['task_id']=m.TASK
    elif fault=='role_state':case['control']['roles']['scheduled']['disposition']='enabled'
    elif fault=='role_proof':case['control']['roles']['interactive']['evidence_sha256']=''
    elif fault=='control_epoch':case['control']['authorization_id']=str(uuid4())
    elif fault=='history_unknown':case['history']['unresolved_runs']=['original-run']
    elif fault=='history_state':case['history']['disposition']='unknown'
    elif fault=='history_anchor':case['history']['journal_anchor']={'byte_count':4,'sha256':'f'*64}
    else:case['history']['evidence_reference']=''
    with pytest.raises(m.AdmissionBlocked):verify(case)


def test_duplicate_json_rejected_even_with_valid_signature(case):
    public,raw,_,c,h=packed(case); raw=raw.replace(b'{',b'{"schema":"evil",',1)
    sig=case['signing'][1](raw)
    with pytest.raises(m.AdmissionBlocked):verify(case,[public,raw,sig,c,h])


def test_public_inputs_are_sealed_against_modification():
    with m.sealed(b'public fixture') as fd:
        with pytest.raises(OSError):os.write(fd,b'change')
        with pytest.raises(OSError):os.ftruncate(fd,0)
        assert os.read(fd,20)==b'public fixture'


@pytest.mark.parametrize('fault',['mode','symlink','hardlink','directory','oversize','ancestor'])
def test_native_evidence_reader_rejects_unsafe_files(tmp_path,fault):
    root=tmp_path/'private';root.mkdir(mode=0o700); f=root/'permit.json'; f.write_bytes(b'{}\n');f.chmod(0o400)
    if fault=='mode':f.chmod(0o644)
    elif fault=='symlink':f.rename(root/'kept');f.symlink_to(root/'kept')
    elif fault=='hardlink':os.link(f,root/'alias')
    elif fault=='directory':f.unlink();f.mkdir()
    elif fault=='oversize':f.chmod(0o600);f.write_bytes(b'a'*65537);f.chmod(0o400)
    else:
        root.rename(tmp_path/'kept');root.symlink_to(tmp_path/'kept')
    with pytest.raises((m.AdmissionBlocked,m.prep.PreparationBlocked,OSError)):m.read_fixed(root,'permit.json')


def test_native_evidence_reader_preserves_bytes_mode_mtime(tmp_path):
    tmp_path.chmod(0o700);f=tmp_path/'permit.json';f.write_bytes(b'{}\n');f.chmod(0o400)
    before=f.stat()
    assert m.read_fixed(tmp_path,'permit.json')==b'{}\n'
    after=f.stat()
    assert before.st_mtime_ns==after.st_mtime_ns and before.st_mode==after.st_mode


def test_uninstalled_real_cli_refuses_before_missing_permit_or_any_install():
    result=subprocess.run([sys.executable,'-I',str(Path(m.__file__).resolve()),'install',
        '--authorization-id',str(uuid4())],capture_output=True,text=True,timeout=10)
    assert result.returncode==2
    data=json.loads(result.stdout)
    assert data=={'status':'admission_blocked_or_effect_uncertain','automatic_retry':False,
                  'enrolled':False,'production_activation_authorized':False}
    assert not result.stderr


@pytest.mark.parametrize('action',['check','install'])
def test_boundary_rejects_before_any_authority_or_installer_access(monkeypatch,action):
    def denied(*args,**kwargs):raise AssertionError('must not reach external access')
    monkeypatch.setattr(m.NativeSession,'files',denied)
    monkeypatch.setattr(m.installer,'install_unenrolled',denied)
    with pytest.raises(m.AdmissionBlocked,match='installed'):m.run(action,str(uuid4()))


def test_real_kernel_coordinator_contends_and_is_not_created_by_caller(tmp_path,monkeypatch):
    aid=str(uuid4());authority=tmp_path/'authority';authority.mkdir(mode=0o700);d=authority/aid;d.mkdir(mode=0o700)
    monkeypatch.setattr(m,'AUTHORITY',authority)
    # Model only installation identity; real owner, kernel lock and files remain.
    monkeypatch.setattr(m.NativeSession,'require_installed',lambda self:None)
    s=m.NativeSession(aid)
    with pytest.raises(FileNotFoundError):
        with s.hold():pass
    assert list(d.iterdir())==[]
    f=d/'coordinator.lock';f.touch(mode=0o600)
    with s.hold():
        ident=s.coordinator()
        assert ident=={'device':f.stat().st_dev,'inode':f.stat().st_ino}
        with pytest.raises(BlockingIOError):
            with m.NativeSession(aid).hold():pass
        f.rename(d/'retained');f.touch(mode=0o600)
        with pytest.raises(m.AdmissionBlocked):s.coordinator()
    assert s.lock_fd is None
    assert set(x.name for x in d.iterdir())=={'coordinator.lock','retained'}


class FixtureSession(m.NativeSession):
    def __init__(self,case):
        super().__init__(case['permit']['authorization_id']);self.case=case
        self.lock_fd=1;self.calls=[]
    def require_installed(self):pass
    def files(self):return packed(self.case)
    def supporting_evidence(self,c,h):return {}  # external supporting review artifacts modeled here
    def coordinator(self):self.calls.append('coordinator');return self.case['permit']['coordinator_identity']
    def source(self,permit):self.calls.append('source')
    def journal(self):self.calls.append('journal');return b'{}\n'
    def live_binding(self,permit):self.calls.append('authority');return Binding(**permit['binding'])


def live_window(case):
    now=datetime.now(timezone.utc);case['now']=now
    case['permit'].update(issued_at=(now-timedelta(seconds=1)).isoformat(),expires_at=(now+timedelta(seconds=300)).isoformat())


def test_signature_gate_precedes_source_or_maintenance_access(case):
    live_window(case);session=FixtureSession(case)
    real=session.files
    def bad():
        v=list(real());v[2]=b'x'*64;return tuple(v)
    session.files=bad
    with pytest.raises(m.AdmissionBlocked):session.authorize()
    assert session.calls==[]


def test_native_sequence_rechecks_permit_and_lock_and_retains_binding(case):
    live_window(case);session=FixtureSession(case)
    result=session.authorize()
    assert asdict(result)==case['permit']['binding']
    assert session.calls==['coordinator','source','journal','authority','source','journal','coordinator']
    assert session.original==session.files()


@pytest.mark.parametrize('fault',['journal','boot','permit_drift','coord_drift'])
def test_changed_context_before_return_refuses(case,fault):
    live_window(case);session=FixtureSession(case)
    if fault=='journal':session.journal=lambda:b'new\n'
    elif fault=='boot':
        b=copy.deepcopy(case['permit']['binding']);b['boot_id']=str(uuid4())
        session.live_binding=lambda permit:Binding(**b)
    elif fault=='permit_drift':
        original=session.live_binding
        def drift(permit):
            result=original(permit);case['permit']['reviewed_head']='f'*40;return result
        session.live_binding=drift
    else:
        calls=[0]
        def coord():
            calls[0]+=1
            return case['permit']['coordinator_identity'] if calls[0]==1 else {'device':2,'inode':91}
        session.coordinator=coord
    with pytest.raises(m.AdmissionBlocked):session.authorize()


def test_expiration_during_source_query_is_rechecked(case,monkeypatch):
    live_window(case);session=FixtureSession(case)
    now=case['now']; calls=[0]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            calls[0]+=1;return cls.fromisoformat((now if calls[0]==1 else now+timedelta(minutes=6)).isoformat())
    monkeypatch.setattr(m,'datetime',Clock)
    with pytest.raises(m.AdmissionBlocked,match='stale'):session.authorize()


@pytest.mark.parametrize('action',['check','install'])
def test_actual_caller_wires_publisher_without_fabricating_enrollment(case,monkeypatch,action):
    live_window(case);events=[]
    class Session(FixtureSession):
        def __init__(self,aid):assert aid==case['permit']['authorization_id'];super().__init__(case)
        @contextmanager
        def hold(self):
            events.append('held')
            try:yield self
            finally:events.append('released')
    monkeypatch.setattr(m,'NativeSession',Session)
    def publish(**kwargs):
        assert events==['held']
        assert kwargs['guard_root']==m.GUARD and kwargs['launch_root']==m.LAUNCH
        assert kwargs['operation_id']==case['permit']['authorization_id']
        assert asdict(kwargs['authorize']())==case['permit']['binding']
        events.append('published-to-modeled-port-only')
        return {'status':'files_installed_unenrolled','enrolled':False,'production_activation_authorized':False}
    monkeypatch.setattr(m.installer,'install_unenrolled',publish)
    result=m.run(action,case['permit']['authorization_id'])
    assert result['enrolled'] is False and result['production_activation_authorized'] is False
    assert events==(['held','released'] if action=='check' else ['held','published-to-modeled-port-only','released'])


@pytest.mark.parametrize('fault',['source','journal'])
def test_native_evidence_changed_during_database_read_cannot_authorize(case,fault):
    live_window(case);session=FixtureSession(case);state={'changed':False}
    old=session.live_binding
    def changed(permit):
        result=old(permit);state['changed']=True;return result
    session.live_binding=changed
    if fault=='source':
        def source(permit):
            if state['changed']:raise m.AdmissionBlocked('source drift after DB read')
        session.source=source
    else:
        session.journal=lambda:b'new journal\n' if state['changed'] else b'{}\n'
    with pytest.raises(m.AdmissionBlocked):session.authorize()


def test_coordinator_name_rechecked_after_native_contention_probe(tmp_path,monkeypatch):
    aid=str(uuid4());authority=tmp_path/'authority';authority.mkdir(mode=0o700);d=authority/aid;d.mkdir(mode=0o700)
    monkeypatch.setattr(m,'AUTHORITY',authority)
    monkeypatch.setattr(m.NativeSession,'require_installed',lambda self:None)
    f=d/'coordinator.lock';f.touch(mode=0o600)
    real=m.subprocess.run
    def replace_after_probe(*args,**kwargs):
        result=real(*args,**kwargs)
        if result.returncode==73:
            f.rename(d/'old-lock');f.touch(mode=0o600)
        return result
    with m.NativeSession(aid).hold() as session:
        monkeypatch.setattr(m.subprocess,'run',replace_after_probe)
        with pytest.raises(m.AdmissionBlocked):session.coordinator()


@pytest.mark.parametrize('fault',[None,'missing','changed'])
def test_supporting_review_files_must_actually_match_referenced_hashes(case,tmp_path,fault):
    session=m.NativeSession(case['permit']['authorization_id']);session.directory=tmp_path
    e=tmp_path/'evidence';e.mkdir(mode=0o700)
    raw=m.prep.canon({'fixture':'synthetic supporting independent review only'})
    digest=m.sha(raw);path=e/(digest+'.json')
    if fault!='missing':path.write_bytes(raw if fault is None else b'changed\n');path.chmod(0o400)
    case['control']['evidence_reference']=digest;case['history']['evidence_reference']=digest
    for v in case['control']['roles'].values():v['evidence_sha256']=digest
    args=[m.prep.canon(case['control']),m.prep.canon(case['history'])]
    if fault:
        with pytest.raises((m.AdmissionBlocked,OSError)):session.supporting_evidence(*args)
    else:assert session.supporting_evidence(*args)=={digest:raw}
