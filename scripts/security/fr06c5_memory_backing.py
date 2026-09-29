"""C5E6 allocate, publish and retain one operation-owned swap backing inode.

Allocation occurs in private staging after a durable preparation intent. Only
an entirely allocated and pinned inode can be published through C5E2's journal.
Partial preparation is retained, never silently overwritten or cleaned up.
Undo moves the same inode back to staging, not truncate/unlink/secure erase.

No formatter, mapper creator, key handling, systemctl or activation CLI exists
here. A fresh independently attested closed/writer-frozen context is required.
Loop and direct-swap consumers are checked before moving the inode. Those
observations do not freeze other administrators, replace a writer barrier or
prove that an mmap/open file holder is absent. Advisory locks serialize only
cooperating operators. Kernel acceptance belongs in a separate VM.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import UUID

from scripts.security.fr06c5_memory_config_files import (
    _dir_identity,
    _file,
    _open_dir,
    _write_new,
    rename_owned,
)
from scripts.security.fr06c5_memory_kernel_observation import (
    Device,
    parse_swaps,
    read_loop_status,
)
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

STEP = "prepare_encrypted_backing"
MAX_BACKING = 64 * 1024**3
MAX_READ = 1024 * 1024


class BackingRejected(TransitionRejected):
    """A backing effect has insufficient ownership, space or consumer evidence."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BackingRejected("Duplicate backing manifest key")
        result[key] = value
    return result


def _metadata(fd: int, capacity: int) -> dict[str, int]:
    s = os.fstat(fd)
    if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid() or s.st_gid != os.getegid()
            or stat.S_IMODE(s.st_mode) != 0o600 or s.st_nlink != 1 or s.st_size != capacity
            or s.st_blocks * 512 < capacity or os.listxattr(fd)):
        raise BackingRejected("Backing not fully allocated, singly linked and private")
    # Ciphertext writes through a future loop may update time metadata, but may
    # not change ownership, capacity or inode; allocation must remain complete.
    # Extent metadata can change st_blocks without replacing the inode. No payload
    # is read or hashed. The separately held writer barrier remains essential.
    return {name: int(getattr(s, name)) for name in (
        "st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_blocks"
    )}



def same_allocation(actual: dict[str, int] | None, expected: dict[str, int] | None) -> bool:
    """Bind file identity and full allocation, not mutable extent accounting.

    Keep the original observed block count in historical manifests. Both current
    and original observations must cover the entire capacity. No sparse file,
    identity, permission, link-count or size drift is accepted. This does not
    attest payload integrity, which is never inferred from stat metadata.
    """
    keys = {"st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_blocks"}
    if actual is None or expected is None:
        return actual is expected
    if set(actual) != keys or set(expected) != keys:
        return False
    if any(type(value) is not int or value < 0 for row in (actual, expected) for value in row.values()):
        return False
    if any(row["st_size"] <= 0 or row["st_blocks"] * 512 < row["st_size"] for row in (actual, expected)):
        return False
    return all(actual[key] == expected[key] for key in keys - {"st_blocks"})

def _named(parent: int, name: str, capacity: int) -> dict[str, int] | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
    except FileNotFoundError:
        return None
    try:
        result = _metadata(fd, capacity)
        now = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (now.st_dev, now.st_ino) != (result["st_dev"], result["st_ino"]):
            raise BackingRejected("Backing name changed during observation")
        return result
    finally:
        os.close(fd)


def _absent(parent: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return True
    return False


def _read(path: str) -> str:
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_READ + 1)
    if len(data) > MAX_READ or not data.endswith(b"\n") or b"\0" in data:
        raise BackingRejected("Incomplete kernel consumer inventory")
    return data.decode("utf-8", errors="strict")


class ConsumerReader(Protocol):
    def consumers(self, fd: int) -> tuple[str, ...]: ...


