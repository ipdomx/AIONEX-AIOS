#!/usr/bin/env python3
"""Guarded FR-06C3C2 provisioning for empty local-backup and operations vaults.

This source can create and prove recovery of EMPTY vaults only. It cannot copy
backup_data or redis_data, stop production services, flush Redis, move logs,
or change application admission/Cloudflare.
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
SUBPART = "FR-06C3C2"
PRODUCTION_ROOT = Path("/opt/AIOS")
STATE_ROOT = Path("/var/lib/aionex/fr06c3")
RUNTIME_ROOT = Path("/run/aionex-fr06c3")
KEY_ROOT = Path("/dev/shm/aionex-fr06c3-keys")
IMAGE_ROOT = Path("/var/lib/aionex/fr06-vaults")
MAX_PLAN_TTL_SECONDS = 900
MAX_EVIDENCE_AGE_SECONDS = 3600
MAX_WINDOW_SECONDS = 4 * 60 * 60
PRODUCTION_CONFIRMATION = "PROVISION_FR06C3_EMPTY_VAULTS"
UNLOCK_CONFIRMATION = "UNLOCK_FR06C3_VAULTS"
SAFE_PLAN_RE = re.compile(r"^plan-[0-9A-Za-z._-]+\.json$")
SENSITIVE_KEYS = {"key", "private_key", "recovery_key", "secret", "secret_key", "token", "passphrase", "password"}

VAULTS: tuple[dict[str, Any], ...] = (
    {
        "role": "local-backup-vault",
        "bundle_field": "local_backup_vault",
        "image": IMAGE_ROOT / "local-backup-vault.luks2",
        "size_bytes": 16 * 1024**3,
        "mapper_name": "aionex-local-backup-vault",
        "mapper": Path("/dev/mapper/aionex-local-backup-vault"),
        "mount_root": Path("/mnt/aionex/fr06-local-backup-vault"),
        "subpath": "backups",
        "volume": "aionex-fr06-local-backup-vault",
        "label": "AIOS06_BACKUP",
        "owner": (0, 0),
        "mode": 0o700,
        "legacy_volume": "web-dashboard_backup_data",
    },
    {
        "role": "operations-vault",
        "bundle_field": "operations_vault",
        "image": IMAGE_ROOT / "operations-vault.luks2",
        "size_bytes": 8 * 1024**3,
        "mapper_name": "aionex-operations-vault",
        "mapper": Path("/dev/mapper/aionex-operations-vault"),
        "mount_root": Path("/mnt/aionex/fr06-operations-vault"),
        "subpath": "redis",
        "volume": "aionex-fr06-operations-vault",
        "label": "AIOS06_OPS",
        "owner": (999, 1000),
        "mode": 0o700,
        "legacy_volume": "web-dashboard_redis_data",
    },
)
MOUNT_OPTIONS = ("nodev", "nosuid", "noexec")


class ProvisionError(RuntimeError):
    pass


class ProvisionBlocked(ProvisionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 120) -> str:
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
        raise ProvisionBlocked(f"{label} unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProvisionBlocked(f"{label} must be a single-link regular file")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077 or not 1 <= info.st_size <= maximum:
        raise ProvisionBlocked(f"{label} ownership/mode/size unsafe")
    return info


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProvisionBlocked(f"{label} must be RFC3339 UTC Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ProvisionBlocked(f"{label} invalid") from exc


def _walk_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or normalized.endswith("_key_material"):
                raise ProvisionBlocked(f"embedded secret material rejected at {path}.{key}")
            _walk_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_sensitive(child, f"{path}[{index}]")


def _git_gate(root: Path, expected_sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if heads != [expected_sha, expected_sha]:
        raise ProvisionBlocked("checkout and origin/main do not match accepted merge SHA")
    if _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise ProvisionBlocked("production source tree is not clean")


def _evidence(path: Path, merge_sha: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    _private_regular(resolved, "recovery evidence")
    value = _json(resolved)
    _walk_sensitive(value)
    if value.get("schema_version") != 1 or value.get("subpart") != SUBPART or value.get("environment") != "production":
        raise ProvisionBlocked("recovery evidence metadata invalid")
    if value.get("production_authorization") is not True:
        raise ProvisionBlocked("production authorization missing")
    now = _utc_now()
    age = (now - _parse_time(value.get("observed_at"), "evidence observed_at")).total_seconds()
    if age < -300 or age > MAX_EVIDENCE_AGE_SECONDS:
        raise ProvisionBlocked("recovery evidence stale/future-dated")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("merge_sha") != merge_sha or source.get("protected_pr_checks_passed") is not True or source.get("post_merge_main_checks_passed") is not True:
        raise ProvisionBlocked("source CI evidence incomplete")
    recovery = value.get("recovery")
    required = {"backup_status": "completed", "offsite_status": "completed", "restore_status": "completed", "restore_validated": True, "restore_offsite_validated": True}
    if not isinstance(recovery, dict):
        raise ProvisionBlocked("recovery evidence missing")
    for key, wanted in required.items():
        if recovery.get(key) != wanted:
            raise ProvisionBlocked(f"recovery gate failed: {key}")
    restore_age = (now - _parse_time(recovery.get("restore_completed_at"), "restore completed_at")).total_seconds()
    if restore_age < -300 or restore_age > MAX_EVIDENCE_AGE_SECONDS:
        raise ProvisionBlocked("restore evidence stale")
    operations = value.get("operations")
    if not isinstance(operations, dict):
        raise ProvisionBlocked("operations evidence missing")
    for key in ("active_backup_jobs", "active_restore_validations", "active_durable_external_jobs"):
        if operations.get(key) != 0:
            raise ProvisionBlocked(f"operations not drained: {key}")
    approvals = value.get("approvals")
    if not isinstance(approvals, dict) or approvals.get("owner_authorized") is not True:
        raise ProvisionBlocked("owner authorization missing")
    start = _parse_time(approvals.get("window_starts_at"), "window start")
    end = _parse_time(approvals.get("window_ends_at"), "window end")
    if end <= start or (end - start).total_seconds() > MAX_WINDOW_SECONDS or not start <= now <= end:
        raise ProvisionBlocked("maintenance window invalid/inactive")
    for role in ("local_backup", "operations"):
        for kind in ("active_key_ref", "recovery_key_ref"):
            ref = approvals.get(f"{role}_{kind}")
            if not isinstance(ref, str) or "://" not in ref or ref.startswith(("file://", "path://")):
                raise ProvisionBlocked(f"external custody reference invalid: {role}_{kind}")
        if approvals[f"{role}_active_key_ref"] == approvals[f"{role}_recovery_key_ref"]:
            raise ProvisionBlocked(f"{role} active/recovery custody must be independent")
    return value


def _bundle(path: Path, purpose: str) -> tuple[dict[str, bytes], str]:
    resolved = path.resolve(strict=True)
    if resolved.parent != KEY_ROOT or not str(resolved).startswith(str(KEY_ROOT) + "/"):
        raise ProvisionBlocked(f"{purpose} bundle must be under fixed tmpfs key root")
    _private_regular(resolved, f"{purpose} bundle", maximum=64 * 1024)
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", str(resolved)]) != "tmpfs":
        raise ProvisionBlocked(f"{purpose} bundle is not on tmpfs")
    value = _json(resolved)
    expected = {"schema_version", "purpose", "local_backup_vault", "operations_vault"}
    if set(value) != expected or value.get("schema_version") != 1 or value.get("purpose") != purpose:
        raise ProvisionBlocked(f"{purpose} bundle fields invalid")
    decoded: dict[str, bytes] = {}
    for field in ("local_backup_vault", "operations_vault"):
        raw = value.get(field)
        if not isinstance(raw, str) or len(raw) != 128:
            raise ProvisionBlocked(f"{purpose} {field} key length invalid")
        try:
            decoded[field] = bytes.fromhex(raw)
        except ValueError as exc:
            raise ProvisionBlocked(f"{purpose} {field} key encoding invalid") from exc
        if len(decoded[field]) != 64:
            raise ProvisionBlocked(f"{purpose} {field} key size invalid")
    if decoded["local_backup_vault"] == decoded["operations_vault"]:
        raise ProvisionBlocked(f"{purpose} bundle reuses key material")
    return decoded, _file_digest(resolved)


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _git_descendant_gate(root: Path, minimum_sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if len(heads) != 2 or heads[0] != heads[1]:
        raise ProvisionBlocked("checkout and origin/main do not match")
    if _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise ProvisionBlocked("production source tree is not clean")
    if subprocess.run(["git", "merge-base", "--is-ancestor", minimum_sha, heads[0]], cwd=root, check=False).returncode != 0:
        raise ProvisionBlocked("current main is not a descendant of provisioned source")


def _legacy_volumes() -> list[dict[str, str]]:
    docker_root = Path(_run(["docker", "info", "--format", "{{.DockerRootDir}}"])).resolve()
    result: list[dict[str, str]] = []
    for vault in VAULTS:
        name = str(vault["legacy_volume"])
        value = json.loads(_run(["docker", "volume", "inspect", name]))
        if not isinstance(value, list) or len(value) != 1:
            raise ProvisionBlocked(f"legacy volume unavailable: {name}")
        mountpoint = Path(str(value[0].get("Mountpoint", ""))).resolve(strict=True)
        expected = docker_root / "volumes" / name / "_data"
        if mountpoint != expected or not mountpoint.is_dir() or mountpoint.is_symlink():
            raise ProvisionBlocked(f"legacy volume path drifted: {name}")
        result.append({"role": str(vault["role"]), "volume": name, "mountpoint": str(mountpoint)})
    return result


def _candidate_absent() -> None:
    for vault in VAULTS:
        if vault["image"].exists() or vault["mapper"].exists() or os.path.ismount(vault["mount_root"]):
            raise ProvisionBlocked(f"{vault['role']} artifacts already exist")
        if subprocess.run(["docker", "volume", "inspect", str(vault["volume"])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0:
            raise ProvisionBlocked(f"{vault['role']} Docker volume already exists")


def _existing_ancestor(path: Path) -> Path:
    value = path
    while not value.exists():
        if value.parent == value:
            raise ProvisionError("no existing capacity ancestor")
        value = value.parent
    return value


def _write_exclusive(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.write(fd, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n")
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


def _mount(vault: dict[str, Any]) -> None:
    root = vault["mount_root"]
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.mkdir(exist_ok=True, mode=0o700)
    info = os.lstat(root)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ProvisionBlocked(f"{vault['role']} mount root unsafe")
    _run(["mount", "-o", ",".join(MOUNT_OPTIONS), str(vault["mapper"]), str(root)])


def _verify_luks(vault: dict[str, Any]) -> dict[str, Any]:
    _run(["cryptsetup", "isLuks", "--type", "luks2", str(vault["image"])])
    value = json.loads(_run(["cryptsetup", "luksDump", "--dump-json-metadata", str(vault["image"])]))
    slots = value.get("keyslots")
    if not isinstance(slots, dict) or len(slots) != 2:
        raise ProvisionBlocked(f"{vault['role']} needs exactly two keyslots")
    for slot in slots.values():
        if not isinstance(slot, dict) or slot.get("type") != "luks2" or slot.get("key_size") != 64:
            raise ProvisionBlocked(f"{vault['role']} keyslot drifted")
        if (slot.get("kdf") or {}).get("type") != "argon2id" or (slot.get("area") or {}).get("encryption") != "aes-xts-plain64":
            raise ProvisionBlocked(f"{vault['role']} crypto drifted")
    return {"format": "LUKS2", "cipher": "aes-xts-plain64", "key_bits": 512, "pbkdf": "argon2id", "keyslot_count": 2}


def _verify_host_ready(vault: dict[str, Any]) -> dict[str, Any]:
    mapper = vault["mapper"]
    if not mapper.exists() or not stat.S_ISBLK(os.stat(mapper).st_mode):
        raise ProvisionBlocked(f"{vault['role']} mapper inactive")
    if _run(["blkid", "-o", "value", "-s", "TYPE", str(mapper)]) != "ext4":
        raise ProvisionBlocked(f"{vault['role']} filesystem not ext4")
    if _run(["blkid", "-o", "value", "-s", "LABEL", str(mapper)]) != vault["label"]:
        raise ProvisionBlocked(f"{vault['role']} label drifted")
    line = _run(["findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS", "--target", str(vault["mount_root"])])
    pieces = line.split(None, 2)
    if len(pieces) != 3 or os.path.realpath(pieces[0]) != os.path.realpath(mapper) or pieces[1] != "ext4":
        raise ProvisionBlocked(f"{vault['role']} mount source drifted")
    if not set(MOUNT_OPTIONS).issubset(set(pieces[2].split(","))):
        raise ProvisionBlocked(f"{vault['role']} mount options drifted")
    subpath = vault["mount_root"] / vault["subpath"]
    info = os.lstat(subpath)
    uid, gid = vault["owner"]
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_gid != gid or stat.S_IMODE(info.st_mode) != vault["mode"]:
        raise ProvisionBlocked(f"{vault['role']} subpath ownership/mode drifted")
    return {"role": vault["role"], "mapper": str(mapper), "mount_root": str(vault["mount_root"]), "subpath": vault["subpath"]}


def _verify_all_host_ready() -> dict[str, Any]:
    rows = [_verify_host_ready(vault) for vault in VAULTS]
    return {
        "status": "host-ready",
        "validation": "FR06C3_VAULTS_HOST_READY",
        "observed_at": _utc_text(),
        "vaults": rows,
        "docker_inspected": False,
        "admission_opened": False,
    }


def _verify_ready(require_zero_consumers: bool = True) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for vault in VAULTS:
        host = _verify_host_ready(vault)
        value = json.loads(_run(["docker", "volume", "inspect", str(vault["volume"])]))
        if not isinstance(value, list) or len(value) != 1:
            raise ProvisionBlocked(f"{vault['role']} Docker volume unavailable")
        options = value[0].get("Options") or {}
        if value[0].get("Driver") != "local" or options.get("type") != "ext4" or os.path.realpath(str(options.get("device", ""))) != os.path.realpath(vault["mapper"]):
            raise ProvisionBlocked(f"{vault['role']} Docker volume device drifted")
        if set(str(options.get("o", "")).split(",")) != set(MOUNT_OPTIONS):
            raise ProvisionBlocked(f"{vault['role']} Docker volume options drifted")
        consumers = [line for line in _run(["docker", "ps", "--filter", f"volume={vault['volume']}", "--format", "{{.ID}}"]).splitlines() if line.strip()]
        if require_zero_consumers and consumers:
            raise ProvisionBlocked(f"{vault['role']} requires zero candidate consumers")
        rows.append({**host, "docker_volume": vault["volume"], "running_consumer_count": len(consumers)})
    return {"status": "ready", "validation": "FR06C3_EMPTY_VAULTS_READY", "observed_at": _utc_text(), "vaults": rows}


def _preflight(args: argparse.Namespace) -> tuple[dict[str, Any], str, str]:
    root = args.root.resolve()
    if os.geteuid() != 0 or root != PRODUCTION_ROOT:
        raise ProvisionBlocked("production provisioning requires root and /opt/AIOS")
    for command in ("cryptsetup", "mkfs.ext4", "fallocate", "mount", "umount", "docker", "git", "findmnt", "blkid"):
        if shutil.which(command) is None:
            raise ProvisionBlocked(f"required command missing: {command}")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]) != "tmpfs" or _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/run"]) != "tmpfs":
        raise ProvisionBlocked("/dev/shm and /run must be tmpfs")
    _git_gate(root, args.merge_sha)
    _evidence(args.evidence.resolve(), args.merge_sha)
    _legacy_volumes()
    _candidate_absent()
    active, active_digest = _bundle(args.active_bundle, "active")
    recovery, recovery_digest = _bundle(args.recovery_bundle, "recovery")
    if any(active[v["bundle_field"]] == recovery[v["bundle_field"]] for v in VAULTS):
        raise ProvisionBlocked("active and recovery keys must be independent")
    total = sum(int(v["size_bytes"]) for v in VAULTS)
    free = shutil.disk_usage(_existing_ancestor(IMAGE_ROOT.parent)).free
    if free < total + 8 * 1024**3:
        raise ProvisionBlocked("insufficient free space for C3 vaults plus reserve")
    return {"free_bytes": free, "legacy": _legacy_volumes(), "observed_at": _utc_text()}, active_digest, recovery_digest


def create_plan(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.ttl_seconds <= MAX_PLAN_TTL_SECONDS:
        raise ProvisionBlocked("plan TTL outside bounded range")
    plan_path = args.plan.resolve()
    if plan_path.parent != RUNTIME_ROOT or SAFE_PLAN_RE.fullmatch(plan_path.name) is None:
        raise ProvisionBlocked("plan path must be fixed runtime plan-*.json")
    inspection, active_digest, recovery_digest = _preflight(args)
    now = _utc_now()
    body = {
        "schema_version": 1, "subpart": SUBPART, "operation": "provision-empty-c3-vaults",
        "created_at": _utc_text(now), "expires_at": _utc_text(now + timedelta(seconds=args.ttl_seconds)),
        "nonce": secrets.token_hex(32), "merge_sha": args.merge_sha,
        "evidence_sha256": _file_digest(args.evidence.resolve()), "active_bundle_sha256": active_digest,
        "recovery_bundle_sha256": recovery_digest, "free_bytes": inspection["free_bytes"],
        "vaults": [{"role": v["role"], "image": str(v["image"]), "size_bytes": v["size_bytes"], "mapper": str(v["mapper"]), "mount_root": str(v["mount_root"]), "subpath": v["subpath"], "volume": v["volume"]} for v in VAULTS],
        "production_data_copy_permitted": False, "service_stop_or_restart_permitted": False,
        "redis_flush_permitted": False, "log_move_permitted": False, "admission_opened": False, "cloudflare_change_permitted": False,
    }
    body["plan_id"] = _digest(body)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_exclusive(plan_path, body)
    return {"status": "planned", "plan": str(plan_path), "plan_id": body["plan_id"], "confirmation": f"PROVISION-{body['plan_id'][:16]}", "production_executed": False}


def _load_plan(path: Path) -> dict[str, Any]:
    _private_regular(path, "plan")
    value = _json(path)
    plan_id = value.get("plan_id")
    if not isinstance(plan_id, str) or _digest({k: v for k, v in value.items() if k != "plan_id"}) != plan_id:
        raise ProvisionBlocked("plan digest invalid")
    if value.get("subpart") != SUBPART or value.get("operation") != "provision-empty-c3-vaults":
        raise ProvisionBlocked("plan scope invalid")
    if _utc_now() > _parse_time(value.get("expires_at"), "plan expiry"):
        raise ProvisionBlocked("plan expired")
    return value


def apply_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load_plan(args.plan.resolve())
    if args.confirmation != f"PROVISION-{plan['plan_id'][:16]}" or args.confirm_production != PRODUCTION_CONFIRMATION:
        raise ProvisionBlocked("production confirmation invalid")
    _, active_digest, recovery_digest = _preflight(args)
    if plan.get("merge_sha") != args.merge_sha or plan.get("evidence_sha256") != _file_digest(args.evidence.resolve()) or plan.get("active_bundle_sha256") != active_digest or plan.get("recovery_bundle_sha256") != recovery_digest:
        raise ProvisionBlocked("plan-bound input changed")
    consumed = STATE_ROOT / "consumed" / f"{plan['plan_id']}.json"
    if consumed.exists():
        raise ProvisionBlocked("plan already consumed")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(RUNTIME_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    created_images: list[Path] = []
    opened: list[str] = []
    mounted: list[Path] = []
    volumes: list[str] = []
    secrets_dir: Path | None = None
    secret_paths: list[Path] = []
    header_paths: list[Path] = []
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProvisionBlocked("another C3 provisioning operation holds lock") from exc
        active, current_active_digest = _bundle(args.active_bundle, "active")
        recovery, current_recovery_digest = _bundle(args.recovery_bundle, "recovery")
        if current_active_digest != active_digest or current_recovery_digest != recovery_digest:
            raise ProvisionBlocked("key bundle changed while applying")
        IMAGE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        KEY_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        secrets_dir = KEY_ROOT / ("apply-" + secrets.token_hex(8))
        secrets_dir.mkdir(mode=0o700)
        receipts: list[dict[str, Any]] = []
        for vault in VAULTS:
            field = vault["bundle_field"]
            active_path = _secret_file(secrets_dir, vault["mapper_name"] + ".active", active[field])
            recovery_path = _secret_file(secrets_dir, vault["mapper_name"] + ".recovery", recovery[field])
            secret_paths += [active_path, recovery_path]
            _run(["fallocate", "-l", str(vault["size_bytes"]), str(vault["image"])], timeout=300)
            created_images.append(vault["image"])
            os.chmod(vault["image"], 0o600)
            _run(["cryptsetup", "luksFormat", "--batch-mode", "--type", "luks2", "--cipher", "aes-xts-plain64", "--key-size", "512", "--pbkdf", "argon2id", "--key-file", str(active_path), str(vault["image"])], timeout=300)
            _run(["cryptsetup", "luksAddKey", str(vault["image"]), str(recovery_path), "--key-file", str(active_path)], timeout=300)
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active_path), str(vault["image"]), vault["mapper_name"]], timeout=180)
            opened.append(vault["mapper_name"])
            _run(["mkfs.ext4", "-q", "-L", vault["label"], str(vault["mapper"])], timeout=180)
            header = RUNTIME_ROOT / "headers" / (vault["mapper_name"] + ".header")
            header.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if header.exists():
                raise ProvisionBlocked(f"{vault['role']} header staging path already exists")
            _run(["cryptsetup", "luksHeaderBackup", str(vault["image"]), "--header-backup-file", str(header)], timeout=120)
            os.chmod(header, 0o400)
            header_paths.append(header)
            _mount(vault)
            mounted.append(vault["mount_root"])
            subpath = vault["mount_root"] / vault["subpath"]
            subpath.mkdir(mode=vault["mode"])
            os.chown(subpath, *vault["owner"])
            os.chmod(subpath, vault["mode"])
            _run(["sync", "-f", str(vault["mount_root"])])
            _run(["docker", "volume", "create", "--driver", "local", "--opt", "type=ext4", "--opt", f"device={vault['mapper']}", "--opt", "o=" + ",".join(MOUNT_OPTIONS), vault["volume"]])
            volumes.append(vault["volume"])
            receipts.append({"role": vault["role"], "image": str(vault["image"]), "size_bytes": vault["size_bytes"], "mapper": str(vault["mapper"]), "mount_root": str(vault["mount_root"]), "subpath": vault["subpath"], "docker_volume": vault["volume"], "crypto": _verify_luks(vault), "header_staging_path": str(header), "header_sha256": _file_digest(header), "header_bytes": os.stat(header).st_size})
        ready = _verify_ready(True)
        receipt = {
            "schema_version": 1, "subpart": SUBPART, "status": "empty_c3_vaults_provisioned_admission_closed",
            "plan_id": plan["plan_id"], "merge_sha": args.merge_sha, "completed_at": _utc_text(), "vaults": receipts,
            "ready_validation": ready["validation"], "active_bundle_sha256": active_digest, "recovery_bundle_sha256": recovery_digest,
            "production_backup_data_read_or_copied": False, "production_redis_data_read_or_copied": False,
            "production_redis_flushed": False, "production_logs_moved": False, "services_stopped_or_restarted": False,
            "admission_opened": False, "cloudflare_changed": False,
        }
        receipt_path = STATE_ROOT / "provision-receipt.json"
        STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_exclusive(receipt_path, receipt)
        _write_exclusive(consumed, {"plan_id": plan["plan_id"], "consumed_at": _utc_text()})
        return {"status": receipt["status"], "receipt": str(receipt_path), "ready": True, "production_data_copied": False}
    except Exception:
        for volume in reversed(volumes):
            subprocess.run(["docker", "volume", "rm", "-f", volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for mount_root in reversed(mounted):
            subprocess.run(["umount", str(mount_root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for mapper in reversed(opened):
            subprocess.run(["cryptsetup", "close", mapper], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for header in reversed(header_paths):
            try: header.unlink()
            except OSError: pass
        for image in reversed(created_images):
            try: image.unlink()
            except OSError: pass
        raise
    finally:
        for path in secret_paths:
            try: path.unlink()
            except OSError: pass
        if secrets_dir is not None:
            try: secrets_dir.rmdir()
            except OSError: pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def prove_recovery(args: argparse.Namespace) -> dict[str, Any]:
    receipt_path = STATE_ROOT / "provision-receipt.json"
    _private_regular(receipt_path, "provision receipt")
    receipt = _json(receipt_path)
    if receipt.get("status") != "empty_c3_vaults_provisioned_admission_closed" or receipt.get("subpart") != SUBPART:
        raise ProvisionBlocked("provision receipt invalid")
    _git_gate(args.root.resolve(), str(receipt.get("merge_sha")))
    ready = _verify_ready(True)
    if any(int(row["running_consumer_count"]) for row in ready["vaults"]):
        raise ProvisionBlocked("recovery proof requires zero candidate consumers")
    active, active_digest = _bundle(args.active_bundle, "active")
    recovery, recovery_digest = _bundle(args.recovery_bundle, "recovery")
    if active_digest != receipt.get("active_bundle_sha256") or recovery_digest != receipt.get("recovery_bundle_sha256"):
        raise ProvisionBlocked("recovery proof bundles differ from provisioning")
    directory = KEY_ROOT / ("recovery-" + secrets.token_hex(8))
    directory.mkdir(mode=0o700)
    paths: list[Path] = []
    active_paths: dict[str, Path] = {}
    checks: list[dict[str, Any]] = []
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(RUNTIME_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProvisionBlocked("another C3 operation holds lock") from exc
        for vault in VAULTS:
            field = vault["bundle_field"]
            active_path = _secret_file(directory, vault["mapper_name"] + ".active", active[field])
            recovery_path = _secret_file(directory, vault["mapper_name"] + ".recovery", recovery[field])
            active_paths[vault["role"]] = active_path
            paths += [active_path, recovery_path]
            _run(["umount", str(vault["mount_root"])])
            _run(["cryptsetup", "close", vault["mapper_name"]])
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(recovery_path), str(vault["image"]), vault["mapper_name"]])
            _mount(vault)
            _verify_host_ready(vault)
            _run(["umount", str(vault["mount_root"])])
            _run(["cryptsetup", "close", vault["mapper_name"]])
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active_path), str(vault["image"]), vault["mapper_name"]])
            _mount(vault)
            _verify_host_ready(vault)
            checks.append({"role": vault["role"], "recovery_open_passed": True, "active_reopen_passed": True})
        _verify_ready(True)
        result = {"schema_version": 1, "subpart": SUBPART, "status": "independent_c3_recovery_keys_proved", "observed_at": _utc_text(), "checks": checks, "candidate_consumers": 0, "key_material_persisted": False, "admission_opened": False}
        out = STATE_ROOT / "recovery-proof.json"
        if out.exists(): out.unlink()
        _write_exclusive(out, result)
        return {"status": result["status"], "receipt": str(out)}
    finally:
        # Best-effort fail-safe: recovery proof must not strand an already
        # provisioned vault closed if a later check fails mid-sequence.
        for vault in VAULTS:
            try:
                if not vault["mapper"].exists():
                    active_path = active_paths.get(vault["role"])
                    if active_path is not None and active_path.exists():
                        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active_path), str(vault["image"]), vault["mapper_name"]])
                if vault["mapper"].exists() and not os.path.ismount(vault["mount_root"]):
                    _mount(vault)
            except Exception:
                pass
        for path in paths:
            try: path.unlink()
            except OSError: pass
        try: directory.rmdir()
        except OSError: pass
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def unlock(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirmation != UNLOCK_CONFIRMATION:
        raise ProvisionBlocked("unlock confirmation is invalid")
    if os.geteuid() != 0:
        raise ProvisionBlocked("post-boot C3 unlock requires root")
    if _docker_available():
        raise ProvisionBlocked("Docker must be stopped before C3 vault unlock")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]) != "tmpfs":
        raise ProvisionBlocked("/dev/shm must be tmpfs")
    receipt_path = STATE_ROOT / "provision-receipt.json"
    _private_regular(receipt_path, "provision receipt")
    receipt = _json(receipt_path)
    merge_sha = receipt.get("merge_sha")
    if receipt.get("status") != "empty_c3_vaults_provisioned_admission_closed" or not isinstance(merge_sha, str):
        raise ProvisionBlocked("provision receipt invalid")
    _git_descendant_gate(PRODUCTION_ROOT, merge_sha)
    active, active_digest = _bundle(args.active_bundle, "active")
    if active_digest != receipt.get("active_bundle_sha256"):
        raise ProvisionBlocked("active bundle differs from provisioned custody")
    for vault in VAULTS:
        _private_regular(vault["image"], f"{vault['role']} image", maximum=int(vault["size_bytes"]) + 1)
        _verify_luks(vault)
        if vault["mapper"].exists() or os.path.ismount(vault["mount_root"]):
            raise ProvisionBlocked(f"{vault['role']} unlock requires fully closed host state")
    directory = KEY_ROOT / ("unlock-" + secrets.token_hex(8))
    directory.mkdir(parents=True, mode=0o700)
    paths: list[Path] = []
    opened: list[str] = []
    mounted: list[Path] = []
    try:
        for vault in VAULTS:
            field = vault["bundle_field"]
            key_path = _secret_file(directory, vault["mapper_name"] + ".active", active[field])
            paths.append(key_path)
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(key_path), str(vault["image"]), vault["mapper_name"]], timeout=180)
            opened.append(vault["mapper_name"])
            _mount(vault)
            mounted.append(vault["mount_root"])
        ready = _verify_all_host_ready()
        out = STATE_ROOT / "unlock-receipts" / f"unlock-{int(_utc_now().timestamp())}-{secrets.token_hex(6)}.json"
        result = {
            "schema_version": 1,
            "subpart": SUBPART,
            "status": "c3_vaults_unlocked_host_ready_docker_stopped",
            "completed_at": _utc_text(),
            "host_validation": ready["validation"],
            "vault_count": len(VAULTS),
            "docker_started": False,
            "services_started_or_restarted": False,
            "key_material_persisted": False,
            "admission_opened": False,
        }
        _write_exclusive(out, result)
        return {"status": result["status"], "receipt": str(out), "vault_count": len(VAULTS)}
    except Exception:
        for mount_root in reversed(mounted):
            subprocess.run(["umount", str(mount_root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for mapper in reversed(opened):
            subprocess.run(["cryptsetup", "close", mapper], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        raise
    finally:
        for path in paths:
            try:
                path.unlink()
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
        try: info = os.lstat(path)
        except OSError: continue
        if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_nlink == 1:
            path.unlink(); removed.append(name)
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
    plan = sub.add_parser("plan"); common(plan); plan.add_argument("--plan", type=Path, required=True); plan.add_argument("--ttl-seconds", type=int, default=600)
    apply = sub.add_parser("apply"); common(apply); apply.add_argument("--plan", type=Path, required=True); apply.add_argument("--confirmation", required=True); apply.add_argument("--confirm-production", default="")
    prove = sub.add_parser("prove-recovery"); prove.add_argument("--root", type=Path, default=PRODUCTION_ROOT); prove.add_argument("--active-bundle", type=Path, required=True); prove.add_argument("--recovery-bundle", type=Path, required=True)
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
        if args.command == "plan": result = create_plan(args)
        elif args.command == "apply": result = apply_plan(args)
        elif args.command == "prove-recovery": result = prove_recovery(args)
        elif args.command == "unlock": result = unlock(args)
        elif args.command == "wipe-inputs": result = wipe_inputs()
        else:
            result = _verify_all_host_ready() if args.require_host_ready else _verify_ready(bool(args.require_ready))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except ProvisionBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    except ProvisionError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
