#!/usr/bin/env python3
"""Prove zero visible host-process references to one owned Studio staging inode.

This is a read-only, candidate-specific host observation. It consumes the C4B1
writer-epoch receipt, C4B2 runtime/backup-drain receipt, and C4B3 cleanup
candidate. It revalidates the exact current writer/reader container epoch,
reopens the candidate path through no-follow directory descriptors, verifies the
current staging/final layout against retained identities, and scans proc-visible
thread references twice.

It never unlinks, renames, rewrites, chmods, kills processes, changes admission
or database state, stops/restarts containers, settles/retries an execution, or
authorizes cleanup. A successful receipt is still not full process/host drain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Iterable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WRITER_SCHEMA = "aionex.studio-writer-epoch.v1"
RUNTIME_SCHEMA = "aionex.studio-runtime-drain.v1"
CANDIDATE_SCHEMA = "aionex.studio-cleanup-candidate.v1"
SCHEMA = "aionex.studio-process-reference-scan.v1"
PROJECT = "web-dashboard"
DESTINATION = "/var/lib/aionex/studio-assets"
WRITERS = frozenset({"backend", "studio-worker"})
READERS = frozenset({"backup-worker"})
ONE_SHOT = "backup-asset-root-init"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class ProcessScanBlocked(RuntimeError):
    pass


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


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


def _digest_receipt(value: dict[str, Any], label: str, key: str) -> str:
    digest = value.get(key)
    if not isinstance(digest, str) or len(digest) != 64:
        raise ProcessScanBlocked(f"{label} digest is missing")
    body = {name: item for name, item in value.items() if name != key}
    if _sha(body) != digest:
        raise ProcessScanBlocked(f"{label} digest differs")
    return digest


def _component(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        or len(value.encode()) > 220
    ):
        raise ProcessScanBlocked("unsafe Studio path component")
    return value


def _writer_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProcessScanBlocked("writer receipt is malformed")
    required = {
        "schema",
        "observed_at",
        "merge_sha",
        "admission",
        "studio_snapshot",
        "writers",
        "readers",
        "studio_volume_source",
        "application_writer_epoch_verified",
        "process_drain_verified",
        "host_process_scan_verified",
        "backup_cycle_drain_verified",
        "cleanup_authorized",
        "filesystem_mutation_performed",
        "full_host_closure",
        "receipt_sha256",
    }
    if set(value) != required:
        raise ProcessScanBlocked("writer receipt fields are not exact")
    _digest_receipt(value, "writer receipt", "receipt_sha256")
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
        raise ProcessScanBlocked("runtime drain receipt is malformed")
    required = {
        "schema",
        "observed_at",
        "writer_receipt_sha256",
        "merge_sha",
        "operation_id",
        "generation",
        "studio_volume_source",
        "writer_container_ids",
        "backup_snapshot_sha256",
        "application_writer_epoch_verified",
        "runtime_container_epoch_stable",
        "backup_cycle_drain_verified",
        "process_drain_verified",
        "host_process_scan_verified",
        "cleanup_authorized",
        "filesystem_mutation_performed",
        "full_host_closure",
        "receipt_sha256",
    }
    if set(value) != required:
        raise ProcessScanBlocked("runtime receipt fields are not exact")
    _digest_receipt(value, "runtime receipt", "receipt_sha256")
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
        raise ProcessScanBlocked("runtime receipt does not extend writer boundary")
    if _time(value["observed_at"], "runtime observed_at") <= _time(
        writer["observed_at"], "writer observed_at"
    ):
        raise ProcessScanBlocked("runtime receipt predates writer receipt")
    return value


_CANDIDATE_KEYS = {
    "schema",
    "observation_id",
    "observation_proof_sha256",
    "execution_id",
    "publication_id",
    "job_id",
    "organization_id",
    "maintenance_operation_id",
    "maintenance_generation",
    "layout",
    "publication_phase",
    "publication_evidence_sha256",
    "relative_components",
    "staging_name",
    "final_name",
    "staging",
    "final",
    "action",
    "process_reference_scan_required",
    "final_deletion_permitted",
    "cleanup_authorized",
    "filesystem_mutation_performed",
    "full_host_closure",
    "candidate_sha256",
}


def _candidate(value: Any, runtime: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CANDIDATE_KEYS:
        raise ProcessScanBlocked("cleanup candidate fields are not exact")
    _digest_receipt(value, "cleanup candidate", "candidate_sha256")
    if (
        value["schema"] != CANDIDATE_SCHEMA
        or value["maintenance_operation_id"] != runtime["operation_id"]
        or value["maintenance_generation"] != runtime["generation"]
        or value["layout"]
        not in {"owned_staging_present", "owned_staging_and_final_hardlinks"}
        or value["action"] != "remove_owned_staging"
        or value["process_reference_scan_required"] is not True
        or value["final_deletion_permitted"] is not False
        or value["cleanup_authorized"] is not False
        or value["filesystem_mutation_performed"] is not False
        or value["full_host_closure"] is not False
    ):
        raise ProcessScanBlocked("cleanup candidate is not scan-eligible")
    parts = value["relative_components"]
    if (
        not isinstance(parts, list)
        or len(parts) != 3
        or [_component(item) for item in parts] != parts
    ):
        raise ProcessScanBlocked("cleanup candidate relative path is invalid")
    _component(value["staging_name"])
    _component(value["final_name"])
    return value


def _mount(item: dict[str, Any]) -> dict[str, Any] | None:
    mounts = item.get("Mounts")
    if not isinstance(mounts, list):
        raise ProcessScanBlocked("container mount inventory is missing")
    matches = [
        mount
        for mount in mounts
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


def _file_identity(raw: os.stat_result) -> dict[str, Any]:
    return {
        "device": raw.st_dev,
        "inode": raw.st_ino,
        "kind": "file" if stat.S_ISREG(raw.st_mode) else "other",
        "uid": raw.st_uid,
        "gid": raw.st_gid,
        "mode": stat.S_IMODE(raw.st_mode),
        "links": raw.st_nlink,
        "size": raw.st_size,
    }


def _same_identity(expected: Any, current: dict[str, Any]) -> bool:
    keys = ("device", "inode", "kind", "uid", "gid", "mode", "links", "size")
    return (
        isinstance(expected, dict)
        and set(expected) >= set(keys)
        and all(expected.get(key) == current[key] for key in keys)
    )


def _open_volume_directory(
    volume_source: str, relative_components: list[str]
) -> tuple[ExitStack, int, int]:
    root = Path(volume_source)
    if (
        not root.is_absolute()
        or root == Path("/")
        or ".." in root.parts
        or len(root.parts) < 2
    ):
        raise ProcessScanBlocked("Studio volume source is unsafe")
    stack = ExitStack()
    try:
        current = os.open("/", _DIRECTORY_FLAGS)
        stack.callback(os.close, current)
        root_device: int | None = None
        for index, part in enumerate([*root.parts[1:], *relative_components]):
            component = _component(part)
            nxt = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
            stack.callback(os.close, nxt)
            info = os.fstat(nxt)
            if index == len(root.parts[1:]) - 1:
                root_device = info.st_dev
            if root_device is not None and info.st_dev != root_device:
                raise ProcessScanBlocked("nested filesystem inside Studio candidate path")
            current = nxt
        if root_device is None:
            raise ProcessScanBlocked("Studio volume device is unavailable")
        return stack, current, root_device
    except BaseException:
        stack.close()
        raise


def _stat_entry(directory: int, name: str) -> dict[str, Any] | None:
    try:
        raw = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProcessScanBlocked("Studio candidate entry is unavailable") from exc
    current = _file_identity(raw)
    if current["kind"] != "file":
        raise ProcessScanBlocked("Studio candidate entry is not a regular file")
    return current


def _target_identity(
    runtime: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    try:
        stack, directory, root_device = _open_volume_directory(
            runtime["studio_volume_source"], candidate["relative_components"]
        )
        with stack:
            staging = _stat_entry(directory, candidate["staging_name"])
            final = _stat_entry(directory, candidate["final_name"])
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        raise ProcessScanBlocked("owned Studio candidate identity is unavailable") from exc

    if (
        staging is None
        or staging["device"] != root_device
        or not _same_identity(candidate.get("staging", {}).get("identity"), staging)
    ):
        raise ProcessScanBlocked("owned Studio staging identity changed")

    layout = candidate["layout"]
    expected_final = candidate.get("final", {})
    if layout == "owned_staging_present":
        if expected_final.get("status") != "absent" or final is not None:
            raise ProcessScanBlocked("Studio final entry changed after candidate export")
    elif layout == "owned_staging_and_final_hardlinks":
        if (
            expected_final.get("status") != "owned"
            or final is None
            or final["device"] != root_device
            or not _same_identity(expected_final.get("identity"), final)
            or (staging["device"], staging["inode"])
            != (final["device"], final["inode"])
            or staging["links"] < 2
            or final["links"] < 2
        ):
            raise ProcessScanBlocked("Studio hardlink layout changed after candidate export")
    else:
        raise ProcessScanBlocked("cleanup candidate layout is not staging-removable")
    return staging


def _proc_identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _verified_absent(reference: Path, *, follow: bool = False) -> bool:
    try:
        (os.stat if follow else os.lstat)(reference)
    except (FileNotFoundError, ProcessLookupError):
        return True
    except OSError as exc:
        raise ProcessScanBlocked(
            "process reference disappearance could not be verified"
        ) from exc
    return False


def _entries(directory: Path, owner: Path) -> list[Path] | None:
    try:
        return sorted(directory.iterdir(), key=lambda value: value.name)
    except (FileNotFoundError, ProcessLookupError) as exc:
        if _verified_absent(owner):
            return None
        raise ProcessScanBlocked(
            "process reference directory disappeared ambiguously"
        ) from exc
    except OSError as exc:
        raise ProcessScanBlocked("cannot enumerate process references") from exc


def _reference_stat(reference: Path) -> os.stat_result | None:
    try:
        return os.stat(reference)
    except (FileNotFoundError, ProcessLookupError) as exc:
        if _verified_absent(reference, follow=True):
            return None
        raise ProcessScanBlocked(
            "process reference stat disappeared ambiguously"
        ) from exc
    except OSError as exc:
        raise ProcessScanBlocked("cannot inspect process reference") from exc


def scan_proc_references(
    *,
    proc_root: Path,
    device: int,
    inode: int,
    only_pids: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Return every stable proc-visible reference to the exact device/inode."""
    if type(device) is not int or device < 0 or type(inode) is not int or inode <= 0:
        raise ProcessScanBlocked("target inode identity is invalid")
    allowed = set(only_pids) if only_pids is not None else None
    processes = _entries(proc_root, proc_root)
    if processes is None:
        raise ProcessScanBlocked("proc root is unavailable")
    found: dict[tuple[int, int, str, str], dict[str, Any]] = {}

    def inspect(
        reference: Path,
        *,
        pid: int,
        tid: int,
        kind: str,
        identifier: str,
    ) -> None:
        before = _reference_stat(reference)
        if before is None:
            return
        after = _reference_stat(reference)
        if after is None:
            return
        if _proc_identity(before) != _proc_identity(after):
            raise ProcessScanBlocked("process reference changed during scan")
        if (after.st_dev, after.st_ino) != (device, inode):
            return
        key = (pid, tid, kind, identifier)
        found[key] = {
            "pid": pid,
            "tid": tid,
            "kind": kind,
            "identifier": identifier,
        }

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
                    inspect(
                        descriptor,
                        pid=pid,
                        tid=tid,
                        kind="fd",
                        identifier=descriptor.name,
                    )
            for kind in ("cwd", "root", "exe"):
                inspect(
                    thread / kind,
                    pid=pid,
                    tid=tid,
                    kind=kind,
                    identifier=kind,
                )
            mappings = _entries(proc_root / thread.name / "map_files", thread)
            if mappings is not None:
                for mapping in mappings:
                    inspect(
                        mapping,
                        pid=pid,
                        tid=tid,
                        kind="mmap",
                        identifier=mapping.name,
                    )

    return [found[key] for key in sorted(found)]