class LinuxConsumers:
    """Read active loop inode bindings and direct file swaps, without key data.

    ENXIO from LOOP_GET_STATUS64 positively denotes an unbound loop. Permission
    errors, missing device nodes, an altered loop set or incomplete data reject
    the inventory rather than masquerading as zero consumers.
    """
    def consumers(self, fd: int) -> tuple[str, ...]:
        wanted = os.fstat(fd)
        if not stat.S_ISREG(wanted.st_mode):
            raise BackingRejected("Pinned regular backing required")
        started = time.monotonic()
        root = Path("/sys/class/block")
        loops = tuple(sorted(p.name for p in root.iterdir() if re.fullmatch(r"loop[0-9]+", p.name)))
        if len(loops) > 1024:
            raise BackingRejected("Loop inventory exceeds bound")
        found = []
        for name in loops:
            number = int(name[4:])
            device = Device.parse(_read(str(root / name / "dev")).strip())
            if device != Device(7, number):
                raise BackingRejected("Loop sysfs identity differs")
            loopfd = os.open("/dev/" + name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                info = os.fstat(loopfd)
                if not stat.S_ISBLK(info.st_mode) or Device.number(info.st_rdev) != device:
                    raise BackingRejected("Loop descriptor identity differs")
                try:
                    binding = read_loop_status(loopfd)
                except OSError as exc:
                    if exc.errno != errno.ENXIO:
                        raise
                else:
                    if binding.number != number:
                        raise BackingRejected("Loop number changed")
                    if (binding.backing_device, binding.backing_inode) == (Device.number(wanted.st_dev), wanted.st_ino):
                        found.append(name)
                named = os.stat("/dev/" + name, follow_symlinks=False)
                if not stat.S_ISBLK(named.st_mode) or named.st_rdev != info.st_rdev:
                    raise BackingRejected("Loop node changed during observation")
            finally:
                os.close(loopfd)
        swaps_text = _read("/proc/swaps")
        for swap in parse_swaps(swaps_text):
            if swap.kind != "file":
                continue
            parent = _open_dir(Path(swap.path).parent)
            try:
                other = os.open(Path(swap.path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                dir_fd=parent)
                try:
                    value = os.fstat(other)
                    if not stat.S_ISREG(value.st_mode):
                        raise BackingRejected("File-swap identity unavailable")
                    if (value.st_dev, value.st_ino) == (wanted.st_dev, wanted.st_ino):
                        found.append("direct-file-swap")
                finally:
                    os.close(other)
            finally:
                os.close(parent)
        again = tuple(sorted(p.name for p in root.iterdir() if re.fullmatch(r"loop[0-9]+", p.name)))
        before_rows, after_rows = parse_swaps(swaps_text), parse_swaps(_read("/proc/swaps"))
        projection = lambda rows: tuple((r.path, r.kind, r.size, r.priority) for r in rows)
        if again != loops or projection(before_rows) != projection(after_rows) or not 0 <= time.monotonic()-started <= 5:
            raise BackingRejected("Consumer inventory changed or sampling exceeded bound")
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino, current.st_size) != (wanted.st_dev, wanted.st_ino, wanted.st_size):
            raise BackingRejected("Backing changed during consumer inventory")
        return tuple(sorted(found))


class BackingAdapter:
    """One atomic journaled publication, retaining ciphertext on explicit undo.

    Preparation reserves real blocks in a new private file; it never adopts an
    existing backing. A partial preparation has no loadable final manifest.
    The receipt records that staging/allocation preceded publication and is not
    itself a production activation or a claim of encryption.
    """
    def __init__(self, target: Path, state_parent: Path, operation: str,
                 context: Callable[[], BoundContext], reader: ConsumerReader | None = None):
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise BackingRejected("Canonical operation required")
        if target.name != "random-swap.backing":
            raise BackingRejected("Only the reviewed backing basename is supported")
        self.target, self.state_parent, self.operation = target, state_parent, operation
        self.read_context, self.reader = context, reader or LinuxConsumers()
        self.parent_fd = self.state_fd = self.lock_fd = self.bundle_fd = self.stage_fd = self.fd = -1
        self.journal: Journal | None = None
        try:
            self.parent_fd, self.state_fd = _open_dir(target.parent), _open_dir(state_parent)
            self.parent_identity = _dir_identity(self.parent_fd, private=True)
            self.state_identity = _dir_identity(self.state_fd, private=True)
            self.lock_fd = os.open(".backing.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                   0o600, dir_fd=self.state_fd)
            info = os.fstat(self.lock_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size):
                raise BackingRejected("Unsafe backing operation lock")
            self.lock_identity = (info.st_dev, info.st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.state_fd)
        except BaseException:
            self.close()
            raise

    @classmethod
    def prepare(cls, target: Path, state_parent: Path, operation: str,
                context: Callable[[], BoundContext], *, capacity: int, reserve: int,
                reader: ConsumerReader | None = None) -> Self:
        if (type(capacity) is not int or not 8192 <= capacity <= MAX_BACKING or capacity % 4096
                or type(reserve) is not int or reserve < 4096):
            raise BackingRejected("Bounded aligned capacity and positive disk reserve required")
        adapter = cls(target, state_parent, operation, context, reader)
        try:
            bound = context()
            if not isinstance(bound, BoundContext) or not _absent(adapter.parent_fd, target.name):
                raise BackingRejected("Closed context and absent new backing required")
            fs = os.fstatvfs(adapter.parent_fd)
            if fs.f_bavail * fs.f_frsize < capacity + reserve:
                raise BackingRejected("Insufficient space beyond backing allocation reserve")
            os.mkdir(operation, mode=0o700, dir_fd=adapter.state_fd)
            os.fsync(adapter.state_fd)
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.state_fd)
            stage_name = ".aionex-backing-" + operation
            # A durable intent exists before candidate creation/allocation.
            intent = {"operation": operation, "context": asdict(bound), "capacity": capacity,
                      "reserve": reserve, "target": str(target), "parent": adapter.parent_identity,
                      "stage_name": stage_name, "automatic_retry": False}
            _write_new(adapter.bundle_fd, "preparation-intent.json", json.dumps(intent, sort_keys=True).encode()+b"\n", 0o600)
            os.mkdir(stage_name, mode=0o700, dir_fd=adapter.parent_fd)
            os.fsync(adapter.parent_fd)
            adapter.stage_fd = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                       dir_fd=adapter.parent_fd)
            adapter.fd = os.open("candidate", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=adapter.stage_fd)
            os.fsync(adapter.fd)
            os.fsync(adapter.stage_fd)
            created = os.fstat(adapter.fd)
            _write_new(adapter.bundle_fd, "created-inode.json",
                       json.dumps({"device": created.st_dev, "inode": created.st_ino,
                                   "capacity": capacity, "operation": operation}, sort_keys=True).encode()+b"\n", 0o600)
            if context() != bound:
                raise BackingRejected("Context changed before allocation; retained without replay")
            os.posix_fallocate(adapter.fd, 0, capacity)
            os.fsync(adapter.fd)
            os.fsync(adapter.stage_fd)
            allocated = _metadata(adapter.fd, capacity)
            if (allocated["st_dev"], allocated["st_ino"]) != (created.st_dev, created.st_ino):
                raise BackingRejected("Reserved allocation inode changed")
            fs = os.fstatvfs(adapter.parent_fd)
            if fs.f_bavail * fs.f_frsize < reserve or context() != bound:
                raise BackingRejected("Space/context changed; allocated staging retained")
            if not _absent(adapter.parent_fd, target.name):
                raise BackingRejected("Another backing appeared; no replacement")
            proof = {}
            for name in ("preparation-intent.json", "created-inode.json"):
                identity, raw = _file(adapter.bundle_fd, name, private=True)
                proof[name] = {"identity": identity, "sha256": hashlib.sha256(raw).hexdigest()}
            manifest = {"schema": 1, "operation": operation, "context": asdict(bound), "target": str(target),
                        "parent": adapter.parent_identity, "state": adapter.state_identity,
                        "bundle": _dir_identity(adapter.bundle_fd, private=True), "lock": list(adapter.lock_identity),
                        "stage_name": stage_name, "stage": _dir_identity(adapter.stage_fd, private=True),
                        "capacity": capacity, "file": allocated, "preparation": proof}
            _write_new(adapter.bundle_fd, "manifest.json", json.dumps(manifest, sort_keys=True).encode()+b"\n", 0o600)
            adapter._load()
            if adapter.observe(adapter.step, operation).fingerprint != adapter.step.before_sha256:
                raise BackingRejected("Publication baseline changed")
            return adapter
        except BaseException:
            adapter.close()
            raise

    @classmethod
    def load(cls, target: Path, state_parent: Path, operation: str,
             context: Callable[[], BoundContext], reader: ConsumerReader | None = None) -> Self:
        adapter = cls(target, state_parent, operation, context, reader)
        try:
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.state_fd)
            adapter._load()
            adapter.stage_fd = os.open(adapter.spec["stage_name"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                       dir_fd=adapter.parent_fd)
            candidates = [(adapter.stage_fd, "candidate"), (adapter.parent_fd, target.name)]
            available = [(fd, name) for fd, name in candidates if not _absent(fd, name)]
            if len(available) != 1:
                raise BackingRejected("Backing location missing or ambiguous")
            parent, name = available[0]
            adapter.fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
            adapter.context()
            return adapter
        except BaseException:
            adapter.close()
            raise

    def _load(self) -> None:
        self.manifest_identity, raw = _file(self.bundle_fd, "manifest.json", private=True)
        spec = json.loads(raw, object_pairs_hook=_unique)
        if (not isinstance(spec, dict) or set(spec) != {"schema", "operation", "context", "target", "parent", "state",
                "bundle", "lock", "stage_name", "stage", "capacity", "file", "preparation"}
                or type(spec["schema"]) is not int or spec["schema"] != 1
                or spec["operation"] != self.operation or spec["target"] != str(self.target)
                or spec["parent"] != self.parent_identity or spec["state"] != self.state_identity
                or spec["lock"] != list(self.lock_identity) or spec["bundle"] != _dir_identity(self.bundle_fd, private=True)
                or spec["stage_name"] != ".aionex-backing-" + self.operation
                or type(spec["capacity"]) is not int or not 8192 <= spec["capacity"] <= MAX_BACKING or spec["capacity"] % 4096
                or not isinstance(spec["preparation"], dict)
                or set(spec["preparation"]) != {"preparation-intent.json", "created-inode.json"}):
            raise BackingRejected("Backing manifest schema or operation differs")
        self.spec, self.manifest_hash = spec, hashlib.sha256(raw).hexdigest()
        self.bound = BoundContext(**spec["context"])
        self.step = BoundStep(STEP, _digest({"manifest": self.manifest_hash, "published": False}),
                             _digest({"manifest": self.manifest_hash, "published": True}))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        for attr in ("fd", "stage_fd", "bundle_fd", "lock_fd", "state_fd", "parent_fd"):
            value = getattr(self, attr)
            if value >= 0:
                os.close(value)
                setattr(self, attr, -1)

    def _identity(self) -> None:
        if min(self.fd, self.stage_fd, self.bundle_fd, self.lock_fd) < 0:
            raise BackingRejected("Closed backing adapter")
        for path, identity in ((self.target.parent, self.parent_identity), (self.state_parent, self.state_identity)):
            current = _open_dir(path)
            try:
                if _dir_identity(current, private=True) != identity:
                    raise BackingRejected("Backing or journal parent changed")
            finally:
                os.close(current)
        lock = os.stat(".backing.lock", dir_fd=self.state_fd, follow_symlinks=False)
        if (not stat.S_ISREG(lock.st_mode) or (lock.st_dev, lock.st_ino) != self.lock_identity
                or lock.st_uid != os.geteuid() or stat.S_IMODE(lock.st_mode) != 0o600 or lock.st_nlink != 1 or lock.st_size):
            raise BackingRejected("Backing lock changed")
        for parent, name, fd, identity in ((self.state_fd, self.operation, self.bundle_fd, self.spec["bundle"]),
                (self.parent_fd, self.spec["stage_name"], self.stage_fd, self.spec["stage"])):
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != (identity["device"], identity["inode"])
                    or _dir_identity(fd, private=True) != identity):
                raise BackingRejected("Backing stage/binding identity changed")
        manifest_info, raw = _file(self.bundle_fd, "manifest.json", private=True)
        if manifest_info != self.manifest_identity or hashlib.sha256(raw).hexdigest() != self.manifest_hash:
            raise BackingRejected("Backing manifest changed")
        if set(os.listdir(self.bundle_fd)) != {"manifest.json", *self.spec["preparation"]}:
            raise BackingRejected("Unexpected backing evidence files")
        for name, wanted in self.spec["preparation"].items():
            preparation_info, data = _file(self.bundle_fd, name, private=True)
            if preparation_info != wanted["identity"] or hashlib.sha256(data).hexdigest() != wanted["sha256"]:
                raise BackingRejected("Preparation intent or inode receipt changed")
        if not set(os.listdir(self.stage_fd)).issubset({"candidate"}) or not same_allocation(_metadata(self.fd, self.spec["capacity"]), self.spec["file"]):
            raise BackingRejected("Backing file allocation or staging changed")

    def context(self) -> BoundContext:
        self._identity()
        current = self.read_context()
        if not isinstance(current, BoundContext) or current != self.bound:
            raise BackingRejected("Independent frozen-writer context changed")
        return current

    def attach(self, journal: Journal) -> None:
        if (journal.plan.operation != self.operation or journal.plan.context != self.bound
                or journal.plan.steps != (self.step,)):
            raise BackingRejected("Exact single backing step journal required")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        self._identity()
        if step != self.step or operation != self.operation:
            raise BackingRejected("Foreign backing step")
        target, staged = _named(self.parent_fd, self.target.name, self.spec["capacity"]), _named(self.stage_fd, "candidate", self.spec["capacity"])
        if target is None and same_allocation(staged, self.spec["file"]):
            published = False
        elif same_allocation(target, self.spec["file"]) and staged is None:
            published = True
        else:
            raise BackingRejected("Unknown or replaced backing inode")
        if not published:
            consumers = self.reader.consumers(self.fd)
            if not isinstance(consumers, tuple) or consumers:
                raise BackingRejected("Unused backing baseline has consumers or incomplete evidence")
            if (_named(self.parent_fd, self.target.name, self.spec["capacity"]) is not None
                    or not same_allocation(_named(self.stage_fd, "candidate", self.spec["capacity"]), staged)):
                raise BackingRejected("Backing location changed during baseline observation")
        self._identity()
        authorized = False
        if self.journal is not None:
            state = self.journal.state()
            authorized = state.applied == 1 or state.pending == ("apply", 0)
        return Observation(step.after_sha256 if published else step.before_sha256, True, published and authorized)

    def _effect(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        if self.journal is None or step != self.step or operation != self.operation:
            raise BackingRejected("Attached exact backing journal required")
        if self.journal.state().pending != ("undo" if undo else "apply", 0):
            raise BackingRejected("Durable backing direction intent required")
        proof = self.observe(step, operation)
        if proof.fingerprint != (step.after_sha256 if undo else step.before_sha256) or (undo and not proof.owned_by_operation):
            raise BackingRejected("Backing effect already happened or ownership differs")
        for _ in range(2):
            consumers = self.reader.consumers(self.fd)
            if not isinstance(consumers, tuple) or consumers:
                raise BackingRejected("Backing has kernel consumers or an unknown inventory")
            self.context()
        current = self.observe(step, operation)
        if current != proof:
            raise BackingRejected("Backing names changed during consumer observation")
        # Same inode, no overwriting, no copying and no fallback on failure.
        if undo:
            rename_owned(self.parent_fd, self.target.name, self.stage_fd, "candidate", exchange=False)
        else:
            rename_owned(self.stage_fd, "candidate", self.parent_fd, self.target.name, exchange=False)
        os.fsync(self.stage_fd)
        os.fsync(self.parent_fd)
        self.context()

    def apply(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=True)
