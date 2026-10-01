"""Synthetic enrollment records, real disposable flock processes, no production I/O.

All role labels are test fixtures, not actual scheduled/watchdog enrollment.
"""
from __future__ import annotations

import copy
import json
import multiprocessing
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.security import fr06_execution_enrollment as m
from scripts.security.fr06_execution_guard import ExecutionGuard, ConcurrentOwner

AT = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)
BIND = {'source_commit': '7'*40, 'boot_id': '00000000-0000-4000-8000-000000000001',
        'operation_id': '00000000-0000-4000-8000-000000000002', 'generation': 41}
IDENT = {'device': 1, 'inode': 2, 'lock_device': 1, 'lock_inode': 3}
CHALLENGE = '00000000-0000-4000-8000-000000000003'


def fixtures():
    events, roles, references = [], {}, {}
    for n, role in enumerate(m.ROUTES):
        rid = role+'-enroll-fixture'; task = m.WATCHDOG if role == 'watchdog' else m.TASK
        base = {'schema': 'aionex.fr06-route-enrollment-run.v1', 'run_id': rid, 'task_id': task,
                'invocation_type': role, **BIND}
        proof = {'schema': 'aionex.fr06-route-probe.v1', 'challenge': '00000000-0000-4000-8000-'+str(n+10).zfill(12),
                 'invocation_type': role, 'guard_identity': copy.deepcopy(IDENT), 'pid': 10+n,
                 'at': (AT+timedelta(seconds=1)).isoformat(), 'result': 'kernel_contention_observed'}
        roles[role] = {'probe': m.canon(proof), 'started': m.canon({**base, 'phase': 'started', 'at': AT.isoformat()})}
        roles[role]['terminal'] = m.canon({**base, 'phase': 'terminal', 'at': (AT+timedelta(seconds=2)).isoformat(),
                                           'probe_sha256': m.hexdigest(roles[role]['probe'])})
        ref = {'run_id': rid}
        for phase in ('started', 'terminal'):
            eid = rid+'-'+phase
            ref[phase+'_event_id'] = eid
            events.append({'event_id': eid, 'at': AT.isoformat() if phase=='started' else (AT+timedelta(seconds=2)).isoformat(), 'run_id': rid, 'run_phase': phase, 'event_type': 'fr06_route_enrollment',
                           'invocation_type': role, 'automation_task_id': task, 'source_commit': BIND['source_commit'],
                           'evidence': [(m.RUNTIME/rid/(phase+'.json')).as_posix()]})
        for kind, raw in roles[role].items(): ref[kind+'_sha256'] = m.hexdigest(raw)
        references[role] = ref
    journal = b''.join(m.canon(e) for e in events)
    bootstrap = {'schema': 'aionex.fr06-executor-bootstrap.v1', 'task_id': m.TASK, **BIND,
                 'guard_identity': copy.deepcopy(IDENT), 'journal_anchor': {'byte_count': len(journal), 'sha256': m.hexdigest(journal)},
                 'routes': references}
    raw = m.canon(bootstrap)
    enrollment = {'schema': 'aionex.fr06-fixed-source-enrollment.v1', 'task_id': m.TASK, **BIND,
                  'guard_directory': str(m.GUARD), 'launchers': {role: '8'*64 for role in m.ROUTES},
                  'bootstrap_evidence_sha256': m.hexdigest(raw)}
    return dict(enrollment=enrollment, bootstrap_raw=raw, journal_raw=journal, role_bytes=roles,
                live_binding=copy.deepcopy(BIND), guard_identity=copy.deepcopy(IDENT), now=AT+timedelta(seconds=3))


def rewrite_bootstrap(f, edit):
    b = m.decode(f['bootstrap_raw']); edit(b); f['bootstrap_raw'] = m.canon(b)
    f['enrollment']['bootstrap_evidence_sha256'] = m.hexdigest(f['bootstrap_raw'])


