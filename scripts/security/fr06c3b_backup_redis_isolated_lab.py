#!/usr/bin/env python3
"""Isolated FR-06C3B rehearsal for local-backup and Redis operations vaults.

Synthetic data only. Uses disposable file-backed LUKS2 images, tmpfs key files,
and disposable Redis containers. Production backup_data/redis_data are never read.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import time
from typing import Any

REDIS_IMAGE = "redis:7-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf"
MARKER = b"FR06C3B_SYNTHETIC_BACKUP_MARKER_4d7b0a91"


class LabError(RuntimeError):
    pass


def _run(argv: list[str], *, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LabError(f"command unavailable or timed out: {argv[0]}") from exc
    if check and result.returncode != 0:
        raise LabError(f"{argv[0]} failed with exit code {result.returncode}; output withheld")
    return result


def _manifest_module(root: Path):
    path = root / "scripts/security/fr06b_asset_copy_manifest.py"
    spec = importlib.util.spec_from_file_location(f"fr06c3b_manifest_{secrets.token_hex(4)}", path)
    if spec is None or spec.loader is None:
        raise LabError("cannot load retained safe manifest helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _production_identity() -> str:
    result = _run([
        "docker", "ps", "-a", "--filter", "label=com.docker.compose.project=web-dashboard",
        "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}",
    ])
    return hashlib.sha256("\n".join(sorted(result.stdout.splitlines())).encode()).hexdigest()


def _raw_contains(path: Path, marker: bytes) -> bool:
    overlap = max(0, len(marker) - 1)
    tail = b""
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(4 * 1024 * 1024)
            if not chunk:
                break
            data = tail + chunk
            if marker in data:
                return True
            tail = data[-overlap:] if overlap else b""
    return False


def _secret(path: Path) -> None:
    path.write_bytes(os.urandom(64))
    os.chmod(path, 0o600)


def _format_vault(image: Path, mapper_name: str, mount_root: Path, label: str, active: Path, recovery: Path, wrong: Path) -> tuple[Path, bool]:
    _run(["fallocate", "-l", "96M", str(image)])
    os.chmod(image, 0o600)
    _run([
        "cryptsetup", "luksFormat", "--type", "luks2", "--cipher", "aes-xts-plain64",
        "--key-size", "512", "--pbkdf", "argon2id", "--batch-mode", "--key-file", str(active), str(image),
    ])
    _run(["cryptsetup", "luksAddKey", str(image), str(recovery), "--key-file", str(active)])
    wrong_result = _run([
        "cryptsetup", "open", "--type", "luks", "--key-file", str(wrong), str(image), mapper_name,
    ], check=False)
    wrong_rejected = wrong_result.returncode != 0
    if not wrong_rejected:
        _run(["cryptsetup", "close", mapper_name], check=False)
        raise LabError("wrong LUKS key was unexpectedly accepted")
    _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active), str(image), mapper_name])
    mapper = Path("/dev/mapper") / mapper_name
    _run(["mkfs.ext4", "-q", "-L", label, str(mapper)])
    mount_root.mkdir(mode=0o700)
    _run(["mount", "-o", "nodev,nosuid,noexec", str(mapper), str(mount_root)])
    return mapper, wrong_rejected


def _reopen(image: Path, mapper_name: str, mount_root: Path, key: Path) -> Path:
    _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(key), str(image), mapper_name])
    mapper = Path("/dev/mapper") / mapper_name
    _run(["mount", "-o", "nodev,nosuid,noexec", str(mapper), str(mount_root)])
    return mapper


def _close(mapper_name: str, mount_root: Path) -> None:
    if os.path.ismount(mount_root):
        _run(["umount", str(mount_root)])
    if (Path("/dev/mapper") / mapper_name).exists():
        _run(["cryptsetup", "close", mapper_name])


def _wait_redis(name: str) -> None:
    for _ in range(30):
        result = _run(["docker", "exec", name, "redis-cli", "ping"], check=False, timeout=10)
        if result.returncode == 0 and result.stdout.strip() == "PONG":
            return
        time.sleep(0.5)
    raise LabError("isolated Redis did not become ready")


def _start_redis(name: str, data_root: Path) -> None:
    _run([
        "docker", "run", "-d", "--rm", "--name", name, "--network", "none",
        "--user", "999:1000", "--mount", f"type=bind,src={data_root},dst=/data",
        REDIS_IMAGE, "redis-server", "--appendonly", "yes", "--appendfsync", "everysec",
        "--save", "", "--protected-mode", "no", "--dir", "/data",
    ])
    _wait_redis(name)


def _stop_redis(name: str) -> None:
    _run(["docker", "stop", "-t", "20", name], check=False, timeout=30)


def _dbsize(name: str) -> int:
    result = _run(["docker", "exec", name, "redis-cli", "DBSIZE"])
    return int(result.stdout.strip())


def run_lab(root: Path) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise LabError("isolated C3B rehearsal requires root")
    for command in ("docker", "cryptsetup", "mkfs.ext4", "mount", "umount", "rsync", "fallocate", "findmnt"):
        if shutil.which(command) is None:
            raise LabError(f"required command missing: {command}")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]).stdout.strip() != "tmpfs":
        raise LabError("/dev/shm must be tmpfs")

    manifest = _manifest_module(root)
    nonce = secrets.token_hex(6)
    sandbox = Path(f"/var/tmp/aionex-fr06c3b-lab-{nonce}")
    source = Path(f"/dev/shm/aionex-fr06c3b-source-{nonce}")
    key_dir = Path(f"/dev/shm/aionex-fr06c3b-keys-{nonce}")
    backup_image = sandbox / "local-backup-vault.luks2"
    ops_image = sandbox / "operations-vault.luks2"
    backup_mount = sandbox / "backup-target"
    ops_mount = sandbox / "ops-target"
    backup_mapper = f"aionex-fr06c3b-backup-{nonce}"
    ops_mapper = f"aionex-fr06c3b-ops-{nonce}"
    redis1 = f"aionex-fr06c3b-redis1-{nonce}"
    redis2 = f"aionex-fr06c3b-redis2-{nonce}"
    redis3 = f"aionex-fr06c3b-redis3-{nonce}"
    keys = {name: key_dir / name for name in (
        "backup.active", "backup.recovery", "backup.wrong",
        "ops.active", "ops.recovery", "ops.wrong",
    )}
    prod_before = _production_identity()
    backup_wrong = ops_wrong = False
    backup_recovery_match = False
    backup_active_reopen_match = False
    redis_initial_empty = False
    redis_persisted_before_reconcile = False
    redis_empty_after_reconcile = False
    redis_empty_after_active_reopen = False
    closed_marker_absent = False
    backup_summary: dict[str, Any] = {}

    try:
        sandbox.mkdir(mode=0o700)
        source.mkdir(mode=0o700)
        key_dir.mkdir(mode=0o700)
        for path in keys.values():
            _secret(path)

        # Synthetic local backup source only.
        (source / "nested").mkdir(mode=0o700)
        (source / "database.dump").write_bytes(MARKER + b"\n" + os.urandom(4096))
        (source / "nested" / "manifest.json").write_text('{"synthetic":true}\n', encoding="utf-8")
        (source / "nested" / "restore.txt").write_text("isolated-recovery-proof\n", encoding="utf-8")
        for p in (source / "database.dump", source / "nested" / "manifest.json", source / "nested" / "restore.txt"):
            os.chmod(p, 0o600)

        _, backup_wrong = _format_vault(
            backup_image, backup_mapper, backup_mount, "AIOS-C3B-BACKUP",
            keys["backup.active"], keys["backup.recovery"], keys["backup.wrong"],
        )
        target = backup_mount / "backups"
        target.mkdir(mode=0o700)
        source_before = manifest.build_manifest(source)
        _run([
            "rsync", "-a", "--delete", "--numeric-ids", "--safe-links", "--no-devices", "--no-specials",
            str(source) + "/", str(target) + "/",
        ])
        source_after = manifest.build_manifest(source)
        candidate = manifest.build_manifest(target)
        if source_before["entries"] != source_after["entries"] or source_after["entries"] != candidate["entries"]:
            raise LabError("synthetic local-backup stable copy mismatch")
        backup_summary = dict(candidate["summary"])
        _run(["sync", "-f", str(backup_mount)])
        _close(backup_mapper, backup_mount)
        closed_marker_absent = not _raw_contains(backup_image, MARKER)
        if not closed_marker_absent:
            raise LabError("closed encrypted backup image exposed synthetic marker")

        _reopen(backup_image, backup_mapper, backup_mount, keys["backup.recovery"])
        recovered = manifest.build_manifest(backup_mount / "backups")
        backup_recovery_match = recovered["entries"] == source_after["entries"]
        if not backup_recovery_match:
            raise LabError("backup recovery-key manifest mismatch")
        _close(backup_mapper, backup_mount)
        _reopen(backup_image, backup_mapper, backup_mount, keys["backup.active"])
        active_again = manifest.build_manifest(backup_mount / "backups")
        backup_active_reopen_match = active_again["entries"] == source_after["entries"]
        if not backup_active_reopen_match:
            raise LabError("backup active-key reopen manifest mismatch")
        _close(backup_mapper, backup_mount)

        # Operations vault: do not copy any legacy Redis AOF. Start empty, then
        # prove persisted volatile state can be explicitly flushed/reconciled.
        _, ops_wrong = _format_vault(
            ops_image, ops_mapper, ops_mount, "AIOS-C3B-OPS",
            keys["ops.active"], keys["ops.recovery"], keys["ops.wrong"],
        )
        redis_root = ops_mount / "redis"
        redis_root.mkdir(mode=0o700)
        os.chown(redis_root, 999, 1000)
        _start_redis(redis1, redis_root)
        redis_initial_empty = _dbsize(redis1) == 0
        if not redis_initial_empty:
            raise LabError("isolated Redis candidate did not start empty")
        _run(["docker", "exec", redis1, "redis-cli", "SET", "fr06c3b:volatile", "synthetic"])
        if _dbsize(redis1) != 1:
            raise LabError("isolated Redis synthetic volatile key was not written")
        _stop_redis(redis1)
        _run(["sync", "-f", str(ops_mount)])
        _close(ops_mapper, ops_mount)

        _reopen(ops_image, ops_mapper, ops_mount, keys["ops.recovery"])
        _start_redis(redis2, ops_mount / "redis")
        redis_persisted_before_reconcile = _dbsize(redis2) == 1
        if not redis_persisted_before_reconcile:
            raise LabError("isolated Redis AOF persistence proof failed")
        _run(["docker", "exec", redis2, "redis-cli", "FLUSHALL", "SYNC"])
        redis_empty_after_reconcile = _dbsize(redis2) == 0
        if not redis_empty_after_reconcile:
            raise LabError("isolated Redis reconciliation flush failed")
        _stop_redis(redis2)
        _run(["sync", "-f", str(ops_mount)])
        _close(ops_mapper, ops_mount)

        _reopen(ops_image, ops_mapper, ops_mount, keys["ops.active"])
        _start_redis(redis3, ops_mount / "redis")
        redis_empty_after_active_reopen = _dbsize(redis3) == 0
        if not redis_empty_after_active_reopen:
            raise LabError("reconciled Redis state did not remain empty after reopen")
        _stop_redis(redis3)
        _close(ops_mapper, ops_mount)

        prod_after = _production_identity()
        if prod_before != prod_after:
            raise LabError("production container identity changed during isolated rehearsal")

        return {
            "schema_version": 1,
            "subpart": "FR-06C3B",
            "status": "isolated_backup_redis_reconciliation_pass",
            "production_backup_data_used": False,
            "production_redis_data_used": False,
            "production_mutation_performed": False,
            "production_container_identity_unchanged": True,
            "keys_only_on_tmpfs": True,
            "local_backup_vault": {
                "luks2": True,
                "cipher": "aes-xts-plain64",
                "key_bits": 512,
                "pbkdf": "argon2id",
                "wrong_key_rejected": backup_wrong,
                "stable_copy_manifest_match": True,
                "recovery_key_manifest_match": backup_recovery_match,
                "active_key_reopen_manifest_match": backup_active_reopen_match,
                "closed_raw_plaintext_marker_absent": closed_marker_absent,
                "regular_files": int(backup_summary["regular_files"]),
                "payload_bytes": int(backup_summary["payload_bytes"]),
                "aggregate_sha256": str(backup_summary["aggregate_sha256"]),
            },
            "operations_vault": {
                "luks2": True,
                "wrong_key_rejected": ops_wrong,
                "legacy_redis_aof_copied": False,
                "redis_started_empty": redis_initial_empty,
                "synthetic_volatile_state_persisted_before_reconcile": redis_persisted_before_reconcile,
                "explicit_reconciliation_flush_passed": redis_empty_after_reconcile,
                "redis_empty_after_active_key_reopen": redis_empty_after_active_reopen,
                "redis_is_disaster_recovery_authority": False,
            },
            "temporary_resources_removed": True,
            "production_cutover_authorized": False,
            "cloudflare_changed": False,
        }
    finally:
        for name in (redis1, redis2, redis3):
            _stop_redis(name)
        for mapper_name, mount_root in ((backup_mapper, backup_mount), (ops_mapper, ops_mount)):
            try:
                _close(mapper_name, mount_root)
            except Exception:
                pass
        shutil.rmtree(source, ignore_errors=True)
        shutil.rmtree(key_dir, ignore_errors=True)
        shutil.rmtree(sandbox, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_lab(args.root.resolve())
        if args.output:
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except LabError as exc:
        print(f"FR06C3B_ISOLATED_LAB_FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
