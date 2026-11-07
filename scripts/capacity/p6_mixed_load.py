#!/usr/bin/env python3
"""P6 gate 6.1: bounded, authenticated, mixed-profile load test against the API.

Runs from a SEPARATE load-generator machine (Python 3.11+, stdlib only) against
``https://api.vip-e.net`` with synthetic accounts created by
``app.services.synthetic_load_accounts``.  It never targets the static cPanel
portal (``vip-e.net`` / ``ai.vip-e.net``, Apache + WAF) or the owner app.

Commands
  plan       print the resolved ramp/workload/stop plan; no network (the default)
  preflight  2 health reads + 1 synthetic login; proves reachability/auth only
  run        the load test; refuses unless --execute and --confirm-target match

Pass criteria (evaluated by ``evaluate_verdict``):
  * P95 of every non-AI request in the steady window   < 500 ms
  * error rate over the whole run                      < 1 %
  * no 5xx storm (a 10 s bucket with >= max(20, 1 %) 5xx)
  * the final ramp stage held >= --steady-seconds with all VUs signed in

Hard stops (``StopPolicy``): edge/WAF block, sliding-window error rate, 5xx
storm, latency collapse, transport collapse, origin /health failing, operator
stop file, max duration.  On a stop the receipt status is ABORTED.

The receipt is load-side evidence.  FR-09 FULL_MIXED acceptance additionally
needs the server-side presence samples (``fr09_presence_capture``) and DB
accounting, judged by ``scripts/capacity/fr09_evidence_gate.py``.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import json
import math
import os
import random
import resource
import stat
import sys
import time
import urllib.parse
from array import array
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p6_http import (  # noqa: E402
    HttpClientError,
    HttpConnection,
    HttpResponse,
    Origin,
    WebSocketClosed,
    WebSocketConnection,
    form_body,
    json_body,
)

SCHEMA = "aionex.p6.mixed-load.v1"
DEFAULT_RAMP = (25, 100, 250, 500, 1000, 2500, 5000)
PRODUCTION_API_HOST = "api.vip-e.net"
# Static cPanel/Apache hosts (WAF can block the generator IP) and the owner app
# behind Cloudflare Access are never load-test targets.
FORBIDDEN_HOSTS = frozenset({"vip-e.net", "www.vip-e.net", "ai.vip-e.net", "gabarot.vip-e.net"})
SYNTHETIC_EMAIL_SUFFIX = "@synthetic.loadtest.invalid"
NON_AI_P95_MAX_MS = 500.0
ERROR_RATE_MAX = 0.01
STORM_BUCKET_SECONDS = 10
STORM_MIN_5XX = 20
STORM_RATIO = 0.01


class PlanError(ValueError):
    """The requested run is unsafe or malformed; nothing was sent."""


class _HardStop(Exception):
    """Internal: a stop condition fired; unwind the ramp."""


# --------------------------------------------------------------------------- workload


@dataclass(frozen=True)
class Action:
    name: str
    weight: int
    ai: bool = False
    write: bool = False
    # Plan-gated routes (Ads is a paid-plan feature): the synthetic free accounts
    # are correctly refused with a JSON 403, which is a policy outcome, not an error.
    entitlement_gated: bool = False


WORKLOAD: tuple[Action, ...] = (
    Action("auth_me", 10),
    Action("auth_refresh", 2, write=True),
    Action("portal_published", 8),
    Action("projects_list", 18),
    Action("project_read", 16),
    Action("conversations_list", 10),
    Action("conversation_messages", 6),
    Action("social_providers", 4),
    Action("social_connections", 4),
    Action("ads_access", 4),
    Action("ads_connections", 3, entitlement_gated=True),
    Action("notifications", 5),
    Action("ai_message", 2, ai=True, write=True),
)


def choose_action(rng: random.Random, workload: tuple[Action, ...] = WORKLOAD) -> Action:
    total = sum(item.weight for item in workload)
    pick = rng.uniform(0, total)
    upto = 0.0
    for item in workload:
        upto += item.weight
        if pick <= upto:
            return item
    return workload[-1]


# --------------------------------------------------------------------------- config + guards


@dataclass(frozen=True)
class LoadConfig:
    target: str
    run_id: str
    ramp: tuple[int, ...] = DEFAULT_RAMP
    stage_seconds: int = 120
    steady_seconds: int = 900
    think_ms: int = 3000
    ai_rps_max: float = 0.2
    ai_concurrency_max: int = 4
    ai_agent_id: str = ""
    conversations_per_vu: int = 1
    hold_realtime_socket: bool = True
    request_timeout: float = 30.0
    max_duration_seconds: int = 3600
    allow_lab_target: bool = False

    def origin(self) -> Origin:
        return Origin.parse(self.target)

    @property
    def max_vus(self) -> int:
        return max(self.ramp)


def validate_config(config: LoadConfig) -> list[str]:
    """Return the list of reasons the config is unsafe (empty means OK)."""
    problems: list[str] = []
    try:
        origin = config.origin()
    except ValueError as exc:
        return [str(exc)]
    if origin.host in FORBIDDEN_HOSTS:
        problems.append(f"{origin.host} is a static/owner host and is never a load-test target")
    lab = origin.host in {"127.0.0.1", "localhost"} or origin.host.endswith(".internal")
    if origin.host != PRODUCTION_API_HOST and not (config.allow_lab_target and lab):
        problems.append("target must be https://api.vip-e.net (or a lab host with --allow-lab-target)")
    if origin.host == PRODUCTION_API_HOST and origin.scheme != "https":
        problems.append("production API must be reached over https")
    if not config.run_id.startswith("p6-") or len(config.run_id) > 40:
        problems.append("run id must be the synthetic seeding run id (p6-...)")
    ramp = list(config.ramp)
    if not ramp or ramp != sorted(set(ramp)) or ramp[0] < 1:
        problems.append("ramp must be strictly increasing positive integers")
    elif ramp[-1] > 6000:
        problems.append("ramp is capped at 6000 virtual users")
    if not 10 <= config.stage_seconds <= 1800:
        problems.append("stage seconds must be between 10 and 1800")
    if not 0 <= config.steady_seconds <= 7200:
        problems.append("steady seconds must be between 0 and 7200")
    if not 200 <= config.think_ms <= 60000:
        problems.append("think time must be between 200 ms and 60 s")
    if not 0 <= config.ai_rps_max <= 2.0:
        problems.append("AI rate cap must be between 0 and 2 requests/s (AIONEX AI capacity)")
    if not 0 <= config.ai_concurrency_max <= 16:
        problems.append("AI concurrency cap must be between 0 and 16")
    if not 0 <= config.conversations_per_vu <= 3:
        problems.append("conversations per VU must be between 0 and 3")
    minimum = len(config.ramp) * config.stage_seconds + config.steady_seconds
    if config.max_duration_seconds < minimum:
        problems.append("max duration is shorter than the ramp + steady plan")
    if config.max_duration_seconds > 4 * 3600:
        problems.append("max duration is capped at 4 hours")
    return problems


def build_schedule(config: LoadConfig) -> list[dict[str, Any]]:
    """Ramp schedule: each stage spreads its new VUs evenly over the stage."""
    schedule = []
    previous = 0
    offset = 0
    for index, users in enumerate(config.ramp):
        final = index == len(config.ramp) - 1
        hold = config.stage_seconds + (config.steady_seconds if final else 0)
        schedule.append({
            "stage": index + 1,
            "users": users,
            "new_users": users - previous,
            "starts_at_second": offset,
            "spawn_interval_ms": round(config.stage_seconds * 1000 / max(1, users - previous), 3),
            "hold_seconds": hold,
            "steady": final,
        })
        offset += hold
        previous = users
    return schedule


def estimate_load(config: LoadConfig) -> dict[str, Any]:
    peak_rps = config.max_vus / (config.think_ms / 1000.0)
    ai_weight = sum(a.weight for a in WORKLOAD if a.ai) / sum(a.weight for a in WORKLOAD)
    return {
        "peak_vus": config.max_vus,
        "peak_request_rate_per_second": round(peak_rps, 1),
        "ai_requests_wanted_per_second": round(peak_rps * ai_weight, 2),
        "ai_requests_capped_per_second": config.ai_rps_max,
        "realtime_sockets_at_peak": config.max_vus if config.hold_realtime_socket else 0,
        "open_files_needed": config.max_vus * (2 if config.hold_realtime_socket else 1) + 256,
        "total_planned_seconds": sum(s["hold_seconds"] for s in build_schedule(config)),
    }


def read_accounts(path: Path, run_id: str, needed: int) -> list[str]:
    emails: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        email = str(row.get("email", "")).strip().lower()
        if row.get("run_id") != run_id or not email.endswith(SYNTHETIC_EMAIL_SUFFIX) or not email.startswith(run_id + "-"):
            raise PlanError("accounts file contains a non-synthetic or foreign-run account")
        emails.append(email)
    if len(set(emails)) != len(emails):
        raise PlanError("accounts file has duplicate accounts")
    if len(emails) < needed:
        raise PlanError(f"accounts file has {len(emails)} accounts, ramp needs {needed}")
    return emails[:needed]


def read_password(path: Path) -> str:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PlanError("password file must be a regular 0600 file")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 16:
        raise PlanError("synthetic password is too short")
    return value


# --------------------------------------------------------------------------- metrics


def percentile(values: list[float] | array, fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return round(float(ordered[rank]), 3)


def classify(action: Action, response: HttpResponse | None, error: str | None) -> str:
    """ok | policy | client_error | server_error | edge_block | transport."""
    if response is None:
        return "transport"
    status = response.status
    server = response.headers.get("server", "").lower()
    if response.headers.get("cf-mitigated") or (status in (403, 429, 1020) and "cloudflare" in server
                                                and "json" not in response.headers.get("content-type", "")):
        return "edge_block"
    if 200 <= status < 400:
        return "ok"
    if status >= 500:
        return "server_error"
    if action.entitlement_gated and status == 403:
        return "policy"
    if action.ai and status in (402, 403, 409, 422, 429):
        # Governed AI admission (plan/quota/consent/capacity) is a legitimate
        # policy denial; it is counted separately, never hidden.
        return "policy"
    return "client_error"


ERROR_KINDS = frozenset({"client_error", "server_error", "edge_block", "transport"})


@dataclass
class RouteStats:
    latencies: array = field(default_factory=lambda: array("d"))
    statuses: collections.Counter = field(default_factory=collections.Counter)
    kinds: collections.Counter = field(default_factory=collections.Counter)

    def summary(self) -> dict[str, Any]:
        count = sum(self.kinds.values())
        errors = sum(self.kinds[k] for k in ERROR_KINDS)
        return {
            "count": count,
            "errors": errors,
            "policy_denials": self.kinds["policy"],
            "p50_ms": percentile(self.latencies, 0.50),
            "p95_ms": percentile(self.latencies, 0.95),
            "p99_ms": percentile(self.latencies, 0.99),
            "max_ms": round(max(self.latencies), 3) if self.latencies else None,
            "status_histogram": {str(k): v for k, v in sorted(self.statuses.items(), key=lambda kv: str(kv[0]))},
            "kinds": dict(self.kinds),
        }


@dataclass
class Metrics:
    started: float = field(default_factory=time.time)
    routes: dict[str, RouteStats] = field(default_factory=lambda: collections.defaultdict(RouteStats))
    steady_routes: dict[str, RouteStats] = field(default_factory=lambda: collections.defaultdict(RouteStats))
    buckets: dict[int, list[int]] = field(default_factory=lambda: collections.defaultdict(lambda: [0, 0]))
    window: collections.deque = field(default_factory=collections.deque)
    steady_start: float | None = None
    steady_end: float | None = None
    steady_active_min: int | None = None
    active_vus: int = 0
    signed_in: int = 0
    ai_inflight: int = 0
    ai_inflight_max: int = 0
    ws_connected: int = 0
    ws_drops: int = 0
    edge_blocks: int = 0
    consecutive_transport: int = 0

    def record(self, action: Action, kind: str, status: int | None, latency_ms: float | None, now: float) -> None:
        stats = self.routes[action.name]
        stats.kinds[kind] += 1
        stats.statuses[status if status is not None else "transport"] += 1
        if latency_ms is not None:
            stats.latencies.append(latency_ms)
        if self.steady_start is not None and self.steady_end is None:
            steady = self.steady_routes[action.name]
            steady.kinds[kind] += 1
            steady.statuses[status if status is not None else "transport"] += 1
            if latency_ms is not None:
                steady.latencies.append(latency_ms)
        bucket = self.buckets[int(now // STORM_BUCKET_SECONDS)]
        bucket[0] += 1
        if kind == "server_error":
            bucket[1] += 1
        if kind == "edge_block":
            self.edge_blocks += 1
        self.consecutive_transport = self.consecutive_transport + 1 if kind == "transport" else 0
        self.window.append((now, kind, latency_ms, action.ai))
        while self.window and self.window[0][0] < now - 30:
            self.window.popleft()


def storm_buckets(buckets: dict[int, list[int]]) -> list[dict[str, Any]]:
    storms = []
    for key, (total, five_xx) in sorted(buckets.items()):
        if five_xx >= max(STORM_MIN_5XX, math.ceil(STORM_RATIO * total)):
            storms.append({"bucket_start_epoch": key * STORM_BUCKET_SECONDS, "requests": total, "server_errors": five_xx})
    return storms


@dataclass(frozen=True)
class StopPolicy:
    window_min_requests: int = 200
    window_error_rate: float = 0.05
    window_5xx: int = 50
    window_non_ai_p95_ms: float = 5000.0
    consecutive_transport: int = 100
    health_failures: int = 3

    def check(self, metrics: Metrics, *, health_failures: int) -> str | None:
        if metrics.edge_blocks:
            return "edge_or_waf_block"
        if metrics.consecutive_transport >= self.consecutive_transport:
            return "transport_collapse"
        if health_failures >= self.health_failures:
            return "origin_health_failing"
        window = list(metrics.window)
        if len(window) >= self.window_min_requests:
            errors = sum(1 for row in window if row[1] in ERROR_KINDS)
            if errors / len(window) > self.window_error_rate:
                return "error_rate"
            if sum(1 for row in window if row[1] == "server_error") >= self.window_5xx:
                return "5xx_storm"
            latencies = [row[2] for row in window if row[2] is not None and not row[3]]
            p95 = percentile(latencies, 0.95)
            if p95 is not None and p95 > self.window_non_ai_p95_ms:
                return "latency_collapse"
        return None


def evaluate_verdict(metrics: Metrics, config: LoadConfig, stop_reason: str | None) -> dict[str, Any]:
    totals = collections.Counter()
    for stats in metrics.routes.values():
        totals.update(stats.kinds)
    requests = sum(totals.values())
    errors = sum(totals[k] for k in ERROR_KINDS)
    error_rate = errors / requests if requests else None
    steady_non_ai: list[float] = []
    for name, stats in metrics.steady_routes.items():
        if not any(a.name == name and a.ai for a in WORKLOAD):
            steady_non_ai.extend(stats.latencies)
    steady_p95 = percentile(steady_non_ai, 0.95)
    storms = storm_buckets(metrics.buckets)
    steady_seconds = (
        (metrics.steady_end or 0) - metrics.steady_start if metrics.steady_start else 0
    )
    failed: list[str] = []
    if stop_reason:
        failed.append(f"stopped:{stop_reason}")
    if steady_p95 is None or steady_p95 >= NON_AI_P95_MAX_MS:
        failed.append("steady_non_ai_p95_lt_500ms")
    if error_rate is None or error_rate >= ERROR_RATE_MAX:
        failed.append("error_rate_lt_1pct")
    if storms:
        failed.append("no_5xx_storm")
    if steady_seconds < config.steady_seconds or (metrics.steady_active_min or 0) < config.max_vus:
        failed.append("steady_window_at_peak_vus")
    if metrics.ai_inflight_max > config.ai_concurrency_max:
        failed.append("ai_concurrency_cap_respected")
    status = "ABORTED" if stop_reason else ("PASS" if not failed else "FAIL")
    return {
        "status": status,
        "failed_criteria": failed,
        "requests": requests,
        "errors": errors,
        "policy_denials": totals["policy"],
        "error_rate": round(error_rate, 6) if error_rate is not None else None,
        "steady_non_ai_p95_ms": steady_p95,
        "steady_window_seconds": round(steady_seconds, 3),
        "steady_active_vus_min": metrics.steady_active_min,
        "five_xx_storm_buckets": storms,
    }


# --------------------------------------------------------------------------- runtime


class AiGate:
    """Global token bucket + in-flight cap for AI requests (AIONEX AI capacity)."""

    def __init__(self, rate: float, concurrency: int, metrics: Metrics) -> None:
        self.rate = rate
        self.capacity = max(1.0, rate)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.concurrency = concurrency
        self.metrics = metrics

    def try_acquire(self) -> bool:
        if self.rate <= 0 or self.concurrency <= 0:
            return False
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1 or self.metrics.ai_inflight >= self.concurrency:
            return False
        self.tokens -= 1
        self.metrics.ai_inflight += 1
        self.metrics.ai_inflight_max = max(self.metrics.ai_inflight_max, self.metrics.ai_inflight)
        return True

    def release(self) -> None:
        self.metrics.ai_inflight -= 1


@dataclass
class VirtualUser:
    index: int
    email: str
    config: LoadConfig
    password: str
    metrics: Metrics
    ai_gate: AiGate
    ca_file: str | None = None
    access: str = ""
    refresh: str = ""
    project_ids: list[str] = field(default_factory=list)
    conversation_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(f"{self.config.run_id}:{self.index}")
        self.http = HttpConnection(self.config.origin(), timeout=self.config.request_timeout, ca_file=self.ca_file)

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access}"}

    async def call(self, action: Action, method: str, path: str, *, headers: dict[str, str] | None = None,
                   body: bytes | None = None) -> HttpResponse | None:
        response: HttpResponse | None = None
        error: str | None = None
        started = time.perf_counter()
        try:
            response = await self.http.request(method, path, headers=headers, body=body)
        except HttpClientError as exc:
            error = exc.kind
        kind = classify(action, response, error)
        latency = response.elapsed_ms if response is not None else (time.perf_counter() - started) * 1000
        self.metrics.record(action, kind, response.status if response else None, latency, time.time())
        return response if kind in ("ok", "policy") else None

    async def login(self) -> bool:
        headers, body = form_body({"username": self.email, "password": self.password})
        for attempt in range(3):
            response = await self.call(Action("auth_login", 0, write=True), "POST", "/api/v1/auth/login",
                                       headers=headers, body=body)
            if response is not None:
                payload = response.json() or {}
                self.access = str(payload.get("access_token", ""))
                self.refresh = str(payload.get("refresh_token", ""))
                if self.access:
                    return True
            await asyncio.sleep(1.5 * (attempt + 1) + self.rng.random())
        return False

    async def refresh_tokens(self) -> bool:
        headers, body = json_body({"refresh_token": self.refresh})
        response = await self.call(Action("auth_refresh", 0, write=True), "POST", "/api/v1/auth/refresh",
                                   headers=headers, body=body)
        if response is None:
            return False
        payload = response.json() or {}
        self.access = str(payload.get("access_token", self.access))
        self.refresh = str(payload.get("refresh_token", self.refresh))
        return True

    async def setup(self) -> None:
        response = await self.call(Action("projects_list", 0), "GET", "/api/v1/projects", headers=self._auth())
        rows = (response.json() if response else None) or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("projects") or []
        self.project_ids = [str(row["id"]) for row in rows if isinstance(row, dict) and row.get("id")][:5]
        for number in range(self.config.conversations_per_vu if self.project_ids else 0):
            headers, body = json_body({
                "project_id": self.project_ids[number % len(self.project_ids)],
                "title": f"P6 synthetic conversation {number + 1}",
                # Deterministic request id: a re-run is idempotent, never duplicates.
                "request_id": f"{self.config.run_id}-{self.index:05d}-c{number}",
            })
            created = await self.call(Action("conversation_create", 0, write=True), "POST",
                                      "/api/v1/project-conversations", headers={**self._auth(), **headers}, body=body)
            payload = created.json() if created else None
            if isinstance(payload, dict) and payload.get("id"):
                self.conversation_ids.append(str(payload["id"]))

    async def act(self, action: Action) -> None:
        auth = self._auth()
        if action.name == "auth_me":
            await self.call(action, "GET", "/api/v1/auth/me", headers=auth)
        elif action.name == "auth_refresh":
            await self.refresh_tokens()
        elif action.name == "portal_published":
            await self.call(action, "GET", "/api/v1/portal/published")
        elif action.name == "projects_list":
            await self.call(action, "GET", "/api/v1/projects", headers=auth)
        elif action.name == "project_read" and self.project_ids:
            await self.call(action, "GET", f"/api/v1/projects/{self.rng.choice(self.project_ids)}", headers=auth)
        elif action.name == "conversations_list":
            query = f"?project_id={self.project_ids[0]}" if self.project_ids else ""
            await self.call(action, "GET", f"/api/v1/project-conversations{query}", headers=auth)
        elif action.name == "conversation_messages" and self.conversation_ids:
            await self.call(action, "GET",
                            f"/api/v1/project-conversations/{self.rng.choice(self.conversation_ids)}/messages",
                            headers=auth)
        elif action.name == "social_providers":
            await self.call(action, "GET", "/api/v1/social/providers", headers=auth)
        elif action.name == "social_connections":
            await self.call(action, "GET", "/api/v1/social/connections", headers=auth)
        elif action.name == "ads_access":
            await self.call(action, "GET", "/api/v1/ads/access", headers=auth)
        elif action.name == "ads_connections":
            await self.call(action, "GET", "/api/v1/ads/connections", headers=auth)
        elif action.name == "notifications":
            await self.call(action, "GET", "/api/v1/notifications", headers=auth)
        elif action.name == "ai_message" and self.conversation_ids and self.ai_gate.try_acquire():
            try:
                headers, body = json_body({
                    "message": "P6 synthetic load check: reply with one short sentence.",
                    "request_id": f"{self.config.run_id}-{self.index:05d}-m{self.rng.getrandbits(40):010x}",
                    "agent_id": self.config.ai_agent_id,
                    # Never consent to external (paid) processing from a load test.
                    "confirm_external_processing": False,
                })
                await self.call(action, "POST",
                                f"/api/v1/project-conversations/{self.conversation_ids[0]}/messages",
                                headers={**auth, **headers}, body=body)
            finally:
                self.ai_gate.release()

    async def hold_socket(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            path = "/api/v1/realtime/connect?" + urllib.parse.urlencode({"token": self.access})
            socket = WebSocketConnection(self.config.origin(), path, timeout=self.config.request_timeout,
                                         ca_file=self.ca_file)
            try:
                await socket.connect()
                self.metrics.ws_connected += 1
                backoff = 1.0
                try:
                    while not stop.is_set():
                        try:
                            await socket.receive(timeout=30)
                        except asyncio.TimeoutError:
                            continue
                finally:
                    self.metrics.ws_connected -= 1
            except (HttpClientError, WebSocketClosed, OSError, asyncio.IncompleteReadError):
                self.metrics.ws_drops += 1
            finally:
                await socket.close()
            if not stop.is_set():
                await asyncio.sleep(backoff + self.rng.random())
                backoff = min(backoff * 2, 30.0)

    async def run(self, stop: asyncio.Event) -> None:
        self.metrics.active_vus += 1
        socket_task: asyncio.Task | None = None
        signed_in = False
        try:
            if not await self.login():
                return
            signed_in = True
            self.metrics.signed_in += 1
            await self.setup()
            if self.config.hold_realtime_socket:
                socket_task = asyncio.create_task(self.hold_socket(stop))
            last_refresh = time.monotonic()
            while not stop.is_set():
                think = min(self.config.think_ms * 5, self.rng.expovariate(1.0 / self.config.think_ms))
                try:
                    await asyncio.wait_for(stop.wait(), timeout=think / 1000.0)
                    break
                except asyncio.TimeoutError:
                    pass
                if time.monotonic() - last_refresh > 20 * 60:
                    await self.refresh_tokens()
                    last_refresh = time.monotonic()
                await self.act(choose_action(self.rng))
        finally:
            self.metrics.active_vus -= 1
            if signed_in:
                self.metrics.signed_in -= 1
            if socket_task is not None:
                socket_task.cancel()
                await asyncio.gather(socket_task, return_exceptions=True)
            await self.http.close()


async def health_monitor(config: LoadConfig, stop: asyncio.Event, state: dict[str, int], ca_file: str | None) -> None:
    connection = HttpConnection(config.origin(), timeout=10, ca_file=ca_file)
    while not stop.is_set():
        try:
            response = await connection.request("GET", "/health")
            state["health_failures"] = 0 if response.status == 200 else state["health_failures"] + 1
        except HttpClientError:
            state["health_failures"] += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=10)
        except asyncio.TimeoutError:
            continue
    await connection.close()


async def execute(config: LoadConfig, emails: list[str], password: str, *, stop_file: Path | None,
                  ca_file: str | None, policy: StopPolicy = StopPolicy()) -> tuple[Metrics, str | None]:
    metrics = Metrics()
    stop = asyncio.Event()
    ai_gate = AiGate(config.ai_rps_max, config.ai_concurrency_max, metrics)
    state = {"health_failures": 0}
    tasks: list[asyncio.Task] = [asyncio.create_task(health_monitor(config, stop, state, ca_file))]
    stop_reason: str | None = None
    deadline = time.monotonic() + config.max_duration_seconds
    spawned = 0

    def check() -> str | None:
        if stop_file is not None and stop_file.exists():
            return "operator_stop_file"
        if time.monotonic() > deadline:
            return "max_duration"
        return policy.check(metrics, health_failures=state["health_failures"])

    try:
        for stage in build_schedule(config):
            interval = stage["spawn_interval_ms"] / 1000.0
            for _ in range(stage["new_users"]):
                vu = VirtualUser(spawned, emails[spawned], config, password, metrics, ai_gate, ca_file)
                tasks.append(asyncio.create_task(vu.run(stop)))
                spawned += 1
                await asyncio.sleep(interval)
                stop_reason = check()
                if stop_reason:
                    raise _HardStop
            remaining = stage["hold_seconds"] - config.stage_seconds
            if stage["steady"]:
                metrics.steady_start = time.time()
            end = time.monotonic() + max(0, remaining)
            while time.monotonic() < end:
                await asyncio.sleep(1)
                if stage["steady"]:
                    metrics.steady_active_min = (
                        metrics.signed_in if metrics.steady_active_min is None
                        else min(metrics.steady_active_min, metrics.signed_in)
                    )
                stop_reason = check()
                if stop_reason:
                    raise _HardStop
            if stage["steady"]:
                metrics.steady_end = time.time()
    except _HardStop:
        if metrics.steady_start and not metrics.steady_end:
            metrics.steady_end = time.time()
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    return metrics, stop_reason


def build_receipt(config: LoadConfig, metrics: Metrics, stop_reason: str | None, completed: float) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "run_id": config.run_id,
        "target_host": config.origin().host,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_at_epoch": round(metrics.started, 3),
        "completed_at_epoch": round(completed, 3),
        "config": {**asdict(config), "ramp": list(config.ramp)},
        "schedule": build_schedule(config),
        "steady_state": {
            "window_start_epoch": metrics.steady_start,
            "window_end_epoch": metrics.steady_end,
            "signed_in_vus_min": metrics.steady_active_min,
            "routes": {name: stats.summary() for name, stats in sorted(metrics.steady_routes.items())},
        },
        "routes": {name: stats.summary() for name, stats in sorted(metrics.routes.items())},
        "realtime": {"held_sockets_at_end": metrics.ws_connected, "socket_drops": metrics.ws_drops},
        "ai": {"rate_cap_per_second": config.ai_rps_max, "concurrency_cap": config.ai_concurrency_max,
               "observed_max_inflight": metrics.ai_inflight_max},
        "stop_reason": stop_reason,
        "verdict": evaluate_verdict(metrics, config, stop_reason),
        "fr09_boundary": (
            "Load-side evidence only. FR-09 FULL_MIXED acceptance also requires HMAC-signed "
            "server presence samples and DB accounting judged by fr09_evidence_gate.py."
        ),
        "production_mutation": "synthetic accounts only (conversations + capped AI messages)",
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


# --------------------------------------------------------------------------- CLI


def _config(args: argparse.Namespace) -> LoadConfig:
    return LoadConfig(
        target=args.target,
        run_id=args.run_id,
        ramp=tuple(int(x) for x in args.ramp.split(",") if x.strip()),
        stage_seconds=args.stage_seconds,
        steady_seconds=args.steady_seconds,
        think_ms=args.think_ms,
        ai_rps_max=args.ai_rps_max,
        ai_concurrency_max=args.ai_concurrency_max,
        ai_agent_id=args.ai_agent_id,
        conversations_per_vu=args.conversations_per_vu,
        hold_realtime_socket=not args.no_realtime_socket,
        request_timeout=args.request_timeout,
        max_duration_seconds=args.max_duration_seconds,
        allow_lab_target=args.allow_lab_target,
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("plan", "preflight", "run"), nargs="?", default="plan")
    p.add_argument("--target", default=f"https://{PRODUCTION_API_HOST}")
    p.add_argument("--run-id", required=True)
    p.add_argument("--accounts", type=Path, help="JSONL export from synthetic_load_accounts seed")
    p.add_argument("--password-file", type=Path)
    p.add_argument("--ramp", default=",".join(str(x) for x in DEFAULT_RAMP))
    p.add_argument("--stage-seconds", type=int, default=120)
    p.add_argument("--steady-seconds", type=int, default=900)
    p.add_argument("--think-ms", type=int, default=3000)
    p.add_argument("--ai-rps-max", type=float, default=0.2)
    p.add_argument("--ai-concurrency-max", type=int, default=4)
    p.add_argument("--ai-agent-id", default="")
    p.add_argument("--conversations-per-vu", type=int, default=1)
    p.add_argument("--no-realtime-socket", action="store_true")
    p.add_argument("--request-timeout", type=float, default=30.0)
    p.add_argument("--max-duration-seconds", type=int, default=3600)
    p.add_argument("--allow-lab-target", action="store_true")
    p.add_argument("--ca-file")
    p.add_argument("--stop-file", type=Path, help="touch this file to stop the run cleanly")
    p.add_argument("--execute", action="store_true", help="actually send load (run only)")
    p.add_argument("--confirm-target", default="", help="must repeat the target host for run")
    p.add_argument("--output", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = _config(args)
    problems = validate_config(config)
    plan = {"schema": SCHEMA + ".plan", "config": {**asdict(config), "ramp": list(config.ramp)},
            "schedule": build_schedule(config) if not problems else [], "estimate": estimate_load(config) if not problems else {},
            "workload": [asdict(a) for a in WORKLOAD], "stop_policy": asdict(StopPolicy()),
            "pass_criteria": {"steady_non_ai_p95_ms_lt": NON_AI_P95_MAX_MS, "error_rate_lt": ERROR_RATE_MAX,
                              "five_xx_storm": f">= max({STORM_MIN_5XX}, {STORM_RATIO:.0%}) 5xx in a {STORM_BUCKET_SECONDS}s bucket"},
            "problems": problems}
    if problems:
        print(json.dumps({**plan, "status": "REFUSED"}, indent=2))
        return 2
    if args.command == "plan" or (args.command == "run" and not args.execute):
        print(json.dumps({**plan, "status": "DRY_RUN", "network_requests_sent": 0}, indent=2))
        return 0
    if args.accounts is None or args.password_file is None:
        print(json.dumps({"status": "REFUSED", "problems": ["--accounts and --password-file are required"]}))
        return 2
    try:
        needed = 1 if args.command == "preflight" else config.max_vus
        emails = read_accounts(args.accounts, config.run_id, needed)
        password = read_password(args.password_file)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "REFUSED", "problems": [str(exc)]}))
        return 2
    if args.command == "preflight":
        return asyncio.run(_preflight(config, emails[0], password, args.ca_file))
    if args.confirm_target != config.origin().host:
        print(json.dumps({"status": "REFUSED", "problems": ["--confirm-target must equal the target host"]}))
        return 2
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = estimate_load(config)["open_files_needed"]
    if soft < want:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(hard, want), hard))
        except (ValueError, OSError):
            print(json.dumps({"status": "REFUSED", "problems": [f"ulimit -n {soft} < {want}; raise it first"]}))
            return 2
    metrics, stop_reason = asyncio.run(execute(config, emails, password, stop_file=args.stop_file, ca_file=args.ca_file))
    receipt = build_receipt(config, metrics, stop_reason, time.time())
    if args.output:
        write_receipt(args.output, receipt)
    print(json.dumps({"status": receipt["verdict"]["status"], "verdict": receipt["verdict"],
                      "receipt": str(args.output) if args.output else None}, indent=2))
    return 0 if receipt["verdict"]["status"] == "PASS" else 1


async def _preflight(config: LoadConfig, email: str, password: str, ca_file: str | None) -> int:
    metrics = Metrics()
    vu = VirtualUser(0, email, config, password, metrics, AiGate(0, 0, metrics), ca_file)
    results: dict[str, Any] = {}
    for path in ("/health", "/ready"):
        response = await vu.call(Action(path.strip("/"), 0), "GET", path)
        results[path] = response.status if response else "FAIL"
    results["login"] = "PASS" if await vu.login() else "FAIL"
    await vu.http.close()
    ok = results == {"/health": 200, "/ready": 200, "login": "PASS"}
    print(json.dumps({"status": "PREFLIGHT_PASS" if ok else "PREFLIGHT_FAIL", "results": results,
                      "network_requests_sent": sum(s.summary()["count"] for s in metrics.routes.values())}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