def rewrite_role(f, role, phase, edit):
    x = m.decode(f['role_bytes'][role][phase]); edit(x); raw = m.canon(x)
    f['role_bytes'][role][phase] = raw
    rewrite_bootstrap(f, lambda b: b['routes'][role].update({phase+'_sha256': m.hexdigest(raw)}))


def rewrite_journal(f, events):
    raw = b''.join(m.canon(e) for e in events); f['journal_raw'] = raw
    rewrite_bootstrap(f, lambda b: b.update(journal_anchor={'byte_count': len(raw), 'sha256': m.hexdigest(raw)}))


def test_exact_bundle_checks_raw_receipts_not_booleans():
    x = m.verify_bundle(**fixtures())
    assert x['roles'] == sorted(m.ROUTES) and x['activation_authority_issued'] is False
    assert 'authorized' not in x and x['source_commit'] == BIND['source_commit']


@pytest.mark.parametrize('field,value', [('source_commit', '$head'), ('source_commit', '8'*40),
    ('boot_id', '00000000-0000-4000-8000-000000000009'), ('operation_id', 'invalid'),
    ('generation', True), ('generation', 42), ('generation', 7)])
def test_live_context_must_match(field, value):
    f = fixtures(); f['live_binding'][field] = value
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


@pytest.mark.parametrize('field,value', [('task_id', 'other'), ('guard_directory', '/tmp/guard'),
    ('bootstrap_evidence_sha256', '0'*64), ('launchers', {}), ('launchers', []),
    ('generation', 1), ('source_commit', '8'*40), ('schema', 'fake')])
def test_enrollment_flags_or_wrong_binding_cannot_authorize(field, value):
    f = fixtures(); f['enrollment'][field] = value
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


def test_approval_true_flags_are_not_an_enrollment_contract():
    f = fixtures(); f['enrollment'].update(approved=True, all_routes_enrolled=True)
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


@pytest.mark.parametrize('field,value', [('schema', 'other'), ('task_id', 'other'),
    ('guard_identity', None), ('guard_identity', {**IDENT, 'lock_inode': 4}), ('routes', {}),
    ('journal_anchor', {'byte_count': True, 'sha256': '9'*64}), ('generation', 42)])
def test_rehashing_invalid_bootstrap_does_not_accept(field, value):
    f = fixtures(); rewrite_bootstrap(f, lambda b: b.update({field: value}))
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


@pytest.mark.parametrize('role', list(m.ROUTES))
@pytest.mark.parametrize('field,value', [('invocation_type', 'scheduled-success'), ('task_id', 'other'),
    ('phase', 'started'), ('run_id', 'different'), ('generation', 42), ('source_commit', '8'*40),
    ('probe_sha256', '0'*64)])
def test_each_terminal_is_bound_to_its_genuine_role_record(role, field, value):
    f = fixtures(); rewrite_role(f, role, 'terminal', lambda x: x.update({field: value}))
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


@pytest.mark.parametrize('field,value', [('result', 'no_contention'), ('challenge', 'not-uuid'),
    ('pid', True), ('pid', 0), ('invocation_type', 'unknown'), ('guard_identity', {**IDENT, 'inode': 99})])
def test_rehashed_probe_still_requires_kernel_proof_fields(field, value):
    f = fixtures(); rewrite_role(f, 'scheduled', 'probe', lambda x: x.update({field: value}))
    digest = m.hexdigest(f['role_bytes']['scheduled']['probe'])
    rewrite_role(f, 'scheduled', 'terminal', lambda x: x.update(probe_sha256=digest))
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


@pytest.mark.parametrize('now', [AT+timedelta(seconds=1), AT+timedelta(seconds=m.MAX_AGE+1), AT.replace(tzinfo=None)])
def test_real_time_must_be_complete_fresh_and_utc(now):
    f = fixtures(); f['now'] = now
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


def test_terminal_does_not_precede_probe():
    f = fixtures(); rewrite_role(f, 'watchdog', 'terminal', lambda x: x.update(at=AT.isoformat()))
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


