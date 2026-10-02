"""Event eligibility regression. All remote responses are explicit fixtures."""
import copy
import pytest
import test_fr06_source_operator as prior
from fr06_check_evidence_fixture import attach
from scripts.security import fr06_source_operator as m

@pytest.mark.parametrize('action',['source_merge','source_sync'])
@pytest.mark.parametrize('event',['workflow_dispatch','schedule'])
def test_manual_or_scheduled_job_cannot_satisfy_source_gate(action,event):
    req=prior.request(action);image=prior.snapshot(req)
    sha=req.head if action=='source_merge' else req.target
    image['actions_evidence']=attach(image['checks'],sha,event=event,pr=req.pr,base_sha=req.source)
    with pytest.raises(m.SourceBlocked):m.validate_remote(req,image)


@pytest.mark.parametrize('action',['source_merge','source_sync'])
def test_expected_native_event_passes_without_issuing_authority(action):
    req=prior.request(action);image=prior.snapshot(req)
    assert m.validate_remote(req,image)==sorted(m.MINIMUM_CHECKS)


@pytest.mark.parametrize('action',['source_merge','source_sync'])
@pytest.mark.parametrize('event',['workflow_dispatch','schedule','repository_dispatch','workflow_run','pull_request_target','deployment'])
def test_ineligible_or_unsupported_events_block_before_effect_intent(tmp_path,action,event):
    directory=tmp_path/'guard';directory.mkdir(mode=0o700);(directory/'receipts').mkdir(mode=0o700)
    port=prior.FakePort(directory,prior.request(action))
    for pair in port.image['actions_evidence'].values():pair['run']['event']=event
    with pytest.raises(m.SourceBlocked):prior.execute(port)
    assert port.effects==0 and not prior.journal(directory)


@pytest.mark.parametrize('action',['source_merge','source_sync'])
@pytest.mark.parametrize('field,value',[
    ('id',42),('id',True),('name','other'),('head_sha','a'*40),('status','in_progress'),
    ('conclusion','failure'),('run_id',4000),('run_id',True),('run_attempt',2),('run_attempt',True),
    ('check_run_url','https://example.invalid/check-runs/1000'),('run_url','https://example.invalid/actions/runs/3000'),
])
def test_job_binding_and_status_must_match_exact_check(action,field,value):
    req=prior.request(action);image=prior.snapshot(req)
    next(iter(image['actions_evidence'].values()))['job'][field]=value
    with pytest.raises(m.SourceBlocked):m.validate_remote(req,image)


@pytest.mark.parametrize('action',['source_merge','source_sync'])
@pytest.mark.parametrize('field,value',[
    ('id',42),('id',True),('head_sha','a'*40),('status','in_progress'),('conclusion','failure'),
    ('check_suite_id',9999),('check_suite_id',True),('run_attempt',2),('run_attempt',True),
    ('repository',{'full_name':'other/repo'}),('head_repository',{'full_name':'other/repo'}),
    ('repository',None),('head_repository',None),
])
def test_run_repository_suite_attempt_and_status_cannot_be_substituted(action,field,value):
    req=prior.request(action);image=prior.snapshot(req)
    next(iter(image['actions_evidence'].values()))['run'][field]=value
    with pytest.raises(m.SourceBlocked):m.validate_remote(req,image)


@pytest.mark.parametrize('fault',['missing','extra','duplicate_id','missing_id','boolean_id','missing_suite','bad_pair'])
def test_provenance_coverage_must_be_complete_and_unambiguous(fault):
    req=prior.request();image=prior.snapshot(req);proof=image['actions_evidence']
    if fault=='missing':proof.pop(next(iter(proof)))
    elif fault=='extra':proof['999999']=copy.deepcopy(next(iter(proof.values())))
    elif fault=='duplicate_id':image['checks']['check_runs'][1]['id']=image['checks']['check_runs'][0]['id']
    elif fault=='missing_id':image['checks']['check_runs'][0].pop('id')
    elif fault=='boolean_id':image['checks']['check_runs'][0]['id']=True
    elif fault=='missing_suite':image['checks']['check_runs'][0].pop('check_suite')
    else:proof[next(iter(proof))]=None
    with pytest.raises(m.SourceBlocked):m.validate_remote(req,image)


@pytest.mark.parametrize('fault',['none','missing','duplicate','different_pr','different_head','different_base','different_base_sha','malformed','boolean_pr'])
def test_pull_request_run_is_bound_to_its_original_pr_head_and_base(fault):
    req=prior.request();image=prior.snapshot(req)
    run=next(iter(image['actions_evidence'].values()))['run'];prs=run['pull_requests']
    if fault=='none':run['pull_requests']=None
    elif fault=='missing':run['pull_requests']=[]
    elif fault=='duplicate':prs.append(copy.deepcopy(prs[0]))
    elif fault=='different_pr':prs[0]['number']=999
    elif fault=='different_head':prs[0]['head']['sha']='b'*40
    elif fault=='different_base':prs[0]['base']['ref']='other'
    elif fault=='different_base_sha':prs[0]['base']['sha']='b'*40
    elif fault=='boolean_pr':prs[0]['number']=True
    else:prs.append(None)
    with pytest.raises(m.SourceBlocked):m.validate_remote(req,image)


