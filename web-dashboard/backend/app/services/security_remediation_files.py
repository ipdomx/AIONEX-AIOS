"""Bounded, descriptor-relative remediation preparation; no application or provider I/O.

Directory descriptors pin the trees being read and cleaned. Name binding checks
detect substitution; Linux has no inode-conditional unlink/rmdir, so final name
removal remains observational and any inconsistent removal retains uncertainty.
Published bundles are never removed by failure cleanup.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

_SKIP = {".git", "node_modules", "vendor", ".venv", "venv", ".next", "dist", "build", "coverage"}
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_CHUNK_BYTES = 1024 * 1024


class RemediationFilesystemUncertain(RuntimeError):
    """The observed namespace or cleanup cannot establish a settled result."""


class RemediationPreparationStopped(RuntimeError):
    """Cooperative interruption leaves the durable activity for reconciliation."""


class RemediationSourceLimit(ValueError):
    """A bounded copy exceeded its declared file, entry, or byte budget."""


@dataclass(frozen=True)
class RemediationBuildInput:
    remediation_id: str
    activity_id: str
    source: Path = field(repr=False)
    allowed_roots: tuple[Path, ...] = field(repr=False)
    work_root: Path = field(repr=False)
    plan_json: bytes = field(repr=False)


@dataclass(frozen=True)
class RemediationIOOutcome:
    evidence: dict[str, Any] | None = None
    error_type: str | None = None
    unresolved_reason: str | None = None


@dataclass
class _CopyState:
    max_files: int
    max_bytes: int
    max_entries: int
    identities: dict[tuple[str, ...], tuple[int, int]]
    files: int = 0
    total: int = 0
    entries: int = 0
    manifest: Any = field(default_factory=hashlib.sha256)
    source_signatures: dict[tuple[str, ...], tuple[int, ...]] = field(default_factory=dict)
    forbidden_directories: set[tuple[int, int]] = field(default_factory=set)
    output_signatures: dict[tuple[str, ...], tuple[int, ...]] = field(default_factory=dict)


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _signature(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def _check_stop(stop: threading.Event) -> None:
    if stop.is_set():
        raise RemediationPreparationStopped("Remediation preparation interrupted")


def _close_descriptors(*descriptors: int) -> None:
    """Attempt every close once; never retry an ambiguously closed descriptor."""
    failed = False
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if failed:
        raise RemediationFilesystemUncertain("Remediation descriptor close is uncertain")


def _open_absolute_directory(path: Path) -> int:
    """Reject symlinks in every ancestor without resolving them first."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Remediation directory must be an absolute bounded path")
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        for component in path.parts[1:]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            previous = descriptor
            descriptor = child
            os.close(previous)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verify_absolute_binding(path: Path, descriptor: int) -> None:
    check = _open_absolute_directory(path)
    try:
        if _identity(os.fstat(check)) != _identity(os.fstat(descriptor)):
            raise RemediationFilesystemUncertain("Remediation directory binding changed")
    finally:
        os.close(check)


def _verify_binding(parent: int, name: str, descriptor: int) -> None:
    observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if _identity(observed) != _identity(os.fstat(descriptor)):
        raise RemediationFilesystemUncertain("Remediation entry binding changed")


def _require_private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.geteuid()
    ):
        raise RemediationFilesystemUncertain("Remediation directory ownership is invalid")


def validate_work_root(path: Path) -> None:
    """Inspect an already prepared root; never mkdir, chmod, seed, or repair."""
    descriptor = _open_absolute_directory(path)
    try:
        _require_private_directory(descriptor)
        _verify_absolute_binding(path, descriptor)
    finally:
        os.close(descriptor)


def _publish_noreplace(
    source_fd: int, source_name: str, destination_fd: int, destination_name: str
) -> None:
    """Linux atomic no-clobber rename, including the verified x86_64 musl ABI."""
    if platform.system() != "Linux":
        raise OSError(errno.ENOSYS, "Atomic remediation publication unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    args = (
        ctypes.c_int(source_fd), ctypes.c_char_p(os.fsencode(source_name)),
        ctypes.c_int(destination_fd), ctypes.c_char_p(os.fsencode(destination_name)),
        ctypes.c_uint(1),
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
        raise OSError(errno.ENOSYS, "Atomic remediation publication ABI unavailable")
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, "Atomic remediation publication failed")


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError(errno.EIO, "Remediation file write did not progress")
        view = view[written:]


