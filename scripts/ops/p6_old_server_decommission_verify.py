#!/usr/bin/env python3
"""P6 gate 6.5 (NS-15 / NS-16): READ-ONLY old-server decommission verification.

Proves nothing still depends on the OLD server before the owner approves its
retirement.  It never changes DNS, tunnels, webhooks, services or billing.
The old host's IP/name are passed at run time and are not stored in the repo
(NS-15: no host IPs in tracked docs); the receipt stores only their SHA-256.

Checks
  dns        public A/AAAA/CNAME/TXT of every production name via two DNS-over-
             HTTPS resolvers and the system resolver: no answer may be the old
             IP/name (TXT covers SPF ip4: entries)
  edge       api/portal/owner hosts answer through Cloudflare (server header)
  webhooks   Telegram getWebhookInfo and Stripe webhook_endpoints (read-only,
             only when their token files are given): no URL on the old host
  local      on the NEW host: /etc/hosts, systemd units, cron, ssh config,
             compose env files and running container env/extra-hosts must not
             mention the old IP/name; old tunnel/rescue units must be inactive
  old_host   informational TCP probe of the old IP (22/80/443)

Exit 0 only when every automated check passes; manual items (Meta webhook,
Cloudflare dashboard, provider billing) are listed in the receipt and in
docs/project/PRE-LAUNCH-RUNBOOK.md.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

SCHEMA = "aionex.p6.old-server-decommission-verify.v1"
PRODUCTION_NAMES = ("api.vip-e.net", "vip-e.net", "www.vip-e.net", "ai.vip-e.net", "gabarot.vip-e.net")
DOH_RESOLVERS = ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve")
RECORD_TYPES = ("A", "AAAA", "CNAME", "TXT")
OLD_RELATIONSHIP_UNITS = (
    "aionex-old-rescue-progress.timer",
    "aionex-phase22c-tunnel.service",
    "aionex-phase22c-2-tunnel.service",
)
LOCAL_SCAN_GLOBS = (
    "/etc/hosts",
    "/etc/systemd/system/*.service",
    "/etc/systemd/system/*.timer",
    "/etc/systemd/system/*.d/*.conf",
    "/etc/cron.d/*",
    "/etc/crontab",
    "/var/spool/cron/crontabs/*",
    "/root/.ssh/config",
    "/etc/ssh/ssh_config.d/*",
    "/opt/AIOS/web-dashboard/.env*",
    "/opt/AIOS/web-dashboard/docker-compose*.yml",
    "/etc/cloudflared/*",
    "/root/.cloudflared/*.yml",
)
MANUAL_ITEMS = (
    "Meta App Dashboard -> Webhooks: Page/Instagram callback is https://api.vip-e.net/api/v1/social/meta/webhooks",
    "Cloudflare Zero Trust -> Tunnels: only the NEW connector is healthy for every public hostname; old connector removed",
    "Cloudflare DNS: no proxied/unproxied record targets the old IP (dashboard view, includes non-listed names)",
    "Stripe Dashboard -> Webhooks: only https://api.vip-e.net/api/v1/billing/webhooks/stripe (if no key file given)",
    "Uptime/monitoring targets and any allow-list (cPanel WAF, R2/API tokens with IP filters) do not reference the old IP",
    "Final archival backup of OLD taken and its restore verified (NS-16), then owner approval recorded",
    "Old-server-only credentials and SSH trust rotated/revoked; provider billing cancelled ONLY after owner approval",
)


def digest(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def answers_reference_old(answers: list[str], old_ip: str, old_names: list[str]) -> list[str]:
    """Answers/lines that mention the old IP (exact token) or an old hostname."""
    if ":" in old_ip:  # IPv6: not part of a longer hex/colon run
        ip_pattern = r"(?<![0-9a-f:])" + re.escape(old_ip.lower()) + r"(?![0-9a-f:])"
    else:  # IPv4: not part of a longer dotted number (ip4:1.2.3.4 still matches)
        ip_pattern = r"(?<![0-9.])" + re.escape(old_ip) + r"(?![0-9]|\.[0-9])"
    patterns = [re.compile(ip_pattern)]
    patterns += [
        re.compile(r"(?<![0-9a-z-])" + re.escape(name.lower().rstrip(".")) + r"(?![0-9a-z-])")
        for name in old_names if name.strip()
    ]
    return [answer for answer in answers if any(p.search(answer.lower()) for p in patterns)]


def doh_query(resolver: str, name: str, record_type: str, opener: Callable[..., Any] = urllib.request.urlopen) -> list[str]:
    url = resolver + "?" + urllib.parse.urlencode({"name": name, "type": record_type})
    request = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
    with opener(request, timeout=10) as response:
        payload = json.loads(response.read(256 * 1024))
    return [str(row.get("data", "")) for row in payload.get("Answer", []) or []]


def check_dns(names: list[str], old_ip: str, old_names: list[str], opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    results: dict[str, Any] = {}
    failures = []
    for name in names:
        per_name: dict[str, Any] = {}
        for resolver in DOH_RESOLVERS:
            for record_type in RECORD_TYPES:
                try:
                    answers = doh_query(resolver, name, record_type, opener)
                except (OSError, ValueError) as exc:
                    per_name[f"{resolver}:{record_type}"] = {"error": type(exc).__name__}
                    failures.append(f"{name}:{record_type}:resolver_error")
                    continue
                hits = answers_reference_old(answers, old_ip, old_names)
                per_name[f"{resolver}:{record_type}"] = {"answers": len(answers), "old_references": len(hits)}
                if hits:
                    failures.append(f"{name}:{record_type}:references_old")
        try:
            system = sorted({info[4][0] for info in socket.getaddrinfo(name, 443)})
        except OSError:
            system = []
        per_name["system_resolver_old_reference"] = old_ip in system
        if old_ip in system:
            failures.append(f"{name}:system_resolver:references_old")
        results[name] = per_name
    return {"status": "PASS" if not failures else "FAIL", "failures": sorted(set(failures)), "names": results}


def check_edge(names: list[str], opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    rows, failures = {}, []
    for name in names:
        request = urllib.request.Request(f"https://{name}/", method="HEAD")
        try:
            with opener(request, timeout=10) as response:
                server, code = response.headers.get("server", ""), response.status
        except urllib.error.HTTPError as error:
            server, code = error.headers.get("server", ""), error.code
        except OSError as exc:
            rows[name] = {"error": type(exc).__name__}
            failures.append(f"{name}:unreachable")
            continue
        rows[name] = {"http": code, "server": server}
        if name.startswith(("api.", "gabarot.")) and "cloudflare" not in server.lower():
            failures.append(f"{name}:not_behind_cloudflare")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "hosts": rows}


def _read_secret(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def check_webhooks(telegram_token_file: str, stripe_key_file: str, old_ip: str, old_names: list[str],
                   opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    failures: list[str] = []
    if telegram_token_file:
        token = _read_secret(telegram_token_file)
        try:
            with opener(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=15) as response:
                info = json.loads(response.read()).get("result", {})
            url = str(info.get("url", ""))
            host = urllib.parse.urlsplit(url).hostname or ""
            rows["telegram"] = {"mode": "webhook" if url else "polling", "host": host,
                                "pending_update_count": info.get("pending_update_count")}
            if url and (answers_reference_old([host], old_ip, old_names) or host != "api.vip-e.net"):
                failures.append("telegram:webhook_not_on_new_api")
        except (OSError, ValueError) as exc:
            rows["telegram"] = {"error": type(exc).__name__}
            failures.append("telegram:unreadable")
    if stripe_key_file:
        key = _read_secret(stripe_key_file)
        request = urllib.request.Request("https://api.stripe.com/v1/webhook_endpoints?limit=100",
                                         headers={"Authorization": f"Bearer {key}"})
        try:
            with opener(request, timeout=15) as response:
                endpoints = json.loads(response.read()).get("data", [])
            hosts = [urllib.parse.urlsplit(str(e.get("url", ""))).hostname or "" for e in endpoints
                     if e.get("status") == "enabled"]
            rows["stripe"] = {"enabled_endpoints": len(hosts), "hosts": sorted(set(hosts))}
            if any(answers_reference_old([h], old_ip, old_names) or h != "api.vip-e.net" for h in hosts):
                failures.append("stripe:endpoint_not_on_new_api")
        except (OSError, ValueError) as exc:
            rows["stripe"] = {"error": type(exc).__name__}
            failures.append("stripe:unreadable")
    status = "PASS" if not failures else "FAIL"
    if not rows:
        status = "MANUAL"
    return {"status": status, "failures": failures, "providers": rows}


def scan_files(patterns: tuple[str, ...], old_ip: str, old_names: list[str]) -> dict[str, Any]:
    hits = []
    scanned = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            file = Path(path)
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1
            count = len(answers_reference_old(text.splitlines(), old_ip, old_names))
            if count:
                hits.append({"path": path, "matching_lines": count})  # never the line content
    return {"scanned_files": scanned, "hits": hits}


def scan_containers(old_ip: str, old_names: list[str]) -> dict[str, Any]:
    listing = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=60, check=False)
    if listing.returncode != 0:
        return {"status": "UNAVAILABLE"}
    hits = []
    for ident in listing.stdout.split():
        inspect = subprocess.run(["docker", "inspect", "--format",
                                  "{{.Name}}\t{{json .Config.Env}}\t{{json .HostConfig.ExtraHosts}}", ident],
                                 capture_output=True, text=True, timeout=30, check=False)
        name, _, rest = inspect.stdout.partition("\t")
        if answers_reference_old([rest], old_ip, old_names):
            hits.append(name.strip().lstrip("/"))
    return {"status": "MEASURED", "containers_referencing_old": sorted(hits)}


def unit_states(units: tuple[str, ...]) -> dict[str, str]:
    states = {}
    for unit in units:
        result = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=15, check=False)
        states[unit] = result.stdout.strip() or "unknown"
    return states


def check_local(old_ip: str, old_names: list[str]) -> dict[str, Any]:
    files = scan_files(LOCAL_SCAN_GLOBS, old_ip, old_names)
    containers = scan_containers(old_ip, old_names)
    units = unit_states(OLD_RELATIONSHIP_UNITS)
    failures = [f"file:{hit['path']}" for hit in files["hits"]]
    failures += [f"container:{name}" for name in containers.get("containers_referencing_old", [])]
    failures += [f"unit_active:{unit}" for unit, state in units.items() if state in ("active", "activating")]
    if containers.get("status") != "MEASURED":
        failures.append("containers:unavailable")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "files": files,
            "containers": containers, "old_relationship_units": units}


def probe_old_host(old_ip: str) -> dict[str, Any]:
    ports = {}
    for port in (22, 80, 443):
        try:
            with socket.create_connection((old_ip, port), timeout=4):
                ports[str(port)] = "open"
        except OSError:
            ports[str(port)] = "closed_or_filtered"
    return {"status": "INFO", "ports": ports}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old-ip", required=True, help="old server public IP (not stored)")
    parser.add_argument("--old-name", action="append", default=[], help="old server hostname(s) (not stored)")
    parser.add_argument("--name", action="append", default=[], help="extra public names to check")
    parser.add_argument("--telegram-token-file", default="")
    parser.add_argument("--stripe-key-file", default="")
    parser.add_argument("--skip-local", action="store_true", help="when not running on the NEW host")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        address = ipaddress.ip_address(args.old_ip)
    except ValueError:
        print(json.dumps({"status": "REFUSED", "reason": "--old-ip must be an IP address"}))
        return 2
    old_ip = address.compressed
    names = list(PRODUCTION_NAMES) + [n for n in args.name if n not in PRODUCTION_NAMES]
    checks = {
        "dns": check_dns(names, old_ip, args.old_name),
        "edge": check_edge(["api.vip-e.net", "ai.vip-e.net", "vip-e.net", "gabarot.vip-e.net"]),
        "webhooks": check_webhooks(args.telegram_token_file, args.stripe_key_file, old_ip, args.old_name),
        "local": {"status": "SKIPPED"} if args.skip_local else check_local(old_ip, args.old_name),
        "old_host": probe_old_host(old_ip),
    }
    automated_fail = [k for k, v in checks.items() if v.get("status") == "FAIL"]
    pending = [k for k, v in checks.items() if v.get("status") in ("MANUAL", "SKIPPED")]
    status = "FAIL" if automated_fail else ("PASS_AUTOMATED_MANUAL_PENDING" if pending else "PASS_AUTOMATED")
    receipt = {
        "schema": SCHEMA,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "old_ip_sha256": digest(old_ip),
        "old_names_sha256": [digest(n) for n in args.old_name],
        "checks": checks,
        "manual_items": list(MANUAL_ITEMS),
        "status": status,
        "decommission_performed": False,
        "owner_approval_required": True,
    }
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        args.output.chmod(0o600)
    print(text)
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
