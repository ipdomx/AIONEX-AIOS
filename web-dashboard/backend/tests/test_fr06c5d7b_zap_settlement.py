"""Isolated ZAP observation tests; no live daemon, scanners or provider traffic.

These establish strict response interpretation and the final passive-tail wait,
not durable remote ownership, remote cancellation or full-host drain acceptance.
"""

import asyncio

import httpx
import pytest

from app.services import security_zap as zap


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SECURITY_ZAP_URL", "http://security-zap.invalid:8080")
    monkeypatch.setenv("SECURITY_ZAP_API_KEY", "disposable-zap-test-only")
    return zap.ZapClient()


@pytest.mark.parametrize("value", [0, 1, 100, "0", "1", "100", 2**63 - 1, str(2**63 - 1)])
def test_integer_observation_accepts_only_bounded_canonical_numbers(value):
    assert zap._integer_field({"recordsToScan": value}, "recordsToScan") == int(value)


@pytest.mark.parametrize("value", [
    None, True, False, -1, 0.0, 1.5, "", " 0", "0 ", "+0", "-0", "-1",
    "00", "01", "0.0", "1e2", "NaN", "Infinity", "١", "０", "9" * 100,
    2**63, str(2**63), [], {},
])
def test_invalid_numeric_observation_is_not_coerced_to_zero(value):
    with pytest.raises(zap.ZapResponseInvalid):
        zap._integer_field({"recordsToScan": value}, "recordsToScan")


@pytest.mark.parametrize("payload", [{}, {"code": "not_found"}, {"code": "bad", "recordsToScan": 0}])
def test_missing_or_error_response_is_not_empty_queue(payload):
    with pytest.raises(zap.ZapResponseInvalid):
        zap._integer_field(payload, "recordsToScan")


@pytest.mark.parametrize("value", [0, "0", 10, "10"])
def test_scan_identifier_accepts_zero_but_is_canonical(value):
    assert zap._scan_id({"scan": value}) == str(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"status": 101}, {"status": "101"}, {"status": True}, {"status": -1}, {"status": "100.0"}, {"status": 100, "code": "error"}])
async def test_progress_must_be_a_real_percentage(client, monkeypatch, payload):
    async def response(*_args, **_kwargs):
        return payload

    monkeypatch.setattr(client, "_json", response)
    with pytest.raises(zap.ZapResponseInvalid):
        await client._wait_percent("/JSON/ascan/view/status/", scan_id="0", timeout=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"status": 100}, {"status": "100"}])
async def test_completed_percentage_is_accepted(client, monkeypatch, payload):
    async def response(*_args, **_kwargs):
        return payload

    monkeypatch.setattr(client, "_json", response)
    await client._wait_percent("/JSON/ascan/view/status/", scan_id="0", timeout=0)


@pytest.mark.asyncio
async def test_positive_passive_queue_times_out_without_becoming_zero(client, monkeypatch):
    async def response(*_args, **_kwargs):
        return {"recordsToScan": "1"}

    monkeypatch.setattr(client, "_json", response)
    with pytest.raises(TimeoutError):
        await client._wait_passive_queue(timeout=0)


class Engine:
    """Small acknowledged engine model, with a separately controlled final queue."""

    def __init__(self, *, urls=None, final_payload=None, final_error=None):
        self.calls = []
        self.queue_reads = 0
        self.active_count = 0
        self.urls = [] if urls is None else urls
        self.final_payload = {"recordsToScan": "0"} if final_payload is None else final_payload
        self.final_error = final_error
        self.final_entered = asyncio.Event()
        self.release_final = asyncio.Event()
        self.release_final.set()

    async def json(self, path, params=None):
        self.calls.append((path, params))
        if path == "/JSON/core/action/newSession/":
            return {"Result": "OK"}
        if path == "/JSON/spider/action/scan/":
            return {"scan": "0"}
        if path == "/JSON/spider/view/status/":
            return {"status": "100"}
        if path == "/JSON/ascan/action/scan/":
            self.active_count += 1
            return {"scan": str(self.active_count)}
        if path == "/JSON/ascan/view/status/":
            return {"status": "100"}
        if path == "/JSON/pscan/view/recordsToScan/":
            self.queue_reads += 1
            if self.active_count:
                self.final_entered.set()
                await self.release_final.wait()
                if self.final_error is not None:
                    raise self.final_error
                return self.final_payload
            return {"recordsToScan": "0"}
        if path == "/JSON/core/view/urls/":
            return {"urls": self.urls}
        if path == "/JSON/core/view/alerts/":
            return {"alerts": []}
        raise AssertionError("Unexpected test engine request")


