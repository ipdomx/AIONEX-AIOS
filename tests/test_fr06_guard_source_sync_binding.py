"""Real lock/journal regression for old local main versus newly accepted remote main."""
from __future__ import annotations
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_guard_test', ROOT/'scripts/security/fr06_execution_guard.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
OLD, NEW = '7'*40, '8'*40
BOOT, OP = '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002'

def binding():
    return m.SyncBinding(source_commit=OLD, local_main_commit=OLD, main_commit=NEW,
                         boot_id=BOOT, operation_id=OP, generation=41,
                         source_clean=True, maintenance_status='closed')

@pytest.fixture
def root(tmp_path):
    p=tmp_path/'guard'; p.mkdir(mode=0o700); return p

def test_sync_represents_remote_and_local_truth_without_equalizing_them(root):
    b=binding(); b.validate()
    with m.ExecutionGuard(root,run_id='sync-one',invocation_type='interactive') as g:
        result=g.perform(action='source_sync',target_commit=NEW,expected=b,observe=lambda:b,
                         invoke=lambda:m.ObservedResult('observed_complete','a'*64))
        assert result['payload']['outcome']=='observed_complete'
    with m.ExecutionGuard(root,run_id='reader',invocation_type='scheduled') as g:
        records=g._records()
        assert records[0]['payload']['binding']['main_commit']==NEW
        assert records[0]['payload']['binding']['local_main_commit']==OLD
        assert g.pending() is None

@pytest.mark.parametrize('field,value', [('source_commit','9'*40),('local_main_commit','9'*40),
    ('main_commit','$head'),('generation',True),('source_clean',False),('maintenance_status','open')])
def test_invalid_sync_binding_does_not_create_intent(root,field,value):
    b=replace(binding(),**{field:value})
    with m.ExecutionGuard(root,run_id='invalid',invocation_type='scheduled') as g:
        with pytest.raises(m.GuardBlocked):
            g.perform(action='source_sync',target_commit=NEW,expected=b,observe=lambda:b,
                      invoke=lambda:pytest.fail('effect must not run'))
        assert g.pending() is None

@pytest.mark.parametrize('action,target',[('source_merge',NEW),('host_state',NEW),('source_sync','9'*40)])
def test_sync_binding_cannot_authorize_other_action_or_target(root,action,target):
    b=binding()
    with m.ExecutionGuard(root,run_id='invalid-action',invocation_type='watchdog') as g:
        with pytest.raises(m.GuardBlocked):
            g.perform(action=action,target_commit=target,expected=b,observe=lambda:b,
                      invoke=lambda:pytest.fail('effect must not run'))
        assert g.pending() is None

def test_ordinary_binding_still_refuses_remote_local_drift():
    with pytest.raises(m.GuardBlocked):
        m.Binding(OLD,NEW,BOOT,OP,41,True,'closed').validate()
