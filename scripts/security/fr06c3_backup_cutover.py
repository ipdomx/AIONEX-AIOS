#!/usr/bin/env python3
"""Guarded FR-06C3 local-backup production cutover executor.

Moves only backup_data after the writer is stopped. Redis/logs are outside this
executor. The candidate local-backup vault must already be provisioned and have
external header/recovery custody evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
from typing import Any

SCHEMA_VERSION = 1
SUBPART = "FR-06C3D"
PRODUCTION_ROOT = Path("/opt/AIOS")
DASHBOARD = PRODUCTION_ROOT / "web-dashboard"
PRODUCTION_ENV = DASHBOARD / ".env.production"
STATE_ROOT = Path("/var/lib/aionex/fr06c3-backup-cutover")
C3_STATE = Path("/var/lib/aionex/fr06c3")
LEGACY_VOLUME = "web-dashboard_backup_data"
CANDIDATE_VOLUME = "aionex-fr06-local-backup-vault"
CANDIDATE_SOURCE = Path("/mnt/aionex/fr06-local-backup-vault/backups")
TARGET = "/var/lib/aionex/backups"
SERVICES = ("backup-worker", "backend")
MAX_EVIDENCE_AGE_SECONDS = 3600
MAX_PLAN_TTL_SECONDS = 900
MAX_WINDOW_SECONDS = 4 * 60 * 60
CUTOVER_CONFIRMATION = "FR06C3_PRODUCTION_BACKUP_CUTOVER"
ROLLBACK_CONFIRMATION = "FR06C3_PRODUCTION_BACKUP_ROLLBACK"
SENSITIVE_KEYS = {"key", "private_key", "recovery_key", "secret", "secret_key", "token", "passphrase", "password"}
ACCEPTED_COMPOSE = [
    DASHBOARD / "docker-compose.production.yml",
    DASHBOARD / "docker-compose.fr06-assets.yml",
    DASHBOARD / "docker-compose.fr06-admission.yml",
    DASHBOARD / "docker-compose.fr06-database.yml",
    DASHBOARD / "docker-compose.fr06-database-admission.yml",
]
CANDIDATE_COMPOSE = [*ACCEPTED_COMPOSE, DASHBOARD / "docker-compose.fr06-backup.yml"]


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


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 180) -> str:
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
        raise CutoverError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CutoverError("JSON object required")
    return value


def _private_regular(path: Path, label: str, maximum: int = 8 * 1024 * 1024) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CutoverBlocked(f"{label} unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise CutoverBlocked(f"{label} must be a single-link regular file")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077 or not 1 <= info.st_size <= maximum:
        raise CutoverBlocked(f"{label} ownership/mode/size unsafe")
    return info


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CutoverBlocked(f"{label} must be RFC3339 UTC Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise CutoverBlocked(f"{label} invalid") from exc


def _walk_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or normalized.endswith("_key_material"):
                raise CutoverBlocked(f"embedded secret material rejected at {path}.{key}")
            _walk_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_sensitive(child, f"{path}[{index}]")


def _git_gate(root: Path, sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if heads != [sha, sha] or _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise CutoverBlocked("production source is not clean exact accepted main")


def _git_descendant_gate(root: Path, sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if len(heads) != 2 or heads[0] != heads[1] or _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise CutoverBlocked("production source is not clean main")
    if subprocess.run(["git", "merge-base", "--is-ancestor", sha, heads[0]], cwd=root, check=False).returncode != 0:
        raise CutoverBlocked("current main is not descendant of cutover source")


def _evidence(path: Path, merge_sha: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    _private_regular(resolved, "cutover evidence")
    value = _json(resolved)
    _walk_sensitive(value)
    if value.get("schema_version") != 1 or value.get("subpart") != SUBPART or value.get("environment") != "production" or value.get("production_authorization") is not True:
        raise CutoverBlocked("cutover evidence metadata invalid")
    now = _utc_now()
    age = (now - _parse_time(value.get("observed_at"), "evidence observed_at")).total_seconds()
    if age < -300 or age > MAX_EVIDENCE_AGE_SECONDS:
        raise CutoverBlocked("cutover evidence stale/future-dated")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("merge_sha") != merge_sha or source.get("protected_pr_checks_passed") is not True or source.get("post_merge_main_checks_passed") is not True:
        raise CutoverBlocked("source CI evidence incomplete")
    recovery = value.get("recovery")
    if not isinstance(recovery, dict):
        raise CutoverBlocked("fresh recovery evidence missing")
    for key, wanted in {"backup_status": "completed", "offsite_status": "completed", "restore_status": "completed", "restore_validated": True, "restore_offsite_validated": True}.items():
        if recovery.get(key) != wanted:
            raise CutoverBlocked(f"fresh recovery gate failed: {key}")
    restore_age = (now - _parse_time(recovery.get("restore_completed_at"), "restore completed_at")).total_seconds()
    if restore_age < -300 or restore_age > MAX_EVIDENCE_AGE_SECONDS:
        raise CutoverBlocked("restore validation stale")
    operations = value.get("operations")
    if not isinstance(operations, dict):
        raise CutoverBlocked("operations preflight missing")
    for key in ("active_backup_jobs", "active_restore_validations", "active_durable_external_jobs"):
        if operations.get(key) != 0:
            raise CutoverBlocked(f"operations not drained: {key}")
    if operations.get("admission_closed") is not True or operations.get("cloudflare_changed") is not False:
        raise CutoverBlocked("admission/Cloudflare preflight unsafe")
    approvals = value.get("approvals")
    if not isinstance(approvals, dict) or approvals.get("owner_authorized") is not True:
        raise CutoverBlocked("owner authorization missing")
    start = _parse_time(approvals.get("window_starts_at"), "window start")
    end = _parse_time(approvals.get("window_ends_at"), "window end")
    if end <= start or (end - start).total_seconds() > MAX_WINDOW_SECONDS or not start <= now <= end:
        raise CutoverBlocked("maintenance window invalid/inactive")
    return value


def _compose(files: list[Path], args: list[str], timeout: int = 300) -> str:
    command = ["docker", "compose", "--env-file", str(PRODUCTION_ENV), "--profile", "*"]
    for path in files:
        command += ["-f", str(path)]
    command += args
    env = os.environ.copy(); env["AIOS_ENV_FILE"] = str(PRODUCTION_ENV)
    result = subprocess.run(command, cwd=DASHBOARD, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise CutoverError(f"docker compose failed with exit code {result.returncode}; output withheld")
    return result.stdout.strip()


def _containers(service: str, running_only: bool = True) -> list[dict[str, Any]]:
    cmd = ["docker", "ps"] if running_only else ["docker", "ps", "-a"]
    cmd += ["--filter", "label=com.docker.compose.project=web-dashboard", "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.ID}}"]
    rows: list[dict[str, Any]] = []
    for cid in [x for x in _run(cmd).splitlines() if x.strip()]:
        item = json.loads(_run(["docker", "inspect", cid]))[0]
        state = item.get("State") or {}
        rows.append({"id": cid, "name": str(item.get("Name", "")).lstrip("/"), "image": str(item.get("Image", "")), "health": str((state.get("Health") or {}).get("Status", "none")), "running": bool(state.get("Running"))})
    return sorted(rows, key=lambda row: row["name"])


def _topology() -> dict[str, Any]:
    active: dict[str, list[str]] = {}
    for service in SERVICES:
        rows = _containers(service)
        if not rows:
            raise CutoverBlocked(f"required backup service is not running: {service}")
        if any(row["health"] not in {"healthy", "none"} for row in rows):
            raise CutoverBlocked(f"backup service is not healthy: {service}")
        active[service] = [row["id"] for row in rows]
    return {"active_services": active, "active_container_count": sum(len(v) for v in active.values())}


def _validate_c3_state(root: Path) -> None:
    for path, label in (
        (C3_STATE / "provision-receipt.json", "C3 provision receipt"),
        (C3_STATE / "recovery-proof.json", "C3 recovery proof"),
        (C3_STATE / "header-custody.json", "C3 header custody"),
    ):
        _private_regular(path, label)
    p = _json(C3_STATE / "provision-receipt.json")
    r = _json(C3_STATE / "recovery-proof.json")
    h = _json(C3_STATE / "header-custody.json")
    if p.get("status") != "empty_c3_vaults_provisioned_admission_closed" or p.get("production_backup_data_read_or_copied") is not False:
        raise CutoverBlocked("C3 provision receipt unacceptable")
    if r.get("status") != "independent_c3_recovery_keys_proved" or len(r.get("checks") or []) != 2:
        raise CutoverBlocked("C3 recovery proof unacceptable")
    if h.get("status") != "off_host_headers_verified" or h.get("object_count") != 2 or h.get("full_readback_verified") is not True or h.get("references_distinct") is not True:
        raise CutoverBlocked("C3 header custody unacceptable")
    output = _run(["python3", str(root / "scripts/security/fr06c3_vault_provision.py"), "status", "--require-ready"])
    status = json.loads(output)
    if status.get("validation") != "FR06C3_EMPTY_VAULTS_READY" or any(int(row.get("running_consumer_count", -1)) for row in status.get("vaults", [])):
        raise CutoverBlocked("C3 candidate vaults are not empty and ready")


def _volume_source(name: str) -> Path:
    value = json.loads(_run(["docker", "volume", "inspect", name]))
    if not isinstance(value, list) or len(value) != 1:
        raise CutoverBlocked(f"volume unavailable: {name}")
    path = Path(str(value[0].get("Mountpoint", ""))).resolve(strict=True)
    if not path.is_dir() or path.is_symlink():
        raise CutoverBlocked(f"volume path unsafe: {name}")
    return path


def _manifest_module(root: Path):
    path = root / "scripts/security/fr06b_asset_copy_manifest.py"
    spec = importlib.util.spec_from_file_location(f"fr06c3_backup_manifest_{secrets.token_hex(4)}", path)
    if spec is None or spec.loader is None:
        raise CutoverError("cannot load safe manifest helper")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _store(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"); os.fsync(fd)
    finally: os.close(fd)


def _summary(value: dict[str, Any]) -> dict[str, Any]:
    s = value["summary"]
    return {"directories": int(s["directories"]), "regular_files": int(s["regular_files"]), "payload_bytes": int(s["payload_bytes"]), "aggregate_sha256": str(s["aggregate_sha256"])}


def _stable_copy(root: Path, source: Path, target: Path, evidence_dir: Path) -> dict[str, Any]:
    manifest = _manifest_module(root)
    evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    before = manifest.build_manifest(source); _store(evidence_dir / "source-before.json", before)
    _run(["rsync", "-aHAX", "--numeric-ids", "--delete", "--safe-links", "--no-devices", "--no-specials", "--", f"{source}/", f"{target}/"], timeout=3600)
    os.sync()
    after = manifest.build_manifest(source); candidate = manifest.build_manifest(target)
    _store(evidence_dir / "source-after.json", after); _store(evidence_dir / "target.json", candidate)
    if before.get("entries") != after.get("entries"):
        raise CutoverBlocked("backup source changed during offline copy")
    if after.get("entries") != candidate.get("entries"):
        raise CutoverBlocked("backup source/candidate manifest mismatch")
    return _summary(candidate)


def _sealed(path: Path) -> bool:
    result = subprocess.run(["findmnt", "-n", "-o", "OPTIONS", "--target", str(path)], capture_output=True, text=True, check=False)
    return result.returncode == 0 and "ro" in set(result.stdout.strip().split(","))


def _seal(path: Path) -> None:
    if _sealed(path): return
    _run(["mount", "--bind", str(path), str(path)])
    _run(["mount", "-o", "remount,bind,ro,nodev,nosuid,noexec", str(path)])
    if not _sealed(path): raise CutoverBlocked("legacy backup_data read-only seal failed")


def _unseal(path: Path) -> None:
    if _sealed(path): _run(["umount", str(path)])


def _stop_ids(ids: list[str]) -> None:
    if ids: _run(["docker", "stop", "-t", "60", *ids], timeout=120)


def _wait(service: str, expected: int) -> None:
    deadline = time.time() + 180
    while time.time() < deadline:
        rows = _containers(service)
        if len(rows) == expected and all(r["health"] not in {"starting", "unhealthy"} for r in rows): return
        time.sleep(2)
    raise CutoverBlocked(f"service did not return healthy at exact scale: {service}")


def _start(files: list[Path], topology: dict[str, Any]) -> None:
    for service in ("backend", "backup-worker"):
        count = len(topology["active_services"][service])
        args = ["up", "-d", "--no-deps", "--force-recreate"]
        if count > 1: args += ["--scale", f"{service}={count}"]
        args += [service]
        _compose(files, args)
    for service in ("backend", "backup-worker"): _wait(service, len(topology["active_services"][service]))


def _stop_candidate() -> None:
    _compose(CANDIDATE_COMPOSE, ["stop", "-t", "60", "backup-worker", "backend"], timeout=180)


def _mount_is_candidate(service: str) -> bool:
    rows = _containers(service)
    if not rows: return False
    for row in rows:
        item = json.loads(_run(["docker", "inspect", row["id"]]))[0]
        matches = [m for m in item.get("Mounts", []) if m.get("Destination") == TARGET]
        if len(matches) != 1 or matches[0].get("Name") != CANDIDATE_VOLUME:
            return False
    return True


def _lock() -> int:
    STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(STATE_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc: os.close(fd); raise CutoverBlocked("another backup cutover holds the lock") from exc
    return fd


def _reserve(operation_id: str, kind: str) -> None:
    _store(STATE_ROOT / "reservations" / f"{operation_id}.json", {"operation_id": operation_id, "kind": kind, "reserved_at": _utc()})


def _write_result(operation_id: str, body: dict[str, Any]) -> Path:
    result = dict(body); result["receipt_sha256"] = _digest(body)
    path = STATE_ROOT / "results" / f"{operation_id}.json"; _store(path, result); return path


def _preflight(root: Path, evidence_path: Path, merge_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if os.geteuid() != 0 or root.resolve() != PRODUCTION_ROOT:
        raise CutoverBlocked("production cutover requires root and /opt/AIOS")
    for path in [PRODUCTION_ENV, *ACCEPTED_COMPOSE, *CANDIDATE_COMPOSE]:
        if not path.is_file(): raise CutoverBlocked(f"required Compose source missing: {path.name}")
    _git_gate(root.resolve(), merge_sha); evidence = _evidence(evidence_path.resolve(), merge_sha); _validate_c3_state(root.resolve())
    legacy = _volume_source(LEGACY_VOLUME); candidate = CANDIDATE_SOURCE.resolve(strict=True)
    if not candidate.is_dir() or candidate.is_symlink() or any(candidate.iterdir()):
        raise CutoverBlocked("candidate backup subpath must be empty before first cutover")
    consumers = [x for x in _run(["docker", "ps", "--filter", f"volume={LEGACY_VOLUME}", "--format", "{{.ID}}"]).splitlines() if x]
    topology = _topology(); planned = {cid for ids in topology["active_services"].values() for cid in ids}
    if set(consumers) != planned:
        raise CutoverBlocked("legacy backup_data consumer topology drifted")
    return evidence, {"topology": topology, "legacy_source": str(legacy), "candidate_source": str(candidate)}


def inspect_runtime(root: Path) -> dict[str, Any]:
    legacy = _volume_source(LEGACY_VOLUME); topology = _topology()
    return {"schema_version": 1, "subpart": SUBPART, "observed_at": _utc(), **topology, "legacy_source": str(legacy), "candidate_source": str(CANDIDATE_SOURCE), "read_only_inspection": True, "production_changed": False}


def create_plan(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.ttl_seconds <= MAX_PLAN_TTL_SECONDS: raise CutoverBlocked("plan TTL outside bounded range")
    _, runtime = _preflight(args.root.resolve(), args.evidence.resolve(), args.merge_sha)
    now = _utc_now(); body = {"schema_version": 1, "subpart": SUBPART, "operation": "backup-cutover", "created_at": _utc(now), "expires_at": _utc(now + timedelta(seconds=args.ttl_seconds)), "nonce": secrets.token_hex(32), "merge_sha": args.merge_sha, "evidence_sha256": _file_digest(args.evidence.resolve()), **runtime, "admission_will_remain_closed": True, "cloudflare_change_permitted": False, "legacy_deletion_permitted": False}
    body["plan_id"] = _digest(body); path = STATE_ROOT / "plans" / f"{body['plan_id']}.json"; _store(path, body)
    return {"decision": "backup_cutover_plan_ready", "plan_id": body["plan_id"], "plan": str(path), "expires_at": body["expires_at"], "production_executed": False}


def _load_plan(path: Path, evidence: Path) -> dict[str, Any]:
    _private_regular(path, "cutover plan"); value = _json(path); plan_id = value.get("plan_id")
    if not isinstance(plan_id, str) or _digest({k:v for k,v in value.items() if k != "plan_id"}) != plan_id: raise CutoverBlocked("plan digest mismatch")
    if value.get("subpart") != SUBPART or value.get("operation") != "backup-cutover": raise CutoverBlocked("plan scope invalid")
    if _utc_now() > _parse_time(value.get("expires_at"), "plan expiry"): raise CutoverBlocked("plan expired")
    if value.get("evidence_sha256") != _file_digest(evidence.resolve()): raise CutoverBlocked("evidence changed after planning")
    return value


def _automatic_rollback(root: Path, topology: dict[str, Any], legacy: Path, candidate: Path, candidate_started: bool, evidence_dir: Path) -> None:
    try: _stop_candidate()
    except Exception: pass
    if candidate_started:
        _unseal(legacy); _stable_copy(root, candidate, legacy, evidence_dir / "reverse-delta")
    else:
        _unseal(legacy)
    _start(ACCEPTED_COMPOSE, topology)


def apply_cutover(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load_plan(args.plan.resolve(), args.evidence.resolve())
    if args.confirmation != f"EXECUTE_FR06C3_BACKUP_CUTOVER:{plan['plan_id']}" or args.confirm_production != CUTOVER_CONFIRMATION: raise CutoverBlocked("exact backup cutover confirmation required")
    evidence, runtime = _preflight(args.root.resolve(), args.evidence.resolve(), args.merge_sha)
    if plan.get("merge_sha") != args.merge_sha or plan.get("topology") != runtime["topology"] or plan.get("legacy_source") != runtime["legacy_source"] or plan.get("candidate_source") != runtime["candidate_source"]: raise CutoverBlocked("topology changed after planning")
    operation_id = plan["plan_id"]
    if (STATE_ROOT / "reservations" / f"{operation_id}.json").exists(): raise CutoverBlocked("plan already consumed")
    topology = runtime["topology"]; legacy = Path(runtime["legacy_source"]); candidate = Path(runtime["candidate_source"])
    fd = _lock(); _reserve(operation_id, "backup-cutover"); candidate_started = False; evidence_dir = STATE_ROOT / "manifests" / operation_id
    try:
        _stop_ids(topology["active_services"]["backup-worker"]); _stop_ids(topology["active_services"]["backend"])
        if _run(["docker", "ps", "--filter", f"volume={LEGACY_VOLUME}", "--format", "{{.ID}}"]).strip(): raise CutoverBlocked("legacy backup_data consumer remained running")
        operations = evidence["operations"]
        if any(int(operations[k]) != 0 for k in ("active_backup_jobs", "active_restore_validations", "active_durable_external_jobs")): raise CutoverBlocked("durable work is not drained")
        _seal(legacy); final_manifest = _stable_copy(args.root.resolve(), legacy, candidate, evidence_dir / "forward-delta")
        _start(CANDIDATE_COMPOSE, topology); candidate_started = True
        if not _mount_is_candidate("backend") or not _mount_is_candidate("backup-worker"): raise CutoverBlocked("candidate backup mount acceptance failed")
        if not _sealed(legacy): raise CutoverBlocked("legacy backup source seal drifted")
        body = {"schema_version": 1, "subpart": SUBPART, "operation": "backup-cutover", "operation_id": operation_id, "status": "candidate_backup_started_admission_closed", "completed_at": _utc(), "merge_sha": args.merge_sha, "topology": topology, "final_manifest": final_manifest, "legacy_source": str(legacy), "candidate_source": str(candidate), "legacy_read_only": True, "legacy_deleted": False, "candidate_services_started": True, "admission_opened": False, "cloudflare_changed": False, "production_execution": True, "parent_fr06_completed": False}
        path = _write_result(operation_id, body); return {"status": body["status"], "operation_id": operation_id, "result": str(path), "admission_opened": False}
    except Exception as original:
        try: _automatic_rollback(args.root.resolve(), topology, legacy, candidate, candidate_started, evidence_dir / "automatic-rollback")
        except Exception as rb: raise CutoverError("backup cutover failed and automatic rollback failed; admission remains closed") from rb
        raise CutoverError("backup cutover failed; automatic rollback passed and admission remains closed") from original
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)


def _success(path: Path) -> dict[str, Any]:
    _private_regular(path, "cutover receipt"); value = _json(path); sha = value.get("receipt_sha256"); body = {k:v for k,v in value.items() if k != "receipt_sha256"}
    if not isinstance(sha,str) or sha != _digest(body) or value.get("status") != "candidate_backup_started_admission_closed" or value.get("admission_opened") is not False: raise CutoverBlocked("invalid successful cutover receipt")
    return value


def rollback(args: argparse.Namespace) -> dict[str, Any]:
    prior = _success(args.receipt.resolve()); nonce = args.nonce
    if re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", nonce) is None: raise CutoverBlocked("rollback nonce invalid")
    op = _digest({"operation":"backup-rollback","receipt":prior["receipt_sha256"],"nonce":nonce})
    if args.confirmation != f"ROLLBACK_FR06C3_BACKUP:{op}" or args.confirm_production != ROLLBACK_CONFIRMATION: raise CutoverBlocked("exact backup rollback confirmation required")
    _git_descendant_gate(args.root.resolve(), str(prior.get("merge_sha")))
    topology = prior["topology"]; legacy = Path(prior["legacy_source"]).resolve(strict=True); candidate = Path(prior["candidate_source"]).resolve(strict=True)
    fd = _lock(); _reserve(op,"backup-rollback")
    try:
        _stop_candidate(); _unseal(legacy); summary = _stable_copy(args.root.resolve(), candidate, legacy, STATE_ROOT / "manifests" / op / "reverse-delta"); _start(ACCEPTED_COMPOSE, topology)
        body={"schema_version":1,"subpart":SUBPART,"operation":"backup-rollback","operation_id":op,"status":"legacy_backup_restored_admission_closed","completed_at":_utc(),"reverse_manifest":summary,"candidate_retained":True,"legacy_deleted":False,"admission_opened":False,"cloudflare_changed":False,"production_execution":True}; path=_write_result(op,body); return {"status":body["status"],"operation_id":op,"result":str(path)}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True)
    inspect=sub.add_parser("inspect-runtime"); inspect.add_argument("--root",type=Path,default=PRODUCTION_ROOT)
    plan=sub.add_parser("plan-cutover"); plan.add_argument("--root",type=Path,default=PRODUCTION_ROOT); plan.add_argument("--merge-sha",required=True); plan.add_argument("--evidence",type=Path,required=True); plan.add_argument("--ttl-seconds",type=int,default=600)
    apply=sub.add_parser("apply-cutover"); apply.add_argument("--root",type=Path,default=PRODUCTION_ROOT); apply.add_argument("--merge-sha",required=True); apply.add_argument("--evidence",type=Path,required=True); apply.add_argument("--plan",type=Path,required=True); apply.add_argument("--confirmation",required=True); apply.add_argument("--confirm-production",default="")
    rb=sub.add_parser("rollback"); rb.add_argument("--root",type=Path,default=PRODUCTION_ROOT); rb.add_argument("--receipt",type=Path,required=True); rb.add_argument("--nonce",required=True); rb.add_argument("--confirmation",required=True); rb.add_argument("--confirm-production",default="")
    return p


def main() -> int:
    args=parser().parse_args()
    try:
        if args.command=="inspect-runtime": result=inspect_runtime(args.root.resolve())
        elif args.command=="plan-cutover": result=create_plan(args)
        elif args.command=="apply-cutover": result=apply_cutover(args)
        else: result=rollback(args)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
    except CutoverBlocked as exc:
        print(json.dumps({"status":"blocked","reason":str(exc)},ensure_ascii=False,sort_keys=True)); return 2
    except CutoverError as exc:
        print(json.dumps({"status":"error","reason":str(exc)},ensure_ascii=False,sort_keys=True)); return 1


if __name__ == "__main__": raise SystemExit(main())
