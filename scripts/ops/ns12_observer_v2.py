"""Bounded, read-only NS12 snapshot collector with fail-closed DNS/pre-connect diagnostics. Never a release-acceptance gate.

Reads public status codes and approved NEW-host container/host metadata only.
Writes a NEW observation file on NEW production locally; no OLD host or SSH. No service, deployment,
credential, configuration, checkpoint, source or customer-data modifications.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

EVIDENCE = Path(__file__).resolve().parent / "observations"
OWNER_IMAGE = "sha256:2d3b78eb79fe64520849536dd34c61be121b12923b6603abffd858ee62d7fb9e"
LOCAL_PROBE = ["/usr/bin/python3", "-B", "-"]
DNS_SLOW_CORRELATION_SECONDS = 2.0
DNS_SLOW_SIBLING_MINIMUM = 2
URLS = {
    "api_health": ("https://api.vip-e.net/health", [200]),
    "api_ready": ("https://api.vip-e.net/ready", [200]),
    "public": ("https://vip-e.net/", [200]),
    "owner_access_boundary": ("https://gabarot.vip-e.net/", [302]),
    **{f"vip_{locale}": (f"https://ai.vip-e.net/{locale}/", [200])
       for locale in ("ar", "de", "en", "es", "fr", "tr")},
}

# The remote script emits selected non-secret metadata, never env/settings,
# Docker raw inspection, container logs, file contents or customer payloads.
REMOTE = r'''
import datetime, json, os, pathlib, socket, subprocess

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def command(argv, timeout=6):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return {"status": "MEASURED" if p.returncode == 0 else "UNAVAILABLE", "exit_code": p.returncode,
                "value": p.stdout.strip() if p.returncode == 0 else None}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "UNAVAILABLE", "error_type": type(e).__name__, "value": None}

result = {"observed_at_utc": now(), "hostname": socket.gethostname(), "checks": {}}
if result["hostname"] != "nc-ph-4354":
    print(json.dumps(result))
    raise SystemExit(3)
checks = result["checks"]
ids = command(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=web-dashboard"])
if ids["status"] != "MEASURED":
    checks["containers"] = ids
elif not ids["value"]:
    checks["containers"] = {"status": "MEASURED", "value": "", "exit_code": 0}
else:
    fmt = "{{.Id}}\t{{.Name}}\t{{.Image}}\t{{.State.Status}}\t{{.RestartCount}}\t{{.State.OOMKilled}}\t{{with (index .State \"Health\")}}{{.Status}}{{else}}none{{end}}\t{{.State.StartedAt}}\t{{.State.ExitCode}}\t{{.HostConfig.RestartPolicy.Name}}"
    checks["containers"] = command(["docker", "inspect", "--format", fmt] + ids["value"].split(), 8)
checks["owner_next_version"] = command(["docker", "exec", "web-dashboard-frontend-1", "node", "-p", "require('next/package.json').version"])
checks["owner_rollback_image"] = command(["docker", "image", "inspect", "web-dashboard-frontend:rollback-pre-next15527-20261008", "--format", "{{.Id}}"])
try:
    memory = {}
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            memory[key + "_bytes"] = int(value.strip().split()[0]) * 1024
    filesystems = []
    for path in ("/", "/var/lib/docker", "/var/lib/aionex-migration"):
        st = os.statvfs(path)
        filesystems.append({"path": path, "total_bytes": st.f_blocks * st.f_frsize,
                            "available_bytes": st.f_bavail * st.f_frsize,
                            "total_inodes": st.f_files, "free_inodes": st.f_favail})
    checks["resources"] = {"status": "MEASURED", "value": {"memory": memory,
        "load": list(os.getloadavg()), "cpus": os.cpu_count(), "filesystems": filesystems}}
except (OSError, ValueError) as e:
    checks["resources"] = {"status": "UNAVAILABLE", "error_type": type(e).__name__, "value": None}
try:
    raids = []
    for md in sorted(pathlib.Path("/sys/block").glob("md*")):
        fields = {}
        for name in ("level", "array_state", "degraded", "sync_action", "mismatch_cnt"):
            p = md / "md" / name
            fields[name] = p.read_text().strip() if p.is_file() else None
        raids.append({"device": md.name, **fields})
    checks["raid"] = {"status": "MEASURED", "value": raids}
except OSError as e:
    checks["raid"] = {"status": "UNAVAILABLE", "error_type": type(e).__name__, "value": None}
print(json.dumps(result))
'''


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def invoke(argv: list[str], timeout: int, input_text: str | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        p = subprocess.run(argv, input=input_text, text=True, capture_output=True,
                           check=False, timeout=timeout)
        # Preserve curl's write-out metrics on non-zero exits. Raw stderr is never
        # persisted; only a bounded error class and phase timings enter evidence.
        return {"exit_code": p.returncode, "stdout": p.stdout,
                "seconds": round(time.monotonic() - started, 3),
                "error_type": None if p.returncode == 0 else "PROCESS_EXIT"}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"exit_code": None, "stdout": "", "seconds": round(time.monotonic() - started, 3),
                "error_type": type(e).__name__}


def _nonnegative_finite(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("Invalid curl timing")
    return parsed


def _curl_phase(exit_code: int | None, timings: dict[str, float | None]) -> str:
    if exit_code == 0:
        return "COMPLETE"
    if exit_code in (5, 6):
        return "DNS_FAILURE"
    if exit_code == 7:
        return "TCP_CONNECT_FAILURE"
    if exit_code in (35, 60):
        return "TLS_FAILURE"
    if exit_code == 28:
        if not timings.get("dns_seconds"):
            return "DNS_OR_PRE_CONNECT_TIMEOUT"
        if not timings.get("tcp_seconds"):
            return "TCP_CONNECT_TIMEOUT"
        if not timings.get("tls_seconds"):
            return "TLS_HANDSHAKE_TIMEOUT"
        if not timings.get("ttfb_seconds"):
            return "ORIGIN_FIRST_BYTE_TIMEOUT"
        return "TRANSFER_TIMEOUT"
    if exit_code == 56:
        return "RECEIVE_FAILURE"
    return "PROCESS_EXIT"


def decode_http(probe: dict[str, Any], expected: list[int]) -> dict[str, Any]:
    base = {"observed_at_utc": now_utc(), "expected_codes": expected,
            "redirects_followed": False, "authenticated_journey": False,
            "probe_seconds": probe.get("seconds")}
    code = None
    timings: dict[str, float | None] = {
        "dns_seconds": None, "tcp_seconds": None, "tls_seconds": None,
        "ttfb_seconds": None, "total_seconds": None,
    }
    try:
        fields = probe.get("stdout", "").strip().split("|")
        if len(fields) != 6:
            raise ValueError("Invalid curl field count")
        code = int(fields[0])
        for key, value in zip(timings, fields[1:]):
            timings[key] = _nonnegative_finite(value)
    except (TypeError, ValueError):
        if not probe.get("error_type") and probe.get("exit_code") == 0:
            return {**base, **timings, "status": "UNAVAILABLE", "http_code": None,
                    "error_type": "INVALID_OUTPUT", "curl_phase": "INVALID_OUTPUT"}
    phase = _curl_phase(probe.get("exit_code"), timings)
    if probe.get("error_type") or probe.get("exit_code") != 0:
        return {**base, **timings, "status": "UNAVAILABLE", "http_code": None,
                "error_type": probe.get("error_type"), "exit_code": probe.get("exit_code"),
                "curl_phase": phase}
    if code is None or not 100 <= code <= 599:
        return {**base, **timings, "status": "UNAVAILABLE", "http_code": None,
                "error_type": "INVALID_OUTPUT", "curl_phase": "INVALID_OUTPUT"}
    return {**base, **timings, "status": "EXPECTED" if code in expected else "UNEXPECTED",
            "http_code": code, "seconds": timings["total_seconds"], "curl_phase": phase}


def http_probe(url: str, expected: list[int]) -> dict[str, Any]:
    # No -L: a login-page 200 must not hide the original Access boundary.
    # Delimited phase timings remain available even when curl exits non-zero.
    write_out = ("%{http_code}|%{time_namelookup}|%{time_connect}|"
                 "%{time_appconnect}|%{time_starttransfer}|%{time_total}")
    p = invoke(["curl", "--silent", "--show-error", "--output", "/dev/null",
                "--proto", "=https", "--connect-timeout", "3", "--max-time", "6",
                "--write-out", write_out, url], 8)
    return decode_http(p, expected)


def cross_target_dns_stall_correlation(http: dict[str, Any]) -> dict[str, Any]:
    """Infer bounded cross-target DNS-path correlation from one primary sample.

    This is diagnostic metadata only: it performs no retry or extra probe,
    changes no primary HTTP result, and never establishes root cause.
    """
    timed_out = sorted(
        name for name, check in http.items()
        if name in URLS and check.get("curl_phase") == "DNS_OR_PRE_CONNECT_TIMEOUT"
    )
    slow_successes = []
    for name, check in sorted(http.items()):
        if name not in URLS or check.get("status") != "EXPECTED":
            continue
        dns_seconds = check.get("dns_seconds")
        if (isinstance(dns_seconds, (int, float))
                and not isinstance(dns_seconds, bool)
                and math.isfinite(dns_seconds)
                and dns_seconds >= DNS_SLOW_CORRELATION_SECONDS):
            slow_successes.append({
                "endpoint": name,
                "dns_seconds": dns_seconds,
            })

    correlated = bool(timed_out) and len(slow_successes) >= DNS_SLOW_SIBLING_MINIMUM
    return {
        "status": "CORRELATED" if correlated else "NOT_CORRELATED",
        "timed_out_endpoints": timed_out,
        "slow_successful_endpoints": slow_successes,
        "dns_slow_threshold_seconds": DNS_SLOW_CORRELATION_SECONDS,
        "minimum_slow_successful_siblings": DNS_SLOW_SIBLING_MINIMUM,
        "same_primary_sample_only": True,
        "inference_only": True,
        "cause_established": False,
        "changes_primary_result": False,
        "interpretation": (
            "A correlation means the same primary sample contained a DNS/pre-connect timeout "
            "and at least two other successful endpoints with slow DNS lookup. It does not "
            "identify root cause or certify availability."
        ),
    }


def dns_preconnect_diagnostic(http: dict[str, Any]) -> dict[str, Any]:
    """Capture bounded post-anomaly resolver and DNS-bypass evidence.

    This never changes the primary HTTP result, retries the acceptance sample, or
    upgrades an unavailable endpoint to healthy. It runs only after a
    DNS_OR_PRE_CONNECT_TIMEOUT and records a separate diagnostic section.
    """
    failed = [
        name for name, check in http.items()
        if name in URLS and check.get("curl_phase") == "DNS_OR_PRE_CONNECT_TIMEOUT"
    ]
    if not failed:
        return {
            "status": "NOT_TRIGGERED",
            "triggered_by": [],
            "post_anomaly_only": True,
            "changes_primary_result": False,
        }

    resolver_path = Path("/etc/resolv.conf")
    resolver_sha256 = None
    resolver_nameserver_count = None
    try:
        resolver_bytes = resolver_path.read_bytes()
        resolver_sha256 = hashlib.sha256(resolver_bytes).hexdigest()
        resolver_nameserver_count = sum(
            1 for line in resolver_bytes.decode(errors="replace").splitlines()
            if line.strip().startswith("nameserver ")
        )
    except OSError:
        pass

    first_by_host: dict[str, str] = {}
    for name in failed:
        host = urllib.parse.urlsplit(URLS[name][0]).hostname
        if host and host not in first_by_host:
            first_by_host[host] = name

    def diagnose(item: tuple[str, str]) -> tuple[str, dict[str, Any]]:
        host, name = item
        url, expected = URLS[name]
        query = invoke(["getent", "ahostsv4", host], 4)
        addresses: list[str] = []
        if query.get("exit_code") == 0 and not query.get("error_type"):
            for line in query.get("stdout", "").splitlines():
                token = [REDACTED] if line.split() else ""
                try:
                    parsed_ip = ipaddress.ip_address(token)
                except ValueError:
                    continue
                if parsed_ip.version == 4 and token not in addresses:
                    addresses.append(token)
        result: dict[str, Any] = {
            "trigger_endpoint": name,
            "resolver": {
                "status": "RESOLVED" if addresses else "UNAVAILABLE",
                "seconds": query.get("seconds"),
                "address_count": len(addresses),
                "exit_code": query.get("exit_code"),
                "error_type": query.get("error_type"),
            },
            "dns_bypass_https": {
                "status": "NOT_RUN",
                "reason": "resolver_returned_no_ipv4",
            },
        }
        if addresses:
            write_out = ("%{http_code}|%{time_namelookup}|%{time_connect}|"
                         "%{time_appconnect}|%{time_starttransfer}|%{time_total}")
            bypass_probe = invoke([
                "curl", "--silent", "--show-error", "--output", "/dev/null",
                "--proto", "=https", "--connect-timeout", "3", "--max-time", "6",
                "--resolve", f"{host}:443:{addresses[0]}",
                "--write-out", write_out, url,
            ], 8)
            bypass = decode_http(bypass_probe, expected)
            bypass["selected_ipv4"] = addresses[0]
            result["dns_bypass_https"] = bypass
        return host, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(first_by_host))) as executor:
        host_results = dict(executor.map(diagnose, first_by_host.items()))

    return {
        "status": "CAPTURED",
        "observed_at_utc": now_utc(),
        "triggered_by": failed,
        "post_anomaly_only": True,
        "changes_primary_result": False,
        "resolver_config_sha256": resolver_sha256,
        "resolver_nameserver_count": resolver_nameserver_count,
        "hosts": host_results,
        "interpretation": (
            "A successful bypass only separates the immediate DNS path from HTTPS reachability; "
            "it does not erase the primary timeout or certify continuous availability."
        ),
    }


def parse_containers(raw: dict[str, Any]) -> dict[str, Any]:
    unavailable = {"status": "UNAVAILABLE", "running": None, "total": None, "containers": None}
    if raw.get("status") != "MEASURED" or not isinstance(raw.get("value"), str):
        return {**unavailable, "error_type": raw.get("error_type", "INVENTORY_UNAVAILABLE")}
    rows = []
    try:
        for line in raw["value"].splitlines():
            fields = line.split("\t")
            if len(fields) != 10:
                raise ValueError("Invalid inventory")
            ident, name, image, state, restarts, oom, health, started, exit_code, restart_policy = fields
            if not name.startswith("/web-dashboard-") or int(restarts) < 0 or oom not in ("true", "false"):
                raise ValueError("Unexpected inventory field")
            rows.append({"id": ident, "name": name.lstrip("/"), "image": image,
                         "state": state, "restart_count": int(restarts), "oom_killed": oom == "true",
                         "health": None if health == "none" else health, "started_at_utc": started,
                         "exit_code": int(exit_code), "restart_policy": restart_policy})
    except (TypeError, ValueError):
        return {**unavailable, "error_type": "INVALID_OUTPUT"}
    initializer_names = {
        "web-dashboard-postgres-credential-reconciler-1", "web-dashboard-realtime-recording-init-1",
        "web-dashboard-ollama-model-bootstrap-1", "web-dashboard-security-tool-cache-init-1",
        "web-dashboard-backup-asset-root-init-1",
    }
    # Names were observed with exit=0/restart=no; never exclude a failed/running initializer.
    completed = [r for r in rows if r["name"] in initializer_names and r["state"] == "exited"
                 and r["exit_code"] == 0 and r["restart_policy"] == "no" and not r["oom_killed"]]
    all_count = len(rows)
    rows = [r for r in rows if r not in completed]
    return {"status": "MEASURED", "total": len(rows), "all_project_container_count": all_count,
            "completed_initializers": completed,
            "running": sum(r["state"] == "running" for r in rows),
            "unhealthy": sum(r["health"] == "unhealthy" for r in rows),
            "restarting": sum(r["state"] == "restarting" for r in rows),
            "restart_count_total": sum(r["restart_count"] for r in rows),
            "without_healthcheck": sum(r["health"] is None for r in rows), "containers": rows}


def host_probe() -> dict[str, Any]:
    p = invoke(LOCAL_PROBE, 38, REMOTE)
    if p["error_type"] or p["exit_code"] != 0:
        return {"status": "UNAVAILABLE", "observed_at_utc": now_utc(),
                "error_type": p["error_type"], "exit_code": p["exit_code"]}
    try:
        result = json.loads(p["stdout"])
        if result.get("hostname") != "nc-ph-4354" or not isinstance(result.get("checks"), dict):
            raise ValueError("Unexpected host")
        result["checks"]["containers"] = parse_containers(result["checks"].get("containers", {}))
        result["status"] = "MEASURED"
        return result
    except (TypeError, ValueError, AttributeError):
        return {"status": "UNAVAILABLE", "observed_at_utc": now_utc(), "error_type": "INVALID_HOST_OUTPUT"}


def make_receipt(http: dict[str, Any], host: dict[str, Any], started: str) -> dict[str, Any]:
    anomalies = [name for name, check in http.items() if check.get("status") != "EXPECTED"]
    c = host.get("checks", {}).get("containers", {})
    if host.get("status") != "MEASURED" or c.get("status") != "MEASURED":
        anomalies.append("new_host_inventory_unavailable")
    elif c.get("running") != 36 or c.get("unhealthy") or c.get("restarting") or c.get("restart_count_total"):
        anomalies.append("container_inventory_requires_review")
    checks = host.get("checks", {})
    owners = [row for row in (c.get("containers") or []) if row["name"] == "web-dashboard-frontend-1"]
    identity_ok = len(owners) == 1 and owners[0]["image"] == OWNER_IMAGE
    version = checks.get("owner_next_version", {})
    version_ok = version.get("status") == "MEASURED" and version.get("value") == "15.5.27"
    if not identity_ok or not version_ok:
        anomalies.append("owner_runtime_identity_unverified")
    for name in ("resources", "raid", "owner_rollback_image"):
        if checks.get(name, {}).get("status") != "MEASURED":
            anomalies.append(name + "_unavailable")
    for container in c.get("containers") or []:
        if container.get("oom_killed") or container.get("state") != "running":
            anomalies.append("container_state_requires_review")
        if container.get("health") not in ("healthy", None):
            anomalies.append("container_health_requires_review")
        if container.get("health") is None and container.get("name") != "web-dashboard-cloudflared-1":
            anomalies.append("unexpected_missing_healthcheck")
    raids = checks.get("raid", {}).get("value") or []
    if not raids:
        anomalies.append("raid_inventory_unavailable")
    for md in raids:
        if md.get("level") in ("raid0", "linear"):
            # Nonredundant arrays do not expose degraded/mismatch counters. Preserve their identity.
            if md.get("array_state") not in ("clean", "active"):
                anomalies.append("nonredundant_array_state_requires_review")
            continue
        if md.get("degraded") is None or md.get("mismatch_cnt") is None or md.get("sync_action") is None:
            anomalies.append("raid_fields_unavailable")
        elif md["degraded"] != "0" or md["mismatch_cnt"] != "0" or md["sync_action"] != "idle":
            anomalies.append("raid_requires_review")
    resources = checks.get("resources", {}).get("value") or {}
    for filesystem in resources.get("filesystems", []):
        total, available = filesystem.get("total_bytes"), filesystem.get("available_bytes")
        inodes, free = filesystem.get("total_inodes"), filesystem.get("free_inodes")
        if total is None or available is None or total <= 0 or not 0 <= available <= total:
            anomalies.append("filesystem_capacity_unavailable")
        elif available / total <= 0.30:
            anomalies.append("disk_capacity_warning")
        if inodes is None or free is None or inodes <= 0 or not 0 <= free <= inodes:
            anomalies.append("filesystem_inode_capacity_unavailable")
        elif free / inodes <= 0.30:
            anomalies.append("inode_capacity_warning")
    if not resources.get("filesystems"):
        anomalies.append("filesystem_inventory_unavailable")
    memory = resources.get("memory", {})
    if memory.get("MemTotal_bytes", 0) > 0 and memory.get("MemAvailable_bytes", 0) / memory["MemTotal_bytes"] < 0.10:
        anomalies.append("memory_pressure_warning")
    return {"schema": "aionex.ns12.bounded_observer.v2", "started_at_utc": started,
            "recorded_at_utc": now_utc(), "target_host": "nc-ph-4354",
            "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "status": "REVIEW_REQUIRED" if anomalies else "PARTIAL_SAMPLE_EXPECTED",
            "http": http,
            "cross_target_dns_stall_correlation": cross_target_dns_stall_correlation(http),
            "new_host": host, "anomalies": sorted(set(anomalies)),
            "owner_runtime_identity_matches_accepted_receipt": identity_ok and version_ok,
            "not_measured": ["authenticated_user_journeys", "postgres_and_redis_deep_metrics",
                             "all_queue_depths_and_ages", "current_backup_and_independent_restore",
                             "nvme_smart", "cloudflare_registered_connections", "old_admission",
                             "continuous_availability_and_error_rates", "vip_artifact_security_parity",
                             "ns14a_real_fault_acceptance"],
            "continuous_72h_certified": False, "full_release_accepted": False,
            "production_mutation": False, "canonical_checkpoint_modified": False,
            "collector_execution": "NEW_HOST_LOCAL", "old_host_required_for_collection": False,
            "note": "Current partial sample only. Unavailable probes are not healthy or zero. No historical backfill."}


def persist(receipt: dict[str, Any], directory: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / ("NS12-WATCH-" + stamp + ".json")
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    # O_EXCL prohibits overwriting any previous observation or canonical state.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def main() -> int:
    started = now_utc()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        remote = executor.submit(host_probe)
        pending = {name: executor.submit(http_probe, url, expected)
                   for name, (url, expected) in URLS.items()}
        def safe_result(future):
            try:
                return future.result()
            except Exception as error:
                return {"status": "UNAVAILABLE", "observed_at_utc": now_utc(),
                        "error_type": type(error).__name__, "http_code": None}
        http = {name: safe_result(f) for name, f in pending.items()}
        host = safe_result(remote)
    receipt = make_receipt(http, host, started)
    receipt["dns_preconnect_diagnostic"] = dns_preconnect_diagnostic(http)
    path = persist(receipt, EVIDENCE)
    # Read-back verifies that the create-only evidence is actually durable/readable.
    saved = json.loads(path.read_text())
    if saved != receipt:
        raise RuntimeError("Observation readback mismatch")
    print(json.dumps({"receipt": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "status": receipt["status"], "anomalies": receipt["anomalies"],
                      "http_codes": {k: v.get("http_code") for k, v in http.items()},
                      "containers": {k: host.get("checks", {}).get("containers", {}).get(k)
                                     for k in ("running", "unhealthy", "restarting", "restart_count_total")},
                      "full_release_accepted": False}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
