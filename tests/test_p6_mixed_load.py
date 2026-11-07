"""P6 gate 6.1: mixed-profile load harness guards, verdict and a local end-to-end run."""
from __future__ import annotations

import asyncio
import base64
import collections
import hashlib
import importlib.util
import io
import json
import struct
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAPACITY = ROOT / "scripts" / "capacity"
sys.path.insert(0, str(CAPACITY))
spec = importlib.util.spec_from_file_location("p6_mixed_load", CAPACITY / "p6_mixed_load.py")
load = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = load
spec.loader.exec_module(load)
import p6_http  # noqa: E402

RUN_ID = "p6-20261120t0900z"


def config(**overrides):
    values = {"target": "https://api.vip-e.net", "run_id": RUN_ID}
    values.update(overrides)
    return load.LoadConfig(**values)


@pytest.mark.parametrize("host", ["vip-e.net", "www.vip-e.net", "ai.vip-e.net", "gabarot.vip-e.net"])
def test_static_cpanel_and_owner_hosts_are_never_targets(host):
    problems = load.validate_config(config(target=f"https://{host}"))
    assert any("never a load-test target" in p for p in problems)


def test_only_production_api_or_explicit_lab_is_accepted():
    assert load.validate_config(config()) == []
    assert load.validate_config(config(target="https://example.com"))
    assert load.validate_config(config(target="http://api.vip-e.net"))
    assert load.validate_config(config(target="http://127.0.0.1:8000"))
    assert load.validate_config(config(target="http://127.0.0.1:8000", allow_lab_target=True)) == []


def test_unsafe_knobs_are_refused():
    assert load.validate_config(config(ai_rps_max=5))
    assert load.validate_config(config(ramp=(100, 50)))
    assert load.validate_config(config(ramp=(10, 7000)))
    assert load.validate_config(config(max_duration_seconds=60))
    assert load.validate_config(config(run_id="prod-users"))


def test_default_schedule_ramps_to_5000_and_holds_steady_window():
    schedule = load.build_schedule(config())
    assert [s["users"] for s in schedule] == [25, 100, 250, 500, 1000, 2500, 5000]
    assert schedule[-1]["steady"] is True
    assert schedule[-1]["hold_seconds"] == 120 + 900
    assert sum(s["new_users"] for s in schedule) == 5000
    estimate = load.estimate_load(config())
    assert estimate["ai_requests_capped_per_second"] == 0.2
    assert estimate["open_files_needed"] > 10000


def test_plan_and_unconfirmed_run_send_nothing(capsys):
    assert load.main(["plan", "--run-id", RUN_ID]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests_sent"] == 0
    assert load.main(["run", "--run-id", RUN_ID]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "DRY_RUN"
    assert load.main(["run", "--run-id", RUN_ID, "--target", "https://ai.vip-e.net", "--execute"]) == 2


def test_accounts_must_be_synthetic_and_of_this_run(tmp_path):
    good = tmp_path / "good.jsonl"
    good.write_text("".join(
        json.dumps({"email": f"{RUN_ID}-{i:05d}@synthetic.loadtest.invalid", "run_id": RUN_ID}) + "\n"
        for i in range(3)))
    assert len(load.read_accounts(good, RUN_ID, 3)) == 3
    with pytest.raises(load.PlanError):
        load.read_accounts(good, RUN_ID, 4)
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"email": "customer@gmail.com", "run_id": RUN_ID}) + "\n")
    with pytest.raises(load.PlanError):
        load.read_accounts(bad, RUN_ID, 1)


def test_password_file_must_be_private(tmp_path):
    secret = tmp_path / "pw"
    secret.write_text("x" * 20)
    secret.chmod(0o644)
    with pytest.raises(load.PlanError):
        load.read_password(secret)
    secret.chmod(0o600)
    assert load.read_password(secret) == "x" * 20


def response(status, headers=None):
    return p6_http.HttpResponse(status, headers or {"content-type": "application/json"}, b"{}", 10.0)


def test_classification_separates_edge_blocks_policy_and_server_errors():
    normal = load.Action("projects_list", 1)
    ai = load.Action("ai_message", 1, ai=True)
    assert load.classify(normal, response(200), None) == "ok"
    assert load.classify(normal, response(503, {"content-type": "text/html"}), None) == "server_error"
    assert load.classify(normal, response(403, {"server": "cloudflare", "content-type": "text/html"}), None) == "edge_block"
    gated = load.Action("ads_connections", 3, entitlement_gated=True)
    assert load.classify(gated, response(403, {"content-type": "application/json"}), None) == "policy"
    assert load.classify(gated, response(403, {"server": "cloudflare", "content-type": "text/html"}), None) == "edge_block"
    assert load.classify(normal, response(403, {"content-type": "application/json"}), None) == "client_error"
    assert load.classify(normal, response(200, {"cf-mitigated": "challenge"}), None) == "edge_block"
    assert load.classify(ai, response(429), None) == "policy"
    assert load.classify(normal, response(429), None) == "client_error"
    assert load.classify(normal, None, "connect_error") == "transport"


