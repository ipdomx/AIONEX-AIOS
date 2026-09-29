"""C5E8 journal-bound creation/removal of an operation-named PLAIN mapper.

Requires an accepted C5E7 loop and C5E6 backing, each with its retained journal
and lock. Creation uses libcryptsetup; removal is one libdevmapper task. No shell/argv keys or key files.
The mapper's operation-specific name/UUID are installed by creation itself;
existing devices are not adopted. Partial native outcomes remain uncertain.

Only mapper create/remove is implemented. There is no mkswap, swapon, mount,
boot unit, production context reader or activation CLI. Native tests belong in
a separate VM. UUID/name markers do not defend against a privileged actor able
to forge them; independently frozen writers and closed authority are required.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import stat
import subprocess
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
from scripts.security.fr06c5_memory_kernel_observation import (
    MAPPER_PATH,
    CryptMetadata,
    Device,
    parse_crypt_status,
    parse_mountinfo,
    parse_swaps,
)
from scripts.security.fr06c5_memory_loop import LoopAdapter
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)
from scripts.security.fr06c5_memory_volatile_key import LockedKey, disable_process_dumps

STEP = "create_swap_mapper"
MAX_TEXT = 1024 * 1024


class MapperRejected(TransitionRejected):
    """Uncertain identity, ownership, context or consumers forbid a mutation."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MapperRejected(reason)


def mapper_name(operation: str) -> str:
    _require(isinstance(operation, str) and str(UUID(operation)) == operation, "Canonical operation required")
    return "aionex-c5e8-" + UUID(operation).hex


def mapper_uuid(operation: str) -> str:
    return "CRYPT-PLAIN-" + mapper_name(operation)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate mapper binding field")
        result[key] = value
    return result


def _text(path: str) -> str:
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_TEXT+1)
    _require(len(data) <= MAX_TEXT and b"\0" not in data and data.endswith(b"\n"), "Incomplete kernel evidence")
    return data.decode("utf-8", errors="strict")


def parse_mapper_status(value: str, operation: str) -> CryptMetadata:
    """Reuse the strict C5E4 parser after verifying the exact dynamic header."""
    path = "/dev/mapper/" + mapper_name(operation)
    head, separator, rest = value.partition("\n")
    _require(bool(separator) and head in {path+" is active.", path+" is active and is in use."},
             "Wrong operation mapper status")
    return parse_crypt_status(MAPPER_PATH + head[len(path):] + "\n" + rest)


@dataclass(frozen=True)
class MapperInfo:
    device: Device
    uuid: str
    sectors: int
    readonly: int
    suspended: int
    slaves: tuple[Device, ...]
    holders: tuple[Device, ...]
    mounts: int
    swaps: int
    crypt: CryptMetadata


@dataclass(frozen=True)
class Runtime:
    boot_id: str
    namespace: tuple[int, int]
    init_namespace: tuple[int, int]
    mapper: MapperInfo | None


class Kernel(Protocol):
    def sample(self, operation: str) -> Runtime: ...
    def create(self, loop_fd: int, number: int, capacity: int, operation: str) -> None: ...
    def remove(self, operation: str) -> None: ...


class _Plain(ctypes.Structure):
    _fields_ = [("hash", ctypes.c_char_p), ("offset", ctypes.c_uint64),
                ("skip", ctypes.c_uint64), ("size", ctypes.c_uint64),
                ("sector_size", ctypes.c_uint32)]


_LOG = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _silent_log(_level: int, _message: int, _user: int) -> None:
    # Never decode native diagnostics that might contain implementation details.
    return None