def _copy_regular_file(
    source_fd: int,
    destination_fd: int,
    name: str,
    relative: tuple[str, ...],
    state: _CopyState,
    stop: threading.Event,
) -> None:
    before = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=source_fd,
    )
    output = -1
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
            or _signature(before) != _signature(opened)
        ):
            raise RemediationFilesystemUncertain("Remediation source file changed")
        state.files += 1
        if state.files > state.max_files:
            raise RemediationSourceLimit("Remediation file budget exceeded")
        output = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=destination_fd,
        )
        os.fchmod(output, 0o600)
        state.identities[relative] = _identity(os.fstat(output))
        digest = hashlib.sha256()
        copied = 0
        while True:
            _check_stop(stop)
            # Read at most one byte beyond the remaining budget, including growth.
            allowance = min(_CHUNK_BYTES, max(1, state.max_bytes - state.total + 1))
            chunk = os.read(descriptor, allowance)
            if not chunk:
                break
            copied += len(chunk)
            state.total += len(chunk)
            if state.total > state.max_bytes:
                raise RemediationSourceLimit("Remediation byte budget exceeded")
            _write_all(output, chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            copied != opened.st_size or after.st_nlink != 1
            or _signature(after) != _signature(opened)
        ):
            raise RemediationFilesystemUncertain("Remediation source file mutated")
        state.source_signatures[relative[1:]] = _signature(after)
        _verify_binding(source_fd, name, descriptor)
        _verify_binding(destination_fd, name, output)
        os.fsync(output)
        state.manifest.update(
            json.dumps(
                ["/".join(relative), copied, digest.hexdigest()],
                separators=(",", ":"), ensure_ascii=True,
            ).encode("ascii") + b"\n"
        )
    finally:
        try:
            if output >= 0:
                state.output_signatures[relative] = _signature(os.fstat(output))
        finally:
            _close_descriptors(output, descriptor)


def _source_directory_names(descriptor: int, state: _CopyState) -> list[str]:
    """Bound readdir allocation before sorting, including entries later skipped."""
    names: list[str] = []
    with os.scandir(descriptor) as entries:
        for entry in entries:
            state.entries += 1
            if state.entries > state.max_entries:
                raise RemediationSourceLimit("Remediation entry budget exceeded")
            names.append(entry.name)
    return sorted(names)


def _known_entry_names(descriptor: int, expected: set[str]) -> list[str]:
    """Unknown/duplicate names stop enumeration before unbounded materialization."""
    observed: set[str] = set()
    with os.scandir(descriptor) as entries:
        for entry in entries:
            if entry.name not in expected or entry.name in observed:
                raise RemediationFilesystemUncertain("Remediation directory entries changed")
            observed.add(entry.name)
    if observed != expected:
        raise RemediationFilesystemUncertain("Remediation directory entries disappeared")
    return sorted(observed)


