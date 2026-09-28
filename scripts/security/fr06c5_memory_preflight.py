#!/usr/bin/env python3
"""Read-only FR-06C5E memory preflight; never an activation or drain permit.

The swap identity rule preserves prepared commit 13b76558. The underlay scan
pins directory inodes and includes file-backed mappings after descriptors close.
A missing/denied/changing observation is UNKNOWN, never zero. No swap, mount,
process-control, fstab, key, service, rollback or provider command is implemented.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Self

PREPARED_SOURCE = "13b76558f585f432acc831b6ad0448ee5909b5bd"
MAX_ENTRIES = 100_000
MAX_DEPTH = 64
MAX_PROC_BYTES = 16 * 1024 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAP_LINE = re.compile(
    r"^([0-9a-f]+)-([0-9a-f]+) ([r-][w-][x-][sp]) ([0-9a-f]+) "
    r"([0-9a-f]+):([0-9a-f]+) ([0-9]+)(?:\s+(.*))?$"
)


class IncompleteObservation(RuntimeError):
    """The observation cannot support a zero-reference conclusion."""


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def same_swap_device(name: str | Path, target: str | Path) -> bool:
    """Match /dev/dm-N and mapper aliases by device number, not pathname."""
    try:
        expected = os.stat(target)
        if not stat.S_ISBLK(expected.st_mode):
            raise IncompleteObservation("expected swap mapper is not a block device")
        observed = os.stat(name)
    except OSError as exc:
        raise IncompleteObservation("swap device identity unavailable") from exc
    return stat.S_ISBLK(observed.st_mode) and observed.st_rdev == expected.st_rdev


def parse_swaps(content: str) -> list[dict[str, Any]]:
    lines = content.splitlines()
    if not lines or lines[0].split() != [
        "Filename",
        "Type",
        "Size",
        "Used",
        "Priority",
    ]:
        raise IncompleteObservation("swap inventory header invalid")
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split()
        if (
            len(parts) != 5
            or not parts[0].startswith("/")
            or parts[1] not in {"file", "partition"}
        ):
            raise IncompleteObservation("swap inventory row invalid")
        name = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), parts[0])
        try:
            size, used, priority = (int(v) for v in parts[2:])
        except ValueError as exc:
            raise IncompleteObservation("swap inventory numbers invalid") from exc
        if name in names or size <= 0 or not 0 <= used <= size:
            raise IncompleteObservation("swap inventory is duplicated or inconsistent")
        names.add(name)
        result.append(
            {
                "name": name,
                "type": parts[1],
                "size_bytes": size * 1024,
                "used_bytes": used * 1024,
                "priority": priority,
            }
        )
    return result


def require_only_encrypted_swap(
    rows: list[dict[str, Any]], mapper: Path
) -> dict[str, Any]:
    if len(rows) != 1 or not same_swap_device(rows[0]["name"], mapper):
        raise IncompleteObservation("exactly one matching encrypted swap required")
    # This is a device identity check, not cryptographic mapper/backing attestation.
    return {**rows[0], "cryptographic_mapping_attested": False}


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@dataclass(frozen=True)
class Inventory:
    source: str
    root_identity: tuple[int, int]
    entries: tuple[tuple[str, tuple[int, ...]], ...]

    @cached_property
    def object_ids(self) -> frozenset[tuple[int, int]]:
        return frozenset((metadata[0], metadata[1]) for _, metadata in self.entries)

    @cached_property
    def devices(self) -> frozenset[int]:
        return frozenset(device for device, _ in self.object_ids)

    @property
    def sha256(self) -> str:
        return canonical_digest(
            {
                "source": self.source,
                "root_identity": self.root_identity,
                "entries": self.entries,
            }
        )


class PinnedUnderlay:
    """Retain the same directory across rename/covering; never read file bytes.

    The caller must quiesce writers separately. An inode pin and repeated scan
    cannot establish a freeze, recall remote work, or prove historical erasure.
    """

    def __init__(self, source: Path):
        self.source = Path(source)
        self.fd = -1
        if (
            not self.source.is_absolute()
            or ".." in self.source.parts
            or self.source == Path("/")
        ):
            raise IncompleteObservation(
                "underlay path must be an explicit absolute nonroot directory"
            )

    def __enter__(self) -> Self:
        fd = os.open("/", DIR_FLAGS)
        try:
            for part in self.source.parts[1:]:
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            self.fd = fd
            return self
        except OSError as exc:
            os.close(fd)
            raise IncompleteObservation(
                "underlay path is unavailable or contains a symlink"
            ) from exc

    def __exit__(self, *_: object) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def snapshot(self) -> Inventory:
        if self.fd < 0:
            raise IncompleteObservation("underlay is not pinned")
        entries: list[tuple[str, tuple[int, ...]]] = []
        root = os.fstat(self.fd)

        def visit(fd: int, prefix: tuple[str, ...]) -> None:
            if len(prefix) > MAX_DEPTH or len(entries) >= MAX_ENTRIES:
                raise IncompleteObservation("underlay inventory bound exceeded")
            before = _fingerprint(os.fstat(fd))
            entries.append(("/".join(prefix), before))
            names = sorted(os.listdir(fd))
            for name in names:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, DIR_FLAGS, dir_fd=fd)
                    try:
                        if _fingerprint(os.fstat(child)) != _fingerprint(info):
                            raise IncompleteObservation(
                                "directory identity changed while opening"
                            )
                        visit(child, (*prefix, name))
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    entries.append(("/".join((*prefix, name)), _fingerprint(info)))
                else:
                    raise IncompleteObservation(
                        "underlay symlink or special entry requires review"
                    )
                if len(entries) > MAX_ENTRIES or _fingerprint(
                    os.stat(name, dir_fd=fd, follow_symlinks=False)
                ) != _fingerprint(info):
                    raise IncompleteObservation("underlay changed during inventory")
            if before != _fingerprint(os.fstat(fd)):
                raise IncompleteObservation(
                    "underlay directory changed during inventory"
                )

        try:
            visit(self.fd, ())
        except OSError as exc:
            raise IncompleteObservation("underlay inventory incomplete") from exc
        return Inventory(str(self.source), (root.st_dev, root.st_ino), tuple(entries))

    def visible_path_matches(self) -> bool:
        try:
            current = os.lstat(self.source)
            pinned = os.fstat(self.fd)
        except OSError as exc:
            raise IncompleteObservation(
                "visible underlay identity unavailable"
            ) from exc
        return stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == (
            pinned.st_dev,
            pinned.st_ino,
        )


def _bounded_text(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="strict") as stream:
            text = stream.read(MAX_PROC_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise IncompleteObservation("process observation inaccessible") from exc
    if len(text) > MAX_PROC_BYTES:
        raise IncompleteObservation("process observation bound exceeded")
    return text


def _numeric_entries(path: Path) -> tuple[str, ...]:
    try:
        return tuple(sorted(p.name for p in path.iterdir() if p.name.isdigit()))
    except OSError as exc:
        raise IncompleteObservation("process/thread enumeration incomplete") from exc


def _process_identity(thread: Path) -> tuple[int, str]:
    content = _bounded_text(thread / "stat")
    try:
        leader, rest = content.rsplit(")", 1)
        pid = int(leader.split("(", 1)[0].strip())
        fields = rest.split()
        started = fields[19]
        if len(fields) < 20 or not started.isdecimal() or str(pid) != thread.name:
            raise ValueError("invalid process identity")
        return pid, started
    except (ValueError, IndexError) as exc:
        raise IncompleteObservation("process identity malformed") from exc


def mapping_rows(text: str) -> list[tuple[int, int, str, str, str]]:
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = MAP_LINE.fullmatch(line)
        if match is None or int(match[1], 16) >= int(match[2], 16):
            raise IncompleteObservation("process mapping row malformed")
        try:
            device = os.makedev(int(match[5], 16), int(match[6], 16))
        except (OverflowError, ValueError) as exc:
            raise IncompleteObservation("mapping device number invalid") from exc
        rows.append(
            (device, int(match[7]), match[8] or "", match[3], match[1] + "-" + match[2])
        )
    return rows


def _match(
    inv: Inventory, device: int, inode: int, target: str, *, unlinked: bool
) -> str | None:
    if (device, inode) in inv.object_ids:
        return "underlay-inode"
    clean = target.removesuffix(" (deleted)")
    if clean == inv.source or clean.startswith(inv.source.rstrip("/") + "/"):
        return "underlay-path"
    if unlinked and inode and device in inv.devices:
        return "unlinked-same-filesystem-provenance-unknown"
    return None


def scan_references(
    pin: PinnedUnderlay,
    *,
    proc_root: Path = Path("/proc"),
    selected_pids: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Observe pinned underlay references; filtered scans are never host coverage.

    PID churn and inaccessible data fail closed. A caller-supplied PID filter is
    useful for owned laboratory processes only; the CLI does not expose it.
    """
    before = pin.snapshot()
    pids = (
        _numeric_entries(proc_root)
        if selected_pids is None
        else tuple(sorted(str(p) for p in selected_pids))
    )
    if (
        not pids
        or len(set(pids)) != len(pids)
        or any(not p.isdecimal() or int(p) <= 0 for p in pids)
    ):
        raise IncompleteObservation("empty or invalid process scope")
    hits: list[dict[str, Any]] = []
    thread_count = 0
    own_pin_exclusions = 0
    for pid in pids:
        process = proc_root / pid
        tids = _numeric_entries(process / "task")
        if not tids:
            raise IncompleteObservation("no observable process threads")
        for tid in tids:
            thread_count += 1
            thread = process / "task" / tid
            identity = _process_identity(thread)
            fds = _numeric_entries(thread / "fd")
            references = [("cwd", thread / "cwd"), ("root", thread / "root")]
            references += [("fd", thread / "fd" / descriptor) for descriptor in fds]
            for kind, ref in references:
                if (
                    proc_root == Path("/proc")
                    and int(pid) == os.getpid()
                    and kind == "fd"
                    and ref.name == str(pin.fd)
                ):
                    own_pin_exclusions += 1
                    continue  # Exact read-only measuring descriptor, never another holder.
                try:
                    first = os.stat(ref)
                    target = os.readlink(ref)
                    second = os.stat(ref)
                except (FileNotFoundError, ProcessLookupError):
                    raise IncompleteObservation(
                        "process reference disappeared during scan"
                    ) from None
                except OSError as exc:
                    raise IncompleteObservation(
                        "process reference inaccessible"
                    ) from exc
                if (first.st_dev, first.st_ino) != (second.st_dev, second.st_ino):
                    raise IncompleteObservation("process reference identity changed")
                reason = _match(
                    before,
                    second.st_dev,
                    second.st_ino,
                    target,
                    unlinked=second.st_nlink == 0,
                )
                if reason:
                    hits.append(
                        {
                            "pid": int(pid),
                            "tid": int(tid),
                            "kind": kind,
                            "reference": ref.name,
                            "reason": reason,
                        }
                    )
            for device, inode, target, permissions, address in mapping_rows(
                _bounded_text(thread / "maps")
            ):
                if not inode:
                    continue
                reason = _match(
                    before,
                    device,
                    inode,
                    target,
                    unlinked=target.endswith(" (deleted)"),
                )
                if reason:
                    hits.append(
                        {
                            "pid": int(pid),
                            "tid": int(tid),
                            "kind": "mmap",
                            "reference": address,
                            "permissions": permissions,
                            "reason": reason,
                        }
                    )
            if _process_identity(thread) != identity:
                raise IncompleteObservation("process identity changed during scan")
        if _numeric_entries(process / "task") != tids:
            raise IncompleteObservation("thread population changed during scan")
    if selected_pids is None and _numeric_entries(proc_root) != pids:
        raise IncompleteObservation("process population changed during scan")
    after = pin.snapshot()
    if after != before:
        raise IncompleteObservation("pinned underlay changed during reference scan")
    return {
        "status": "references_present" if hits else "observed_clear",
        "reference_count": len(hits),
        "references": hits,
        "underlay_sha256": before.sha256,
        "underlay_entries": len(before.entries),
        "root_identity": list(before.root_identity),
        "visible_path_matches_pinned_underlay": pin.visible_path_matches(),
        "processes_scanned": len(pids),
        "threads_scanned": thread_count,
        "measuring_descriptor_exclusions": own_pin_exclusions,
        "scope": (
            "proc-visible-host"
            if proc_root == Path("/proc")
            else "synthetic-proc-fixture"
        )
        if selected_pids is None
        else "selected-owned-processes",
        "writers_quiesced_by_this_tool": False,
        "full_host_closure": False,
        "activation_authorized": False,
        "production_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlay", type=Path, required=True)
    args = parser.parse_args()
    try:
        with PinnedUnderlay(args.underlay) as pin:
            result = scan_references(pin)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "observed_clear" else 2
    except (IncompleteObservation, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "unknown",
                    "reason": str(exc),
                    "reference_count": None,
                    "activation_authorized": False,
                    "full_host_closure": False,
                    "production_changed": False,
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
