from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("fr06c5d13_maintenance_authority_operator",ROOT/"scripts/security/fr06c5d13_maintenance_authority_operator.py")
assert SPEC and SPEC.loader
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)
OP="cd5a0e31-a49b-4fdf-b2a6-ac53a7831d17"

def snap(gen=41,status="closed"):
 return {"schema_version":8,"scope":"all-eight-scopes","generation":gen,"status":status,"enabled":status=="open","operation_id":OP,"full_host_closure":False}

def root(monkeypatch,tmp_path):
 def open_root(path):
  path.mkdir(parents=True,exist_ok=True);os.chmod(path,0o700)
  return os.open(path,os.O_RDONLY|os.O_DIRECTORY)
 monkeypatch.setattr(m,"_root",open_root)
 monkeypatch.setattr(m,"_source",lambda:{"source_commit":"a"*40})

def install_transition(monkeypatch,state,calls):
 monkeypatch.setattr(m,"_snapshot",lambda:dict(state))
 def run(args,timeout=20):
  assert args[:4]==["docker","exec","web-dashboard-backend-1","/opt/venv/bin/python"]
  action=args[-4];gen=int(args[-2])
  calls.append((action,gen))
  assert state["generation"]==gen
  state["generation"]+=1
  state["status"]="open" if action=="open" else "closed"
  state["enabled"]=action=="open"
  return json.dumps(state,sort_keys=True)
 monkeypatch.setattr(m,"_run",run)

@pytest.mark.parametrize("action,before_status,gen", [("open","closed",41),("close","open",42)])
def test_one_journaled_transition(action,before_status,gen,monkeypatch,tmp_path):
 root(monkeypatch,tmp_path);state=snap(gen,before_status);calls=[];install_transition(monkeypatch,state,calls)
 receipt=m.execute(action=action,operation_id=OP,expected_generation=gen,reason="FR-06 controlled transition",journal_root=tmp_path/"j")
 assert calls==[(action,gen)]
 assert receipt["before"]["generation"]==gen
 assert receipt["after"]["generation"]==gen+1
 assert receipt["after"]["status"]==("open" if action=="open" else "closed")
 assert receipt["replayed_transition"] is False
 assert (tmp_path/"j"/f"{action}-g{gen}-intent.json").is_file()
 assert (tmp_path/"j"/f"{action}-g{gen}-accepted.json").is_file()

def test_accepted_transition_is_read_only_on_repeat(monkeypatch,tmp_path):
 root(monkeypatch,tmp_path);state=snap();calls=[];install_transition(monkeypatch,state,calls)
 kw=dict(action="open",operation_id=OP,expected_generation=41,reason="backup window",journal_root=tmp_path/"j")
 first=m.execute(**kw);second=m.execute(**kw)
 assert first==second and calls==[("open",41)]

def test_existing_intent_reconciles_target_without_replay(monkeypatch,tmp_path):
 root(monkeypatch,tmp_path)
 fd=os.open(tmp_path/"j",os.O_RDONLY|os.O_DIRECTORY) if (tmp_path/"j").exists() else None
 if fd is not None: os.close(fd)
 state=snap();calls=[];install_transition(monkeypatch,state,calls)
 # Force the first transition result to become target but fail before receipt write.
 original_write=m._write
 def fail_accept(fd,name,value):
  if name.endswith("-accepted.json"): raise OSError("synthetic post-effect write failure")
  return original_write(fd,name,value)
 monkeypatch.setattr(m,"_write",fail_accept)
 kw=dict(action="open",operation_id=OP,expected_generation=41,reason="backup window",journal_root=tmp_path/"j")
 with pytest.raises(OSError):m.execute(**kw)
 assert calls==[("open",41)] and state["generation"]==42 and state["status"]=="open"
 monkeypatch.setattr(m,"_write",original_write)
 # No transition command may run on reconciliation.
 monkeypatch.setattr(m,"_run",lambda *a,**k: (_ for _ in ()).throw(AssertionError("replay")))
 receipt=m.execute(**kw)
 assert receipt["reconciled_after_intent"] is True and receipt["after"]["generation"]==42

def test_existing_intent_with_unchanged_baseline_refuses_replay(monkeypatch,tmp_path):
 root(monkeypatch,tmp_path);state=snap();calls=[]
 monkeypatch.setattr(m,"_snapshot",lambda:dict(state))
 monkeypatch.setattr(m,"_run",lambda *a,**k: (_ for _ in ()).throw(m.AuthorityTransitionHalted("synthetic pre-effect failure")))
 kw=dict(action="open",operation_id=OP,expected_generation=41,reason="backup window",journal_root=tmp_path/"j")
 with pytest.raises(m.AuthorityTransitionHalted):m.execute(**kw)
 intent=tmp_path/"j"/"open-g41-intent.json"
 assert intent.is_file()
 with pytest.raises(m.AuthorityTransitionHalted):m.execute(**kw)

@pytest.mark.parametrize("field,value",[
 ("generation",40),("status","open"),("enabled",True),("operation_id","11111111-1111-1111-1111-111111111111"),("full_host_closure",True)
])
def test_baseline_drift_denied_before_effect(field,value,monkeypatch,tmp_path):
 root(monkeypatch,tmp_path);state=snap();state[field]=value;calls=[]
 monkeypatch.setattr(m,"_snapshot",lambda:dict(state))
 monkeypatch.setattr(m,"_run",lambda *a,**k:calls.append(a) or "")
 with pytest.raises(m.AuthorityTransitionHalted):
  m.execute(action="open",operation_id=OP,expected_generation=41,reason="backup window",journal_root=tmp_path/"j")
 assert calls==[]

def test_source_contains_no_direct_sql_or_retry_loop():
 source=(ROOT/"scripts/security/fr06c5d13_maintenance_authority_operator.py").read_text()
 assert "open_admission" in source and "close_admission" in source
 assert "UPDATE owner_control" not in source.upper()
 assert "automatic_retry" in source
