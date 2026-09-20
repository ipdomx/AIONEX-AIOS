#!/usr/bin/env python3
"""Atomically detach one verified Studio staging name into retained quarantine.

FR-06D8C4B5 is a bounded containment step, not cleanup or settlement. It
consumes the accepted C4B1/C4B2/C4B3 evidence plus a C4B4 process-reference
receipt, rechecks the exact writer/reader boundary and candidate inode, performs
candidate-specific /proc scans, and moves only the owned staging name to a
deterministic retained quarantine name with Linux renameat2(RENAME_NOREPLACE).

The inode and any final hardlink are retained. No archive bytes are deleted,
no final name is modified, no process/container/admission/database state is
changed, and no execution is settled or retried. A crash after the atomic rename
but before receipt persistence is recoverable on the same boot by recognizing
the deterministic quarantine name and exact retained inode.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import importlib.util
import json
import os
import platform
import stat
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any

_B4_PATH = Path(__file__).with_name("fr06d8c4_studio_process_reference_scan.py")
_B4_SPEC = importlib.util.spec_from_file_location("fr06d8c4_process_scan_for_b5", _B4_PATH)
if _B4_SPEC is None or _B4_SPEC.loader is None:
    raise RuntimeError("B4 process-reference scanner is unavailable")
scan = importlib.util.module_from_spec(_B4_SPEC)
_B4_SPEC.loader.exec_module(scan)

SCHEMA = "aionex.studio-staging-quarantine.v1"
SCAN_SCHEMA = scan.SCHEMA
_RENAME_NOREPLACE = 1
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
STATE_ROOT = Path("/var/lib/aionex/fr06d8c4b5-studio-quarantine")


class StagingQuarantineBlocked(RuntimeError):
    pass


def _blocked(message: str, exc: BaseException | None = None) -> StagingQuarantineBlocked:
    error = StagingQuarantineBlocked(message)
    if exc is not None:
        error.__cause__ = exc
    return error


def _sha(value: Any) -> str:
    return scan._sha(value)


def _scan_receipt(
    value: Any,
    *,
    writer: dict[str, Any],
    runtime: dict[str, Any],
    candidate: dict[str, Any],
    boot_id: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _blocked("process scan receipt is malformed")
    required = {
        "schema",
        "observed_at",
        "writer_receipt_sha256",
        "runtime_receipt_sha256",
        "candidate_sha256",
        "operation_id",
        "generation",
        "boot_id",
        "staging_identity",
        "scan_passes",
        "visible_reference_count",
        "candidate_reference_drain_verified",
        "host_process_scan_verified",
        "process_drain_verified",
        "cleanup_authorized",
        "filesystem_mutation_performed",
        "final_deletion_permitted",
        "full_host_closure",
        "receipt_sha256",
    }
    if set(value) != required:
        raise _blocked("process scan receipt fields are not exact")
    try:
        scan._digest_receipt(value, "process scan receipt", "receipt_sha256")
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc
    if (
        value["schema"] != SCAN_SCHEMA
        or value["writer_receipt_sha256"] != writer["receipt_sha256"]
        or value["runtime_receipt_sha256"] != runtime["receipt_sha256"]
        or value["candidate_sha256"] != candidate["candidate_sha256"]
        or value["operation_id"] != runtime["operation_id"]
        or value["generation"] != runtime["generation"]
        or value["boot_id"] != boot_id
        or value["scan_passes"] != 2
        or value["visible_reference_count"] != 0
        or value["candidate_reference_drain_verified"] is not True
        or value["host_process_scan_verified"] is not True
        or value["process_drain_verified"] is not False
        or value["cleanup_authorized"] is not False
        or value["filesystem_mutation_performed"] is not False
        or value["final_deletion_permitted"] is not False
        or value["full_host_closure"] is not False
        or not scan._same_identity(
            candidate.get("staging", {}).get("identity"),
            value.get("staging_identity"),
        )
    ):
        raise _blocked("process scan receipt boundary is invalid")
    try:
        if scan._time(value["observed_at"], "process scan observed_at") <= scan._time(
            runtime["observed_at"], "runtime observed_at"
        ):
            raise _blocked("process scan receipt predates runtime drain")
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc
    return value


def _quarantine_name(candidate_sha256: str) -> str:
    if (
        not isinstance(candidate_sha256, str)
        or len(candidate_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in candidate_sha256)
    ):
        raise _blocked("candidate digest is not canonical")
    name = f".studio-quarantine-{candidate_sha256}.retained"
    try:
        return scan._component(name)
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc


def _rename_noreplace(directory: int, source: str, destination: str) -> None:
    """Linux atomic same-directory rename that can never replace destination."""
    if platform.system() != "Linux":
        raise OSError(errno.ENOSYS, "atomic Studio quarantine is Linux-only")
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    args = (
        ctypes.c_int(directory),
        ctypes.c_char_p(os.fsencode(source)),
        ctypes.c_int(directory),
        ctypes.c_char_p(os.fsencode(destination)),
        ctypes.c_uint(_RENAME_NOREPLACE),
    )
    if rename is not None:
        rename.restype = ctypes.c_int
        result = rename(*args)
    elif (
        platform.machine().lower() in {"x86_64", "amd64"}
        and ctypes.sizeof(ctypes.c_void_p) == 8
        and ctypes.sizeof(ctypes.c_long) == 8
        and getattr(libc, "syscall", None) is not None
    ):
        libc.syscall.restype = ctypes.c_long
        result = libc.syscall(ctypes.c_long(316), *args)
    else:
        raise OSError(errno.ENOSYS, "atomic Studio quarantine ABI is unavailable")
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, "atomic Studio quarantine rename failed")


def _layout(
    *,
    directory: int,
    root_device: int,
    candidate: dict[str, Any],
    quarantine_name: str,
) -> tuple[str, dict[str, Any]]:
    """Return source state and exact retained inode, or fail closed."""
    try:
        staging = scan._stat_entry(directory, candidate["staging_name"])
        quarantine = scan._stat_entry(directory, quarantine_name)
        final = scan._stat_entry(directory, candidate["final_name"])
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc

    expected = candidate.get("staging", {}).get("identity")
    staging_ok = (
        staging is not None
        and staging["device"] == root_device
        and scan._same_identity(expected, staging)
    )
    quarantine_ok = (
        quarantine is not None
        and quarantine["device"] == root_device
        and scan._same_identity(expected, quarantine)
    )
    if staging is not None and quarantine is not None:
        raise _blocked("Studio staging and quarantine names both exist")
    if staging_ok and quarantine is None:
        state, retained = "staging", staging
    elif staging is None and quarantine_ok:
        state, retained = "quarantine", quarantine
    else:
        raise _blocked("Studio staging/quarantine identity changed")

    layout = candidate["layout"]
    expected_final = candidate.get("final", {})
    if layout == "owned_staging_present":
        if expected_final.get("status") != "absent" or final is not None:
            raise _blocked("Studio final entry changed during quarantine")
    elif layout == "owned_staging_and_final_hardlinks":
        if (
            expected_final.get("status") != "owned"
            or final is None
            or final["device"] != root_device
            or not scan._same_identity(expected_final.get("identity"), final)
            or (final["device"], final["inode"])
            != (retained["device"], retained["inode"])
        ):
            raise _blocked("Studio final hardlink changed during quarantine")
    else:
        raise _blocked("Studio candidate layout is not quarantine-eligible")
    return state, retained


def _zero_references(
    *,
    proc_root: Path,
    device: int,
    inode: int,
    label: str,
) -> None:
    try:
        found = scan.scan_proc_references(
            proc_root=proc_root,
            device=device,
            inode=inode,
        )
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc
    if found:
        raise _blocked(f"Studio retained inode has visible references during {label}")


def evaluate_and_quarantine(
    *,
    writer_receipt: dict[str, Any],
    runtime_receipt: dict[str, Any],
    cleanup_candidate: dict[str, Any],
    process_scan_receipt: dict[str, Any],
    container_provider: Callable[[], list[dict[str, Any]]],
    proc_root: Path,
    boot_id: str,
) -> dict[str, Any]:
    """Contain one owned staging name without deleting its inode or final link."""
    try:
        writer = scan._writer_receipt(writer_receipt)
        runtime = scan._runtime_receipt(runtime_receipt, writer)
        candidate = scan._candidate(cleanup_candidate, runtime)
    except scan.ProcessScanBlocked as exc:
        raise _blocked(str(exc), exc) from exc
    if not isinstance(boot_id, str) or not boot_id.strip():
        raise _blocked("boot id is unavailable")
    prior = _scan_receipt(
        process_scan_receipt,
        writer=writer,
        runtime=runtime,
        candidate=candidate,
        boot_id=boot_id.strip(),
    )
    def current_epoch() -> None:
        try:
            containers = container_provider()
        except Exception as exc:
            raise _blocked("current container inventory is unavailable", exc) from exc
        if not isinstance(containers, list):
            raise _blocked("current container inventory is malformed")
        try:
            scan._current_epoch(writer, runtime, containers)
        except scan.ProcessScanBlocked as exc:
            raise _blocked(str(exc), exc) from exc

    current_epoch()

    quarantine_name = _quarantine_name(candidate["candidate_sha256"])
    try:
        stack, directory, root_device = scan._open_volume_directory(
            runtime["studio_volume_source"], candidate["relative_components"]
        )
    except (scan.ProcessScanBlocked, OSError) as exc:
        raise _blocked("owned Studio candidate directory is unavailable", exc) from exc

    renamed = False
    recovered = False
    with stack:
        state, retained = _layout(
            directory=directory,
            root_device=root_device,
            candidate=candidate,
            quarantine_name=quarantine_name,
        )
        if not scan._same_identity(prior["staging_identity"], retained):
            raise _blocked("process scan inode differs from quarantine target")

        if state == "staging":
            # Re-prove the exact candidate is unreferenced immediately before mutation.
            _zero_references(
                proc_root=proc_root,
                device=retained["device"],
                inode=retained["inode"],
                label="pre-quarantine scan one",
            )
            middle_state, middle = _layout(
                directory=directory,
                root_device=root_device,
                candidate=candidate,
                quarantine_name=quarantine_name,
            )
            if middle_state != "staging" or middle != retained:
                raise _blocked("Studio staging identity changed during pre-quarantine scan")
            _zero_references(
                proc_root=proc_root,
                device=retained["device"],
                inode=retained["inode"],
                label="pre-quarantine scan two",
            )
            final_state, final_pre = _layout(
                directory=directory,
                root_device=root_device,
                candidate=candidate,
                quarantine_name=quarantine_name,
            )
            if final_state != "staging" or final_pre != retained:
                raise _blocked("Studio staging identity changed before quarantine")
            # Refresh Docker state at the last safe point before namespace mutation.
            current_epoch()
            try:
                descriptor = os.open(
                    candidate["staging_name"],
                    _FILE_FLAGS,
                    dir_fd=directory,
                )
            except OSError as exc:
                raise _blocked("Studio staging descriptor is unavailable", exc) from exc
            try:
                pinned = scan._file_identity(os.fstat(descriptor))
                if pinned != retained:
                    raise _blocked("Studio staging descriptor identity changed")
                try:
                    _rename_noreplace(
                        directory,
                        candidate["staging_name"],
                        quarantine_name,
                    )
                    os.fsync(directory)
                except OSError as exc:
                    raise _blocked("Studio staging quarantine rename failed", exc) from exc
                renamed = True
                state, retained_after = _layout(
                    directory=directory,
                    root_device=root_device,
                    candidate=candidate,
                    quarantine_name=quarantine_name,
                )
                if state != "quarantine" or retained_after != pinned:
                    raise _blocked("Studio quarantine postcondition changed")
                retained = retained_after
            finally:
                os.close(descriptor)
        else:
            recovered = True

        # A race that acquired the inode immediately around rename is not hidden.
        current_epoch()
        _zero_references(
            proc_root=proc_root,
            device=retained["device"],
            inode=retained["inode"],
            label="post-quarantine scan one",
        )
        middle_state, middle = _layout(
            directory=directory,
            root_device=root_device,
            candidate=candidate,
            quarantine_name=quarantine_name,
        )
        if middle_state != "quarantine" or middle != retained:
            raise _blocked("Studio quarantine identity changed during post scan")
        _zero_references(
            proc_root=proc_root,
            device=retained["device"],
            inode=retained["inode"],
            label="post-quarantine scan two",
        )
        final_state, final_identity = _layout(
            directory=directory,
            root_device=root_device,
            candidate=candidate,
            quarantine_name=quarantine_name,
        )
        if final_state != "quarantine" or final_identity != retained:
            raise _blocked("Studio quarantine identity changed after post scan")
        current_epoch()

    receipt = {
        "schema": SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "writer_receipt_sha256": writer["receipt_sha256"],
        "runtime_receipt_sha256": runtime["receipt_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "process_scan_receipt_sha256": prior["receipt_sha256"],
        "operation_id": runtime["operation_id"],
        "generation": runtime["generation"],
        "boot_id": boot_id.strip(),
        "staging_name": candidate["staging_name"],
        "quarantine_name": quarantine_name,
        "retained_identity": retained,
        "pre_quarantine_scan_passes": 0 if recovered else 2,
        "post_quarantine_scan_passes": 2,
        "recovered_existing_quarantine": recovered,
        "mutation_performed_by_this_run": renamed,
        "staging_namespace_detached": True,
        "quarantine_inode_retained": True,
        "final_layout_preserved": True,
        "candidate_reference_drain_verified": True,
        "process_drain_verified": False,
        "cleanup_authorized": False,
        "settlement_authorized": False,
        "filesystem_mutation_performed": True,
        "quarantine_deletion_permitted": False,
        "final_deletion_permitted": False,
        "full_host_closure": False,
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def _validated_state_root(path: Path) -> int:
    if not path.is_absolute() or path == Path("/") or ".." in path.parts:
        raise StagingQuarantineBlocked("quarantine state root is unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        current = os.open("/", flags)
    except OSError as exc:
        raise StagingQuarantineBlocked(
            "quarantine state root cannot start from filesystem root"
        ) from exc
    try:
        for component in path.parts[1:]:
            try:
                nxt = os.open(component, flags, dir_fd=current)
            except OSError as exc:
                raise StagingQuarantineBlocked(
                    "quarantine state root descriptor chain is unavailable"
                ) from exc
            os.close(current)
            current = nxt
        metadata = os.fstat(current)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            raise StagingQuarantineBlocked(
                "quarantine state root is not private"
            )
        return current
    except BaseException:
        os.close(current)
        raise


def _write_private(
    state_root: Path, candidate_sha256: str, value: dict[str, Any]
) -> Path:
    name = _quarantine_name(candidate_sha256)
    # Receipt name is separate from the Studio quarantine name but shares the
    # exact candidate digest, so B6 can locate only the candidate-bound proof.
    receipt_name = name.removeprefix(".studio-quarantine-").removesuffix(
        ".retained"
    ) + ".json"
    root_fd = _validated_state_root(state_root)
    try:
        try:
            descriptor = os.open(
                receipt_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=root_fd,
            )
        except FileExistsError as exc:
            raise StagingQuarantineBlocked(
                "quarantine receipt already exists"
            ) from exc
        try:
            content = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("quarantine receipt write made no progress")
                view = view[count:]
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
            ):
                raise StagingQuarantineBlocked(
                    "quarantine receipt is not private"
                )
        finally:
            os.close(descriptor)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    return state_root / receipt_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--writer-receipt", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument("--cleanup-candidate", type=Path, required=True)
    parser.add_argument("--process-scan-receipt", type=Path, required=True)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    args = parser.parse_args()
    try:
        writer = json.loads(args.writer_receipt.read_text(encoding="utf-8"))
        runtime = json.loads(args.runtime_receipt.read_text(encoding="utf-8"))
        candidate = json.loads(args.cleanup_candidate.read_text(encoding="utf-8"))
        prior = json.loads(args.process_scan_receipt.read_text(encoding="utf-8"))
        receipt = evaluate_and_quarantine(
            writer_receipt=writer,
            runtime_receipt=runtime,
            cleanup_candidate=candidate,
            process_scan_receipt=prior,
            container_provider=scan._containers,
            proc_root=args.proc_root,
            boot_id=scan._boot_id(),
        )
        if os.geteuid() != 0:
            raise StagingQuarantineBlocked("B5 host receipt requires root")
        _write_private(STATE_ROOT, candidate["candidate_sha256"], receipt)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        StagingQuarantineBlocked,
        scan.ProcessScanBlocked,
    ) as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
