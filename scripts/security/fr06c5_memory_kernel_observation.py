"""C5E4 read-only Linux memory-resource evidence; never a mutation authority.

Join active swaps -> dm-crypt metadata -> a single loop -> a pinned backing
inode, and join the visible /tmp inode/device to its exact mountinfo record.
Names, a missing SWAPSPACE2 signature, or a command exit code are insufficient.
Two matching observations detect drift, not ABA or noncooperating writers.
Caller-supplied expectations need independent creation/ownership evidence before
any future adapter may mutate a resource. No such adapter or activation CLI is
shipped here. Key bytes, dm tables and backing contents are never requested.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

MAX_TEXT = 1024 * 1024
MAPPER_NAME = "aionex-fr06c5-swap"
MAPPER_PATH = "/dev/mapper/" + MAPPER_NAME
LOOP_GET_STATUS64 = 0x4C05
LOOP_STRUCT = struct.Struct("=QQQQQIIII64s64s32sQQ")
_ESCAPE = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


class KernelEvidenceRejected(RuntimeError):
    """Unknown, malformed, incomplete or inconsistent resource evidence."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise KernelEvidenceRejected(message)


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _text(value: str, limit: int = MAX_TEXT) -> list[str]:
    _require(isinstance(value, str) and 0 < len(value) <= limit
             and "\x00" not in value and value.endswith("\n"), "Incomplete bounded text")
    return value.splitlines()


def _path(value: str) -> str:
    _require(isinstance(value, str) and value.startswith("/") and "\x00" not in value
             and not any(x in {".", ".."} for x in value.split("/"))
             and "//" not in value and (value == "/" or not value.endswith("/")), "Ambiguous absolute path")
    return value


def _unescape(value: str) -> str:
    out, pos = [], 0
    while pos < len(value):
        if value[pos] == "\\":
            code = value[pos + 1:pos + 4]
            _require(code in _ESCAPE, "Unsupported kernel path escape")
            out.append(_ESCAPE[code])
            pos += 4
        else:
            out.append(value[pos])
            pos += 1
    return "".join(out)


@dataclass(frozen=True, order=True)
class Device:
    major: int
    minor: int

    def __post_init__(self) -> None:
        _require(_integer(self.major) and _integer(self.minor), "Invalid block device number")

    @classmethod
    def parse(cls, value: str) -> Device:
        _require(re.fullmatch(r"[0-9]+:[0-9]+", value) is not None, "Invalid kernel device field")
        a, b = value.split(":")
        return cls(int(a), int(b))

    @classmethod
    def number(cls, value: int) -> Device:
        return cls(os.major(value), os.minor(value))

    def label(self) -> str:
        return f"{self.major}:{self.minor}"


@dataclass(frozen=True)
class FileIdentity:
    device: Device
    inode: int
    mode: int
    uid: int
    gid: int
    links: int
    size: int

    @classmethod
    def of(cls, info: os.stat_result) -> FileIdentity:
        return cls(Device.number(info.st_dev), info.st_ino, info.st_mode,
                   info.st_uid, info.st_gid, info.st_nlink, info.st_size)

    def require_backing(self, size: int) -> None:
        _require(stat.S_ISREG(self.mode) and stat.S_IMODE(self.mode) == 0o600
                 and self.uid == 0 and self.gid == 0 and self.links == 1
                 and self.inode > 0 and self.size == size, "Backing identity or ownership differs")


@dataclass(frozen=True)
class Swap:
    path: str
    kind: str
    size: int
    used: int
    priority: int

    def __post_init__(self) -> None:
        _path(self.path)
        _require(self.kind in {"file", "partition"} and _integer(self.size, 1)
                 and _integer(self.used) and self.used <= self.size
                 and type(self.priority) is int and -32768 <= self.priority <= 32767,
                 "Invalid typed swap record")


def parse_swaps(value: str) -> tuple[Swap, ...]:
    lines = _text(value)
    _require(lines[0].split() == ["Filename", "Type", "Size", "Used", "Priority"], "Invalid swap header")
    rows = []
    for line in lines[1:]:
        fields = line.split()
        _require(len(fields) == 5 and fields[1] in {"file", "partition"}, "Incomplete swap record")
        _require(all(re.fullmatch(r"[0-9]+", x) for x in fields[2:4])
                 and re.fullmatch(r"-?[0-9]+", fields[4]) is not None, "Invalid swap quantities")
        size, used, priority = (int(x) for x in fields[2:])
        _require(size > 0 and 0 <= used <= size and -32768 <= priority <= 32767, "Invalid swap capacity")
        path = _path(_unescape(fields[0]))
        _require(not path.endswith(" (deleted)"), "Unlinked swap resource")
        rows.append(Swap(path, fields[1], size * 1024, used * 1024, priority))
    _require(len({r.path for r in rows}) == len(rows), "Duplicate swap records")
    return tuple(rows)


