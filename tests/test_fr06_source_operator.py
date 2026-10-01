"""Fixed source dispatcher integration: synthetic GitHub, real flock and isolated Git.

No test contacts GitHub, Docker, a provider, a live guard directory or production.
Invocation labels below are synthetic fixture roles, never scheduled-run receipts.
"""
from __future__ import annotations
import copy
import json
import multiprocessing
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.security import fr06_source_operator as m
from scripts.security.fr06_execution_guard import ConcurrentOwner, UncertainEffect, ExecutionGuard
OLD, HEAD, NEW='7'*40,'8'*40,'9'*40
BOOT, OP='00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000002'


def request(action='source_merge'):
    return m.Request(action,835,HEAD,OLD,HEAD if action=='source_merge' else NEW,BOOT,OP,41)


def snapshot(req):
    sync=req.action=='source_sync'
    return {'main':req.target if sync else req.source,
      'pr':{'number':835,'baseRefName':'main','headRefOid':req.head,'baseRefOid':req.source,
            'state':'MERGED' if sync else 'OPEN','isDraft':False,'mergeStateStatus':'CLEAN',
            'mergeable':'MERGEABLE','reviewDecision':'','mergeCommit':{'oid':req.target} if sync else None},
      'rules':[{'type':'pull_request','parameters':{'allowed_merge_methods':['merge'],
                'required_review_thread_resolution':True}},
               {'type':'required_status_checks','parameters':{'strict_required_status_checks_policy':True,
                'required_status_checks':[{'context':name,'integration_id':15368} for name in sorted(m.MINIMUM_CHECKS)]}}],
      'checks':{'total_count':11,'check_runs':[{'name':name,'app':{'id':15368},
                'head_sha':req.target if sync else req.head,'status':'completed','conclusion':'success'}
                 for name in sorted(m.MINIMUM_CHECKS)]}}


class FakePort:
    def __init__(self, directory, req):
        self.guard_root=directory
        self.req=req
        self.current=req.source
        self.clean=True
        self.image=snapshot(req)
        self.calls=[]
        self.saved=[]
        self.enrolled=True
        self.effects=0
        self.fetched=False
        self.remote_hook=None
        self.enroll_hook=None
        self.merge_hook=None
        self.sync_hook=None
        self.save_hook=None
        self.auth={'operation_id':OP,'generation':41,'status':'closed','enabled':False,'full_host_closure':False}
    def enrollment(self, req):
        self.calls.append('enrollment')
        if self.enroll_hook: self.enroll_hook()
        m.need(self.enrolled,'not enrolled')
    def local(self):
        self.calls.append('local')
        return self.current,self.current,self.clean
    def authority(self,req):
        self.calls.append('authority')
        return BOOT,copy.deepcopy(self.auth)
    def remote(self,req):
        self.calls.append('remote')
        if self.remote_hook: self.remote_hook()
        return copy.deepcopy(self.image)
    def fetch_target(self,req):
        self.calls.append('fetch'); self.fetched=True
    def merge(self,req):
        self.calls.append('merge'); self.effects+=1
        if self.merge_hook: self.merge_hook()
    def fast_forward(self,req):
        self.calls.append('ff'); self.effects+=1
        self.current=req.target
        if self.sync_hook: self.sync_hook()
    def merge_observation(self,req):
        self.calls.append('merge_observation')
        return {'pr':req.pr,'head':req.head,'merge_commit':NEW,'remote_main':NEW,
                'source_synced':False,'deployment_accepted':False}
    def save(self,doc):
        self.calls.append('save')
        if self.save_hook: self.save_hook()
        self.saved.append(doc)
        import hashlib
        return hashlib.sha256(m.canonical(doc)).hexdigest()


@pytest.fixture
def directory(tmp_path):
    d=tmp_path/'guard';d.mkdir(mode=0o700);(d/'receipts').mkdir(mode=0o700);return d


def execute(port,req=None,kind='interactive',run='fixture-one'):
    return m.execute(req or port.req,run_id=run,invocation_type=kind,port=port)