@pytest.mark.parametrize('change', ['role_missing', 'duplicate_run', 'not_journaled', 'wrong_task', 'bad_bytes'])
def test_missing_or_fake_acknowledgement_is_not_readiness(change):
    f = fixtures()
    if change == 'role_missing': del f['role_bytes']['watchdog']
    elif change == 'duplicate_run': rewrite_bootstrap(f, lambda b: b['routes']['watchdog'].update(run_id=b['routes']['scheduled']['run_id']))
    elif change == 'not_journaled': rewrite_bootstrap(f, lambda b: b['routes']['watchdog'].update(terminal_event_id='absent'))
    elif change == 'wrong_task':
        events = m._journal(f['journal_raw']); events[0]['automation_task_id'] = 'other'; rewrite_journal(f, events)
    else: f['role_bytes']['interactive']['terminal'] += b'\n'
    with pytest.raises(m.EnrollmentBlocked): m.verify_bundle(**f)


def test_prior_unfinished_run_stays_uncertain_even_when_old():
    f = fixtures(); events = m._journal(f['journal_raw']); rid = 'old-scheduled-run'
    events.insert(0, {'event_id':rid+'-started', 'invocation_type':'scheduled', 'run_phase':'started',
                      'evidence':[(m.RUNTIME/rid/'started.json').as_posix()]})
    rewrite_journal(f, events)
    with pytest.raises(m.EnrollmentBlocked, match='uncertain'): m.verify_bundle(**f)


def test_ordinary_later_start_does_not_retroactively_modify_bound_bootstrap_prefix():
    f = fixtures(); f['journal_raw'] += m.canon({'event_id':'current-started','run_phase':'started'})
    assert m.verify_bundle(**f)['activation_authority_issued'] is False


def test_placeholder_historical_receipt_requires_resolution_not_silent_drop():
    f = fixtures(); events = m._journal(f['journal_raw'])
    events.insert(0, {'event_id':'fr06-$dir-start','source_commit':'$head','invocation_type':'scheduled','evidence':['$dir/started.json']})
    rewrite_journal(f, events)
    with pytest.raises(m.EnrollmentBlocked, match='reconciliation'): m.verify_bundle(**f)


@pytest.mark.parametrize('raw', [b'{}', b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'[]\n', b'\xff\n', b''])
def test_malformed_records_raise_sanitized_error(raw):
    with pytest.raises(m.EnrollmentBlocked): m.decode(raw)


@pytest.fixture
def private(tmp_path):
    p = tmp_path/'private'; p.mkdir(mode=0o700)
    (p/'execution.lock').touch(mode=0o600)
    return p


def test_probe_absence_does_not_create_directory_or_lock(tmp_path):
    p = tmp_path/'absent'
    with pytest.raises(OSError): m.probe_existing_lock(p,'scheduled',CHALLENGE)
    assert not p.exists()
    p.mkdir(mode=0o700)
    with pytest.raises(OSError): m.probe_existing_lock(p,'scheduled',CHALLENGE)
    assert list(p.iterdir()) == []


def test_probe_without_real_lock_owner_is_not_evidence(private):
    with pytest.raises(m.EnrollmentBlocked, match='no shared lock'): m.probe_existing_lock(private,'scheduled',CHALLENGE)
    assert [x.name for x in private.iterdir()] == ['execution.lock']


def child_probe(path, role, challenge, send):
    try: send.send(('ok',m.probe_existing_lock(Path(path),role,challenge)))
    except Exception as e: send.send(('blocked',type(e).__name__))
    finally: send.close()


def real_probe(path, role, challenge):
    ctx = multiprocessing.get_context('spawn'); recv, send = ctx.Pipe(duplex=False)
    p = ctx.Process(target=child_probe,args=(str(path),role,challenge,send)); p.start(); send.close()
    try:
        assert recv.poll(8), 'owned probe child did not complete'
        state, value = recv.recv(); p.join(8)
        assert p.exitcode == 0 and state == 'ok'; return value
    finally:
        recv.close()
        if p.is_alive(): p.terminate(); p.join(8)
        p.close()


