#!/usr/bin/env python3
"""Guarded FR-06C2C PostgreSQL physical cutover executor.

The executor has no key-handling or vault-provisioning capability. It consumes
only an already-provisioned/recovery-proved database-vault and performs a fully
offline PGDATA copy after clean PostgreSQL shutdown.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
from typing import Any, Iterable

SCHEMA_VERSION = 1
SUBPART = "FR-06C2C"
PRODUCTION_ROOT = Path("/opt/AIOS")
DASHBOARD = PRODUCTION_ROOT / "web-dashboard"
PRODUCTION_ENV = DASHBOARD / ".env.production"
STATE_ROOT = Path("/var/lib/aionex/fr06c2-cutover")
C2B_STATE = Path("/var/lib/aionex/fr06c2")
LEGACY_VOLUME = "web-dashboard_postgres_data"
CANDIDATE_VOLUME = "aionex-fr06-database-vault"
LEGACY_SOURCE = Path("/var/lib/docker/volumes/web-dashboard_postgres_data/_data")
CANDIDATE_SOURCE = Path("/mnt/aionex/fr06-database-vault/pgdata")
POSTGRES_SERVICE = "postgres"
RECONCILER_SERVICE = "postgres-credential-reconciler"
POSTGRES_IMAGE = "aionex-aios-postgres:16-hardened"
MAX_PLAN_TTL_SECONDS = 900
MAX_EVIDENCE_AGE_SECONDS = 1800
MAX_WINDOW_SECONDS = 4 * 60 * 60
CUTOVER_CONFIRMATION = "FR06C2_PRODUCTION_DATABASE_CUTOVER"
ROLLBACK_CONFIRMATION = "FR06C2_PRODUCTION_DATABASE_ROLLBACK"
START_CONFIRMATION = "FR06C2_PRODUCTION_DATABASE_START"
SENSITIVE_KEYS = {"key", "private_key", "recovery_key", "secret", "secret_key", "token", "passphrase", "password"}
ACCEPTED_COMPOSE = [
    DASHBOARD / "docker-compose.production.yml",
    DASHBOARD / "docker-compose.fr06-assets.yml",
    DASHBOARD / "docker-compose.fr06-admission.yml",
]
CANDIDATE_COMPOSE = [
    *ACCEPTED_COMPOSE,
    DASHBOARD / "docker-compose.fr06-database.yml",
    DASHBOARD / "docker-compose.fr06-database-admission.yml",
]


class CutoverError(RuntimeError):
    pass


class CutoverBlocked(CutoverError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
    finally:
        os.close(fd)
    return h.hexdigest()


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 120) -> str:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CutoverError(f"command unavailable or timed out: {argv[0]}") from exc
    if result.returncode != 0:
        raise CutoverError(f"{argv[0]} failed with exit code {result.returncode}; output withheld")
    return result.stdout.strip()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise CutoverError("JSON object required")
    return value


def _private_regular(path: Path, label: str, maximum: int = 8 * 1024 * 1024) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CutoverBlocked(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise CutoverBlocked(f"{label} must be a single-link regular file")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077 or not 1 <= info.st_size <= maximum:
        raise CutoverBlocked(f"{label} ownership, mode or size is unsafe")
    return info


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CutoverBlocked(f"{label} must use RFC3339 UTC Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise CutoverBlocked(f"{label} is invalid") from exc


def _walk_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or normalized.endswith("_key_material"):
                raise CutoverBlocked(f"embedded secret material field rejected at {path}.{key}")
            _walk_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_sensitive(child, f"{path}[{index}]")


def _git_gate(root: Path, expected_sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if heads != [expected_sha, expected_sha]:
        raise CutoverBlocked("checkout and origin/main do not match cutover merge SHA")
    if _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise CutoverBlocked("production source tree is not clean")


def _git_descendant_gate(root: Path, minimum_sha: str) -> str:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if len(heads) != 2 or heads[0] != heads[1]:
        raise CutoverBlocked("checkout and origin/main do not match")
    if _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise CutoverBlocked("production source tree is not clean")
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", minimum_sha, heads[0]],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CutoverError("cannot verify cutover source ancestry") from exc
    if result.returncode != 0:
        raise CutoverBlocked("current main does not descend from the accepted cutover commit")
    return heads[0]


def _load_contract(root: Path) -> dict[str, Any]:
    value = _json(root / "docs/project/receipts/FR-06C2C-database-cutover-contract.json")
    clients = value.get("topology", {}).get("runtime_database_clients")
    if not isinstance(clients, list) or len(clients) < 20:
        raise CutoverBlocked("database client contract is incomplete")
    return value


def _evidence(path: Path, merge_sha: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    _private_regular(resolved, "cutover evidence")
    value = _json(resolved)
    _walk_sensitive(value)
    if value.get("schema_version") != 1 or value.get("subpart") != SUBPART or value.get("environment") != "production":
        raise CutoverBlocked("cutover evidence metadata is invalid")
    if value.get("production_authorization") is not True:
        raise CutoverBlocked("cutover evidence lacks production authorization")
    now = _utc_now()
    observed = _parse_time(value.get("observed_at"), "evidence observed_at")
    age = (now - observed).total_seconds()
    if age < -300 or age > MAX_EVIDENCE_AGE_SECONDS:
        raise CutoverBlocked("cutover evidence is stale or future-dated")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("merge_sha") != merge_sha or source.get("protected_pr_checks_passed") is not True or source.get("post_merge_main_checks_passed") is not True:
        raise CutoverBlocked("source CI evidence is incomplete")
    recovery = value.get("recovery")
    if not isinstance(recovery, dict):
        raise CutoverBlocked("fresh recovery evidence is missing")
    for key, wanted in {
        "backup_status": "completed",
        "offsite_status": "completed",
        "restore_status": "completed",
        "restore_validated": True,
        "restore_offsite_validated": True,
    }.items():
        if recovery.get(key) != wanted:
            raise CutoverBlocked(f"fresh recovery gate failed: {key}")
    restore_time = _parse_time(recovery.get("restore_completed_at"), "restore completed_at")
    restore_age = (now - restore_time).total_seconds()
    if restore_age < -300 or restore_age > MAX_EVIDENCE_AGE_SECONDS:
        raise CutoverBlocked("restore validation is stale")
    operations = value.get("operations")
    if not isinstance(operations, dict):
        raise CutoverBlocked("operations preflight is missing")
    for key in ("active_backup_jobs", "active_restore_validations", "active_durable_external_jobs"):
        if operations.get(key) != 0:
            raise CutoverBlocked(f"operations are not drained: {key}")
    if operations.get("admission_closed") is not True or operations.get("cloudflare_changed") is not False:
        raise CutoverBlocked("admission/Cloudflare preflight is unsafe")
    approvals = value.get("approvals")
    if not isinstance(approvals, dict) or approvals.get("owner_authorized") is not True:
        raise CutoverBlocked("owner authorization is missing")
    start = _parse_time(approvals.get("window_starts_at"), "window start")
    end = _parse_time(approvals.get("window_ends_at"), "window end")
    if end <= start or (end - start).total_seconds() > MAX_WINDOW_SECONDS or not start <= now <= end:
        raise CutoverBlocked("maintenance window is invalid or inactive")
    return value


def _compose(files: list[Path], args: list[str], timeout: int = 180) -> str:
    command = ["docker", "compose", "--env-file", str(PRODUCTION_ENV), "--profile", "*"]
    for path in files:
        command += ["-f", str(path)]
    command += args
    environment = os.environ.copy()
    environment["AIOS_ENV_FILE"] = str(PRODUCTION_ENV)
    try:
        result = subprocess.run(command, cwd=DASHBOARD, env=environment, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CutoverError("docker compose invocation failed") from exc
    if result.returncode != 0:
        raise CutoverError(f"docker compose failed with exit code {result.returncode}; output withheld")
    return result.stdout.strip()


def _containers(service: str, *, running_only: bool) -> list[dict[str, Any]]:
    command = ["docker", "ps"] if running_only else ["docker", "ps", "-a"]
    command += ["--filter", "label=com.docker.compose.project=web-dashboard", "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.ID}}"]
    ids = [line.strip() for line in _run(command).splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    for cid in ids:
        value = json.loads(_run(["docker", "inspect", cid]))
        if not isinstance(value, list) or len(value) != 1:
            raise CutoverBlocked(f"cannot inspect service container: {service}")
        item = value[0]
        state = item.get("State") or {}
        rows.append({
            "id": cid,
            "name": str(item.get("Name", "")).lstrip("/"),
            "running": bool(state.get("Running")),
            "status": str(state.get("Status", "")),
            "health": str((state.get("Health") or {}).get("Status", "none")),
            "image": str(item.get("Image", "")),
        })
    return sorted(rows, key=lambda row: row["name"])


def _runtime_topology(contract: dict[str, Any]) -> dict[str, Any]:
    services = contract["topology"]["runtime_database_clients"]
    active: dict[str, list[str]] = {}
    for service in services:
        rows = _containers(str(service), running_only=True)
        if rows:
            active[str(service)] = [row["id"] for row in rows]
    postgres = _containers(POSTGRES_SERVICE, running_only=True)
    if len(postgres) != 1:
        raise CutoverBlocked("exactly one running PostgreSQL container is required")
    if postgres[0]["health"] not in {"healthy", "none"}:
        raise CutoverBlocked("PostgreSQL is not healthy before planning")
    if not active:
        raise CutoverBlocked("no running database clients were found")
    return {
        "postgres_id": postgres[0]["id"],
        "postgres_image_id": postgres[0]["image"],
        "active_clients": active,
        "active_service_count": len(active),
        "active_container_count": sum(len(ids) for ids in active.values()),
    }


def inspect_runtime(root: Path) -> dict[str, Any]:
    contract = _load_contract(root)
    topology = _runtime_topology(contract)
    return {
        "schema_version": 1,
        "subpart": SUBPART,
        "observed_at": _utc(),
        **topology,
        "legacy_source": str(LEGACY_SOURCE),
        "candidate_pgdata": str(CANDIDATE_SOURCE),
        "read_only_inspection": True,
        "production_changed": False,
    }


def _validate_c2b_state(root: Path) -> None:
    provision = C2B_STATE / "provision-receipt.json"
    recovery = C2B_STATE / "recovery-proof.json"
    custody = C2B_STATE / "header-custody.json"
    for path, label in ((provision, "C2B provision receipt"), (recovery, "C2B recovery proof"), (custody, "C2B header custody")):
        _private_regular(path, label)
    p = _json(provision); r = _json(recovery); h = _json(custody)
    if p.get("status") != "empty_database_vault_provisioned_admission_closed" or p.get("target_subpath") != "pgdata" or p.get("production_pgdata_read_or_copied") is not False:
        raise CutoverBlocked("C2B provision receipt is not acceptable")
    if r.get("status") != "independent_database_recovery_key_proved" or r.get("recovery_open_passed") is not True or r.get("active_reopen_passed") is not True:
        raise CutoverBlocked("C2B recovery proof is not acceptable")
    if h.get("status") != "off_host_headers_verified" or h.get("object_count") != 1 or h.get("full_readback_verified") is not True or h.get("recovery_keys_stored_in_r2") is not False:
        raise CutoverBlocked("C2B header custody is not acceptable")
    output = _run(["python3", str(root / "scripts/security/fr06c2_database_vault_provision.py"), "status", "--require-ready"])
    try:
        status = json.loads(output)
    except json.JSONDecodeError as exc:
        raise CutoverBlocked("database-vault status did not return JSON") from exc
    if status.get("validation") != "FR06C2_DATABASE_VAULT_READY" or status.get("running_consumer_count") != 0:
        raise CutoverBlocked("database-vault is not empty and ready for cutover")


def _volume_source(name: str) -> Path:
    value = json.loads(_run(["docker", "volume", "inspect", name]))
    if not isinstance(value, list) or len(value) != 1:
        raise CutoverBlocked(f"volume unavailable: {name}")
    path = Path(str(value[0].get("Mountpoint", ""))).resolve(strict=True)
    if not path.is_dir() or path.is_symlink():
        raise CutoverBlocked(f"volume path unsafe: {name}")
    return path


def _root_paths() -> tuple[Path, Path]:
    legacy = _volume_source(LEGACY_VOLUME)
    if legacy != LEGACY_SOURCE.resolve(strict=True):
        raise CutoverBlocked("legacy PGDATA source path drifted")
    candidate = CANDIDATE_SOURCE.resolve(strict=True)
    if not candidate.is_dir() or candidate.is_symlink():
        raise CutoverBlocked("candidate PGDATA path is unavailable")
    return legacy, candidate


def _manifest_module(root: Path):
    path = root / "scripts/security/fr06b_asset_copy_manifest.py"
    spec = importlib.util.spec_from_file_location(f"fr06c2_pg_manifest_{secrets.token_hex(4)}", path)
    if spec is None or spec.loader is None:
        raise CutoverError("cannot load safe manifest helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _store_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)


def _manifest_summary(value: dict[str, Any]) -> dict[str, Any]:
    summary = value.get("summary")
    if not isinstance(summary, dict):
        raise CutoverError("manifest summary missing")
    return {
        "directories": int(summary["directories"]),
        "regular_files": int(summary["regular_files"]),
        "payload_bytes": int(summary["payload_bytes"]),
        "aggregate_sha256": str(summary["aggregate_sha256"]),
    }


def _stable_copy(root: Path, source: Path, target: Path, evidence_dir: Path) -> dict[str, Any]:
    manifest = _manifest_module(root)
    evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    before = manifest.build_manifest(source)
    _store_json(evidence_dir / "source-before.json", before)
    _run(["rsync", "-aHAX", "--numeric-ids", "--delete", "--safe-links", "--no-devices", "--no-specials", "--", f"{source}/", f"{target}/"], timeout=3600)
    os.sync()
    after = manifest.build_manifest(source)
    candidate = manifest.build_manifest(target)
    _store_json(evidence_dir / "source-after.json", after)
    _store_json(evidence_dir / "target.json", candidate)
    if before.get("entries") != after.get("entries"):
        raise CutoverBlocked("PGDATA source changed during offline copy")
    if after.get("entries") != candidate.get("entries"):
        raise CutoverBlocked("PGDATA source/candidate manifest mismatch")
    return _manifest_summary(candidate)


def _sealed(path: Path) -> bool:
    try:
        options = _run(["findmnt", "-n", "-o", "OPTIONS", "--target", str(path)])
    except CutoverError:
        return False
    return "ro" in set(options.split(","))


def _seal(path: Path) -> None:
    if _sealed(path):
        return
    _run(["mount", "--bind", str(path), str(path)])
    _run(["mount", "-o", "remount,bind,ro,nodev,nosuid,noexec", str(path)])
    if not _sealed(path):
        raise CutoverBlocked("legacy PGDATA read-only seal failed")


def _unseal(path: Path) -> None:
    if _sealed(path):
        _run(["umount", str(path)])


def _pg_state_volume(volume: str, *, subpath: str | None = None) -> str:
    command = ["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", "--user", "70:70"]
    if subpath is None:
        command += ["-v", f"{volume}:/var/lib/postgresql/data:ro"]
    else:
        command += ["--mount", f"type=volume,src={volume},dst=/var/lib/postgresql/data,readonly,volume-subpath={subpath}"]
    command += [POSTGRES_IMAGE, "-lc", "pg_controldata /var/lib/postgresql/data | sed -n 's/^Database cluster state:[[:space:]]*//p'"]
    return _run(command).strip()


def _stop_ids(ids: Iterable[str]) -> None:
    values = list(ids)
    if values:
        _run(["docker", "stop", "-t", "60", *values], timeout=120)


def _all_client_ids(topology: dict[str, Any]) -> list[str]:
    return [cid for service in sorted(topology["active_clients"]) for cid in topology["active_clients"][service]]


def _assert_planned_clients_stopped(topology: dict[str, Any]) -> None:
    for cid in _all_client_ids(topology):
        value = json.loads(_run(["docker", "inspect", cid]))[0]
        if value.get("State", {}).get("Running") is True:
            raise CutoverBlocked("planned database client remained running")


def _wait_service(service: str, expected: int, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = _containers(service, running_only=True)
        if len(rows) == expected and all(row["health"] not in {"unhealthy", "starting"} for row in rows):
            return
        time.sleep(2)
    raise CutoverBlocked(f"service did not become healthy at expected scale: {service}")


def _postgres_probe(container_id: str) -> dict[str, Any]:
    inspected = json.loads(_run(["docker", "inspect", container_id]))
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise CutoverBlocked("cannot inspect PostgreSQL for acceptance")
    env_rows = (inspected[0].get("Config") or {}).get("Env") or []
    env: dict[str, str] = {}
    for row in env_rows:
        if isinstance(row, str) and "=" in row:
            key, value = row.split("=", 1)
            if key in {"POSTGRES_DB", "POSTGRES_USER"}:
                env[key] = value
    database = env.get("POSTGRES_DB")
    user = env.get("POSTGRES_USER")
    if not database or not user:
        raise CutoverBlocked("PostgreSQL identity environment is incomplete")
    query = (
        "select current_database() || '|' || current_user || '|' || current_setting('server_version_num');"
        "select version_num from alembic_version;"
        "select count(*) from organizations;"
        "select count(*) from users;"
        "select count(*) from project_executions;"
        "select count(*) from backup_records;"
        "select count(*) from pg_catalog.pg_tables where schemaname='public';"
    )
    output = _run([
        "docker", "exec", container_id, "psql",
        "-U", user, "-d", database, "-v", "ON_ERROR_STOP=1", "-Atqc", query,
    ], timeout=60)
    lines = output.splitlines()
    if len(lines) != 7:
        raise CutoverBlocked("PostgreSQL acceptance output is incomplete")
    identity = lines[0].split("|")
    if len(identity) != 3 or identity[0] != database or identity[1] != user:
        raise CutoverBlocked("PostgreSQL database identity drifted")
    try:
        counts = [int(value) for value in lines[2:]]
    except ValueError as exc:
        raise CutoverBlocked("PostgreSQL acceptance counts are invalid") from exc
    return {
        "database": identity[0],
        "user": identity[1],
        "server_version_num": identity[2],
        "alembic_version": lines[1],
        "organizations": counts[0],
        "users": counts[1],
        "project_executions": counts[2],
        "backup_records": counts[3],
        "public_table_count": counts[4],
    }


def _start_postgres(files: list[Path]) -> None:
    _compose(files, ["up", "-d", "--no-deps", POSTGRES_SERVICE], timeout=240)
    _wait_service(POSTGRES_SERVICE, 1, timeout=180)


def _run_reconciler(files: list[Path]) -> None:
    _compose(files, ["run", "--rm", "--no-deps", RECONCILER_SERVICE], timeout=180)


def _start_clients(files: list[Path], topology: dict[str, Any]) -> None:
    for service in sorted(topology["active_clients"]):
        count = len(topology["active_clients"][service])
        args = ["up", "-d", "--no-deps"]
        if count > 1:
            args += ["--scale", f"{service}={count}"]
        args += [service]
        _compose(files, args, timeout=300)
    for service in sorted(topology["active_clients"]):
        _wait_service(service, len(topology["active_clients"][service]), timeout=180)


def _stop_candidate_services(topology: dict[str, Any]) -> None:
    services = sorted(topology["active_clients"])
    if services:
        try:
            _compose(CANDIDATE_COMPOSE, ["stop", "-t", "60", *services], timeout=180)
        except CutoverError:
            pass
    try:
        _compose(CANDIDATE_COMPOSE, ["stop", "-t", "90", POSTGRES_SERVICE], timeout=180)
    except CutoverError:
        pass


def _start_legacy(topology: dict[str, Any]) -> None:
    _start_postgres(ACCEPTED_COMPOSE)
    _run_reconciler(ACCEPTED_COMPOSE)
    _start_clients(ACCEPTED_COMPOSE, topology)


def _candidate_topology_matches(topology: dict[str, Any]) -> bool:
    for service, ids in topology["active_clients"].items():
        if len(_containers(service, running_only=True)) != len(ids):
            return False
    return len(_containers(POSTGRES_SERVICE, running_only=True)) == 1


def _write_result(operation_id: str, body: dict[str, Any]) -> Path:
    result = dict(body)
    result["receipt_sha256"] = _digest(body)
    path = STATE_ROOT / "results" / f"{operation_id}.json"
    _store_json(path, result)
    return path


def _lock() -> int:
    STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(STATE_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise CutoverBlocked("another FR-06C2 cutover operation holds the lock") from exc
    return fd


def _reserve(operation_id: str, kind: str) -> None:
    path = STATE_ROOT / "reservations" / f"{operation_id}.json"
    _store_json(path, {"operation_id": operation_id, "kind": kind, "reserved_at": _utc()})


def _preflight(root: Path, evidence_path: Path, merge_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if os.geteuid() != 0 or root.resolve() != PRODUCTION_ROOT:
        raise CutoverBlocked("production cutover requires root and /opt/AIOS")
    for path in [PRODUCTION_ENV, *ACCEPTED_COMPOSE, *CANDIDATE_COMPOSE]:
        if not path.is_file():
            raise CutoverBlocked(f"required Compose source is missing: {path.name}")
    _git_gate(root.resolve(), merge_sha)
    evidence = _evidence(evidence_path.resolve(), merge_sha)
    _validate_c2b_state(root.resolve())
    legacy, candidate = _root_paths()
    if any(candidate.iterdir()):
        raise CutoverBlocked("candidate pgdata subpath is not empty before cutover")
    contract = _load_contract(root.resolve())
    topology = _runtime_topology(contract)
    return evidence, {"topology": topology, "legacy_source": str(legacy), "candidate_source": str(candidate)}


def create_plan(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.ttl_seconds <= MAX_PLAN_TTL_SECONDS:
        raise CutoverBlocked("plan TTL is outside the bounded range")
    evidence, runtime = _preflight(args.root.resolve(), args.evidence.resolve(), args.merge_sha)
    now = _utc_now()
    body = {
        "schema_version": 1,
        "subpart": SUBPART,
        "operation": "database-cutover",
        "created_at": _utc(now),
        "expires_at": _utc(now + timedelta(seconds=args.ttl_seconds)),
        "nonce": secrets.token_hex(32),
        "merge_sha": args.merge_sha,
        "evidence_sha256": _file_digest(args.evidence.resolve()),
        "topology": runtime["topology"],
        "legacy_source": runtime["legacy_source"],
        "candidate_source": runtime["candidate_source"],
        "admission_will_remain_closed": True,
        "cloudflare_change_permitted": False,
        "legacy_deletion_permitted": False,
        "vault_unlock_or_creation_permitted": False,
    }
    body["plan_id"] = _digest(body)
    plan_path = STATE_ROOT / "plans" / f"{body['plan_id']}.json"
    _store_json(plan_path, body)
    return {"decision": "database_cutover_plan_ready", "plan_id": body["plan_id"], "plan": str(plan_path), "expires_at": body["expires_at"], "production_executed": False}


def _load_plan(path: Path, evidence_path: Path) -> dict[str, Any]:
    _private_regular(path, "cutover plan")
    value = _json(path)
    plan_id = value.get("plan_id")
    body = {k: v for k, v in value.items() if k != "plan_id"}
    if not isinstance(plan_id, str) or _digest(body) != plan_id:
        raise CutoverBlocked("cutover plan digest mismatch")
    if value.get("subpart") != SUBPART or value.get("operation") != "database-cutover":
        raise CutoverBlocked("cutover plan scope is invalid")
    if _utc_now() > _parse_time(value.get("expires_at"), "plan expiry"):
        raise CutoverBlocked("cutover plan expired")
    if value.get("evidence_sha256") != _file_digest(evidence_path.resolve()):
        raise CutoverBlocked("cutover evidence changed after planning")
    return value


def _automatic_rollback(root: Path, topology: dict[str, Any], *, candidate_started: bool, legacy: Path, candidate: Path, evidence_dir: Path) -> None:
    _stop_candidate_services(topology)
    if candidate_started:
        state = _pg_state_volume(CANDIDATE_VOLUME, subpath="pgdata")
        if state != "shut down":
            raise CutoverError("candidate PostgreSQL did not shut down cleanly for automatic rollback")
        _unseal(legacy)
        _stable_copy(root, candidate, legacy, evidence_dir / "reverse-delta")
    else:
        _unseal(legacy)
    _start_legacy(topology)


def apply_cutover(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load_plan(args.plan.resolve(), args.evidence.resolve())
    if args.confirmation != f"EXECUTE_FR06C2_DATABASE_CUTOVER:{plan['plan_id']}" or args.confirm_production != CUTOVER_CONFIRMATION:
        raise CutoverBlocked("exact production database cutover confirmation is required")
    evidence, runtime = _preflight(args.root.resolve(), args.evidence.resolve(), args.merge_sha)
    if plan.get("merge_sha") != args.merge_sha or plan.get("topology") != runtime["topology"] or plan.get("legacy_source") != runtime["legacy_source"] or plan.get("candidate_source") != runtime["candidate_source"]:
        raise CutoverBlocked("production topology changed after planning")
    topology = runtime["topology"]
    legacy = Path(runtime["legacy_source"])
    candidate = Path(runtime["candidate_source"])
    operation_id = plan["plan_id"]
    reservation = STATE_ROOT / "reservations" / f"{operation_id}.json"
    if reservation.exists():
        raise CutoverBlocked("cutover plan was already consumed")
    lock_fd = _lock()
    _reserve(operation_id, "database-cutover")
    evidence_dir = STATE_ROOT / "manifests" / operation_id
    candidate_started = False
    try:
        _stop_ids(_all_client_ids(topology))
        _assert_planned_clients_stopped(topology)
        # PostgreSQL remains available only for a final drain check and read-only
        # identity/count baseline after every database client is stopped.
        operations = evidence["operations"]
        if any(int(operations[key]) != 0 for key in ("active_backup_jobs", "active_restore_validations", "active_durable_external_jobs")):
            raise CutoverBlocked("durable work is not drained")
        database_baseline = _postgres_probe(topology["postgres_id"])
        _stop_ids([topology["postgres_id"]])
        state = _pg_state_volume(LEGACY_VOLUME)
        if state != "shut down":
            raise CutoverBlocked("legacy PostgreSQL did not reach clean shutdown")
        _seal(legacy)
        final_manifest = _stable_copy(args.root.resolve(), legacy, candidate, evidence_dir / "forward-delta")
        _start_postgres(CANDIDATE_COMPOSE)
        candidate_started = True
        if _pg_state_volume(LEGACY_VOLUME) != "shut down":
            raise CutoverBlocked("retained legacy PGDATA changed after candidate start")
        candidate_rows = _containers(POSTGRES_SERVICE, running_only=True)
        if len(candidate_rows) != 1:
            raise CutoverBlocked("candidate PostgreSQL topology is invalid")
        database_candidate = _postgres_probe(candidate_rows[0]["id"])
        if database_candidate != database_baseline:
            raise CutoverBlocked("candidate PostgreSQL identity/schema/count acceptance differs from legacy baseline")
        _run_reconciler(CANDIDATE_COMPOSE)
        _start_clients(CANDIDATE_COMPOSE, topology)
        if not _candidate_topology_matches(topology):
            raise CutoverBlocked("candidate database-client topology does not match plan")
        if not _sealed(legacy):
            raise CutoverBlocked("legacy PGDATA read-only seal drifted")
        result_body = {
            "schema_version": 1,
            "subpart": SUBPART,
            "operation": "database-cutover",
            "operation_id": operation_id,
            "status": "candidate_database_started_admission_closed",
            "completed_at": _utc(),
            "merge_sha": args.merge_sha,
            "topology": topology,
            "final_manifest": final_manifest,
            "database_acceptance": {
                "baseline": database_baseline,
                "candidate": database_candidate,
                "exact_match": True,
                "validated_before_reconciler_and_clients": True,
            },
            "legacy_source": str(legacy),
            "candidate_source": str(candidate),
            "legacy_read_only": True,
            "legacy_deleted": False,
            "candidate_postgres_started": True,
            "admission_opened": False,
            "cloudflare_changed": False,
            "docker_gate_installed": False,
            "production_execution": True,
            "parent_fr06_completed": False,
        }
        path = _write_result(operation_id, result_body)
        return {"status": result_body["status"], "operation_id": operation_id, "result": str(path), "admission_opened": False}
    except Exception as original:
        try:
            _automatic_rollback(args.root.resolve(), topology, candidate_started=candidate_started, legacy=legacy, candidate=candidate, evidence_dir=evidence_dir / "automatic-rollback")
        except Exception as rollback_error:
            raise CutoverError("database cutover failed and automatic rollback also failed; admission must remain closed") from rollback_error
        raise CutoverError("database cutover failed; automatic rollback passed and admission remains closed") from original
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _load_success_receipt(path: Path) -> dict[str, Any]:
    _private_regular(path, "cutover receipt")
    value = _json(path)
    receipt_sha = value.get("receipt_sha256")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not isinstance(receipt_sha, str) or receipt_sha != _digest(body):
        raise CutoverBlocked("cutover receipt digest is invalid")
    if value.get("subpart") != SUBPART or value.get("operation") != "database-cutover" or value.get("status") != "candidate_database_started_admission_closed" or value.get("admission_opened") is not False:
        raise CutoverBlocked("receipt is not a successful database cutover")
    return value


def rollback(args: argparse.Namespace) -> dict[str, Any]:
    prior = _load_success_receipt(args.receipt.resolve())
    nonce = args.nonce
    if re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", nonce) is None:
        raise CutoverBlocked("rollback nonce is invalid")
    operation_id = _digest({"operation": "database-rollback", "receipt": prior.get("receipt_sha256"), "nonce": nonce})
    if args.confirmation != f"ROLLBACK_FR06C2_DATABASE:{operation_id}" or args.confirm_production != ROLLBACK_CONFIRMATION:
        raise CutoverBlocked("exact production database rollback confirmation is required")
    _git_descendant_gate(args.root.resolve(), args.merge_sha)
    _evidence(args.evidence.resolve(), args.merge_sha)
    topology = prior.get("topology")
    if not isinstance(topology, dict):
        raise CutoverBlocked("cutover receipt topology is missing")
    legacy = Path(str(prior.get("legacy_source"))).resolve(strict=True)
    candidate = Path(str(prior.get("candidate_source"))).resolve(strict=True)
    lock_fd = _lock()
    _reserve(operation_id, "database-rollback")
    try:
        _stop_candidate_services(topology)
        state = _pg_state_volume(CANDIDATE_VOLUME, subpath="pgdata")
        if state != "shut down":
            raise CutoverBlocked("candidate PostgreSQL did not shut down cleanly")
        _unseal(legacy)
        summary = _stable_copy(args.root.resolve(), candidate, legacy, STATE_ROOT / "manifests" / operation_id / "reverse-delta")
        _start_legacy(topology)
        body = {
            "schema_version": 1,
            "subpart": SUBPART,
            "operation": "database-rollback",
            "operation_id": operation_id,
            "status": "legacy_database_restored_admission_closed",
            "completed_at": _utc(),
            "reverse_manifest": summary,
            "candidate_retained": True,
            "legacy_deleted": False,
            "admission_opened": False,
            "cloudflare_changed": False,
            "production_execution": True,
        }
        path = _write_result(operation_id, body)
        return {"status": body["status"], "operation_id": operation_id, "result": str(path)}
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)



def _validate_candidate_host_ready(root: Path) -> None:
    output = _run([
        "python3",
        str(root / "scripts/security/fr06c2_database_vault_provision.py"),
        "status",
        "--require-host-ready",
    ])
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise CutoverBlocked("database-vault host gate did not return JSON") from exc
    if value.get("validation") != "FR06C2_DATABASE_HOST_READY":
        raise CutoverBlocked("database-vault host gate is not ready")


def _manifest_entries(root: Path, path: Path) -> dict[str, Any]:
    return _manifest_module(root).build_manifest(path)


def guarded_start(args: argparse.Namespace) -> dict[str, Any]:
    prior = _load_success_receipt(args.receipt.resolve())
    nonce = args.nonce
    if re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", nonce) is None:
        raise CutoverBlocked("guarded-start nonce is invalid")
    operation_id = _digest({"operation": "database-guarded-start", "receipt": prior["receipt_sha256"], "nonce": nonce})
    if args.confirmation != f"START_FR06C2_DATABASE:{operation_id}" or args.confirm_production != START_CONFIRMATION:
        raise CutoverBlocked("exact production database guarded-start confirmation is required")
    root = args.root.resolve()
    if os.geteuid() != 0 or root != PRODUCTION_ROOT:
        raise CutoverBlocked("production guarded-start requires root and /opt/AIOS")
    _git_descendant_gate(root, str(prior.get("merge_sha", "")))
    _validate_candidate_host_ready(root)
    topology = prior.get("topology")
    if not isinstance(topology, dict):
        raise CutoverBlocked("cutover receipt topology is missing")
    legacy = Path(str(prior.get("legacy_source"))).resolve(strict=True)
    candidate = Path(str(prior.get("candidate_source"))).resolve(strict=True)
    if _containers(POSTGRES_SERVICE, running_only=True):
        raise CutoverBlocked("guarded-start requires PostgreSQL stopped")
    for service in topology.get("active_clients", {}):
        if _containers(str(service), running_only=True):
            raise CutoverBlocked("guarded-start requires database clients stopped")
    lock_fd = _lock()
    _reserve(operation_id, "database-guarded-start")
    candidate_started = False
    resealed = False
    try:
        legacy_manifest = _manifest_entries(root, legacy)
        candidate_manifest = _manifest_entries(root, candidate)
        if legacy_manifest.get("entries") != candidate_manifest.get("entries"):
            raise CutoverBlocked("legacy/candidate PGDATA drifted before guarded-start")
        if not _sealed(legacy):
            _seal(legacy)
            resealed = True
        _start_postgres(CANDIDATE_COMPOSE)
        candidate_started = True
        rows = _containers(POSTGRES_SERVICE, running_only=True)
        if len(rows) != 1:
            raise CutoverBlocked("candidate PostgreSQL did not return at exact scale")
        accepted = _postgres_probe(rows[0]["id"])
        expected = (prior.get("database_acceptance") or {}).get("candidate")
        if accepted != expected:
            raise CutoverBlocked("candidate PostgreSQL acceptance drifted after restart")
        _run_reconciler(CANDIDATE_COMPOSE)
        _start_clients(CANDIDATE_COMPOSE, topology)
        if not _candidate_topology_matches(topology):
            raise CutoverBlocked("candidate database-client topology differs after guarded-start")
        if not _sealed(legacy):
            raise CutoverBlocked("legacy PGDATA seal drifted after guarded-start")
        body = {
            "schema_version": 1,
            "subpart": "FR-06C2D",
            "operation": "database-guarded-start",
            "operation_id": operation_id,
            "status": "candidate_database_started_admission_closed",
            "completed_at": _utc(),
            "source_cutover_receipt": prior["receipt_sha256"],
            "database_acceptance": accepted,
            "legacy_resealed": resealed,
            "legacy_read_only": True,
            "admission_opened": False,
            "cloudflare_changed": False,
            "production_execution": True,
        }
        path = _write_result(operation_id, body)
        return {"status": body["status"], "operation_id": operation_id, "result": str(path), "admission_opened": False}
    except Exception as original:
        try:
            _automatic_rollback(root, topology, candidate_started=candidate_started, legacy=legacy, candidate=candidate, evidence_dir=STATE_ROOT / "manifests" / operation_id / "automatic-rollback")
        except Exception as rollback_error:
            raise CutoverError("database guarded-start failed and automatic rollback also failed; admission must remain closed") from rollback_error
        raise CutoverError("database guarded-start failed; automatic rollback passed and admission remains closed") from original
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect-runtime")
    inspect.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    plan = sub.add_parser("plan-cutover")
    plan.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    plan.add_argument("--merge-sha", required=True)
    plan.add_argument("--evidence", type=Path, required=True)
    plan.add_argument("--ttl-seconds", type=int, default=600)
    apply = sub.add_parser("apply-cutover")
    apply.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    apply.add_argument("--merge-sha", required=True)
    apply.add_argument("--evidence", type=Path, required=True)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--confirmation", required=True)
    apply.add_argument("--confirm-production", default="")
    start = sub.add_parser("guarded-start")
    start.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    start.add_argument("--receipt", type=Path, required=True)
    start.add_argument("--nonce", required=True)
    start.add_argument("--confirmation", required=True)
    start.add_argument("--confirm-production", default="")
    rb = sub.add_parser("rollback")
    rb.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    rb.add_argument("--merge-sha", required=True)
    rb.add_argument("--evidence", type=Path, required=True)
    rb.add_argument("--receipt", type=Path, required=True)
    rb.add_argument("--nonce", required=True)
    rb.add_argument("--confirmation", required=True)
    rb.add_argument("--confirm-production", default="")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "inspect-runtime":
            result = inspect_runtime(args.root.resolve())
        elif args.command == "plan-cutover":
            result = create_plan(args)
        elif args.command == "apply-cutover":
            result = apply_cutover(args)
        elif args.command == "guarded-start":
            result = guarded_start(args)
        else:
            result = rollback(args)
    except CutoverBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    except (CutoverError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
