"""C5E5 journal-bound removal/restoration of one pinned legacy swap file.

The native boundary calls Linux swapoff/swapon using the retained descriptor,
never a re-resolved caller path or a shell command. There is no activation CLI,
production-context reader, header formatter, mapper creation or host-wide -a.
A caller must supply independently verified closed/writer-frozen authority.
Tests invoking the real syscalls must run in a separate VM, not a container or
mount namespace: this module does not claim that namespaces isolate host swap.

The binding records metadata only, never reads swap payload or keys. It accepts
one regular, singly linked file, a 4KiB page profile and restorable priority.
An interrupted effect retains its journal intent; no implicit retry or rollback.
This adapter currently accepts a single-step journal. Composition with encrypted
replacement swap and boot recovery remains a separate acceptance requirement.
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
from scripts.security.fr06c5_memory_kernel_observation import parse_swaps
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

STEP = "disable_legacy_swap"
MAX_READ = 1024 * 1024


class SwapStepRejected(TransitionRejected):
    """Unknown context, identity, swap set or reserve prevents a kernel effect."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SwapStepRejected("Duplicate binding key")
        result[key] = value
    return result


def _read_text(path: str) -> str:
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_READ + 1)
    if len(data) > MAX_READ or not data.endswith(b"\n") or b"\0" in data:
        raise SwapStepRejected("Incomplete kernel evidence")
    return data.decode("utf-8", errors="strict")


def memory_available(value: str) -> int:
    rows = [line.split() for line in value.splitlines() if line.startswith("MemAvailable:")]
    if (len(rows) != 1 or len(rows[0]) != 3 or rows[0][2] != "kB"
            or not rows[0][1].isdigit()):
        raise SwapStepRejected("Available memory is not uniquely measurable")
    return int(rows[0][1]) * 1024