def _options(value: str) -> tuple[str, ...]:
    items = value.split(",")
    _require(all(items) and len({x.split("=", 1)[0] for x in items}) == len(items), "Ambiguous mount options")
    _require(not {"rw", "ro"}.issubset(items), "Contradictory mount access")
    return tuple(sorted(items))


@dataclass(frozen=True)
class Mount:
    mount_id: int
    parent_id: int
    device: Device
    root: str
    target: str
    options: tuple[str, ...]
    optional: tuple[str, ...]
    kind: str
    source: str
    super_options: tuple[str, ...]


def _mount_root(value: str, kind: str) -> str:
    root = _unescape(value)
    if root.startswith("/"):
        return _path(root)
    # nsfs bind mounts expose a namespace handle, not a filesystem pathname.
    # Preserve it as an opaque root; it can never satisfy the /tmp root gate.
    _require(kind == "nsfs" and re.fullmatch(r"[a-z_]+:\[[0-9]+\]", root) is not None,
             "Unrecognized non-path mount root")
    return root


def parse_mountinfo(value: str) -> tuple[Mount, ...]:
    rows = []
    for line in _text(value):
        fields = line.split()
        _require(fields.count("-") == 1, "Missing or ambiguous mount separator")
        sep = fields.index("-")
        _require(sep >= 6 and len(fields) == sep + 4, "Incomplete mount record")
        _require(all(re.fullmatch(r"[0-9]+", x) for x in fields[:2]), "Invalid mount IDs")
        mount_id, parent_id = int(fields[0]), int(fields[1])
        _require(mount_id > 0 and parent_id >= 0, "Invalid mount ID range")
        rows.append(Mount(mount_id, parent_id, Device.parse(fields[2]),
                          _mount_root(fields[3], fields[sep + 1]), _path(_unescape(fields[4])),
                          _options(fields[5]), tuple(fields[6:sep]), fields[sep + 1],
                          _unescape(fields[sep + 2]), _options(fields[sep + 3])))
    _require(len({r.mount_id for r in rows}) == len(rows), "Repeated mount ID")
    return tuple(rows)


