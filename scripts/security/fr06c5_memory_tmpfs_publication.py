"""C5E11 retained underlay and reversible publication of an accepted private tmpfs.

Two journal-bound steps preserve a private bind reference to the original
subdirectory, then move the existing tmpfs mount into that directory. Rollback
moves the SAME mount back to staging, including any new files; it never unmounts
or discards that tmpfs. Only afterwards may the no-longer-needed recovery reference go.

There is no production CLI, writer freezer or encrypted-swap attestor here.
The mandatory authority callback must independently revalidate those proofs
and the reference scan each time. A digest is a binding, not such an attestor.
Markers/advisory locks do not prevent privileged ABA or outside namespaces.
Native mutation tests must run in a separate guest, never on the project host.
C5E9 and its blocked source receipt are neither imported nor replaced.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Self

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
from scripts.security.fr06c5_memory_tmpfs_stage import (
    TmpfsStageAdapter,
    _text,
    _visible,
)
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

STEPS = ("preserve_tmp_underlay", "publish_tmpfs_mount")


class PublicationRejected(TransitionRejected):
    """An absent independent gate or unknown topology prevents publication."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise PublicationRejected(reason)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate publication binding field")
        result[key] = value
    return result


@dataclass(frozen=True)
class FrozenEvidence:
    """Bindings returned by an independent, CURRENT frozen-writer authority.

    Construction alone verifies no kernel, production or provider condition.
    There is deliberately no default authority implementation.
    """
    context: BoundContext
    writer_fence_sha256: str
    encrypted_swap_sha256: str
    underlay_scan_sha256: str

    def __post_init__(self) -> None:
        _require(isinstance(self.context, BoundContext), "Typed closed context required")
        for value in (self.writer_fence_sha256, self.encrypted_swap_sha256, self.underlay_scan_sha256):
            _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
                     "Independent writer/swap/reference evidence is required")


@dataclass(frozen=True)
class Runtime:
    boot_id: str
    namespace: tuple[int, int]
    init_namespace: tuple[int, int]
    mounts: tuple[Mount, ...]
    stage: tuple[int, ...]
    public: tuple[int, ...]
    reference: tuple[int, ...]


def _exact(rows: tuple[Mount, ...], path: Path) -> Mount | None:
    found = [row for row in rows if row.target == str(path)]
    _require(len(found) <= 1, "Stacked mounts are not accepted")
    _require(not any(row.target.startswith(str(path) + "/") for row in rows), "Nested mounts are not accepted")
    return found[0] if found else None


def _containing(rows: tuple[Mount, ...], path: Path) -> Mount:
    found = [row for row in rows if str(path) == row.target or str(path).startswith(row.target.rstrip("/") + "/")]
    _require(bool(found), "Containing mount is missing")
    length = max(len(row.target) for row in found)
    closest = [row for row in found if len(row.target) == length]
    _require(len(closest) == 1 and closest[0].optional == (), "Containing mount is ambiguous or propagating")
    return closest[0]


class Kernel(Protocol):
    def sample(self, stage: TmpfsStageAdapter, public_parent: int, public: Path, bundle: int, reference: Path) -> Runtime: ...
    def preserve(self, public_parent: int, name: str, bundle: int) -> None: ...
    def move(self, source_parent: int, source_name: str, target_parent: int, target_name: str) -> None: ...
    def release(self, bundle: int) -> None: ...


