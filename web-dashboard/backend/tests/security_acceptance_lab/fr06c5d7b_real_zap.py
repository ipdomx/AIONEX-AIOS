"""Explicit opt-in QA: real worker, PostgreSQL, ZAP JVM and local HTTP target.

This file is run explicitly, not auto-collected by the ordinary offline suite.
Only the exact isolated QA engine/target are admitted. The worker uses a stated
synthetic executor to exercise resource ownership, not production target policy
or the complete scanner catalog. Active QA enables one real ZAP rule only.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import sys
from threading import Thread

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import SecurityScan, SecurityScanExecution
from app.services import host_maintenance_scan_execution as registry
from app.services import security_scan_worker as worker_module
from app.services.security_scan_resources import require_runtime
from app.services.security_scan_zap_resources import OwnedZapClient
from app.services.security_zap import ZapClient

_name = "fr06c5d7b8_real_engine_worker_fixtures"
_spec = importlib.util.spec_from_file_location(
    _name, Path(__file__).parents[1] / "test_fr06c5d7b_worker_runtime.py",
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
remediation_case = _shared.remediation_case
scan_case = _shared.scan_case
registry_case = _shared.registry_case
local_runtime_case = _shared.local_runtime_case

ENGINE = "http://aionex-fr06c5d7b8-test-zap:8080"
TARGET = "http://aionex-fr06c5d7b8-zap-db-proof:8000"


class TargetHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><html><title>Owned QA target</title><a href="/page">Local page</a><p>Synthetic fixture.</p></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return None  # Do not retain engine payloads or target request details.


@pytest_asyncio.fixture
async def real_engine_case(local_runtime_case, tmp_path, monkeypatch):
    if (os.environ.get("SECURITY_ZAP_URL") != ENGINE
            or os.environ.get("AIONEX_SCAN_QA_TARGET_ORIGIN") != TARGET
            or os.environ.get("SECURITY_ZAP_API_KEY") != "fr06c5d7b8-disposable-only"):
        raise RuntimeError("This acceptance requires the exact isolated QA engine and target")
    case = local_runtime_case
    server = ThreadingHTTPServer(("0.0.0.0", 8000), TargetHandler)
    server.daemon_threads = False
    serving = Thread(target=server.serve_forever)
    serving.start()
    original_json = ZapClient._json
    observations = []

    async def observed_json(client, path, params=None):
        if isinstance(client, OwnedZapClient):
            async with case.sessions() as session:
                row = await session.get(SecurityScanExecution, client.runtime.owner.execution_id)
                assert row.zap_owner_key == client.engine_key
                if "/action/" in path:
                    assert row.resources[client.identifier]["identity"]["submission_pending"] is True
                observations.append(path)
        return await original_json(client, path, params)

    try:
        plain = ZapClient()
        async with asyncio.timeout(100):
            while True:
                try:
                    version = await plain._json("/JSON/core/view/version/")
                    assert version.get("version") == "2.17.0"
                    break
                except (httpx.HTTPError, OSError):
                    await asyncio.sleep(1)
        for kind in ("spider", "ascan"):
            assert (await plain._json(f"/JSON/{kind}/view/scans/"))["scans"] == []
        scanners = await plain._json("/JSON/ascan/view/scanners/")
        assert any(str(item.get("id")) == "40012" for item in scanners["scanners"])
        assert await plain._json("/JSON/ascan/action/disableAllScanners/") == {"Result": "OK"}
        assert await plain._json("/JSON/ascan/action/enableScanners/", {"ids": "40012"}) == {"Result": "OK"}
        monkeypatch.setattr(ZapClient, "_json", observed_json)
        instance = _shared.worker(case, tmp_path, monkeypatch)
        instance.heartbeat_seconds = 0.05

        async def policy(_session):
            return {"max_scan_runtime_seconds": 240}

        monkeypatch.setattr(worker_module, "get_policy", policy)
        yield case, instance, observations
    finally:
        await asyncio.to_thread(server.shutdown)
        await asyncio.to_thread(serving.join)
        await asyncio.to_thread(server.server_close)
        assert not serving.is_alive()


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [False, True])
async def test_real_worker_database_engine_and_local_resources_settle(real_engine_case, monkeypatch, active):
    case, instance, observations = real_engine_case
    clients, folders = [], []

    async def execute(_session, scan):
        runtime = require_runtime(scan.id)
        async with runtime.temporary_workspace("real-engine-acceptance") as folder:
            folders.append(folder)
            assert await runtime.thread("qa-real-thread", lambda: 23) == 23
            process = await runtime.process([sys.executable, "-c", "print('qa-owned-child')"], timeout=5)
            assert process.returncode == 0 and process.stdout == b"qa-owned-child\n"
            client = OwnedZapClient(runtime)
            clients.append(client)
            result = await client.run(TARGET, active=active)
            assert result["status"] == "completed"
        scan.status = "completed"
        scan.completed_at = datetime.now(UTC)
        scan.lease_token = None

    monkeypatch.setattr(worker_module, "execute_scan", execute)
    identifier = await _shared._shared.new_scan(case)
    claim = await instance.claim()
    assert claim and claim[0] == identifier
    await asyncio.wait_for(instance.run_claim(*claim), 300)
    async with case.sessions() as session:
        scan = await session.get(SecurityScan, identifier)
        row = await session.scalar(select(SecurityScanExecution).where(SecurityScanExecution.scan_id == identifier))
    assert scan.status == "completed" and scan.summary["execution_cleanup"]["verified"] is True
    assert row.state == "settled" and row.operation_stopped_at and row.supervisor_stopped_at
    assert row.zap_owner_key is None
    assert {item["kind"] for item in row.resources.values()} == {"async_io", "thread", "process", "zap"}
    assert all(item["state"] == "settled" for item in row.resources.values())
    assert all(not folder.exists() for folder in folders)
    assert observations and all(path.startswith("/JSON/") for path in observations)
    plain = ZapClient()
    for kind in ("spider", "ascan"):
        assert (await plain._json(f"/JSON/{kind}/view/scans/"))["scans"] == []
    assert (await registry.execution_snapshot(session_factory=case.sessions))["is_clear"]
    assert await instance.claim() is None
    print(json.dumps({"case": "real-worker-db-zap", "active": active, "resources": len(row.resources),
                      "database_settled": True, "engine_fence_released": True,
                      "engine_inventories_empty": True, "workspaces_removed": True,
                      "durable_request_observations": len(observations)}), flush=True)


@pytest.mark.asyncio
async def test_real_cancel_stop_ack_preserves_unresolved_engine_fence(real_engine_case, monkeypatch):
    case, instance, observations = real_engine_case
    submitted = asyncio.Event()
    clients = []

    async def execute(_session, scan):
        runtime = require_runtime(scan.id)
        client = OwnedZapClient(runtime)
        clients.append(client)

        async def hold_completion(_path, *, scan_id, timeout):
            # A real submission has already returned its durable ID. Deliberately
            # withhold observation of natural completion, even if the tiny target
            # finishes quickly; a later stop ACK alone must not release the fence.
            assert scan_id in client.ids["spider"] and timeout > 0
            submitted.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(client, "_wait_percent", hold_completion)
        await client.run(TARGET, active=False)

    monkeypatch.setattr(worker_module, "execute_scan", execute)
    identifier = await _shared._shared.new_scan(case)
    claim = await instance.claim()
    assert claim
    task = asyncio.create_task(instance.run_claim(*claim))
    try:
        await asyncio.wait_for(submitted.wait(), 30)
        reply = await _shared.cancel(case, identifier)
        assert reply["cancellation"] == {"status": "cancellation_requested", "cleanup_verified": False}
        with pytest.raises(registry.ScanExecutionUncertain):
            await asyncio.wait_for(task, 30)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with case.sessions() as session:
        scan = await session.get(SecurityScan, identifier)
        row = await session.scalar(select(SecurityScanExecution).where(SecurityScanExecution.scan_id == identifier))
    client = clients[0]
    assert row.state == "unresolved" and row.zap_owner_key == client.engine_key
    assert row.resources[client.identifier]["state"] == "unresolved"
    assert row.cancel_requested_at and row.operation_stopped_at and row.supervisor_stopped_at
    assert scan.status == "running" and "execution_cleanup" not in scan.summary
    assert "/JSON/spider/action/stop/" in observations
    assert not any("removeScan" in path for path in observations)
    assert (await registry.execution_snapshot(session_factory=case.sessions))["blocker_count"] == 1
    assert await instance.claim() is None
    print(json.dumps({"case": "real-cancel-stop-ack", "database_settled": False,
                      "engine_fence_retained": True, "automatic_replay": False,
                      "scope": "uncertain QA producer retained until disposable daemon destruction"}), flush=True)
