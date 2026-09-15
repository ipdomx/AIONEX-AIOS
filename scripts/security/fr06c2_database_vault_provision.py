#!/usr/bin/env python3
"""Guarded FR-06C2B production database-vault provisioning.

This executor only provisions and proves recovery of an EMPTY database vault.
It never copies PGDATA or stops/starts PostgreSQL or database clients.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
from typing import Any

SCHEMA_VERSION = 1
SUBPART = "FR-06C2B"
PRODUCTION_ROOT = Path("/opt/AIOS")
STATE_ROOT = Path("/var/lib/aionex/fr06c2")
RUNTIME_ROOT = Path("/run/aionex-fr06c2")
KEY_ROOT = Path("/dev/shm/aionex-fr06c2-keys")
IMAGE_ROOT = Path("/var/lib/aionex/fr06-vaults")
IMAGE = IMAGE_ROOT / "database-vault.luks2"
IMAGE_BYTES = 16 * 1024**3
MAPPER_NAME = "aionex-database-vault"
MAPPER = Path("/dev/mapper") / MAPPER_NAME
MOUNT_ROOT = Path("/mnt/aionex/fr06-database-vault")
SUBPATH = "pgdata"
DOCKER_VOLUME = "aionex-fr06-database-vault"
LEGACY_VOLUME = "web-dashboard_postgres_data"
FS_LABEL = "AIONEX06_DB"
MOUNT_OPTIONS = ("nodev", "nosuid", "noexec")
HEADER_NAME = "aionex-database-vault.header"
MAX_PLAN_TTL_SECONDS = 900
MAX_EVIDENCE_AGE_SECONDS = 3600
MAX_WINDOW_SECONDS = 4 * 60 * 60
PRODUCTION_CONFIRMATION = "PROVISION_FR06C2_DATABASE_VAULT"
UNLOCK_CONFIRMATION = "UNLOCK_FR06C2_DATABASE_VAULT"
SAFE_PLAN_RE = re.compile(r"^plan-[0-9A-Za-z._-]+\.json$")
SENSITIVE_KEYS = {"key", "private_key", "recovery_key", "secret", "secret_key", "token", "passphrase", "password"}


class ProvisionError(RuntimeError):
    pass


class ProvisionBlocked(ProvisionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
    finally:
        os.close(descriptor)
    return h.hexdigest()


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 90) -> str:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProvisionError(f"command unavailable or timed out: {argv[0]}") from exc
    if result.returncode != 0:
        raise ProvisionError(f"{argv[0]} failed with exit code {result.returncode}; output withheld")
    return result.stdout.strip()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvisionError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ProvisionError("JSON object required")
    return value


def _private_regular(path: Path, label: str, *, maximum: int = 1024 * 1024) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ProvisionBlocked(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProvisionBlocked(f"{label} must be a single-link regular file")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077 or not 1 <= info.st_size <= maximum:
        raise ProvisionBlocked(f"{label} ownership, mode, or size is unsafe")
    return info


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProvisionBlocked(f"{label} must be RFC3339 UTC Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProvisionBlocked(f"{label} is invalid") from exc
    return parsed.astimezone(timezone.utc)


def _walk_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or normalized.endswith("_key_material"):
                raise ProvisionBlocked(f"embedded secret material field rejected at {path}.{key}")
            _walk_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_sensitive(child, f"{path}[{index}]")


def _git_gate(root: Path, expected_sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if heads != [expected_sha, expected_sha]:
        raise ProvisionBlocked("checkout and origin/main do not match the accepted merge SHA")
    if _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise ProvisionBlocked("production source tree is not clean")


def _evidence(path: Path, merge_sha: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    _private_regular(resolved, "recovery evidence")
    value = _json(resolved)
    _walk_sensitive(value)
    if value.get("schema_version") != 1 or value.get("subpart") != SUBPART or value.get("environment") != "production":
        raise ProvisionBlocked("recovery evidence metadata is invalid")
    if value.get("production_authorization") is not True:
        raise ProvisionBlocked("recovery evidence lacks production authorization")
    now = _utc_now()
    observed = _parse_time(value.get("observed_at"), "evidence observed_at")
    age = (now - observed).total_seconds()
    if age < -300 or age > MAX_EVIDENCE_AGE_SECONDS:
        raise ProvisionBlocked("recovery evidence is stale or future-dated")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("merge_sha") != merge_sha or source.get("protected_pr_checks_passed") is not True or source.get("post_merge_main_checks_passed") is not True:
        raise ProvisionBlocked("source recovery gate is incomplete")
    recovery = value.get("recovery")
    if not isinstance(recovery, dict):
        raise ProvisionBlocked("recovery evidence is missing")
    required = {
        "backup_status": "completed",
        "offsite_status": "completed",
        "restore_status": "completed",
        "restore_validated": True,
        "restore_offsite_validated": True,
    }
    for key, wanted in required.items():
        if recovery.get(key) != wanted:
            raise ProvisionBlocked(f"recovery evidence failed: {key}")
    if not isinstance(recovery.get("backup_id"), str) or not recovery["backup_id"] or not isinstance(recovery.get("restore_run_id"), str) or not recovery["restore_run_id"]:
        raise ProvisionBlocked("recovery identifiers are missing")
    restore_time = _parse_time(recovery.get("restore_completed_at"), "restore completed_at")
    restore_age = (now - restore_time).total_seconds()
    if restore_age < -300 or restore_age > MAX_EVIDENCE_AGE_SECONDS:
        raise ProvisionBlocked("restore validation is stale")
    approvals = value.get("approvals")
    if not isinstance(approvals, dict) or approvals.get("owner_authorized") is not True:
        raise ProvisionBlocked("owner authorization is missing")
    start = _parse_time(approvals.get("window_starts_at"), "window start")
    end = _parse_time(approvals.get("window_ends_at"), "window end")
    if end <= start or (end - start).total_seconds() > MAX_WINDOW_SECONDS or not start <= now <= end:
        raise ProvisionBlocked("maintenance window is invalid or inactive")
    for key in ("active_key_ref", "recovery_key_ref"):
        ref = approvals.get(key)
        if not isinstance(ref, str) or "://" not in ref or ref.startswith(("file://", "path://")):
            raise ProvisionBlocked(f"external custody reference is invalid: {key}")
    if approvals["active_key_ref"] == approvals["recovery_key_ref"]:
        raise ProvisionBlocked("active and recovery custody references must be distinct")
    return value


def _bundle(path: Path, purpose: str) -> tuple[bytes, str]:
    resolved = path.resolve(strict=True)
    if resolved.parent != KEY_ROOT or not str(resolved).startswith(str(KEY_ROOT) + "/"):
        raise ProvisionBlocked(f"{purpose} bundle must be directly under the fixed tmpfs key root")
    _private_regular(resolved, f"{purpose} bundle", maximum=64 * 1024)
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", str(resolved)]) != "tmpfs":
        raise ProvisionBlocked(f"{purpose} bundle is not on tmpfs")
    value = _json(resolved)
    if set(value) != {"schema_version", "purpose", "database_vault"} or value.get("schema_version") != 1 or value.get("purpose") != purpose:
        raise ProvisionBlocked(f"{purpose} bundle fields are invalid")
    raw = value.get("database_vault")
    if not isinstance(raw, str) or len(raw) != 128:
        raise ProvisionBlocked(f"{purpose} database key length is invalid")
    try:
        decoded = bytes.fromhex(raw)
    except ValueError as exc:
        raise ProvisionBlocked(f"{purpose} database key encoding is invalid") from exc
    if len(decoded) != 64:
        raise ProvisionBlocked(f"{purpose} database key size is invalid")
    return decoded, _file_digest(resolved)


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _legacy_gate() -> dict[str, str]:
    docker_root = Path(_run(["docker", "info", "--format", "{{.DockerRootDir}}"])).resolve()
    value = json.loads(_run(["docker", "volume", "inspect", LEGACY_VOLUME]))
    if not isinstance(value, list) or len(value) != 1:
        raise ProvisionBlocked("legacy PostgreSQL volume is unavailable")
    mountpoint = Path(str(value[0].get("Mountpoint", ""))).resolve(strict=True)
    expected = docker_root / "volumes" / LEGACY_VOLUME / "_data"
    if mountpoint != expected or not mountpoint.is_dir() or mountpoint.is_symlink():
        raise ProvisionBlocked("legacy PostgreSQL volume path drifted")
    return {"volume": LEGACY_VOLUME, "mountpoint": str(mountpoint)}


def _fresh_candidate_absence() -> None:
    if IMAGE.exists() or MAPPER.exists() or os.path.ismount(MOUNT_ROOT):
        raise ProvisionBlocked("database-vault artifacts already exist")
    result = subprocess.run(["docker", "volume", "inspect", DOCKER_VOLUME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode == 0:
        raise ProvisionBlocked("database-vault Docker volume already exists")


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            raise ProvisionError("no existing ancestor for capacity check")
        current = parent
    return current


def _write_exclusive(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        payload = json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def _secret_file(directory: Path, name: str, payload: bytes) -> Path:
    path = directory / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def _verify_luks() -> dict[str, Any]:
    _run(["cryptsetup", "isLuks", "--type", "luks2", str(IMAGE)])
    raw = _run(["cryptsetup", "luksDump", "--dump-json-metadata", str(IMAGE)])
    value = json.loads(raw)
    slots = value.get("keyslots")
    if not isinstance(slots, dict) or len(slots) != 2:
        raise ProvisionBlocked("database-vault must contain exactly two LUKS2 keyslots")
    for slot in slots.values():
        if not isinstance(slot, dict) or slot.get("type") != "luks2" or slot.get("key_size") != 64:
            raise ProvisionBlocked("database-vault keyslot contract drifted")
        kdf = slot.get("kdf") or {}
        area = slot.get("area") or {}
        if kdf.get("type") != "argon2id" or area.get("encryption") != "aes-xts-plain64":
            raise ProvisionBlocked("database-vault LUKS2 crypto contract drifted")
    return {"format": "LUKS2", "cipher": "aes-xts-plain64", "key_bits": 512, "pbkdf": "argon2id", "keyslot_count": 2}


def _mount() -> None:
    MOUNT_ROOT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    MOUNT_ROOT.mkdir(exist_ok=True, mode=0o700)
    info = os.lstat(MOUNT_ROOT)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ProvisionBlocked("database-vault mount root is unsafe")
    _run(["mount", "-o", ",".join(MOUNT_OPTIONS), str(MAPPER), str(MOUNT_ROOT)])


def _verify_host_ready() -> dict[str, Any]:
    if not MAPPER.exists() or not stat.S_ISBLK(os.stat(MAPPER).st_mode):
        raise ProvisionBlocked("database-vault mapper is not active")
    if " is active" not in _run(["cryptsetup", "status", MAPPER_NAME]):
        raise ProvisionBlocked("database-vault cryptsetup status is not active")
    if _run(["blkid", "-o", "value", "-s", "TYPE", str(MAPPER)]) != "ext4":
        raise ProvisionBlocked("database-vault filesystem is not ext4")
    if _run(["blkid", "-o", "value", "-s", "LABEL", str(MAPPER)]) != FS_LABEL:
        raise ProvisionBlocked("database-vault filesystem label drifted")
    line = _run(["findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS", "--target", str(MOUNT_ROOT)])
    pieces = line.split(None, 2)
    if len(pieces) != 3 or os.path.realpath(pieces[0]) != os.path.realpath(MAPPER) or pieces[1] != "ext4":
        raise ProvisionBlocked("database-vault mount source or filesystem drifted")
    options = set(pieces[2].split(","))
    if not set(MOUNT_OPTIONS).issubset(options):
        raise ProvisionBlocked("database-vault mount options drifted")
    pgdata = MOUNT_ROOT / SUBPATH
    info = os.lstat(pgdata)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != 70 or info.st_gid != 70 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProvisionBlocked("database-vault pgdata subpath ownership or mode drifted")
    return {"status": "host-ready", "validation": "FR06C2_DATABASE_HOST_READY", "observed_at": _utc_text(), "mapper": str(MAPPER), "mount_root": str(MOUNT_ROOT), "subpath": SUBPATH}


def _verify_ready(require_zero_consumers: bool = True) -> dict[str, Any]:
    host = _verify_host_ready()
    value = json.loads(_run(["docker", "volume", "inspect", DOCKER_VOLUME]))
    if not isinstance(value, list) or len(value) != 1:
        raise ProvisionBlocked("database-vault Docker volume is unavailable")
    item = value[0]
    if item.get("Driver") != "local":
        raise ProvisionBlocked("database-vault Docker volume driver drifted")
    options = item.get("Options") or {}
    if options.get("type") != "ext4" or os.path.realpath(str(options.get("device", ""))) != os.path.realpath(MAPPER):
        raise ProvisionBlocked("database-vault Docker volume device drifted")
    actual_options = set(str(options.get("o", "")).split(","))
    if actual_options != set(MOUNT_OPTIONS):
        raise ProvisionBlocked("database-vault Docker volume options drifted")
    consumers = _run(["docker", "ps", "--filter", f"volume={DOCKER_VOLUME}", "--format", "{{.ID}}"])
    consumer_count = len([line for line in consumers.splitlines() if line.strip()])
    if require_zero_consumers and consumer_count:
        raise ProvisionBlocked("empty database-vault provisioning requires zero candidate consumers")
    return {**host, "validation": "FR06C2_DATABASE_VAULT_READY", "docker_volume": DOCKER_VOLUME, "running_consumer_count": consumer_count}


def _preflight(args: argparse.Namespace) -> tuple[dict[str, Any], str, str]:
    root = args.root.resolve()
    if os.geteuid() != 0 or root != PRODUCTION_ROOT:
        raise ProvisionBlocked("production database-vault provisioning requires root and /opt/AIOS")
    for command in ("cryptsetup", "mkfs.ext4", "fallocate", "mount", "umount", "docker", "git", "findmnt", "blkid"):
        if shutil.which(command) is None:
            raise ProvisionBlocked(f"required command unavailable: {command}")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]) != "tmpfs" or _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/run"]) != "tmpfs":
        raise ProvisionBlocked("/dev/shm and /run must be tmpfs")
    _git_gate(root, args.merge_sha)
    _evidence(args.evidence.resolve(), args.merge_sha)
    if not _docker_available():
        raise ProvisionBlocked("Docker must be active for pre-cutover empty-vault provisioning")
    legacy = _legacy_gate()
    _fresh_candidate_absence()
    active, active_digest = _bundle(args.active_bundle, "active")
    recovery, recovery_digest = _bundle(args.recovery_bundle, "recovery")
    if active == recovery:
        raise ProvisionBlocked("active and recovery database keys must be independent")
    free = shutil.disk_usage(_existing_ancestor(IMAGE_ROOT.parent)).free
    if free < IMAGE_BYTES + 8 * 1024**3:
        raise ProvisionBlocked("insufficient free space for database-vault plus safety reserve")
    return {"legacy": legacy, "free_bytes": free, "observed_at": _utc_text()}, active_digest, recovery_digest


def create_plan(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.ttl_seconds <= MAX_PLAN_TTL_SECONDS:
        raise ProvisionBlocked("plan TTL is outside the bounded range")
    plan_path = args.plan.resolve()
    if plan_path.parent != RUNTIME_ROOT or SAFE_PLAN_RE.fullmatch(plan_path.name) is None:
        raise ProvisionBlocked("plan must be a plan-*.json file directly under the fixed runtime root")
    inspection, active_digest, recovery_digest = _preflight(args)
    now = _utc_now()
    body = {
        "schema_version": 1,
        "subpart": SUBPART,
        "operation": "provision-empty-database-vault",
        "nonce": secrets.token_hex(32),
        "created_at": _utc_text(now),
        "expires_at": _utc_text(now + timedelta(seconds=args.ttl_seconds)),
        "merge_sha": args.merge_sha,
        "evidence_sha256": _file_digest(args.evidence.resolve()),
        "active_bundle_sha256": active_digest,
        "recovery_bundle_sha256": recovery_digest,
        "legacy_volume": inspection["legacy"]["volume"],
        "image": str(IMAGE),
        "size_bytes": IMAGE_BYTES,
        "mapper": str(MAPPER),
        "mount_root": str(MOUNT_ROOT),
        "target_subpath": SUBPATH,
        "docker_volume": DOCKER_VOLUME,
        "admission_opened": False,
        "services_may_be_stopped_or_restarted": False,
        "production_pgdata_copy_permitted": False,
        "cloudflare_change_permitted": False,
    }
    body["plan_id"] = _digest(body)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_exclusive(plan_path, body)
    return {"status": "planned", "plan": str(plan_path), "plan_id": body["plan_id"], "confirmation": f"PROVISION-{body['plan_id'][:16]}", "production_executed": False}


def _load_plan(path: Path) -> dict[str, Any]:
    _private_regular(path, "plan")
    value = _json(path)
    plan_id = value.get("plan_id")
    body = {k: v for k, v in value.items() if k != "plan_id"}
    if not isinstance(plan_id, str) or _digest(body) != plan_id:
        raise ProvisionBlocked("plan digest is invalid")
    if value.get("subpart") != SUBPART or value.get("operation") != "provision-empty-database-vault":
        raise ProvisionBlocked("plan scope is invalid")
    if _utc_now() > _parse_time(value.get("expires_at"), "plan expiry"):
        raise ProvisionBlocked("plan expired")
    return value


def apply_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load_plan(args.plan.resolve())
    if args.confirmation != f"PROVISION-{plan['plan_id'][:16]}" or args.confirm_production != PRODUCTION_CONFIRMATION:
        raise ProvisionBlocked("production provisioning confirmation is invalid")
    inspection, active_digest, recovery_digest = _preflight(args)
    if plan.get("merge_sha") != args.merge_sha or plan.get("evidence_sha256") != _file_digest(args.evidence.resolve()) or plan.get("active_bundle_sha256") != active_digest or plan.get("recovery_bundle_sha256") != recovery_digest:
        raise ProvisionBlocked("plan-bound evidence or key bundle changed")
    if plan.get("legacy_volume") != inspection["legacy"]["volume"]:
        raise ProvisionBlocked("legacy PostgreSQL volume changed after planning")
    consumed = STATE_ROOT / "consumed" / f"{plan['plan_id']}.json"
    if consumed.exists():
        raise ProvisionBlocked("plan was already consumed")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(RUNTIME_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    created_image = False
    opened = False
    mounted = False
    volume_created = False
    secrets_dir: Path | None = None
    secret_paths: list[Path] = []
    header_path = RUNTIME_ROOT / "headers" / HEADER_NAME
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProvisionBlocked("another FR-06C2 operation holds the lock") from exc
        active, current_active_digest = _bundle(args.active_bundle, "active")
        recovery, current_recovery_digest = _bundle(args.recovery_bundle, "recovery")
        if current_active_digest != active_digest or current_recovery_digest != recovery_digest:
            raise ProvisionBlocked("key bundle changed while applying")
        IMAGE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        _run(["fallocate", "-l", str(IMAGE_BYTES), str(IMAGE)], timeout=300)
        created_image = True
        os.chmod(IMAGE, 0o600)
        KEY_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        secrets_dir = KEY_ROOT / ("apply-" + secrets.token_hex(8))
        secrets_dir.mkdir(mode=0o700)
        active_path = _secret_file(secrets_dir, "database.active", active)
        recovery_path = _secret_file(secrets_dir, "database.recovery", recovery)
        secret_paths += [active_path, recovery_path]
        _run(["cryptsetup", "luksFormat", "--batch-mode", "--type", "luks2", "--cipher", "aes-xts-plain64", "--key-size", "512", "--pbkdf", "argon2id", "--key-file", str(active_path), str(IMAGE)], timeout=300)
        _run(["cryptsetup", "luksAddKey", str(IMAGE), str(recovery_path), "--key-file", str(active_path)], timeout=300)
        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active_path), str(IMAGE), MAPPER_NAME], timeout=180)
        opened = True
        _run(["mkfs.ext4", "-q", "-L", FS_LABEL, str(MAPPER)], timeout=180)
        _mount()
        mounted = True
        pgdata = MOUNT_ROOT / SUBPATH
        pgdata.mkdir(mode=0o700)
        os.chown(pgdata, 70, 70)
        _run(["sync", "-f", str(MOUNT_ROOT)])
        header_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _run(["cryptsetup", "luksHeaderBackup", str(IMAGE), "--header-backup-file", str(header_path)], timeout=120)
        os.chmod(header_path, 0o400)
        _run(["docker", "volume", "create", "--driver", "local", "--opt", "type=ext4", "--opt", f"device={MAPPER}", "--opt", "o=" + ",".join(MOUNT_OPTIONS), DOCKER_VOLUME])
        volume_created = True
        ready = _verify_ready(require_zero_consumers=True)
        crypto = _verify_luks()
        receipt = {
            "schema_version": 1,
            "subpart": SUBPART,
            "status": "empty_database_vault_provisioned_admission_closed",
            "plan_id": plan["plan_id"],
            "merge_sha": args.merge_sha,
            "completed_at": _utc_text(),
            "image": str(IMAGE),
            "size_bytes": IMAGE_BYTES,
            "allocated_bytes": os.stat(IMAGE).st_blocks * 512,
            "mapper": str(MAPPER),
            "mount_root": str(MOUNT_ROOT),
            "target_subpath": SUBPATH,
            "docker_volume": DOCKER_VOLUME,
            "header_staging_path": str(header_path),
            "header_sha256": _file_digest(header_path),
            "header_bytes": os.stat(header_path).st_size,
            "crypto": crypto,
            "ready_validation": ready["validation"],
            "active_bundle_sha256": active_digest,
            "recovery_bundle_sha256": recovery_digest,
            "production_pgdata_read_or_copied": False,
            "production_postgres_stopped": False,
            "database_clients_stopped": False,
            "admission_opened": False,
            "cloudflare_changed": False,
            "docker_gate_installed": False,
            "next_gate": "upload and fully verify the LUKS2 header off-host, then prove recovery-key open and active-key reopen",
        }
        receipt_path = STATE_ROOT / "provision-receipt.json"
        STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_exclusive(receipt_path, receipt)
        _write_exclusive(consumed, {"plan_id": plan["plan_id"], "consumed_at": _utc_text()})
        return {"status": receipt["status"], "receipt": str(receipt_path), "ready": True, "production_pgdata_copied": False}
    except Exception:
        if volume_created:
            subprocess.run(["docker", "volume", "rm", "-f", DOCKER_VOLUME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if mounted:
            subprocess.run(["umount", str(MOUNT_ROOT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if opened:
            subprocess.run(["cryptsetup", "close", MAPPER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            header_path.unlink()
        except OSError:
            pass
        if created_image:
            try:
                IMAGE.unlink()
            except OSError:
                pass
        raise
    finally:
        for path in secret_paths:
            try:
                path.unlink()
            except OSError:
                pass
        if secrets_dir is not None:
            try:
                secrets_dir.rmdir()
            except OSError:
                pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def prove_recovery(args: argparse.Namespace) -> dict[str, Any]:
    receipt_path = STATE_ROOT / "provision-receipt.json"
    _private_regular(receipt_path, "provision receipt")
    receipt = _json(receipt_path)
    if receipt.get("status") != "empty_database_vault_provisioned_admission_closed" or receipt.get("subpart") != SUBPART:
        raise ProvisionBlocked("provision receipt is invalid")
    _git_gate(args.root.resolve(), str(receipt.get("merge_sha")))
    ready = _verify_ready(require_zero_consumers=True)
    active, active_digest = _bundle(args.active_bundle, "active")
    recovery, recovery_digest = _bundle(args.recovery_bundle, "recovery")
    if active_digest != receipt.get("active_bundle_sha256") or recovery_digest != receipt.get("recovery_bundle_sha256") or active == recovery:
        raise ProvisionBlocked("recovery proof key bundles do not match provisioning")
    directory = KEY_ROOT / ("recovery-proof-" + secrets.token_hex(8))
    directory.mkdir(mode=0o700)
    active_path = _secret_file(directory, "database.active", active)
    recovery_path = _secret_file(directory, "database.recovery", recovery)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(RUNTIME_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProvisionBlocked("another FR-06C2 operation holds the lock") from exc
        if ready.get("running_consumer_count") != 0:
            raise ProvisionBlocked("recovery proof requires zero database-vault consumers")
        _run(["umount", str(MOUNT_ROOT)])
        _run(["cryptsetup", "close", MAPPER_NAME])
        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(recovery_path), str(IMAGE), MAPPER_NAME], timeout=180)
        _mount()
        _verify_host_ready()
        _run(["umount", str(MOUNT_ROOT)])
        _run(["cryptsetup", "close", MAPPER_NAME])
        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active_path), str(IMAGE), MAPPER_NAME], timeout=180)
        _mount()
        _verify_ready(require_zero_consumers=True)
        result = {
            "schema_version": 1,
            "subpart": SUBPART,
            "status": "independent_database_recovery_key_proved",
            "observed_at": _utc_text(),
            "recovery_open_passed": True,
            "active_reopen_passed": True,
            "candidate_consumers": 0,
            "production_pgdata_read_or_copied": False,
            "key_material_persisted": False,
            "admission_opened": False,
        }
        out = STATE_ROOT / "recovery-proof.json"
        if out.exists():
            out.unlink()
        _write_exclusive(out, result)
        return {"status": result["status"], "receipt": str(out)}
    finally:
        for path in (active_path, recovery_path):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def unlock(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirmation != UNLOCK_CONFIRMATION:
        raise ProvisionBlocked("unlock confirmation is invalid")
    if os.geteuid() != 0 or _docker_available():
        raise ProvisionBlocked("post-boot database-vault unlock requires root with Docker stopped")
    receipt_path = STATE_ROOT / "provision-receipt.json"
    _private_regular(receipt_path, "provision receipt")
    receipt = _json(receipt_path)
    merge_sha = receipt.get("merge_sha")
    if receipt.get("status") != "empty_database_vault_provisioned_admission_closed" or not isinstance(merge_sha, str):
        raise ProvisionBlocked("provision receipt is invalid")
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=PRODUCTION_ROOT).splitlines()
    if len(heads) != 2 or heads[0] != heads[1] or subprocess.run(["git", "merge-base", "--is-ancestor", merge_sha, heads[0]], cwd=PRODUCTION_ROOT, check=False).returncode != 0:
        raise ProvisionBlocked("current main is not a clean descendant of the provisioned source")
    if _run(["git", "status", "--porcelain=v1"], cwd=PRODUCTION_ROOT):
        raise ProvisionBlocked("production source tree is not clean")
    _private_regular(IMAGE, "database-vault image", maximum=IMAGE_BYTES + 1)
    _verify_luks()
    if MAPPER.exists() or os.path.ismount(MOUNT_ROOT):
        raise ProvisionBlocked("unlock requires database-vault to be fully closed")
    active, active_digest = _bundle(args.active_bundle, "active")
    if active_digest != receipt.get("active_bundle_sha256"):
        raise ProvisionBlocked("active bundle differs from provisioned custody")
    directory = KEY_ROOT / ("unlock-" + secrets.token_hex(8))
    directory.mkdir(mode=0o700)
    key_path = _secret_file(directory, "database.active", active)
    try:
        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(key_path), str(IMAGE), MAPPER_NAME], timeout=180)
        _mount()
        ready = _verify_host_ready()
        result = {
            "schema_version": 1,
            "subpart": SUBPART,
            "status": "database_vault_unlocked_host_ready_docker_stopped",
            "completed_at": _utc_text(),
            "host_validation": ready["validation"],
            "docker_started": False,
            "services_started_or_restarted": False,
            "key_material_persisted": False,
            "admission_opened": False,
        }
        out = STATE_ROOT / "unlock-receipts" / f"unlock-{int(_utc_now().timestamp())}-{secrets.token_hex(6)}.json"
        _write_exclusive(out, result)
        return {"status": result["status"], "receipt": str(out)}
    except Exception:
        if os.path.ismount(MOUNT_ROOT):
            subprocess.run(["umount", str(MOUNT_ROOT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if MAPPER.exists():
            subprocess.run(["cryptsetup", "close", MAPPER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        raise
    finally:
        try:
            key_path.unlink()
        except OSError:
            pass
        try:
            directory.rmdir()
        except OSError:
            pass


def wipe_inputs() -> dict[str, Any]:
    removed: list[str] = []
    for name in ("active-bundle.json", "recovery-bundle.json"):
        path = KEY_ROOT / name
        try:
            info = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_nlink == 1:
            path.unlink()
            removed.append(name)
    return {"status": "tmpfs_inputs_removed", "removed": removed, "key_material_persisted": False}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    def common(cmd: argparse.ArgumentParser) -> None:
        cmd.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
        cmd.add_argument("--merge-sha", required=True)
        cmd.add_argument("--evidence", type=Path, required=True)
        cmd.add_argument("--active-bundle", type=Path, required=True)
        cmd.add_argument("--recovery-bundle", type=Path, required=True)
    plan = sub.add_parser("plan")
    common(plan)
    plan.add_argument("--plan", type=Path, required=True)
    plan.add_argument("--ttl-seconds", type=int, default=600)
    apply = sub.add_parser("apply")
    common(apply)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--confirmation", required=True)
    apply.add_argument("--confirm-production", default="")
    prove = sub.add_parser("prove-recovery")
    prove.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    prove.add_argument("--active-bundle", type=Path, required=True)
    prove.add_argument("--recovery-bundle", type=Path, required=True)
    status = sub.add_parser("status")
    group = status.add_mutually_exclusive_group()
    group.add_argument("--require-ready", action="store_true")
    group.add_argument("--require-host-ready", action="store_true")
    unlock_cmd = sub.add_parser("unlock")
    unlock_cmd.add_argument("--active-bundle", type=Path, required=True)
    unlock_cmd.add_argument("--confirmation", required=True)
    sub.add_parser("wipe-inputs")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "plan":
            result = create_plan(args)
        elif args.command == "apply":
            result = apply_plan(args)
        elif args.command == "prove-recovery":
            result = prove_recovery(args)
        elif args.command == "unlock":
            result = unlock(args)
        elif args.command == "wipe-inputs":
            result = wipe_inputs()
        else:
            result = _verify_ready(require_zero_consumers=True) if args.require_ready else _verify_host_ready()
    except ProvisionBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    except (ProvisionError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
