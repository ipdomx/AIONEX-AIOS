from __future__ import annotations
import json
from pathlib import Path
from uuid import uuid4
from .models import WorkflowRecord,WorkflowStep

class DurableWorkflowEngine:
    def __init__(self,state_dir:Path): self.state_dir=state_dir; self.state_dir.mkdir(parents=True,exist_ok=True)
    def _path(self,wid:str)->Path: return self.state_dir/f'{wid}.json'
    def run(self,tenant_id:str,name:str,steps:list[WorkflowStep],context:dict,workflow_id:str|None=None)->WorkflowRecord:
        wid=workflow_id or str(uuid4()); current=0
        if self._path(wid).exists():
            saved=json.loads(self._path(wid).read_text()); current=saved['current_step']; context=saved['context']
        record=WorkflowRecord(wid,tenant_id,name,'running',current,context)
        for idx in range(current,len(steps)):
            step=steps[idx]; step.attempts+=1
            try:
                step.result=step.handler(dict(record.context)); step.state='complete'; record.context.update(step.result); record.current_step=idx+1
                self._save(record)
            except Exception as exc:
                step.state='failed'; record.state='failed'; record.context['last_error']=str(exc); self._save(record); return record
        record.state='complete'; self._save(record); return record
    def _save(self,r:WorkflowRecord)->None:
        self._path(r.workflow_id).write_text(json.dumps({'workflow_id':r.workflow_id,'tenant_id':r.tenant_id,'name':r.name,'state':r.state,'current_step':r.current_step,'context':r.context},ensure_ascii=False,indent=2))
