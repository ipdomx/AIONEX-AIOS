"""C5E9 metadata preparation and journal-bound encrypted swap activation.

Only an already finalized C5E8 mapper with retained parent journals is accepted.
A create-only header intent precedes a single bounded header write; incomplete
preparation is not replayed. Explicit reconciliation can flush and certify an
already exact header, never rewrite it. The activation baseline is that prepared
header, inactive; undo disables swap without formatting or erasing its parent.
There is no production CLI, host-context reader, boot unit or full-plan executor.
Native syscalls belong in an isolated VM, not a container sharing host swap.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import stat
import struct
import sys
import time
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
from scripts.security.fr06c5_memory_kernel_observation import Device, parse_swaps
from scripts.security.fr06c5_memory_legacy_swap import memory_available
from scripts.security.fr06c5_memory_mapper import MapperAdapter, MapperInfo, mapper_name
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

STEP = "activate_encrypted_swap"
PAGE = 4096
MAX_TEXT = 1024 * 1024
BLKGETSIZE64 = 0x80081272


class EncryptedSwapRejected(TransitionRejected):
    """Incomplete ownership, preparation, consumer or memory proof."""


def _require(value: bool, reason: str) -> None:
    if not value:
        raise EncryptedSwapRejected(reason)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _require(key not in result, "Repeated binding field")
        result[key] = value
    return result


def header_bytes(operation: str, capacity: int) -> bytes:
    """Linux swap_header v1, LE 4KiB profile, no bad pages, operation UUID.

    Matches include/linux/swap.h: bootbits[1024], version, last_page,
    nr_badpages, sws_uuid[16], sws_volume[16], padding; trailing SWAPSPACE2.
    The supported profile is tested by the actual guest kernel, not by a mock.
    """
    _require(isinstance(operation, str) and str(UUID(operation)) == operation, "Canonical operation required")
    _require(type(capacity) is int and 16 * 1024 <= capacity <= 64 * 1024**3
             and capacity % PAGE == 0 and sys.byteorder == "little", "Unsupported swap geometry")
    data = bytearray(PAGE)
    struct.pack_into("<III", data, 1024, 1, capacity // PAGE - 1, 0)
    data[1036:1052] = UUID(operation).bytes
    data[1052:1068] = b"AIONEX-C5E9".ljust(16, b"\0")
    data[-10:] = b"SWAPSPACE2"
    return bytes(data)


def _text(path: str) -> str:
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_TEXT + 1)
    _require(len(data) <= MAX_TEXT and data.endswith(b"\n") and b"\0" not in data, "Incomplete kernel metadata")
    return data.decode("utf-8", errors="strict")


@dataclass(frozen=True)
class SwapRuntime:
    boot_id: str
    namespace: tuple[int, int]
    init_namespace: tuple[int, int]
    active: bool
    size: int
    used: int
    priority: int
    available: int
    capacity: int
    page_size: int


class Kernel(Protocol):
    def open(self, operation: str) -> int: ...
    def node(self, fd: int, operation: str) -> dict[str, int]: ...
    def read_header(self, fd: int) -> bytes: ...
    def write_header(self, fd: int, content: bytes) -> None: ...
    def sync(self, fd: int) -> None: ...
    def sample(self, fd: int, operation: str) -> SwapRuntime: ...
    def activate(self, fd: int, priority: int) -> None: ...
    def deactivate(self, fd: int) -> None: ...


class LinuxEncryptedSwapKernel:
    """Descriptor-bound metadata I/O and libc swapon/swapoff; no shell or -a."""
    def open(self, operation: str) -> int:
        fd = os.open("/dev/mapper/" + mapper_name(operation), os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            self.node(fd, operation)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def node(self, fd: int, operation: str) -> dict[str, int]:
        value = os.fstat(fd)
        named = os.stat("/dev/mapper/" + mapper_name(operation))
        keys = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_rdev")
        _require(stat.S_ISBLK(value.st_mode) and value.st_uid == 0
                 and all(getattr(value, k) == getattr(named, k) for k in keys), "Mapper descriptor or node changed")
        return {k: int(getattr(value, k)) for k in keys}

    def read_header(self, fd: int) -> bytes:
        data = os.pread(fd, PAGE, 0)
        _require(len(data) == PAGE, "Complete header page unavailable")
        return data

    def write_header(self, fd: int, content: bytes) -> None:
        _require(os.geteuid() == 0 and stat.S_ISBLK(os.fstat(fd).st_mode)
                 and len(content) == PAGE, "Native bounded block header write required")
        # A short/failed write stays uncertain. Never retry a partial formatter.
        _require(os.pwrite(fd, content, 0) == PAGE, "Incomplete header write; no retry")

    def sync(self, fd: int) -> None:
        os.fsync(fd)

    def sample(self, fd: int, operation: str) -> SwapRuntime:
        node = self.node(fd, operation)
        rows = parse_swaps(_text("/proc/swaps"))
        _require(len(rows) <= 1, "Additional swap resources present")
        if rows:
            _require(rows[0].kind == "partition", "Plain file swap or unrecognized consumer present")
            other = os.stat(rows[0].path)
            _require(stat.S_ISBLK(other.st_mode) and other.st_rdev == node["st_rdev"], "Active swap belongs to another device")
        size = bytearray(8)
        fcntl.ioctl(fd, BLKGETSIZE64, size, True)
        own, init = os.stat("/proc/self/ns/mnt"), os.stat("/proc/1/ns/mnt")
        result = SwapRuntime(_text("/proc/sys/kernel/random/boot_id").strip(),
                             (own.st_dev, own.st_ino), (init.st_dev, init.st_ino), bool(rows),
                             rows[0].size if rows else 0, rows[0].used if rows else 0,
                             rows[0].priority if rows else 0, memory_available(_text("/proc/meminfo")),
                             struct.unpack("=Q", size)[0], os.sysconf("SC_PAGE_SIZE"))
        _require(self.node(fd, operation) == node, "Mapper node changed while reading")
        return result

    @staticmethod
    def _call(fd: int, priority: int | None) -> None:
        _require(os.geteuid() == 0 and stat.S_ISBLK(os.fstat(fd).st_mode), "Native swap effects require a block descriptor and root")
        lib = ctypes.CDLL(None, use_errno=True)
        name = f"/proc/self/fd/{fd}".encode("ascii")
        function = lib.swapon if priority is not None else lib.swapoff
        function.argtypes = [ctypes.c_char_p, ctypes.c_int] if priority is not None else [ctypes.c_char_p]
        function.restype = ctypes.c_int
        if priority is not None:
            _require(type(priority) is int and 0 <= priority <= 32767, "Explicit swap priority required")
            code = function(name, 0x8000 | priority)
        else:
            code = function(name)
        if code != 0:
            raise OSError(ctypes.get_errno(), "Descriptor-bound encrypted swap operation failed")

    def activate(self, fd: int, priority: int) -> None:
        self._call(fd, priority)

    def deactivate(self, fd: int) -> None:
        self._call(fd, None)


class EncryptedSwapAdapter:
    """One activation journal over an explicitly prepared encrypted volume.

    Header preparation is irreversible initialization of a newly owned volatile
    mapper; it is NOT baseline restoration. Its bytes are never restored or
    formatted twice. Discard requires explicit removal of the inactive mapper
    under its parent journal. Activation undo retains the prepared header.
    """
    def __init__(self, mapper: MapperAdapter, parent: Path, kernel: Kernel | None = None):
        self.mapper, self.parent = mapper, parent
        self.kernel = kernel or LinuxEncryptedSwapKernel()
        self.operation, self.bound = mapper.operation, mapper.context()
        self.parent_fd = self.bundle_fd = self.lock_fd = self.fd = -1
        self.journal: Journal | None = None
        try:
            info = self._mapper_owned()
            self.parent_fd = _open_dir(parent)
            self.parent_identity = _dir_identity(self.parent_fd, private=True)
            self.lock_fd = os.open(".encrypted-swap.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                   0o600, dir_fd=self.parent_fd)
            self._lock_ok(os.fstat(self.lock_fd))
            self.lock_identity = (os.fstat(self.lock_fd).st_dev, os.fstat(self.lock_fd).st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.parent_fd)
            self.fd = self.kernel.open(self.operation)
            self.node_identity = self.kernel.node(self.fd, self.operation)
            _require(Device.number(self.node_identity["st_rdev"]) == info.device, "Opened mapper is not the owned graph")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _lock_ok(value: os.stat_result) -> None:
        _require(stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid()
                 and stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1 and not value.st_size,
                 "Unsafe encrypted-swap lock")

    def _mapper_owned(self) -> MapperInfo:
        mapper = self.mapper
        _require(mapper.context() == self.bound and mapper.journal is not None, "Accepted parent mapper required")
        assert mapper.journal is not None
        _require(mapper.journal.state().phase == "applied", "Parent mapper is not finalized")
        proof = mapper.observe(mapper.step, self.operation)
        _require(proof.identity_verified and proof.owned_by_operation and proof.fingerprint == mapper.step.after_sha256,
                 "Parent mapper ownership not proven")
        info = mapper._sample().mapper
        _require(info is not None, "Owned mapper is absent")
        assert info is not None
        return info

    @classmethod
    def prepare(cls, mapper: MapperAdapter, parent: Path, *, priority: int, reserve: int,
                kernel: Kernel | None = None) -> Self:
        _require(type(priority) is int and 0 <= priority <= 32767 and type(reserve) is int and reserve >= PAGE,
                 "Explicit bounded priority and memory reserve required")
        adapter = cls(mapper, parent, kernel)
        try:
            sample = adapter.kernel.sample(adapter.fd, adapter.operation)
            info = adapter._mapper_owned()
            _require(not sample.active and not info.holders and info.mounts == info.swaps == 0,
                     "Preparation requires an inactive unused mapper")
            capacity = mapper.binding["capacity"]
            expected = header_bytes(adapter.operation, capacity)
            os.mkdir(adapter.operation, mode=0o700, dir_fd=adapter.parent_fd)
            os.fsync(adapter.parent_fd)
            adapter.bundle_fd = os.open(adapter.operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.parent_fd)
            assert mapper.journal is not None
            body = {"schema": 1, "operation": adapter.operation, "context": asdict(adapter.bound),
                    "parent": adapter.parent_identity, "bundle": _dir_identity(adapter.bundle_fd, private=True),
                    "lock": list(adapter.lock_identity), "node": adapter.node_identity,
                    "mapper_binding": mapper.binding_hash, "mapper_plan": _digest(asdict(mapper.journal.plan)),
                    "capacity": capacity, "priority": priority, "reserve": reserve,
                    "namespace": list(sample.namespace), "header_sha256": hashlib.sha256(expected).hexdigest()}
            _write_new(adapter.bundle_fd, "binding.json", json.dumps(body, sort_keys=True).encode() + b"\n", 0o600)
            adapter._load()
            verified = adapter._runtime()
            _require(not verified.active and verified.available >= reserve, "Baseline or available reserve changed during preparation")
            return adapter
        except BaseException:
            adapter.close()
            raise

    @classmethod
    def load(cls, mapper: MapperAdapter, parent: Path, *, kernel: Kernel | None = None) -> Self:
        adapter = cls(mapper, parent, kernel)
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
        assert self.mapper.journal is not None
        _require(isinstance(body, dict) and set(body) == {"schema", "operation", "context", "parent", "bundle", "lock", "node",
                 "mapper_binding", "mapper_plan", "capacity", "priority", "reserve", "namespace", "header_sha256"}, "Invalid swap binding fields")
        _require(type(body["schema"]) is int and body["schema"] == 1 and body["operation"] == self.operation
                 and BoundContext(**body["context"]) == self.bound and body["parent"] == self.parent_identity
                 and body["bundle"] == _dir_identity(self.bundle_fd, private=True) and body["lock"] == list(self.lock_identity)
                 and body["node"] == self.node_identity and body["mapper_binding"] == self.mapper.binding_hash
                 and body["mapper_plan"] == _digest(asdict(self.mapper.journal.plan))
                 and type(body["capacity"]) is int and body["capacity"] == self.mapper.binding["capacity"]
                 and type(body["priority"]) is int and 0 <= body["priority"] <= 32767
                 and type(body["reserve"]) is int and body["reserve"] >= PAGE
                 and isinstance(body["namespace"], list) and len(body["namespace"]) == 2
                 and all(type(x) is int and x > 0 for x in body["namespace"])
                 and body["namespace"] == self.mapper.binding["namespace"], "Swap binding not owned by this operation")
        self.header = header_bytes(self.operation, body["capacity"])
        _require(body["header_sha256"] == hashlib.sha256(self.header).hexdigest(), "Unexpected header digest")
        self.binding, self.binding_hash = body, hashlib.sha256(raw).hexdigest()
        self.step = BoundStep(STEP, _digest({"binding": self.binding_hash, "active": False}),
                             _digest({"binding": self.binding_hash, "active": True}))
        self._identity()

    def _identity(self) -> None:
        _require(min(self.parent_fd, self.bundle_fd, self.fd, self.lock_fd) >= 0, "Closed swap adapter")
        self._mapper_owned()
        fd = _open_dir(self.parent)
        try:
            _require(_dir_identity(fd, private=True) == self.parent_identity, "Swap state parent changed")
        finally:
            os.close(fd)
        lock = os.stat(".encrypted-swap.lock", dir_fd=self.parent_fd, follow_symlinks=False)
        self._lock_ok(lock)
        _require((lock.st_dev, lock.st_ino) == self.lock_identity, "Swap lock replaced")
        bundle = os.stat(self.operation, dir_fd=self.parent_fd, follow_symlinks=False)
        _require(stat.S_ISDIR(bundle.st_mode) and (bundle.st_dev, bundle.st_ino) ==
                 (self.binding["bundle"]["device"], self.binding["bundle"]["inode"])
                 and _dir_identity(self.bundle_fd, private=True) == self.binding["bundle"], "Swap operation bundle replaced")
        identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        _require(identity == self.binding_identity and hashlib.sha256(raw).hexdigest() == self.binding_hash,
                 "Swap binding changed")
        _require(set(os.listdir(self.bundle_fd)).issubset({"binding.json", "header-intent.json", "header-ready.json"}),
                 "Unexpected swap preparation records")
        _require(self.kernel.node(self.fd, self.operation) == self.node_identity, "Pinned block descriptor changed")

    def context(self) -> BoundContext:
        self._identity()
        return self.bound

    def _runtime(self) -> SwapRuntime:
        self._identity()
        start = time.monotonic()
        sample = self.kernel.sample(self.fd, self.operation)
        info = self._mapper_owned()
        _require(isinstance(sample, SwapRuntime) and sample.boot_id == self.bound.boot_id
                 and isinstance(sample.namespace, tuple) and len(sample.namespace) == 2
                 and all(type(x) is int and x > 0 for x in sample.namespace)
                 and sample.namespace == sample.init_namespace and list(sample.namespace) == self.binding["namespace"]
                 and type(sample.active) is bool and type(sample.page_size) is int and sample.page_size == PAGE
                 and type(sample.capacity) is int and sample.capacity == self.binding["capacity"]
                 and all(type(x) is int and x >= 0 for x in (sample.used, sample.size, sample.available))
                 and type(sample.priority) is int and sample.used <= sample.size,
                 "Invalid swap boot, namespace, geometry or sample")
        _require(not info.holders and info.mounts == 0 and info.swaps == int(sample.active), "Mapper has an unrelated consumer")
        if sample.active:
            _require(sample.size == sample.capacity - PAGE and sample.priority == self.binding["priority"], "Active swap size or priority differs")
        else:
            _require((sample.used, sample.size, sample.priority) == (0, 0, 0), "Inactive swap has contradictory counters")
        _require(0 <= time.monotonic() - start <= 20, "Swap sample exceeded its window")
        self._identity()
        return sample

    def _header_event(self, ready: bool) -> dict[str, Any]:
        return {"schema": 1, "operation": self.operation, "binding_sha256": self.binding_hash,
                "header_sha256": self.binding["header_sha256"], "status": "synchronized" if ready else "initialization-intent"}

    def _check_header_record(self, ready: bool) -> None:
        _, raw = _file(self.bundle_fd, "header-ready.json" if ready else "header-intent.json", private=True)
        _require(bool(raw), "Header preparation evidence missing")
        value = json.loads(raw, object_pairs_hook=_unique)
        _require(isinstance(value, dict) and type(value.get("schema")) is int
                 and value == self._header_event(ready), "Header preparation evidence missing or changed")

    def initialize_header(self) -> None:
        """Initialize ONCE; create-only intent is durable before the block write."""
        self.context()
        _require(not self._runtime().active, "Never format active swap")
        _require(set(os.listdir(self.bundle_fd)) == {"binding.json"}, "Existing header intent must be reconciled, never repeated")
        _require(self.kernel.read_header(self.fd) != self.header, "Unproven pre-existing matching header is not adopted")
        _write_new(self.bundle_fd, "header-intent.json", json.dumps(self._header_event(False), sort_keys=True).encode() + b"\n", 0o600)
        self.context()
        _require(not self._runtime().active, "Swap became active before initialization")
        self.kernel.write_header(self.fd, self.header)
        self._certify_header()

    def _certify_header(self) -> None:
        self.context()
        self._check_header_record(False)
        _require(not self._runtime().active and self.kernel.read_header(self.fd) == self.header, "Header incomplete or volume in use; do not rewrite")
        self.kernel.sync(self.fd)
        self.context()
        _require(not self._runtime().active and self.kernel.read_header(self.fd) == self.header, "Header changed during synchronization")
        _write_new(self.bundle_fd, "header-ready.json", json.dumps(self._header_event(True), sort_keys=True).encode() + b"\n", 0o600)

    def reconcile_header(self) -> None:
        """Explicit sync/certification of exact existing bytes; no block rewrite."""
        self._identity()
        _require(set(os.listdir(self.bundle_fd)) == {"binding.json", "header-intent.json"}, "No unique unsealed header intent")
        self._certify_header()

    def _prepared(self) -> None:
        self.context()
        self._check_header_record(False)
        self._check_header_record(True)
        _require(self.kernel.read_header(self.fd) == self.header, "Prepared swap header changed")

    def attach(self, journal: Journal) -> None:
        _require(journal.plan.operation == self.operation and journal.plan.context == self.bound
                 and journal.plan.steps == (self.step,), "Exact single encrypted-swap journal required")
        self._prepared()
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        _require(step == self.step and operation == self.operation, "Foreign swap operation")
        self._prepared()
        active = self._runtime().active
        owned = False
        if self.journal is not None:
            state = self.journal.state()
            owned = state.applied == 1 or state.pending == ("apply", 0)
        return Observation(step.after_sha256 if active else step.before_sha256, True, active and owned)

    def _effect(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        _require(self.journal is not None and step == self.step and operation == self.operation, "Attached exact journal required")
        assert self.journal is not None
        _require(self.journal.state().pending == ("undo" if undo else "apply", 0), "Durable swap intent required")
        self._prepared()
        first, second = self._runtime(), self._runtime()
        _require(first.active == second.active == undo, "Swap already transitioned; do not replay")
        if undo:
            _require(min(first.available - first.used, second.available - second.used) >= self.binding["reserve"],
                     "Insufficient current memory reserve for swapoff")
        else:
            _require(min(first.available, second.available) >= self.binding["reserve"], "Current activation reserve unavailable")
        self.context()
        if undo:
            self.kernel.deactivate(self.fd)
        else:
            self.kernel.activate(self.fd, self.binding["priority"])
        self._prepared()
        _require(self._runtime().active != undo, "Native return did not establish swap postcondition")

    def apply(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=True)

    def close(self) -> None:
        for attr in ("fd", "bundle_fd", "lock_fd", "parent_fd"):
            value = getattr(self, attr)
            if value >= 0:
                os.close(value)
                setattr(self, attr, -1)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
