#!/usr/bin/env python3
"""P6 gate 6.2: 72-hour continuous observation sampler + pass/fail certificate.

Builds on ``ns12_observer_v2.py`` (same public probes, same read-only NEW-host
container inventory, same create-only 0600 evidence discipline) and adds the
signals NS12 listed as ``not_measured``: continuous availability, origin 5xx
rate from the Nginx access log, and local + R2 backup freshness.

  sample   one read-only sample (run every 2 min from the systemd timer in
           docs/project/PRE-LAUNCH-RUNBOOK.md); writes P6-72H-<utc>.json
  certify  reads all samples of a run and writes the certificate; exit 0 only
           for PASS

Owner alerting stays on the existing server-side Telegram alerts (the AIONEX
AI gateway owner alerts); ``--notify-command`` can additionally pipe each
anomalous sample (JSON on stdin, no shell) to an existing notifier.
Never mutates services, configuration, credentials or customer data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_SAMPLE = "aionex.p6.observation-sample.v1"
SCHEMA_CERT = "aionex.p6.72h-certificate.v1"
NS12_PATH = Path(__file__).resolve().parent / "ns12_observer_v2.py"
DEFAULT_INTERVAL = 120
REQUIRED_HOURS = 72.0
AVAILABILITY_MIN = 0.999
ORIGIN_5XX_RATE_MAX = 0.01
SAMPLE_5XX_RATE_MAX = 0.05
BACKUP_MAX_AGE_HOURS = 26.0
NGINX_CONTAINER = "web-dashboard-nginx-1"
POSTGRES_CONTAINER = "web-dashboard-postgres-1"
_STATUS = re.compile(r'"\S+ \S+ HTTP/[0-9.]+" (\d{3}) ')
_RUN_ID = re.compile(r"p6-72h-[0-9]{8}t[0-9]{4}z\Z")


def load_ns12() -> Any:
    spec = importlib.util.spec_from_file_location("ns12_observer_v2", NS12_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def parse_nginx_statuses(log_text: str) -> dict[str, int]:
    """Count status classes in Nginx 'aionex' log lines (no URLs retained)."""
    counts = {"total": 0, "5xx": 0, "4xx": 0, "503": 0}
    for line in log_text.splitlines():
        match = _STATUS.search(line)
        if not match:
            continue
        code = int(match.group(1))
        counts["total"] += 1
        if code >= 500:
            counts["5xx"] += 1
        if code == 503:
            counts["503"] += 1
        elif 400 <= code < 500:
            counts["4xx"] += 1
    return counts


def _run(argv: list[str], timeout: int = 20) -> tuple[int | None, str]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, type(exc).__name__
    # stdout + stderr: docker logs writes the container's stdout/stderr to both.
    return completed.returncode, completed.stdout + completed.stderr


def origin_error_rate(since_seconds: int) -> dict[str, Any]:
    code, output = _run(["docker", "logs", "--since", f"{since_seconds}s", NGINX_CONTAINER], 30)
    if code != 0:
        return {"status": "UNAVAILABLE", "error_type": "DOCKER_LOGS_FAILED"}
    counts = parse_nginx_statuses(output)
    rate = counts["5xx"] / counts["total"] if counts["total"] else 0.0
    return {"status": "MEASURED", "window_seconds": since_seconds, **counts, "rate_5xx": round(rate, 6)}


BACKUP_SQL = (
    "select coalesce(extract(epoch from max(completed_at))::bigint, 0), "
    "coalesce(extract(epoch from max(offsite_completed_at) filter (where offsite_status = 'completed'))::bigint, 0) "
    "from backup_records where status = 'completed'"
)


def backup_freshness(now_epoch: float) -> dict[str, Any]:
    argv = ["docker", "exec", POSTGRES_CONTAINER, "sh", "-c",
            'psql -X -A -t -F " " -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "$0"', BACKUP_SQL]
    code, output = _run(argv, 20)
    if code != 0:
        return {"status": "UNAVAILABLE", "error_type": "BACKUP_QUERY_FAILED"}
    try:
        local_epoch, offsite_epoch = (int(x) for x in output.strip().split()[:2])
    except ValueError:
        return {"status": "UNAVAILABLE", "error_type": "BACKUP_QUERY_UNPARSEABLE"}

    def age(epoch: int) -> float | None:
        return round((now_epoch - epoch) / 3600, 3) if epoch else None

    return {"status": "MEASURED", "local_age_hours": age(local_epoch), "offsite_age_hours": age(offsite_epoch)}


def sample_anomalies(sample: dict[str, Any]) -> list[str]:
    anomalies = [f"http:{name}" for name, check in sample["http"].items() if check.get("status") != "EXPECTED"]
    containers = sample.get("containers") or {}
    if containers.get("status") != "MEASURED":
        anomalies.append("containers_unavailable")
    else:
        if containers.get("unhealthy") or containers.get("restarting"):
            anomalies.append("containers_unhealthy")
        if any(row.get("oom_killed") for row in containers.get("containers") or []):
            anomalies.append("container_oom")
    origin = sample.get("origin_errors") or {}
    if origin.get("status") != "MEASURED":
        anomalies.append("origin_errors_unavailable")
    elif origin.get("total", 0) >= 50 and origin.get("rate_5xx", 0) > SAMPLE_5XX_RATE_MAX:
        anomalies.append("origin_5xx_spike")
    backup = sample.get("backup") or {}
    if backup.get("status") != "MEASURED":
        anomalies.append("backup_unavailable")
    else:
        for key in ("local_age_hours", "offsite_age_hours"):
            value = backup.get(key)
            if value is None or value > BACKUP_MAX_AGE_HOURS:
                anomalies.append(f"backup_stale:{key}")
    return sorted(set(anomalies))


def take_sample(run_id: str, interval: int, ns12: Any | None = None) -> dict[str, Any]:
    ns12 = ns12 or load_ns12()
    started = now_utc()
    http = {}
    for name, (url, expected) in ns12.URLS.items():
        http[name] = _probe(ns12, url, expected)
        if http[name].get("status") != "EXPECTED":
            # One confirmation probe: a single dropped packet is recorded
            # (first_attempt) but only a confirmed failure counts as downtime.
            time.sleep(5)
            retry = _probe(ns12, url, expected)
            retry["first_attempt"] = {k: http[name].get(k) for k in ("status", "http_code", "curl_phase")}
            http[name] = retry
    host = ns12.host_probe()
    containers = (host.get("checks") or {}).get("containers") if host.get("status") == "MEASURED" else {"status": "UNAVAILABLE"}
    sample = {
        "schema": SCHEMA_SAMPLE,
        "run_id": run_id,
        "started_at_utc": started,
        "epoch": time.time(),
        "interval_seconds": interval,
        "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "ns12_collector_sha256": hashlib.sha256(NS12_PATH.read_bytes()).hexdigest(),
        "http": {name: {k: v.get(k) for k in ("status", "http_code", "curl_phase", "total_seconds", "first_attempt") if k in v}
                 for name, v in http.items()},
        "containers": _compact_containers(containers or {}),
        "origin_errors": origin_error_rate(interval),
        "backup": backup_freshness(time.time()),
        "production_mutation": False,
    }
    sample["anomalies"] = sample_anomalies(sample)
    return sample


def _probe(ns12: Any, url: str, expected: list[int]) -> dict[str, Any]:
    try:
        return ns12.http_probe(url, expected)
    except Exception as error:  # an exception is an unavailable probe, never healthy
        return {"status": "UNAVAILABLE", "error_type": type(error).__name__, "http_code": None}


def _compact_containers(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("status") != "MEASURED":
        return {"status": raw.get("status", "UNAVAILABLE")}
    return {
        "status": "MEASURED",
        **{k: raw.get(k) for k in ("total", "running", "unhealthy", "restarting", "restart_count_total")},
        "containers": [
            {k: row.get(k) for k in ("name", "state", "health", "restart_count", "oom_killed", "started_at_utc")}
            for row in raw.get("containers") or []
        ],
    }


def persist(path_dir: Path, payload: dict[str, Any], prefix: str) -> Path:
    path_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = path_dir / f"{prefix}-{stamp}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    return path


def certify(samples: list[dict[str, Any]], *, run_id: str, interval: int,
            required_hours: float = REQUIRED_HOURS) -> dict[str, Any]:
    """Pure certificate evaluation over the ordered samples of one run."""
    rows = sorted((s for s in samples if s.get("run_id") == run_id and s.get("schema") == SCHEMA_SAMPLE),
                  key=lambda s: s["epoch"])
    failed: list[str] = []
    if len(rows) < 2:
        return {"schema": SCHEMA_CERT, "run_id": run_id, "status": "FAIL",
                "failed_criteria": ["insufficient_samples"], "samples": len(rows)}
    span_hours = (rows[-1]["epoch"] - rows[0]["epoch"]) / 3600
    gaps = [b["epoch"] - a["epoch"] for a, b in zip(rows, rows[1:])]
    max_gap = max(gaps)
    if span_hours < required_hours:
        failed.append("continuous_72h_span")
    if max_gap > 2 * interval + 60:
        failed.append("no_sampling_gap_over_2_intervals")

    availability: dict[str, float] = {}
    for name in rows[0]["http"]:
        ok = sum(1 for row in rows if row["http"].get(name, {}).get("status") == "EXPECTED")
        availability[name] = round(ok / len(rows), 6)
        if availability[name] < AVAILABILITY_MIN:
            failed.append(f"availability:{name}")

    origin_rows = [row["origin_errors"] for row in rows if row.get("origin_errors", {}).get("status") == "MEASURED"]
    origin_total = sum(r["total"] for r in origin_rows)
    origin_5xx = sum(r["5xx"] for r in origin_rows)
    origin_rate = origin_5xx / origin_total if origin_total else None
    if len(origin_rows) < 0.99 * len(rows):
        failed.append("origin_error_rate_measured_99pct_of_samples")
    if origin_rate is None or origin_rate > ORIGIN_5XX_RATE_MAX:
        failed.append("origin_5xx_rate_le_1pct")

    measured = [row["containers"] for row in rows if row.get("containers", {}).get("status") == "MEASURED"]
    restart_delta = None
    if len(measured) < 0.99 * len(rows):
        failed.append("container_inventory_measured_99pct_of_samples")
    if measured:
        first = {c["name"]: (c["restart_count"], c.get("started_at_utc")) for c in measured[0]["containers"]}
        last = {c["name"]: (c["restart_count"], c.get("started_at_utc")) for c in measured[-1]["containers"]}
        restart_delta = sum(max(0, last[n][0] - first[n][0]) for n in last if n in first)
        recreated = sorted(n for n in last if n in first and last[n][1] != first[n][1])
        vanished = sorted(set(first) - set(last))
        if restart_delta:
            failed.append("container_restarts_zero")
        if recreated or vanished:
            failed.append("no_container_recreated_or_missing")
        if any(c.get("oom_killed") for m in measured for c in m["containers"]):
            failed.append("no_oom_kill")
        if any(m.get("unhealthy") for m in measured):
            failed.append("no_unhealthy_container")
    else:
        recreated, vanished = [], []

    backups = [row["backup"] for row in rows if row.get("backup", {}).get("status") == "MEASURED"]
    worst_local = max((b["local_age_hours"] if b["local_age_hours"] is not None else 1e9) for b in backups) if backups else None
    worst_offsite = max((b["offsite_age_hours"] if b["offsite_age_hours"] is not None else 1e9) for b in backups) if backups else None
    if len(backups) < 0.99 * len(rows) or worst_local is None or worst_local > BACKUP_MAX_AGE_HOURS:
        failed.append("local_backup_fresh_le_26h")
    if worst_offsite is None or worst_offsite > BACKUP_MAX_AGE_HOURS:
        failed.append("r2_backup_fresh_le_26h")

    return {
        "schema": SCHEMA_CERT,
        "run_id": run_id,
        "status": "PASS" if not failed else "FAIL",
        "failed_criteria": sorted(set(failed)),
        "samples": len(rows),
        "first_sample_utc": rows[0]["started_at_utc"],
        "last_sample_utc": rows[-1]["started_at_utc"],
        "span_hours": round(span_hours, 3),
        "max_gap_seconds": round(max_gap, 3),
        "availability": availability,
        "origin_5xx": {"requests": origin_total, "errors": origin_5xx,
                       "rate": round(origin_rate, 6) if origin_rate is not None else None},
        "container_restart_delta": restart_delta,
        "containers_recreated": recreated,
        "containers_missing": vanished,
        "worst_backup_age_hours": {"local": worst_local, "offsite": worst_offsite},
        "anomalous_samples": sum(1 for row in rows if row.get("anomalies")),
        "thresholds": {"availability_min": AVAILABILITY_MIN, "origin_5xx_rate_max": ORIGIN_5XX_RATE_MAX,
                       "backup_max_age_hours": BACKUP_MAX_AGE_HOURS, "required_hours": required_hours,
                       "max_gap_seconds": 2 * interval + 60},
    }


def load_samples(directory: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(directory.glob("P6-72H-*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("sample", "certify"))
    parser.add_argument("--run-id", required=True, help="p6-72h-YYYYMMDDtHHMMz")
    parser.add_argument("--dir", type=Path, required=True, help="evidence directory for this run")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--hours", type=float, default=REQUIRED_HOURS)
    parser.add_argument("--notify-command", default="", help="optional existing notifier; sample JSON on stdin")
    args = parser.parse_args(argv)
    if _RUN_ID.fullmatch(args.run_id) is None:
        print("REFUSED: run id must be p6-72h-YYYYMMDDtHHMMz", file=sys.stderr)
        return 2
    if not 60 <= args.interval <= 900:
        print("REFUSED: interval must be 60..900 seconds", file=sys.stderr)
        return 2
    if args.command == "sample":
        sample = take_sample(args.run_id, args.interval)
        path = persist(args.dir, sample, "P6-72H")
        if sample["anomalies"] and args.notify_command:
            subprocess.run(shlex.split(args.notify_command), input=json.dumps(
                {"run_id": args.run_id, "anomalies": sample["anomalies"], "sample": str(path)}),
                text=True, timeout=30, check=False)
        print(json.dumps({"sample": str(path), "anomalies": sample["anomalies"]}))
        return 0
    certificate = certify(load_samples(args.dir), run_id=args.run_id, interval=args.interval, required_hours=args.hours)
    path = persist(args.dir, certificate, "P6-72H-CERTIFICATE")
    print(json.dumps({"certificate": str(path), "status": certificate["status"],
                      "failed_criteria": certificate["failed_criteria"]}, indent=2))
    return 0 if certificate["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
