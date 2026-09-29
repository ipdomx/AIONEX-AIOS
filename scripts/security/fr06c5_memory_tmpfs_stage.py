"""C5E10 private, empty tmpfs staging with journaled native mount/unmount.

This module never covers /tmp, moves a mount, changes boot units or populates
application data. It creates a mount only at an operation-private new directory.
The mount source carries the operation marker at creation. Undo refuses a
nonempty, aliased, nested, foreign or busy mount, and uses umount2(flags=0),
never lazy/forced removal. All native-effect tests must use a separate VM.

A fresh independent closed context is mandatory. Advisory locks and source
markers do not exclude privileged actors, other namespaces or ABA replacement.
Production writer quiescence, encrypted-swap acceptance, underlay preservation,
publication to /tmp and boot recovery are separate, unimplemented gates here.
No C5E9 source or blocked receipt is imported or replaced by this part.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import stat
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import UUID

from scripts.security.fr06c5_memory_config_files import (
    _dir_identity,
    _file,
    _open_dir,
    _write_new,
)
from scripts.security.fr06c5_memory_kernel_observation import (
    Device,
    Mount,
    parse_mountinfo,
)
from scripts.security.fr06c5_memory_legacy_swap import memory_available
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

STEP = "prepare_tmpfs_mount"
MIN_CAPACITY = 1024**2
MAX_CAPACITY = 8 * 1024**3
MAX_TEXT = 4 * 1024**2


class TmpfsRejected(TransitionRejected):
    """No native effect or success claim with incomplete ownership evidence."""


def _require(value: bool, message: str) -> None:
    if not value:
        raise TmpfsRejected(message)


def marker(operation: str) -> str:
    _require(isinstance(operation, str) and str(UUID(operation)) == operation, "Canonical operation required")
    return "aionex-c5e10-" + UUID(operation).hex


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        _require(name not in result, "Duplicate tmpfs binding field")
        result[name] = value
    return result


def _text(path: str) -> str:
    data = bytearray()
    with Path(path).open("rb") as stream:
        while len(data) <= MAX_TEXT:
            block = stream.read(min(4096, MAX_TEXT + 1 - len(data)))
            if not block:
                break
            data.extend(block)
    _require(len(data) <= MAX_TEXT and data.endswith(b"\n") and b"\0" not in data, "Incomplete kernel text")
    return data.decode("utf-8", errors="strict")


def _visible(fd: int) -> tuple[int, ...]:
    info = os.fstat(fd)
    _require(stat.S_ISDIR(info.st_mode), "Mountpoint must be a directory")
    return tuple(int(getattr(info, name)) for name in ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid"))


@dataclass(frozen=True)
class Runtime:
    boot_id: str
    namespace: tuple[int, int]
    init_namespace: tuple[int, int]
    mount: Mount | None
    visible: tuple[int, ...]
    entries: int
    attributes: int
    aliases: int
    nested: int
    available: int
    capacity: int
    inodes: int
    used_blocks: int
    parent_private: bool


class Kernel(Protocol):
    def sample(self, bundle_fd: int, target: Path) -> Runtime: ...
    def create(self, bundle_fd: int, operation: str, capacity: int, inodes: int) -> None: ...
    def remove(self, bundle_fd: int) -> None: ...


class LinuxTmpfsKernel:
    """Fixed descriptor-relative target, one mount or one non-lazy unmount."""
    def sample(self, bundle_fd: int, target: Path) -> Runtime:
        own, init = os.stat("/proc/self/ns/mnt"), os.stat("/proc/1/ns/mnt")
        before = parse_mountinfo(_text("/proc/self/mountinfo"))
        exact = [row for row in before if row.target == str(target)]
        _require(len(exact) <= 1, "Stacked staging mounts are not accepted")
        ancestors = [row for row in before if str(target.parent) == row.target
                     or str(target.parent).startswith(row.target.rstrip("/") + "/")]
        _require(bool(ancestors), "Containing mount is unknown")
        length = max(len(row.target) for row in ancestors)
        nearest = [row for row in ancestors if len(row.target) == length]
        _require(len(nearest) == 1, "Containing mount is ambiguous")
        fd = os.open("mount", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=bundle_fd)
        try:
            visible = _visible(fd)
            reopened = _open_dir(target)
            try:
                _require(_visible(reopened) == visible, "Mountpoint path changed")
            finally:
                os.close(reopened)
            entries = len(os.listdir(fd))
            attributes = len(os.listxattr(fd))
            space = os.fstatvfs(fd)
            _require(_visible(fd) == visible, "Mountpoint changed during sample")
        finally:
            os.close(fd)
        after = parse_mountinfo(_text("/proc/self/mountinfo"))
        _require(before == after, "Mount topology changed during observation")
        mount = exact[0] if exact else None
        return Runtime(_text("/proc/sys/kernel/random/boot_id").strip(),
                       (own.st_dev, own.st_ino), (init.st_dev, init.st_ino), mount, visible,
                       entries, attributes, sum(row.device == mount.device for row in before) if mount else 0,
                       sum(row.target.startswith(str(target) + "/") for row in before),
                       memory_available(_text("/proc/meminfo")), space.f_blocks * space.f_frsize,
                       space.f_files, space.f_blocks - space.f_bfree, not nearest[0].optional)

    def create(self, bundle_fd: int, operation: str, capacity: int, inodes: int) -> None:
        _require(os.geteuid() == 0, "Native mount requires root in the independently attested VM/host")
        _dir_identity(bundle_fd, private=True)
        _require(type(capacity) is int and MIN_CAPACITY <= capacity <= MAX_CAPACITY and capacity % 4096 == 0
                 and type(inodes) is int and 128 <= inodes <= 1048576, "Explicit bounded tmpfs profile required")
        # The containing bundle FD is pinned. Independent frozen-writer authority
        # remains required for the final lookup; a pathname is not an ABA fence.
        target = f"/proc/self/fd/{bundle_fd}/mount".encode("ascii")
        options = f"mode=1777,uid=0,gid=0,size={capacity},nr_inodes={inodes}".encode("ascii")
        lib = ctypes.CDLL(None, use_errno=True)
        lib.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]
        lib.mount.restype = ctypes.c_int
        if lib.mount(marker(operation).encode("ascii"), target, b"tmpfs", 2 | 4, options) != 0:
            raise OSError(ctypes.get_errno(), "Private tmpfs creation failed; no automatic retry")

    def remove(self, bundle_fd: int) -> None:
        _require(os.geteuid() == 0, "Native unmount requires root in the independently attested VM/host")
        _dir_identity(bundle_fd, private=True)
        lib = ctypes.CDLL(None, use_errno=True)
        lib.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.umount2.restype = ctypes.c_int
        if lib.umount2(f"/proc/self/fd/{bundle_fd}/mount".encode("ascii"), 0) != 0:
            raise OSError(ctypes.get_errno(), "Private tmpfs is busy or removal failed; retained without force")


class TmpfsStageAdapter:
    """One private staging step. No mount move, data cleanup or /tmp activation."""
    def __init__(self, parent: Path, operation: str, context: Callable[[], BoundContext],
                 *, kernel: Kernel | None = None):
        marker(operation)
        self.parent, self.operation, self.read_context = parent, operation, context
        self.kernel = kernel or LinuxTmpfsKernel()
        self.target = parent / operation / "mount"
        self.parent_fd = self.lock_fd = self.bundle_fd = -1
        self.journal: Journal | None = None
        try:
            self.parent_fd = _open_dir(parent)
            self.parent_identity = _dir_identity(self.parent_fd, private=True)
            self.lock_fd = os.open(".tmpfs-stage.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                   0o600, dir_fd=self.parent_fd)
            lock = os.fstat(self.lock_fd)
            self._lock_ok(lock)
            self.lock_identity = (lock.st_dev, lock.st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.parent_fd)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _lock_ok(info: os.stat_result) -> None:
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and info.st_size == 0,
                 "Unsafe tmpfs staging lock")

    @classmethod
    def prepare(cls, parent: Path, operation: str, context: Callable[[], BoundContext], *,
                capacity: int, inodes: int, reserve: int, kernel: Kernel | None = None) -> Self:
        _require(type(capacity) is int and MIN_CAPACITY <= capacity <= MAX_CAPACITY and capacity % 4096 == 0
                 and type(inodes) is int and 128 <= inodes <= 1048576
                 and type(reserve) is int and reserve >= MIN_CAPACITY, "Explicit bounded capacity and reserve required")
        adapter = cls(parent, operation, context, kernel=kernel)
        try:
            bound = context()
            _require(isinstance(bound, BoundContext), "Independent typed closed context required")
            os.mkdir(operation, mode=0o700, dir_fd=adapter.parent_fd)
            os.fsync(adapter.parent_fd)
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.parent_fd)
            os.mkdir("mount", mode=0o700, dir_fd=adapter.bundle_fd)
            os.fsync(adapter.bundle_fd)
            sample = adapter.kernel.sample(adapter.bundle_fd, adapter.target)
            adapter._shape(sample, bound)
            _require(sample.mount is None and sample.entries == sample.attributes == sample.nested == sample.aliases == 0
                     and sample.parent_private and sample.available >= capacity + reserve,
                     "Initial staging target or memory reserve unsafe")
            fd = os.open("mount", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=adapter.bundle_fd)
            try:
                _require(_visible(fd) == sample.visible and stat.S_IMODE(sample.visible[2]) == 0o700
                         and sample.visible[3:] == (os.geteuid(), os.getegid()), "Original mountpoint identity differs")
            finally:
                os.close(fd)
            body = {"schema": 1, "operation": operation, "context": asdict(bound),
                    "parent": adapter.parent_identity, "bundle": _dir_identity(adapter.bundle_fd, private=True),
                    "lock": list(adapter.lock_identity), "target": str(adapter.target),
                    "original": list(sample.visible), "namespace": list(sample.namespace),
                    "capacity": capacity, "inodes": inodes, "reserve": reserve, "marker": marker(operation)}
            _write_new(adapter.bundle_fd, "binding.json", json.dumps(body, sort_keys=True).encode() + b"\n", 0o600)
            adapter._load()
            _require(context() == bound and adapter._sample().mount is None, "Staging changed during preparation")
            return adapter
        except BaseException:
            adapter.close()
            raise

    @classmethod
    def load(cls, parent: Path, operation: str, context: Callable[[], BoundContext], *, kernel: Kernel | None = None) -> Self:
        adapter = cls(parent, operation, context, kernel=kernel)
        try:
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.parent_fd)
            adapter._load()
            adapter.context()
            return adapter
        except BaseException:
            adapter.close()
            raise

    def _load(self) -> None:
        self.binding_identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        body = json.loads(raw, object_pairs_hook=_unique)
        _require(isinstance(body, dict) and set(body) == {"schema", "operation", "context", "parent", "bundle",
                 "lock", "target", "original", "namespace", "capacity", "inodes", "reserve", "marker"}, "Unexpected staging binding")
        _require(type(body["schema"]) is int and body["schema"] == 1 and body["operation"] == self.operation
                 and body["parent"] == self.parent_identity and body["bundle"] == _dir_identity(self.bundle_fd, private=True)
                 and body["lock"] == list(self.lock_identity) and body["target"] == str(self.target)
                 and body["marker"] == marker(self.operation), "Staging identity binding differs")
        for name, length in (("original", 5), ("namespace", 2)):
            _require(isinstance(body[name], list) and len(body[name]) == length
                     and all(type(n) is int and n >= 0 for n in body[name]), "Malformed bound kernel identity")
        _require(type(body["capacity"]) is int and MIN_CAPACITY <= body["capacity"] <= MAX_CAPACITY and body["capacity"] % 4096 == 0
                 and type(body["inodes"]) is int and 128 <= body["inodes"] <= 1048576
                 and type(body["reserve"]) is int and body["reserve"] >= MIN_CAPACITY, "Unsafe bound capacity")
        self.bound = BoundContext(**body["context"])
        self.binding, self.binding_hash = body, hashlib.sha256(raw).hexdigest()
        self.step = BoundStep(STEP, _digest({"binding": self.binding_hash, "active": False}),
                             _digest({"binding": self.binding_hash, "active": True}))
        self._identity()

    def _identity(self) -> None:
        _require(min(self.parent_fd, self.lock_fd, self.bundle_fd) >= 0, "Closed staging adapter")
        fd = _open_dir(self.parent)
        try:
            _require(_dir_identity(fd, private=True) == self.parent_identity, "Staging parent replaced")
        finally:
            os.close(fd)
        lock = os.stat(".tmpfs-stage.lock", dir_fd=self.parent_fd, follow_symlinks=False)
        self._lock_ok(lock)
        _require((lock.st_dev, lock.st_ino) == self.lock_identity, "Staging lock replaced")
        bundle = os.stat(self.operation, dir_fd=self.parent_fd, follow_symlinks=False)
        _require(stat.S_ISDIR(bundle.st_mode) and (bundle.st_dev, bundle.st_ino) ==
                 (self.binding["bundle"]["device"], self.binding["bundle"]["inode"])
                 and _dir_identity(self.bundle_fd, private=True) == self.binding["bundle"], "Operation bundle replaced")
        identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        _require(identity == self.binding_identity and hashlib.sha256(raw).hexdigest() == self.binding_hash
                 and set(os.listdir(self.bundle_fd)) == {"mount", "binding.json"}, "Staging metadata changed or incomplete")

    @staticmethod
    def _shape(sample: Runtime, bound: BoundContext) -> None:
        _require(isinstance(sample, Runtime) and sample.boot_id == bound.boot_id
                 and isinstance(sample.namespace, tuple) and len(sample.namespace) == 2
                 and all(type(n) is int and n > 0 for n in sample.namespace)
                 and sample.namespace == sample.init_namespace and type(sample.parent_private) is bool,
                 "Invalid boot or namespace evidence")
        _require(isinstance(sample.visible, tuple) and len(sample.visible) == 5
                 and all(type(n) is int and n >= 0 for n in sample.visible)
                 and all(type(n) is int and n >= 0 for n in (sample.entries, sample.attributes, sample.aliases,
                         sample.nested, sample.available, sample.capacity, sample.inodes, sample.used_blocks)), "Invalid kernel quantities")

    def context(self) -> BoundContext:
        self._identity()
        current = self.read_context()
        _require(isinstance(current, BoundContext) and current == self.bound, "Closed source/boot/authority changed")
        return current

    def _sample(self) -> Runtime:
        self._identity()
        start = time.monotonic()
        sample = self.kernel.sample(self.bundle_fd, self.target)
        self._shape(sample, self.bound)
        _require(list(sample.namespace) == self.binding["namespace"] and sample.parent_private
                 and sample.nested == 0, "Changed namespace, propagation or nested mounts")
        if sample.mount is None:
            _require(list(sample.visible) == self.binding["original"] and sample.entries == sample.attributes == sample.aliases == 0,
                     "Original empty staging directory is not restored")
        else:
            mount = sample.mount
            _require(isinstance(mount, Mount) and mount.target == str(self.target) and mount.root == "/"
                     and mount.kind == "tmpfs" and mount.source == self.binding["marker"] and mount.optional == ()
                     and mount.mount_id > 0 and mount.device == Device.number(sample.visible[0])
                     and {"rw", "nodev", "nosuid"}.issubset(mount.options) and "ro" not in mount.options
                     and sample.aliases == 1, "Foreign, unsafe or aliased staging mount")
            _require(stat.S_ISDIR(sample.visible[2]) and stat.S_IMODE(sample.visible[2]) == 0o1777
                     and sample.visible[3:] == (0, 0) and sample.capacity == self.binding["capacity"]
                     and sample.inodes == self.binding["inodes"], "Tmpfs capacity, inode limit or permissions differ")
        _require(0 <= time.monotonic() - start <= 10, "Staging observation took too long")
        self._identity()
        return sample

    def attach(self, journal: Journal) -> None:
        _require(journal.plan.operation == self.operation and journal.plan.context == self.bound
                 and journal.plan.steps == (self.step,), "Exact one-step staging journal required")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        _require(step == self.step and operation == self.operation, "Foreign tmpfs operation")
        sample = self._sample()
        active = sample.mount is not None
        if active:
            _require(sample.entries == sample.attributes == sample.used_blocks == 0,
                     "Staging is not empty; contents retained and readiness refused")
        owned = False
        if self.journal is not None:
            state = self.journal.state()
            owned = state.applied == 1 or state.pending == ("apply", 0)
        return Observation(step.after_sha256 if active else step.before_sha256, True, active and owned)

    def _effect(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        _require(self.journal is not None and step == self.step and operation == self.operation, "Attached staging journal required")
        assert self.journal is not None
        _require(self.journal.state().pending == ("undo" if undo else "apply", 0), "Exact durable intent required")
        first, second = self._sample(), self._sample()
        _require((first.mount is not None) == undo and first.mount == second.mount and first.visible == second.visible,
                 "Staging mount already changed; do not replay")
        _require(first.entries == second.entries == first.attributes == second.attributes == 0,
                 "Nonempty tmpfs is retained; no implicit data deletion")
        if undo:
            _require(first.used_blocks == second.used_blocks == 0, "Tmpfs still owns data blocks")
        else:
            _require(min(first.available, second.available) >= self.binding["capacity"] + self.binding["reserve"],
                     "Insufficient current memory reserve")
        self.context()
        if undo:
            self.kernel.remove(self.bundle_fd)
        else:
            self.kernel.create(self.bundle_fd, operation, self.binding["capacity"], self.binding["inodes"])
        self.context()
        _require((self._sample().mount is None) == undo, "Native return did not establish the expected mount state")

    def apply(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=True)

    def close(self) -> None:
        for name in ("bundle_fd", "lock_fd", "parent_fd"):
            fd = getattr(self, name)
            if fd >= 0:
                os.close(fd)
                setattr(self, name, -1)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
