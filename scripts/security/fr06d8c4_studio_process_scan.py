#!/usr/bin/env python3
"""Prove the absence of proc-visible references to current Studio volume objects.

This is a scoped, read-only host observation. It consumes accepted C4B1/C4B2
receipts, rechecks the exact running writer/reader container epoch, inventories
the current Studio volume without following symlinks, and scans /proc twice for
FD/cwd/root/exe/mmap references to any current object in that inventory.

It does not stop/restart containers, change admission/database state, unlink,
rename, chmod, write, or authorize cleanup. The resulting proof is Studio-scoped
and explicitly is not full-host process drain or full-host closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WRITER_SCHEMA = "aionex.studio-writer-epoch.v1"
RUNTIME_SCHEMA = "aionex.studio-runtime-drain.v1"
SCHEMA = "aionex.studio-process-scan.v1"
PROJECT = "web-dashboard"
DESTINATION = "/var/lib/aionex/studio-assets"
WRITERS = frozenset({"backend", "studio-worker"})
READERS = frozenset({"backup-worker"})
ONE_SHOT = "backup-asset-root-init"
MAX_ENTRIES = 200_000
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class ProcessScanBlocked(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ProcessScanBlocked(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProcessScanBlocked(f"{label} is malformed") from exc
    if parsed.utcoffset() is None:
        raise ProcessScanBlocked(f"{label} lacks timezone")
    return parsed.astimezone(UTC)


def _digest_receipt(value: dict[str, Any], label: str) -> str:
    digest = value.get("receipt_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ProcessScanBlocked(f"{label} receipt digest is missing")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if _sha(body) != digest:
        raise ProcessScanBlocked(f"{label} receipt digest differs")
    return digest


def _writer_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProcessScanBlocked("writer receipt is malformed")
    required = {
        "schema", "observed_at", "merge_sha", "admission", "studio_snapshot",
        "writers", "readers", "studio_volume_source",
        "application_writer_epoch_verified", "process_drain_verified",
        "host_process_scan_verified", "backup_cycle_drain_verified",
        "cleanup_authorized", "filesystem_mutation_performed",
        "full_host_closure", "receipt_sha256",
    }
    if set(value) != required:
        raise ProcessScanBlocked("writer receipt fields are not exact")
    _digest_receipt(value, "writer")
    if (
        value["schema"] != WRITER_SCHEMA
        or value["application_writer_epoch_verified"] is not True
        or value["process_drain_verified"] is not False
        or value["host_process_scan_verified"] is not False
        or value["backup_cycle_drain_verified"] is not False
        or value["cleanup_authorized"] is not False
        or value["filesystem_mutation_performed"] is not False
        or value["full_host_closure"] is not False
        or not isinstance(value["studio_volume_source"], str)
        or not value["studio_volume_source"].startswith("/")
    ):
        raise ProcessScanBlocked("writer receipt boundary is invalid")
    _time(value["observed_at"], "writer observed_at")
    return value


def _runtime_receipt(value: Any, writer: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProcessScanBlocked("runtime receipt is malformed")
    required = {
        "schema", "observed_at", "writer_receipt_sha256", "merge_sha",
        "operation_id", "generation", "studio_volume_source",
        "writer_container_ids", "backup_snapshot_sha256",
        "application_writer_epoch_verified", "runtime_container_epoch_stable",
        "backup_cycle_drain_verified", "process_drain_verified",
        "host_process_scan_verified", "cleanup_authorized",
        "filesystem_mutation_performed", "full_host_closure", "receipt_sha256",
    }
    if set(value) != required:
        raise ProcessScanBlocked("runtime receipt fields are not exact")
    _digest_receipt(value, "runtime")
    admission = writer.get("admission")
    if not isinstance(admission, dict):
        raise ProcessScanBlocked("writer admission is malformed")
    if (
        value["schema"] != RUNTIME_SCHEMA
        or value["writer_receipt_sha256"] != writer["receipt_sha256"]
        or value["merge_sha"] != writer["merge_sha"]
        or value["operation_id"] != admission.get("operation_id")
        or value["generation"] != admission.get("generation")
        or value["studio_volume_source"] != writer["studio_volume_source"]
        or value["application_writer_epoch_verified"] is not True
        or value["runtime_container_epoch_stable"] is not True
        or value["backup_cycle_drain_verified"] is not True
        or value["process_drain_verified"] is not False
        or value["host_process_scan_verified"] is not False
        or value["cleanup_authorized"] is not False
        or value["filesystem_mutation_performed"] is not False
        or value["full_host_closure"] is not False
    ):
        raise ProcessScanBlocked("runtime receipt does not extend the writer boundary")
    if _time(value["observed_at"], "runtime observed_at") <= _time(
        writer["observed_at"], "writer observed_at"
    ):
        raise ProcessScanBlocked("runtime receipt predates writer receipt")
    return value


def _mount(item: dict[str, Any]) -> dict[str, Any] | None:
    mounts = item.get("Mounts")
    if not isinstance(mounts, list):
        raise ProcessScanBlocked("container mount inventory is missing")
    matches = [
        mount for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == DESTINATION
    ]
    if len(matches) > 1:
        raise ProcessScanBlocked("container has ambiguous Studio mounts")
    return matches[0] if matches else None


def _service(item: dict[str, Any]) -> str:
    labels = (item.get("Config") or {}).get("Labels") or {}
    value = labels.get("com.docker.compose.service")
    if not isinstance(value, str) or not value:
        raise ProcessScanBlocked("compose service identity is missing")
    return value


def _current_epoch(
    writer: dict[str, Any],
    runtime: dict[str, Any],
    containers: list[dict[str, Any]],
) -> None:
    running: list[dict[str, Any]] = []
    for item in containers:
        if not isinstance(item, dict):
            raise ProcessScanBlocked("container inspection is malformed")
        config, state = item.get("Config") or {}, item.get("State") or {}
        labels = config.get("Labels") or {}
        if labels.get("com.docker.compose.project") != PROJECT:
            continue
        if state.get("Running") is not True or state.get("Status") != "running":
            continue
        if not isinstance(item.get("Id"), str) or not item["Id"]:
            raise ProcessScanBlocked("running container id is missing")
        _service(item)
        running.append(item)

    by_service: dict[str, list[dict[str, Any]]] = {}
    mounted: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for item in running:
        service = _service(item)
        by_service.setdefault(service, []).append(item)
        mount = _mount(item)
        if mount is not None:
            mounted.append((service, item, mount))

    if by_service.get(ONE_SHOT):
        raise ProcessScanBlocked("one-shot Studio root initializer is running")

    expected_writers = {
        row["service"]: row
        for row in writer.get("writers", [])
        if isinstance(row, dict) and isinstance(row.get("service"), str)
    }
    if set(expected_writers) != WRITERS or len(writer["writers"]) != len(WRITERS):
        raise ProcessScanBlocked("writer receipt writer set differs")
    if sorted(runtime.get("writer_container_ids", [])) != sorted(
        row.get("container_id") for row in expected_writers.values()
    ):
        raise ProcessScanBlocked("runtime writer identity set differs")

    for service in sorted(WRITERS):
        rows = by_service.get(service, [])
        if len(rows) != 1:
            raise ProcessScanBlocked(f"current writer count differs: {service}")
        item, expected = rows[0], expected_writers[service]
        if (
            item["Id"] != expected.get("container_id")
            or item.get("RestartCount") != expected.get("restart_count")
            or _time((item.get("State") or {}).get("StartedAt"), service)
            != _time(expected.get("started_at"), service)
        ):
            raise ProcessScanBlocked(f"current writer epoch changed: {service}")

    expected_readers = {
        row["service"]: row
        for row in writer.get("readers", [])
        if isinstance(row, dict) and isinstance(row.get("service"), str)
    }
    if set(expected_readers) != READERS or len(writer["readers"]) != len(READERS):
        raise ProcessScanBlocked("writer receipt reader set differs")
    for service in sorted(READERS):
        rows = by_service.get(service, [])
        if len(rows) != 1:
            raise ProcessScanBlocked(f"current reader count differs: {service}")
        expected = expected_readers[service]
        if (
            rows[0]["Id"] != expected.get("container_id")
            or rows[0].get("RestartCount") != expected.get("restart_count")
            or _time((rows[0].get("State") or {}).get("StartedAt"), service)
            != _time(expected.get("started_at"), service)
        ):
            raise ProcessScanBlocked(f"current reader epoch changed: {service}")

    source = writer["studio_volume_source"]
    for service, _, mount in mounted:
        if mount.get("Source") != source or type(mount.get("RW")) is not bool:
            raise ProcessScanBlocked("current Studio volume identity changed")
        if mount["RW"] and service not in WRITERS:
            raise ProcessScanBlocked(f"unexpected current Studio writer: {service}")
        if not mount["RW"] and service not in READERS:
            raise ProcessScanBlocked(f"unexpected current Studio reader: {service}")


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
        info.st_size, info.st_nlink, info.st_mtime_ns, info.st_ctime_ns,
    )


def _inventory(root: Path) -> dict[str, tuple[int, ...]]:
    if not root.is_absolute() or root == Path("/") or ".." in root.parts:
        raise ProcessScanBlocked("Studio volume root is invalid")
    try:
        linked = os.lstat(root)
    except OSError as exc:
        raise ProcessScanBlocked("Studio volume root is unavailable") from exc
    if not stat.S_ISDIR(linked.st_mode) or stat.S_ISLNK(linked.st_mode):
        raise ProcessScanBlocked("Studio volume root is not a real directory")
    root_device = linked.st_dev
    snapshot: dict[str, tuple[int, ...]] = {}
    count = 0

    def visit(descriptor: int, relative: tuple[str, ...]) -> None:
        nonlocal count
        directory_before = os.fstat(descriptor)
        if directory_before.st_dev != root_device:
            raise ProcessScanBlocked("nested filesystem inside Studio volume")
        key = "/".join(relative) if relative else "."
        snapshot[key] = _fingerprint(directory_before)
        count += 1
        if count > MAX_ENTRIES:
            raise ProcessScanBlocked("Studio volume inventory exceeds limit")
        try:
            with os.scandir(descriptor) as entries:
                names = sorted(entry.name for entry in entries)
        except OSError as exc:
            raise ProcessScanBlocked("Studio directory enumeration failed") from exc
        for name in names:
            try:
                before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as exc:
                raise ProcessScanBlocked("Studio entry stat failed") from exc
            if before.st_dev != root_device:
                raise ProcessScanBlocked("nested filesystem inside Studio volume")
            if stat.S_ISLNK(before.st_mode) or not (
                stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode)
            ):
                raise ProcessScanBlocked("Studio volume contains unsafe entry type")
            child_relative = (*relative, name)
            child_key = "/".join(child_relative)
            snapshot[child_key] = _fingerprint(before)
            count += 1
            if count > MAX_ENTRIES:
                raise ProcessScanBlocked("Studio volume inventory exceeds limit")
            if stat.S_ISDIR(before.st_mode):
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
                try:
                    if _fingerprint(os.fstat(child)) != _fingerprint(before):
                        raise ProcessScanBlocked("Studio directory changed while opening")
                    visit(child, child_relative)
                finally:
                    os.close(child)
            try:
                after = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as exc:
                raise ProcessScanBlocked("Studio entry disappeared during inventory") from exc
            if _fingerprint(after) != _fingerprint(before):
                raise ProcessScanBlocked("Studio entry changed during inventory")
        if _fingerprint(os.fstat(descriptor)) != _fingerprint(directory_before):
            raise ProcessScanBlocked("Studio directory changed during inventory")

    descriptor = os.open(root, _DIRECTORY_FLAGS)
    try:
        if _fingerprint(os.fstat(descriptor)) != _fingerprint(linked):
            raise ProcessScanBlocked("Studio volume root changed while opening")
        visit(descriptor, ())
    finally:
        os.close(descriptor)
    return snapshot


def _reference_identities(snapshot: dict[str, tuple[int, ...]]) -> set[tuple[int, int, int]]:
    return {
        (value[0], value[1], stat.S_IFMT(value[2]))
        for value in snapshot.values()
    }


def _verified_absent(reference: Path, *, follow: bool = False) -> bool:
    try:
        (os.stat if follow else os.lstat)(reference)
    except (FileNotFoundError, ProcessLookupError):
        return True
    except OSError as exc:
        raise ProcessScanBlocked("process reference disappearance is ambiguous") from exc
    return False


def _entries(directory: Path, owner: Path) -> list[Path] | None:
    try:
        return sorted(directory.iterdir(), key=lambda value: value.name)
    except (FileNotFoundError, ProcessLookupError) as exc:
        if _verified_absent(owner):
            return None
        raise ProcessScanBlocked("process reference directory disappeared ambiguously") from exc
    except OSError as exc:
        raise ProcessScanBlocked("cannot enumerate process references") from exc


def _reference_stat(reference: Path) -> os.stat_result | None:
    try:
        return os.stat(reference)
    except (FileNotFoundError, ProcessLookupError) as exc:
        if _verified_absent(reference, follow=True):
            return None
        raise ProcessScanBlocked("process reference stat disappeared ambiguously") from exc
    except OSError as exc:
        raise ProcessScanBlocked("cannot inspect process reference") from exc


def _scan_proc(
    identities: set[tuple[int, int, int]],
    *,
    proc_root: Path = Path("/proc"),
    only_pids: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    holders: list[dict[str, Any]] = []
    allowed = set(only_pids) if only_pids is not None else None
    try:
        processes = sorted(proc_root.iterdir(), key=lambda value: value.name)
    except OSError as exc:
        raise ProcessScanBlocked("cannot enumerate host processes") from exc

    def inspect(reference: Path, kind: str, pid: int, tid: int, identifier: str | None = None) -> None:
        before = _reference_stat(reference)
        if before is None:
            return
        after = _reference_stat(reference)
        if after is None:
            return
        if _identity(before) != _identity(after):
            raise ProcessScanBlocked("process reference changed during scan")
        if _identity(after) not in identities:
            return
        row: dict[str, Any] = {"kind": kind, "pid": pid, "tid": tid}
        if identifier is not None:
            row["identifier"] = identifier
        holders.append(row)

    for process in processes:
        if not process.name.isdigit():
            continue
        pid = int(process.name)
        if allowed is not None and pid not in allowed:
            continue
        threads = _entries(process / "task", process)
        if threads is None:
            continue
        for thread in threads:
            if not thread.name.isdigit():
                continue
            tid = int(thread.name)
            descriptors = _entries(thread / "fd", thread)
            if descriptors is not None:
                for descriptor in descriptors:
                    inspect(descriptor, "fd", pid, tid, descriptor.name)
            for kind in ("cwd", "root", "exe"):
                inspect(thread / kind, kind, pid, tid)
            mappings = _entries(proc_root / thread.name / "map_files", thread)
            if mappings is not None:
                for mapping in mappings:
                    inspect(mapping, "mmap", pid, tid, mapping.name)
    return holders


def _host_scan(root: Path) -> dict[str, Any]:
    first = _inventory(root)
    identities = _reference_identities(first)
    holders_one = _scan_proc(identities)
    second = _inventory(root)
    if second != first:
        raise ProcessScanBlocked("Studio volume changed during first process scan")
    holders_two = _scan_proc(identities)
    third = _inventory(root)
    if third != first:
        raise ProcessScanBlocked("Studio volume changed during second process scan")
    if holders_one or holders_two:
        raise ProcessScanBlocked("visible Studio process references remain")
    return {
        "scan_passes": 2,
        "inventory_entries": len(first),
        "inventory_sha256": _sha(first),
        "visible_reference_count": 0,
    }


def evaluate(
    *,
    writer_receipt: dict[str, Any],
    runtime_receipt: dict[str, Any],
    containers: list[dict[str, Any]],
    scan: dict[str, Any],
    boot_id: str,
) -> dict[str, Any]:
    writer = _writer_receipt(writer_receipt)
    runtime = _runtime_receipt(runtime_receipt, writer)
    _current_epoch(writer, runtime, containers)
    if (
        not isinstance(scan, dict)
        or set(scan) != {
            "scan_passes", "inventory_entries", "inventory_sha256",
            "visible_reference_count",
        }
        or scan["scan_passes"] != 2
        or type(scan["inventory_entries"]) is not int
        or scan["inventory_entries"] < 1
        or not isinstance(scan["inventory_sha256"], str)
        or len(scan["inventory_sha256"]) != 64
        or scan["visible_reference_count"] != 0
    ):
        raise ProcessScanBlocked("host process scan evidence is incomplete")
    if not isinstance(boot_id, str) or not boot_id.strip():
        raise ProcessScanBlocked("boot id is unavailable")
    receipt = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "writer_receipt_sha256": writer["receipt_sha256"],
        "runtime_receipt_sha256": runtime["receipt_sha256"],
        "merge_sha": runtime["merge_sha"],
        "operation_id": runtime["operation_id"],
        "generation": runtime["generation"],
        "studio_volume_source": runtime["studio_volume_source"],
        "boot_id": boot_id.strip(),
        **scan,
        "application_writer_epoch_verified": True,
        "runtime_container_epoch_stable": True,
        "backup_cycle_drain_verified": True,
        "host_visible_studio_reference_scan_verified": True,
        "studio_process_drain_verified": True,
        "process_drain_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "full_host_closure": False,
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def _run(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ProcessScanBlocked(f"command failed: {args[0]}")
    return result.stdout.strip()


def _containers() -> list[dict[str, Any]]:
    ids = [
        value for value in _run([
            "docker", "ps", "--no-trunc",
            "--filter", f"label=com.docker.compose.project={PROJECT}",
            "--format", "{{.ID}}",
        ]).splitlines() if value
    ]
    if not ids:
        raise ProcessScanBlocked("running compose inventory is empty")
    value = json.loads(_run(["docker", "inspect", *ids], timeout=60))
    if not isinstance(value, list) or len(value) != len(ids):
        raise ProcessScanBlocked("container inspection set is incomplete")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--writer-receipt", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        writer = json.loads(args.writer_receipt.read_text(encoding="utf-8"))
        runtime = json.loads(args.runtime_receipt.read_text(encoding="utf-8"))
        checked_writer = _writer_receipt(writer)
        checked_runtime = _runtime_receipt(runtime, checked_writer)
        volume = Path(checked_runtime["studio_volume_source"])
        scan = _host_scan(volume)
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        receipt = evaluate(
            writer_receipt=checked_writer,
            runtime_receipt=checked_runtime,
            containers=_containers(),
            scan=scan,
            boot_id=boot_id,
        )
        if args.output.exists():
            raise ProcessScanBlocked("process scan receipt already exists")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        args.output.chmod(0o600)
    except (OSError, ValueError, json.JSONDecodeError, ProcessScanBlocked) as exc:
        print(f"FR06D8C4B3_STUDIO_PROCESS_SCAN_BLOCKED: {type(exc).__name__}")
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
