from __future__ import annotations
import json,time,hashlib
from pathlib import Path

class Observability:
    def __init__(self,path:Path): self.path=path; path.parent.mkdir(parents=True,exist_ok=True)
    def record(self,kind:str,tenant_id:str,data:dict)->dict:
        previous='GENESIS'
        if self.path.exists() and self.path.stat().st_size:
            previous=json.loads(self.path.read_text().splitlines()[-1])['hash']
        entry={'ts':time.time(),'kind':kind,'tenant_id':tenant_id,'data':data,'previous_hash':previous}
        entry['hash']=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(entry,ensure_ascii=False)+'\n')
        return entry
    def verify(self)->bool:
        prev='GENESIS'
        if not self.path.exists(): return True
        for line in self.path.read_text().splitlines():
            e=json.loads(line); h=e.pop('hash')
            if e['previous_hash']!=prev or hashlib.sha256(json.dumps(e,sort_keys=True).encode()).hexdigest()!=h:return False
            prev=h
        return True
