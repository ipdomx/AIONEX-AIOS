import importlib.util,sys
from pathlib import Path
from uuid import uuid4
import pytest
P=Path('scripts/security/fr06d8c4_studio_final_drain.py');s=importlib.util.spec_from_file_location('sfd',P);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
def bundle():
 op=str(uuid4());a={'operation_id':op,'generation':8,'status':'closed','enabled':False,'full_host_closure':False};studio={'is_clear':True,'blocker_count':0,'admission_closed':True,'full_host_closure':False,'executions':[],'publications':[]};b={'active_count':0,'unresolved_count':0,'expired_count':0,'unfinished_count':0,'operation_id':op,'generation':8,'full_host_closure':False};x={'schema':'aionex.studio-drain-inputs.v1','admission':a,'studio':studio,'backup':b};return x,{'schema':x['schema'],'admission':a.copy(),'studio':studio.copy(),'backup':b.copy()}
def test_accepts_two_stable_clear_observations():
 a,b=bundle();assert m.accept(first=a,second=b).process_drain_verified
def test_rejects_blocker():
 a,b=bundle();b['studio']['blocker_count']=1;b['studio']['is_clear']=False
 with pytest.raises(m.StudioFinalDrainBlocked):m.accept(first=a,second=b)
def test_rejects_state_change():
 a,b=bundle();b['studio']['executions']=[{'id':'changed'}]
 with pytest.raises(m.StudioFinalDrainBlocked):m.accept(first=a,second=b)
def test_rejects_authority_change():
 a,b=bundle();b['admission']['generation']=9
 with pytest.raises(m.StudioFinalDrainBlocked):m.accept(first=a,second=b)
