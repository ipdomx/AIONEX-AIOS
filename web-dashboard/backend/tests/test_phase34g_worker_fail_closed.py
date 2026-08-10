from __future__ import annotations

import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import three_d_provider_policy, three_d_worker


@pytest.mark.asyncio
async def test_hunyuan_runtime_drift_bypasses_cache_and_never_submits_provider_job(
    monkeypatch,
):
    calls = {
        "runtime": 0,
        "fetch": 0,
        "submit": 0,
        "failure": 0,
        "defer": 0,
    }

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self):
            return None

    class Storage:
        def get_bytes(self, _key, *, max_bytes):
            assert max_bytes > 0
            return b"test-image"

    class Client:
        endpoint_id = "current-secret-endpoint"

        def submit(self, _payload, *, ttl_seconds):
            calls["submit"] += 1
            raise AssertionError(
                f"provider submit must remain unreachable (ttl={ttl_seconds})"
            )

    async def policy(_session):
        return {
            "enabled": True,
            "max_queue_seconds": 30,
            "max_runtime_seconds": 60,
            "max_input_megabytes": 8,
            "max_texture_size": 1024,
            "compression_policy": "balanced",
        }

    async def available(_session, *, provider):
        assert provider == "hunyuan3d"
        return {"state": "closed"}

    def provider_env():
        calls["runtime"] += 1
        return {
            "RUNPOD_API_KEY": "test-key",
            "RUNPOD_ENDPOINT_ID": "current-secret-endpoint",
            "RUNPOD_HUNYUAN_LOCATION": "US",
        }

    def drifted_region_fetch(_api_key, endpoint_id):
        assert endpoint_id == Client.endpoint_id
        calls["fetch"] += 1
        return ("US-TX-3", "EU-RO-1")

    job = SimpleNamespace(
        status="queued",
        provider="hunyuan3d",
        provider_job_id=None,
        input_object_key="private/test.png",
        request_options={},
    )
    worker = object.__new__(three_d_worker.ThreeDGenerationWorker)
    worker.storage = Storage()
    worker.runpods = {"hunyuan3d": Client()}

    async def load(_job_id, _lease_token):
        return job

    async def provider_failure(received_job, error_code):
        assert received_job is job
        assert error_code == "THREE_D_PROVIDER_RUNTIME_UNVERIFIED"
        calls["failure"] += 1

    async def defer(_job_id, _lease_token, *, provider):
        assert provider == "hunyuan3d"
        calls["defer"] += 1

    worker._load = load
    worker._provider_failure = provider_failure
    worker._defer_for_runtime_gate = defer

    monkeypatch.setattr(three_d_worker, "SessionLocal", Session)
    monkeypatch.setattr(three_d_worker, "get_three_d_policy", policy)
    monkeypatch.setattr(three_d_worker, "assert_provider_available", available)
    monkeypatch.setattr(three_d_provider_policy, "_provider_env", provider_env)
    monkeypatch.setattr(
        three_d_provider_policy,
        "_fetch_runpod_endpoint_datacenter_ids",
        drifted_region_fetch,
    )

    three_d_provider_policy._runpod_endpoint_region_cache.clear()
    three_d_provider_policy._runpod_endpoint_region_cache[Client.endpoint_id] = (
        float("inf"),
        True,
    )
    try:
        await worker.execute("job-test", "lease-test")

        assert calls == {
            "runtime": 1,
            "fetch": 1,
            "submit": 0,
            "failure": 1,
            "defer": 1,
        }
    finally:
        three_d_provider_policy._runpod_endpoint_region_cache.clear()


def test_worker_health_writes_use_unique_atomic_temp_files(tmp_path, monkeypatch):
    health_path = tmp_path / "three-d-worker-health.json"
    worker = object.__new__(three_d_worker.ThreeDGenerationWorker)
    worker.health_path = health_path
    worker.cycles = 17
    worker.errors = 2
    worker.circuit_state = "closed"
    worker.last_cleanup_at = None
    worker.last_provider_success_at = None
    worker.last_provider_failure_at = None

    sources: list[Path] = []
    sources_lock = threading.Lock()
    original_replace = three_d_worker.os.replace

    def tracked_replace(source, destination):
        with sources_lock:
            sources.append(Path(source))
        original_replace(source, destination)

    monkeypatch.setattr(three_d_worker.os, "replace", tracked_replace)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: worker.write_health("ok"), range(32)))

    document = json.loads(health_path.read_text(encoding="utf-8"))
    assert document["status"] == "ok"
    assert document["cycles"] == 17
    assert document["errors"] == 2
    assert len(sources) == 32
    assert len(set(sources)) == 32
    assert all(source.parent == health_path.parent for source in sources)
    assert not list(tmp_path.glob(f".{health_path.name}.*.tmp"))
    assert stat.S_IMODE(health_path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_compose_healthcheck_reads_fresh_worker_owned_evidence(tmp_path, monkeypatch):
    health_path = tmp_path / "three-d-worker-health.json"
    monkeypatch.setattr(
        three_d_worker.settings, "THREE_D_WORKER_HEALTH_FILE", str(health_path)
    )
    monkeypatch.setattr(three_d_worker.time, "time", lambda: 1_000.0)

    health_path.write_text(
        json.dumps({"status": "ok", "checked_at_epoch": 995.0}), encoding="utf-8"
    )
    assert await three_d_worker.healthcheck() == 0

    health_path.write_text(
        json.dumps({"status": "ok", "checked_at_epoch": 800.0}), encoding="utf-8"
    )
    assert await three_d_worker.healthcheck() == 1

    health_path.write_text(
        json.dumps({"status": "error", "checked_at_epoch": 995.0}), encoding="utf-8"
    )
    assert await three_d_worker.healthcheck() == 1
