from __future__ import annotations
import hashlib, importlib.util, json, sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
t=load('coord_tx','scripts/security/fr06c5_memory_transaction.py'); c=load('coord','scripts/security/fr06c5_memory_coordinator.py')
def h(x):return hashlib.sha256(x).hexdigest()
def ctx():return t.BoundContext('a'*40,str(uuid4()),str(uuid4()),1,h(b'h'),h(b'p'),h(b'g'))
class Child:
 def __init__(self,name,context):
  step=t.BoundStep(name,h(('b'+name).encode()),h(('a'+name).encode()));self.journal=SimpleNamespace(plan=t.Plan(str(uuid4()),context,(step,),1,900));self.s=t.State('applying',0,None,1);self.calls=[]
 def state(self):return self.s
 def apply_next(self):self.calls.append('apply');self.s=t.State('applying',1,None,3);return self.s
 def verify_applied(self):self.calls.append('verify');self.s=t.State('applied',1,None,4);return self.s
 def begin_rollback(self):self.calls.append('begin');self.s=t.State('rolling_back',self.s.applied,None,5);return self.s
 def undo_next(self):self.calls.append('undo');self.s=t.State('rolling_back',0,None,7);return self.s
 def verify_restored(self):self.calls.append('restored');self.s=t.State('restored',0,None,8);return self.s
 def reconcile_pending(self):raise AssertionError('coordinator must not auto reconcile')
def digest(ch):return hashlib.sha256(json.dumps(asdict(ch.journal.plan),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def make(tmp):
 x=ctx(); a=Child('prepare_encrypted_backing',x);b=Child('attach_swap_loop',x);plan=c.Plan(str(uuid4()),h(json.dumps(asdict(x),sort_keys=True,separators=(',',':'),allow_nan=False).encode()),(c.ChildSpec('backing',digest(a)),c.ChildSpec('loop',digest(b))));return c.Coordinator(tmp/'coord',plan,{'backing':a,'loop':b}),a,b
def test_forward_is_strictly_ordered_and_verified(tmp_path):
 q,a,b=make(tmp_path);assert q.apply_next()[0]=='backing';assert q.apply_next()[0]=='backing';assert a.calls==['apply','verify'];assert q.apply_next()[0]=='loop';q.close()
def test_pending_child_halts_without_replay(tmp_path):
 q,a,b=make(tmp_path);a.s=t.State('applying',0,('apply',0),2)
 with pytest.raises(c.CoordinatorUncertain):q.apply_next()
 assert not a.calls and not b.calls;q.close()
def test_rollback_is_reverse_order_and_explicit(tmp_path):
 q,a,b=make(tmp_path)
 for _ in range(4):q.apply_next()
 assert a.s.phase==b.s.phase=='applied';assert q.begin_rollback()[0]=='loop';assert q.rollback_next()[0]=='loop';assert q.rollback_next()[0]=='loop';assert q.begin_rollback()[0]=='backing';assert q.rollback_next()[0]=='backing';assert q.rollback_next()[0]=='backing';assert a.s.phase==b.s.phase=='restored';q.close()
def test_changed_child_plan_is_rejected(tmp_path):
 q,a,b=make(tmp_path);parent=q.parent;plan=q.plan;q.close();a.journal.plan=t.Plan(str(uuid4()),a.journal.plan.context,a.journal.plan.steps,1,900)
 with pytest.raises(c.CoordinatorRejected):c.Coordinator(parent,plan,{'backing':a,'loop':b})
def test_no_production_cli_or_kernel_effect_imports():
 src=(ROOT/'scripts/security/fr06c5_memory_coordinator.py').read_text();assert 'subprocess' not in src and 'systemctl' not in src and '__main__' not in src


def test_unjournaled_child_is_rejected(tmp_path):
 q,a,b=make(tmp_path); parent=q.parent; plan=q.plan; q.close()
 class Unjournaled:
  def __init__(self, source): self.source=source
  def state(self): return self.source.state()
  def apply_next(self): return self.source.apply_next()
  def verify_applied(self): return self.source.verify_applied()
  def begin_rollback(self): return self.source.begin_rollback()
  def undo_next(self): return self.source.undo_next()
  def verify_restored(self): return self.source.verify_restored()
  def reconcile_pending(self): return self.source.reconcile_pending()
 with pytest.raises(c.CoordinatorRejected):
  c.Coordinator(parent,plan,{'backing':Unjournaled(a),'loop':b})


def test_context_digest_must_match_child_context(tmp_path):
 q,a,b=make(tmp_path); old=q.plan; q.close()
 wrong=c.Plan(old.operation,h(b'wrong-context'),old.children)
 with pytest.raises(c.CoordinatorRejected):
  c.Coordinator(tmp_path/'wrong-context',wrong,{'backing':a,'loop':b})


def test_halted_child_can_enter_explicit_reverse_rollback(tmp_path):
 q,a,b=make(tmp_path)
 a.s=t.State('applied',1,None,4)
 b.s=t.State('halted',0,None,4)
 assert q.begin_rollback()[0]=='loop'
 assert b.s.phase=='rolling_back' and b.s.applied==0
 assert q.rollback_next()[0]=='loop'
 assert b.s.phase=='restored'
 assert q.begin_rollback()[0]=='backing'
 q.close()
