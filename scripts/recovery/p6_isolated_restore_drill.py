#!/usr/bin/env python3
"""P6 gate 6.4 (FR-08 / FR-24): isolated FULL restore drill from the newest R2 backup.

Restores DB + platform assets (media, studio, portal, 3D, ...) + auth data into
a throwaway compose project on an internal network, smoke-tests it (canary
login, project read, media fetch), writes a receipt and tears everything down.

  plan          print the steps; touches nothing (default)
  guard-check   render the drill compose config and run every production
                guard; read-only (needs docker on the NEW host)
  run           the drill; needs --execute and --confirm-project

Production guards (``validate_compose_config``) refuse to start when the
project name, any network or any volume could be production's, when a
service publishes ports, uses host networking/privileges, mounts the Docker
socket or any bind path outside the allow-list, or when anything but the
one-shot ``fetch`` service can reach the internet.  Teardown always runs and
is verified (no container, network or volume with the drill label remains).

Implements FR-24 ``RESTORE_PLAN`` steps 1-3, 5-7 for real
(``scripts/recovery/fr24_restore_plan.py`` stays the metadata contract).
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
COMPOSE_FILE = ROOT / "deploy" / "restore-drill" / "docker-compose.restore-drill.yml"
SMOKE_FILE = ROOT / "deploy" / "restore-drill" / "smoke.py"
SCHEMA = "aionex.p6.isolated-restore-drill.v1"
PROJECT_PATTERN = re.compile(r"aionex-restore-drill-[0-9]{8}t[0-9]{6}z\Z")
PRODUCTION_PROJECTS = frozenset({"web-dashboard", "aionex", "aios", "aionex-aios"})
PRODUCTION_MARKERS = ("web-dashboard", "aionex-network", "postgres_data", "backup_data", "media_asset_data")
DRILL_ROOT = Path("/var/lib/aionex-migration/p6-restore-drill")
ALLOWED_NETWORKS = {"drill_isolated", "drill_egress"}
ALLOWED_VOLUMES = {"drill_scratch", "drill_assets", "drill_pgdata"}
EGRESS_SERVICES = {"fetch"}
PROFILES = ("fetch", "restore", "app", "smoke")
DEFAULT_R2_SECRET = "/root/.config/aionex/r2-backup/credentials.env"
DEFAULT_KEYRING = "/root/.config/aionex/backup-encryption/keyring.json"


class DrillRefused(RuntimeError):
    pass


def default_project_name(now: datetime | None = None) -> str:
    return "aionex-restore-drill-" + (now or datetime.now(UTC)).strftime("%Y%m%dt%H%M%Sz")


def validate_project_name(name: str) -> None:
    if PROJECT_PATTERN.fullmatch(name) is None:
        raise DrillRefused("project name must be aionex-restore-drill-YYYYMMDDtHHMMSSz")
    if name in PRODUCTION_PROJECTS or any(marker in name for marker in PRODUCTION_MARKERS):
        raise DrillRefused("project name collides with production")


def validate_compose_config(config: dict[str, Any], project: str, allowed_binds: dict[str, set[str]]) -> list[str]:
    """Return every production-safety violation in a rendered compose config.

    ``allowed_binds`` maps service name -> host paths it may bind (read-only).
    """
    problems: list[str] = []
    try:
        validate_project_name(project)
    except DrillRefused as exc:
        problems.append(str(exc))
    if config.get("name") != project:
        problems.append("rendered project name differs from the guarded name")
    networks = config.get("networks") or {}
    for key, network in networks.items():
        if key not in ALLOWED_NETWORKS:
            problems.append(f"unexpected network {key}")
            continue
        network = network or {}
        if network.get("external"):
            problems.append(f"network {key} is external")
        if network.get("name") != f"{project}_{key}":
            problems.append(f"network {key} is not project-scoped")
        if any(marker in str(network.get("name", "")) for marker in PRODUCTION_MARKERS):
            problems.append(f"network {key} uses a production name")
    if not (networks.get("drill_isolated") or {}).get("internal"):
        problems.append("drill_isolated must be internal (no egress)")
    volumes = config.get("volumes") or {}
    for key, volume in volumes.items():
        volume = volume or {}
        if key not in ALLOWED_VOLUMES:
            problems.append(f"unexpected volume {key}")
        if volume.get("external"):
            problems.append(f"volume {key} is external")
        if volume.get("name") != f"{project}_{key}":
            problems.append(f"volume {key} is not project-scoped")
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
        mode = service.get("network_mode")
        if mode not in (None, "none"):
            problems.append(f"{name} uses network_mode {mode}")
        joined = set((service.get("networks") or {}).keys())
        if joined - ALLOWED_NETWORKS:
            problems.append(f"{name} joins a foreign network")
        if "drill_egress" in joined and name not in EGRESS_SERVICES:
            problems.append(f"{name} must not reach the internet")
        if name in EGRESS_SERVICES and "drill_isolated" in joined:
            problems.append(f"{name} must not bridge egress and the isolated network")
        for mount in service.get("volumes") or []:
            kind, source = mount.get("type"), str(mount.get("source", ""))
            if kind == "volume":
                if source not in ALLOWED_VOLUMES:
                    problems.append(f"{name} mounts foreign volume {source}")
            elif kind == "bind":
                if "docker.sock" in source:
                    problems.append(f"{name} mounts the Docker socket")
                elif source not in allowed_binds.get(name, set()):
                    problems.append(f"{name} binds a non-allow-listed path {source}")
                elif not mount.get("read_only"):
                    problems.append(f"{name} bind {source} is not read-only")
            else:
                problems.append(f"{name} uses mount type {kind}")
    return sorted(set(problems))


def plan_steps() -> list[dict[str, str]]:
    return [
        {"step": "0", "action": "guard: fresh project name, no existing resources, compose config passes production guards"},
        {"step": "1", "action": "fetch (egress-only container): newest R2 manifest -> AES-GCM authenticated -> DB dump + asset snapshot, SHA-256 verified"},
        {"step": "2", "action": "postgres + redis on internal network; pg_restore --exit-on-error --no-owner --no-privileges"},
        {"step": "3", "action": "extract asset snapshot (files/<root>/...) into the drill asset volume"},
        {"step": "4", "action": "start the restored backend (same image, throwaway SECRET_KEY, no egress) and wait for /ready"},
        {"step": "5", "action": "smoke: canary login, project list/read, portal/studio media fetch"},
        {"step": "6", "action": "receipt (RPO = drill start - backup created_at, RTO = app ready - drill start)"},
        {"step": "7", "action": "teardown: down -v --remove-orphans, verify zero labelled resources, delete drill env"},
    ]


class Drill:
    def __init__(self, project: str, *, r2_secret: str, keyring: str, canary_email: str,
                 canary_password_file: str, studio_asset_id: str, backend_image: str, postgres_image: str) -> None:
        validate_project_name(project)
        self.project = project
        self.directory = DRILL_ROOT / project
        self.env_file = self.directory / "drill.env"
        self.env = {
            **os.environ,
            "DRILL_ENV_FILE": str(self.env_file),
            "DRILL_R2_SECRET_FILE": r2_secret,
            "DRILL_KEYRING_FILE": keyring,
            "DRILL_CANARY_EMAIL": canary_email,
            "DRILL_CANARY_PASSWORD_FILE": canary_password_file,
            "DRILL_STUDIO_ASSET_ID": studio_asset_id,
            "DRILL_BACKEND_IMAGE": backend_image,
            "DRILL_POSTGRES_IMAGE": postgres_image,
        }
        self.allowed_binds = {
            "fetch": {r2_secret, keyring},
            "smoke": {str(SMOKE_FILE), canary_password_file},
        }
        self.timeline: dict[str, float] = {}

    def compose(self, *args: str, timeout: int = 1800, profiles: tuple[str, ...] = PROFILES) -> subprocess.CompletedProcess[str]:
        argv = ["docker", "compose", "-p", self.project, "-f", str(COMPOSE_FILE)]
        for profile in profiles:
            argv += ["--profile", profile]
        return subprocess.run(argv + list(args), env=self.env, capture_output=True, text=True,
                              timeout=timeout, check=False)

    def existing_resources(self) -> dict[str, list[str]]:
        label = f"label=com.docker.compose.project={self.project}"
        found = {}
        for kind, argv in (("containers", ["docker", "ps", "-aq", "--filter", label]),
                           ("networks", ["docker", "network", "ls", "-q", "--filter", label]),
                           ("volumes", ["docker", "volume", "ls", "-q", "--filter", label])):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
            if result.returncode != 0:
                raise DrillRefused(f"cannot list docker {kind}")
            found[kind] = [line for line in result.stdout.split() if line]
        return found

    def write_env(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        values = {
            "SECRET_KEY": secrets.token_urlsafe(48),
            "POSTGRES_USER": "aionex_drill",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "POSTGRES_DB": "aionex_restore_drill",
        }
        descriptor = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))

    def rendered_config(self) -> dict[str, Any]:
        result = self.compose("config", "--format", "json", timeout=120)
        if result.returncode != 0:
            raise DrillRefused("docker compose config failed")
        return json.loads(result.stdout)

    def guard(self) -> dict[str, Any]:
        config = self.rendered_config()
        problems = validate_compose_config(config, self.project, self.allowed_binds)
        # The rendered config inlines the throwaway secrets: keep only a digest.
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        return {"problems": problems, "rendered_config_sha256": digest}

    def step(self, name: str, *args: str, timeout: int = 3600, profiles: tuple[str, ...] = PROFILES) -> dict[str, Any]:
        result = self.compose(*args, timeout=timeout, profiles=profiles)
        self.timeline[name] = time.time()
        tail = result.stdout.strip().splitlines()[-1:] if result.stdout.strip() else []
        parsed = None
        if tail:
            try:
                parsed = json.loads(tail[0])
            except ValueError:
                parsed = None
        if result.returncode != 0:
            raise DrillRefused(f"step {name} failed (exit {result.returncode}): {result.stderr.strip()[-300:]}")
        return {"exit_code": result.returncode, "result": parsed}

    def wait_healthy(self, service: str, timeout: int) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.compose("ps", "--format", "json", service, timeout=60)
            text = result.stdout.strip()
            rows = [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")] if text else []
            if rows and all(row.get("Health") == "healthy" for row in rows):
                return
            time.sleep(5)
        raise DrillRefused(f"{service} did not become healthy within {timeout}s")

    def teardown(self) -> dict[str, Any]:
        result = self.compose("down", "-v", "--remove-orphans", "--timeout", "20", timeout=600)
        remaining = self.existing_resources()
        try:
            self.env_file.unlink(missing_ok=True)
            self.directory.rmdir()
        except OSError:
            pass
        return {"exit_code": result.returncode, "remaining": remaining,
                "clean": result.returncode == 0 and not any(remaining.values())}

    def run(self) -> dict[str, Any]:
        receipt: dict[str, Any] = {"schema": SCHEMA, "project": self.project, "started_at_utc": datetime.now(UTC).isoformat(),
                                   "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                   "compose_sha256": hashlib.sha256(COMPOSE_FILE.read_bytes()).hexdigest(),
                                   "steps": {}}
        start = time.time()
        if any(self.existing_resources().values()):
            raise DrillRefused("drill project already has resources; choose a fresh name")
        self.write_env()
        try:
            guard = self.guard()
            receipt["guard"] = guard
            if guard["problems"]:
                raise DrillRefused("production guard failed: " + "; ".join(guard["problems"]))
            receipt["steps"]["scratch_init"] = self.step("scratch_init", "run", "--rm", "scratch-init", timeout=300)
            receipt["steps"]["fetch"] = self.step("fetch", "run", "--rm", "fetch")
            self.step("datastores", "up", "-d", "postgres", "redis", timeout=600)
            self.wait_healthy("postgres", 300)
            receipt["steps"]["db_restore"] = self.step("db_restore", "run", "--rm", "db-restore")
            receipt["steps"]["assets_restore"] = self.step("assets_restore", "run", "--rm", "assets-restore")
            self.step("backend", "up", "-d", "backend", timeout=900)
            self.wait_healthy("backend", 900)
            self.timeline["app_ready"] = time.time()
            receipt["steps"]["smoke"] = self.step("smoke", "run", "--rm", "smoke", timeout=600)
            receipt["status"] = "PASS" if (receipt["steps"]["smoke"]["result"] or {}).get("status") == "PASS" else "FAIL"
        except (DrillRefused, subprocess.TimeoutExpired, ValueError) as exc:
            receipt["status"] = "FAIL"
            receipt["error"] = str(exc)[:500]
        finally:
            receipt["teardown"] = self.teardown()
            if not receipt["teardown"]["clean"]:
                receipt["status"] = "FAIL_TEARDOWN_INCOMPLETE"
        summary = (receipt["steps"].get("fetch") or {}).get("result") or {}
        created = summary.get("backup_created_at")
        receipt["backup"] = {k: summary.get(k) for k in ("backup_id", "backup_created_at", "database", "assets")}
        receipt["rpo_seconds"] = (
            round(start - datetime.fromisoformat(created).timestamp(), 1) if isinstance(created, str) else None
        )
        receipt["rto_seconds"] = round(self.timeline["app_ready"] - start, 1) if "app_ready" in self.timeline else None
        receipt["timeline_offsets_seconds"] = {k: round(v - start, 1) for k, v in self.timeline.items()}
        receipt["completed_at_utc"] = datetime.now(UTC).isoformat()
        receipt["production_mutation"] = False
        return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "guard-check", "run"), nargs="?", default="plan")
    parser.add_argument("--project", default=default_project_name())
    parser.add_argument("--r2-secret-file", default=DEFAULT_R2_SECRET)
    parser.add_argument("--keyring-file", default=DEFAULT_KEYRING)
    parser.add_argument("--canary-email", default="", help="synthetic restore canary present in the backup")
    parser.add_argument("--canary-password-file", default="")
    parser.add_argument("--studio-asset-id", default="")
    parser.add_argument("--backend-image", default="aionex-aios-backend:local")
    parser.add_argument("--postgres-image", default="aionex-aios-postgres:16-hardened")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-project", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        validate_project_name(args.project)
    except DrillRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 2
    if args.command == "plan" or (args.command == "run" and not args.execute):
        print(json.dumps({"schema": SCHEMA + ".plan", "status": "DRY_RUN", "project": args.project,
                          "steps": plan_steps(), "docker_commands_run": 0}, indent=2))
        return 0
    if args.canary_email and not args.canary_email.endswith("@synthetic.loadtest.invalid"):
        print(json.dumps({"status": "REFUSED", "reason": "the canary must be a synthetic account"}))
        return 2
    drill = Drill(args.project, r2_secret=args.r2_secret_file, keyring=args.keyring_file,
                  canary_email=args.canary_email or "unset@synthetic.loadtest.invalid",
                  canary_password_file=args.canary_password_file or str(SMOKE_FILE),
                  studio_asset_id=args.studio_asset_id, backend_image=args.backend_image,
                  postgres_image=args.postgres_image)
    if args.command == "guard-check":
        # Render only: the env file is created in a fresh drill dir and removed.
        try:
            drill.write_env()
            result = drill.guard()
        except DrillRefused as exc:
            result = {"problems": [str(exc)]}
        finally:
            drill.env_file.unlink(missing_ok=True)
            try:
                drill.directory.rmdir()
            except OSError:
                pass
        print(json.dumps({"status": "GUARDS_PASS" if not result["problems"] else "GUARDS_FAIL", **result}, indent=2))
        return 0 if not result["problems"] else 2
    if args.confirm_project != args.project or not args.canary_email or not args.canary_password_file:
        print(json.dumps({"status": "REFUSED",
                          "reason": "--confirm-project, --canary-email and --canary-password-file are required"}))
        return 2
    receipt = drill.run()
    if args.output:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: receipt.get(k) for k in ("status", "project", "rpo_seconds", "rto_seconds", "error")}, indent=2))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