def test_all_three_real_children_contend_without_journal_creation(private):
    before = (private/'execution.lock').read_bytes()
    proofs = m.challenge_routes(private, lambda role, challenge: real_probe(private,role,challenge))
    assert len(proofs) == 3 and len({x['challenge'] for x in proofs}) == 3
    assert {x['invocation_type'] for x in proofs} == set(m.ROUTES)
    assert (private/'execution.lock').read_bytes() == before
    assert not (private/'effects.jsonl').exists()


def test_real_guard_ownership_survives_probe_children(private):
    with ExecutionGuard(private,run_id='parent',invocation_type='interactive') as g:
        results = m.challenge_routes(private,lambda role, challenge: real_probe(private,role,challenge),active_guard=g)
        assert len(results)==3 and g.pending() is None
        with pytest.raises(ConcurrentOwner):
            with ExecutionGuard(private,run_id='contender',invocation_type='watchdog'):pass
    assert (private/'effects.jsonl').read_bytes()==b''


def test_closed_guard_is_not_authority(private):
    with ExecutionGuard(private,run_id='closed',invocation_type='interactive') as g:pass
    with pytest.raises(m.GuardBlocked): m.challenge_routes(private,lambda *_: {},active_guard=g)


@pytest.mark.parametrize('field,value',[('challenge',CHALLENGE),('guard_identity',IDENT),('result','pass'),('pid',1),('at',AT.isoformat())])
def test_forged_or_stale_child_output_not_accepted(private,field,value):
    def bad(role, challenge):
        x = real_probe(private,role,challenge)
        if field=='pid': value_now=os.getpid()
        else:value_now=value
        x[field]=value_now; return x
    with pytest.raises(m.EnrollmentBlocked):m.challenge_routes(private,bad)


@pytest.mark.parametrize('change',['file_symlink','parent_symlink','hardlink','world_readable','traversal','oversized'])
def test_bounded_file_reads_reject_unsafe_inputs(tmp_path,change):
    root=tmp_path/'records';root.mkdir(mode=0o700);(root/'child').mkdir(mode=0o700)
    f=root/'child'/'started.json';f.write_bytes(b'{"safe":true}\n');f.chmod(0o600)
    rel='child/started.json'
    if change=='file_symlink':f.rename(root/'original');f.symlink_to(root/'original')
    elif change=='parent_symlink':(root/'child').rename(root/'elsewhere');(root/'child').symlink_to(root/'elsewhere',target_is_directory=True)
    elif change=='hardlink':os.link(f,root/'alias')
    elif change=='world_readable':f.chmod(0o644)
    elif change=='traversal':rel='../outside/started.json'
    else:f.write_bytes(b'x'*(m.MAX_BYTES+1))
    with pytest.raises((m.EnrollmentBlocked,OSError)):m.read_bounded(root,rel)


def test_allowlisted_read_and_atomic_change_detection(tmp_path,monkeypatch):
    root=tmp_path/'records';root.mkdir(mode=0o700);f=root/'started.json';f.write_bytes(b'{"safe":true}\n');f.chmod(0o600)
    assert m.read_bounded(root,'started.json')==b'{"safe":true}\n'
    old=os.read
    def replace(fd,n):
        raw=old(fd,n);f.rename(root/'preserved');f.write_bytes(raw);f.chmod(0o600);return raw
    monkeypatch.setattr(os,'read',replace)
    with pytest.raises(m.EnrollmentBlocked,match='changed'):m.read_bounded(root,'started.json')


def test_native_interface_rejects_test_paths_without_provisioning(tmp_path):
    with pytest.raises(m.EnrollmentBlocked,match='fixed installed'):m.verify_installed_routes(source_root=tmp_path,guard_root=tmp_path/'absent',enrollment={})
    assert not (tmp_path/'absent').exists()


