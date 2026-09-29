"""Kernel evidence contracts on explicit fixtures and owned files, as nonroot.

No real mapper, loop device, swap, mount, cryptsetup action, network or secret.
Native checks only parse this test process's mountinfo and pin disposable files.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fr06_kernel_observation", ROOT / "scripts/security/fr06c5_memory_kernel_observation.py")
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
SIZE = 8 * 1024 ** 3
BOOT = "ffffffff-ffff-4fff-8fff-ffffffffffff"
DM = m.Device(253, 19)
LOOP = m.Device(7, 12)
TMP = m.Device(0, 191)
NS = (4, 4026531841)
SWAPS = f"Filename\t\tType\tSize\tUsed\tPriority\n/dev/dm-19 partition {(SIZE - 4096) // 1024} 0 -2\n"
MOUNTS = "20 1 8:1 / / rw,relatime - ext4 /dev/sda1 rw\n42 20 0:191 / /tmp rw,nosuid,nodev,relatime - tmpfs tmpfs rw,size=8388608k,inode64\n"
CRYPT = f"""/dev/mapper/aionex-fr06c5-swap is active and is in use.
  type:    PLAIN
  cipher:  aes-xts-plain64
  keysize: 512 bits
  key location: dm-crypt
  device:  /dev/loop12
  loop:    /var/lib/aionex/fr06-vaults/random-swap.backing
  sector size:  512
  offset:  0 sectors
  size:    {SIZE // 512} sectors
  mode:    read/write
"""


def fixture():
    backing = m.FileIdentity(m.Device(8, 1), 910001, stat.S_IFREG | 0o600, 0, 0, 1, SIZE)
    expected = m.Expectation(BOOT, NS, DM, "CRYPT-PLAIN-aionex-fr06c5-swap", LOOP, 12,
                             backing, SIZE, 512, 42, TMP, SIZE)
    loop = m.LoopMetadata(backing.device, backing.inode, 0, 0, 12, 4)
    sample = m.Sample(BOOT, NS, NS, DM, m.MAPPER_NAME, expected.mapper_uuid,
                      SIZE // 512, 0, 0, (LOOP,), (), LOOP, (DM,), loop, backing,
                      m.parse_crypt_status(CRYPT), m.parse_swaps(SWAPS), (DM,),
                      m.parse_mountinfo(MOUNTS), m.FileIdentity(TMP, 1, stat.S_IFDIR | 0o1777, 0, 0, 2, 40), 4096)
    return expected, sample


def test_joined_graph_accepts_only_identity_evidence_and_never_mutation_authority():
    expected, sample = fixture()
    result = m.stable_pair(sample, sample, expected)
    assert result["kernel_graph_consistent"] is True
    assert result["crypt_parameters_matched"] is True
    for field in ("independent_operation_ownership_verified", "writer_quiescence_verified",
                  "random_key_generation_or_custody_verified", "host_boot_verified", "activation_authorized", "full_host_closure"):
        assert result[field] is False
    assert len(result["resource_fingerprint"]) == 64


@pytest.mark.parametrize("field,value", [
    ("boot_id", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"), ("namespace", (4, 9)),
    ("init_namespace", (4, 9)), ("mapper", m.Device(253, 20)), ("dm_name", "wrong"),
    ("dm_uuid", "CRYPT-PLAIN-unowned"), ("dm_sectors", 12), ("dm_readonly", 1),
    ("dm_suspended", 1), ("dm_slaves", ()), ("dm_slaves", (LOOP, m.Device(7, 13))),
    ("dm_holders", (m.Device(253, 33),)), ("loop", m.Device(7, 13)),
    ("loop_holders", ()), ("loop_holders", (DM, m.Device(253, 33))),
    ("swaps", ()), ("swap_devices", (m.Device(8, 1),)),
    ("swap_devices", (DM, DM)), ("page_size", 65536),
])
def test_mapper_name_alone_cannot_prove_the_resource_graph(field, value):
    expected, sample = fixture()
    with pytest.raises(m.KernelEvidenceRejected):
        m.validate_sample(dataclasses.replace(sample, **{field: value}), expected)


@pytest.mark.parametrize("field,value", [
    ("backing_device", m.Device(8, 2)), ("backing_inode", 910002), ("offset", 4096),
    ("size_limit", 512), ("number", 13), ("flags", 1), ("flags", 8), ("flags", 128),
])
def test_loop_ioctl_identity_not_filename_hint(field, value):
    expected, sample = fixture()
    bad = dataclasses.replace(sample.loop_info, **{field: value})
    with pytest.raises(m.KernelEvidenceRejected):
        m.validate_sample(dataclasses.replace(sample, loop_info=bad), expected)


@pytest.mark.parametrize("field,value", [
    ("kind", "LUKS2"), ("cipher", "null"), ("cipher", "aes-cbc-plain"),
    ("key_bits", 256), ("sector_size", 4096), ("device_path", "/dev/loop13"),
    ("offset_sectors", 8), ("size_sectors", 8), ("mode", "readonly"),
    ("flags", ("discards",)),
])
def test_cipher_geometry_and_flags_are_required(field, value):
    expected, sample = fixture()
    with pytest.raises(m.KernelEvidenceRejected):
        m.validate_sample(dataclasses.replace(sample, crypt=dataclasses.replace(sample.crypt, **{field: value})), expected)


@pytest.mark.parametrize("field,value", [
    ("inode", 99), ("device", m.Device(8, 2)), ("uid", 1000), ("gid", 1000),
    ("links", 2), ("size", SIZE // 2), ("mode", stat.S_IFREG | 0o644),
])
def test_replaced_or_exposed_backing_is_not_accepted(field, value):
    expected, sample = fixture()
    with pytest.raises(m.KernelEvidenceRejected):
        m.validate_sample(dataclasses.replace(sample, backing=dataclasses.replace(sample.backing, **{field: value})), expected)


@pytest.mark.parametrize("field,value", [
    ("mount_id", 43), ("device", m.Device(0, 192)), ("root", "/subdir"),
    ("kind", "ext4"), ("source", "other-tmpfs"), ("optional", ("shared:1",)),
    ("options", ("rw", "nosuid")), ("options", ("ro", "nosuid", "nodev")),
    ("super_options", ("rw", "size=1k")),
])
def test_visible_tmpfs_must_match_its_exact_mount_record(field, value):
    expected, sample = fixture()
    mounts = (sample.mounts[0], dataclasses.replace(sample.mounts[1], **{field: value}))
    with pytest.raises(m.KernelEvidenceRejected):
        m.validate_sample(dataclasses.replace(sample, mounts=mounts), expected)


@pytest.mark.parametrize("kind", ["stacked", "nested", "missing", "visible-device", "visible-symlink", "visible-mode", "visible-owner"])
def test_visible_tmp_and_mount_topology_cannot_disagree(kind):
    expected, sample = fixture()
    if kind == "stacked":
        sample = dataclasses.replace(sample, mounts=(*sample.mounts, dataclasses.replace(sample.mounts[1], mount_id=44)))
    elif kind == "nested":
        sample = dataclasses.replace(sample, mounts=(*sample.mounts, dataclasses.replace(sample.mounts[1], mount_id=44, target="/tmp/child")))
    elif kind == "missing":
        sample = dataclasses.replace(sample, mounts=sample.mounts[:1])
    else:
        field, value = {"visible-device": ("device", m.Device(0, 192)), "visible-symlink": ("mode", stat.S_IFLNK | 0o777),
                        "visible-mode": ("mode", stat.S_IFDIR | 0o777), "visible-owner": ("uid", 1000)}[kind]
        sample = dataclasses.replace(sample, tmp=dataclasses.replace(sample.tmp, **{field: value}))
    with pytest.raises(m.KernelEvidenceRejected):
        m.validate_sample(sample, expected)


@pytest.mark.parametrize("text", ["", "Filename Type Size Used Priority", "wrong header\n",
    "Filename Type Size Used Priority\n/dev/a partition 4 5 -2\n",
    "Filename Type Size Used Priority\n/dev/a partition -4 0 -2\n",
    "Filename Type Size Used Priority\n/dev/a partition 0 0 -2\n",
    "Filename Type Size Used Priority\n/dev/a partition 4 0 99999\n",
    "Filename Type Size Used Priority\n/dev/a unknown 4 0 -2\n",
    "Filename Type Size Used Priority\n/dev/a partition 4 0 -2 extra\n",
    "Filename Type Size Used Priority\n/dev/../a partition 4 0 -2\n",
    "Filename Type Size Used Priority\n/dev/a\\999 partition 4 0 -2\n",
    "Filename Type Size Used Priority\n/dev/a\\040(deleted) partition 4 0 -2\n",
    "Filename Type Size Used Priority\n/dev/a partition 4 0 -2\n/dev/a partition 4 0 -2\n",
])
def test_swap_parser_rejects_partial_or_ambiguous_data(text):
    with pytest.raises(m.KernelEvidenceRejected):
        m.parse_swaps(text)


def test_kernel_path_escaping_is_not_whitespace_splitting():
    data = "Filename Type Size Used Priority\n/a\\040b\\134c file 4 0 -2\n"
    assert m.parse_swaps(data)[0].path == "/a b\\c"
    assert m.parse_swaps("Filename Type Size Used Priority\n") == ()
    text = "42 20 8:1 /a\\040b /test\\040path rw - ext4 /dev/a rw\n"
    row = m.parse_mountinfo(text)[0]
    assert (row.root, row.target) == ("/a b", "/test path")


@pytest.mark.parametrize("text", ["", MOUNTS.rstrip("\n"), MOUNTS + MOUNTS,
    "42 20 0:191 / /tmp rw,nosuid,nodev tmpfs tmpfs rw\n",
    "42 20 0:191 / /tmp rw,rw - tmpfs tmpfs rw\n",
    "42 20 0:191 / /tmp rw,ro - tmpfs tmpfs rw\n",
    "42 20 a:b / /tmp rw - tmpfs tmpfs rw\n",
    "42 20 0:191 / /tmp rw - tmpfs tmpfs rw - extra\n",
    "0 20 0:191 / /tmp rw - tmpfs tmpfs rw\n",
    "42 20 0:191 / /tmp rw - tmpfs tmpfs rw,size=8k,size=9k\n",
])
def test_mountinfo_parser_does_not_silently_drop_unknown_rows(text):
    with pytest.raises(m.KernelEvidenceRejected):
        m.parse_mountinfo(text)


@pytest.mark.parametrize("text", ["", CRYPT.rstrip("\n"), CRYPT.replace("is active and is in use", "is inactive"),
    CRYPT + "  key: SECRET_SENTINEL\n", CRYPT + "  cipher: null\n",
    CRYPT.replace("  type:    PLAIN\n", ""), CRYPT.replace("512 bits", "512"),
    CRYPT.replace("sector size:  512", "sector size:  512 bytes"),
    CRYPT.replace("/dev/loop12", "/dev/../loop12"),
])
def test_status_parser_fails_closed_without_returning_unknown_key_fields(text):
    with pytest.raises(m.KernelEvidenceRejected) as error:
        m.parse_crypt_status(text)
    assert "SECRET_SENTINEL" not in str(error.value)


def test_cipher_status_accepts_active_unused_and_four_k_sector_profile():
    assert m.parse_crypt_status(CRYPT.replace("is active and is in use", "is active")).key_bits == 512
    expected, sample = fixture()
    updated = dataclasses.replace(expected, sector_bytes=4096)
    m.validate_sample(dataclasses.replace(sample, crypt=dataclasses.replace(sample.crypt, sector_size=4096)), updated)


def test_expected_profile_is_not_constructed_from_an_untrusted_name_alone():
    expected, _ = fixture()
    for args in ({"boot_id": "bad"}, {"mount_namespace": (4, 0)}, {"mapper_uuid": "../../any"},
                 {"size_bytes": True}, {"size_bytes": 8193}, {"loop_number": 13},
                 {"sector_bytes": True}, {"tmp_mount_id": 0}, {"tmp_capacity_bytes": -1}):
        with pytest.raises((m.KernelEvidenceRejected, ValueError)):
            dataclasses.replace(expected, **args)


def loop_payload(**updates):
    fields = [os.makedev(8, 1), 910001, 0, 0, 0, 12, 0, 0, 4,
              b"SENSITIVE_HINT_DO_NOT_EXPORT", b"", b"SECRET_SENTINEL_DO_NOT_EXPORT", 0, 0]
    for key, value in updates.items():
        fields[int(key)] = value
    return m.LOOP_STRUCT.pack(*fields)


def test_loop_uapi_decoding_uses_inodes_not_fixed_length_filename_hints():
    result = m.decode_loop_status(loop_payload())
    assert result.backing_device == m.Device(8, 1)
    assert result.backing_inode == 910001
    assert "SECRET_SENTINEL" not in repr(result) and "SENSITIVE_HINT" not in repr(result)
    assert set(dataclasses.asdict(result)) == {"backing_device", "backing_inode", "offset", "size_limit", "number", "flags"}


@pytest.mark.parametrize("payload", [b"", b"x" * 231, b"x" * 233, loop_payload(**{"6": 1}), loop_payload(**{"7": 32})])
def test_incomplete_loop_structure_and_legacy_key_modes_rejected(payload):
    with pytest.raises(m.KernelEvidenceRejected):
        m.decode_loop_status(payload)


@pytest.mark.parametrize("failure", [False, True])
def test_loop_ioctl_is_get_only_and_raw_buffer_is_cleared(monkeypatch, failure):
    monkeypatch.setattr(m.os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFBLK | 0o600))
    captured = []

    def ioctl(fd, command, buffer, mutable):
        assert fd == 33 and command == 0x4C05 and mutable is True
        buffer[:] = loop_payload()
        captured.append(buffer)
        if failure:
            raise OSError("synthetic ioctl unavailable")
        return 0

    monkeypatch.setattr(m.fcntl, "ioctl", ioctl)
    if failure:
        with pytest.raises(OSError):
            m.read_loop_status(33)
    else:
        assert m.read_loop_status(33).number == 12
    assert captured[0] == bytearray(232)


def test_regular_file_is_not_probed_as_a_loop_device(tmp_path):
    path = tmp_path / "not-device"
    path.write_bytes(b"owned fixture")
    with path.open("rb") as stream, pytest.raises(m.KernelEvidenceRejected):
        m.read_loop_status(stream.fileno())


@pytest.mark.parametrize("change", ["rename", "unlink", "symlink", "parent", "hardlink", "chmod", "resize"])
def test_real_pinned_backing_detects_replacement_and_metadata_changes(tmp_path, change):
    parent = tmp_path / "owned"
    parent.mkdir()
    path = parent / "backing"
    path.write_bytes(b"synthetic original payload")
    path.chmod(0o600)
    pin = m.PinnedBacking(path)
    original = pin.identity()
    try:
        if change == "rename":
            path.rename(parent / "original")
            path.write_bytes(b"synthetic original payload")
        elif change == "unlink":
            path.unlink()
        elif change == "symlink":
            path.rename(parent / "original")
            path.symlink_to(parent / "original")
        elif change == "parent":
            parent.rename(tmp_path / "old-parent")
            parent.mkdir()
            path.write_bytes(b"synthetic original payload")
        elif change == "hardlink":
            os.link(path, parent / "alias")
        elif change == "chmod":
            path.chmod(0o644)
        else:
            path.write_bytes(b"changed size")
        if change in {"hardlink", "chmod", "resize"}:
            assert pin.identity() != original
        else:
            with pytest.raises((m.KernelEvidenceRejected, OSError)):
                pin.identity()
    finally:
        pin.close()
    with pytest.raises(m.KernelEvidenceRejected):
        pin.identity()


def test_real_pinned_file_never_reads_file_payload(monkeypatch, tmp_path):
    path = tmp_path / "backing"
    path.write_bytes(b"SENSITIVE_NOT_READ")
    pin = m.PinnedBacking(path)
    monkeypatch.setattr(m.os, "read", lambda *args: pytest.fail("payload read not allowed"))
    try:
        assert pin.identity().size == len(b"SENSITIVE_NOT_READ")
    finally:
        pin.close()


def test_real_test_process_mountinfo_is_parseable_without_mounting_anything():
    rows = m.parse_mountinfo(Path("/proc/self/mountinfo").read_text())
    assert rows and any(row.target == "/" for row in rows)
    assert len({row.mount_id for row in rows}) == len(rows)


def test_non_block_alias_and_symlink_parent_are_not_accepted(tmp_path):
    path = tmp_path / "backing"
    path.write_bytes(b"data")
    pin = m.PinnedBacking(path)
    try:
        with pytest.raises(m.KernelEvidenceRejected):
            m.LinuxReader(pin).device(str(path))
        directory = tmp_path / "real"
        directory.mkdir()
        (directory / "file").write_bytes(b"data")
        (tmp_path / "link").symlink_to(directory)
        with pytest.raises(OSError):
            m.PinnedBacking(tmp_path / "link/file")
    finally:
        pin.close()


class FakeReader:
    def __init__(self):
        self.expected, self.sample = fixture()
        dm = "/sys/dev/block/253:19"
        self.values = {"/proc/swaps": SWAPS, "/proc/self/mountinfo": MOUNTS,
                       "/proc/sys/kernel/random/boot_id": BOOT + "\n",
                       dm + "/dm/name": m.MAPPER_NAME + "\n", dm + "/dm/uuid": self.expected.mapper_uuid + "\n",
                       dm + "/size": str(SIZE // 512) + "\n", dm + "/ro": "0\n", dm + "/dm/suspended": "0\n",
                       dm + "/slaves/loop12/dev": "7:12\n", "/sys/dev/block/7:12/holders/dm-19/dev": "253:19\n"}
        self.graph = {dm + "/slaves": ("loop12",), dm + "/holders": (), "/sys/dev/block/7:12/holders": ("dm-19",)}
        self.paths = []

    def text(self, path):
        self.paths.append(path)
        return self.values[path]

    def names(self, path):
        return self.graph[path]

    def device(self, path):
        return LOOP if path == "/dev/loop12" else DM

    def namespace(self, pid):
        return NS

    def loop(self, path):
        return self.sample.loop_info

    def backing(self):
        return self.sample.backing

    def tmp(self):
        return self.sample.tmp

    def crypt_status(self):
        return CRYPT

    def page_size(self):
        return 4096


def test_collector_joins_all_sources_and_rechecks_without_mutators():
    reader = FakeReader()
    result = m.observe_pair(reader, reader.expected)
    assert result["kernel_graph_consistent"] is True
    assert reader.paths.count("/proc/swaps") == 2
    assert reader.paths.count("/sys/dev/block/253:19/dm/uuid") == 2


@pytest.mark.parametrize("path", ["/proc/swaps", "/proc/self/mountinfo", "/sys/dev/block/253:19/dm/uuid", "/sys/dev/block/253:19/size"])
def test_missing_kernel_data_never_becomes_zero_or_success(path):
    reader = FakeReader()
    del reader.values[path]
    with pytest.raises(KeyError):
        m.observe_pair(reader, reader.expected)


@pytest.mark.parametrize("kind", ["extra-swap", "plaintext", "name-traversal", "stale", "clock-backwards"])
def test_collector_fail_closed_edges(kind):
    reader = FakeReader()
    if kind == "extra-swap":
        reader.values["/proc/swaps"] += "/dev/mapper/alias partition 4 0 -3\n"
    elif kind == "plaintext":
        reader.values["/proc/swaps"] = SWAPS.replace("/dev/dm-19 partition", "/swap.img file")
    elif kind == "name-traversal":
        reader.graph["/sys/dev/block/253:19/slaves"] = ("../unowned",)
    clock_values = iter([1, 17] if kind == "stale" else [1, 0] if kind == "clock-backwards" else [1, 2])
    with pytest.raises(m.KernelEvidenceRejected):
        m.observe_pair(reader, reader.expected, clock=lambda: next(clock_values))


def test_two_individually_valid_samples_still_reject_topology_drift():
    expected, sample = fixture()
    changed_root = dataclasses.replace(sample.mounts[0], parent_id=99)
    second = dataclasses.replace(sample, mounts=(changed_root, sample.mounts[1]))
    m.validate_sample(second, expected)
    with pytest.raises(m.KernelEvidenceRejected, match="changed between"):
        m.stable_pair(sample, second, expected)


def test_swap_usage_changes_do_not_hide_identity_drift():
    expected, sample = fixture()
    second = dataclasses.replace(sample, swaps=(dataclasses.replace(sample.swaps[0], used=4096),))
    assert m.stable_pair(sample, second, expected)["max_observed_swap_used_bytes"] == 4096
    with pytest.raises(m.KernelEvidenceRejected):
        m.stable_pair(sample, dataclasses.replace(second, dm_uuid="other"), expected)


@pytest.mark.parametrize("available,reserve,good", [(1024, 1024, True), (1023, 1024, False), (0, 0, False), (True, 1, False), (-1, 1, False)])
def test_swapoff_reserve_is_an_observation_not_an_activation(available, reserve, good):
    _, sample = fixture()
    if good:
        assert m.require_swapoff_reserve(sample.swaps, available, reserve) is None
    else:
        with pytest.raises(m.KernelEvidenceRejected):
            m.require_swapoff_reserve(sample.swaps, available, reserve)


def test_reserve_counts_all_active_used_pages():
    rows = (m.Swap("/a", "file", 10000, 3000, -2), m.Swap("/b", "file", 10000, 4000, -3))
    with pytest.raises(m.KernelEvidenceRejected):
        m.require_swapoff_reserve(rows, 7999, 1000)
    m.require_swapoff_reserve(rows, 8000, 1000)


def test_linux_command_is_only_status_with_fixed_name_and_no_key_export(monkeypatch, tmp_path):
    path = tmp_path / "backing"
    path.write_bytes(b"fixture")
    pin = m.PinnedBacking(path)
    captured = []

    def run(args, **kwargs):
        captured.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=CRYPT, stderr="")

    monkeypatch.setattr(m.subprocess, "run", run)
    try:
        assert m.LinuxReader(pin).crypt_status() == CRYPT
    finally:
        pin.close()
    args, kwargs = captured[0]
    assert args == ["/usr/sbin/cryptsetup", "status", m.MAPPER_NAME]
    assert kwargs["env"]["LC_ALL"] == "C" and kwargs["timeout"] == 5
    assert "shell" not in kwargs
    assert "--showkeys" not in args and "table" not in args


def test_raw_status_failure_is_sanitized(monkeypatch, tmp_path):
    path = tmp_path / "backing"
    path.write_bytes(b"fixture")
    pin = m.PinnedBacking(path)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="SECRET_SENTINEL", stderr="SECRET_SENTINEL"))
    try:
        with pytest.raises(m.KernelEvidenceRejected) as error:
            m.LinuxReader(pin).crypt_status()
        assert "SECRET_SENTINEL" not in str(error.value)
    finally:
        pin.close()


def test_negative_control_no_swap_signature_does_not_prove_encryption(tmp_path):
    raw = tmp_path / "plaintext-looking-backing"
    raw.write_bytes(b"plaintext data without a swap signature")
    assert b"SWAPSPACE2" not in raw.read_bytes()
    expected, sample = fixture()
    wrong = dataclasses.replace(sample, crypt=dataclasses.replace(sample.crypt, cipher="null"))
    with pytest.raises(m.KernelEvidenceRejected):
        m.validate_sample(wrong, expected)


def test_no_mutating_entrypoint_or_protocol_is_shipped():
    source = (ROOT / "scripts/security/fr06c5_memory_kernel_observation.py").read_text()
    assert "def apply(" not in source and "def undo(" not in source and "__main__" not in source
    assert source.count("subprocess.run(") == 1
    assert "LOOP_SET_" not in source
    assert "SWAPSPACE2" in source  # explanatory negative control, never backing read
    _, sample = fixture()
    assert "SECRET_SENTINEL" not in json.dumps(dataclasses.asdict(sample))


def test_nsfs_opaque_root_is_preserved_not_treated_as_a_tmp_path():
    row = m.parse_mountinfo("88 20 0:4 net:[12345] /run/netns/test rw - nsfs nsfs rw\n")[0]
    assert row.root == "net:[12345]"
    with pytest.raises(m.KernelEvidenceRejected):
        m.parse_mountinfo("88 20 0:4 net:[12345] /tmp rw - tmpfs tmpfs rw\n")


@pytest.mark.parametrize("field,value", [("size", True), ("used", -1), ("used", SIZE), ("priority", True)])
def test_typed_swap_records_cannot_bypass_quantity_validation(field, value):
    _, sample = fixture()
    with pytest.raises(m.KernelEvidenceRejected):
        dataclasses.replace(sample.swaps[0], **{field: value})


def test_swap_reserve_includes_used_pages_even_when_graph_identity_is_stable():
    expected, sample = fixture()
    busy = dataclasses.replace(sample, swaps=(dataclasses.replace(sample.swaps[0], used=SIZE // 2),))
    result = m.stable_pair(sample, busy, expected)
    assert result["max_observed_swap_used_bytes"] == SIZE // 2
    with pytest.raises(m.KernelEvidenceRejected):
        m.require_swapoff_reserve(busy.swaps, SIZE // 2, 4096)
