"""C5E7 one journal-bound loop attachment with atomic creation provenance.

Only LOOP_CONFIGURE/LOOP_CLR_FD mutate the kernel. No fallback to SET_FD then
SET_STATUS, no guessed/adopted loop, mapper/key/swap/mount command or activation
CLI. An existing unused loop node is explicitly selected, never created here.
The backing must remain published under its accepted C5E6 journal and lock.
An operation marker is installed atomically with backing identity and geometry;
reopening after process loss checks that marker, not just a matching filename.

Markers and advisory locks are not protection from a privileged administrator.
Independently attested frozen writers and closed authority remain mandatory.
Tests using the native kernel effects belong in a separate VM, not a container.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import stat
import struct
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import UUID

from scripts.security.fr06c5_memory_backing import (
    BackingAdapter,
    LinuxConsumers,
    _metadata,
    same_allocation,
)
from scripts.security.fr06c5_memory_config_files import (
    _dir_identity,
    _file,
    _open_dir,
    _write_new,
)
from scripts.security.fr06c5_memory_kernel_observation import (
    LOOP_STRUCT,
    Device,
    parse_mountinfo,
    parse_swaps,
)
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

STEP = "attach_swap_loop"
LOOP_CONFIGURE = 0x4C0A
LOOP_CLR_FD = 0x4C01
LOOP_GET_STATUS64 = 0x4C05
MAX_LOOPS = 1024
MAX_TEXT = 1024 * 1024


class LoopRejected(TransitionRejected):
    """No mutation without complete backing, loop, intent and consumer proof."""


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise LoopRejected(message)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate loop binding field")
        result[key] = value
    return result


def _text(path: str) -> str:
    with Path(path).open("rb") as stream:
        value = stream.read(MAX_TEXT + 1)
    _require(len(value) <= MAX_TEXT and value.endswith(b"\n") and b"\0" not in value, "Incomplete kernel text")
    return value.decode("utf-8", errors="strict")


def _number(number: int) -> None:
    _require(type(number) is int and 0 <= number < MAX_LOOPS, "Explicit bounded loop number required")


@dataclass(frozen=True)
class LoopInfo:
    backing_device: int
    backing_inode: int
    number: int
    offset: int
    size_limit: int
    flags: int
    marker: str


def read_info(fd: int) -> LoopInfo | None:
    """Only ENXIO means unbound. No filename hints or key buffers are exported."""
    data = bytearray(LOOP_STRUCT.size)
    try:
        try:
            fcntl.ioctl(fd, LOOP_GET_STATUS64, data, True)
        except OSError as exc:
            if exc.errno == errno.ENXIO:
                return None
            raise
        fields = LOOP_STRUCT.unpack(data)
        _require(fields[2] == fields[6] == fields[7] == 0, "Unsupported loop resource or legacy encryption")
        marker, separator, remainder = fields[9].partition(b"\0")
        _require(bool(separator) and not remainder.strip(b"\0"), "Ambiguous loop marker")
        return LoopInfo(fields[0], fields[1], fields[5], fields[3], fields[4], fields[8], marker.decode("ascii", errors="strict"))
    finally:
        data[:] = b"\0" * len(data)


@dataclass(frozen=True)
class Runtime:
    boot_id: str
    namespace: tuple[int, int]
    init_namespace: tuple[int, int]
    info: LoopInfo | None
    sectors: int
    readonly: int
    block_size: int
    holders: tuple[str, ...]
    mounts: int
    swaps: int
    backing_consumers: tuple[str, ...]


class Kernel(Protocol):
    def open(self, number: int) -> int: ...
    def node(self, fd: int, number: int) -> dict[str, int]: ...
    def sample(self, fd: int, number: int, backing_fd: int) -> Runtime: ...
    def configure(self, fd: int, backing_fd: int, number: int, capacity: int, marker: str) -> None: ...
    def detach(self, fd: int) -> None: ...


class LinuxLoopKernel:
    """Descriptor-bound UAPI calls, never a shell, automatic allocation or retry."""
    def open(self, number: int) -> int:
        _number(number)
        fd = os.open(f"/dev/loop{number}", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            self.node(fd, number)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def node(self, fd: int, number: int) -> dict[str, int]:
        _number(number)
        info = os.fstat(fd)
        named = os.stat(f"/dev/loop{number}", follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_rdev")
        _require(stat.S_ISBLK(info.st_mode) and info.st_uid == 0
                 and Device.number(info.st_rdev) == Device(7, number)
                 and all(getattr(info, k) == getattr(named, k) for k in fields), "Loop node identity changed")
        return {k: int(getattr(info, k)) for k in fields}

    def sample(self, fd: int, number: int, backing_fd: int) -> Runtime:
        pinned = self.node(fd, number)
        info = read_info(fd)
        root = f"/sys/dev/block/7:{number}"
        _require(Device.parse(_text(root + "/dev").strip()) == Device(7, number), "Loop sysfs identity differs")
        def quantity(relative: str) -> int:
            value = _text(root + "/" + relative).strip()
            _require(value.isdecimal(), "Invalid loop sysfs quantity")
            return int(value)
        holders = tuple(sorted(Device.parse(_text(root + "/holders/" + p.name + "/dev").strip()).label()
                               for p in Path(root + "/holders").iterdir()))
        _require(len(holders) <= 64, "Unexpected loop consumer count")
        own, init = os.stat("/proc/self/ns/mnt"), os.stat("/proc/1/ns/mnt")
        mounts = parse_mountinfo(_text("/proc/self/mountinfo"))
        swaps = parse_swaps(_text("/proc/swaps"))
        count = 0
        for swap in swaps:
            if swap.kind != "partition":
                continue
            device = os.stat(swap.path)
            _require(stat.S_ISBLK(device.st_mode), "Block swap identity unavailable")
            count += int(Device.number(device.st_rdev) == Device(7, number))
        result = Runtime(_text("/proc/sys/kernel/random/boot_id").strip(),
                         (own.st_dev, own.st_ino), (init.st_dev, init.st_ino), info,
                         quantity("size"), quantity("ro"), quantity("queue/logical_block_size"),
                         holders, sum(m.device == Device(7, number) for m in mounts), count,
                         LinuxConsumers().consumers(backing_fd))
        _require(self.node(fd, number) == pinned and read_info(fd) == info, "Loop changed during observation")
        return result

    def configure(self, fd: int, backing_fd: int, number: int, capacity: int, marker: str) -> None:
        _require(os.geteuid() == 0, "Native loop changes require root in the attested kernel")
        self.node(fd, number)
        _metadata(backing_fd, capacity)
        _require(read_info(fd) is None, "Selected loop no longer unbound")
        encoded = marker.encode("ascii")
        _require(0 < len(encoded) < 64 and b"\0" not in encoded, "Bounded marker required")
        info = LOOP_STRUCT.pack(0, 0, 0, 0, capacity, number, 0, 0, 0,
                                encoded.ljust(64, b"\0"), b"\0" * 64, b"\0" * 32, 0, 0)
        config = struct.pack("=II", backing_fd, 512) + info + b"\0" * 64
        _require(len(config) == 304, "Loop UAPI size differs")
        fcntl.ioctl(fd, LOOP_CONFIGURE, config)

    def detach(self, fd: int) -> None:
        _require(os.geteuid() == 0, "Native loop changes require root in the attested kernel")
        fcntl.ioctl(fd, LOOP_CLR_FD, 0)


class LoopAdapter:
    """An explicit single-loop journal linked to the accepted backing journal.

    An uncertain ioctl never authorizes a replay. A pending undo which turns
    into deferred autoclear is rejected, not called complete. Backing locks and
    proof remain held, and the backing inode is never removed by this adapter.
    """
    def __init__(self, backing: BackingAdapter, parent: Path, *, number: int,
                 kernel: Kernel | None = None):
        _number(number)
        self.backing, self.parent, self.number = backing, parent, number
        self.kernel = kernel or LinuxLoopKernel()
        self.operation = backing.operation
        _require(str(UUID(self.operation)) == self.operation, "Canonical operation required")
        self.parent_fd = self.bundle_fd = self.lock_fd = self.fd = self.backing_fd = -1
        self.journal: Journal | None = None
        try:
            self.bound = backing.context()
            self._backing_owned()
            self.parent_fd = _open_dir(parent)
            self.parent_identity = _dir_identity(self.parent_fd, private=True)
            self.backing_fd = os.open(backing.target.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                      dir_fd=backing.parent_fd)
            _require(same_allocation(_metadata(self.backing_fd, backing.spec["capacity"]), backing.spec["file"]), "Writable backing descriptor differs")
            self.lock_fd = os.open(".loop-owner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                   0o600, dir_fd=self.parent_fd)
            lock = os.fstat(self.lock_fd)
            self._valid_lock(lock)
            self.lock_identity = (lock.st_dev, lock.st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.parent_fd)
            self.fd = self.kernel.open(number)
            self.node_identity = self.kernel.node(self.fd, number)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _valid_lock(lock: os.stat_result) -> None:
        _require(stat.S_ISREG(lock.st_mode) and lock.st_uid == os.geteuid()
                 and stat.S_IMODE(lock.st_mode) == 0o600 and lock.st_nlink == 1 and not lock.st_size, "Unsafe loop operation lock")

    def _backing_owned(self) -> None:
        backing = self.backing
        _require(backing.context() == self.bound and backing.journal is not None, "Accepted backing authority required")
        assert backing.journal is not None
        _require(backing.journal.state().phase == "applied", "Backing journal not finalized")
        proof = backing.observe(backing.step, self.operation)
        _require(proof.identity_verified and proof.owned_by_operation and proof.fingerprint == backing.step.after_sha256,
                 "Published backing ownership not proved")

    @classmethod
    def prepare(cls, backing: BackingAdapter, parent: Path, *, number: int,
                kernel: Kernel | None = None) -> Self:
        adapter = cls(backing, parent, number=number, kernel=kernel)
        try:
            sample = adapter.kernel.sample(adapter.fd, number, adapter.backing_fd)
            adapter._runtime_shape(sample)
            _require(sample.info is None and sample.sectors == 0 and not sample.holders
                     and sample.mounts == sample.swaps == 0 and sample.backing_consumers == (), "Loop or backing already used")
            os.mkdir(adapter.operation, mode=0o700, dir_fd=adapter.parent_fd)
            os.fsync(adapter.parent_fd)
            adapter.bundle_fd = os.open(adapter.operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.parent_fd)
            assert backing.journal is not None
            body = {"schema": 1, "operation": adapter.operation, "context": asdict(adapter.bound),
                    "parent": adapter.parent_identity, "bundle": _dir_identity(adapter.bundle_fd, private=True),
                    "lock": list(adapter.lock_identity), "loop_number": number, "node": adapter.node_identity,
                    "namespace": list(sample.namespace), "marker": "AIONEX-C5E7:" + adapter.operation,
                    "backing_manifest": backing.manifest_hash, "backing_plan": _digest(asdict(backing.journal.plan)),
                    "backing_file": backing.spec["file"], "capacity": backing.spec["capacity"]}
            _write_new(adapter.bundle_fd, "binding.json", json.dumps(body, sort_keys=True).encode()+b"\n", 0o600)
            adapter._load()
            _require(adapter._sample().info is None, "Baseline changed during preparation")
            return adapter
        except BaseException:
            adapter.close()
            raise

    @classmethod
    def load(cls, backing: BackingAdapter, parent: Path, *, number: int,
             kernel: Kernel | None = None) -> Self:
        adapter = cls(backing, parent, number=number, kernel=kernel)
        try:
            adapter.bundle_fd = os.open(adapter.operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
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
        assert self.backing.journal is not None
        _require(isinstance(body, dict) and set(body) == {"schema", "operation", "context", "parent", "bundle", "lock", "loop_number", "node", "namespace", "marker", "backing_manifest", "backing_plan", "backing_file", "capacity"}, "Invalid loop binding schema")
        _require(type(body["schema"]) is int and body["schema"] == 1 and body["operation"] == self.operation
                 and BoundContext(**body["context"]) == self.bound and body["parent"] == self.parent_identity
                 and body["bundle"] == _dir_identity(self.bundle_fd, private=True) and body["lock"] == list(self.lock_identity)
                 and type(body["loop_number"]) is int and body["loop_number"] == self.number and body["node"] == self.node_identity
                 and body["marker"] == "AIONEX-C5E7:" + self.operation
                 and body["backing_manifest"] == self.backing.manifest_hash
                 and body["backing_plan"] == _digest(asdict(self.backing.journal.plan))
                 and body["backing_file"] == self.backing.spec["file"] and body["capacity"] == self.backing.spec["capacity"]
                 and isinstance(body["namespace"], list) and len(body["namespace"]) == 2
                 and all(type(x) is int and x > 0 for x in body["namespace"]), "Loop binding is not the exact owned operation")
        self.binding, self.binding_hash = body, hashlib.sha256(raw).hexdigest()
        self.step = BoundStep(STEP, _digest({"binding": self.binding_hash, "bound": False}),
                             _digest({"binding": self.binding_hash, "bound": True}))
        self._identity()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        for attr in ("fd", "backing_fd", "bundle_fd", "lock_fd", "parent_fd"):
            fd = getattr(self, attr)
            if fd >= 0:
                os.close(fd)
                setattr(self, attr, -1)

    def _identity(self) -> None:
        _require(min(self.fd, self.backing_fd, self.bundle_fd, self.lock_fd) >= 0, "Closed loop adapter")
        self._backing_owned()
        reopened = _open_dir(self.parent)
        try:
            _require(_dir_identity(reopened, private=True) == self.parent_identity
                     and _dir_identity(self.parent_fd, private=True) == self.parent_identity, "Loop evidence parent changed")
        finally:
            os.close(reopened)
        lock = os.stat(".loop-owner.lock", dir_fd=self.parent_fd, follow_symlinks=False)
        self._valid_lock(lock)
        _require((lock.st_dev, lock.st_ino) == self.lock_identity, "Loop lock changed")
        bundle = os.stat(self.operation, dir_fd=self.parent_fd, follow_symlinks=False)
        _require(stat.S_ISDIR(bundle.st_mode) and (bundle.st_dev, bundle.st_ino) ==
                 (self.binding["bundle"]["device"], self.binding["bundle"]["inode"])
                 and _dir_identity(self.bundle_fd, private=True) == self.binding["bundle"], "Loop evidence bundle changed")
        identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        _require(identity == self.binding_identity and hashlib.sha256(raw).hexdigest() == self.binding_hash
                 and os.listdir(self.bundle_fd) == ["binding.json"], "Loop binding changed or incomplete")
        _require(self.kernel.node(self.fd, self.number) == self.node_identity
                 and same_allocation(_metadata(self.backing_fd, self.binding["capacity"]), self.binding["backing_file"]), "Loop or backing descriptor changed")

    def _runtime_shape(self, sample: Runtime) -> None:
        _require(isinstance(sample, Runtime) and sample.boot_id == self.bound.boot_id
                 and isinstance(sample.namespace, tuple) and len(sample.namespace) == 2
                 and all(type(x) is int and x > 0 for x in sample.namespace)
                 and sample.namespace == sample.init_namespace
                 and (sample.info is None or isinstance(sample.info, LoopInfo))
                 and all(type(x) is int and x >= 0 for x in (sample.sectors, sample.readonly, sample.block_size, sample.mounts, sample.swaps))
                 and sample.readonly == 0 and sample.block_size == 512
                 and isinstance(sample.holders, tuple) and isinstance(sample.backing_consumers, tuple), "Kernel/boot/namespace evidence invalid")

    def _sample(self) -> Runtime:
        self._identity()
        started = time.monotonic()
        result = self.kernel.sample(self.fd, self.number, self.backing_fd)
        self._runtime_shape(result)
        _require(list(result.namespace) == self.binding["namespace"], "Bound namespace changed")
        if result.info is None:
            _require(result.sectors == result.mounts == result.swaps == 0 and not result.holders
                     and result.backing_consumers == (), "Unbound loop baseline still has consumers")
        else:
            f = self.binding["backing_file"]
            expected = LoopInfo(f["st_dev"], f["st_ino"], self.number, 0, self.binding["capacity"], 0, self.binding["marker"])
            _require(result.info == expected and result.sectors * 512 == self.binding["capacity"]
                     and result.backing_consumers == (f"loop{self.number}",), "Foreign, partial, extra or deferred loop binding")
        _require(0 <= time.monotonic()-started <= 10, "Loop sampling window exceeded")
        self._identity()
        return result

    def context(self) -> BoundContext:
        self._identity()
        return self.bound

    def attach(self, journal: Journal) -> None:
        _require(journal.plan.operation == self.operation and journal.plan.context == self.bound
                 and journal.plan.steps == (self.step,), "Exact single-loop journal required")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        _require(step == self.step and operation == self.operation, "Foreign loop step")
        active = self._sample().info is not None
        owned = False
        if self.journal is not None:
            state = self.journal.state()
            owned = state.applied == 1 or state.pending == ("apply", 0)
        return Observation(step.after_sha256 if active else step.before_sha256, True, active and owned)

    def _effect(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        _require(self.journal is not None and step == self.step and operation == self.operation, "Attached loop journal required")
        assert self.journal is not None
        _require(self.journal.state().pending == ("undo" if undo else "apply", 0), "Durable direction-bound loop intent required")
        first, second = self._sample(), self._sample()
        _require(first == second and (first.info is not None) == undo, "Loop state changed or already transitioned")
        _require(first.holders == () and first.mounts == first.swaps == 0, "Loop still has dm, mount or swap consumers")
        self.context()
        if undo:
            self.kernel.detach(self.fd)
        else:
            self.kernel.configure(self.fd, self.backing_fd, self.number, self.binding["capacity"], self.binding["marker"])
        self.context()
        _require((self._sample().info is None) == undo, "Kernel return did not prove loop transition")

    def apply(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=True)