def journal(directory):
    p=directory/'effects.jsonl'
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.mark.parametrize('kind',['interactive','scheduled','watchdog'])
@pytest.mark.parametrize('action',['source_merge','source_sync'])
def test_all_fixed_invocation_routes_hold_one_guard_through_effect(directory,kind,action):
    p=FakePort(directory,request(action))
    def locked():
        with pytest.raises(ConcurrentOwner):
            with ExecutionGuard(directory,run_id='other',invocation_type='watchdog'): pass
        assert journal(directory)[-1]['kind']=='intent'
    p.merge_hook=locked;p.sync_hook=locked;p.save_hook=locked
    result=execute(p,kind=kind)
    assert p.effects==1 and len(p.saved)==1
    assert result['payload']['outcome']=='observed_complete'
    assert [e['kind'] for e in journal(directory)]==['intent','result']
    assert p.saved[0]['production_deployed'] is False
    assert p.saved[0]['observations']['deployment_accepted'] is False
    if action=='source_sync':
        b=journal(directory)[0]['payload']['binding']
        assert b['source_commit']==OLD and b['local_main_commit']==OLD and b['main_commit']==NEW
        assert p.calls.index('fetch') < p.calls.index('ff')


def test_missing_enrollment_makes_no_guard_journal_or_effect(directory):
    p=FakePort(directory,request());p.enrolled=False
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==0 and not (directory/'execution.lock').exists()


def test_enrollment_changed_while_entering_lock_is_rejected(directory):
    p=FakePort(directory,request());n=0
    def changed():
        nonlocal n;n+=1
        if n>=2:p.enrolled=False
    p.enroll_hook=changed
    with pytest.raises(m.SourceBlocked):execute(p)
    assert not journal(directory) and p.effects==0


@pytest.mark.parametrize('path,value',[
    (('main',),'0'*40), (('pr','headRefOid'),'0'*40), (('pr','baseRefOid'),'0'*40),
    (('pr','baseRefName'),'other'),(('pr','state'),'CLOSED'),(('pr','isDraft'),True),
    (('pr','mergeStateStatus'),'BEHIND'),(('pr','mergeable'),'UNKNOWN'),
    (('pr','reviewDecision'),'REVIEW_REQUIRED'),(('pr','number'),836),
])
def test_live_pr_drift_does_not_write_an_intent(directory,path,value):
    p=FakePort(directory,request());x=p.image
    for key in path[:-1]:x=x[key]
    x[path[-1]]=value
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==0 and not journal(directory)


@pytest.mark.parametrize('field,value',[('head_sha','0'*40),('status','in_progress'),('conclusion','failure')])
def test_old_head_or_pending_or_failed_checks_do_not_accept(directory,field,value):
    p=FakePort(directory,request());p.image['checks']['check_runs'][0][field]=value
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==0 and not journal(directory)


@pytest.mark.parametrize('change',['wrong_app','missing','duplicate','partial','strict_off','review_rule_missing','checks_weakened'])
def test_check_and_protection_identity_gates(directory,change):
    p=FakePort(directory,request());s=p.image;c=s['checks'];rules=s['rules']
    if change=='wrong_app':c['check_runs'][0]['app']['id']=999
    if change=='missing':c['check_runs'].pop();c['total_count']-=1
    if change=='duplicate':c['check_runs'].append(copy.deepcopy(c['check_runs'][0]));c['total_count']+=1
    if change=='partial':c['total_count']+=1
    if change=='strict_off':rules[1]['parameters']['strict_required_status_checks_policy']=False
    if change=='review_rule_missing':rules.pop(0)
    if change=='checks_weakened':rules[1]['parameters']['required_status_checks'].pop()
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==0


def test_extra_required_context_is_also_enforced(directory):
    p=FakePort(directory,request());p.image['rules'][1]['parameters']['required_status_checks'].append({'context':'New gate','integration_id':15368})
    with pytest.raises(m.SourceBlocked):execute(p)
    assert not journal(directory)
    p.image['checks']['check_runs'].append({'name':'New gate','app':{'id':15368},'head_sha':HEAD,'status':'completed','conclusion':'success'})
    p.image['checks']['total_count']+=1
    execute(p); assert p.effects==1


@pytest.mark.parametrize('field,value',[('generation',42),('generation',True),('operation_id',BOOT),('status','open'),('enabled',True),('full_host_closure',True)])
def test_authority_drift_prevents_effect(directory,field,value):
    p=FakePort(directory,request());p.auth[field]=value
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==0 and not journal(directory)


def test_dirty_source_never_fetches_or_merges(directory):
    p=FakePort(directory,request());p.clean=False
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==0 and not journal(directory)


