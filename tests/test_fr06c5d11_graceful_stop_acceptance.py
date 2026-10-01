import importlib.util,sys
from pathlib import Path
from uuid import uuid4
import pytest
P=Path('scripts/security/fr06c5d11_graceful_stop_acceptance.py');s=importlib.util.spec_from_file_location('gstop',P);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
def evidence():
 op=str(uuid4());a={'operation_id':op,'generation':8,'status':'closed','enabled':False,'full_host_closure':False};before={};after={}
 for i,n in enumerate(m.SERVICES):
  cid=str(i+1)*64;before[n]={'container_id':cid,'restart_count':0,'running':True,'restart_policy':'no'};after[n]={'container_id':cid,'restart_count':0,'running':False,'restart_policy':'no','exit_code':0}
 return {'authority':a,'services':before},{'authority':a.copy(),'services':after}
def test_accepts_exact_clean_stops():
 a,b=evidence();assert m.accept(before=a,after=b).graceful_stop_verified
def test_rejects_restart_or_replacement():
 a,b=evidence();b['services']['telegram-worker']['restart_count']=1
 with pytest.raises(m.GracefulStopBlocked):m.accept(before=a,after=b)
def test_rejects_nonzero_exit():
 a,b=evidence();b['services']['operations-observer']['exit_code']=143
 with pytest.raises(m.GracefulStopBlocked):m.accept(before=a,after=b)
def test_rejects_open_or_changed_authority():
 a,b=evidence();b['authority']['generation']=9
 with pytest.raises(m.GracefulStopBlocked):m.accept(before=a,after=b)
