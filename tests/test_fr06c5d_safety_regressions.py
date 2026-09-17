from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def cutover(tmp_path,monkeypatch):
    spec=spec_from_file_location('c5d_safe',ROOT/'scripts/security/fr06c5_host_state_cutover.py');m=module_from_spec(spec);spec.loader.exec_module(m)
    monkeypatch.setattr(m,'STATE',tmp_path/'state')
    plan={'plan_id':'a'*64,'merge_sha':'b'*40,'topology':{'containers':[{'id':'cid','name':'c','service':'backend','health':'healthy','restart':'unless-stopped'}],'services':{'backend':['cid']},'container_count':36,'project_worker_scale':4}}
    args=SimpleNamespace(plan=tmp_path/'plan.json',evidence=tmp_path/'evidence.json',merge_sha=plan['merge_sha'],confirmation='EXECUTE_FR06C5_HOST_STATE_CUTOVER:'+plan['plan_id'],confirm_production=m.CONFIRM)
    monkeypatch.setattr(m,'loadplan',lambda p,e:dict(plan));monkeypatch.setattr(m,'gitgate',lambda sha:None);monkeypatch.setattr(m,'evidence',lambda p,sha:{});monkeypatch.setattr(m,'c5gate',lambda:None);monkeypatch.setattr(m,'topology',lambda:plan['topology']);monkeypatch.setattr(m,'unresolved_attempt_gate',lambda:None)
    monkeypatch.setattr(m,'reject_nested_mounts',lambda:None);monkeypatch.setattr(m,'precopy',lambda:None);monkeypatch.setattr(m,'watcher_states',lambda:{'watch':True});monkeypatch.setattr(m,'stop_watchers',lambda w:None);monkeypatch.setattr(m,'quiesce_restart_policies',lambda t:None);monkeypatch.setattr(m,'stop_live',lambda t:None);monkeypatch.setattr(m,'seal',lambda p:None);monkeypatch.setattr(m,'exact_copy_and_manifest',lambda:{'x':{}});monkeypatch.setattr(m,'bootstrap_match',lambda:None);monkeypatch.setattr(m,'require_zero_hidden_underlay_fds',lambda:0);monkeypatch.setattr(m,'install_gates',lambda:None);monkeypatch.setattr(m,'restore_restart_policies',lambda t:None);monkeypatch.setattr(m,'restore_watchers',lambda w:None);monkeypatch.setattr(m,'acceptance',lambda t:t)
    events=[]
    def run(argv,*a,**k):
        events.append(tuple(argv))
        if 'fr06c5_host_state_bind.py' in ' '.join(argv) and 'status' in argv:return json.dumps({'validation':'FR06C5_HOST_STATE_BIND_READY'})
        return ''
    monkeypatch.setattr(m,'run',run)
    rb=[];monkeypatch.setattr(m,'rollback_prestart',lambda t,w,phase:rb.append(phase))
    return SimpleNamespace(m=m,args=args,plan=plan,events=events,rollback=rb)

def test_success_persists_candidate_start_before_docker_start(cutover):
    s=cutover;out=s.m.apply(s.args);assert out['status']=='encrypted_host_state_started_admission_closed'
    attempt=json.loads(s.m.attempt_path(s.plan['plan_id']).read_text());assert attempt['phase']=='accepted' and attempt['candidate_start_attempted'] is True
    marker=[i for i,x in enumerate(s.events) if x[:4]==('systemctl','start','docker.socket','docker.service')]
    assert marker

def test_same_plan_cannot_replay_after_success(cutover):
    s=cutover;s.m.apply(s.args);s.events.clear()
    with pytest.raises(s.m.B,match='already attempted'):s.m.apply(s.args)
    assert not s.events

def test_precopy_failure_consumes_plan_without_live_rollback(cutover,monkeypatch):
    s=cutover;monkeypatch.setattr(s.m,'precopy',lambda:(_ for _ in ()).throw(s.m.B('synthetic precopy')))
    with pytest.raises(s.m.E,match='before live mutation'):s.m.apply(s.args)
    assert s.rollback==[]
    attempt=json.loads(s.m.attempt_path(s.plan['plan_id']).read_text());assert attempt['phase']=='failed_before_live_mutation'