def test_current_head_changes_after_intent_retains_uncertainty(directory):
    p=FakePort(directory,request());n=0
    def change():
        nonlocal n;n+=1
        if n>=3:p.image['pr']['headRefOid']='a'*40
    p.remote_hook=change
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==0 and [x['kind'] for x in journal(directory)]==['intent']
    p.remote_hook=None;p.image=snapshot(p.req)
    with pytest.raises(UncertainEffect):execute(p,run='successor')
    assert p.effects==0


def test_network_timeout_is_unknown_not_no_effect_or_replayed(directory):
    p=FakePort(directory,request())
    def timeout():raise m.SourceBlocked('timeout outcome unknown')
    p.merge_hook=timeout
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==1 and len(journal(directory))==1
    p.merge_hook=None
    with pytest.raises(UncertainEffect):execute(p,run='next-hour',kind='scheduled')
    assert p.effects==1


def test_receipt_write_failure_after_merge_leaves_intent(directory):
    p=FakePort(directory,request());p.save_hook=lambda:(_ for _ in ()).throw(OSError('fixture failure'))
    with pytest.raises(OSError):execute(p)
    assert p.effects==1 and len(journal(directory))==1


def test_sync_requires_exact_merged_head_target_and_main_checks(directory):
    p=FakePort(directory,request('source_sync'));p.image['pr']['mergeCommit']['oid']='a'*40
    with pytest.raises(m.SourceBlocked):execute(p)
    assert not p.fetched and p.effects==0


def test_postfetch_drift_prevents_fast_forward(directory):
    p=FakePort(directory,request('source_sync'))
    def change():
        if p.fetched:p.image['main']='a'*40
    p.remote_hook=change
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.fetched and p.effects==0 and len(journal(directory))==1


def test_postsynchronization_authority_drift_is_not_accepted(directory):
    p=FakePort(directory,request('source_sync'));p.sync_hook=lambda:p.auth.update(generation=42)
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==1 and len(journal(directory))==1 and p.saved==[]


def test_uninstalled_native_operator_cannot_execute(directory):
    with pytest.raises(m.SourceBlocked,match='uninstalled|root-owned'):
        m.NativePort().enrollment(request())


@pytest.mark.parametrize('value',['{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}','{'])
def test_json_parser_rejects_ambiguous_data(value):
    with pytest.raises(m.GuardBlocked):m.decode(value)


def git(path,*args):
    r=subprocess.run(['git','-C',str(path),*args],text=True,capture_output=True,check=False,timeout=15)
    if r.returncode:raise m.SourceBlocked('synthetic git command failed')
    return r.stdout.strip()


@pytest.fixture
def repositories(tmp_path):
    upstream=tmp_path/'upstream';upstream.mkdir();git(upstream,'init','-b','main')
    git(upstream,'config','user.name','fixture');git(upstream,'config','user.email','fixture@example.invalid')
    (upstream/'content.txt').write_text('initial\n');git(upstream,'add','content.txt');git(upstream,'commit','-m','initial')
    source=git(upstream,'rev-parse','HEAD')
    local=tmp_path/'local';git(tmp_path,'clone',str(upstream),str(local))
    (upstream/'content.txt').write_text('successor\n');git(upstream,'commit','-am','successor')
    target=git(upstream,'rev-parse','HEAD')
    return upstream,local,source,target


class LocalGitPort(FakePort):
    def __init__(self,directory,req,local):
        super().__init__(directory,req);self.path=local
    def git(self,*args,timeout=30):return git(self.path,*args)
    def local(self):return self.git('rev-parse','HEAD'),self.git('rev-parse','refs/heads/main'),not bool(self.git('status','--porcelain=v1'))
    def fetch_target(self,req):
        self.fetched=True;m.NativePort.fetch_target(self,req)
    def fast_forward(self,req):
        self.effects+=1;m.NativePort.fast_forward(self,req)


def test_real_git_clean_fast_forward_with_distinct_remote_target(directory,repositories):
    upstream,local,old,new=repositories
    req=replace(request('source_sync'),source=old,target=new)
    p=LocalGitPort(directory,req,local)
    # The remote API is synthetic; Git object transfer and local ff are real.
    execute(p)
    assert git(local,'rev-parse','HEAD')==new
    assert not git(local,'status','--porcelain=v1')
    assert (local/'content.txt').read_text()=='successor\n'
    assert p.effects==1 and len(journal(directory))==2
    b=journal(directory)[0]['payload']['binding']
    assert b['source_commit']==old and b['main_commit']==new


