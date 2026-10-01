import importlib.util,sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
P=Path('scripts/security/fr06c5_full_host_closure.py');s=importlib.util.spec_from_file_location('fhc',P);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
def proofs():
 op=str(uuid4());studio=SimpleNamespace(operation_id=op,generation=8,process_drain_verified=True,full_host_closure=False);turn=SimpleNamespace(operation_id=op,generation=8,turn_allocation_drain_verified=True,credential_expiry_verified=True,full_host_closure=False);g=SimpleNamespace(operation_id=op,generation=8,graceful_stop_verified=True,full_host_closure=False);return op,studio,turn,g
def test_certifies_only_all_bound_proofs():
 op,s,t,g=proofs();r=m.certify(studio=s,turn=t,graceful=g,operation_id=op,generation=8);assert r['full_host_closure'] and not r['production_activation_authorized']
def test_rejects_mixed_generation():
 op,s,t,g=proofs();t.generation=9
 with pytest.raises(m.FullHostClosureBlocked):m.certify(studio=s,turn=t,graceful=g,operation_id=op,generation=8)
def test_rejects_component_overclaim():
 op,s,t,g=proofs();g.full_host_closure=True
 with pytest.raises(m.FullHostClosureBlocked):m.certify(studio=s,turn=t,graceful=g,operation_id=op,generation=8)