def _copy_directory(
    source_fd: int,
    destination_fd: int,
    relative: tuple[str, ...],
    state: _CopyState,
    stop: threading.Event,
) -> None:
    if len(relative) > 128:
        raise RemediationSourceLimit("Remediation directory depth budget exceeded")
    before = os.fstat(source_fd)
    if _identity(before) in state.forbidden_directories:
        raise RemediationFilesystemUncertain("Remediation source overlaps its destination")
    state.source_signatures[relative[1:]] = _signature(before)
    for name in _source_directory_names(source_fd, state):
        _check_stop(stop)
        if name in _SKIP:
            continue
        metadata = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        child_relative = relative + (name,)
        if stat.S_ISLNK(metadata.st_mode):
            continue
        if stat.S_ISDIR(metadata.st_mode):
            source_child = os.open(name, _DIRECTORY_FLAGS, dir_fd=source_fd)
            destination_child = -1
            try:
                if _signature(metadata) != _signature(os.fstat(source_child)):
                    raise RemediationFilesystemUncertain("Remediation source directory changed")
                os.mkdir(name, 0o700, dir_fd=destination_fd)
                destination_child = os.open(name, _DIRECTORY_FLAGS, dir_fd=destination_fd)
                state.identities[child_relative] = _identity(os.fstat(destination_child))
                _require_private_directory(destination_child)
                _copy_directory(source_child, destination_child, child_relative, state, stop)
                _verify_binding(source_fd, name, source_child)
                _verify_binding(destination_fd, name, destination_child)
                os.fsync(destination_child)
            finally:
                _close_descriptors(destination_child, source_child)
        elif stat.S_ISREG(metadata.st_mode):
            _copy_regular_file(source_fd, destination_fd, name, child_relative, state, stop)
    if _signature(before) != _signature(os.fstat(source_fd)):
        raise RemediationFilesystemUncertain("Remediation source directory mutated")
    os.fsync(destination_fd)


def _verify_source_inventory(
    descriptor: int,
    relative: tuple[str, ...],
    signatures: dict[tuple[str, ...], tuple[int, ...]],
    children_by_parent: dict[tuple[str, ...], set[str]] | None = None,
) -> None:
    if children_by_parent is None:
        children_by_parent = {}
        for path in signatures:
            if path:
                children_by_parent.setdefault(path[:-1], set()).add(path[-1])
    if _signature(os.fstat(descriptor)) != signatures[relative]:
        raise RemediationFilesystemUncertain("Remediation source inventory changed")
    children = children_by_parent.get(relative, set())
    for name in sorted(children):
        path = relative + (name,)
        expected = signatures[path]
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if _signature(metadata) != expected:
            raise RemediationFilesystemUncertain("Remediation source entry changed after copy")
        if stat.S_ISDIR(metadata.st_mode):
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                _verify_source_inventory(child, path, signatures, children_by_parent)
                _verify_binding(descriptor, name, child)
            finally:
                os.close(child)
        elif metadata.st_nlink != 1:
            raise RemediationFilesystemUncertain("Remediation source gained an alias")


def _verify_created_tree(
    descriptor: int,
    relative: tuple[str, ...],
    identities: dict[tuple[str, ...], tuple[int, int]],
    file_signatures: dict[tuple[str, ...], tuple[int, ...]],
    children_by_parent: dict[tuple[str, ...], set[str]] | None = None,
) -> None:
    if children_by_parent is None:
        children_by_parent = {}
        for path in identities:
            if path:
                children_by_parent.setdefault(path[:-1], set()).add(path[-1])
    if _identity(os.fstat(descriptor)) != identities[relative]:
        raise RemediationFilesystemUncertain("Remediation staging directory changed")
    _require_private_directory(descriptor)
    expected_names = children_by_parent.get(relative, set())
    for name in _known_entry_names(descriptor, expected_names):
        path = relative + (name,)
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if _identity(metadata) != identities[path] or stat.S_ISLNK(metadata.st_mode):
            raise RemediationFilesystemUncertain("Remediation staging entry changed")
        if stat.S_ISDIR(metadata.st_mode):
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                _verify_created_tree(child, path, identities, file_signatures, children_by_parent)
                _verify_binding(descriptor, name, child)
            finally:
                os.close(child)
        elif (
            not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
            or _signature(metadata) != file_signatures.get(path)
        ):
            raise RemediationFilesystemUncertain("Remediation staging file changed")