class LinuxMapperKernel:
    """Fixed PLAIN AES-XTS profile; no table/key export or forced deactivation."""
    def _devices(self, name: str) -> tuple[Device, ...]:
        found = []
        for item in sorted(Path("/sys/block").glob("dm-*")):
            if _text(str(item/"dm/name")).strip() == name:
                found.append(Device.parse(_text(str(item/"dev")).strip()))
        _require(len(found) <= 1, "Ambiguous device-mapper name")
        return tuple(found)

    def sample(self, operation: str) -> Runtime:
        name = mapper_name(operation)
        before = self._devices(name)
        own, init = os.stat("/proc/self/ns/mnt"), os.stat("/proc/1/ns/mnt")
        boot = _text("/proc/sys/kernel/random/boot_id").strip()
        mapper = None
        if not before:
            _require(not os.path.lexists("/dev/mapper/"+name), "Mapper node exists without independent sysfs identity")
        else:
            device = before[0]
            root = "/sys/dev/block/" + device.label()
            def quantity(relative: str) -> int:
                value = _text(root+"/"+relative).strip()
                _require(value.isdecimal(), "Invalid mapper quantity")
                return int(value)
            def members(relative: str) -> tuple[Device, ...]:
                values = tuple(sorted(Device.parse(_text(str(p/"dev")).strip()) for p in Path(root+"/"+relative).iterdir()))
                _require(len(values) <= 64, "Unexpected mapper graph size")
                return values
            result = subprocess.run(["/usr/sbin/cryptsetup", "status", name],
                                    capture_output=True, text=True, timeout=5, check=False,
                                    env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL":"C"})
            _require(result.returncode == 0 and not result.stderr.strip(), "Mapper metadata not positively available")
            mounts = parse_mountinfo(_text("/proc/self/mountinfo"))
            swaps = parse_swaps(_text("/proc/swaps"))
            swap_count = 0
            for swap in swaps:
                if swap.kind == "partition":
                    info = os.stat(swap.path)
                    _require(stat.S_ISBLK(info.st_mode), "Swap block identity unavailable")
                    swap_count += int(Device.number(info.st_rdev) == device)
            mapper = MapperInfo(device, _text(root+"/dm/uuid").strip(), quantity("size"),
                                quantity("ro"), quantity("dm/suspended"), members("slaves"), members("holders"),
                                sum(m.device == device for m in mounts), swap_count, parse_mapper_status(result.stdout, operation))
        _require(self._devices(name) == before, "Mapper identity changed during observation")
        return Runtime(boot, (own.st_dev, own.st_ino), (init.st_dev, init.st_ino), mapper)

    @staticmethod
    def _library() -> Any:
        lib = ctypes.CDLL("libcryptsetup.so.12", use_errno=True)
        lib.crypt_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p]
        lib.crypt_init.restype = ctypes.c_int
        lib.crypt_set_log_callback.argtypes = [ctypes.c_void_p, _LOG, ctypes.c_void_p]
        lib.crypt_set_log_callback.restype = None
        lib.crypt_set_debug_level.argtypes = [ctypes.c_int]
        lib.crypt_set_debug_level.restype = None
        lib.crypt_format.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                                    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.c_void_p]
        lib.crypt_format.restype = ctypes.c_int
        lib.crypt_activate_by_volume_key.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        lib.crypt_activate_by_volume_key.restype = ctypes.c_int
        lib.crypt_free.argtypes = [ctypes.c_void_p]
        lib.crypt_free.restype = None
        lib.crypt_set_debug_level(0)
        return lib

    def create(self, loop_fd: int, number: int, capacity: int, operation: str) -> None:
        _require(os.geteuid() == 0, "Native mapper creation requires root in the attested kernel")
        _require(type(number) is int and 0 <= number < 1024 and type(capacity) is int
                 and capacity >= 8192 and capacity % 4096 == 0, "Explicit bounded geometry required")
        info = os.fstat(loop_fd)
        _require(stat.S_ISBLK(info.st_mode) and Device.number(info.st_rdev) == Device(7, number), "Wrong loop descriptor")
        _require(self.sample(operation).mapper is None, "Existing mapper cannot be adopted or rekeyed")
        disable_process_dumps()
        lib = self._library()
        context = ctypes.c_void_p()
        callback = _LOG(_silent_log)
        try:
            _require(lib.crypt_init(ctypes.byref(context), f"/proc/self/fd/{loop_fd}".encode()) == 0,
                     "Crypt context could not bind the retained loop")
            lib.crypt_set_log_callback(context, callback, None)
            params = _Plain(None, 0, 0, capacity//512, 512)
            _require(ctypes.sizeof(params) == 40, "Native PLAIN ABI differs")
            _require(lib.crypt_format(context, b"PLAIN", b"aes", b"xts-plain64", None,
                                     None, 64, ctypes.byref(params)) == 0, "Native PLAIN profile not accepted")
            with LockedKey() as key:
                def activate(pointer: ctypes.c_void_p, size: int) -> None:
                    result = lib.crypt_activate_by_volume_key(context, mapper_name(operation).encode(), pointer, size, 0)
                    _require(result == 0, "Native mapper activation uncertain; no automatic retry")
                key.use(activate)
        finally:
            if context.value:
                lib.crypt_free(context)

    def remove(self, operation: str) -> None:
        _require(os.geteuid() == 0, "Native mapper removal requires root in the attested kernel")
        sample = self.sample(operation)
        _require(sample.mapper is not None and sample.mapper.uuid == mapper_uuid(operation)
                 and not sample.mapper.holders and sample.mapper.mounts == sample.mapper.swaps == 0,
                 "Unowned or in-use mapper removal denied")
        # libcryptsetup retries EBUSY internally even with deactivation flags
        # zero. Use one key-free libdevmapper removal task instead; never enable
        # retry_remove or deferred_remove. Preserve its native errno.
        lib = ctypes.CDLL("libdevmapper.so.1.02.1", use_errno=True)
        lib.dm_task_create.argtypes = [ctypes.c_int]
        lib.dm_task_create.restype = ctypes.c_void_p
        for method in ("dm_task_set_name", "dm_task_set_uuid"):
            function = getattr(lib, method)
            function.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            function.restype = ctypes.c_int
        for method in ("dm_task_run", "dm_task_get_errno"):
            function = getattr(lib, method)
            function.argtypes = [ctypes.c_void_p]
            function.restype = ctypes.c_int
        lib.dm_task_destroy.argtypes = [ctypes.c_void_p]
        lib.dm_task_destroy.restype = None
        lib.dm_task_update_nodes.argtypes = []
        lib.dm_task_update_nodes.restype = None
        task = lib.dm_task_create(2)  # DM_DEVICE_REMOVE, not REMOVE_ALL
        _require(bool(task), "Native mapper removal task unavailable")
        try:
            # The exact UUID was independently checked above. Name lookup is
            # needed for libdevmapper to retire its node too; UUID-only removal
            # leaves an alias behind on a guest without udev. No simultaneous
            # name+UUID selector is supported. Frozen-writer context is required
            # across this check/call, not protection against a root ABA attack.
            _require(lib.dm_task_set_name(task, mapper_name(operation).encode()) == 1,
                     "Exact operation-name removal not accepted")
            if lib.dm_task_run(task) != 1:
                raise OSError(lib.dm_task_get_errno(task), "Single mapper removal did not complete")
            lib.dm_task_update_nodes()
        finally:
            lib.dm_task_destroy(task)


class MapperAdapter:
    """One mapper journal; parent loop/backing lifetimes are held independently."""
    def __init__(self, loop: LoopAdapter, parent: Path, *, kernel: Kernel | None = None):
        self.loop, self.parent, self.kernel = loop, parent, kernel or LinuxMapperKernel()
        self.operation, self.bound = loop.operation, loop.context()
        self.parent_fd = self.lock_fd = self.bundle_fd = -1
        self.journal: Journal | None = None
        try:
            self._loop_owned()
            self.parent_fd = _open_dir(parent)
            self.parent_identity = _dir_identity(self.parent_fd, private=True)
            self.lock_fd = os.open(".mapper-owner.lock", os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,
                                   0o600, dir_fd=self.parent_fd)
            lock = os.fstat(self.lock_fd)
            self._lock_ok(lock)
            self.lock_identity = (lock.st_dev, lock.st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.parent_fd)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _lock_ok(value: os.stat_result) -> None:
        _require(stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid()
                 and stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1 and value.st_size == 0,
                 "Unsafe mapper operation lock")

    def _loop_owned(self) -> None:
        loop = self.loop
        _require(loop.context() == self.bound and loop.journal is not None, "Accepted loop journal required")
        assert loop.journal is not None
        _require(loop.journal.state().phase == "applied", "Loop is not finalized")
        proof = loop.observe(loop.step, self.operation)
        _require(proof.identity_verified and proof.owned_by_operation and proof.fingerprint == loop.step.after_sha256,
                 "Operation does not own the published loop")

    @classmethod
    def prepare(cls, loop: LoopAdapter, parent: Path, *, kernel: Kernel | None = None) -> Self:
        adapter = cls(loop, parent, kernel=kernel)
        try:
            sample = adapter.kernel.sample(adapter.operation)
            adapter._shape(sample)
            source = loop._sample()
            _require(source.namespace == sample.namespace and sample.mapper is None
                     and not source.holders and source.mounts == source.swaps == 0,
                     "Loop or mapper already consumed")
            os.mkdir(adapter.operation, mode=0o700, dir_fd=adapter.parent_fd)
            os.fsync(adapter.parent_fd)
            adapter.bundle_fd = os.open(adapter.operation, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,
                                        dir_fd=adapter.parent_fd)
            assert loop.journal is not None
            body = {"schema":1, "operation":adapter.operation, "context":asdict(adapter.bound),
                    "parent":adapter.parent_identity, "bundle":_dir_identity(adapter.bundle_fd, private=True),
                    "lock":list(adapter.lock_identity), "loop_binding":loop.binding_hash,
                    "loop_plan":_digest(asdict(loop.journal.plan)), "namespace":list(sample.namespace),
                    "number":loop.number, "capacity":loop.binding["capacity"],
                    "name":mapper_name(adapter.operation), "uuid":mapper_uuid(adapter.operation)}
            _write_new(adapter.bundle_fd, "binding.json", json.dumps(body, sort_keys=True).encode()+b"\n", 0o600)
            adapter._load()
            _require(adapter._sample().mapper is None, "Baseline changed while binding mapper")
            return adapter
        except BaseException:
            adapter.close()
            raise

    @classmethod
    def load(cls, loop: LoopAdapter, parent: Path, *, kernel: Kernel | None = None) -> Self:
        adapter = cls(loop, parent, kernel=kernel)
        try:
            adapter.bundle_fd = os.open(adapter.operation, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,
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
        assert self.loop.journal is not None
        _require(isinstance(body, dict) and set(body) == {"schema","operation","context","parent","bundle","lock", "loop_binding","loop_plan","namespace","number","capacity","name","uuid"}, "Invalid mapper binding fields")
        _require(type(body["schema"]) is int and body["schema"] == 1 and body["operation"] == self.operation
                 and BoundContext(**body["context"]) == self.bound and body["parent"] == self.parent_identity
                 and body["bundle"] == _dir_identity(self.bundle_fd, private=True) and body["lock"] == list(self.lock_identity)
                 and body["loop_binding"] == self.loop.binding_hash and body["loop_plan"] == _digest(asdict(self.loop.journal.plan))
                 and type(body["number"]) is int and body["number"] == self.loop.number
                 and type(body["capacity"]) is int and body["capacity"] == self.loop.binding["capacity"]
                 and body["name"] == mapper_name(self.operation) and body["uuid"] == mapper_uuid(self.operation)
                 and isinstance(body["namespace"], list) and len(body["namespace"]) == 2
                 and all(type(x) is int and x > 0 for x in body["namespace"]), "Mapper binding differs from owned parents")
        self.binding, self.binding_hash = body, hashlib.sha256(raw).hexdigest()
        self.step = BoundStep(STEP, _digest({"binding":self.binding_hash, "active":False}),
                             _digest({"binding":self.binding_hash, "active":True}))
        self._identity()

    def _identity(self) -> None:
        _require(min(self.parent_fd, self.bundle_fd, self.lock_fd) >= 0, "Closed mapper adapter")
        self._loop_owned()
        fd = _open_dir(self.parent)
        try:
            _require(_dir_identity(fd, private=True) == self.parent_identity, "Mapper state parent changed")
        finally:
            os.close(fd)
        lock = os.stat(".mapper-owner.lock", dir_fd=self.parent_fd, follow_symlinks=False)
        self._lock_ok(lock)
        _require((lock.st_dev, lock.st_ino) == self.lock_identity, "Mapper lock replaced")
        bundle = os.stat(self.operation, dir_fd=self.parent_fd, follow_symlinks=False)
        _require(stat.S_ISDIR(bundle.st_mode) and (bundle.st_dev, bundle.st_ino) ==
                 (self.binding["bundle"]["device"],self.binding["bundle"]["inode"])
                 and _dir_identity(self.bundle_fd, private=True) == self.binding["bundle"], "Mapper bundle replaced")
        identity, raw = _file(self.bundle_fd, "binding.json", private=True)
        _require(identity == self.binding_identity and hashlib.sha256(raw).hexdigest() == self.binding_hash
                 and os.listdir(self.bundle_fd) == ["binding.json"], "Mapper binding changed or incomplete")

    def context(self) -> BoundContext:
        self._identity()
        return self.bound

    def _shape(self, sample: Runtime) -> None:
        _require(isinstance(sample, Runtime) and sample.boot_id == self.bound.boot_id
                 and isinstance(sample.namespace, tuple) and len(sample.namespace) == 2
                 and all(type(x) is int and x > 0 for x in sample.namespace)
                 and sample.namespace == sample.init_namespace
                 and (sample.mapper is None or isinstance(sample.mapper, MapperInfo)), "Invalid mapper boot or namespace evidence")

    def _sample(self) -> Runtime:
        self._identity()
        start = time.monotonic()
        sample = self.kernel.sample(self.operation)
        self._shape(sample)
        _require(list(sample.namespace) == self.binding["namespace"], "Mapper namespace changed")
        source = self.loop._sample()
        _require(source.namespace == sample.namespace and source.mounts == source.swaps == 0,
                 "Underlying loop namespace differs or has a direct consumer")
        info = sample.mapper
        if info is None:
            _require(source.holders == (), "No mapper named but underlying loop still held")
        else:
            crypt = info.crypt
            _require(isinstance(info.device, Device) and info.uuid == self.binding["uuid"]
                     and type(info.sectors) is int and info.sectors*512 == self.binding["capacity"]
                     and type(info.readonly) is int and type(info.suspended) is int
                     and info.readonly == info.suspended == 0
                     and info.slaves == (Device(7,self.loop.number),)
                     and source.holders == (info.device.label(),)
                     and isinstance(info.holders, tuple) and all(isinstance(x,Device) for x in info.holders)
                     and type(info.mounts) is int and info.mounts >= 0 and type(info.swaps) is int and info.swaps >= 0,
                     "Foreign mapper identity, geometry, state or graph")
            _require(isinstance(crypt,CryptMetadata) and crypt.kind == "PLAIN" and crypt.cipher == "aes-xts-plain64"
                     and crypt.key_bits == 512 and crypt.sector_size == 512 and crypt.offset_sectors == 0
                     and crypt.size_sectors == info.sectors and crypt.mode == "read/write" and crypt.flags == ()
                     and crypt.device_path == f"/dev/loop{self.loop.number}", "Cipher profile differs")
        _require(0 <= time.monotonic()-start <= 15, "Mapper observation window exceeded")
        self._identity()
        return sample

    def attach(self, journal: Journal) -> None:
        _require(journal.plan.operation == self.operation and journal.plan.context == self.bound
                 and journal.plan.steps == (self.step,), "Exact single-mapper journal required")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        _require(step == self.step and operation == self.operation, "Foreign mapper step")
        active = self._sample().mapper is not None
        owned = False
        if self.journal is not None:
            state = self.journal.state()
            owned = state.applied == 1 or state.pending == ("apply",0)
        return Observation(step.after_sha256 if active else step.before_sha256, True, active and owned)

    def _effect(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        _require(self.journal is not None and step == self.step and operation == self.operation, "Attached mapper journal required")
        assert self.journal is not None
        _require(self.journal.state().pending == ("undo" if undo else "apply",0), "Durable mapper intent required")
        first, second = self._sample(), self._sample()
        _require(first == second and (first.mapper is not None) == undo, "Mapper state changed or already transitioned")
        if undo:
            assert first.mapper is not None
            _require(first.mapper.holders == () and first.mapper.mounts == first.mapper.swaps == 0,
                     "Mapper still has consumers; no forced/deferred removal")
        self.context()
        if undo:
            self.kernel.remove(operation)
        else:
            self.kernel.create(self.loop.fd,self.loop.number,self.binding["capacity"],operation)
        self.context()
        _require((self._sample().mapper is None) == undo, "Native return did not establish expected mapper state")

    def apply(self, step: BoundStep, operation: str) -> None:
        self._effect(step,operation,undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._effect(step,operation,undo=True)

    def close(self) -> None:
        for attribute in ("bundle_fd","lock_fd","parent_fd"):
            fd = getattr(self,attribute)
            if fd >= 0:
                os.close(fd)
                setattr(self,attribute,-1)

    def __enter__(self) -> Self:
        return self

    def __exit__(self,*args: object) -> None:
        self.close()
