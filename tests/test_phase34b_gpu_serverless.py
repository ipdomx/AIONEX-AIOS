from __future__ import annotations
import base64
from pathlib import Path
import pytest
from aios.gpu_worker import HunyuanServerlessController, RunPodError, ServerlessCostGuardrails

class FakeRunPod:
    def __init__(self, states): self.states=list(states); self.cancelled=[]; self.purged=0; self.submits=0
    def submit(self, payload, ttl_seconds=None): self.submits+=1; return {"id": f"job-{self.submits}", "status":"IN_QUEUE"}
    def status(self, job_id): return self.states.pop(0) if self.states else {"status":"FAILED"}
    def cancel(self, job_id): self.cancelled.append(job_id); return {"id":job_id,"status":"CANCELLED"}
    def purge_queue(self): self.purged+=1; return {"status":"completed"}

def test_completed_job_writes_glb(tmp_path: Path, monkeypatch):
    blob=b"glTF"+b"x"*16
    fake=FakeRunPod([{"status":"COMPLETED","output":{"content_base64":base64.b64encode(blob).decode(),"size_bytes":len(blob)}}])
    out=tmp_path/'x.glb'
    result=HunyuanServerlessController(fake, max_runtime_seconds=60).execute({"image":"x"}, artifact_path=out)
    assert result.success and out.read_bytes()==blob

def test_stuck_queue_is_cancelled_purged_and_retried(monkeypatch):
    times=iter([0,0,20,20,20,20])
    monkeypatch.setattr('aios.gpu_worker.controller.time.monotonic', lambda: next(times,20))
    monkeypatch.setattr('aios.gpu_worker.controller.time.sleep', lambda _: None)
    fake=FakeRunPod([{"status":"IN_QUEUE"},{"status":"COMPLETED","output":{}}])
    alerts=[]
    c=HunyuanServerlessController(fake,max_runtime_seconds=60,guardrails=ServerlessCostGuardrails(max_queue_seconds=10,max_retries=1),owner_alert=lambda code,d: alerts.append(code))
    assert c.execute({"image":"x"}).success
    assert fake.cancelled==['job-1'] and fake.purged==1 and fake.submits==2
    assert '3d.job.stuck_recovered' in alerts and '3d.job.retry' in alerts

def test_failed_job_retries_once(monkeypatch):
    monkeypatch.setattr('aios.gpu_worker.controller.time.sleep', lambda _: None)
    fake=FakeRunPod([{"status":"FAILED"},{"status":"COMPLETED","output":{}}])
    c=HunyuanServerlessController(fake,max_runtime_seconds=60,guardrails=ServerlessCostGuardrails(max_retries=1))
    assert c.execute({"image":"x"}).success and fake.submits==2

def test_cost_guard_blocks_before_submit():
    fake=FakeRunPod([]); alerts=[]
    guards=ServerlessCostGuardrails(estimated_gpu_cost_per_second_usd=0.1,max_estimated_job_cost_usd=1.0)
    c=HunyuanServerlessController(fake,max_runtime_seconds=60,guardrails=guards,owner_alert=lambda code,d: alerts.append(code))
    with pytest.raises(RunPodError,match='cost'):
        c.execute({"image":"x"})
    assert fake.submits==0 and alerts==['3d.cost.job_blocked']

def test_daily_and_monthly_limits_are_fail_closed():
    fake=FakeRunPod([])
    guards=ServerlessCostGuardrails(estimated_gpu_cost_per_second_usd=0.01,max_estimated_job_cost_usd=10,daily_spend_limit_usd=1,monthly_spend_limit_usd=10)
    c=HunyuanServerlessController(fake,max_runtime_seconds=60,guardrails=guards)
    with pytest.raises(RunPodError,match='Daily'):
        c.execute({"image":"x"},daily_spend_usd=0.5)
