#!/usr/bin/env python3
"""FR-22 external monitoring state machine.

This module is intentionally dependency-free and safe to run off-host.  It
separates observation from delivery: it emits deterministic JSON events, but it
does not configure notification channels, restart services, mutate production,
or delete recovery evidence.

The coordinator owns off-host scheduling/delivery and deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import ssl
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


OUTAGE_CONDITIONS = frozenset(
    {"target_unreachable", "target_degraded", "heartbeat_stale"}
)


@dataclass(frozen=True, slots=True)
class WatchConfig:
    origin: str
    health_path: str = "/health"
    ready_path: str = "/ready"
    expected_status: int = 200
    request_timeout_seconds: float = 5.0
    stale_after_seconds: int = 900
    tls_warning_seconds: int = 30 * 24 * 3600
    tls_critical_seconds: int = 7 * 24 * 3600

    def normalized_origin(self) -> str:
        return validate_exact_https_origin(self.origin)


@dataclass(frozen=True, slots=True)
class Observation:
    observed_at: int
    health_status: int | None
    ready_status: int | None
    tls_not_after: int | None
    transport_error: str | None = None


@dataclass(frozen=True, slots=True)
class WatchState:
    first_observed_at: int | None = None
    last_observed_at: int | None = None
    last_success_at: int | None = None
    outage_started_at: int | None = None
    active_conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    severity: str
    observed_at: int
    origin: str
    fingerprint: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Evaluation:
    state: WatchState
    events: tuple[Event, ...]
    conditions: tuple[str, ...]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def validate_exact_https_origin(origin: str) -> str:
    """Return canonical HTTPS origin or raise ValueError.

    Exact-origin means: HTTPS only, no userinfo, no path other than '/', no
    query/fragment, and no implicit redirect following.
    """

    parsed = urlsplit(origin)
    if parsed.scheme.lower() != "https":
        raise ValueError("origin must use https")
    if not parsed.hostname:
        raise ValueError("origin must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("userinfo is forbidden in monitoring origin")
    if parsed.path not in ("", "/"):
        raise ValueError("origin must not contain a path")
    if parsed.query or parsed.fragment:
        raise ValueError("origin must not contain query or fragment")

    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid origin port") from exc

    if ":" in host and not host.startswith("["):
        rendered_host = f"[{host}]"
    else:
        rendered_host = host
    if port in (None, 443):
        return f"https://{rendered_host}"
    if port < 1 or port > 65535:
        raise ValueError("invalid origin port")
    return f"https://{rendered_host}:{port}"


def _join_origin_path(origin: str, path: str) -> str:
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("probe path must be an absolute single-origin path")
    return f"{validate_exact_https_origin(origin)}{path}"


def _condition_fingerprint(origin: str, kind: str) -> str:
    material = f"fr22-v1\n{validate_exact_https_origin(origin)}\n{kind}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _event(
    config: WatchConfig,
    *,
    kind: str,
    severity: str,
    observed_at: int,
    **details: Any,
) -> Event:
    return Event(
        kind=kind,
        severity=severity,
        observed_at=observed_at,
        origin=config.normalized_origin(),
        fingerprint=_condition_fingerprint(config.origin, kind),
        details=details,
    )


def _tls_condition(config: WatchConfig, observation: Observation) -> tuple[str, dict[str, Any]] | None:
    if observation.tls_not_after is None:
        return None
    remaining = observation.tls_not_after - observation.observed_at
    details = {
        "not_after": observation.tls_not_after,
        "remaining_seconds": remaining,
    }
    if remaining <= config.tls_critical_seconds:
        return "tls_expiry_critical", details
    if remaining <= config.tls_warning_seconds:
        return "tls_expiry_warning", details
    return None


def evaluate(
    config: WatchConfig,
    previous: WatchState,
    observation: Observation,
) -> Evaluation:
    """Evaluate one observation and emit only state transitions.

    The scheduler cadence is never treated as proof of an SLA.  Staleness is
    derived from observation timestamps and last confirmed healthy readiness.
    """

    if observation.observed_at < 0:
        raise ValueError("observed_at must be non-negative")
    if previous.last_observed_at is not None and observation.observed_at < previous.last_observed_at:
        raise ValueError("observation time moved backwards")

    first_observed_at = (
        previous.first_observed_at
        if previous.first_observed_at is not None
        else observation.observed_at
    )

    transport_ok = observation.transport_error is None
    health_ok = transport_ok and observation.health_status == config.expected_status
    ready_ok = transport_ok and observation.ready_status == config.expected_status
    fully_healthy = health_ok and ready_ok

    last_success_at = observation.observed_at if fully_healthy else previous.last_success_at
    conditions: set[str] = set()

    if not transport_ok or observation.health_status is None:
        conditions.add("target_unreachable")
    elif not health_ok or not ready_ok:
        conditions.add("target_degraded")

    heartbeat_reference = (
        last_success_at if last_success_at is not None else first_observed_at
    )
    heartbeat_age = observation.observed_at - heartbeat_reference
    if heartbeat_age > config.stale_after_seconds:
        conditions.add("heartbeat_stale")

    tls = _tls_condition(config, observation)
    tls_details: dict[str, Any] = {}
    if tls is not None:
        tls_kind, tls_details = tls
        conditions.add(tls_kind)

    prior = set(previous.active_conditions)
    opened = sorted(conditions - prior)
    cleared = sorted(prior - conditions)

    prior_outage = bool(prior & OUTAGE_CONDITIONS)
    current_outage = bool(conditions & OUTAGE_CONDITIONS)
    outage_started_at = previous.outage_started_at
    if current_outage and not prior_outage:
        outage_started_at = observation.observed_at
    elif not current_outage:
        outage_started_at = None

    events: list[Event] = []
    for kind in opened:
        if kind == "target_unreachable":
            events.append(
                _event(
                    config,
                    kind=kind,
                    severity="critical",
                    observed_at=observation.observed_at,
                    transport_error=observation.transport_error,
                    health_status=observation.health_status,
                    ready_status=observation.ready_status,
                )
            )
        elif kind == "target_degraded":
            events.append(
                _event(
                    config,
                    kind=kind,
                    severity="warning",
                    observed_at=observation.observed_at,
                    health_status=observation.health_status,
                    ready_status=observation.ready_status,
                )
            )
        elif kind == "heartbeat_stale":
            events.append(
                _event(
                    config,
                    kind=kind,
                    severity="critical",
                    observed_at=observation.observed_at,
                    heartbeat_age_seconds=heartbeat_age,
                    stale_after_seconds=config.stale_after_seconds,
                    last_success_at=last_success_at,
                )
            )
        elif kind == "tls_expiry_critical":
            events.append(
                _event(
                    config,
                    kind=kind,
                    severity="critical",
                    observed_at=observation.observed_at,
                    **tls_details,
                )
            )
        elif kind == "tls_expiry_warning":
            events.append(
                _event(
                    config,
                    kind=kind,
                    severity="warning",
                    observed_at=observation.observed_at,
                    **tls_details,
                )
            )

    if prior_outage and not current_outage:
        started = previous.outage_started_at
        duration = (
            observation.observed_at - started if started is not None else None
        )
        events.append(
            _event(
                config,
                kind="target_recovered",
                severity="info",
                observed_at=observation.observed_at,
                outage_duration_seconds=duration,
                cleared_conditions=sorted(c for c in cleared if c in OUTAGE_CONDITIONS),
            )
        )

    if "tls_expiry_critical" in cleared or "tls_expiry_warning" in cleared:
        if not (conditions & {"tls_expiry_critical", "tls_expiry_warning"}):
            events.append(
                _event(
                    config,
                    kind="tls_expiry_recovered",
                    severity="info",
                    observed_at=observation.observed_at,
                    tls_not_after=observation.tls_not_after,
                )
            )

    state = WatchState(
        first_observed_at=first_observed_at,
        last_observed_at=observation.observed_at,
        last_success_at=last_success_at,
        outage_started_at=outage_started_at,
        active_conditions=tuple(sorted(conditions)),
    )
    return Evaluation(state=state, events=tuple(events), conditions=state.active_conditions)


def load_state(path: str | Path) -> WatchState:
    target = Path(path)
    if not target.exists():
        return WatchState()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema") != 1:
        raise ValueError("unsupported FR22 watch-state schema")
    return WatchState(
        first_observed_at=payload.get("first_observed_at"),
        last_observed_at=payload.get("last_observed_at"),
        last_success_at=payload.get("last_success_at"),
        outage_started_at=payload.get("outage_started_at"),
        active_conditions=tuple(payload.get("active_conditions", ())),
    )


def save_state_atomic(path: str | Path, state: WatchState) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, **asdict(state)}
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _http_status(url: str, *, timeout_seconds: float) -> tuple[int | None, str | None]:
    opener = build_opener(_NoRedirect)
    request = Request(url, method="GET", headers={"User-Agent": "AIONEX-FR22/1"})
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if final_url != url:
                return None, "redirect_refused"
            return int(response.status), None
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            return None, f"redirect_refused:{exc.code}"
        return int(exc.code), None
    except (URLError, TimeoutError, OSError) as exc:
        return None, f"transport:{type(exc).__name__}"


def _tls_not_after(origin: str, *, timeout_seconds: float) -> tuple[int | None, str | None]:
    parsed = urlsplit(validate_exact_https_origin(origin))
    assert parsed.hostname is not None
    host = parsed.hostname
    port = parsed.port or 443
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
        not_after = cert.get("notAfter")
        if not not_after:
            return None, "tls:no_not_after"
        return int(ssl.cert_time_to_seconds(not_after)), None
    except (ssl.SSLError, OSError, ValueError) as exc:
        return None, f"tls:{type(exc).__name__}"


def collect_observation(config: WatchConfig, *, observed_at: int | None = None) -> Observation:
    origin = config.normalized_origin()
    health_status, health_error = _http_status(
        _join_origin_path(origin, config.health_path),
        timeout_seconds=config.request_timeout_seconds,
    )
    ready_status, ready_error = _http_status(
        _join_origin_path(origin, config.ready_path),
        timeout_seconds=config.request_timeout_seconds,
    )
    tls_not_after, tls_error = _tls_not_after(
        origin, timeout_seconds=config.request_timeout_seconds
    )
    error = health_error or ready_error or tls_error
    return Observation(
        observed_at=int(time.time()) if observed_at is None else int(observed_at),
        health_status=health_status,
        ready_status=ready_status,
        tls_not_after=tls_not_after,
        transport_error=error,
    )


def _event_payload(event: Event) -> dict[str, Any]:
    return asdict(event)


def _parse_observation(path: str | Path) -> Observation:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Observation(
        observed_at=int(payload["observed_at"]),
        health_status=payload.get("health_status"),
        ready_status=payload.get("ready_status"),
        tls_not_after=payload.get("tls_not_after"),
        transport_error=payload.get("transport_error"),
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIONEX FR-22 off-host watch state machine")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--observation-json")
    parser.add_argument("--stale-after-seconds", type=int, default=900)
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = WatchConfig(
        origin=args.origin,
        stale_after_seconds=args.stale_after_seconds,
    )
    previous = load_state(args.state)
    observation = (
        _parse_observation(args.observation_json)
        if args.observation_json
        else collect_observation(config)
    )
    result = evaluate(config, previous, observation)
    save_state_atomic(args.state, result.state)
    print(
        json.dumps(
            {
                "schema": 1,
                "origin": config.normalized_origin(),
                "conditions": list(result.conditions),
                "events": [_event_payload(event) for event in result.events],
                "state": asdict(result.state),
                "scheduler_sla_claimed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