def test_real_git_preserves_unrelated_untracked_work(directory,repositories):
    _,local,old,new=repositories
    (local/'unrelated.txt').write_text('do not delete\n')
    p=LocalGitPort(directory,replace(request('source_sync'),source=old,target=new),local)
    with pytest.raises(m.SourceBlocked):execute(p)
    assert git(local,'rev-parse','HEAD')==old and (local/'unrelated.txt').read_text()=='do not delete\n'
    assert not p.fetched and p.effects==0


def test_real_git_non_forward_target_never_resets(directory,repositories):
    upstream,local,old,new=repositories
    git(local,'config','user.name','fixture');git(local,'config','user.email','fixture@example.invalid')
    (local/'only-local.txt').write_text('preserve\n');git(local,'add','only-local.txt');git(local,'commit','-m','local divergence')
    diverged=git(local,'rev-parse','HEAD')
    p=LocalGitPort(directory,replace(request('source_sync'),source=diverged,target=new),local)
    with pytest.raises(m.SourceBlocked):execute(p)
    assert git(local,'rev-parse','HEAD')==diverged and (local/'only-local.txt').exists()
    assert p.effects==0 and len(journal(directory))==1


def test_real_git_operator_self_update_requires_new_bootstrap(directory,repositories):
    upstream,local,old,_=repositories
    f=upstream/'scripts/security/fr06_source_operator.py';f.parent.mkdir(parents=True);f.write_text('# changed dispatcher\n')
    git(upstream,'add','.');git(upstream,'commit','-m','operator delta')
    new=git(upstream,'rev-parse','HEAD')
    p=LocalGitPort(directory,replace(request('source_sync'),source=old,target=new),local)
    with pytest.raises(m.SourceBlocked,match='self-update'):execute(p)
    assert git(local,'rev-parse','HEAD')==old and p.effects==0


def child_contend(directory,queue):
    try:
        execute(FakePort(Path(directory),request()),kind='watchdog',run='fixture-child')
        queue.put('wrong-effect')
    except ConcurrentOwner:queue.put('concurrent_owner')
    except BaseException as e:queue.put(type(e).__name__)


def test_actual_child_route_cannot_enter_during_parent_dispatch(directory):
    p=FakePort(directory,request());ctx=multiprocessing.get_context('fork');queue=ctx.Queue()
    def compete():
        child=ctx.Process(target=child_contend,args=(str(directory),queue));child.start();child.join(5)
        assert not child.is_alive() and child.exitcode==0
        assert queue.get(timeout=2)=='concurrent_owner'
    p.merge_hook=compete
    execute(p,kind='scheduled')
    assert p.effects==1 and len(journal(directory))==2


def test_native_command_joins_its_timed_out_owned_child(monkeypatch,tmp_path):
    monkeypatch.setattr(m,'ROOT',tmp_path)
    with pytest.raises(m.SourceBlocked,match='timed out'):
        m.command([sys.executable,'-c','import time; time.sleep(30)'],timeout=0.05)


def test_command_failure_does_not_leak_stderr(monkeypatch,tmp_path):
    monkeypatch.setattr(m,'ROOT',tmp_path)
    with pytest.raises(m.SourceBlocked) as exc:
        m.command([sys.executable,'-c','import sys;sys.stderr.write("SYNTHETIC_PRIVATE_CANARY");sys.exit(1)'])
    assert 'SYNTHETIC_PRIVATE_CANARY' not in str(exc.value)


def test_fixed_native_merge_has_expected_sha_no_bypass(monkeypatch):
    calls=[]
    monkeypatch.setattr(m,'command',lambda args,**kwargs:calls.append(args) or json.dumps({'merged':True,'sha':NEW}))
    m.NativePort().merge(request())
    assert len(calls)==1
    assert calls[0]==['gh','api','--hostname','github.com','--method','PUT',m.API+'/pulls/835/merge','-f','sha='+HEAD,'-f','merge_method=merge']
    assert '--admin' not in calls[0]


def test_native_merge_refusal_remains_a_failure(monkeypatch):
    monkeypatch.setattr(m,'command',lambda *a,**k:json.dumps({'merged':False,'message':'fixture refusal'}))
    with pytest.raises(m.SourceBlocked):m.NativePort().merge(request())