def file_identity(fd: int) -> dict[str, int]:
    s = os.fstat(fd)
    if (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.geteuid()
            or s.st_gid != os.getegid() or stat.S_IMODE(s.st_mode) != 0o600
            or s.st_size < 8192 or s.st_size % 4096 or os.listxattr(fd)):
        raise SwapStepRejected("Legacy swap file identity or permissions unsafe")
    return {k: int(getattr(s, k)) for k in ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                                         "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}


@dataclass(frozen=True)
class Runtime:
    boot_id: str
    namespace: tuple[int, int]
    init_namespace: tuple[int, int]
    active: bool
    size: int
    priority: int
    used: int
    available: int
    page_size: int


class Kernel(Protocol):
    def sample(self, fd: int, path: Path) -> Runtime: ...
    def disable(self, fd: int) -> None: ...
    def restore(self, fd: int, priority: int) -> None: ...


class LinuxSwapKernel:
    """The only two mutable calls are descriptor-bound libc swapoff/swapon."""
    def sample(self, fd: int, path: Path) -> Runtime:
        expected = file_identity(fd)
        rows = parse_swaps(_read_text("/proc/swaps"))
        if len(rows) > 1 or (rows and rows[0].kind != "file"):
            raise SwapStepRejected("Additional or non-file swap exists")
        if rows:
            other_parent = _open_dir(Path(rows[0].path).parent)
            try:
                other = os.open(Path(rows[0].path).name,
                                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=other_parent)
                try:
                    if file_identity(other) != expected:
                        raise SwapStepRejected("Active swap is not the pinned legacy file")
                finally:
                    os.close(other)
            finally:
                os.close(other_parent)
        a, b = os.stat("/proc/self/ns/mnt"), os.stat("/proc/1/ns/mnt")
        return Runtime(_read_text("/proc/sys/kernel/random/boot_id").strip(),
                       (a.st_dev, a.st_ino), (b.st_dev, b.st_ino), bool(rows),
                       rows[0].size if rows else 0, rows[0].priority if rows else 0,
                       rows[0].used if rows else 0, memory_available(_read_text("/proc/meminfo")),
                       os.sysconf("SC_PAGE_SIZE"))

    @staticmethod
    def _native(fd: int, priority: int | None) -> None:
        if os.geteuid() != 0:
            raise SwapStepRejected("Native swap effects require root in the attested kernel")
        file_identity(fd)
        libc = ctypes.CDLL(None, use_errno=True)
        function = libc.swapoff if priority is None else libc.swapon
        function.argtypes = [ctypes.c_char_p] if priority is None else [ctypes.c_char_p, ctypes.c_int]
        function.restype = ctypes.c_int
        filename = f"/proc/self/fd/{fd}".encode("ascii")
        if priority is None:
            result = function(filename)
        else:
            if type(priority) is not int or not (priority == -2 or 0 <= priority <= 32767):
                raise SwapStepRejected("Original swap priority cannot be reproduced")
            # Linux SWAP_FLAG_PREFER, preserving explicit priorities. No discard,
            # formatting, automatic priority guess or reinitialization is used.
            result = function(filename, 0 if priority == -2 else 0x8000 | priority)
        if result != 0:
            raise OSError(ctypes.get_errno(), "Descriptor-bound swap operation did not complete")

    def disable(self, fd: int) -> None:
        self._native(fd, None)

    def restore(self, fd: int, priority: int) -> None:
        self._native(fd, priority)


class LegacySwapAdapter:
    """Owned file metadata + operation-bound intent, not authority by path/absence.

    A shared state-directory lock and retained file FD are held throughout.
    External administrative mutations are not prevented by advisory file locks;
    independent frozen-writer context remains mandatory for real integration.
    """
    def __init__(self, path: Path, parent: Path, operation: str,
                 context: Callable[[], BoundContext], kernel: Kernel | None = None):
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise SwapStepRejected("Canonical operation required")
        self.path, self.parent, self.operation = path, parent, operation
        self.read_context, self.kernel = context, kernel or LinuxSwapKernel()
        self.parent_fd = self.file_parent_fd = self.fd = self.bundle_fd = self.lock_fd = -1
        self.journal: Journal | None = None
        try:
            self.parent_fd = _open_dir(parent)
            self.parent_identity = _dir_identity(self.parent_fd, private=True)
            self.file_parent_fd = _open_dir(path.parent)
            self.file_parent_identity = _dir_identity(self.file_parent_fd)
            self.fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=self.file_parent_fd)
            self.original = file_identity(self.fd)
            self.lock_fd = os.open(".legacy-swap.lock", os.O_RDWR | os.O_CREAT | os.O_NONBLOCK
                                   | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.parent_fd)
            lock = os.fstat(self.lock_fd)
            if (not stat.S_ISREG(lock.st_mode) or lock.st_nlink != 1 or lock.st_size
                    or lock.st_uid != os.geteuid() or stat.S_IMODE(lock.st_mode) != 0o600):
                raise SwapStepRejected("Unsafe swap operation lock")
            self.lock_identity = (lock.st_dev, lock.st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.parent_fd)
        except BaseException:
            self.close()
            raise

    @classmethod
    def prepare(cls, path: Path, parent: Path, operation: str,
                context: Callable[[], BoundContext], *, reserve: int,
                kernel: Kernel | None = None) -> Self:
        adapter = cls(path, parent, operation, context, kernel)
        try:
            if type(reserve) is not int or reserve < 4096:
                raise SwapStepRejected("Explicit positive memory reserve required")
            bound = context()
            if not isinstance(bound, BoundContext):
                raise SwapStepRejected("Independent typed context required")
            sample = adapter.kernel.sample(adapter.fd, path)
            adapter._valid_runtime(sample, bound)
            if (not sample.active or sample.size != adapter.original["st_size"] - 4096
                    or not (sample.priority == -2 or 0 <= sample.priority <= 32767)
                    or sample.available < sample.used + reserve):
                raise SwapStepRejected("Legacy active swap baseline or reserve not accepted")
            os.mkdir(operation, mode=0o700, dir_fd=adapter.parent_fd)
            os.fsync(adapter.parent_fd)
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                        | os.O_CLOEXEC, dir_fd=adapter.parent_fd)
            body = {"schema": 1, "operation": operation, "context": asdict(bound),
                    "path": str(path), "parent": adapter.parent_identity,
                    "file_parent": adapter.file_parent_identity, "file": adapter.original,
                    "lock": list(adapter.lock_identity), "bundle": _dir_identity(adapter.bundle_fd, private=True),
                    "namespace": list(sample.namespace), "size": sample.size,
                    "priority": sample.priority, "reserve": reserve}
            _write_new(adapter.bundle_fd, "binding.json", json.dumps(body, sort_keys=True).encode()+b"\n", 0o600)
            adapter._load()
            if context() != bound or not adapter._sample().active:
                raise SwapStepRejected("Baseline changed during preparation; retained without cleanup")
            return adapter
        except BaseException:
            adapter.close()
            raise

    @classmethod
    def load(cls, path: Path, parent: Path, operation: str,
             context: Callable[[], BoundContext], *, kernel: Kernel | None = None) -> Self:
        adapter = cls(path, parent, operation, context, kernel)
        try:
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                        | os.O_CLOEXEC, dir_fd=adapter.parent_fd)
            adapter._load()
            adapter.context()
            return adapter
        except BaseException:
            adapter.close()
            raise

    def _load(self) -> None:
        self.binding_identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        body = json.loads(raw, object_pairs_hook=_unique)
        if (not isinstance(body, dict) or set(body) != {"schema", "operation", "context", "path", "parent",
                "file_parent", "file", "lock", "bundle", "namespace", "size", "priority", "reserve"}
                or type(body["schema"]) is not int or body["schema"] != 1
                or body["operation"] != self.operation or body["path"] != str(self.path)
                or body["parent"] != self.parent_identity or body["file_parent"] != self.file_parent_identity
                or body["file"] != self.original or body["lock"] != list(self.lock_identity)
                or body["bundle"] != _dir_identity(self.bundle_fd, private=True)
                or type(body["size"]) is not int or body["size"] != self.original["st_size"]-4096
                or type(body["priority"]) is not int or not (body["priority"] == -2 or 0 <= body["priority"] <= 32767)
                or type(body["reserve"]) is not int or body["reserve"] < 4096
                or not isinstance(body["namespace"], list) or len(body["namespace"]) != 2
                or any(type(n) is not int or n <= 0 for n in body["namespace"])):
            raise SwapStepRejected("Swap binding identity or schema differs")
        self.bound = BoundContext(**body["context"])
        self.binding, self.binding_hash = body, hashlib.sha256(raw).hexdigest()
        self.step = BoundStep(STEP, self._fingerprint(True), self._fingerprint(False))
        self._identity()

    def _fingerprint(self, active: bool) -> str:
        return _digest({"binding": self.binding_hash, "active": active})

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        for attr in ("fd", "file_parent_fd", "bundle_fd", "lock_fd", "parent_fd"):
            value = getattr(self, attr)
            if value >= 0:
                os.close(value)
                setattr(self, attr, -1)

    def _identity(self) -> None:
        if self.fd < 0 or self.bundle_fd < 0:
            raise SwapStepRejected("Closed swap adapter")
        for path, pinned, private in ((self.parent, self.parent_identity, True),
                                       (self.path.parent, self.file_parent_identity, False)):
            current = _open_dir(path)
            try:
                if _dir_identity(current, private=private) != pinned:
                    raise SwapStepRejected("Swap parent changed")
            finally:
                os.close(current)
        named = os.stat(self.path.name, dir_fd=self.file_parent_fd, follow_symlinks=False)
        if ((named.st_dev, named.st_ino) != (self.original["st_dev"], self.original["st_ino"])
                or not stat.S_ISREG(named.st_mode) or file_identity(self.fd) != self.original):
            raise SwapStepRejected("Legacy swap file changed")
        lock = os.stat(".legacy-swap.lock", dir_fd=self.parent_fd, follow_symlinks=False)
        if ((lock.st_dev, lock.st_ino) != self.lock_identity or not stat.S_ISREG(lock.st_mode)
                or lock.st_uid != os.geteuid() or stat.S_IMODE(lock.st_mode) != 0o600
                or lock.st_nlink != 1 or lock.st_size != 0):
            raise SwapStepRejected("Swap operation lock changed")
        bundle = os.stat(self.operation, dir_fd=self.parent_fd, follow_symlinks=False)
        if ((bundle.st_dev, bundle.st_ino) != (self.binding["bundle"]["device"], self.binding["bundle"]["inode"])
                or _dir_identity(self.bundle_fd, private=True) != self.binding["bundle"]):
            raise SwapStepRejected("Swap binding directory changed")
        identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        if (identity != self.binding_identity or hashlib.sha256(raw).hexdigest() != self.binding_hash
                or os.listdir(self.bundle_fd) != ["binding.json"]):
            raise SwapStepRejected("Swap binding content or identity changed")

    @staticmethod
    def _valid_runtime(sample: Runtime, bound: BoundContext) -> None:
        if (not isinstance(sample, Runtime) or sample.boot_id != bound.boot_id
                or not isinstance(sample.namespace, tuple) or sample.namespace != sample.init_namespace
                or len(sample.namespace) != 2
                or any(type(x) is not int or x <= 0 for x in sample.namespace)
                or type(sample.active) is not bool or type(sample.page_size) is not int
                or sample.page_size != 4096 or type(sample.priority) is not int
                or any(type(x) is not int or x < 0 for x in (sample.size, sample.used, sample.available))
                or sample.used > sample.size):
            raise SwapStepRejected("Boot, namespace or memory sample invalid")

    def _sample(self) -> Runtime:
        self._identity()
        start = time.monotonic()
        sample = self.kernel.sample(self.fd, self.path)
        self._valid_runtime(sample, self.bound)
        if (list(sample.namespace) != self.binding["namespace"]
                or (sample.active and (sample.size != self.binding["size"] or sample.priority != self.binding["priority"]))
                or (not sample.active and (sample.size, sample.priority, sample.used) != (0, 0, 0))
                or not 0 <= time.monotonic()-start <= 5):
            raise SwapStepRejected("Bound swap state or sampling window changed")
        self._identity()
        return sample

    def context(self) -> BoundContext:
        self._identity()
        current = self.read_context()
        if current != self.bound:
            raise SwapStepRejected("Independent closed authority or source context changed")
        return current

    def attach(self, journal: Journal) -> None:
        if (journal.plan.operation != self.operation or journal.plan.context != self.bound
                or journal.plan.steps != (self.step,)):
            raise SwapStepRejected("Single legacy swap step and exact binding required")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        if step != self.step or operation != self.operation:
            raise SwapStepRejected("Foreign swap operation")
        sample = self._sample()
        authorized = False
        if self.journal is not None:
            state = self.journal.state()
            authorized = state.applied == 1 or state.pending == ("apply", 0)
        return Observation(self._fingerprint(sample.active), True, not sample.active and authorized)

    def _effect(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        if self.journal is None or step != self.step or operation != self.operation:
            raise SwapStepRejected("Exact attached journal required")
        state = self.journal.state()
        if state.pending != ("undo" if undo else "apply", 0):
            raise SwapStepRejected("Durable direction-bound intent required")
        first, second = self._sample(), self._sample()
        if first.active != (not undo) or second.active != first.active:
            raise SwapStepRejected("Unexpected active-swap transition; never replay")
        if not undo and min(first.available-first.used, second.available-second.used) < self.binding["reserve"]:
            raise SwapStepRejected("Insufficient current reserve for swapoff")
        self.context()
        if undo:
            self.kernel.restore(self.fd, self.binding["priority"])
        else:
            self.kernel.disable(self.fd)
        self.context()
        if self._sample().active != undo:
            raise SwapStepRejected("Kernel return did not establish the expected state")

    def apply(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=True)
