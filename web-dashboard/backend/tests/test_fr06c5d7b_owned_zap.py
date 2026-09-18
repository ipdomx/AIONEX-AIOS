"""Durable ownership with an explicit synthetic HTTP ZAP protocol model.

Real PostgreSQL fencing; httpx MockTransport for remote responses. These tests
never certify a real ZAP JVM, its filesystem or production deployment as drained.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.services import host_maintenance_scan_execution as registry
from app.services.security_scan_resources import ScanResourceRuntime
from app.services.security_scan_zap_resources import OwnedZapClient
from app.services import security_zap

_name = "fr06c5d7b_owned_zap_registry"
_spec = importlib.util.spec_from_file_location(_name, Path(__file__).with_name("test_fr06c5d7b_execution_registry.py"))
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
remediation_case = _shared.remediation_case
scan_case = _shared.scan_case
registry_case = _shared.registry_case


class EngineModel:
    def __init__(self):
        self.scans = {"spider": [], "ascan": []}
        self.calls = []
        self.sequence = 0
        self.malformed = None
        self.pending_passive = 0
        self.fail_submit = False
        self.submitted = asyncio.Event()
        self.release = None
        self.observe = None

    async def request(self, request):
        path = request.url.path
        self.calls.append(path)
        if self.observe:
            await self.observe(path)
        payload = {"Result": "OK"}
        if path == self.malformed:
            payload = {}
        elif path.endswith("/view/scans/"):
            kind = path.split('/')[2]
            payload = {"scans": [{"id": x, "progress": "100", "state": "FINISHED"} for x in self.scans[kind]]}
        elif path.endswith('/action/scan/'):
            kind = path.split('/')[2]
            self.sequence += 1
            self.scans[kind].append(str(self.sequence))
            self.submitted.set()
            if self.release:
                await self.release.wait()
            if self.fail_submit:
                raise httpx.ReadTimeout("synthetic lost acknowledgement", request=request)
            payload = {"scan": str(self.sequence)}
        elif path.endswith('/view/status/'):
            payload = {"status": "100"}
        elif path.endswith('/view/recordsToScan/'):
            payload = {"recordsToScan": str(self.pending_passive)}
        elif path.endswith('/view/alerts/'):
            payload = {"alerts": []}
        elif path.endswith('/view/urls/'):
            payload = {"urls": []}
        elif path.endswith('/action/removeScan/'):
            self.scans[path.split('/')[2]].remove(request.url.params['scanId'])
        return httpx.Response(200, json=payload)


async def setup(case, monkeypatch):
    owner = await _shared.claim(case)
    assert await _shared.begin(case, owner)
    runtime = ScanResourceRuntime(owner, session_factory=case.sessions)
    model = EngineModel()
    real_client = httpx.AsyncClient
    monkeypatch.setenv("SECURITY_ZAP_URL", "http://synthetic-engine.test:8080")
    monkeypatch.setenv("SECURITY_ZAP_API_KEY", "synthetic-only-not-a-production-key")
    monkeypatch.setattr(security_zap.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(model.request), **kwargs))
    return owner, runtime, model, OwnedZapClient(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize('active', [False, True])
async def test_acknowledged_natural_completion_cleans_then_releases_fence(registry_case, monkeypatch, active):
    case = registry_case
    owner, runtime, model, client = await setup(case, monkeypatch)

    async def observe(path):
        row = await _shared.row(case, owner)
        assert row.zap_owner_key == client.engine_key
        if '/action/' in path:
            record = row.resources[client.identifier]
            assert record['identity']['submission_pending'] is True

    model.observe = observe
    result = await client.run('http://synthetic-target.test', active=active)
    row = await _shared.row(case, owner)
    assert result['status'] == 'completed' and row.zap_owner_key is None
    assert row.resources[client.identifier]['state'] == 'settled'
    assert row.resources[client.identifier]['evidence'] == {'remote_zero': True, 'cleanup_complete': True}
    assert model.scans == {'spider': [], 'ascan': []}
    assert model.calls[-1] == '/JSON/pscan/view/recordsToScan/'
    assert not any('/stop/' in p for p in model.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('foreign', ['spider', 'ascan', 'passive'])
async def test_foreign_work_is_never_reset_or_adopted(registry_case, monkeypatch, foreign):
    case = registry_case
    owner, runtime, model, client = await setup(case, monkeypatch)
    if foreign == 'passive':
        model.pending_passive = 1
    else:
        model.scans[foreign] = ['7']
    with pytest.raises(registry.ScanExecutionUncertain):
        await client.run('http://synthetic-target.test', active=False)
    row = await _shared.row(case, owner)
    assert row.zap_owner_key == client.engine_key
    assert row.resources[client.identifier]['state'] == 'unresolved'
    assert not any('/action/' in p for p in model.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/JSON/spider/view/scans/', '/JSON/ascan/view/scans/', '/JSON/pscan/view/recordsToScan/', '/JSON/core/action/newSession/'])
async def test_missing_observation_cannot_release_engine(registry_case, monkeypatch, path):
    case = registry_case
    owner, runtime, model, client = await setup(case, monkeypatch)
    model.malformed = path
    with pytest.raises(registry.ScanExecutionUncertain):
        await client.run('http://synthetic-target.test', active=False)
    row = await _shared.row(case, owner)
    assert row.zap_owner_key and row.resources[client.identifier]['state'] == 'unresolved'
    assert not any('/action/removeScan/' in p for p in model.calls)


@pytest.mark.asyncio
async def test_lost_submit_response_retains_pending_intent_and_engine(registry_case, monkeypatch):
    case = registry_case
    owner, runtime, model, client = await setup(case, monkeypatch)
    model.fail_submit = True
    with pytest.raises(registry.ScanExecutionUncertain):
        await client.run('http://synthetic-target.test', active=False)
    row = await _shared.row(case, owner)
    assert row.resources[client.identifier]['identity']['submission_pending'] is True
    assert row.zap_owner_key
    assert model.scans['spider'] == ['1']
    assert not any('/action/stop/' in p or '/removeScan/' in p for p in model.calls)


@pytest.mark.asyncio
async def test_timeout_stop_ack_is_not_remote_join_proof(registry_case, monkeypatch):
    case = registry_case
    owner, runtime, model, client = await setup(case, monkeypatch)

    async def timeout(*_args, **_kwargs):
        raise TimeoutError('synthetic unfinished producer')

    monkeypatch.setattr(client, '_wait_percent', timeout)
    with pytest.raises(registry.ScanExecutionUncertain):
        await client.run('http://synthetic-target.test', active=False)
    row = await _shared.row(case, owner)
    assert row.zap_owner_key and row.resources[client.identifier]['state'] == 'unresolved'
    assert '/JSON/spider/action/stop/' in model.calls
    assert not any('/removeScan/' in p for p in model.calls)
    assert model.calls.count('/JSON/core/action/newSession/') == 1


@pytest.mark.asyncio
async def test_cancel_during_submission_joins_response_and_records_owned_id(registry_case, monkeypatch):
    case = registry_case
    owner, runtime, model, client = await setup(case, monkeypatch)
    model.release = asyncio.Event()
    task = asyncio.create_task(client.run('http://synthetic-target.test', active=False))
    try:
        await asyncio.wait_for(model.submitted.wait(), 5)
        task.cancel()
        await asyncio.sleep(.02)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
        row = await _shared.row(case, owner)
        assert row.resources[client.identifier]['identity']['submission_pending'] is True
        model.release.set()
        with pytest.raises(registry.ScanExecutionUncertain):
            await asyncio.wait_for(task, 5)
    finally:
        model.release.set()
        await asyncio.gather(task, return_exceptions=True)
    row = await _shared.row(case, owner)
    assert row.zap_owner_key
    assert row.resources[client.identifier]['identity']['spider_ids'] == ['1']
    assert row.resources[client.identifier]['state'] == 'unresolved'


@pytest.mark.asyncio
async def test_second_execution_cannot_use_fenced_engine(registry_case, monkeypatch):
    case = registry_case
    owner, runtime, model, client = await setup(case, monkeypatch)
    client.identifier = await runtime.reserve('zap', 'prior-owned-engine', exclusive_key=client.engine_key)
    second = await _shared.claim(case)
    assert await _shared.begin(case, second)
    other = OwnedZapClient(ScanResourceRuntime(second, session_factory=case.sessions))
    with pytest.raises(IntegrityError):
        await other.run('http://synthetic-target.test', active=False)
    assert model.calls == []
    assert (await _shared.row(case, owner)).zap_owner_key == client.engine_key