def _remove_owned_contents(
    descriptor: int,
    relative: tuple[str, ...],
    identities: dict[tuple[str, ...], tuple[int, int]],
    children_by_parent: dict[tuple[str, ...], set[str]] | None = None,
) -> None:
    if children_by_parent is None:
        children_by_parent = {}
        for path in identities:
            if path:
                children_by_parent.setdefault(path[:-1], set()).add(path[-1])
    for name in _known_entry_names(descriptor, children_by_parent.get(relative, set())):
        child_relative = relative + (name,)
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if identities.get(child_relative) != _identity(metadata):
            raise RemediationFilesystemUncertain("Remediation cleanup found an unowned entry")
        directory = stat.S_ISDIR(metadata.st_mode)
        flags = _DIRECTORY_FLAGS if directory else os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
        child = os.open(name, flags, dir_fd=descriptor)
        try:
            if _identity(os.fstat(child)) != identities[child_relative]:
                raise RemediationFilesystemUncertain("Remediation cleanup entry changed")
            if directory:
                _remove_owned_contents(child, child_relative, identities, children_by_parent)
            _verify_binding(descriptor, name, child)
            if directory:
                os.rmdir(name, dir_fd=descriptor)
            else:
                os.unlink(name, dir_fd=descriptor)
            if os.fstat(child).st_nlink != 0:
                raise RemediationFilesystemUncertain("Remediation cleanup removal is uncertain")
        finally:
            os.close(child)


def _cleanup_owned_stage(
    parent_fd: int,
    stage_name: str,
    stage_fd: int,
    identities: dict[tuple[str, ...], tuple[int, int]],
) -> None:
    """Traverse only the pinned original and only recorded created identities."""
    if _identity(os.fstat(stage_fd)) != identities.get(()):
        raise RemediationFilesystemUncertain("Remediation stage identity changed")
    _verify_binding(parent_fd, stage_name, stage_fd)
    _remove_owned_contents(stage_fd, (), identities)
    _verify_binding(parent_fd, stage_name, stage_fd)
    os.rmdir(stage_name, dir_fd=parent_fd)
    if os.fstat(stage_fd).st_nlink != 0:
        raise RemediationFilesystemUncertain("Remediation stage removal is uncertain")
    os.fsync(parent_fd)


