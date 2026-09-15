#!/usr/bin/env python3
"""Fail-closed FR-06B4 production vault provisioning and recovery checks.

The tool accepts key bundles only from tmpfs, never emits key material, binds a
short-lived plan to exact source and bundle digests, and provisions only the two
fixed FR-06 production vaults.  It deliberately does not stop containers, copy
live data, open admission, or change Cloudflare.

The explicit ``unlock`` command is the only supported post-boot recovery path.
It consumes the externally held active bundle from tmpfs, opens and mounts the
two fixed vaults, and stops before starting Docker or any application service.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
SUBPART = "FR-06B4"
PRODUCTION_ROOT = Path("/opt/AIOS")
PRODUCTION_STATE = Path("/var/lib/aionex/fr06b4")
IMAGE_ROOT = Path("/var/lib/aionex/fr06-vaults")
RUNTIME_ROOT = Path("/run/aionex-fr06b4")
KEY_ROOT = Path("/dev/shm/aionex-fr06b4-keys")
MAX_PLAN_TTL_SECONDS = 900
MAX_WINDOW_SECONDS = 4 * 60 * 60
GIB = 1024**3
DOCKER_HOST = "unix:///run/docker.sock"
SECOND_CONFIRMATION = "PROVISION_FR06B4_PRODUCTION"
WIPE_CONFIRMATION = "WIPE_FR06B4_TMPFS_KEY_INPUTS"
UNLOCK_CONFIRMATION = "UNLOCK_FR06B4_PRODUCTION"

VAULTS: tuple[dict[str, Any], ...] = (
    {
        "role": "asset-vault",
        "image": IMAGE_ROOT / "asset-vault.luks2",
        "size_bytes": 64 * GIB,
        "mapper_name": "aionex-asset-vault",
        "mapper": Path("/dev/mapper/aionex-asset-vault"),
        "mount_root": Path("/mnt/aionex/fr06-asset-vault"),
        "mount_options": ("nodev", "nosuid", "noexec"),
        "volume": "aionex-fr06-asset-vault",
        "fs_label": "AIONEX06_ASSET",
        "bundle_field": "asset_vault",
    },
    {
        "role": "project-execution-vault",
        "image": IMAGE_ROOT / "project-execution-vault.luks2",
        "size_bytes": 32 * GIB,
        "mapper_name": "aionex-project-execution-vault",
        "mapper": Path("/dev/mapper/aionex-project-execution-vault"),
        "mount_root": Path("/mnt/aionex/fr06-project-execution-vault"),
        "mount_options": ("nodev", "nosuid"),
        "volume": "aionex-fr06-project-execution-vault",
        "fs_label": "AIONEX06_PROJECT",
        "bundle_field": "project_execution_vault",
    },
)


class ProvisionError(RuntimeError):
    """Malformed input or operational failure."""


class ProvisionBlocked(RuntimeError):
    """A valid request that does not satisfy every safety gate."""


def _run(argv: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvisionError(f"command unavailable or timed out: {argv[0]}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1:] or ["no diagnostic"]
        raise ProvisionError(f"command failed: {argv[0]}: {detail[0]}")
    return result.stdout.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: str, label: str) -> datetime:
    if not value.endswith("Z"):
        raise ProvisionError(f"{label} must be an RFC3339 UTC Z timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ProvisionError(f"invalid {label}") from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvisionError(f"cannot read valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ProvisionError(f"JSON object required: {path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.write(fd, _canonical(value) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_regular(path: Path, label: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ProvisionBlocked(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProvisionBlocked(f"{label} must be a real regular file")
    if info.st_nlink != 1 or info.st_uid != 0 or info.st_mode & 0o077:
        raise ProvisionBlocked(f"{label} must be root-owned, single-link, and private")
    return info


def _bundle(path: Path, purpose: str) -> tuple[dict[str, bytes], str]:
    resolved = path.resolve(strict=True)
    if resolved.parent != KEY_ROOT or not str(resolved).startswith(str(KEY_ROOT) + "/"):
        raise ProvisionBlocked(f"{purpose} bundle must be directly under the fixed tmpfs key root")
    _private_regular(resolved, f"{purpose} bundle")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", str(resolved)]) != "tmpfs":
        raise ProvisionBlocked(f"{purpose} bundle is not on tmpfs")
    value = _json(resolved)
    if value.get("schema_version") != 1 or value.get("purpose") != purpose:
        raise ProvisionBlocked(f"{purpose} bundle metadata is invalid")
    expected = {"schema_version", "purpose", "asset_vault", "project_execution_vault"}
    if set(value) != expected:
        raise ProvisionBlocked(f"{purpose} bundle fields are not exact")
    decoded: dict[str, bytes] = {}
    for field in ("asset_vault", "project_execution_vault"):
        raw = value.get(field)
        if not isinstance(raw, str) or len(raw) != 128:
            raise ProvisionBlocked(f"{purpose} bundle key length is invalid")
        try:
            decoded[field] = bytes.fromhex(raw)
        except ValueError as exc:
            raise ProvisionBlocked(f"{purpose} bundle key encoding is invalid") from exc
        if len(decoded[field]) != 64:
            raise ProvisionBlocked(f"{purpose} bundle key size is invalid")
    if decoded["asset_vault"] == decoded["project_execution_vault"]:
        raise ProvisionBlocked(f"{purpose} bundle reuses key material")
    return decoded, _file_digest(resolved)


def _load_contract(root: Path) -> dict[str, Any]:
    contract = _json(root / "docs/project/receipts/FR-06B1-asset-vault-copy-contract.json")
    rows = contract.get("source_roots")
    if not isinstance(rows, list) or len(rows) != 11:
        raise ProvisionBlocked("FR-06B1 root contract is incomplete")
    return contract


def _git_gate(root: Path, expected_sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if heads != [expected_sha, expected_sha]:
        raise ProvisionBlocked("checkout and origin/main do not match the accepted merge SHA")
    if _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise ProvisionBlocked("production source tree is not clean")


def _git_descendant_gate(root: Path, minimum_sha: str) -> None:
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).splitlines()
    if len(heads) != 2 or heads[0] != heads[1]:
        raise ProvisionBlocked("checkout and origin/main do not match")
    if _run(["git", "status", "--porcelain=v1"], cwd=root):
        raise ProvisionBlocked("production source tree is not clean")
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
        raise ProvisionError("cannot verify provisioning commit ancestry") from exc
    if result.returncode != 0:
        raise ProvisionBlocked("current main does not descend from the accepted provisioning commit")


def _volume_exists(name: str) -> bool:
    result = subprocess.run(
        ["docker", "--host", DOCKER_HOST, "volume", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    return result.returncode == 0


def _fresh_topology_gate() -> None:
    for vault in VAULTS:
        if vault["image"].exists() or vault["mapper"].exists():
            raise ProvisionBlocked(f"{vault['role']}: production image or mapper already exists")
        if os.path.ismount(vault["mount_root"]):
            raise ProvisionBlocked(f"{vault['role']}: mount already exists")
        if _volume_exists(vault["volume"]):
            raise ProvisionBlocked(f"{vault['role']}: Docker volume already exists")


def _legacy_gate(contract: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    docker_root = Path(_run(["docker", "--host", DOCKER_HOST, "info", "--format", "{{.DockerRootDir}}"])).resolve()
    for item in contract["source_roots"]:
        name = str(item.get("runtime_volume"))
        target = str(item.get("target_vault"))
        subpath = str(item.get("target_subpath"))
        if target not in {v["role"] for v in VAULTS} or not subpath or "/" in subpath:
            raise ProvisionBlocked("unsafe FR-06B1 root mapping")
        inspected = json.loads(_run(["docker", "--host", DOCKER_HOST, "volume", "inspect", name]))
        if not isinstance(inspected, list) or len(inspected) != 1:
            raise ProvisionBlocked(f"legacy volume missing: {name}")
        mountpoint = Path(str(inspected[0].get("Mountpoint", ""))).resolve(strict=True)
        expected = docker_root / "volumes" / name / "_data"
        if mountpoint != expected or not mountpoint.is_dir() or mountpoint.is_symlink():
            raise ProvisionBlocked(f"legacy volume path drifted: {name}")
        rows.append({"volume": name, "vault": target, "target_subpath": subpath})
    return rows


def _validate_window(start_text: str, end_text: str, now: datetime) -> None:
    start = _parse_time(start_text, "window start")
    end = _parse_time(end_text, "window end")
    if end <= start or (end - start).total_seconds() > MAX_WINDOW_SECONDS:
        raise ProvisionBlocked("maintenance window bounds are invalid")
    if not start <= now <= end:
        raise ProvisionBlocked("current time is outside the approved maintenance window")


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise ProvisionError("no existing ancestor for capacity check")
        candidate = parent
    return candidate


def _preflight(args: argparse.Namespace) -> tuple[dict[str, Any], str, str]:
    if os.geteuid() != 0 or args.root.resolve() != PRODUCTION_ROOT:
        raise ProvisionBlocked("production provisioning requires root and /opt/AIOS")
    for command in ("cryptsetup", "mkfs.ext4", "fallocate", "mount", "umount", "docker", "git", "findmnt", "blkid"):
        if shutil.which(command) is None:
            raise ProvisionBlocked(f"required command unavailable: {command}")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]) != "tmpfs":
        raise ProvisionBlocked("/dev/shm is not tmpfs")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/run"]) != "tmpfs":
        raise ProvisionBlocked("/run is not tmpfs")
    _git_gate(args.root.resolve(), args.merge_sha)
    _fresh_topology_gate()
    contract = _load_contract(args.root.resolve())
    roots = _legacy_gate(contract)
    active, active_digest = _bundle(args.active_bundle, "active")
    recovery, recovery_digest = _bundle(args.recovery_bundle, "recovery")
    all_keys = list(active.values()) + list(recovery.values())
    if len(set(all_keys)) != 4:
        raise ProvisionBlocked("all four production keys must be independent")
    del active, recovery, all_keys
    required = sum(int(v["size_bytes"]) for v in VAULTS) + 8 * GIB
    free = shutil.disk_usage(_existing_ancestor(IMAGE_ROOT.parent)).free
    if free < required:
        raise ProvisionBlocked("insufficient free space for non-sparse vaults and safety reserve")
    now = _utc_now()
    _validate_window(args.window_starts_at, args.window_ends_at, now)
    if args.owner_authorized is not True:
        raise ProvisionBlocked("owner authorization is absent")
    return {"roots": roots, "free_bytes": free, "observed_at": _utc_text(now)}, active_digest, recovery_digest


def create_plan(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.ttl_seconds <= MAX_PLAN_TTL_SECONDS:
        raise ProvisionBlocked("plan TTL is outside the bounded range")
    plan_path = args.plan.resolve()
    if plan_path.parent != RUNTIME_ROOT or not plan_path.name.startswith("plan-") or plan_path.suffix != ".json":
        raise ProvisionBlocked("plan must be a plan-*.json file directly under the fixed tmpfs runtime root")
    inspection, active_digest, recovery_digest = _preflight(args)
    now = _utc_now()
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "subpart": SUBPART,
        "operation": "provision-production-vaults",
        "nonce": secrets.token_hex(32),
        "created_at": _utc_text(now),
        "expires_at": _utc_text(now + timedelta(seconds=args.ttl_seconds)),
        "merge_sha": args.merge_sha,
        "active_bundle_sha256": active_digest,
        "recovery_bundle_sha256": recovery_digest,
        "window_starts_at": args.window_starts_at,
        "window_ends_at": args.window_ends_at,
        "owner_authorized": True,
        "docker_host": DOCKER_HOST,
        "vaults": [
            {
                "role": v["role"],
                "image": str(v["image"]),
                "size_bytes": v["size_bytes"],
                "mapper": str(v["mapper"]),
                "mount_root": str(v["mount_root"]),
                "volume": v["volume"],
                "mount_options": list(v["mount_options"]),
            }
            for v in VAULTS
        ],
        "protected_root_count": len(inspection["roots"]),
        "free_bytes": inspection["free_bytes"],
        "admission_remains_closed": True,
        "services_may_be_stopped_or_restarted": False,
        "cloudflare_change_permitted": False,
    }
    body["plan_id"] = _digest(body)
    _write_exclusive(plan_path, body)
    return {"status": "planned", "plan": str(plan_path), "plan_id": body["plan_id"], "confirmation": f"PROVISION-{body['plan_id'][:16]}"}


def _load_plan(path: Path) -> dict[str, Any]:
    _private_regular(path, "plan")
    plan = _json(path)
    plan_id = plan.get("plan_id")
    body = {k: v for k, v in plan.items() if k != "plan_id"}
    if not isinstance(plan_id, str) or _digest(body) != plan_id:
        raise ProvisionBlocked("plan digest is invalid")
    if plan.get("subpart") != SUBPART or plan.get("operation") != "provision-production-vaults":
        raise ProvisionBlocked("plan scope is invalid")
    if plan.get("owner_authorized") is not True:
        raise ProvisionBlocked("plan does not retain owner authorization")
    expected_vaults = [
        {
            "role": v["role"],
            "image": str(v["image"]),
            "size_bytes": v["size_bytes"],
            "mapper": str(v["mapper"]),
            "mount_root": str(v["mount_root"]),
            "volume": v["volume"],
            "mount_options": list(v["mount_options"]),
        }
        for v in VAULTS
    ]
    if plan.get("vaults") != expected_vaults:
        raise ProvisionBlocked("plan vault topology does not match the fixed production contract")
    if _utc_now() > _parse_time(str(plan.get("expires_at")), "plan expiry"):
        raise ProvisionBlocked("plan expired")
    return plan


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
    vault["mount_root"].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    vault["mount_root"].mkdir(exist_ok=True, mode=0o700)
    info = os.lstat(vault["mount_root"])
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ProvisionBlocked(f"{vault['role']}: mount root is unsafe")
    _run(["mount", "-o", ",".join(vault["mount_options"]), str(vault["mapper"]), str(vault["mount_root"])])


def _luks_metadata(vault: dict[str, Any]) -> dict[str, Any]:
    _run(["cryptsetup", "isLuks", "--type", "luks2", str(vault["image"])])
    raw = _run(["cryptsetup", "luksDump", "--dump-json-metadata", str(vault["image"])])
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProvisionError(f"{vault['role']}: cannot parse LUKS2 metadata") from exc
    keyslots = metadata.get("keyslots")
    if not isinstance(keyslots, dict) or len(keyslots) != 2:
        raise ProvisionBlocked(f"{vault['role']}: exactly two keyslots are required")
    for slot in keyslots.values():
        if not isinstance(slot, dict) or slot.get("type") != "luks2" or slot.get("key_size") != 64:
            raise ProvisionBlocked(f"{vault['role']}: keyslot contract drifted")
        kdf = slot.get("kdf")
        area = slot.get("area")
        if not isinstance(kdf, dict) or kdf.get("type") != "argon2id":
            raise ProvisionBlocked(f"{vault['role']}: keyslot PBKDF is not argon2id")
        if not isinstance(area, dict) or area.get("encryption") != "aes-xts-plain64":
            raise ProvisionBlocked(f"{vault['role']}: keyslot cipher drifted")
    return {"format": "LUKS2", "cipher": "aes-xts-plain64", "key_bits": 512, "pbkdf": "argon2id", "keyslot_count": 2}


def _verify_host_ready(root: Path) -> dict[str, Any]:
    contract = _load_contract(root)
    rows_by_role: dict[str, list[str]] = {v["role"]: [] for v in VAULTS}
    for row in contract["source_roots"]:
        rows_by_role[str(row["target_vault"])].append(str(row["target_subpath"]))
    result: list[dict[str, Any]] = []
    for vault in VAULTS:
        if not vault["mapper"].exists() or not stat.S_ISBLK(os.stat(vault["mapper"]).st_mode):
            raise ProvisionBlocked(f"{vault['role']}: mapper is not active")
        if " is active" not in _run(["cryptsetup", "status", vault["mapper_name"]]):
            raise ProvisionBlocked(f"{vault['role']}: cryptsetup status is not active")
        if _run(["blkid", "-o", "value", "-s", "TYPE", str(vault["mapper"])]) != "ext4":
            raise ProvisionBlocked(f"{vault['role']}: filesystem is not ext4")
        if _run(["blkid", "-o", "value", "-s", "LABEL", str(vault["mapper"])]) != vault["fs_label"]:
            raise ProvisionBlocked(f"{vault['role']}: filesystem label drifted")
        line = _run(["findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS", "--target", str(vault["mount_root"])])
        pieces = line.split(None, 2)
        if len(pieces) != 3 or os.path.realpath(pieces[0]) != os.path.realpath(vault["mapper"]) or pieces[1] != "ext4":
            raise ProvisionBlocked(f"{vault['role']}: mount source or filesystem drifted")
        options = set(pieces[2].split(","))
        if not set(vault["mount_options"]).issubset(options):
            raise ProvisionBlocked(f"{vault['role']}: mount options drifted")
        if vault["role"] == "project-execution-vault" and "noexec" in options:
            raise ProvisionBlocked("project execution vault must not be noexec")
        for name in rows_by_role[vault["role"]]:
            target = vault["mount_root"] / name
            if target.is_symlink() or not target.is_dir():
                raise ProvisionBlocked(f"{vault['role']}: target subpath missing or unsafe")
        result.append({"role": vault["role"], "mapper": str(vault["mapper"]), "mount_root": str(vault["mount_root"]), "subpath_count": len(rows_by_role[vault["role"]])})
    return {"status": "host-ready", "validation": "FR06B4_HOST_VAULTS_READY", "observed_at": _utc_text(), "vaults": result, "docker_inspected": False, "admission_opened": False}


def _verify_ready(root: Path) -> dict[str, Any]:
    host = _verify_host_ready(root)
    rows_by_role = {
        row["role"]: int(row["subpath_count"])
        for row in host["vaults"]
    }
    result: list[dict[str, Any]] = []
    for vault in VAULTS:
        inspected = json.loads(_run(["docker", "--host", DOCKER_HOST, "volume", "inspect", vault["volume"]]))[0]
        expected_options = {"type": "ext4", "device": str(vault["mapper"]), "o": ",".join(vault["mount_options"])}
        if inspected.get("Driver") != "local" or inspected.get("Options") != expected_options:
            raise ProvisionBlocked(f"{vault['role']}: Docker volume contract drifted")
        consumers = _run(["docker", "--host", DOCKER_HOST, "ps", "--filter", f"volume={vault['volume']}", "--format", "{{.ID}}"])
        if consumers:
            raise ProvisionBlocked(f"{vault['role']}: candidate volume has running consumers")
        result.append({"role": vault["role"], "mapper": str(vault["mapper"]), "mount_root": str(vault["mount_root"]), "volume": vault["volume"], "subpath_count": rows_by_role[vault["role"]]})
    return {"status": "ready", "validation": "FR06B4_VAULTS_READY", "observed_at": _utc_text(), "vaults": result, "admission_opened": False}


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "--host", DOCKER_HOST, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def unlock_vaults(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirmation != UNLOCK_CONFIRMATION:
        raise ProvisionBlocked("unlock confirmation is invalid")
    if os.geteuid() != 0:
        raise ProvisionBlocked("production unlock requires root")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]) != "tmpfs":
        raise ProvisionBlocked("/dev/shm is not tmpfs")
    if _docker_available():
        raise ProvisionBlocked("Docker must be stopped before production vault unlock")
    receipt_path = PRODUCTION_STATE / "provision-receipt.json"
    _private_regular(receipt_path, "provision receipt")
    receipt = _json(receipt_path)
    merge_sha = receipt.get("merge_sha")
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("subpart") != SUBPART
        or receipt.get("status") != "vaults_provisioned_admission_closed"
        or not isinstance(merge_sha, str)
    ):
        raise ProvisionBlocked("provision receipt is invalid")
    _git_descendant_gate(PRODUCTION_ROOT, merge_sha)
    for vault in VAULTS:
        info = _private_regular(vault["image"], f"{vault['role']} image")
        if info.st_size != vault["size_bytes"] or info.st_blocks * 512 < info.st_size:
            raise ProvisionBlocked(f"{vault['role']}: backing image size or allocation drifted")
        _luks_metadata(vault)
        if vault["mapper"].exists() or os.path.ismount(vault["mount_root"]):
            raise ProvisionBlocked(f"{vault['role']}: unlock requires a fully closed host state")
    active, _ = _bundle(args.active_bundle, "active")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(RUNTIME_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    directory = KEY_ROOT / ("unlock-" + secrets.token_hex(8))
    paths: list[Path] = []
    opened: list[str] = []
    mounted: list[Path] = []
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProvisionBlocked("another FR-06B4 operation holds the lock") from exc
        directory.mkdir(mode=0o700)
        for vault in VAULTS:
            key_path = _secret_file(directory, vault["mapper_name"] + ".active", active[vault["bundle_field"]])
            paths.append(key_path)
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(key_path), str(vault["image"]), vault["mapper_name"]])
            opened.append(vault["mapper_name"])
            _mount(vault)
            mounted.append(vault["mount_root"])
        ready = _verify_host_ready(PRODUCTION_ROOT)
        nonce = secrets.token_hex(8)
        unlock_receipt = PRODUCTION_STATE / "unlock-receipts" / f"unlock-{int(_utc_now().timestamp())}-{nonce}.json"
        _write_exclusive(
            unlock_receipt,
            {
                "schema_version": SCHEMA_VERSION,
                "subpart": SUBPART,
                "status": "vaults_unlocked_host_ready_docker_stopped",
                "merge_sha": merge_sha,
                "completed_at": _utc_text(),
                "host_validation": ready["validation"],
                "vault_count": len(VAULTS),
                "docker_started": False,
                "services_started_or_restarted": False,
                "key_material_persisted": False,
                "admission_opened": False,
            },
        )
        return {"status": "vaults_unlocked_host_ready_docker_stopped", "receipt": str(unlock_receipt), "vault_count": len(VAULTS)}
    except Exception:
        for mount_root in reversed(mounted):
            subprocess.run(["umount", str(mount_root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for mapper_name in reversed(opened):
            subprocess.run(["cryptsetup", "close", mapper_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
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
        os.close(lock_fd)


def apply_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load_plan(args.plan.resolve())
    if args.confirmation != f"PROVISION-{plan['plan_id'][:16]}" or args.confirm_production != SECOND_CONFIRMATION:
        raise ProvisionBlocked("dynamic or production confirmation is invalid")
    consumed = RUNTIME_ROOT / ("consumed-plan-" + str(plan["plan_id"]) + ".json")
    if consumed.exists():
        raise ProvisionBlocked("plan was already consumed")
    _validate_window(str(plan["window_starts_at"]), str(plan["window_ends_at"]), _utc_now())
    _git_gate(PRODUCTION_ROOT, str(plan["merge_sha"]))
    active, active_digest = _bundle(args.active_bundle, "active")
    recovery, recovery_digest = _bundle(args.recovery_bundle, "recovery")
    if active_digest != plan["active_bundle_sha256"] or recovery_digest != plan["recovery_bundle_sha256"]:
        raise ProvisionBlocked("key bundle changed after planning")
    _fresh_topology_gate()
    _legacy_gate(_load_contract(PRODUCTION_ROOT))
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = RUNTIME_ROOT / "operation.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    created_images: list[Path] = []
    opened: list[str] = []
    mounted: list[Path] = []
    volumes: list[str] = []
    secret_paths: list[Path] = []
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProvisionBlocked("another FR-06B4 operation holds the lock") from exc
        key_dir = KEY_ROOT / ("operation-" + str(plan["nonce"])[:16])
        key_dir.mkdir(mode=0o700)
        headers = RUNTIME_ROOT / "headers"
        headers.mkdir(mode=0o700)
        contract = _load_contract(PRODUCTION_ROOT)
        for vault in VAULTS:
            field = vault["bundle_field"]
            active_path = _secret_file(key_dir, vault["mapper_name"] + ".active", active[field])
            recovery_path = _secret_file(key_dir, vault["mapper_name"] + ".recovery", recovery[field])
            secret_paths.extend([active_path, recovery_path])
            vault["image"].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _run(["fallocate", "-l", str(vault["size_bytes"]), str(vault["image"])])
            os.chmod(vault["image"], 0o600)
            info = _private_regular(vault["image"], f"{vault['role']} image")
            if info.st_blocks * 512 < info.st_size:
                raise ProvisionBlocked(f"{vault['role']}: backing image is sparse")
            created_images.append(vault["image"])
            _run(["cryptsetup", "luksFormat", "--type", "luks2", "--cipher", "aes-xts-plain64", "--key-size", "512", "--pbkdf", "argon2id", "--batch-mode", "--key-file", str(active_path), str(vault["image"])])
            _run(["cryptsetup", "luksAddKey", str(vault["image"]), str(recovery_path), "--key-file", str(active_path)])
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active_path), str(vault["image"]), vault["mapper_name"]])
            opened.append(vault["mapper_name"])
            _run(["mkfs.ext4", "-q", "-L", vault["fs_label"], str(vault["mapper"])])
            header = headers / (vault["mapper_name"] + ".header")
            _run(["cryptsetup", "luksHeaderBackup", str(vault["image"]), "--header-backup-file", str(header)])
            os.chmod(header, 0o400)
            _mount(vault)
            mounted.append(vault["mount_root"])
            for row in contract["source_roots"]:
                if row.get("target_vault") == vault["role"]:
                    target = vault["mount_root"] / str(row["target_subpath"])
                    target.mkdir(mode=0o700)
            _run(["sync", "-f", str(vault["mount_root"])])
            _run(["docker", "--host", DOCKER_HOST, "volume", "create", "--driver", "local", "--opt", "type=ext4", "--opt", f"device={vault['mapper']}", "--opt", "o=" + ",".join(vault["mount_options"]), vault["volume"]])
            volumes.append(vault["volume"])
        ready = _verify_ready(PRODUCTION_ROOT)
        crypto = {v["role"]: _luks_metadata(v) for v in VAULTS}
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "subpart": SUBPART,
            "status": "vaults_provisioned_admission_closed",
            "plan_id": plan["plan_id"],
            "merge_sha": plan["merge_sha"],
            "completed_at": _utc_text(),
            "vaults": [
                {
                    "role": v["role"], "image": str(v["image"]), "size_bytes": v["size_bytes"],
                    "allocated_bytes": os.stat(v["image"]).st_blocks * 512,
                    "mapper": str(v["mapper"]), "mount_root": str(v["mount_root"]),
                    "volume": v["volume"], "mount_options": list(v["mount_options"]),
                    "header_staging_path": str(RUNTIME_ROOT / "headers" / (v["mapper_name"] + ".header")),
                    "header_sha256": _file_digest(RUNTIME_ROOT / "headers" / (v["mapper_name"] + ".header")),
                    "header_bytes": os.stat(RUNTIME_ROOT / "headers" / (v["mapper_name"] + ".header")).st_size,
                    "crypto": crypto[v["role"]],
                }
                for v in VAULTS
            ],
            "ready_validation": ready["validation"],
            "protected_root_count": 11,
            "key_material_persisted_on_unencrypted_root": False,
            "headers_staged_only_on_tmpfs": True,
            "services_stopped_or_restarted": False,
            "admission_opened": False,
            "cloudflare_changed": False,
            "next_gate": "upload and independently verify both header backups off-host, then prove both recovery keys",
        }
        receipt_path = PRODUCTION_STATE / "provision-receipt.json"
        _write_exclusive(receipt_path, receipt)
        _write_exclusive(consumed, {"plan_id": plan["plan_id"], "consumed_at": _utc_text()})
        return {"status": receipt["status"], "receipt": str(receipt_path), "header_count": 2, "ready": True}
    except Exception:
        for volume in reversed(volumes):
            subprocess.run(["docker", "--host", DOCKER_HOST, "volume", "rm", volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for mount_root in reversed(mounted):
            subprocess.run(["umount", str(mount_root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for mapper_name in reversed(opened):
            subprocess.run(["cryptsetup", "close", mapper_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for image in reversed(created_images):
            try:
                image.unlink()
            except OSError:
                pass
        raise
    finally:
        for path in secret_paths:
            try:
                path.unlink()
            except OSError:
                pass
        if secret_paths:
            try:
                secret_paths[0].parent.rmdir()
            except OSError:
                pass
        os.close(lock_fd)


def prove_recovery(args: argparse.Namespace) -> dict[str, Any]:
    _verify_ready(PRODUCTION_ROOT)
    active, _ = _bundle(args.active_bundle, "active")
    recovery, _ = _bundle(args.recovery_bundle, "recovery")
    if any(_run(["docker", "--host", DOCKER_HOST, "ps", "--filter", f"volume={v['volume']}", "--format", "{{.ID}}"]) for v in VAULTS):
        raise ProvisionBlocked("recovery proof requires zero candidate consumers")
    directory = KEY_ROOT / ("recovery-proof-" + secrets.token_hex(8))
    directory.mkdir(mode=0o700)
    paths: list[Path] = []
    checks: list[dict[str, Any]] = []
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(RUNTIME_ROOT / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProvisionBlocked("another FR-06B4 operation holds the lock") from exc
        for vault in VAULTS:
            field = vault["bundle_field"]
            active_path = _secret_file(directory, vault["mapper_name"] + ".active", active[field])
            recovery_path = _secret_file(directory, vault["mapper_name"] + ".recovery", recovery[field])
            paths += [active_path, recovery_path]
            _run(["umount", str(vault["mount_root"])])
            _run(["cryptsetup", "close", vault["mapper_name"]])
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(recovery_path), str(vault["image"]), vault["mapper_name"]])
            _mount(vault)
            _run(["umount", str(vault["mount_root"])])
            _run(["cryptsetup", "close", vault["mapper_name"]])
            _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active_path), str(vault["image"]), vault["mapper_name"]])
            _mount(vault)
            checks.append({"role": vault["role"], "recovery_open_passed": True, "active_reopen_passed": True})
        _verify_ready(PRODUCTION_ROOT)
        receipt = {"schema_version": 1, "subpart": SUBPART, "status": "independent_recovery_keys_proved", "observed_at": _utc_text(), "checks": checks, "candidate_consumers": 0, "key_material_persisted": False, "admission_opened": False}
        path = PRODUCTION_STATE / "recovery-proof.json"
        _write_exclusive(path, receipt)
        return {"status": receipt["status"], "receipt": str(path)}
    finally:
        for vault in VAULTS:
            try:
                field = vault["bundle_field"]
                if not vault["mapper"].exists():
                    fallback = directory / (vault["mapper_name"] + ".active")
                    if fallback.exists():
                        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(fallback), str(vault["image"]), vault["mapper_name"]])
                if vault["mapper"].exists() and not os.path.ismount(vault["mount_root"]):
                    _mount(vault)
            except Exception:
                # Preserve the original exception; status will remain fail-closed and
                # the operator can re-materialize the external active bundle.
                pass
        for path in paths:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
        os.close(lock_fd)


def wipe_inputs(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirmation != WIPE_CONFIRMATION:
        raise ProvisionBlocked("wipe confirmation is invalid")
    removed: list[str] = []
    for path in (args.active_bundle.resolve(strict=True), args.recovery_bundle.resolve(strict=True)):
        if path.parent != KEY_ROOT:
            raise ProvisionBlocked("refusing to remove a path outside the fixed tmpfs key root")
        _private_regular(path, "tmpfs key bundle")
        path.unlink()
        removed.append(path.name)
    return {"status": "tmpfs_key_inputs_removed", "removed_count": len(removed)}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--root", type=Path, default=PRODUCTION_ROOT)
    plan.add_argument("--merge-sha", required=True)
    plan.add_argument("--active-bundle", type=Path, required=True)
    plan.add_argument("--recovery-bundle", type=Path, required=True)
    plan.add_argument("--plan", type=Path, required=True)
    plan.add_argument("--ttl-seconds", type=int, default=600)
    plan.add_argument("--window-starts-at", required=True)
    plan.add_argument("--window-ends-at", required=True)
    plan.add_argument("--owner-authorized", action="store_true")
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--active-bundle", type=Path, required=True)
    apply.add_argument("--recovery-bundle", type=Path, required=True)
    apply.add_argument("--confirmation", required=True)
    apply.add_argument("--confirm-production", required=True)
    recovery = commands.add_parser("prove-recovery")
    recovery.add_argument("--active-bundle", type=Path, required=True)
    recovery.add_argument("--recovery-bundle", type=Path, required=True)
    unlock = commands.add_parser("unlock")
    unlock.add_argument("--active-bundle", type=Path, required=True)
    unlock.add_argument("--confirmation", required=True)
    status_cmd = commands.add_parser("status")
    required = status_cmd.add_mutually_exclusive_group()
    required.add_argument("--require-ready", action="store_true")
    required.add_argument("--require-host-ready", action="store_true")
    wipe = commands.add_parser("wipe-inputs")
    wipe.add_argument("--active-bundle", type=Path, required=True)
    wipe.add_argument("--recovery-bundle", type=Path, required=True)
    wipe.add_argument("--confirmation", required=True)
    return value


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
            result = unlock_vaults(args)
        elif args.command == "status":
            result = _verify_host_ready(PRODUCTION_ROOT) if args.require_host_ready else _verify_ready(PRODUCTION_ROOT)
        else:
            result = wipe_inputs(args)
    except ProvisionBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    except ProvisionError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