def evaluate(
    *,
    writer_receipt: dict[str, Any],
    runtime_receipt: dict[str, Any],
    cleanup_candidate: dict[str, Any],
    containers: list[dict[str, Any]],
    proc_root: Path = Path("/proc"),
    boot_id: str,
) -> dict[str, Any]:
    writer = _writer_receipt(writer_receipt)
    runtime = _runtime_receipt(runtime_receipt, writer)
    candidate = _candidate(cleanup_candidate, runtime)
    _current_epoch(writer, runtime, containers)
    if not isinstance(boot_id, str) or not boot_id.strip():
        raise ProcessScanBlocked("boot id is unavailable")

    first = _target_identity(runtime, candidate)
    holders_one = scan_proc_references(
        proc_root=proc_root,
        device=first["device"],
        inode=first["inode"],
    )
    middle = _target_identity(runtime, candidate)
    if middle != first:
        raise ProcessScanBlocked("Studio staging identity changed during first scan")
    holders_two = scan_proc_references(
        proc_root=proc_root,
        device=first["device"],
        inode=first["inode"],
    )
    final = _target_identity(runtime, candidate)
    if final != first:
        raise ProcessScanBlocked("Studio staging identity changed during second scan")
    if holders_one or holders_two:
        raise ProcessScanBlocked("owned Studio staging inode still has process references")

    receipt = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "writer_receipt_sha256": writer["receipt_sha256"],
        "runtime_receipt_sha256": runtime["receipt_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "operation_id": runtime["operation_id"],
        "generation": runtime["generation"],
        "boot_id": boot_id.strip(),
        "staging_identity": first,
        "scan_passes": 2,
        "visible_reference_count": 0,
        "candidate_reference_drain_verified": True,
        "host_process_scan_verified": True,
        "process_drain_verified": False,
        "cleanup_authorized": False,
        "filesystem_mutation_performed": False,
        "final_deletion_permitted": False,
        "full_host_closure": False,
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def _run(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        raise ProcessScanBlocked(f"command failed: {args[0]}")
    return result.stdout.strip()


def _containers() -> list[dict[str, Any]]:
    ids = [
        value
        for value in _run([
            "docker",
            "ps",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.ID}}",
        ]).splitlines()
        if value
    ]
    if not ids:
        raise ProcessScanBlocked("running compose inventory is empty")
    value = json.loads(_run(["docker", "inspect", *ids], timeout=60))
    if not isinstance(value, list) or len(value) != len(ids):
        raise ProcessScanBlocked("container inspection set is incomplete")
    return value


def _boot_id() -> str:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
    except OSError as exc:
        raise ProcessScanBlocked("boot id is unavailable") from exc
    if not value:
        raise ProcessScanBlocked("boot id is unavailable")
    return value


def _write_private(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise ProcessScanBlocked("process scan receipt already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        content = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--writer-receipt", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument("--cleanup-candidate", type=Path, required=True)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        writer = json.loads(args.writer_receipt.read_text(encoding="utf-8"))
        runtime = json.loads(args.runtime_receipt.read_text(encoding="utf-8"))
        candidate = json.loads(args.cleanup_candidate.read_text(encoding="utf-8"))
        receipt = evaluate(
            writer_receipt=writer,
            runtime_receipt=runtime,
            cleanup_candidate=candidate,
            containers=_containers(),
            proc_root=args.proc_root,
            boot_id=_boot_id(),
        )
        _write_private(args.output, receipt)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        ProcessScanBlocked,
    ):
        print("FR06D8C4B4_STUDIO_PROCESS_REFERENCE_SCAN_BLOCKED")
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
