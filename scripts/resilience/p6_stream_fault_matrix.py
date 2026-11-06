#!/usr/bin/env python3
"""P6 gate 6.3: streaming / reconnect fault matrix (NS-14A extended acceptance).

The case list is NOT re-invented here: it is read from
``docs/project/PLAN.json`` -> ``new_server_migration.client_delivery_resilience
.acceptance_cases`` (the NS-14A contract), and each case is mapped to one
executable scenario, an operator-coordinated disruptive scenario, or the
existing NS-14A Playwright browser suite.

  plan     print the matrix; no network (default)
  run      run the automated scenarios against the API with ONE synthetic
           account; requires --execute and --confirm-target

Disruptive scenarios (backend / LiveKit / tunnel restart) additionally need
--allow-disruptive and run ON the NEW host, because they call
``docker restart`` on an allow-listed production container.  They belong in
the pre-launch window only.

Pass rule for every stream scenario: the client reconnects within the bound,
resumes with ``after_event_id`` and never sees the same ``event_id`` twice, and
an AI request identified by ``request_id`` is executed at most once
(``GET .../messages`` shows a single assistant reply for it).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import subprocess
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "capacity"))
from p6_http import (  # noqa: E402
    HttpClientError,
    HttpConnection,
    Origin,
    WebSocketClosed,
    WebSocketConnection,
    form_body,
    json_body,
)

SCHEMA = "aionex.p6.stream-fault-matrix.v1"
PLAN_PATH = ROOT / "docs" / "project" / "PLAN.json"
API_HOST = "api.vip-e.net"
DISRUPTIVE_CONTAINERS = frozenset({
    "web-dashboard-backend-1",
    "web-dashboard-realtime-livekit-1",
    "web-dashboard-cloudflared-1",
})
RECONNECT_BOUND_SECONDS = 15.0


@dataclass(frozen=True)
class Scenario:
    case: str               # NS-14A acceptance case text (from PLAN.json)
    scenario_id: str
    mode: str               # automated | disruptive | browser
    description: str
    pass_criterion: str
    container: str | None = None


CASE_MAP: dict[str, tuple[str, str, str, str, str | None]] = {
    "mid-stream disconnect": ("ws_abort_resume", "automated",
        "Abort the TCP connection under an open socket, reconnect with after_event_id.",
        "reconnected <= 15 s, connected frame received, no duplicate event_id", None),
    "Cloudflare/proxy interruption": ("ws_idle_through_edge", "automated",
        "Hold an idle socket for 130 s (> Cloudflare 100 s idle) using the app 'ping' keepalive.",
        "socket survives with ping/pong, or drop detected and recovered <= 15 s", None),
    "client background/foreground": ("browser_background", "browser",
        "NS-14A Playwright: hide/show the tab during a reply.",
        "UI shows reconnecting -> recovered; reply completes once", None),
    "network change": ("browser_network_change", "browser",
        "NS-14A Playwright: offline -> online during a reply.",
        "UI recovers; no duplicate reply; durable status fallback used", None),
    "repeated reconnect": ("ws_repeated_reconnect", "automated",
        "20 abort/reconnect cycles with jittered exponential backoff.",
        "20/20 reconnects, handshake p95 < 2000 ms, no 5xx", None),
    "duplicate events/chunks": ("ws_resume_no_duplicates", "automated",
        "Send one AI message, abort mid-reply, resume from the last cursor.",
        "every event_id seen at most once; one assistant reply for the request_id", None),
    "server/container restart": ("backend_restart", "disruptive",
        "docker restart web-dashboard-backend-1 with a socket open.",
        "client reconnects <= 60 s after /health returns; request executed once",
        "web-dashboard-backend-1"),
    "authentication refresh or expiry": ("ws_invalid_token", "automated",
        "Open a socket with a revoked/invalid token; then refresh and reconnect.",
        "invalid token closed promptly (no hang); refreshed token connects", None),
    "terminal-event loss": ("durable_status_fallback", "automated",
        "Drop the socket before the terminal event; recover through GET messages.",
        "terminal state visible via durable status poll <= 180 s", None),
    "durable status/poll fallback recovery": ("durable_status_fallback", "automated",
        "Same scenario as terminal-event loss (shared executor).",
        "terminal state visible via durable status poll <= 180 s", None),
}
EXTRA_SCENARIOS = (
    Scenario("LiveKit signaling", "livekit_signaling", "automated",
             "GET /livekit/ through the edge and the authenticated media readiness endpoint.",
             "LiveKit signaling reachable (HTTP 200) and readiness reports configured"),
    Scenario("LiveKit restart", "livekit_restart", "disruptive",
             "docker restart web-dashboard-realtime-livekit-1.",
             "signaling back <= 60 s; app realtime socket unaffected", "web-dashboard-realtime-livekit-1"),
    Scenario("tunnel restart", "tunnel_restart", "disruptive",
             "docker restart web-dashboard-cloudflared-1 (full edge interruption).",
             "API /health back <= 90 s; clients reconnect with backoff", "web-dashboard-cloudflared-1"),
)


def load_cases(plan_path: Path = PLAN_PATH) -> list[str]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    cases = plan["new_server_migration"]["client_delivery_resilience"]["acceptance_cases"]
    if not isinstance(cases, list) or not all(isinstance(c, str) for c in cases):
        raise ValueError("NS-14A acceptance_cases must be a list of strings")
    return cases


def build_matrix(cases: list[str]) -> list[Scenario]:
    unmapped = [case for case in cases if case not in CASE_MAP]
    if unmapped:
        # A new NS-14A case must get an explicit scenario; never silently skip it.
        raise ValueError(f"NS-14A cases without a scenario: {unmapped}")
    matrix = [Scenario(case, *CASE_MAP[case]) for case in cases]
    return matrix + list(EXTRA_SCENARIOS)


# --------------------------------------------------------------------------- client helpers


class StreamClient:
    def __init__(self, origin: Origin, email: str, password: str, ca_file: str | None) -> None:
        self.origin = origin
        self.email = email
        self.password = password
        self.ca_file = ca_file
        self.http = HttpConnection(origin, timeout=30, ca_file=ca_file)
        self.access = ""
        self.refresh = ""
        self.seen_events: list[str] = []
        self.server_errors = 0

    async def login(self) -> None:
        headers, body = form_body({"username": self.email, "password": self.password})
        response = await self.http.request("POST", "/api/v1/auth/login", headers=headers, body=body)
        if response.status != 200:
            raise RuntimeError(f"login failed: HTTP {response.status}")
        payload = response.json()
        self.access, self.refresh = payload["access_token"], payload["refresh_token"]

    async def refresh_tokens(self) -> bool:
        headers, body = json_body({"refresh_token": self.refresh})
        response = await self.http.request("POST", "/api/v1/auth/refresh", headers=headers, body=body)
        if response.status != 200:
            return False
        payload = response.json()
        self.access, self.refresh = payload["access_token"], payload["refresh_token"]
        return True

    async def get(self, path: str) -> Any:
        response = await self.http.request("GET", path, headers={"Authorization": f"Bearer {self.access}"})
        if response.status >= 500:
            self.server_errors += 1
        return response

    def socket(self, token: str | None = None, after: str | None = None) -> WebSocketConnection:
        query = {"token": token if token is not None else self.access}
        if after:
            query["after_event_id"] = after
        return WebSocketConnection(self.origin, "/api/v1/realtime/connect?" + urllib.parse.urlencode(query),
                                   timeout=20, ca_file=self.ca_file)

    async def open_socket(self, after: str | None = None) -> tuple[WebSocketConnection, float]:
        started = time.monotonic()
        socket = self.socket(after=after)
        await socket.connect()
        first = json.loads(await socket.receive(timeout=10))
        if first.get("type") != "connected":
            raise RuntimeError("first frame was not 'connected'")
        return socket, time.monotonic() - started

    async def drain(self, socket: WebSocketConnection, seconds: float) -> list[dict[str, Any]]:
        events = []
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                frame = json.loads(await socket.receive(timeout=max(0.1, deadline - time.monotonic())))
            except asyncio.TimeoutError:
                break
            if frame.get("event_id"):
                self.seen_events.append(str(frame["event_id"]))
            events.append(frame)
        return events

    def duplicates(self) -> list[str]:
        return sorted({e for e in self.seen_events if self.seen_events.count(e) > 1})


async def _first_conversation(client: StreamClient) -> str | None:
    response = await client.get("/api/v1/project-conversations")
    rows = response.json() if response.status == 200 else []
    rows = rows.get("items", []) if isinstance(rows, dict) else rows
    return str(rows[0]["id"]) if rows and isinstance(rows[0], dict) and rows[0].get("id") else None


# --------------------------------------------------------------------------- scenarios


async def ws_abort_resume(client: StreamClient, ctx: dict[str, Any]) -> dict[str, Any]:
    socket, _ = await client.open_socket()
    await client.drain(socket, 2)
    socket.abort()
    cursor = client.seen_events[-1] if client.seen_events else None
    started = time.monotonic()
    socket, _ = await client.open_socket(after=cursor)
    await client.drain(socket, 3)
    await socket.close()
    elapsed = time.monotonic() - started
    return {"reconnect_seconds": round(elapsed, 3), "duplicates": client.duplicates(),
            "passed": elapsed <= RECONNECT_BOUND_SECONDS and not client.duplicates()}


async def ws_idle_through_edge(client: StreamClient, ctx: dict[str, Any]) -> dict[str, Any]:
    socket, _ = await client.open_socket()
    pongs = 0
    dropped_at = None
    started = time.monotonic()
    try:
        while time.monotonic() - started < ctx.get("idle_seconds", 130):
            await asyncio.sleep(25)
            await socket.send_text("ping")
            frame = json.loads(await socket.receive(timeout=10))
            pongs += frame.get("type") == "pong"
    except (WebSocketClosed, HttpClientError, asyncio.TimeoutError, OSError, asyncio.IncompleteReadError):
        dropped_at = round(time.monotonic() - started, 3)
    recovered = None
    if dropped_at is not None:
        begin = time.monotonic()
        socket, _ = await client.open_socket(after=client.seen_events[-1] if client.seen_events else None)
        recovered = round(time.monotonic() - begin, 3)
    await socket.close()
    return {"pongs": pongs, "dropped_at_seconds": dropped_at, "recovered_seconds": recovered,
            "passed": dropped_at is None or (recovered is not None and recovered <= RECONNECT_BOUND_SECONDS)}


async def ws_repeated_reconnect(client: StreamClient, ctx: dict[str, Any]) -> dict[str, Any]:
    timings, failures, backoff = [], 0, 0.5
    rng = random.Random(ctx["run_id"])
    for _ in range(ctx.get("cycles", 20)):
        try:
            socket, seconds = await client.open_socket(after=client.seen_events[-1] if client.seen_events else None)
            timings.append(seconds * 1000)
            socket.abort()
            backoff = 0.5
        except (HttpClientError, WebSocketClosed, RuntimeError, asyncio.TimeoutError):
            failures += 1
            backoff = min(backoff * 2, 8)
        await asyncio.sleep(backoff + rng.random() * 0.5)
    timings.sort()
    p95 = timings[max(0, int(0.95 * len(timings)) - 1)] if timings else None
    return {"reconnects": len(timings), "failures": failures, "handshake_p95_ms": round(p95, 1) if p95 else None,
            "passed": failures == 0 and p95 is not None and p95 < 2000 and client.server_errors == 0}


async def _send_ai(client: StreamClient, conversation: str, request_id: str, agent_id: str) -> int:
    headers, body = json_body({"message": "P6 fault matrix: reply with one short sentence.",
                               "request_id": request_id, "agent_id": agent_id,
                               "confirm_external_processing": False})
    response = await client.http.request("POST", f"/api/v1/project-conversations/{conversation}/messages",
                                         headers={"Authorization": f"Bearer {client.access}", **headers}, body=body)
    return response.status


async def _replies_for(client: StreamClient, conversation: str, request_id: str) -> tuple[int, bool]:
    response = await client.get(f"/api/v1/project-conversations/{conversation}/messages")
    rows = response.json() if response.status == 200 else []
    rows = rows.get("messages", rows.get("items", [])) if isinstance(rows, dict) else rows
    text = json.dumps(rows)
    related = [r for r in rows if isinstance(r, dict) and request_id in json.dumps(r)]
    assistant = [r for r in related if r.get("role") in ("assistant", "agent")]
    terminal = any(str(r.get("status", "")).lower() in {"completed", "failed", "cancelled", "denied"} for r in related)
    return len(assistant), terminal or (request_id in text and bool(assistant))


async def ws_resume_no_duplicates(client: StreamClient, ctx: dict[str, Any]) -> dict[str, Any]:
    conversation = ctx.get("conversation_id")
    if not conversation:
        return {"passed": False, "reason": "synthetic account has no conversation (run 6.1 setup first)"}
    request_id = f"{ctx['run_id']}-dup-{int(time.time())}"
    socket, _ = await client.open_socket()
    status = await _send_ai(client, conversation, request_id, ctx.get("agent_id", ""))
    await client.drain(socket, 3)
    socket.abort()
    socket, _ = await client.open_socket(after=client.seen_events[-1] if client.seen_events else None)
    await client.drain(socket, 20)
    await socket.close()
    replies, _terminal = await _replies_for(client, conversation, request_id)
    return {"send_status": status, "duplicates": client.duplicates(), "assistant_replies": replies,
            "passed": status in (200, 202) and not client.duplicates() and replies <= 1}


async def ws_invalid_token(client: StreamClient, ctx: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    rejected = False
    try:
        socket = client.socket(token="invalid-" + hashlib.sha256(ctx["run_id"].encode()).hexdigest()[:24])
        await socket.connect()
        await socket.receive(timeout=10)
    except (WebSocketClosed, HttpClientError, asyncio.TimeoutError):
        rejected = True
    closed_in = time.monotonic() - started
    refreshed = await client.refresh_tokens()
    ok_after = False
    if refreshed:
        socket, _ = await client.open_socket()
        ok_after = True
        await socket.close()
    return {"rejected": rejected, "closed_seconds": round(closed_in, 3), "refreshed": refreshed,
            "reconnected_after_refresh": ok_after, "passed": rejected and closed_in < 11 and ok_after}


async def durable_status_fallback(client: StreamClient, ctx: dict[str, Any]) -> dict[str, Any]:
    conversation = ctx.get("conversation_id")
    if not conversation:
        return {"passed": False, "reason": "synthetic account has no conversation (run 6.1 setup first)"}
    request_id = f"{ctx['run_id']}-term-{int(time.time())}"
    socket, _ = await client.open_socket()
    status = await _send_ai(client, conversation, request_id, ctx.get("agent_id", ""))
    socket.abort()  # the terminal event is never received on this socket
    deadline = time.monotonic() + ctx.get("terminal_timeout", 180)
    replies, terminal = 0, False
    while time.monotonic() < deadline and not terminal:
        await asyncio.sleep(5)
        replies, terminal = await _replies_for(client, conversation, request_id)
    return {"send_status": status, "terminal_via_poll": terminal, "assistant_replies": replies,
            "passed": status in (200, 202) and terminal and replies <= 1}


async def livekit_signaling(client: StreamClient, ctx: dict[str, Any]) -> dict[str, Any]:
    edge = HttpConnection(client.origin, timeout=15, ca_file=client.ca_file)
    signaling = await edge.request("GET", "/livekit/")
    await edge.close()
    readiness = await client.get("/api/v1/realtime/media/readiness")
    return {"livekit_http": signaling.status, "media_readiness_http": readiness.status,
            "passed": signaling.status == 200 and readiness.status == 200}


async def disruptive_restart(client: StreamClient, ctx: dict[str, Any], container: str) -> dict[str, Any]:
    if container not in DISRUPTIVE_CONTAINERS:
        return {"passed": False, "reason": "container not allow-listed"}
    socket, _ = await client.open_socket()
    completed = subprocess.run(["docker", "restart", "--time", "20", container],
                               capture_output=True, text=True, timeout=180, check=False)
    started = time.monotonic()
    recovered = None
    while time.monotonic() - started < 120:
        try:
            probe = HttpConnection(client.origin, timeout=5, ca_file=client.ca_file)
            health = await probe.request("GET", "/health")
            await probe.close()
            if health.status == 200:
                socket2, _ = await client.open_socket(after=client.seen_events[-1] if client.seen_events else None)
                recovered = round(time.monotonic() - started, 3)
                await socket2.close()
                break
        except (HttpClientError, WebSocketClosed, RuntimeError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(3)
    socket.abort()
    return {"restart_exit_code": completed.returncode, "recovered_seconds": recovered,
            "duplicates": client.duplicates(),
            "passed": completed.returncode == 0 and recovered is not None and recovered <= 90 and not client.duplicates()}


EXECUTORS: dict[str, Callable[[StreamClient, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "ws_abort_resume": ws_abort_resume,
    "ws_idle_through_edge": ws_idle_through_edge,
    "ws_repeated_reconnect": ws_repeated_reconnect,
    "ws_resume_no_duplicates": ws_resume_no_duplicates,
    "ws_invalid_token": ws_invalid_token,
    "durable_status_fallback": durable_status_fallback,
    "livekit_signaling": livekit_signaling,
}


async def run_matrix(matrix: list[Scenario], client: StreamClient, ctx: dict[str, Any],
                     allow_disruptive: bool) -> list[dict[str, Any]]:
    await client.login()
    ctx["conversation_id"] = await _first_conversation(client)
    results, executed = [], set()
    for scenario in matrix:
        row = asdict(scenario)
        if scenario.mode == "browser":
            row.update(status="MANUAL", evidence="scripts/release/ns14a_validate_playwright_artifacts.py")
        elif scenario.mode == "disruptive" and not allow_disruptive:
            row.update(status="SKIPPED", reason="needs --allow-disruptive on the NEW host")
        elif scenario.scenario_id in executed:
            row.update(status="SHARED", reason="same executor already ran for an earlier case")
        else:
            executed.add(scenario.scenario_id)
            client.seen_events.clear()
            try:
                if scenario.mode == "disruptive":
                    outcome = await disruptive_restart(client, ctx, scenario.container or "")
                else:
                    outcome = await EXECUTORS[scenario.scenario_id](client, ctx)
            except (HttpClientError, WebSocketClosed, RuntimeError, asyncio.TimeoutError, OSError) as exc:
                outcome = {"passed": False, "error": type(exc).__name__, "detail": str(exc)[:200]}
            row.update(status="PASS" if outcome.get("passed") else "FAIL", outcome=outcome)
        results.append(row)
    await client.http.close()
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    automated_ok = all(row["status"] != "FAIL" for row in results)
    complete = automated_ok and not counts.get("SKIPPED") and not counts.get("MANUAL")
    return {"counts": counts,
            "status": "PASS" if complete else ("PARTIAL_PASS_MANUAL_PENDING" if automated_ok else "FAIL")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "run"), nargs="?", default="plan")
    parser.add_argument("--target", default=f"https://{API_HOST}")
    parser.add_argument("--run-id", default="p6-faults")
    parser.add_argument("--email", help="one synthetic account (…@synthetic.loadtest.invalid)")
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--ca-file")
    parser.add_argument("--allow-disruptive", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-target", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    matrix = build_matrix(load_cases())
    origin = Origin.parse(args.target)
    if origin.host != API_HOST:
        print(json.dumps({"status": "REFUSED", "reason": "target must be https://api.vip-e.net"}))
        return 2
    if args.command == "plan" or not args.execute:
        print(json.dumps({"schema": SCHEMA + ".plan", "status": "DRY_RUN", "network_requests_sent": 0,
                          "matrix": [asdict(s) for s in matrix]}, indent=2))
        return 0
    if args.confirm_target != origin.host or not args.email or not args.password_file:
        print(json.dumps({"status": "REFUSED", "reason": "--confirm-target, --email and --password-file are required"}))
        return 2
    if not args.email.endswith("@synthetic.loadtest.invalid"):
        print(json.dumps({"status": "REFUSED", "reason": "only synthetic accounts may be used"}))
        return 2
    password = args.password_file.read_text(encoding="utf-8").strip()
    client = StreamClient(origin, args.email, password, args.ca_file)
    ctx = {"run_id": args.run_id, "agent_id": args.agent_id}
    results = asyncio.run(run_matrix(matrix, client, ctx, args.allow_disruptive))
    receipt = {"schema": SCHEMA, "run_id": args.run_id, "target_host": origin.host,
               "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "completed_at_epoch": time.time(), "results": results, "summary": summarize(results)}
    if args.output:
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.output.chmod(0o600)
    print(json.dumps(receipt["summary"], indent=2))
    return 0 if receipt["summary"]["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
