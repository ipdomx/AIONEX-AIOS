"""Native read adapter with real disposable Git and modeled GitHub responses.

No production source, permit, trust key, GitHub write or database access occurs.
The existing app-bound protected-check verifier is exercised without mocking it.
"""
from __future__ import annotations
import copy
import os
import subprocess
from pathlib import Path
from uuid import uuid4
import pytest
from fr06_check_evidence_fixture import attach
from scripts.security import fr06_executor_native_install as m
from scripts.security import fr06_source_operator as operator
from scripts.security.fr06_execution_guard import GuardBlocked


@pytest.fixture
def source_case(tmp_path,monkeypatch):
    repo=tmp_path/'repo';repo.mkdir(mode=0o700)
    env={'PATH':'/usr/bin:/bin','HOME':str(tmp_path),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
    def git(*args):
        return subprocess.check_output(['/usr/bin/git','-C',str(repo),*args],env=env,stderr=subprocess.DEVNULL,text=True).strip()
    git('init','-q','-b','main')
    paths=['scripts/security/fr06_executor_native_install.py','scripts/security/fr06_executor_installation.py',
           'scripts/security/fr06_executor_preparation.py','scripts/security/fr06_source_operator.py',
           'scripts/security/fr06_execution_guard.py','scripts/security/fr06_execution_enrollment.py']
    for rel in paths:
        p=repo/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# synthetic native-source fixture only\n');p.chmod(0o644)
    git('add','.')
    git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-qm','synthetic source')
    head=git('rev-parse','HEAD');reviewed='f'*40
    permit={'binding':{'source_commit':head},'source_pr':835,'reviewed_head':reviewed}
    rules=[{'type':'required_status_checks','parameters':{'strict_required_status_checks_policy':True,
            'required_status_checks':[{'context':name,'integration_id':15368} for name in sorted(operator.MINIMUM_CHECKS)]}},
           {'type':'pull_request','parameters':{'required_review_thread_resolution':True,'allowed_merge_methods':['merge']}}]
    checks={'total_count':len(operator.MINIMUM_CHECKS),'check_runs':[
        {'name':name,'app':{'id':15368},'head_sha':head,'status':'completed','conclusion':'success'}
        for name in sorted(operator.MINIMUM_CHECKS)]}
    pr={'number':835,'merged':True,'base':{'ref':'main'},'head':{'sha':reviewed,'repo':{'full_name':m.REPOSITORY}},'merge_commit_sha':head}
    data={'remote':{'commit':{'sha':head}},'pr':pr,'rules':rules,'checks':checks,'local_head':head,'local_main':head,'clean':True,'calls':[]}
    evidence = attach(checks, head, event='push')
    data['actions_evidence'] = evidence
    class Port:
        def local(self):return data['local_head'],data['local_main'],data['clean'] and not bool(git('status','--porcelain'))
        def git(self,*args,**kwargs):return git(*args)
        def api(self,endpoint):
            assert endpoint.startswith(operator.API+'/'), 'native endpoint must obey the existing port contract'
            data['calls'].append(endpoint)
            if '/rules/' in endpoint:return data['rules']
            if endpoint.endswith('/branches/main'):return data['remote']
            if '/pulls/' in endpoint:return data['pr']
            if '/check-runs?' in endpoint:return data['checks']
            if '/actions/jobs/' in endpoint:return copy.deepcopy(evidence[endpoint.rsplit('/',1)[1]]['job'])
            if '/actions/runs/' in endpoint:return copy.deepcopy(next(iter(evidence.values()))['run'])
            raise AssertionError('unexpected native API endpoint')
    monkeypatch.setattr(m,'ROOT',repo)
    monkeypatch.setattr(operator,'NativePort',Port)
    return repo,permit,data


def test_real_source_bytes_and_exact_main_protected_checks_are_consumed(source_case):
    repo,permit,data=source_case
    assert m.NativeSession(str(uuid4())).source(permit) is None
    assert len(data['calls'])==4+len(operator.MINIMUM_CHECKS)+1
    assert sum('/actions/runs/' in x for x in data['calls'])==1
    assert any('/commits/'+permit['binding']['source_commit']+'/check-runs?' in x for x in data['calls'])


@pytest.mark.parametrize('fault',['remote_head','not_merged','base_branch','reviewed_head','merge_sha','check_fail','check_app','check_sha','check_missing','rules_empty','weak_rules','dirty_source','mode','symlink'])
def test_native_source_gate_rejects_changed_or_unprotected_state(source_case,fault):
    repo,permit,data=source_case
    if fault=='remote_head':data['remote']['commit']['sha']='b'*40
    elif fault=='not_merged':data['pr']['merged']=False
    elif fault=='base_branch':data['pr']['base']['ref']='review'
    elif fault=='reviewed_head':data['pr']['head']['sha']='b'*40
    elif fault=='merge_sha':data['pr']['merge_commit_sha']='b'*40
    elif fault=='check_fail':data['checks']['check_runs'][0]['conclusion']='failure'
    elif fault=='check_app':data['checks']['check_runs'][0]['app']['id']=1
    elif fault=='check_sha':data['checks']['check_runs'][0]['head_sha']='b'*40
    elif fault=='check_missing':data['checks']['check_runs'].pop()
    elif fault=='rules_empty':data['rules']=[]
    elif fault=='weak_rules':data['rules'][0]['parameters']['strict_required_status_checks_policy']=False
    elif fault=='dirty_source':(repo/'unrelated.txt').write_text('retained untracked file')
    elif fault=='mode':(repo/'scripts/security/fr06_executor_native_install.py').chmod(0o666)
    else:
        p=repo/'scripts/security/fr06_executor_native_install.py';p.rename(p.with_name('kept'));p.symlink_to(p.with_name('kept'))
    with pytest.raises((m.AdmissionBlocked,GuardBlocked)):
        m.NativeSession(str(uuid4())).source(permit)


def test_native_caller_reaches_real_file_publisher_only_in_signed_disposable_lab(source_case,tmp_path,monkeypatch):
    from dataclasses import asdict
    from datetime import datetime,timedelta,timezone
    from scripts.security.fr06_execution_guard import Binding
    repo,old_permit,data=source_case;port=operator.NativePort()
    for name,(rel,mode) in m.prep.PAYLOAD.items():
        path=repo/rel
        if not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# synthetic role launcher, never executed\n')
        path.chmod(int(mode[-3:],8))
    port.git('add','.')
    port.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-qm','synthetic launcher payload')
    head=port.git('rev-parse','HEAD')
    data.update(local_head=head,local_main=head)
    data['remote']['commit']['sha']=head;data['pr']['merge_commit_sha']=head
    for check in data['checks']['check_runs']:check['head_sha']=head
    for pair in data['actions_evidence'].values():
        pair['job']['head_sha']=head;pair['run']['head_sha']=head
    (repo/'.git/info/exclude').write_text('/docs/project/runtime/\n')
    runtime=repo/'docs/project/runtime';runtime.mkdir(parents=True)
    (runtime/'events.jsonl').write_bytes(b'{}\n');(runtime/'events.jsonl').chmod(0o644)
    roots={name:tmp_path/name for name in ['TRUST','AUTHORITY','STORE','JOURNALS']}
    for name,path in roots.items():path.mkdir(mode=0o700);monkeypatch.setattr(m,name,path)
    gp=tmp_path/'guard-parent';gp.mkdir(mode=0o700)
    lp=tmp_path/'launch-parent';lp.mkdir(mode=0o700)
    monkeypatch.setattr(m,'GUARD',gp/'new-guard');monkeypatch.setattr(m,'LAUNCH',lp/'new-launch')
    aid=str(uuid4());pid=str(uuid4());ad=m.AUTHORITY/aid;ad.mkdir(mode=0o700)
    (m.JOURNALS/aid).mkdir(mode=0o700)
    lock=ad/'coordinator.lock';lock.touch(mode=0o600)
    ident={'device':lock.stat().st_dev,'inode':lock.stat().st_ino}
    binding=Binding(head,head,str(uuid4()),str(uuid4()),41,True,'closed')
    m.prep.prepare(source_root=repo,source_commit=head,store=m.STORE,operation_id=pid)
    anchor={'byte_count':3,'sha256':m.sha(b'{}\n')}
    c={'schema':'aionex.fr06-independent-install-control.v1','authorization_id':aid,
       'binding':asdict(binding),'coordinator_identity':ident,'roles':{
         role:{'task_id':task,'disposition':'fenced_for_this_installation','evidence_sha256':'b'*64}
         for role,task in m.ROLES.items()},'evidence_reference':'c'*64}
    h={'schema':'aionex.fr06-independent-history-review.v1','authorization_id':aid,
       'journal_anchor':anchor,'disposition':'effects_reconciled','unresolved_runs':[],'evidence_reference':'d'*64}
    supporting=m.prep.canon({'fixture':'synthetic independent history and role-fencing review'})
    supporting_digest=m.sha(supporting);(ad/'evidence').mkdir(mode=0o700)
    supporting_path=ad/'evidence'/(supporting_digest+'.json');supporting_path.write_bytes(supporting);supporting_path.chmod(0o400)
    c['evidence_reference']=supporting_digest;h['evidence_reference']=supporting_digest
    for role in c['roles'].values():role['evidence_sha256']=supporting_digest
    now=datetime.now(timezone.utc)
    permit={'schema':m.SCHEMA,'authorization_id':aid,'task_id':m.TASK,'repository':m.REPOSITORY,
        'action':'initial_install_unenrolled','binding':asdict(binding),'source_pr':835,'reviewed_head':old_permit['reviewed_head'],
        'preparation_id':pid,'issued_at':(now-timedelta(seconds=1)).isoformat(),
        'expires_at':(now+timedelta(minutes=10)).isoformat(),'coordinator_identity':ident,
        'journal_anchor':anchor,'control_sha256':m.sha(m.prep.canon(c)),'history_sha256':m.sha(m.prep.canon(h))}
    for name,value in [('permit.json',permit),('control-evidence.json',c),('history-evidence.json',h)]:
        q=ad/name;q.write_bytes(m.prep.canon(value));q.chmod(0o400)
    key=tmp_path/'synthetic-test-private.pem'
    subprocess.run(['/usr/bin/openssl','genpkey','-algorithm','Ed25519','-out',str(key)],
                   env=m.ENV,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    public=subprocess.check_output(['/usr/bin/openssl','pkey','-in',str(key),'-pubout'],env=m.ENV,stderr=subprocess.DEVNULL)
    (m.TRUST/'owner-ed25519.pub').write_bytes(public);(m.TRUST/'owner-ed25519.pub').chmod(0o400)
    sig=subprocess.check_output(['/usr/bin/openssl','pkeyutl','-sign','-inkey',str(key),'-rawin','-in',str(ad/'permit.json')],
                                env=m.ENV,stderr=subprocess.DEVNULL)
    (ad/'permit.sig').write_bytes(sig);(ad/'permit.sig').chmod(0o400)
    # The ONLY modeled installation/DB boundaries. Git/files/signatures/flock,
    # native API parsing and the journaled publisher are the real implementations.
    monkeypatch.setattr(m.NativeSession,'require_installed',lambda self:None)
    monkeypatch.setattr(m.NativeSession,'live_binding',lambda self,p:binding)
    assert m.run('check',aid)['files_installed'] is False
    assert not m.GUARD.exists() and not m.LAUNCH.exists()
    result=m.run('install',aid)
    assert result['status']=='files_installed_unenrolled'
    assert result['enrolled'] is False and result['production_activation_authorized'] is False
    assert set(q.name for q in m.GUARD.iterdir())=={'execution.lock','receipts'}
    assert set(q.name for q in m.LAUNCH.iterdir())==set(m.installer.ROUTES)
    before={q.name:q.stat().st_mtime_ns for q in m.LAUNCH.iterdir()}
    with pytest.raises(m.installer.InstallationBlocked):m.run('install',aid)
    assert before=={q.name:q.stat().st_mtime_ns for q in m.LAUNCH.iterdir()}


@pytest.mark.parametrize('event',['workflow_dispatch','schedule','pull_request'])
def test_native_install_source_rejects_non_main_push_checks(source_case,event):
    repo,permit,data=source_case
    for pair in data['actions_evidence'].values():pair['run']['event']=event
    with pytest.raises(GuardBlocked):m.NativeSession(str(uuid4())).source(permit)