def prepare_remediation_bundle(
    build_input: RemediationBuildInput,
    stop: threading.Event,
    *,
    max_files: int = 25_000,
    max_bytes: int = 1_073_741_824,
    max_entries: int = 100_000,
) -> RemediationIOOutcome:
    """Own all payload I/O through publication or verified staging cleanup."""
    descriptors: list[int] = []
    stage_fd = -1
    temporary_fd = -1
    stage_name = build_input.activity_id
    identities: dict[tuple[str, ...], tuple[int, int]] = {}
    state: _CopyState | None = None
    published = False
    publication_started = False
    result = RemediationIOOutcome(error_type="RemediationPreparationFailed")
    try:
        if any(type(value) is not int or value <= 0 for value in (max_files, max_bytes, max_entries)):
            raise ValueError("Remediation copy limits must be positive integers")
        for identifier in (build_input.remediation_id, build_input.activity_id):
            if str(UUID(identifier)) != identifier:
                raise ValueError("Remediation identifiers must be canonical UUIDs")
        if (
            not build_input.source.is_absolute()
            or ".." in build_input.source.parts
            or not any(
                build_input.source == root or root in build_input.source.parents
                for root in build_input.allowed_roots if root.is_absolute()
            )
        ):
            raise ValueError("Remediation source is outside the allowed roots")
        if (
            build_input.source == build_input.work_root
            or build_input.source in build_input.work_root.parents
            or build_input.work_root in build_input.source.parents
        ):
            raise RemediationFilesystemUncertain("Remediation source and destination overlap")
        _check_stop(stop)
        root_fd = _open_absolute_directory(build_input.work_root)
        descriptors.append(root_fd)
        _require_private_directory(root_fd)
        try:
            os.stat(build_input.remediation_id, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = False
        else:
            existing = True
        if existing:
            raise RemediationFilesystemUncertain("Remediation destination already exists")
        source_fd = _open_absolute_directory(build_input.source)
        descriptors.append(source_fd)
        source_initial = _signature(os.fstat(source_fd))
        try:
            os.mkdir(".tmp", 0o700, dir_fd=root_fd)
        except FileExistsError:
            temporary_exists = True
        else:
            temporary_exists = False
        temporary_fd = os.open(".tmp", _DIRECTORY_FLAGS, dir_fd=root_fd)
        descriptors.append(temporary_fd)
        _require_private_directory(temporary_fd)
        if not temporary_exists:
            os.fsync(root_fd)
        os.mkdir(stage_name, 0o700, dir_fd=temporary_fd)
        stage_fd = os.open(stage_name, _DIRECTORY_FLAGS, dir_fd=temporary_fd)
        descriptors.append(stage_fd)
        identities[()] = _identity(os.fstat(stage_fd))
        _require_private_directory(stage_fd)
        os.mkdir("source", 0o700, dir_fd=stage_fd)
        copy_fd = os.open("source", _DIRECTORY_FLAGS, dir_fd=stage_fd)
        descriptors.append(copy_fd)
        identities[("source",)] = _identity(os.fstat(copy_fd))
        state = _CopyState(max_files, max_bytes, max_entries, identities)
        state.forbidden_directories = {_identity(os.fstat(fd)) for fd in (root_fd, temporary_fd, stage_fd)}
        _copy_directory(source_fd, copy_fd, ("source",), state, stop)
        plan_fd = os.open(
            "remediation-plan.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=stage_fd,
        )
        try:
            identities[("remediation-plan.json",)] = _identity(os.fstat(plan_fd))
            os.fchmod(plan_fd, 0o600)
            _write_all(plan_fd, build_input.plan_json)
            os.fsync(plan_fd)
            _verify_binding(stage_fd, "remediation-plan.json", plan_fd)
        finally:
            try:
                state.output_signatures[("remediation-plan.json",)] = _signature(os.fstat(plan_fd))
            finally:
                os.close(plan_fd)
        _check_stop(stop)
        _verify_source_inventory(source_fd, (), state.source_signatures)
        _verify_created_tree(stage_fd, (), identities, state.output_signatures)
        _verify_absolute_binding(build_input.source, source_fd)
        if source_initial != _signature(os.fstat(source_fd)):
            raise RemediationFilesystemUncertain("Remediation source binding mutated")
        _verify_absolute_binding(build_input.work_root, root_fd)
        _verify_binding(root_fd, ".tmp", temporary_fd)
        _verify_binding(temporary_fd, stage_name, stage_fd)
        _verify_binding(stage_fd, "source", copy_fd)
        os.fsync(stage_fd)
        os.fsync(temporary_fd)
        publication_started = True
        _publish_noreplace(temporary_fd, stage_name, root_fd, build_input.remediation_id)
        published = True
        _verify_binding(root_fd, build_input.remediation_id, stage_fd)
        _verify_created_tree(stage_fd, (), identities, state.output_signatures)
        _verify_absolute_binding(build_input.work_root, root_fd)
        os.fsync(root_fd)
        os.fsync(temporary_fd)
        _check_stop(stop)
        result = RemediationIOOutcome(evidence={
            "files": state.files,
            "bytes": state.total,
            "manifest_digest": state.manifest.hexdigest(),
            "plan_digest": hashlib.sha256(build_input.plan_json).hexdigest(),
        })
    except BaseException as exc:
        uncertain = isinstance(exc, (RemediationFilesystemUncertain, RemediationPreparationStopped))
        # OSError can be a namespace/I/O ambiguity; retain even if cleanup succeeds.
        uncertain = uncertain or isinstance(exc, OSError) or publication_started or not isinstance(exc, Exception)
        result = RemediationIOOutcome(
            error_type=type(exc).__name__,
            unresolved_reason="remediation-filesystem-uncertain" if uncertain else None,
        )
    finally:
        if stage_fd >= 0 and not published:
            try:
                _verify_absolute_binding(build_input.work_root, root_fd)
                _verify_binding(root_fd, ".tmp", temporary_fd)
                if state is not None:
                    _verify_created_tree(stage_fd, (), identities, state.output_signatures)
                _cleanup_owned_stage(temporary_fd, stage_name, stage_fd, identities)
            except BaseException:
                result = RemediationIOOutcome(
                    error_type=result.error_type or "RemediationCleanupIncomplete",
                    unresolved_reason="remediation-cleanup-incomplete",
                )
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                result = RemediationIOOutcome(
                    error_type=result.error_type or "RemediationDescriptorCloseFailed",
                    unresolved_reason="remediation-descriptor-close-uncertain",
                )
    return result