def test_stop_policy_triggers():
    metrics = load.Metrics()
    action = load.Action("projects_list", 1)
    now = time.time()
    for _ in range(190):
        metrics.record(action, "ok", 200, 20, now)
    for _ in range(20):
        metrics.record(action, "server_error", 503, 20, now)
    assert load.StopPolicy().check(metrics, health_failures=0) == "error_rate"
    clean = load.Metrics()
    clean.edge_blocks = 1
    assert load.StopPolicy().check(clean, health_failures=0) == "edge_or_waf_block"
    assert load.StopPolicy().check(load.Metrics(), health_failures=3) == "origin_health_failing"


def test_storm_detection_uses_10s_buckets():
    buckets = collections.defaultdict(lambda: [0, 0])
    buckets[1] = [1000, 5]
    buckets[2] = [1000, 25]
    storms = load.storm_buckets(buckets)
    assert [s["bucket_start_epoch"] for s in storms] == [20]


def _steady_metrics(latency_ms: float, errors: int = 0) -> load.Metrics:
    metrics = load.Metrics()
    metrics.steady_start = 1000.0
    action = load.Action("projects_list", 1)
    for index in range(1000):
        metrics.record(action, "server_error" if index < errors else "ok", 200, latency_ms, 1000.0 + index)
    metrics.steady_end = 1000.0 + 900
    metrics.steady_active_min = 5000
    return metrics


def test_verdict_pass_and_fail():
    assert load.evaluate_verdict(_steady_metrics(120), config(), None)["status"] == "PASS"
    slow = load.evaluate_verdict(_steady_metrics(700), config(), None)
    assert slow["status"] == "FAIL" and "steady_non_ai_p95_lt_500ms" in slow["failed_criteria"]
    erroring = load.evaluate_verdict(_steady_metrics(100, errors=20), config(), None)
    assert "error_rate_lt_1pct" in erroring["failed_criteria"]
    assert load.evaluate_verdict(_steady_metrics(100), config(), "5xx_storm")["status"] == "ABORTED"


def test_ai_gate_caps_rate_and_concurrency():
    metrics = load.Metrics()
    gate = load.AiGate(rate=2.0, concurrency=1, metrics=metrics)
    assert gate.try_acquire() is True
    assert gate.try_acquire() is False  # concurrency 1
    gate.release()
    assert load.AiGate(0, 4, metrics).try_acquire() is False


# --------------------------------------------------------------------------- local end-to-end


async def fake_api(reader, writer, seen):
    try:
        while True:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode().split("\r\n")
            method, path, _ = lines[0].split(" ", 2)
            headers = {k.lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:] if line)}
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            seen.append((method, path.split("?")[0]))
            if headers.get("upgrade", "").lower() == "websocket":
                accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + p6_http.WS_GUID).encode()).digest()).decode()
                writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
                payload = json.dumps({"type": "connected"}).encode()
                writer.write(bytes([0x81, len(payload)]) + payload)
                await writer.drain()
                await reader.read()  # until the client closes
                return
            if path == "/api/v1/auth/login":
                assert b"synthetic.loadtest.invalid" in body
                data = {"access_token": "a", "refresh_token": "r", "expires_in": 1800}
            elif path.startswith("/api/v1/projects"):
                data = [{"id": "p1"}] if path == "/api/v1/projects" else {"id": "p1"}
            elif path == "/api/v1/project-conversations" and method == "POST":
                data = {"id": "c1"}
            else:
                data = {"status": "ok"}
            raw = json.dumps(data).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(raw)).encode() + b"\r\n\r\n" + raw)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        return
    finally:
        writer.close()


def test_end_to_end_against_local_fake_api(tmp_path):
    async def scenario():
        seen: list = []
        server = await asyncio.start_server(lambda r, w: fake_api(r, w, seen), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        cfg = load.LoadConfig(target=f"http://127.0.0.1:{port}", run_id=RUN_ID, ramp=(2, 4), stage_seconds=1,
                              steady_seconds=2, think_ms=200, ai_rps_max=0, allow_lab_target=True,
                              max_duration_seconds=60)
        emails = [f"{RUN_ID}-{i:05d}@synthetic.loadtest.invalid" for i in range(4)]
        async with server:
            metrics, stop = await load.execute(cfg, emails, "x" * 20, stop_file=None, ca_file=None)
        return cfg, metrics, stop, seen

    cfg, metrics, stop, seen = asyncio.run(scenario())
    assert stop is None
    receipt = load.build_receipt(cfg, metrics, stop, time.time())
    assert receipt["routes"]["auth_login"]["count"] == 4
    assert receipt["routes"]["conversation_create"]["count"] == 4
    assert ("GET", "/api/v1/realtime/connect") in seen
    assert receipt["verdict"]["errors"] == 0
    assert receipt["steady_state"]["signed_in_vus_min"] == 4
    assert not any(path == "/api/v1/project-conversations/c1/messages" and m == "POST" for m, path in seen)