def test_candidate_cli_cannot_probe_live_lock_or_create_state():
    p=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/security/fr06_source_operator.py'),'enrollment_probe',
                      '--challenge',CHALLENGE,'--invocation-type','interactive'],capture_output=True,text=True,timeout=10)
    assert p.returncode==2 and json.loads(p.stdout)=={'status':'probe_blocked','production_accepted':False}
    assert not p.stderr


@pytest.mark.parametrize('location',['enrollment','bootstrap','started','terminal'])
def test_float_generation_is_not_an_integer_authority(location):
    f=fixtures()
    if location=='enrollment':f[location]['generation']=41.0
    elif location=='bootstrap':rewrite_bootstrap(f,lambda x:x.update(generation=41.0))
    else:rewrite_role(f,'scheduled',location,lambda x:x.update(generation=41.0))
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)


def test_unbound_prior_start_cannot_be_silently_ignored():
    f=fixtures();events=m._journal(f['journal_raw'])
    events.insert(0,{'event_id':'unbound-started','invocation_type':'scheduled','run_phase':'started',
                     'evidence':['some-other-path/started.json']})
    rewrite_journal(f,events)
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)


def test_role_event_timestamp_must_match_retained_bytes():
    f=fixtures();events=m._journal(f['journal_raw']);events[0]['at']=(AT-timedelta(days=10)).isoformat()
    rewrite_journal(f,events)
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)


def test_old_terminal_event_without_matching_terminal_file_cannot_resolve_run():
    f=fixtures();events=m._journal(f['journal_raw']);rid='prior-unknown'
    # An unverified event alone must not remove uncertainty from an earlier run.
    events[0:0]=[{'event_id':rid+'-'+phase,'invocation_type':'scheduled','run_phase':phase,
        'evidence':[(m.RUNTIME/rid/(phase+'.json')).as_posix()]} for phase in ('started','terminal')]
    rewrite_journal(f,events)
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)


def test_duplicate_retained_challenge_cannot_prove_different_roles():
    f=fixtures();p=m.decode(f['role_bytes']['scheduled']['probe'])
    rewrite_role(f,'watchdog','probe',lambda x:x.update(challenge=p['challenge']))
    digest=m.hexdigest(f['role_bytes']['watchdog']['probe'])
    rewrite_role(f,'watchdog','terminal',lambda x:x.update(probe_sha256=digest))
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)


def test_duck_typed_guard_is_not_actual_ownership(private):
    class FakeHeld:
        directory=private
        def _assert_held(self):pass
    with pytest.raises(m.EnrollmentBlocked):
        with m.held_probe_lock(private,FakeHeld()):pass


@pytest.mark.parametrize('bad',[None,123,[]])
def test_malformed_live_clock_is_explicitly_blocked(bad):
    f=fixtures();f['now']=bad
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)


def test_supported_historical_file_pair_is_read_not_invented():
    f=fixtures();events=m._journal(f['journal_raw']);rid='earlier-reviewed-run'
    records={}
    for phase in ('started','terminal'):
        events.insert(0,{'event_id':rid+'-'+phase,'invocation_type':'interactive','run_phase':phase,
            'source_commit':BIND['source_commit'],'evidence':[(m.RUNTIME/rid/(phase+'.json')).as_posix()]})
        v={'run_id':rid,'invocation_type':'interactive','phase':phase,'observed_source_commit':BIND['source_commit']}
        if phase=='started':v['started_at']=(AT-timedelta(minutes=2)).isoformat()
        else:v.update(finished_at=(AT-timedelta(minutes=1)).isoformat(),outcome='progress')
        records[phase]=m.canon(v)
    # Put the authentic start before terminal in the journal's original order.
    events[0],events[1]=events[1],events[0]
    rewrite_journal(f,events);f['historical_runs']={rid:records}
    assert m.verify_bundle(**f)['activation_authority_issued'] is False
    records['terminal']=m.canon({'run_id':rid,'phase':'terminal'})
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)