class LinuxPublicationKernel:
    """One ordinary bind, mount move or unmount; no shell, force or lazy flags."""
    def sample(self, stage: TmpfsStageAdapter, public_parent: int, public: Path, bundle: int, reference: Path) -> Runtime:
        before = parse_mountinfo(_text("/proc/self/mountinfo"))
        values = []
        for parent, name, path in ((stage.bundle_fd, "mount", stage.target),
                                    (public_parent, public.name, public), (bundle, "underlay", reference)):
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
                visible = _visible(fd)
                current = _open_dir(path)
                try:
                    _require(_visible(current) == visible, "Public/reference path changed")
                finally:
                    os.close(current)
                values.append(visible)
            finally:
                os.close(fd)
        own, init = os.stat("/proc/self/ns/mnt"), os.stat("/proc/1/ns/mnt")
        _require(parse_mountinfo(_text("/proc/self/mountinfo")) == before, "Topology changed during observation")
        return Runtime(_text("/proc/sys/kernel/random/boot_id").strip(), (own.st_dev, own.st_ino),
                       (init.st_dev, init.st_ino), before, *values)

    @staticmethod
    def _mount(source: bytes, target: bytes, flags: int) -> None:
        _require(os.geteuid() == 0 and flags in {4096, 8192}, "Only native bind or move in the attested kernel")
        lib = ctypes.CDLL(None, use_errno=True)
        lib.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_void_p]
        lib.mount.restype = ctypes.c_int
        if lib.mount(source, target, None, flags, None) != 0:
            raise OSError(ctypes.get_errno(), "Single mount operation failed; no fallback or automatic replay")

    def preserve(self, public_parent: int, name: str, bundle: int) -> None:
        source = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=public_parent)
        try:
            self._mount(f"/proc/self/fd/{source}".encode(), f"/proc/self/fd/{bundle}/underlay".encode(), 4096)
        finally:
            os.close(source)

    def move(self, source_parent: int, source_name: str, target_parent: int, target_name: str) -> None:
        _require(source_name in {"tmp", "mount"} and target_name in {"tmp", "mount"}, "Fixed publication basenames required")
        self._mount(f"/proc/self/fd/{source_parent}/{source_name}".encode(),
                    f"/proc/self/fd/{target_parent}/{target_name}".encode(), 8192)

    def release(self, bundle: int) -> None:
        _require(os.geteuid() == 0, "Native reference removal requires root in the attested kernel")
        lib = ctypes.CDLL(None, use_errno=True)
        lib.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.umount2.restype = ctypes.c_int
        if lib.umount2(f"/proc/self/fd/{bundle}/underlay".encode(), 0) != 0:
            raise OSError(ctypes.get_errno(), "Reference is busy or removal failed; no force or lazy unmount")


