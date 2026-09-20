#!/usr/bin/env python3
"""Read-only host revalidation of one retained Studio crash quarantine.

FR-06D8C4B6B2 consumes the database-exported B6B1 terminal candidate and
revalidates the current host state from scratch. It derives the current Studio
volume source from two fresh Docker inventories, opens the exact relative path
through O_NOFOLLOW directory descriptors, requires the original staging name to
remain absent, requires the deterministic quarantine name to retain the exact
inode/layout, and scans proc-visible references twice.

This stage never renames/unlinks/writes Studio bytes, changes containers,
changes admission/database state, clears the blocker, settles/retries work, or
authorizes deletion/terminalization. A later database stage must revalidate the
current closed maintenance authority before any terminal decision.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

_DIR = Path(__file__).resolve().parent

_B4_PATH = _DIR / "fr06d8c4_studio_process_reference_scan.py"
_B4_SPEC = importlib.util.spec_from_file_location(
    "fr06d8c4_process_scan_for_b6b2", _B4_PATH
)
if _B4_SPEC is None or _B4_SPEC.loader is None:
    raise RuntimeError("B4 process-reference scanner is unavailable")
scan = importlib.util.module_from_spec(_B4_SPEC)
_B4_SPEC.loader.exec_module(scan)

_B5_PATH = _DIR / "fr06d8c4_studio_staging_quarantine.py"
_B5_SPEC = importlib.util.spec_from_file_location(
    "fr06d8c4_staging_quarantine_for_b6b2", _B5_PATH
)
if _B5_SPEC is None or _B5_SPEC.loader is None:
    raise RuntimeError("B5 staging-quarantine helper is unavailable")
quarantine = importlib.util.module_from_spec(_B5_SPEC)
_B5_SPEC.loader.exec_module(quarantine)

CANDIDATE_SCHEMA = "aionex.studio-crash-terminal-candidate.v1"
SCHEMA = "aionex.studio-quarantine-revalidation.v1"
STATE_ROOT = Path(
    "/var/lib/aionex/fr06d8c4b6b2-studio-quarantine-revalidation"
)
_ALLOWED = scan.WRITERS | scan.READERS

_CANDIDATE_KEYS = {
    "schema",
    "containment_id",
    "containment_proof_sha256",
    "observation_id",
    "observation_proof_sha256",
    "execution_id",
    "publication_id",
    "job_id",
    "organization_id",
    "worker_incarnation",
    "admitted_generation",
    "containment_operation_id",
    "containment_generation",
    "containment_boot_id",
    "cleanup_candidate_sha256",
    "process_scan_receipt_sha256",
    "staging_quarantine_receipt_sha256",
    "layout",
    "relative_components",
    "original_staging_name",
    "final_name",
    "final_evidence",
    "archive_size_bytes",
    "archive_checksum_sha256",
    "quarantine_name",
    "retained_identity",
    "reconciliation_authority",
    "reconciliation_authority_sha256",
    "host_revalidation_required",
    "quarantine_revalidation_required",
    "terminalization_authorized",
    "blocker_cleared",
    "retry_authorized",
    "filesystem_cleanup_claimed",
    "cleanup_authorized",
    "settlement_authorized",
    "quarantine_deletion_permitted",
    "final_deletion_permitted",
    "full_host_closure",
    "candidate_sha256",
}

_AUTHORITY_KEYS = {
    "schema_version",
    "scope",
    "generation",
    "status",
    "enabled",
    "operation_id",
    "reason",
    "changed_at",
    "full_host_closure",
}


class QuarantineRevalidationBlocked(RuntimeError):
    pass


def _blocked(
    message: str, exc: BaseException | None = None
) -> QuarantineRevalidationBlocked:
    error = QuarantineRevalidationBlocked(message)
    if exc is not None:
        error.__cause__ = exc
    return error


def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise _blocked(f"{label} is missing")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise _blocked(f"{label} is malformed", exc) from exc
    if str(parsed) != value:
        raise _blocked(f"{label} is not canonical")
    return value


def _digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise _blocked(f"{label} digest is not canonical")
    return value


def _terminal_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CANDIDATE_KEYS:
        raise _blocked("terminal candidate fields are not exact")
    body = {
        key: item for key, item in value.items() if key != "candidate_sha256"
    }
    digest = _digest(value.get("candidate_sha256"), "terminal candidate")
    if scan._sha(body) != digest:
        raise _blocked("terminal candidate digest differs")
    if value.get("schema") != CANDIDATE_SCHEMA:
        raise _blocked("terminal candidate schema differs")

    for field in (
        "containment_id",
        "observation_id",
        "execution_id",
        "publication_id",
        "job_id",
        "organization_id",
        "worker_incarnation",
        "containment_operation_id",
    ):
        _uuid(value.get(field), field)
    for field in (
        "containment_proof_sha256",
        "observation_proof_sha256",
        "cleanup_candidate_sha256",
        "process_scan_receipt_sha256",
        "staging_quarantine_receipt_sha256",
        "reconciliation_authority_sha256",
    ):
        _digest(value.get(field), field)

    if (
        type(value.get("admitted_generation")) is not int
        or value["admitted_generation"] < 7
        or type(value.get("containment_generation")) is not int
        or value["containment_generation"] < 1
    ):
        raise _blocked("terminal candidate generation is invalid")
    if not isinstance(value.get("containment_boot_id"), str) or not value[
        "containment_boot_id"
    ].strip():
        raise _blocked("containment boot id is unavailable")

    parts = value.get("relative_components")
    if (
        not isinstance(parts, list)
        or len(parts) != 3
        or [scan._component(item) for item in parts] != parts
    ):
        raise _blocked("terminal candidate relative path is invalid")
    scan._component(value.get("original_staging_name"))
    scan._component(value.get("final_name"))
    scan._component(value.get("quarantine_name"))
    expected_quarantine = quarantine._quarantine_name(
        value["cleanup_candidate_sha256"]
    )
    if value["quarantine_name"] != expected_quarantine:
        raise _blocked("terminal candidate quarantine name differs")

    if value.get("layout") not in {
        "owned_staging_present",
        "owned_staging_and_final_hardlinks",
    }:
        raise _blocked("terminal candidate layout is invalid")
    if not isinstance(value.get("final_evidence"), dict):
        raise _blocked("terminal candidate final evidence is malformed")
    if not isinstance(value.get("retained_identity"), dict):
        raise _blocked("terminal candidate retained identity is malformed")
    if (
        type(value.get("archive_size_bytes")) is not int
        or value["archive_size_bytes"] < 0
        or value["retained_identity"].get("size")
        != value["archive_size_bytes"]
    ):
        raise _blocked("terminal candidate archive size is invalid")
    _digest(value.get("archive_checksum_sha256"), "archive checksum")

    authority = value.get("reconciliation_authority")
    if not isinstance(authority, dict) or set(authority) != _AUTHORITY_KEYS:
        raise _blocked("terminal candidate authority fields are not exact")
    if (
        scan._sha(authority) != value["reconciliation_authority_sha256"]
        or authority.get("status") != "closed"
        or authority.get("enabled") is not False
        or authority.get("full_host_closure") is not False
        or type(authority.get("generation")) is not int
        or authority["generation"] < value["containment_generation"]
        or not isinstance(authority.get("scope"), str)
        or not authority["scope"]
        or not isinstance(authority.get("reason"), str)
        or not authority["reason"]
    ):
        raise _blocked("terminal candidate authority is invalid")
    _uuid(authority.get("operation_id"), "reconciliation operation_id")
    try:
        scan._time(authority.get("changed_at"), "reconciliation changed_at")
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc

    if (
        value.get("host_revalidation_required") is not True
        or value.get("quarantine_revalidation_required") is not True
        or value.get("terminalization_authorized") is not False
        or value.get("blocker_cleared") is not False
        or value.get("retry_authorized") is not False
        or value.get("filesystem_cleanup_claimed") is not False
        or value.get("cleanup_authorized") is not False
        or value.get("settlement_authorized") is not False
        or value.get("quarantine_deletion_permitted") is not False
        or value.get("final_deletion_permitted") is not False
        or value.get("full_host_closure") is not False
    ):
        raise _blocked("terminal candidate safety boundary is invalid")
    return value


def _inventory(containers: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(containers, list) or not containers:
        raise _blocked("current container inventory is unavailable")

    running: list[dict[str, Any]] = []
    for item in containers:
        if not isinstance(item, dict):
            raise _blocked("container inspection is malformed")
        config, state = item.get("Config") or {}, item.get("State") or {}
        labels = config.get("Labels") or {}
        if labels.get("com.docker.compose.project") != scan.PROJECT:
            continue
        if state.get("Running") is not True or state.get("Status") != "running":
            continue
        service = scan._service(item)
        if service == scan.ONE_SHOT:
            raise _blocked("one-shot Studio root initializer is running")
        running.append(item)

    by_service: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    candidate_sources: set[str] = set()
    for item in running:
        service = scan._service(item)
        mount = scan._mount(item)
        if mount is None:
            continue
        if service not in _ALLOWED:
            raise _blocked(f"unexpected current Studio mount: {service}")
        by_service.setdefault(service, []).append((item, mount))
        source = mount.get("Source")
        if not isinstance(source, str) or not source:
            raise _blocked("current Studio volume source is missing")
        candidate_sources.add(source)

    if set(by_service) != _ALLOWED:
        raise _blocked("current Studio writer/reader set differs")
    if len(candidate_sources) != 1:
        raise _blocked("current Studio volume source is ambiguous")
    source = next(iter(candidate_sources))
    root = Path(source)
    if (
        not root.is_absolute()
        or root == Path("/")
        or ".." in root.parts
        or len(root.parts) < 2
    ):
        raise _blocked("current Studio volume source is unsafe")

    rows: list[dict[str, Any]] = []
    for service in sorted(_ALLOWED):
        matches = by_service.get(service, [])
        if len(matches) != 1:
            raise _blocked(f"current Studio service count differs: {service}")
        item, mount = matches[0]
        expected_rw = service in scan.WRITERS
        if (
            mount.get("Destination") != scan.DESTINATION
            or mount.get("Source") != source
            or mount.get("RW") is not expected_rw
            or not isinstance(item.get("Id"), str)
            or not item["Id"]
            or type(item.get("RestartCount")) is not int
            or item["RestartCount"] < 0
        ):
            raise _blocked(f"current Studio mount boundary differs: {service}")
        started_at = (item.get("State") or {}).get("StartedAt")
        try:
            scan._time(started_at, f"{service} started_at")
        except scan.ProcessScanBlocked as exc:
            raise _blocked(str(exc), exc) from exc
        rows.append(
            {
                "service": service,
                "container_id": item["Id"],
                "restart_count": item["RestartCount"],
                "started_at": started_at,
                "rw": mount["RW"],
                "source": source,
                "type": mount.get("Type"),
                "name": mount.get("Name"),
            }
        )

    # Reject any alternate path from another running Compose service to the
    # same underlying source, even when mounted at a different destination.
    for item in running:
        service = scan._service(item)
        mounts = item.get("Mounts")
        if not isinstance(mounts, list):
            raise _blocked("container mount inventory is missing")
        for mount in mounts:
            if not isinstance(mount, dict) or mount.get("Source") != source:
                continue
            if (
                service not in _ALLOWED
                or mount.get("Destination") != scan.DESTINATION
            ):
                raise _blocked(
                    "unexpected current alternate Studio volume access path"
                )
    return source, rows


def _layout(
    *,
    directory: int,
    root_device: int,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    try:
        staging = scan._stat_entry(
            directory, candidate["original_staging_name"]
        )
        retained = scan._stat_entry(directory, candidate["quarantine_name"])
        final = scan._stat_entry(directory, candidate["final_name"])
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc

    if staging is not None:
        raise _blocked("original Studio staging name reappeared")
    if (
        retained is None
        or retained["device"] != root_device
        or not scan._same_identity(candidate["retained_identity"], retained)
    ):
        raise _blocked("retained Studio quarantine identity changed")

    final_evidence = candidate["final_evidence"]
    if candidate["layout"] == "owned_staging_present":
        if final_evidence.get("status") != "absent" or final is not None:
            raise _blocked("Studio final entry changed after containment")
    else:
        expected = final_evidence.get("identity")
        if (
            final_evidence.get("status") != "owned"
            or final is None
            or final["device"] != root_device
            or not scan._same_identity(expected, final)
            or (final["device"], final["inode"])
            != (retained["device"], retained["inode"])
            or retained["links"] < 2
            or final["links"] < 2
        ):
            raise _blocked("Studio final hardlink layout changed")
    return retained




def _hash_descriptor(descriptor: int, expected_identity: dict[str, Any]) -> str:
    before = scan._file_identity(os.fstat(descriptor))
    if before != expected_identity:
        raise _blocked("pinned Studio quarantine identity changed")
    digest = hashlib.sha256()
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    except OSError as exc:
        raise _blocked("retained Studio quarantine cannot be hashed", exc) from exc
    after = scan._file_identity(os.fstat(descriptor))
    if after != before:
        raise _blocked("pinned Studio quarantine changed during hashing")
    return digest.hexdigest()


def _open_retained_descriptor(
    *,
    directory: int,
    root_device: int,
    candidate: dict[str, Any],
    retained: dict[str, Any],
) -> int:
    try:
        descriptor = os.open(
            candidate["quarantine_name"],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
    except OSError as exc:
        raise _blocked("retained Studio quarantine descriptor is unavailable", exc) from exc
    try:
        pinned = scan._file_identity(os.fstat(descriptor))
        if (
            pinned["device"] != root_device
            or pinned != retained
            or pinned["size"] != candidate["archive_size_bytes"]
        ):
            raise _blocked("retained Studio quarantine descriptor identity changed")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def evaluate(
    *,
    terminal_candidate: dict[str, Any],
    container_provider: Callable[[], list[dict[str, Any]]],
    proc_root: Path,
    boot_id: str,
) -> dict[str, Any]:
    candidate = _terminal_candidate(terminal_candidate)
    if not isinstance(boot_id, str) or not boot_id.strip():
        raise _blocked("current boot id is unavailable")
    current_boot = boot_id.strip()

    try:
        source_one, inventory_one = _inventory(container_provider())
    except Exception as exc:
        if isinstance(exc, QuarantineRevalidationBlocked):
            raise
        raise _blocked("current container inventory is unavailable", exc) from exc

    try:
        stack, directory, root_device = scan._open_volume_directory(
            source_one, candidate["relative_components"]
        )
    except (scan.ProcessScanBlocked, OSError) as exc:
        raise _blocked(
            "retained Studio quarantine directory is unavailable", exc
        ) from exc

    with stack:
        first = _layout(
            directory=directory,
            root_device=root_device,
            candidate=candidate,
        )
        descriptor = _open_retained_descriptor(
            directory=directory,
            root_device=root_device,
            candidate=candidate,
            retained=first,
        )
        try:
            content_one = _hash_descriptor(descriptor, first)
            if content_one != candidate["archive_checksum_sha256"]:
                raise _blocked("retained Studio quarantine checksum differs")
            try:
                holders_one = scan.scan_proc_references(
                    proc_root=proc_root,
                    device=first["device"],
                    inode=first["inode"],
                )
            except scan.ProcessScanBlocked as exc:
                raise _blocked(str(exc), exc) from exc

            middle = _layout(
                directory=directory,
                root_device=root_device,
                candidate=candidate,
            )
            if middle != first:
                raise _blocked("Studio quarantine identity changed during first scan")

            try:
                holders_two = scan.scan_proc_references(
                    proc_root=proc_root,
                    device=first["device"],
                    inode=first["inode"],
                )
            except scan.ProcessScanBlocked as exc:
                raise _blocked(str(exc), exc) from exc

            content_two = _hash_descriptor(descriptor, first)
            if (
                content_two != candidate["archive_checksum_sha256"]
                or content_two != content_one
            ):
                raise _blocked("retained Studio quarantine checksum changed")

            final = _layout(
                directory=directory,
                root_device=root_device,
                candidate=candidate,
            )
            if final != first:
                raise _blocked("Studio quarantine identity changed during second scan")
            if holders_one or holders_two:
                raise _blocked(
                    "retained Studio quarantine inode still has process references"
                )

            try:
                source_two, inventory_two = _inventory(container_provider())
            except Exception as exc:
                if isinstance(exc, QuarantineRevalidationBlocked):
                    raise
                raise _blocked(
                    "final container inventory is unavailable", exc
                ) from exc
            if source_two != source_one or inventory_two != inventory_one:
                raise _blocked(
                    "current Studio container epoch changed during revalidation"
                )
            if scan._file_identity(os.fstat(descriptor)) != first:
                raise _blocked("pinned Studio quarantine changed before receipt")
        finally:
            os.close(descriptor)

    receipt = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "terminal_candidate_sha256": candidate["candidate_sha256"],
        "containment_id": candidate["containment_id"],
        "reconciliation_authority_sha256": candidate[
            "reconciliation_authority_sha256"
        ],
        "containment_boot_id": candidate["containment_boot_id"],
        "current_boot_id": current_boot,
        "same_boot_as_containment": (
            current_boot == candidate["containment_boot_id"]
        ),
        "studio_volume_source": source_one,
        "container_inventory": inventory_one,
        "container_inventory_sha256": scan._sha(inventory_one),
        "retained_identity": first,
        "archive_size_bytes": candidate["archive_size_bytes"],
        "archive_checksum_sha256": candidate["archive_checksum_sha256"],
        "content_hash_passes": 2,
        "archive_content_revalidated": True,
        "scan_passes": 2,
        "visible_reference_count": 0,
        "current_container_epoch_stable": True,
        "staging_name_absent": True,
        "quarantine_identity_revalidated": True,
        "final_layout_revalidated": True,
        "quarantine_reference_drain_verified": True,
        "host_process_scan_verified": True,
        "process_drain_verified": False,
        "authority_revalidation_required_by_next_stage": True,
        "terminalization_authorized": False,
        "blocker_cleared": False,
        "retry_authorized": False,
        "filesystem_cleanup_claimed": False,
        "filesystem_mutation_performed": False,
        "cleanup_authorized": False,
        "settlement_authorized": False,
        "quarantine_deletion_permitted": False,
        "final_deletion_permitted": False,
        "full_host_closure": False,
    }
    receipt["receipt_sha256"] = scan._sha(receipt)
    return receipt


def _write_private(
    state_root: Path,
    candidate_sha256: str,
    receipt: dict[str, Any],
) -> Path:
    if os.geteuid() != 0:
        raise _blocked("B6B2 host revalidation receipt requires root")
    try:
        root_fd = quarantine._validated_state_root(state_root)
    except quarantine.StagingQuarantineBlocked as exc:
        raise _blocked(str(exc), exc) from exc
    name = f"{candidate_sha256}.json"
    try:
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                0o600,
                dir_fd=root_fd,
            )
        except OSError as exc:
            raise _blocked("revalidation receipt cannot be created", exc) from exc
        try:
            raw = (
                json.dumps(receipt, sort_keys=True, indent=2) + "\n"
            ).encode()
            os.write(descriptor, raw)
            os.fsync(descriptor)
            meta = os.fstat(descriptor)
            if (
                not stat.S_ISREG(meta.st_mode)
                or stat.S_IMODE(meta.st_mode) != 0o600
                or meta.st_uid != os.geteuid()
                or meta.st_nlink != 1
            ):
                raise _blocked("revalidation receipt boundary is unsafe")
        finally:
            os.close(descriptor)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    return state_root / name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-candidate", type=Path, required=True)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    args = parser.parse_args()
    try:
        candidate = json.loads(
            args.terminal_candidate.read_text(encoding="utf-8")
        )
        checked = _terminal_candidate(candidate)
        receipt = evaluate(
            terminal_candidate=checked,
            container_provider=scan._containers,
            proc_root=args.proc_root,
            boot_id=scan._boot_id(),
        )
        _write_private(
            args.state_root,
            checked["candidate_sha256"],
            receipt,
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        scan.ProcessScanBlocked,
        quarantine.StagingQuarantineBlocked,
        QuarantineRevalidationBlocked,
    ):
        print("FR06D8C4B6B2_STUDIO_QUARANTINE_REVALIDATION_BLOCKED")
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
