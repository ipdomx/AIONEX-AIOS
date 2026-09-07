#!/usr/bin/env python3
"""AIONEX host capacity guard.

Runs root-side from the existing production runtime-watch systemd timer. It reads
only host kernel/filesystem counters and sends sanitized threshold transitions to
the existing durable Owner notification bridge inside an application container.
No Docker socket is mounted into application containers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

STATE_VERSION = 1
_SAFE_PROJECT = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SAFE_INTERFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")
_NOTIFIER_SERVICES = ("operations-observer", "communication-worker", "backend")

# Thresholds are deliberately conservative and are tied to the 2026-09-07
# production capacity acceptance on the current 12-thread / 1-Gbps host.
THRESHOLDS: dict[str, tuple[float, float]] = {
    "cpu_pct": (70.0, 85.0),
    "memory_pct": (75.0, 85.0),
    "disk_pct": (70.0, 85.0),
    "load_pct": (75.0, 100.0),
    "network_pct": (65.0, 80.0),
    "swap_pct": (20.0, 50.0),
}
WARNING_STREAK = 3
CRITICAL_STREAK = 2
RECOVERY_STREAK = 3


def _run(args: list[str]) -> str:
    result = subprocess.run(
        args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    return result.stdout


def _read_cpu() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
    if not fields or fields[0] != "cpu" or len(fields) < 5:
        raise RuntimeError("invalid /proc/stat cpu row")
    values = [int(value) for value in fields[1:]]
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def _memory_metrics() -> tuple[float, float]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            values[key] = int(rest.strip().split()[0])
    mem_total = max(1, values.get("MemTotal", 0))
    mem_available = max(0, values.get("MemAvailable", 0))
    memory_pct = max(0.0, min(100.0, (mem_total - mem_available) * 100.0 / mem_total))
    swap_total = max(0, values.get("SwapTotal", 0))
    swap_free = max(0, values.get("SwapFree", 0))
    swap_pct = 0.0 if swap_total <= 0 else max(0.0, min(100.0, (swap_total - swap_free) * 100.0 / swap_total))
    return memory_pct, swap_pct


def _network_counters(interface: str) -> tuple[int, int, int]:
    base = Path("/sys/class/net") / interface
    rx = int((base / "statistics/rx_bytes").read_text(encoding="utf-8").strip())
    tx = int((base / "statistics/tx_bytes").read_text(encoding="utf-8").strip())
    try:
        speed_mbps = int((base / "speed").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        speed_mbps = 1000
    if speed_mbps <= 0:
        speed_mbps = 1000
    return rx, tx, speed_mbps


def collect_metrics(previous_sample: dict[str, Any] | None, *, interface: str) -> tuple[dict[str, float], dict[str, Any]]:
    now = time.time()
    cpu_total, cpu_idle = _read_cpu()
    memory_pct, swap_pct = _memory_metrics()
    disk = shutil.disk_usage("/")
    disk_pct = 0.0 if disk.total <= 0 else disk.used * 100.0 / disk.total
    logical_cpus = max(1, int(os.cpu_count() or 1))
    load_pct = max(0.0, os.getloadavg()[0] * 100.0 / logical_cpus)
    rx, tx, speed_mbps = _network_counters(interface)

    cpu_pct = 0.0
    network_pct = 0.0
    if previous_sample:
        old_total = int(previous_sample.get("cpu_total", cpu_total))
        old_idle = int(previous_sample.get("cpu_idle", cpu_idle))
        delta_total = cpu_total - old_total
        delta_idle = cpu_idle - old_idle
        if delta_total > 0:
            cpu_pct = max(0.0, min(100.0, (delta_total - max(0, delta_idle)) * 100.0 / delta_total))
        elapsed = now - float(previous_sample.get("timestamp", now))
        if elapsed > 0:
            rx_delta = max(0, rx - int(previous_sample.get("rx_bytes", rx)))
            tx_delta = max(0, tx - int(previous_sample.get("tx_bytes", tx)))
            peak_direction_bps = max(rx_delta, tx_delta) * 8.0 / elapsed
            link_bps = float(speed_mbps) * 1_000_000.0
            network_pct = max(0.0, min(100.0, peak_direction_bps * 100.0 / link_bps))

    metrics = {
        "cpu_pct": round(cpu_pct, 2),
        "memory_pct": round(memory_pct, 2),
        "disk_pct": round(disk_pct, 2),
        "load_pct": round(load_pct, 2),
        "network_pct": round(network_pct, 2),
        "swap_pct": round(swap_pct, 2),
    }
    sample = {
        "timestamp": now,
        "cpu_total": cpu_total,
        "cpu_idle": cpu_idle,
        "rx_bytes": rx,
        "tx_bytes": tx,
        "interface": interface,
        "link_speed_mbps": speed_mbps,
    }
    return metrics, sample


def classify(metric: str, value: float) -> str:
    warning, critical = THRESHOLDS[metric]
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "healthy"


def reconcile_capacity(previous: dict[str, Any], metrics: dict[str, float]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prior_rows = dict(previous.get("metrics") or {})
    next_rows: dict[str, Any] = {}
    events: list[dict[str, Any]] = []

    for metric in sorted(THRESHOLDS):
        value = float(metrics.get(metric, 0.0))
        warning_threshold, critical_threshold = THRESHOLDS[metric]
        level = classify(metric, value)
        prior = dict(prior_rows.get(metric) or {})
        alerted = str(prior.get("alerted_level") or "healthy")
        transition = max(0, int(prior.get("transition", 0) or 0))
        warning_streak = max(0, int(prior.get("warning_streak", 0) or 0))
        critical_streak = max(0, int(prior.get("critical_streak", 0) or 0))
        healthy_streak = max(0, int(prior.get("healthy_streak", 0) or 0))

        event: str | None = None
        threshold = warning_threshold
        if level == "critical":
            warning_streak += 1
            critical_streak += 1
            healthy_streak = 0
            if critical_streak >= CRITICAL_STREAK and alerted != "critical":
                event = "capacity_critical"
                threshold = critical_threshold
                alerted = "critical"
        elif level == "warning":
            warning_streak += 1
            critical_streak = 0
            healthy_streak = 0
            if warning_streak >= WARNING_STREAK and alerted == "healthy":
                event = "capacity_warning"
                threshold = warning_threshold
                alerted = "warning"
        else:
            warning_streak = 0
            critical_streak = 0
            healthy_streak += 1
            if healthy_streak >= RECOVERY_STREAK and alerted != "healthy":
                event = "capacity_recovered"
                threshold = warning_threshold
                alerted = "healthy"

        if event:
            transition += 1
            events.append(
                {
                    "event": event,
                    "metric": metric,
                    "value": round(value, 2),
                    "threshold": round(threshold, 2),
                    "transition": transition,
                }
            )

        next_rows[metric] = {
            "value": round(value, 2),
            "level": level,
            "alerted_level": alerted,
            "warning_streak": warning_streak,
            "critical_streak": critical_streak,
            "healthy_streak": healthy_streak,
            "transition": transition,
        }

    return {"version": STATE_VERSION, "metrics": next_rows}, events


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": STATE_VERSION, "metrics": {}, "sample": {}}
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        return {"version": STATE_VERSION, "metrics": {}, "sample": {}}
    if not isinstance(payload.get("metrics"), dict):
        payload["metrics"] = {}
    if not isinstance(payload.get("sample"), dict):
        payload["sample"] = {}
    return payload


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _notifier_container(project: str) -> str | None:
    for service in _NOTIFIER_SERVICES:
        ids = [
            line.strip()
            for line in _run([
                "docker", "ps", "-q",
                "--filter", f"label=com.docker.compose.project={project}",
                "--filter", f"label=com.docker.compose.service={service}",
            ]).splitlines()
            if line.strip()
        ]
        if ids:
            return ids[0]
    return None


def notify_capacity(*, project: str, event: dict[str, Any]) -> bool:
    container_id = _notifier_container(project)
    if not container_id:
        return False
    result = subprocess.run(
        [
            "docker", "exec", "-u", "1000:1000", container_id,
            "python", "-m", "app.services.runtime_host_alert",
            "--event", str(event["event"]),
            "--service", "production-host",
            "--transition", str(int(event["transition"])),
            "--restart-count", "0",
            "--metric", str(event["metric"]),
            "--value", str(float(event["value"])),
            "--threshold", str(float(event["threshold"])),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="web-dashboard")
    parser.add_argument("--state-file", default="/var/lib/aionex-runtime-watch/capacity-state.json")
    parser.add_argument("--interface", default="wan0")
    args = parser.parse_args()
    if not _SAFE_PROJECT.fullmatch(args.project):
        raise SystemExit("invalid compose project")
    if not _SAFE_INTERFACE.fullmatch(args.interface):
        raise SystemExit("invalid network interface")

    state_path = Path(args.state_file)
    previous = _load_state(state_path)
    metrics, sample = collect_metrics(previous.get("sample") or None, interface=args.interface)
    planned, events = reconcile_capacity(previous, metrics)
    planned["sample"] = sample

    failed_metrics: set[str] = set()
    for event in events:
        if not notify_capacity(project=args.project, event=event):
            failed_metrics.add(str(event["metric"]))

    if failed_metrics:
        prior_rows = previous.get("metrics") or {}
        for metric in failed_metrics:
            if metric in prior_rows:
                planned["metrics"][metric] = prior_rows[metric]
    _write_state(state_path, planned)
    return 1 if failed_metrics else 0


if __name__ == "__main__":
    raise SystemExit(main())