def _capacity(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([kKmMgG]?)", value)
    _require(match is not None, "Unknown tmpfs size unit")
    assert match is not None
    return int(match[1]) * {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[match[2].lower()]


@dataclass(frozen=True)
class CryptMetadata:
    kind: str
    cipher: str
    key_bits: int
    sector_size: int
    device_path: str
    offset_sectors: int
    size_sectors: int
    mode: str
    flags: tuple[str, ...]


def parse_crypt_status(value: str) -> CryptMetadata:
    lines = _text(value, 16384)
    _require(lines[0] in {MAPPER_PATH + " is active.", MAPPER_PATH + " is active and is in use."}, "Mapping not positively active")
    allowed = {"type", "cipher", "keysize", "key location", "sector size", "device", "loop", "offset", "size", "mode", "flags"}
    required = {"type", "cipher", "keysize", "sector size", "device", "offset", "size", "mode"}
    fields = {}
    for line in lines[1:]:
        _require(line.startswith("  ") and ":" in line, "Malformed crypt metadata")
        name, content = (x.strip() for x in line.split(":", 1))
        _require(name in allowed and name not in fields and bool(content), "Unknown or repeated crypt metadata")
        fields[name] = content
    _require(required.issubset(fields), "Incomplete crypt metadata")

    def quantity(key: str, suffix: str) -> int:
        match = re.fullmatch(r"([0-9]+) " + suffix, fields[key])
        _require(match is not None, "Invalid crypt size or offset")
        assert match is not None
        return int(match[1])

    _require(re.fullmatch(r"[0-9]+", fields["sector size"]) is not None, "Invalid sector size")
    _require(fields.get("key location", "dm-crypt") in {"dm-crypt", "keyring"}, "Unknown key location metadata")
    return CryptMetadata(fields["type"], fields["cipher"], quantity("keysize", "bits"),
                         int(fields["sector size"]), _path(fields["device"]),
                         quantity("offset", "sectors"), quantity("size", "sectors"),
                         fields["mode"], tuple(fields.get("flags", "").split()))


@dataclass(frozen=True)
class LoopMetadata:
    backing_device: Device
    backing_inode: int
    offset: int
    size_limit: int
    number: int
    flags: int


def decode_loop_status(value: bytes | bytearray) -> LoopMetadata:
    _require(len(value) == LOOP_STRUCT.size == 232, "Truncated loop status structure")
    fields = LOOP_STRUCT.unpack(value)
    _require(fields[6] == 0 and fields[7] == 0, "Legacy loop encryption is outside the reviewed graph")
    return LoopMetadata(Device.number(fields[0]), fields[1], fields[3], fields[4], fields[5], fields[8])


def read_loop_status(fd: int) -> LoopMetadata:
    """Only LOOP_GET_STATUS64; never return filename hints or key buffers."""
    info = os.fstat(fd)
    _require(stat.S_ISBLK(info.st_mode), "Loop query requires a block-device descriptor")
    buffer = bytearray(LOOP_STRUCT.size)
    try:
        fcntl.ioctl(fd, LOOP_GET_STATUS64, buffer, True)
        return decode_loop_status(buffer)
    finally:
        buffer[:] = b"\x00" * len(buffer)


class PinnedBacking:
    """Retain an owned file descriptor; never read the backing's contents."""
    def __init__(self, path: Path):
        _path(str(path))
        self.path, self.fd = path, -1
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in path.parts[1:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                os.close(directory)
                directory = new
            self.fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
            _require(stat.S_ISREG(os.fstat(self.fd).st_mode), "Backing must be regular")
        except BaseException:
            self.close()
            raise
        finally:
            os.close(directory)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def identity(self) -> FileIdentity:
        _require(self.fd >= 0, "Backing descriptor closed")
        # Re-open the full path without symlinks, then compare to retained FD.
        current = PinnedBacking(self.path)
        try:
            pinned = FileIdentity.of(os.fstat(self.fd))
            _require(pinned == FileIdentity.of(os.fstat(current.fd)), "Backing pathname now resolves to another inode")
            return pinned
        finally:
            current.close()


@dataclass(frozen=True)
class Expectation:
    boot_id: str
    mount_namespace: tuple[int, int]
    mapper_device: Device
    mapper_uuid: str
    loop_device: Device
    loop_number: int
    backing: FileIdentity
    size_bytes: int
    sector_bytes: int
    tmp_mount_id: int
    tmp_device: Device
    tmp_capacity_bytes: int

    def __post_init__(self) -> None:
        _require(isinstance(self.boot_id, str) and str(UUID(self.boot_id)) == self.boot_id, "Canonical boot ID required")
        _require(isinstance(self.mount_namespace, tuple) and len(self.mount_namespace) == 2
                 and all(_integer(x, 1) for x in self.mount_namespace), "Pinned mount namespace required")
        _require(isinstance(self.mapper_device, Device) and isinstance(self.loop_device, Device)
                 and isinstance(self.tmp_device, Device) and isinstance(self.backing, FileIdentity), "Typed identities required")
        _require(isinstance(self.mapper_uuid, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", self.mapper_uuid) is not None, "Exact dm UUID required")
        _require(_integer(self.loop_number) and self.loop_device == Device(7, self.loop_number), "Exact loop number required")
        _require(_integer(self.size_bytes, 4096) and self.size_bytes % 4096 == 0
                 and type(self.sector_bytes) is int and self.sector_bytes in {512, 4096}, "Invalid mapped size or sector profile")
        _require(_integer(self.tmp_mount_id, 1) and _integer(self.tmp_capacity_bytes, 4096), "Exact tmpfs identity and capacity required")
        self.backing.require_backing(self.size_bytes)


@dataclass(frozen=True)
class Sample:
    boot_id: str
    namespace: tuple[int, int]
    init_namespace: tuple[int, int]
    mapper: Device
    dm_name: str
    dm_uuid: str
    dm_sectors: int
    dm_readonly: int
    dm_suspended: int
    dm_slaves: tuple[Device, ...]
    dm_holders: tuple[Device, ...]
    loop: Device
    loop_holders: tuple[Device, ...]
    loop_info: LoopMetadata
    backing: FileIdentity
    crypt: CryptMetadata
    swaps: tuple[Swap, ...]
    swap_devices: tuple[Device, ...]
    mounts: tuple[Mount, ...]
    tmp: FileIdentity
    page_size: int


def validate_sample(sample: Sample, expected: Expectation) -> None:
    _require(type(sample.page_size) is int and sample.page_size == 4096, "Only the reviewed 4KiB page profile is accepted")
    _require(sample.boot_id == expected.boot_id and sample.namespace == sample.init_namespace == expected.mount_namespace, "Boot or mount namespace changed")
    _require(sample.mapper == expected.mapper_device and sample.dm_name == MAPPER_NAME
             and sample.dm_uuid == expected.mapper_uuid, "Mapper identity differs")
    _require(sample.dm_sectors * 512 == expected.size_bytes and sample.dm_readonly == 0
             and sample.dm_suspended == 0 and sample.dm_holders == (), "Mapper geometry or state unsafe")
    _require(sample.dm_slaves == (expected.loop_device,) and sample.loop == expected.loop_device
             and sample.loop_holders == (expected.mapper_device,), "Unexpected device graph or extra consumer")
    info = sample.loop_info
    _require(info.backing_device == expected.backing.device and info.backing_inode == expected.backing.inode
             and info.number == expected.loop_number and info.offset == 0 and info.size_limit in {0, expected.size_bytes}
             and info.flags in {0, 4, 16, 20}, "Loop does not match pinned backing geometry")
    _require(sample.backing == expected.backing, "Backing inode or metadata changed")
    crypt = sample.crypt
    _require(crypt.kind == "PLAIN" and crypt.cipher == "aes-xts-plain64" and crypt.key_bits == 512
             and crypt.sector_size == expected.sector_bytes and crypt.offset_sectors == 0
             and crypt.size_sectors * 512 == expected.size_bytes and crypt.mode == "read/write"
             and crypt.flags == () and crypt.device_path == f"/dev/loop{expected.loop_number}", "Crypt parameters or backing device do not match")
    _require(len(sample.swaps) == 1 and sample.swap_devices == (expected.mapper_device,)
             and sample.swaps[0].kind == "partition" and sample.swaps[0].size == expected.size_bytes - 4096,
             "Active swap is missing, extra, plaintext, aliased twice, or wrong size")
    matches = [m for m in sample.mounts if m.target == "/tmp"]
    _require(len(matches) == 1 and not any(m.target.startswith("/tmp/") for m in sample.mounts), "Stacked, missing or nested tmp mounts")
    mount = matches[0]
    _require(mount.mount_id == expected.tmp_mount_id and mount.device == expected.tmp_device
             and mount.root == "/" and mount.kind == "tmpfs" and mount.source == "tmpfs"
             and mount.optional == () and {"rw", "nodev", "nosuid"}.issubset(mount.options), "Tmp mount identity, origin, propagation or options differ")
    options = dict(x.split("=", 1) for x in mount.super_options if "=" in x)
    _require("rw" in mount.super_options and "size" in options
             and _capacity(options["size"]) == expected.tmp_capacity_bytes, "Tmpfs capacity differs")
    _require(sample.tmp.device == expected.tmp_device and stat.S_ISDIR(sample.tmp.mode)
             and stat.S_IMODE(sample.tmp.mode) == 0o1777 and sample.tmp.uid == sample.tmp.gid == 0, "Visible tmp directory does not match the mount")


def stable_pair(first: Sample, second: Sample, expected: Expectation) -> dict[str, object]:
    """Observe graph consistency only. No ownership/admission capability issued."""
    validate_sample(first, expected)
    validate_sample(second, expected)
    a, b = asdict(first), asdict(second)
    # Swap used bytes may change during normal use. No other field is ignored.
    for item in (a, b):
        item["swaps"] = tuple({k: v for k, v in x.items() if k != "used"} for x in item["swaps"])
    _require(a == b, "Kernel topology or identity changed between samples")
    digest = hashlib.sha256(json.dumps(a, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"kernel_graph_consistent": True, "resource_fingerprint": digest,
            "crypt_parameters_matched": True, "backing_inode_matched": True,
            "max_observed_swap_used_bytes": max(first.swaps[0].used, second.swaps[0].used),
            "independent_operation_ownership_verified": False, "writer_quiescence_verified": False,
            "random_key_generation_or_custody_verified": False, "host_boot_verified": False,
            "activation_authorized": False, "full_host_closure": False}


def require_swapoff_reserve(swaps: tuple[Swap, ...], available_bytes: int, reserve_bytes: int) -> None:
    _require(_integer(available_bytes) and _integer(reserve_bytes, 1), "Memory reserve unavailable")
    _require(available_bytes >= sum(s.used for s in swaps) + reserve_bytes, "Insufficient memory to remove active swap safely")


class Reader(Protocol):
    def text(self, path: str) -> str: ...
    def names(self, path: str) -> tuple[str, ...]: ...
    def device(self, path: str) -> Device: ...
    def namespace(self, pid: str) -> tuple[int, int]: ...
    def loop(self, path: str) -> LoopMetadata: ...
    def backing(self) -> FileIdentity: ...
    def tmp(self) -> FileIdentity: ...
    def crypt_status(self) -> str: ...
    def page_size(self) -> int: ...


class LinuxReader:
    """Fixed read-only operations. status output is parsed, never journaled raw."""
    def __init__(self, backing: PinnedBacking):
        self._backing = backing

    def text(self, path: str) -> str:
        _require(path.startswith(("/proc/", "/sys/")), "Kernel text path only")
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_TEXT + 1)
        _require(len(data) <= MAX_TEXT, "Kernel text exceeds bound")
        return data.decode("utf-8", errors="strict")

    def names(self, path: str) -> tuple[str, ...]:
        _require(path.startswith("/sys/dev/block/"), "Kernel device directory only")
        return tuple(sorted(os.listdir(path)))

    def device(self, path: str) -> Device:
        _path(path)
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            _require(stat.S_ISBLK(info.st_mode), "Swap/mapper identity requires a block device")
            _require(info.st_rdev == os.stat(path).st_rdev, "Named device changed during open")
            return Device.number(info.st_rdev)
        finally:
            os.close(fd)

    def namespace(self, pid: str) -> tuple[int, int]:
        _require(pid in {"self", "1"}, "Only current/init namespace identities")
        info = os.stat(f"/proc/{pid}/ns/mnt")
        return info.st_dev, info.st_ino

    def loop(self, path: str) -> LoopMetadata:
        _require(re.fullmatch(r"/dev/loop[0-9]+", path) is not None, "Exact loop path required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            return read_loop_status(fd)
        finally:
            os.close(fd)

    def backing(self) -> FileIdentity:
        return self._backing.identity()

    def tmp(self) -> FileIdentity:
        return FileIdentity.of(os.stat("/tmp", follow_symlinks=False))

    def page_size(self) -> int:
        return os.sysconf("SC_PAGE_SIZE")

    def crypt_status(self) -> str:
        result = subprocess.run(["/usr/sbin/cryptsetup", "status", MAPPER_NAME],
                                capture_output=True, text=True, timeout=5, check=False,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
        _require(result.returncode == 0 and not result.stderr.strip(), "Crypt metadata query failed")
        _require(len(result.stdout) <= 16384, "Crypt metadata exceeds bound")
        return result.stdout


def collect_sample(reader: Reader, expected: Expectation) -> Sample:
    """Fail on any missing read; do not substitute an empty graph."""
    def number(path: str) -> int:
        value = reader.text(path).strip()
        _require(re.fullmatch(r"[0-9]+", value) is not None, "Invalid sysfs quantity")
        return int(value)

    def devices(path: str) -> tuple[Device, ...]:
        names = reader.names(path)
        _require(len(names) <= 16 and all(re.fullmatch(r"[A-Za-z0-9_-]+", n) for n in names), "Unexpected graph names")
        return tuple(sorted(Device.parse(reader.text(path + "/" + n + "/dev").strip()) for n in names))

    dm = "/sys/dev/block/" + expected.mapper_device.label()
    loop = "/sys/dev/block/" + expected.loop_device.label()
    swaps = parse_swaps(reader.text("/proc/swaps"))
    # A file/plaintext swap cannot stand in for the block mapper.
    _require(len(swaps) == 1 and swaps[0].kind == "partition", "Unexpected active swap set")
    crypt = parse_crypt_status(reader.crypt_status())
    _require(crypt.device_path == f"/dev/loop{expected.loop_number}", "Unowned crypt backing path")
    return Sample(reader.text("/proc/sys/kernel/random/boot_id").strip(),
                  reader.namespace("self"), reader.namespace("1"), reader.device(MAPPER_PATH),
                  reader.text(dm + "/dm/name").strip(), reader.text(dm + "/dm/uuid").strip(),
                  number(dm + "/size"), number(dm + "/ro"), number(dm + "/dm/suspended"),
                  devices(dm + "/slaves"), devices(dm + "/holders"), reader.device(crypt.device_path),
                  devices(loop + "/holders"), reader.loop(crypt.device_path), reader.backing(), crypt,
                  swaps, tuple(reader.device(row.path) for row in swaps),
                  parse_mountinfo(reader.text("/proc/self/mountinfo")), reader.tmp(), reader.page_size())


def observe_pair(reader: Reader, expected: Expectation,
                 collect: Callable[[Reader, Expectation], Sample] = collect_sample,
                 clock: Callable[[], float] = time.monotonic) -> dict[str, object]:
    start = clock()
    first = collect(reader, expected)
    second = collect(reader, expected)
    elapsed = clock() - start
    _require(0 <= elapsed <= 15, "Kernel sampling window exceeded")
    result = stable_pair(first, second, expected)
    return {**result, "sampling_seconds": elapsed}