@pytest.fixture
def native_lab(tmp_path,monkeypatch,private):
    """Native evidence-file/probe plumbing, SYNTHETIC enrollment and Git reads."""
    from scripts.security import fr06_source_operator as operator
    repo=tmp_path/'repo';repo.mkdir(mode=0o700)
    launch=tmp_path/'launch';launch.mkdir(mode=0o700)
    monkeypatch.setattr(m,'ROOT',repo);monkeypatch.setattr(m,'GUARD',private);monkeypatch.setattr(m,'LAUNCH',launch)
    monkeypatch.setattr(m,'__file__',str(repo/'scripts/security/fr06_execution_enrollment.py'))
    # This fixture does NOT attest root or a real production installation.
    # Only that boundary is synthetic; file metadata, effective UID and
    # subprocess flock contention keep using the real nonroot test process.
    def synthetic_installed_context(source_root, guard_root):
        assert source_root == repo and guard_root == private
    monkeypatch.setattr(m, '_require_installed_context', synthetic_installed_context)
    monkeypatch.setattr(sys.modules[__name__],'AT',datetime.now(timezone.utc)-timedelta(seconds=3))
    f=fixtures();f['guard_identity']=m.resource_identity(private)
    for role in m.ROUTES:
        rewrite_role(f,role,'probe',lambda x:x.update(guard_identity=f['guard_identity']))
        digest=m.hexdigest(f['role_bytes'][role]['probe'])
        rewrite_role(f,role,'terminal',lambda x:x.update(probe_sha256=digest))
    rewrite_bootstrap(f,lambda b:b.update(guard_identity=f['guard_identity']))
    def save(p,raw,mode=0o600):
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);p.chmod(mode)
    save(private/'enrollment.json',m.canon(f['enrollment']))
    save(private/'bootstrap-evidence.json',f['bootstrap_raw'])
    save(repo/'docs/project/runtime/events.jsonl',f['journal_raw'],0o644)
    for role,parts in f['role_bytes'].items():
        rid=m.decode(parts['started'])['run_id']
        for kind,raw in parts.items():save(repo/m.RUNTIME/rid/('route-probe.json' if kind=='probe' else kind+'.json'),raw)
    helper=tmp_path/'probe-only.py'
    helper.write_text('import sys,json\nsys.dont_write_bytecode=True\nsys.path.insert(0,'+repr(str(ROOT))+')\n'
        'from pathlib import Path\nfrom scripts.security.fr06_execution_enrollment import probe_existing_lock\n'
        'assert sys.argv[1:3]==["enrollment_probe","--challenge"]\n'
        'print(json.dumps(probe_existing_lock(Path('+repr(str(private))+'),sys.argv[-1],sys.argv[3])))\n')
    for role,name in m.ROUTES.items():
        p=launch/name
        p.write_text('#!/bin/sh\nexec '+sys.executable+' -I '+str(helper)+' "$@" '+role+'\n');p.chmod(0o755)
    calls=[]
    def cmd(args,**kwargs):
        calls.append(args)
        if args[:3]==['git','-C',str(repo)]:
            return BIND['source_commit'] if args[3:]==['rev-parse','HEAD'] else ''
        assert args[0] in {str(launch/n) for n in m.ROUTES.values()}
        p=subprocess.run(args,capture_output=True,text=True,timeout=8)
        assert p.returncode==0 and not p.stderr
        return p.stdout.strip()
    monkeypatch.setattr(operator,'command',cmd)
    real_read=Path.read_text
    def safe_boot(p,*args,**kwargs):
        if str(p)=='/proc/sys/kernel/random/boot_id':return BIND['boot_id']
        return real_read(p,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',safe_boot)
    return repo,private,f,calls,operator,cmd


def test_native_io_reads_only_fixed_files_and_challenges_three_executables(native_lab):
    repo,private,f,calls,_,_=native_lab
    before={p:p.read_bytes() for p in private.iterdir() if p.is_file()}
    result=m.verify_installed_routes(source_root=repo,guard_root=private,enrollment=f['enrollment'])
    assert result['activation_authority_issued'] is False and len(result['fresh_route_probes'])==3
    assert len([a for a in calls if 'enrollment_probe' in a])==3
    assert {p:p.read_bytes() for p in private.iterdir() if p.is_file()}==before
    assert not (private/'effects.jsonl').exists()


def test_native_io_reuses_actual_guard_without_unlocking(native_lab):
    repo,private,f,_,_,_=native_lab
    with ExecutionGuard(private,run_id='native-lab-only',invocation_type='interactive') as g:
        x=m.verify_installed_routes(source_root=repo,guard_root=private,enrollment=f['enrollment'],active_guard=g)
        assert len(x['fresh_route_probes'])==3 and g.pending() is None
        with pytest.raises(ConcurrentOwner):
            with ExecutionGuard(private,run_id='other',invocation_type='scheduled'):pass


def test_missing_role_receipt_prevents_native_probe_subprocess(native_lab):
    repo,private,f,calls,_,_=native_lab
    (repo/m.RUNTIME/'watchdog-enroll-fixture/terminal.json').unlink()
    with pytest.raises(OSError):m.verify_installed_routes(source_root=repo,guard_root=private,enrollment=f['enrollment'])
    assert not [a for a in calls if 'enrollment_probe' in a]


def test_bootstrap_change_during_probe_is_not_accepted(native_lab,monkeypatch):
    repo,private,f,_,operator,cmd=native_lab
    def changing(args,**kwargs):
        value=cmd(args,**kwargs)
        if 'enrollment_probe' in args:
            p=private/'bootstrap-evidence.json';p.write_bytes(p.read_bytes()+b' ')
        return value
    monkeypatch.setattr(operator,'command',changing)
    with pytest.raises(m.EnrollmentBlocked, match='bootstrap changed during verification'):
        m.verify_installed_routes(source_root=repo,guard_root=private,enrollment=f['enrollment'])


def test_hourly_role_receipts_can_span_one_real_hour_before_bootstrap():
    f=fixtures();f['now']=AT+timedelta(hours=1,seconds=3)
    # Role adoption is historical; the Native verifier separately performs new
    # unpredictable kernel challenges during every current verification.
    assert m.verify_bundle(**f)['activation_authority_issued'] is False


def quarantined_fixture(valid_target=False):
    f=fixtures();events=m._journal(f['journal_raw'])
    bad={'event_id':'fr06-$dir-start','source_commit':'$head','invocation_type':'scheduled','evidence':['$dir/started.json']}
    if valid_target:bad={'event_id':'real-unknown-started','source_commit':BIND['source_commit'],'invocation_type':'scheduled',
                        'run_phase':'started','evidence':[(m.RUNTIME/'real-unknown'/'started.json').as_posix()]}
    q={'event_id':'metadata-quarantine-reviewed','event_type':'fr06_receipt_metadata_quarantine',
       'target_event_id':bad['event_id'],'target_event_canonical_sha256':m.hexdigest(m.canon(bad)),
       'scope':'invalid_metadata_only_not_effect_reconciliation','source_commit':BIND['source_commit']}
    events[0:0]=[bad,q];rewrite_journal(f,events);return f


def test_explicit_hash_bound_metadata_quarantine_preserves_history_without_acceptance():
    f=quarantined_fixture();before=f['journal_raw'];out=m.verify_bundle(**f)
    assert f['journal_raw']==before and out['activation_authority_issued'] is False
    assert out['quarantined_metadata_events']==['fr06-$dir-start']


@pytest.mark.parametrize('change',['wrong_target_digest','wrong_scope','valid_start','duplicate_quarantine'])
def test_metadata_quarantine_never_resolves_valid_or_uncertain_effect(change):
    f=quarantined_fixture(valid_target=change=='valid_start');events=m._journal(f['journal_raw'])
    if change=='wrong_target_digest':events[1]['target_event_canonical_sha256']='0'*64
    elif change=='wrong_scope':events[1]['scope']='all_effects_resolved'
    elif change=='duplicate_quarantine':events.insert(2,{**events[1],'event_id':'another-quarantine'})
    rewrite_journal(f,events)
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)