@pytest.mark.parametrize('field,value',[('generation',42),('operation_id',BOOT),('full_host_closure',True)])
def test_postmerge_authority_drift_is_not_success(directory,field,value):
    p=FakePort(directory,request());p.merge_hook=lambda:p.auth.update({field:value})
    with pytest.raises(m.SourceBlocked):execute(p)
    assert p.effects==1 and len(journal(directory))==1 and not p.saved


def test_postmerge_local_source_changed_is_not_success(directory):
    p=FakePort(directory,request());p.merge_hook=lambda:setattr(p,'current','a'*40)
    with pytest.raises(m.SourceBlocked):execute(p)
    assert len(journal(directory))==1 and not p.saved


def test_missing_review_decision_not_accepted_when_approval_is_required(directory):
    p=FakePort(directory,request())
    p.image['rules'][0]['parameters']['required_approving_review_count']=1
    p.image['pr'].pop('reviewDecision')
    with pytest.raises(m.SourceBlocked):execute(p)
    assert not journal(directory)


def test_real_git_existing_hook_is_preserved_and_not_executed(directory,repositories):
    _,local,old,new=repositories
    hook=local/'.git/hooks/post-merge';marker=local.parent/'hook-effect'
    hook.write_text('#!/bin/sh\nprintf forbidden > '+str(marker)+'\n');hook.chmod(0o755)
    p=LocalGitPort(directory,replace(request('source_sync'),source=old,target=new),local)
    with pytest.raises(m.SourceBlocked):execute(p)
    assert not marker.exists() and hook.exists() and git(local,'rev-parse','HEAD')==old


def test_real_git_external_hook_configuration_is_not_bypassed(directory,repositories):
    _,local,old,new=repositories
    hooks=local.parent/'external-hooks';hooks.mkdir()
    git(local,'config','core.hooksPath',str(hooks))
    p=LocalGitPort(directory,replace(request('source_sync'),source=old,target=new),local)
    with pytest.raises(m.SourceBlocked):execute(p)
    assert git(local,'config','--get','core.hooksPath')==str(hooks)
    assert git(local,'rev-parse','HEAD')==old


@pytest.mark.parametrize('kind,name',list(m.LAUNCHERS.items()))
def test_launcher_roles_are_fixed_last_and_share_exact_operator(tmp_path,kind,name):
    source=ROOT/'deploy/bin'/name
    script=source.read_text()
    literal='/usr/bin/python3 -I /opt/AIOS/scripts/security/fr06_source_operator.py'
    assert script.count(literal)==1 and '"$@" --invocation-type '+kind in script
    assert source.stat().st_mode & 0o111 == 0o111
    subprocess.run(['sh','-n',str(source)],check=True,capture_output=True,timeout=5)
    # Exercise ONLY a scratch copy retargeted to an argv recorder, never /opt/AIOS.
    recorder=tmp_path/'args.py';recorder.write_text('import sys,json;print(json.dumps(sys.argv[1:]))\n')
    fixture=tmp_path/'fixture.sh';fixture.write_text(script.replace(literal,sys.executable+' '+str(recorder)))
    r=subprocess.run(['sh',str(fixture),'source_sync','--invocation-type','spoofed'],check=True,
                     capture_output=True,text=True,timeout=5)
    args=json.loads(r.stdout)
    assert args[-2:]==['--invocation-type',kind]


def test_postsync_full_closure_flag_drift_is_not_accepted(directory):
    p=FakePort(directory,request('source_sync'));p.sync_hook=lambda:p.auth.update(full_host_closure=True)
    with pytest.raises(m.SourceBlocked):execute(p)
    assert len(journal(directory))==1 and not p.saved


def test_native_receipt_writer_retains_only_supplied_sanitized_source_result(monkeypatch,directory):
    monkeypatch.setattr(m,'GUARD_ROOT',directory)
    payload={'schema':'fixture-source-observation','source_commit':OLD,'production_deployed':False}
    digest=m.NativePort().save(payload)
    files=list((directory/'receipts').iterdir())
    assert len(files)==1 and json.loads(files[0].read_text())==payload
    import hashlib
    assert digest==hashlib.sha256(files[0].read_bytes()).hexdigest()
    assert files[0].stat().st_mode & 0o777 == 0o600
