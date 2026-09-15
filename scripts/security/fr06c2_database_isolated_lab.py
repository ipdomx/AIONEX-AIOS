#!/usr/bin/env python3
"""Isolated FR-06C2 physical PostgreSQL migration/recovery rehearsal.

Uses synthetic PostgreSQL data, a disposable file-backed LUKS2 vault, temporary
Docker resources, and tmpfs keys. It never reads or mutates production PGDATA.
"""
from __future__ import annotations

import argparse
import hashlib
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

IMAGE = "aionex-aios-postgres:16-hardened"
MARKER = "FR06C2_SYNTHETIC_PLAINTEXT_MARKER_7f07d8fd"


class LabError(RuntimeError):
    pass


def _run(argv: list[str], *, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LabError(f"command unavailable or timed out: {argv[0]}") from exc
    if check and result.returncode != 0:
        raise LabError(f"{' '.join(argv[:4])} failed with exit code {result.returncode}; output withheld")
    return result


def _production_identity() -> str:
    result = _run([
        "docker", "ps", "-a", "--filter", "label=com.docker.compose.project=web-dashboard",
        "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}",
    ])
    return hashlib.sha256("\n".join(sorted(result.stdout.splitlines())).encode()).hexdigest()


def _manifest(root: Path) -> dict[str, Any]:
    rows: list[tuple[str, str, int, int, int, str]] = []
    files = 0
    dirs = 0
    payload = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        info = os.lstat(path)
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            dirs += 1
            rows.append((relative, "d", mode, info.st_uid, info.st_gid, ""))
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise LabError("hard-linked file rejected by isolated manifest")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            files += 1
            payload += info.st_size
            rows.append((relative, "f", mode, info.st_uid, info.st_gid, f"{info.st_size}:{digest.hexdigest()}"))
        else:
            raise LabError("non-regular PGDATA entry rejected by isolated manifest")
    aggregate = hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return {"directories": dirs, "regular_files": files, "payload_bytes": payload, "aggregate_sha256": aggregate}


def _wait_ready(name: str) -> None:
    for _ in range(45):
        result = _run(["docker", "exec", name, "pg_isready", "-h", "/tmp", "-U", "postgres", "-d", "postgres", "-q"], check=False, timeout=10)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise LabError("isolated PostgreSQL did not become ready")


def _start(name: str, mount: str) -> None:
    _run([
        "docker", "run", "-d", "--rm", "--name", name, "--network", "none",
        "--entrypoint", "postgres", "--user", "70:70", "-v", f"{mount}:/var/lib/postgresql/data",
        IMAGE, "-D", "/var/lib/postgresql/data", "-c", "listen_addresses=", "-c", "unix_socket_directories=/tmp",
    ])
    _wait_ready(name)


def _validate_row(name: str) -> None:
    result = _run([
        "docker", "exec", name, "psql", "-h", "/tmp", "-U", "postgres", "-d", "postgres",
        "-Atqc", "select count(*) from fr06c2_probe where payload='vault-ok'",
    ])
    if result.stdout.strip() != "1":
        raise LabError("synthetic row validation failed")


def _stop(name: str) -> None:
    _run(["docker", "stop", "-t", "30", name], check=False, timeout=45)
    _run(["docker", "rm", "-f", name], check=False, timeout=20)
    for _ in range(20):
        if _run(["docker", "inspect", name], check=False, timeout=10).returncode != 0:
            return
        time.sleep(0.1)
    raise LabError("isolated container did not disappear after stop")


def _raw_contains(path: Path, marker: bytes) -> bool:
    overlap = max(0, len(marker) - 1)
    tail = b""
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                break
            data = tail + chunk
            if marker in data:
                return True
            tail = data[-overlap:] if overlap else b""
    return False


def run_lab(root: Path) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise LabError("isolated LUKS rehearsal requires root")
    for command in ("docker", "cryptsetup", "mkfs.ext4", "mount", "umount", "rsync", "fallocate"):
        if shutil.which(command) is None:
            raise LabError(f"required command missing: {command}")
    if _run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]).stdout.strip() != "tmpfs":
        raise LabError("/dev/shm must be tmpfs")

    nonce = secrets.token_hex(6)
    sandbox = Path(f"/var/tmp/aionex-fr06c2-lab-{nonce}")
    source = Path(f"/dev/shm/aionex-fr06c2-source-{nonce}")
    key_dir = Path(f"/dev/shm/aionex-fr06c2-keys-{nonce}")
    image = sandbox / "database-vault.luks2"
    mount_root = sandbox / "target"
    mapper_name = f"aionex-fr06c2-lab-{nonce}"
    mapper = Path("/dev/mapper") / mapper_name
    volume = f"aionex-fr06c2-lab-db-{nonce}"
    source_container = f"aionex-fr06c2-source-{nonce}"
    target_container = f"aionex-fr06c2-target-{nonce}"
    active = key_dir / "active.key"
    recovery = key_dir / "recovery.key"
    wrong = key_dir / "wrong.key"
    prod_before = _production_identity()
    source_manifest: dict[str, Any] | None = None
    target_manifest: dict[str, Any] | None = None
    wrong_key_rejected = False
    recovery_open_passed = False
    row_after_active_open = False
    row_after_recovery_open = False
    closed_marker_absent = False
    cluster_state = ""
    pg_wal_present = False

    try:
        sandbox.mkdir(mode=0o700)
        source.mkdir(mode=0o700)
        key_dir.mkdir(mode=0o700)
        os.chown(source, 70, 70)
        for path in (active, recovery, wrong):
            path.write_bytes(os.urandom(64))
            os.chmod(path, 0o600)

        _run([
            "docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", "--user", "70:70",
            "-v", f"{source}:/var/lib/postgresql/data", IMAGE, "-lc",
            "initdb -D /var/lib/postgresql/data --auth=trust --username=postgres >/dev/null",
        ])
        _start(source_container, str(source))
        _run([
            "docker", "exec", source_container, "psql", "-h", "/tmp", "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-Atqc",
            "create table fr06c2_probe(payload text not null); insert into fr06c2_probe values ('vault-ok'); checkpoint; select count(*) from fr06c2_probe;",
        ])
        _stop(source_container)
        state = _run([
            "docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", "--user", "70:70",
            "-v", f"{source}:/var/lib/postgresql/data:ro", IMAGE, "-lc",
            "pg_controldata /var/lib/postgresql/data | sed -n 's/^Database cluster state:[[:space:]]*//p'",
        ])
        cluster_state = state.stdout.strip()
        if cluster_state != "shut down":
            raise LabError("source PostgreSQL cluster did not reach clean shutdown")
        marker_path = source / ".fr06c2-synthetic-marker"
        marker_path.write_text(MARKER, encoding="utf-8")
        os.chmod(marker_path, 0o600)
        os.chown(marker_path, 70, 70)
        pg_wal_present = (source / "pg_wal").is_dir() and any((source / "pg_wal").iterdir())
        if not pg_wal_present:
            raise LabError("synthetic PGDATA has no pg_wal content")
        source_manifest = _manifest(source)

        _run(["fallocate", "-l", str(1024**3), str(image)])
        os.chmod(image, 0o600)
        _run([
            "cryptsetup", "luksFormat", "--batch-mode", "--type", "luks2", "--cipher", "aes-xts-plain64",
            "--key-size", "512", "--pbkdf", "argon2id", "--key-file", str(active), str(image),
        ], timeout=180)
        _run(["cryptsetup", "luksAddKey", str(image), str(recovery), "--key-file", str(active)], timeout=180)
        test_wrong = _run(["cryptsetup", "open", "--test-passphrase", "--key-file", str(wrong), str(image)], check=False, timeout=60)
        wrong_key_rejected = test_wrong.returncode != 0
        if not wrong_key_rejected:
            raise LabError("wrong key unexpectedly opened isolated LUKS2 image")
        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(active), str(image), mapper_name], timeout=180)
        _run(["mkfs.ext4", "-q", "-L", "AIOS_DB_LAB", str(mapper)], timeout=120)
        mount_root.mkdir(mode=0o700)
        _run(["mount", "-o", "nodev,nosuid,noexec", str(mapper), str(mount_root)])
        _run(["rsync", "-aHAX", "--numeric-ids", "--delete", f"{source}/", f"{mount_root}/"], timeout=180)
        _run(["sync", "-f", str(mount_root)])
        target_manifest = _manifest(mount_root)
        if source_manifest != target_manifest:
            raise LabError("offline PGDATA source/candidate manifests differ")
        _run(["umount", str(mount_root)])

        _run([
            "docker", "volume", "create", "--driver", "local", "--opt", "type=ext4", "--opt", f"device={mapper}",
            "--opt", "o=nodev,nosuid,noexec", volume,
        ])
        _start(target_container, volume)
        _validate_row(target_container)
        row_after_active_open = True
        _stop(target_container)
        _run(["docker", "volume", "rm", volume])
        _run(["cryptsetup", "close", mapper_name])
        closed_marker_absent = not _raw_contains(image, MARKER.encode())
        if not closed_marker_absent:
            raise LabError("closed LUKS2 image exposed synthetic plaintext marker")

        _run(["cryptsetup", "open", "--type", "luks", "--key-file", str(recovery), str(image), mapper_name], timeout=180)
        recovery_open_passed = True
        _run([
            "docker", "volume", "create", "--driver", "local", "--opt", "type=ext4", "--opt", f"device={mapper}",
            "--opt", "o=nodev,nosuid,noexec", volume,
        ])
        _start(target_container, volume)
        _validate_row(target_container)
        row_after_recovery_open = True
        _stop(target_container)
        _run(["docker", "volume", "rm", volume])
        _run(["cryptsetup", "close", mapper_name])

        prod_after = _production_identity()
        if prod_before != prod_after:
            raise LabError("production container identity changed during isolated rehearsal")
        return {
            "schema_version": 1,
            "subpart": "FR-06C2A",
            "status": "isolated_database_physical_migration_recovery_pass",
            "postgres_image": IMAGE,
            "production_pgdata_used": False,
            "production_mutation_performed": False,
            "production_container_identity_unchanged": True,
            "source_cluster_state_before_copy": cluster_state,
            "online_raw_copy_performed": False,
            "pg_wal_included": pg_wal_present,
            "source_manifest": source_manifest,
            "candidate_manifest": target_manifest,
            "source_candidate_manifest_match": source_manifest == target_manifest,
            "luks2": True,
            "cipher": "aes-xts-plain64",
            "key_bits": 512,
            "pbkdf": "argon2id",
            "wrong_key_rejected": wrong_key_rejected,
            "independent_recovery_key_open_passed": recovery_open_passed,
            "row_validated_after_active_open": row_after_active_open,
            "row_validated_after_recovery_open": row_after_recovery_open,
            "closed_raw_plaintext_marker_absent": closed_marker_absent,
            "keys_only_on_tmpfs": True,
            "temporary_resources_removed": True,
            "production_cutover_authorized": False,
        }
    finally:
        _stop(source_container)
        _stop(target_container)
        _run(["docker", "volume", "rm", "-f", volume], check=False)
        if os.path.ismount(mount_root):
            _run(["umount", str(mount_root)], check=False)
        if mapper.exists():
            _run(["cryptsetup", "close", mapper_name], check=False)
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
    except LabError as exc:
        print(f"FR06C2_DATABASE_LAB_FAIL: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