def test_policy_phase_failure_rolls_back_and_consumes_plan(cutover,monkeypatch):
    s=cutover;monkeypatch.setattr(s.m,'quiesce_restart_policies',lambda t:(_ for _ in ()).throw(s.m.B('synthetic policy')))
    with pytest.raises(s.m.E,match='legacy runtime restored'):s.m.apply(s.args)
    assert s.rollback==['restart_policy_quiesce_started']
    attempt=json.loads(s.m.attempt_path(s.plan['plan_id']).read_text());assert attempt['phase']=='legacy_restored_prestart'

def test_prestart_rollback_failure_never_claims_restored(cutover,monkeypatch):
    s=cutover;monkeypatch.setattr(s.m,'quiesce_restart_policies',lambda t:(_ for _ in ()).throw(s.m.B('synthetic policy')));monkeypatch.setattr(s.m,'rollback_prestart',lambda t,w,phase:(_ for _ in ()).throw(s.m.B('synthetic rollback')))
    with pytest.raises(s.m.E,match='rollback failed'):s.m.apply(s.args)
    attempt=json.loads(s.m.attempt_path(s.plan['plan_id']).read_text());assert attempt['phase']=='rollback_failed'

def test_candidate_start_attempt_blocks_automatic_rollback(cutover,monkeypatch):
    s=cutover
    def run(argv,*a,**k):
        if 'fr06c5_host_state_bind.py' in ' '.join(argv) and 'status' in argv:return json.dumps({'validation':'FR06C5_HOST_STATE_BIND_READY'})
        if argv[:4]==['systemctl','start','docker.socket','docker.service']:raise s.m.E('synthetic start')
        return ''
    monkeypatch.setattr(s.m,'run',run)
    with pytest.raises(s.m.E,match='blind rollback is prohibited'):s.m.apply(s.args)
    assert s.rollback==[]
    attempt=json.loads(s.m.attempt_path(s.plan['plan_id']).read_text());assert attempt['phase']=='post_start_failure_requires_reconciliation' and attempt['candidate_start_attempted'] is True

@pytest.fixture
def bindmod(tmp_path,monkeypatch):
    spec=spec_from_file_location('c5bind_safe',ROOT/'scripts/security/fr06c5_host_state_bind.py');m=module_from_spec(spec);spec.loader.exec_module(m)
    src=tmp_path/'candidate';dst=tmp_path/'target';src.write_text('candidate');dst.write_text('legacy');monkeypatch.setattr(m,'PAIRS',((src,dst,False),));monkeypatch.setattr(m,'active',lambda u:False);monkeypatch.setattr(m,'vault_ready',lambda:None)
    state={'same':True,'exact':True};monkeypatch.setattr(m,'same',lambda s,d:state['same']);monkeypatch.setattr(m,'exact_mount',lambda d:state['exact'])
    calls=[]
    def run(argv,*a,**k):
        calls.append(tuple(argv))
        if argv[0]=='umount':state['same']=False
        return ''
    monkeypatch.setattr(m,'run',run)
    return SimpleNamespace(m=m,state=state,calls=calls)

def test_bind_rollback_unmounts_only_owned_candidate_layer(bindmod):
    s=bindmod;out=s.m.rollback();assert out['candidate_binds_removed']==1 and out['validation']=='FR06C5_HOST_STATE_BIND_REMOVED';assert s.state['exact'] is True and s.state['same'] is False;assert s.calls==[('umount',str(s.m.PAIRS[0][1]))]

def test_bind_rollback_failure_is_not_reported_success(bindmod,monkeypatch):
    s=bindmod;monkeypatch.setattr(s.m,'run',lambda *a,**k:(_ for _ in ()).throw(s.m.B('synthetic umount')))
    with pytest.raises(s.m.B,match='synthetic'):s.m.rollback()