def test_sync_push_from_another_branch_is_not_installed_main_acceptance():
    req=prior.request('source_sync');image=prior.snapshot(req)
    next(iter(image['actions_evidence'].values()))['run']['head_branch']='review'
    with pytest.raises(m.SourceBlocked):m.validate_remote(req,image)


def test_no_legacy_status_only_fallback():
    req=prior.request();image=prior.snapshot(req)
    with pytest.raises(m.SourceBlocked):m.required_checks(image['rules'],image['checks'],req.head)
    image.pop('actions_evidence')
    with pytest.raises(m.SourceBlocked):m.validate_remote(req,image)


def test_native_gets_are_fixed_deduplicated_and_ignore_details_url():
    req=prior.request();image=prior.snapshot(req);proof=image['actions_evidence'];calls=[]
    for check in image['checks']['check_runs']:check['details_url']='https://example.invalid/not-followed'
    def api(endpoint):
        calls.append(endpoint)
        if endpoint.startswith(m.API+'/actions/jobs/'):
            return copy.deepcopy(proof[endpoint.rsplit('/',1)[1]]['job'])
        assert endpoint==m.API+'/actions/runs/3000'
        return copy.deepcopy(next(iter(proof.values()))['run'])
    result=m.collect_actions_evidence(api,image['rules'],image['checks'],req.head)
    assert result==proof and len(calls)==12
    assert calls.count(m.API+'/actions/runs/3000')==1


@pytest.mark.parametrize('fault',['bad_job_id','bad_run_id','bad_run_object','job_not_object','run_not_object','unavailable'])
def test_native_collector_rejects_wrong_or_missing_api_evidence(fault):
    req=prior.request();image=prior.snapshot(req);proof=image['actions_evidence']
    def api(endpoint):
        if fault=='unavailable':raise m.SourceBlocked('fixture API unavailable')
        if '/jobs/' in endpoint:
            value=copy.deepcopy(proof[endpoint.rsplit('/',1)[1]]['job'])
            if fault=='bad_job_id':value['id']=999
            if fault=='bad_run_id':value['run_id']='../other'
            return [] if fault=='job_not_object' else value
        value=copy.deepcopy(next(iter(proof.values()))['run'])
        if fault=='bad_run_object':value['id']=999
        return None if fault=='run_not_object' else value
    with pytest.raises(m.SourceBlocked):m.collect_actions_evidence(api,image['rules'],image['checks'],req.head)


def test_failed_required_status_stops_before_any_provenance_request():
    req=prior.request();image=prior.snapshot(req)
    image['checks']['check_runs'][0]['conclusion']='failure'
    with pytest.raises(m.SourceBlocked):
        m.collect_actions_evidence(lambda endpoint:pytest.fail('no API expected'),image['rules'],image['checks'],req.head)


def test_external_app_check_does_not_invent_an_actions_run_requirement():
    req=prior.request();image=prior.snapshot(req)
    image['rules'][1]['parameters']['required_status_checks'].append({'context':'External gate','integration_id':45678})
    image['checks']['check_runs'].append({'id':9000,'name':'External gate','app':{'id':45678},'head_sha':req.head,'status':'completed','conclusion':'success'})
    image['checks']['total_count']+=1
    assert 'External gate' in m.validate_remote(req,image)


@pytest.mark.parametrize('action',['source_merge','source_sync'])
@pytest.mark.parametrize('manual',[False,True])
def test_native_remote_adapter_carries_fetched_provenance_to_gate(monkeypatch,action,manual):
    import json
    req=prior.request(action);image=prior.snapshot(req);proof=image['actions_evidence']
    if manual:
        for pair in proof.values():pair['run']['event']='workflow_dispatch'
    calls=[]
    class Port(m.NativePort):
        def api(self,endpoint):
            calls.append(endpoint)
            if endpoint==m.API+'/branches/main':return {'commit':{'sha':image['main']}}
            if '/rules/' in endpoint:return copy.deepcopy(image['rules'])
            if '/commits/' in endpoint:return copy.deepcopy(image['checks'])
            if '/actions/jobs/' in endpoint:return copy.deepcopy(proof[endpoint.rsplit('/',1)[1]]['job'])
            assert endpoint==m.API+'/actions/runs/3000'
            return copy.deepcopy(next(iter(proof.values()))['run'])
    def command(args,**kwargs):
        assert args[:3]==['gh','pr','view'] and args[3]==str(req.pr)
        return json.dumps(image['pr'])
    monkeypatch.setattr(m,'command',command)
    remote=Port().remote(req)
    assert remote['actions_evidence']==proof
    assert len(calls)==15
    if manual:
        with pytest.raises(m.SourceBlocked):m.validate_remote(req,remote)
    else:assert m.validate_remote(req,remote)==sorted(m.MINIMUM_CHECKS)
