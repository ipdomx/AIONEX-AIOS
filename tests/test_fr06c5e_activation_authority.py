import importlib.util,sys,hashlib,json
from pathlib import Path
from uuid import uuid4
import pytest
P=Path('scripts/security/fr06c5e_activation_authority.py');s=importlib.util.spec_from_file_location('act',P);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
def closure():
 b={'schema':'aionex.fr06-full-host-closure.v1','operation_id':str(uuid4()),'generation':8,'studio_process_drain_verified':True,'turn_allocation_drain_verified':True,'turn_credential_expiry_verified':True,'telegram_observer_graceful_stop_verified':True,'component_full_host_flags_remain_false':True,'full_host_closure':True,'production_activation_authorized':False};b['receipt_sha256']=hashlib.sha256(json.dumps(b,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest();return b
def test_issues_bound_short_lived_authority():
 c=closure();r=m.issue(closure=c,source_commit='a'*40,boot_id=str(uuid4()),host_state_receipt_sha256='b'*64,preflight_sha256='c'*64,boot_graph_sha256='d'*64,now=100,ttl_seconds=600);assert r['production_activation_authorized'] and r['expires_at_epoch']==700
def test_rejects_closure_overclaim_or_digest_drift():
 c=closure();c['production_activation_authorized']=True
 with pytest.raises(m.ActivationBlocked):m.issue(closure=c,source_commit='a'*40,boot_id=str(uuid4()),host_state_receipt_sha256='b'*64,preflight_sha256='c'*64,boot_graph_sha256='d'*64,now=100)
def test_rejects_unbounded_ttl():
 c=closure()
 with pytest.raises(m.ActivationBlocked):m.issue(closure=c,source_commit='a'*40,boot_id=str(uuid4()),host_state_receipt_sha256='b'*64,preflight_sha256='c'*64,boot_graph_sha256='d'*64,now=100,ttl_seconds=3600)
