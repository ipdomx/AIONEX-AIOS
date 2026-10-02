"""Legacy journal identity regressions; synthetic records, no host/provider I/O."""
from pathlib import Path
import importlib.util
import sys
import pytest
from scripts.security import fr06_execution_enrollment as m

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('history_fixture_helpers', ROOT/'tests/test_fr06_execution_enrollment.py')
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)

RID = 'scheduled-20261001T130107077325012Z'
SUFFIX = RID.removeprefix('scheduled-')

def event(phase):
    return {'event_id': 'fr06-scheduled-'+phase+'-'+SUFFIX,
            'invocation_type': 'scheduled', 'source_commit': '7'*40,
            'evidence': [(m.RUNTIME/RID/(phase+'.json')).as_posix()]}

@pytest.mark.parametrize('phase',['started','terminal'])
def test_known_legacy_event_identity_is_not_silently_ignored(phase):
    e=event(phase)
    if phase=='started':e['event_id']='fr06-scheduled-start-'+SUFFIX
    assert m._event_run(e)==(RID,phase)

def test_completed_legacy_event_with_both_references_selects_terminal():
    e=event('terminal')
    e['evidence'].insert(0,(m.RUNTIME/RID/'started.json').as_posix())
    assert m._event_run(e)==(RID,'terminal')

def test_unfinished_legacy_run_prevents_bootstrap_acceptance():
    f=h.fixtures();es=m._journal(f['journal_raw'])
    e=event('started');e['event_id']='fr06-scheduled-start-'+SUFFIX
    es.insert(0,e);h.rewrite_journal(f,es)
    with pytest.raises(m.EnrollmentBlocked):m.verify_bundle(**f)

@pytest.mark.parametrize('phase',['started','terminal'])
def test_wrong_legacy_identity_never_binds_another_run(phase):
    e=event(phase);e['event_id']=e['event_id'].replace(SUFFIX,'20260101T000000Z')
    with pytest.raises(m.EnrollmentBlocked):m._event_run(e)
