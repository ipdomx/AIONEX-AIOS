#!/usr/bin/env python3
"""FR-23C: isolated DAST against a throwaway copy of the backend (never production).

  plan          print the steps (default; runs nothing)
  guard-check   render the compose config and run every production-safety guard
  run --execute --confirm-project <same>   start, probe, scan, tear down, write a receipt

The stack (deploy/fr23c-dast) is an internal-only compose project with an EMPTY
database: two synthetic tenants are seeded, then probe.py runs cross-tenant
(IDOR), anonymous, auth-channel and upload checks over every route of the app's
own OpenAPI document, and OWASP ZAP runs an API scan with tenant B's token.
Everything is removed with `down -v` whatever happens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = ROOT / "deploy" / "fr23c-dast"
COMPOSE_FILE = COMPOSE_DIR / "docker-compose.fr23c-dast.yml"
WORK_ROOT = Path("/var/lib/aionex-migration/fr23c-dast")
SCHEMA = "aionex.fr23c.isolated-dast.v1"
PROJECT_RE = re.compile(r"^aionex-fr23c-dast-[0-9]{8}t[0-9]{6}z$")
PRODUCTION_MARKERS = ("web-dashboard", "aionex-network", "postgres_data", "backup_data", "media_asset_data")
ALLOWED_NETWORKS = {"dast_isolated"}
ALLOWED_VOLUMES = {"dast_scratch", "dast_zap", "dast_data", "dast_pgdata"}
PROFILES = ("app", "tools")


class DastRefused(RuntimeError):
    pass


def default_project_name() -> str:
    return "aionex-fr23c-dast-" + datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz")


def validate_project_name(project: str) -> None:
    if not PROJECT_RE.fullmatch(project) or any(marker in project for marker in PRODUCTION_MARKERS):
        raise DastRefused("project must look like aionex-fr23c-dast-YYYYMMDDtHHMMSSz")


def validate_compose_config(config: dict[str, Any], project: str, allowed_binds: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    try:
        validate_project_name(project)
    except DastRefused as exc:
        problems.append(str(exc))
    if config.get("name") != project:
        problems.append("rendered project name differs from the guarded name")
    networks = config.get("networks") or {}
    for key, network in networks.items():
        network = network or {}
        if key not in ALLOWED_NETWORKS:
            problems.append(f"unexpected network {key}")
        if network.get("external"):
            problems.append(f"network {key} is external")
        if network.get("name") != f"{project}_{key}":
            problems.append(f"network {key} is not project-scoped")
        if not network.get("internal"):
            problems.append(f"network {key} must be internal (no egress)")
    for key, volume in (config.get("volumes") or {}).items():
        volume = volume or {}
        if key not in ALLOWED_VOLUMES:
            problems.append(f"unexpected volume {key}")
        if volume.get("external") or volume.get("name") != f"{project}_{key}":
            problems.append(f"volume {key} is not a project-scoped volume")
    for name, service in (config.get("services") or {}).items():
        if service.get("ports"):
            problems.append(f"{name} publishes ports")
        if service.get("privileged"):
            problems.append(f"{name} is privileged")
        if service.get("container_name"):
            problems.append(f"{name} pins a container name")
        for key in ("pid", "ipc", "userns_mode", "cgroup_parent"):
            if str(service.get(key, "")).startswith(("host", "container:")):
                problems.append(f"{name} shares host {key}")
        if service.get("network_mode") not in (None, "none"):
            problems.append(f"{name} uses network_mode {service.get('network_mode')}")
        if set((service.get("networks") or {}).keys()) - ALLOWED_NETWORKS:
            problems.append(f"{name} joins a foreign network")
        if service.get("extra_hosts"):
            problems.append(f"{name} adds extra hosts")
        for mount in service.get("volumes") or []:
            kind, source = mount.get("type"), str(mount.get("source", ""))
            if kind == "volume" and source not in ALLOWED_VOLUMES:
                problems.append(f"{name} mounts foreign volume {source}")
            elif kind == "bind":
                if "docker.sock" in source:
                    problems.append(f"{name} mounts the Docker socket")
                elif source not in allowed_binds.get(name, set()):
                    problems.append(f"{name} binds a non-allow-listed path {source}")
                elif not mount.get("read_only"):
                    problems.append(f"{name} bind {source} is not read-only")
            elif kind not in ("volume", "bind", "tmpfs"):
                problems.append(f"{name} uses mount type {kind}")
    return problems


def plan_steps() -> list[dict[str, str]]:
    return [
        {"step": "0", "action": "guard: render the compose config and refuse any production reference, egress or host port"},
        {"step": "1", "action": "start an EMPTY postgres + redis and the backend (same image, throwaway SECRET_KEY, no egress)"},
        {"step": "2", "action": "seed two synthetic tenants (A, B) and dump the app's OpenAPI document"},
        {"step": "3", "action": "probe: cross-tenant IDOR over every route, anonymous reads, private channel, upload validator"},
        {"step": "4", "action": "OWASP ZAP API scan (25 min cap) with tenant B's token"},
        {"step": "5", "action": "down -v (containers, network, volumes) and write the receipt"},
    ]


class Dast:
    def __init__(self, project: str, *, backend_image: str, postgres_image: str, zap_image: str) -> None:
        self.project = project
        self.directory = WORK_ROOT / project
        self.env_file = self.directory / "dast.env"
        self.password_file = self.directory / "synthetic-password"
        self.allowed_binds = {"probe": {str(COMPOSE_DIR / "probe.py"), str(self.password_file)},
                              "seed": {str(self.password_file)}}
        self.env = {**os.environ, "DAST_ENV_FILE": str(self.env_file), "DAST_PASSWORD_FILE": str(self.password_file),
                    "DAST_BACKEND_IMAGE": backend_image, "DAST_POSTGRES_IMAGE": postgres_image,
                    "DAST_ZAP_IMAGE": zap_image}

    def compose(self, *args: str, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
        argv = ["docker", "compose", "-p", self.project, "-f", str(COMPOSE_FILE)]
        for profile in PROFILES:
            argv += ["--profile", profile]
        return subprocess.run(argv + list(args), env=self.env, capture_output=True, text=True, timeout=timeout, check=False)

    def write_secrets(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        for path, text in ((self.env_file, "".join(f"{k}={v}\n" for k, v in {
                "SECRET_KEY": secrets.token_urlsafe(48), "POSTGRES_USER": "aionex_dast",
                "POSTGRES_PASSWORD": secrets.token_urlsafe(32), "POSTGRES_DB": "aionex_fr23c_dast"}.items())),
                (self.password_file, secrets.token_urlsafe(24) + "\n")):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(text)

    def guard(self) -> dict[str, Any]:
        result = self.compose("config", "--format", "json", timeout=120)
        if result.returncode != 0:
            raise DastRefused("docker compose config failed")
        config = json.loads(result.stdout)
        return {"problems": validate_compose_config(config, self.project, self.allowed_binds),
                "rendered_config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()}

    def step(self, name: str, *args: str, timeout: int = 1800, allow_fail: bool = False) -> dict[str, Any]:
        result = self.compose(*args, timeout=timeout)
        lines = result.stdout.strip().splitlines()
        parsed = None
        if lines:
            try:
                parsed = json.loads(lines[-1])
            except ValueError:
                parsed = None
        if result.returncode != 0 and not allow_fail:
            detail = json.dumps(parsed)[:600] if parsed is not None else result.stderr.strip()[-400:]
            raise DastRefused(f"step {name} failed (exit {result.returncode}): {detail}")
        return {"exit_code": result.returncode, "result": parsed}

    def wait_healthy(self, service: str, timeout: int) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.compose("ps", "--format", "json", service, timeout=60)
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
            if rows and all(row.get("Health") == "healthy" for row in rows):
                return
            if rows and any(row.get("State") == "exited" for row in rows):
                raise DastRefused(f"{service} exited before becoming healthy")
            time.sleep(5)
        raise DastRefused(f"{service} did not become healthy within {timeout}s")

    def zap_summary(self) -> dict[str, Any]:
        result = self.compose("run", "--rm", "--no-deps", "--entrypoint", "cat", "zap", "/zap/wrk/zap-report.json", timeout=120)
        try:
            report = json.loads(result.stdout)
        except ValueError:
            return {"report": "missing"}
        alerts: dict[str, dict[str, Any]] = {}
        for site in report.get("site", []):
            for alert in site.get("alerts", []):
                key = alert.get("name", "?")
                entry = alerts.setdefault(key, {"risk": alert.get("riskdesc", "").split(" ")[0], "instances": 0, "uris": []})
                entry["instances"] += int(alert.get("count", len(alert.get("instances", []))) or 0)
                if entry["risk"] != "Informational":
                    for instance in alert.get("instances", []):
                        uri = f"{instance.get('method', '')} {instance.get('uri', '')}".strip()
                        if uri and uri not in entry["uris"] and len(entry["uris"]) < 10:
                            entry["uris"].append(uri)
        by_risk: dict[str, int] = {}
        for entry in alerts.values():
            by_risk[entry["risk"]] = by_risk.get(entry["risk"], 0) + 1
        return {"alerts_by_risk": by_risk, "alerts": dict(sorted(alerts.items()))}

    def teardown(self) -> dict[str, Any]:
        result = self.compose("down", "-v", "--remove-orphans", "--timeout", "20", timeout=600)
        label = f"label=com.docker.compose.project={self.project}"
        remaining = {}
        for kind, argv in (("containers", ["docker", "ps", "-aq", "--filter", label]),
                           ("networks", ["docker", "network", "ls", "-q", "--filter", label]),
                           ("volumes", ["docker", "volume", "ls", "-q", "--filter", label])):
            listed = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
            remaining[kind] = listed.stdout.split()
        for path in (self.env_file, self.password_file):
            path.unlink(missing_ok=True)
        try:
            self.directory.rmdir()
        except OSError:
            pass
        return {"exit_code": result.returncode, "remaining": remaining,
                "clean": result.returncode == 0 and not any(remaining.values())}

    def run(self) -> dict[str, Any]:
        receipt: dict[str, Any] = {"schema": SCHEMA, "project": self.project,
                                   "started_at_utc": datetime.now(UTC).isoformat(),
                                   "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                   "compose_sha256": hashlib.sha256(COMPOSE_FILE.read_bytes()).hexdigest(),
                                   "probe_sha256": hashlib.sha256((COMPOSE_DIR / "probe.py").read_bytes()).hexdigest(),
                                   "images": {k: self.env[k] for k in ("DAST_BACKEND_IMAGE", "DAST_POSTGRES_IMAGE", "DAST_ZAP_IMAGE")},
                                   "steps": {}}
        self.write_secrets()
        try:
            guard = self.guard()
            receipt["guard"] = guard
            if guard["problems"]:
                raise DastRefused("production guard failed: " + "; ".join(guard["problems"]))
            self.step("scratch_init", "run", "--rm", "scratch-init", timeout=300)
            self.step("datastores", "up", "-d", "postgres", "redis", timeout=600)
            self.wait_healthy("postgres", 300)
            self.step("backend", "up", "-d", "backend", timeout=900)
            self.wait_healthy("backend", 900)
            run_id = "p6-" + datetime.now(UTC).strftime("%Y%m%dt%H%Mz") + "-fr23c"
            receipt["steps"]["seed"] = self.step(
                "seed", "run", "--rm", "seed", "seed", "--run-id", run_id, "--count", "2", "--projects-per-user", "1",
                "--password-file", "/dast-secrets/password", "--export", "/scratch/accounts.jsonl", "--execute")
            receipt["steps"]["openapi"] = self.step("openapi", "run", "--rm", "openapi", timeout=300)
            receipt["steps"]["probe"] = self.step("probe", "run", "--rm", "probe", timeout=2400, allow_fail=True)
            receipt["steps"]["zap"] = self.step("zap", "run", "--rm", "zap", timeout=2400, allow_fail=True)
            receipt["zap"] = self.zap_summary()
            probe = (receipt["steps"]["probe"].get("result") or {})
            high = int((receipt["zap"].get("alerts_by_risk") or {}).get("High", 0))
            receipt["status"] = "PASS" if probe.get("status") == "PASS" and high == 0 else "FAIL"
        except (DastRefused, subprocess.TimeoutExpired, ValueError) as exc:
            receipt["status"] = "FAIL"
            receipt["error"] = str(exc)[:600]
        finally:
            receipt["teardown"] = self.teardown()
            if not receipt["teardown"]["clean"]:
                receipt["status"] = "FAIL_TEARDOWN_INCOMPLETE"
        receipt["completed_at_utc"] = datetime.now(UTC).isoformat()
        receipt["production_mutation"] = False
        return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "guard-check", "run"), nargs="?", default="plan")
    parser.add_argument("--project", default=default_project_name())
    parser.add_argument("--backend-image", default="aionex-aios-backend:local")
    parser.add_argument("--postgres-image", default="aionex-aios-postgres:16-hardened")
    parser.add_argument("--zap-image", default="zaproxy/zap-stable:2.17.0@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-project", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        validate_project_name(args.project)
    except DastRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 2
    if args.command == "plan" or (args.command == "run" and not args.execute):
        print(json.dumps({"schema": SCHEMA + ".plan", "status": "DRY_RUN", "project": args.project,
                          "steps": plan_steps(), "docker_commands_run": 0}, indent=2))
        return 0
    dast = Dast(args.project, backend_image=args.backend_image, postgres_image=args.postgres_image, zap_image=args.zap_image)
    if args.command == "guard-check":
        dast.write_secrets()
        try:
            guard = dast.guard()
        finally:
            dast.teardown()
        print(json.dumps({"status": "GUARDS_PASS" if not guard["problems"] else "GUARDS_FAIL", **guard}, indent=2))
        return 0 if not guard["problems"] else 1
    if args.confirm_project != args.project:
        print(json.dumps({"status": "REFUSED", "reason": "--confirm-project must repeat --project exactly"}))
        return 2
    receipt = dast.run()
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: receipt.get(k) for k in ("status", "project", "error")}, indent=2))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