@pytest.mark.asyncio
@pytest.mark.parametrize("target_count", [0, 1, 3])
async def test_final_passive_tail_is_awaited_after_all_active_producers(client, monkeypatch, target_count):
    engine = Engine(urls=[f"https://example.test/search?q={i}" for i in range(target_count)])
    engine.release_final.clear()
    monkeypatch.setattr(client, "_json", engine.json)
    task = asyncio.create_task(client.active_clone("https://example.test", timeout=2))
    try:
        await asyncio.wait_for(engine.final_entered.wait(), timeout=2)
        assert engine.active_count == 1 + target_count
        assert engine.queue_reads == 2
        assert not task.done()
        assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)
        engine.release_final.set()
        result = await asyncio.wait_for(task, timeout=2)
        assert result["status"] == "completed"
        paths = [path for path, _ in engine.calls]
        final_queue_index = max(i for i, path in enumerate(paths) if path == "/JSON/pscan/view/recordsToScan/")
        assert final_queue_index > max(i for i, path in enumerate(paths) if path == "/JSON/ascan/view/status/")
        assert final_queue_index < paths.index("/JSON/core/view/alerts/")
    finally:
        engine.release_final.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_final_nonempty_queue_requires_a_later_zero(client, monkeypatch):
    engine = Engine(final_payload={"recordsToScan": "7"})
    second_observation = asyncio.Event()
    release_zero = asyncio.Event()
    original = engine.json

    async def response(path, params=None):
        if path == "/JSON/pscan/view/recordsToScan/" and engine.queue_reads == 2:
            second_observation.set()
            await release_zero.wait()
            engine.final_payload = {"recordsToScan": "0"}
        return await original(path, params)

    async def yield_without_delay(_delay):
        # The events, not a sleep duration, establish the observed ordering.
        return None

    monkeypatch.setattr(client, "_json", response)
    monkeypatch.setattr(zap.asyncio, "sleep", yield_without_delay)
    task = asyncio.create_task(client.active_clone("https://example.test", timeout=2))
    try:
        await asyncio.wait_for(second_observation.wait(), timeout=2)
        assert not task.done()
        assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)
        release_zero.set()
        assert (await asyncio.wait_for(task, timeout=2))["status"] == "completed"
        assert engine.queue_reads == 3
    finally:
        release_zero.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"recordsToScan": None}, {"recordsToScan": False}, {"recordsToScan": -1}, {"recordsToScan": "0.0"}, {"code": "error", "recordsToScan": "0"}])
async def test_final_malformed_queue_cannot_publish_completed_engine(client, monkeypatch, payload):
    engine = Engine(final_payload=payload)
    monkeypatch.setattr(client, "_json", engine.json)
    with pytest.raises(zap.ZapResponseInvalid):
        await client.active_clone("https://example.test", timeout=0)
    assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout("not-for-output"), RuntimeError("not-for-output"), TimeoutError("not-for-output")])