class TmpfsPublicationAdapter:
    """Two reversible topology steps, retaining BOTH old and new data in place."""
    def __init__(self, stage: TmpfsStageAdapter, public: Path, parent: Path,
                 authority: Callable[[], FrozenEvidence], *, kernel: Kernel | None = None):
        _require(callable(authority) and public.is_absolute() and public.name == "tmp" and ".." not in public.parts,
                 "Explicit directory and independent authority required")
        _require(not any(a == b or a in b.parents or b in a.parents for a, b in
                         ((public, parent), (public, stage.parent), (parent, stage.target))), "Publication resources overlap")
        self.stage, self.public, self.parent, self.authority = stage, public, parent, authority
        self.kernel = kernel or LinuxPublicationKernel()
        self.operation, self.bound = stage.operation, stage.context()
        self.parent_fd = self.public_parent_fd = self.lock_fd = self.bundle_fd = -1
        self.journal: Journal | None = None
        self.reference = parent / self.operation / "underlay"
        try:
            self._parent_owned()
            self.parent_fd = _open_dir(parent)
            self.parent_identity = _dir_identity(self.parent_fd, private=True)
            self.public_parent_fd = _open_dir(public.parent)
            self.public_parent_identity = _dir_identity(self.public_parent_fd)
            self.lock_fd = os.open(".publication.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                   0o600, dir_fd=self.parent_fd)
            info = os.fstat(self.lock_fd)
            self._lock_ok(info)
            self.lock_identity = (info.st_dev, info.st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.parent_fd)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _lock_ok(info: os.stat_result) -> None:
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600
                 and info.st_nlink == 1 and not info.st_size, "Unsafe publication lock")

    def _parent_owned(self) -> None:
        _require(self.stage.context() == self.bound and self.stage.journal is not None,
                 "Retained staging authority and journal required")
        assert self.stage.journal is not None
        _require(self.stage.journal.state().phase == "applied", "Staging journal is not finalized")

    @classmethod
    def prepare(cls, stage: TmpfsStageAdapter, public: Path, parent: Path,
                authority: Callable[[], FrozenEvidence], *, kernel: Kernel | None = None) -> Self:
        a = cls(stage, public, parent, authority, kernel=kernel)
        try:
            proof = authority()
            _require(isinstance(proof, FrozenEvidence) and proof.context == a.bound, "Independent frozen evidence differs")
            owned = stage.observe(stage.step, stage.operation)
            _require(owned.identity_verified and owned.owned_by_operation and owned.fingerprint == stage.step.after_sha256,
                     "Only accepted empty staging is publishable")
            stage_sample = stage._sample()
            _require(stage_sample.mount is not None, "Staging was removed before preparation")
            assert stage_sample.mount is not None
            os.mkdir(a.operation, mode=0o700, dir_fd=a.parent_fd)
            os.fsync(a.parent_fd)
            a.bundle_fd = os.open(a.operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=a.parent_fd)
            os.mkdir("underlay", mode=0o700, dir_fd=a.bundle_fd)
            os.fsync(a.bundle_fd)
            sample = a.kernel.sample(stage, a.public_parent_fd, public, a.bundle_fd, a.reference)
            a._shape(sample)
            _require(sample.namespace == stage_sample.namespace, "Staging and publication namespaces differ")
            _require(_exact(sample.mounts, public) is None and _exact(sample.mounts, a.reference) is None
                     and _exact(sample.mounts, stage.target) == stage_sample.mount and sample.stage == stage_sample.visible,
                     "Public directory already mounted or staging identity differs")
            _require(stat.S_ISDIR(sample.public[2]) and stat.S_IMODE(sample.public[2]) == 0o1777
                     and sample.public[3:] == (os.geteuid(), os.getegid()), "Original tmp directory ownership or mode unsafe")
            containers = [_containing(sample.mounts, path) for path in (stage.target.parent, public.parent, a.reference.parent)]
            origin = containers[1]
            origin_root = str(Path(origin.root) / public.relative_to(Path(origin.target)))
            assert stage.journal is not None
            body = {"schema": 1, "operation": a.operation, "context": asdict(a.bound), "authority": asdict(proof),
                    "parent": a.parent_identity, "public_parent": a.public_parent_identity, "public_path": str(public),
                    "bundle": _dir_identity(a.bundle_fd, private=True), "lock": list(a.lock_identity),
                    "stage_binding": stage.binding_hash, "stage_plan": _digest(asdict(stage.journal.plan)),
                    "namespace": list(sample.namespace), "mount": asdict(stage_sample.mount),
                    "tmpfs_root": list(sample.stage), "original_public": list(sample.public), "original_reference": list(sample.reference),
                    "origin_root": origin_root, "containers": [asdict(c) for c in containers]}
            _write_new(a.bundle_fd, "binding.json", json.dumps(body, sort_keys=True).encode() + b"\n", 0o600)
            a._load()
            _require(a._sample()[1:] == (False, False), "Publication baseline changed during preparation")
            a.context()
            return a
        except BaseException:
            a.close()
            raise

    @classmethod
    def load(cls, stage: TmpfsStageAdapter, public: Path, parent: Path,
             authority: Callable[[], FrozenEvidence], *, kernel: Kernel | None = None) -> Self:
        a = cls(stage, public, parent, authority, kernel=kernel)
        try:
            a.bundle_fd = os.open(a.operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=a.parent_fd)
            a._load()
            a.context()
            return a
        except BaseException:
            a.close()
            raise

    def _load(self) -> None:
        self.binding_identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        b = json.loads(raw, object_pairs_hook=_unique)
        keys = {"schema", "operation", "context", "authority", "parent", "public_parent", "public_path", "bundle", "lock",
                "stage_binding", "stage_plan", "namespace", "mount", "tmpfs_root", "original_public", "original_reference", "origin_root", "containers"}
        assert self.stage.journal is not None
        _require(isinstance(b, dict) and set(b) == keys and type(b["schema"]) is int and b["schema"] == 1
                 and b["operation"] == self.operation and BoundContext(**b["context"]) == self.bound
                 and b["parent"] == self.parent_identity and b["public_parent"] == self.public_parent_identity
                 and b["public_path"] == str(self.public) and b["bundle"] == _dir_identity(self.bundle_fd, private=True)
                 and b["lock"] == list(self.lock_identity) and b["stage_binding"] == self.stage.binding_hash
                 and b["stage_plan"] == _digest(asdict(self.stage.journal.plan)), "Publication binding identity differs")
        self.frozen = FrozenEvidence(BoundContext(**b["authority"]["context"]), **{k: v for k, v in b["authority"].items() if k != "context"})
        _require(self.frozen.context == self.bound, "Publication evidence context differs")
        for key, length in (("namespace", 2), ("tmpfs_root", 5), ("original_public", 5), ("original_reference", 5)):
            _require(isinstance(b[key], list) and len(b[key]) == length and all(type(n) is int and n >= 0 for n in b[key]),
                     "Malformed identity vector")
        self.binding, self.binding_hash = b, hashlib.sha256(raw).hexdigest()
        self.steps = tuple(BoundStep(name, _digest({"binding": self.binding_hash, "step": name, "active": False}),
                                    _digest({"binding": self.binding_hash, "step": name, "active": True})) for name in STEPS)
        self._identity()

    def _identity(self) -> None:
        _require(min(self.parent_fd, self.public_parent_fd, self.lock_fd, self.bundle_fd) >= 0, "Closed publication adapter")
        self._parent_owned()
        for path, expected, private in ((self.parent, self.parent_identity, True), (self.public.parent, self.public_parent_identity, False)):
            fd = _open_dir(path)
            try:
                _require(_dir_identity(fd, private=private) == expected, "Publication parent replaced")
            finally:
                os.close(fd)
        lock = os.stat(".publication.lock", dir_fd=self.parent_fd, follow_symlinks=False)
        self._lock_ok(lock)
        _require((lock.st_dev, lock.st_ino) == self.lock_identity, "Publication lock replaced")
        bundle = os.stat(self.operation, dir_fd=self.parent_fd, follow_symlinks=False)
        _require(stat.S_ISDIR(bundle.st_mode) and (bundle.st_dev, bundle.st_ino) ==
                 (self.binding["bundle"]["device"], self.binding["bundle"]["inode"])
                 and _dir_identity(self.bundle_fd, private=True) == self.binding["bundle"], "Publication bundle replaced")
        identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        _require(identity == self.binding_identity and hashlib.sha256(raw).hexdigest() == self.binding_hash
                 and set(os.listdir(self.bundle_fd)) == {"binding.json", "underlay"}, "Publication evidence changed")

    def context(self) -> BoundContext:
        self._identity()
        _require(self.authority() == self.frozen, "Independent frozen-writer, encrypted-swap or reference proof changed")
        return self.bound

    def _shape(self, sample: Runtime) -> None:
        _require(isinstance(sample, Runtime) and sample.boot_id == self.bound.boot_id
                 and isinstance(sample.namespace, tuple) and len(sample.namespace) == 2
                 and all(type(n) is int and n > 0 for n in sample.namespace) and sample.namespace == sample.init_namespace
                 and isinstance(sample.mounts, tuple) and all(isinstance(m, Mount) for m in sample.mounts), "Invalid kernel observation")
        for value in (sample.stage, sample.public, sample.reference):
            _require(isinstance(value, tuple) and len(value) == 5 and all(type(n) is int and n >= 0 for n in value), "Malformed directory identity")

    def _sample(self) -> tuple[Runtime, bool, bool]:
        self._identity()
        start = time.monotonic()
        s = self.kernel.sample(self.stage, self.public_parent_fd, self.public, self.bundle_fd, self.reference)
        self._shape(s)
        _require(list(s.namespace) == self.binding["namespace"], "Publication namespace changed")
        containers = [_containing(s.mounts, p) for p in (self.stage.target.parent, self.public.parent, self.reference.parent)]
        _require(_digest([asdict(c) for c in containers]) == _digest(self.binding["containers"]), "Containing mount changed")
        staged, public, reference = (_exact(s.mounts, p) for p in (self.stage.target, self.public, self.reference))
        _require((staged is None) != (public is None), "Original tmpfs must have exactly one visible location")
        published = public is not None
        mount = public if published else staged
        assert mount is not None
        original_mount = dict(self.binding["mount"])
        actual = asdict(mount)
        for key in ("target", "parent_id"):
            original_mount.pop(key)
            actual.pop(key)
        _require(_digest(actual) == _digest(original_mount)
                 and mount.parent_id == containers[1 if published else 0].mount_id
                 and sum(m.device == mount.device for m in s.mounts) == 1,
                 "Moved tmpfs identity, options or aliases differ")
        _require(list(s.public if published else s.stage) == self.binding["tmpfs_root"], "Tmpfs root replaced")
        if published:
            _require(list(s.stage) == self.stage.binding["original"] and reference is not None, "Staging underlay or recovery reference lost")
        else:
            _require(list(s.public) == self.binding["original_public"], "Public underlay not restored")
        if reference is None:
            _require(list(s.reference) == self.binding["original_reference"] and not published, "Recovery directory replaced or removed too early")
        else:
            origin = self.binding["containers"][1]
            _require(reference.device == Device.number(s.reference[0]) and list(s.reference) == self.binding["original_public"]
                     and reference.root == self.binding["origin_root"] and reference.kind == origin["kind"]
                     and reference.source == origin["source"] and reference.optional == ()
                     and reference.parent_id == containers[2].mount_id
                     and list(reference.options) == origin["options"], "Recovery reference is not the original underlay")
        original_device = Device.number(self.binding["original_public"][0])
        origin_root = self.binding["origin_root"]
        aliases = [row for row in s.mounts if row.device == original_device
                   and (row.root == origin_root or row.root.startswith(origin_root.rstrip("/") + "/"))]
        _require(len(aliases) == int(reference is not None), "Unexpected alias of the original underlay")
        _require(0 <= time.monotonic() - start <= 10, "Publication sampling bound exceeded")
        self._identity()
        return s, reference is not None, published

    def attach(self, journal: Journal) -> None:
        _require(journal.plan.operation == self.operation and journal.plan.context == self.bound and journal.plan.steps == self.steps,
                 "Exact two-step publication journal required")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        _require(step in self.steps and operation == self.operation, "Foreign publication step")
        _, reference, published = self._sample()
        index = self.steps.index(step)
        active = reference if index == 0 else published
        owned = False
        if self.journal is not None:
            state = self.journal.state()
            owned = state.applied > index or state.pending == ("apply", index)
        return Observation(step.after_sha256 if active else step.before_sha256, True, active and owned)

    def _effect(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        _require(self.journal is not None and step in self.steps and operation == self.operation, "Exact attached journal required")
        assert self.journal is not None
        index = self.steps.index(step)
        _require(self.journal.state().pending == ("undo" if undo else "apply", index), "Durable direction-bound intent required")
        first, second = self._sample(), self._sample()
        _require(first == second, "Topology changed before publication effect")
        expected = {(False, 0): (False, False), (False, 1): (True, False),
                    (True, 1): (True, True), (True, 0): (True, False)}[(undo, index)]
        _require(first[1:] == expected, "Unexpected topology; no replay or implicit resource deletion")
        self.context()
        if not undo:
            # A staging mount can gain files after preparation. Refuse forward
            # publication of newly introduced data; reverse moves preserve it.
            proof = self.stage.observe(self.stage.step, self.operation)
            _require(proof.identity_verified and proof.owned_by_operation
                     and proof.fingerprint == self.stage.step.after_sha256, "Staging is no longer accepted and empty")
        self.context()
        if index == 0:
            if undo:
                self.kernel.release(self.bundle_fd)
            else:
                self.kernel.preserve(self.public_parent_fd, self.public.name, self.bundle_fd)
        elif undo:
            self.kernel.move(self.public_parent_fd, self.public.name, self.stage.bundle_fd, "mount")
        else:
            self.kernel.move(self.stage.bundle_fd, "mount", self.public_parent_fd, self.public.name)
        self.context()
        _, reference, published = self._sample()
        _require((reference if index == 0 else published) != undo, "Native result did not establish the required topology")

    def apply(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._effect(step, operation, undo=True)

    def close(self) -> None:
        for name in ("bundle_fd", "lock_fd", "public_parent_fd", "parent_fd"):
            fd = getattr(self, name)
            if fd >= 0:
                os.close(fd)
                setattr(self, name, -1)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