async def test_wrapper_reports_final_observation_failure_not_success(client, monkeypatch, error):
    engine = Engine(final_error=error)
    monkeypatch.setattr(client, "_json", engine.json)
    monkeypatch.setattr(zap, "ZapClient", lambda: client)
    result = await zap.run_zap("https://example.test", execution_mode="intrusive_clone", active=True)
    assert result["status"] in {"failed", "unavailable"}
    assert result["findings"] == []
    assert "not-for-output" not in str(result)
    assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)


@pytest.mark.asyncio
async def test_cancel_during_final_queue_is_not_success_or_stop_proof(client, monkeypatch):
    engine = Engine()
    engine.release_final.clear()
    monkeypatch.setattr(client, "_json", engine.json)
    monkeypatch.setattr(zap, "ZapClient", lambda: client)
    task = asyncio.create_task(zap.run_zap("https://example.test", execution_mode="intrusive_clone", active=True))
    try:
        await asyncio.wait_for(engine.final_entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)
    finally:
        engine.release_final.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"alerts": None}, {"alerts": {}}, {"alerts": [None]}, {"alerts": [], "code": "error"}])
async def test_invalid_alert_inventory_is_not_no_findings(client, monkeypatch, payload):
    async def response(*_args, **_kwargs):
        return payload

    monkeypatch.setattr(client, "_json", response)
    with pytest.raises(zap.ZapResponseInvalid):
        await client.alerts("https://example.test")


@pytest.mark.asyncio
@pytest.mark.parametrize("urls", [None, {}, [None], [False], [1]])
async def test_invalid_discovery_inventory_is_not_no_targets(client, monkeypatch, urls):
    engine = Engine()
    original = engine.json

    async def response(path, params=None):
        if path == "/JSON/core/view/urls/":
            return {"urls": urls}
        return await original(path, params)

    monkeypatch.setattr(client, "_json", response)
    with pytest.raises(zap.ZapResponseInvalid):
        await client.active_clone("https://example.test", timeout=0)
    assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [False, True])
async def test_missing_start_acknowledgement_stops_follow_on_requests(client, monkeypatch, active):
    calls = []

    async def response(path, params=None):
        calls.append(path)
        return {"Result": "OK"} if path.endswith("newSession/") else {}

    monkeypatch.setattr(client, "_json", response)
    with pytest.raises(zap.ZapResponseInvalid):
        if active:
            await client.active_clone("https://example.test", timeout=0)
        else:
            await client.passive("https://example.test", timeout=0)
    assert calls == ["/JSON/core/action/newSession/", "/JSON/spider/action/scan/"]


@pytest.mark.asyncio
async def test_passive_flow_requires_explicit_queue_observation(client, monkeypatch):
    engine = Engine()
    original = engine.json

    async def response(path, params=None):
        if path == "/JSON/pscan/view/recordsToScan/":
            return {}
        return await original(path, params)

    monkeypatch.setattr(client, "_json", response)
    with pytest.raises(zap.ZapResponseInvalid):
        await client.passive("https://example.test", timeout=0)
    assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)


@pytest.mark.asyncio
async def test_final_nonempty_queue_timeout_blocks_alert_publication(client, monkeypatch):
    engine = Engine(final_payload={"recordsToScan": "3"})
    monkeypatch.setattr(client, "_json", engine.json)
    with pytest.raises(TimeoutError):
        await client.active_clone("https://example.test", timeout=0)
    assert engine.active_count == 1
    assert engine.queue_reads == 2
    assert not any(path == "/JSON/core/view/alerts/" for path, _ in engine.calls)


@pytest.mark.asyncio
async def test_wrapper_preserves_malformed_tail_as_failed_not_completed(client, monkeypatch):
    engine = Engine(final_payload={})
    monkeypatch.setattr(client, "_json", engine.json)
    monkeypatch.setattr(zap, "ZapClient", lambda: client)
    result = await zap.run_zap("https://example.test", execution_mode="intrusive_clone", active=True)
    assert result == {
        "tool": "owasp-zap", "status": "failed",
        "error_type": "ZapResponseInvalid", "findings": [],
    }
