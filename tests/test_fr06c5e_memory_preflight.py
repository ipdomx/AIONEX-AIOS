"""Read-only preflight on owned fixtures and a real controlled mmap process.

No swapoff, swapon, mapper, mount, service, production DB or provider operation.
The inherited scanner is retained verbatim as a negative regression control.
"""

from __future__ import annotations

import importlib.util
import json
import os
import select
import stat
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_preflight", ROOT / "scripts/security/fr06c5_memory_preflight.py"
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def _stat_line(pid: int, start: int = 100) -> str:
    return f"{pid} (owned fixture) " + " ".join(
        ["S"] + ["0"] * 18 + [str(start)] + ["0"] * 8
    )


def _maps(info, path: str, mode: str = "rw-s") -> str:
    return f"1000-2000 {mode} 00000000 {os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x} {info.st_ino} {path}\n"


def _proc(tmp_path, *, pid: int = 4321):
    proc = tmp_path / "proc"
    thread = proc / str(pid) / "task" / str(pid)
    (thread / "fd").mkdir(parents=True)
    (thread / "stat").write_text(_stat_line(pid))
    (thread / "cwd").symlink_to(tmp_path)
    (thread / "root").symlink_to(Path("/"))
    (thread / "maps").write_text("")
    return proc, thread


@pytest.mark.parametrize("kind", ["same", "alias", "other", "regular"])
def test_swap_device_identity_not_path_or_inode(monkeypatch, kind):
    numbers = {
        "same": (253, 7),
        "alias": (253, 7),
        "other": (253, 8),
        "regular": (253, 7),
    }

    def info(path):
        if str(path) == "/dev/mapper/owned":
            return SimpleNamespace(
                st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(253, 7), st_ino=10
            )
        return SimpleNamespace(
            st_mode=(stat.S_IFREG if kind == "regular" else stat.S_IFBLK) | 0o600,
            st_rdev=os.makedev(*numbers[kind]),
            st_ino=99,
        )

    monkeypatch.setattr(m, "os", SimpleNamespace(stat=info))
    assert m.same_swap_device("/dev/dm-7", "/dev/mapper/owned") is (
        kind in {"same", "alias"}
    )


@pytest.mark.parametrize("error", [FileNotFoundError, PermissionError, OSError])
def test_unreadable_swap_never_counts_as_nonmatch(monkeypatch, error):
    def fail(_path):
        raise error("synthetic")

    monkeypatch.setattr(m, "os", SimpleNamespace(stat=fail))
    with pytest.raises(m.IncompleteObservation):
        m.same_swap_device("/dev/dm-7", "/dev/mapper/owned")


def test_nonblock_expected_mapper_is_unknown(monkeypatch):
    monkeypatch.setattr(
        m, "os", SimpleNamespace(stat=lambda _: SimpleNamespace(st_mode=stat.S_IFREG))
    )
    with pytest.raises(m.IncompleteObservation):
        m.same_swap_device("/dev/dm-7", "/dev/mapper/owned")


HEADER = "Filename\tType\tSize\tUsed\tPriority\n"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "wrong\n",
        HEADER + "/swap file 1\n",
        HEADER + "/swap file x 0 -1\n",
        HEADER + "/swap file 1 2 -1\n",
        HEADER + "/swap file -1 0 -1\n",
        HEADER + "/swap file 1 -1 -1\n",
        HEADER + "relative file 1 0 -1\n",
        HEADER + "/swap unknown 1 0 -1\n",
        HEADER + "/swap file 1 0 -1\n/swap file 1 0 -1\n",
    ],
)
def test_swap_inventory_rejects_malformed_and_duplicate_rows(content):
    with pytest.raises(m.IncompleteObservation):
        m.parse_swaps(content)


def test_valid_swap_parser_and_empty_inventory_are_distinct():
    assert m.parse_swaps(HEADER) == []
    assert m.parse_swaps(HEADER + "/owned\\040swap file 8 2 -3\n") == [
        {
            "name": "/owned swap",
            "type": "file",
            "size_bytes": 8192,
            "used_bytes": 2048,
            "priority": -3,
        }
    ]


@pytest.mark.parametrize("count", [0, 2, 3])
def test_multiple_or_absent_swaps_never_pass_identity_gate(monkeypatch, count):
    monkeypatch.setattr(
        m,
        "same_swap_device",
        lambda *_: pytest.fail("must reject count before device reads"),
    )
    with pytest.raises(m.IncompleteObservation):
        m.require_only_encrypted_swap(
            [{"name": "/owned"}] * count, Path("/dev/mapper/owned")
        )


def test_identity_gate_does_not_claim_encryption_proof(monkeypatch):
    monkeypatch.setattr(m, "same_swap_device", lambda *_: True)
    assert (
        m.require_only_encrypted_swap([{"name": "/owned"}], Path("/dev/mapper/owned"))[
            "cryptographic_mapping_attested"
        ]
        is False
    )


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_owned_underlay_reference_is_detected(tmp_path, kind):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    asset = underlay / "fixture.bin"
    asset.write_bytes(b"owned")
    proc, thread = _proc(tmp_path)
    if kind == "mmap":
        (thread / "maps").write_text(_maps(asset.stat(), str(asset)))
    elif kind == "fd":
        (thread / "fd" / "3").symlink_to(asset)
    else:
        (thread / kind).unlink()
        (thread / kind).symlink_to(underlay)
    with m.PinnedUnderlay(underlay) as pin:
        result = m.scan_references(pin, proc_root=proc)
    assert result["status"] == "references_present"
    assert result["reference_count"] == 1
    assert result["references"][0]["kind"] == kind
    assert result["activation_authorized"] is False
    assert result["full_host_closure"] is False


def test_hardlink_mapping_alias_matched_by_inode_without_relying_on_path(tmp_path):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    asset = underlay / "owned.bin"
    asset.write_bytes(b"owned")
    alias = tmp_path / "elsewhere.bin"
    os.link(asset, alias)
    proc, thread = _proc(tmp_path)
    (thread / "maps").write_text(_maps(alias.stat(), str(alias)))
    with m.PinnedUnderlay(underlay) as pin:
        result = m.scan_references(pin, proc_root=proc)
    assert result["references"][0]["reason"] == "underlay-inode"


def test_unlinked_unknown_same_filesystem_mapping_is_not_a_zero(tmp_path):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    other = tmp_path / "deleted.bin"
    other.write_bytes(b"owned")
    info = other.stat()
    other.unlink()
    proc, thread = _proc(tmp_path)
    (thread / "maps").write_text(_maps(info, str(other) + " (deleted)"))
    with m.PinnedUnderlay(underlay) as pin:
        result = m.scan_references(pin, proc_root=proc)
    assert result["reference_count"] == 1
    assert (
        result["references"][0]["reason"]
        == "unlinked-same-filesystem-provenance-unknown"
    )


@pytest.mark.parametrize("component", ["maps", "stat", "fd"])
def test_missing_or_unreadable_process_observation_is_unknown(tmp_path, component):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, thread = _proc(tmp_path)
    target = thread / component
    target.rmdir() if component == "fd" else target.unlink()
    with m.PinnedUnderlay(underlay) as pin, pytest.raises(m.IncompleteObservation):
        m.scan_references(pin, proc_root=proc)


@pytest.mark.parametrize(
    "line",
    [
        "bad",
        "2000-1000 rw-s 0000 00:01 3 /owned",
        "1000-2000 bad 0 00:01 3 /owned",
        "1000-2000 rw-s 0 bad 3 /owned",
        "1000-2000 rw-s 0 00:01 -1 /owned",
    ],
)
def test_malformed_mapping_never_becomes_anonymous(line):
    with pytest.raises(m.IncompleteObservation):
        m.mapping_rows(line)


def test_pid_reuse_during_scan_is_unknown(tmp_path, monkeypatch):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, _ = _proc(tmp_path)
    count = 0

    def identity(_):
        nonlocal count
        count += 1
        return (4321, str(count))

    monkeypatch.setattr(m, "_process_identity", identity)
    with (
        m.PinnedUnderlay(underlay) as pin,
        pytest.raises(m.IncompleteObservation, match="identity changed"),
    ):
        m.scan_references(pin, proc_root=proc)


def test_inventory_change_during_scan_is_unknown(tmp_path, monkeypatch):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, thread = _proc(tmp_path)
    original = m._bounded_text

    def changed(path):
        text = original(path)
        if path == thread / "maps":
            (underlay / "new.bin").write_bytes(b"changed")
        return text

    monkeypatch.setattr(m, "_bounded_text", changed)
    with (
        m.PinnedUnderlay(underlay) as pin,
        pytest.raises(m.IncompleteObservation, match="underlay changed"),
    ):
        m.scan_references(pin, proc_root=proc)


@pytest.mark.parametrize(
    "path", [Path("relative"), Path("/"), Path("/tmp/../elsewhere")]
)
def test_invalid_root_scope_rejected(path):
    with pytest.raises(m.IncompleteObservation):
        m.PinnedUnderlay(path)


def test_symlink_ancestor_refused(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "underlay").mkdir()
    link = tmp_path / "link"
    link.symlink_to(actual)
    with pytest.raises(m.IncompleteObservation), m.PinnedUnderlay(link / "underlay"):
        pass


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_underlay_special_entries_require_review(tmp_path, kind):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    if kind == "symlink":
        (underlay / "special").symlink_to(tmp_path)
    else:
        os.mkfifo(underlay / "special")
    with m.PinnedUnderlay(underlay) as pin, pytest.raises(m.IncompleteObservation):
        pin.snapshot()


def test_selected_empty_or_duplicate_scope_cannot_report_clear(tmp_path):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, _ = _proc(tmp_path)
    with m.PinnedUnderlay(underlay) as pin:
        for selected in ([], [4321, 4321], [-1]):
            with pytest.raises(m.IncompleteObservation):
                m.scan_references(pin, proc_root=proc, selected_pids=selected)


def test_real_inode_pin_survives_path_replacement_and_finds_hidden_mapping(tmp_path):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    asset = underlay / "owned.bin"
    asset.write_bytes(b"owned")
    info = asset.stat()
    proc, thread = _proc(tmp_path)
    with m.PinnedUnderlay(underlay) as pin:
        underlay.rename(tmp_path / "hidden-original")
        underlay.mkdir()
        (thread / "maps").write_text(
            _maps(info, str(tmp_path / "hidden-original" / "owned.bin"))
        )
        result = m.scan_references(pin, proc_root=proc)
        assert result["visible_path_matches_pinned_underlay"] is False
        assert result["reference_count"] == 1
        assert result["references"][0]["reason"] == "underlay-inode"
    assert (tmp_path / "hidden-original/owned.bin").read_bytes() == b"owned"


CHILD = r"""
import ctypes,json,os,sys
from pathlib import Path
p=Path(sys.argv[1]);fd=os.open(p,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);os.ftruncate(fd,4096)
lib=ctypes.CDLL(None,use_errno=True)
lib.mmap.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_long]
lib.mmap.restype=ctypes.c_void_p
lib.munmap.argtypes=[ctypes.c_void_p,ctypes.c_size_t];lib.munmap.restype=ctypes.c_int
ptr=lib.mmap(None,4096,3,1,fd,0)
assert ptr not in (None,ctypes.c_void_p(-1).value)
ctypes.memset(ptr,65,1);os.close(fd)
print(json.dumps({'pid':os.getpid(),'fd_closed':True}),flush=True)
assert sys.stdin.readline().strip()=='unmap'
assert lib.munmap(ptr,4096)==0
print('unmapped',flush=True)
assert sys.stdin.readline().strip()=='exit'
"""


def _receive(proc):
    assert select.select([proc.stdout], [], [], 8)[0], "owned child did not respond"
    value = proc.stdout.readline().strip()
    assert value, "owned child terminated"
    return value


def test_actual_writable_mmap_after_fd_close_is_missed_by_prepared_scanner_and_found():
    with tempfile.TemporaryDirectory(
        prefix="aionex-disposable-c5e-map-", dir="/tmp"
    ) as directory:
        path = Path(directory) / "owned.bin"
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", CHILD, str(path)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            info = json.loads(_receive(child))
            assert info["fd_closed"] is True
            links = [
                os.readlink(fd)
                for fd in (Path("/proc") / str(child.pid) / "fd").iterdir()
            ]
            assert str(path) not in links
            fixture = ROOT / "tests/fixtures/fr06c5e/prepared_tmp_holders.py.txt"
            legacy_spec = importlib.util.spec_from_loader(
                "prepared_baseline", SourceFileLoader("prepared_baseline", str(fixture))
            )
            assert legacy_spec and legacy_spec.loader
            legacy = importlib.util.module_from_spec(legacy_spec)
            legacy_spec.loader.exec_module(legacy)

            def selected(value):
                return (
                    SimpleNamespace(iterdir=lambda: [Path("/proc") / str(child.pid)])
                    if value == "/proc"
                    else Path(value)
                )

            legacy.Path = selected
            assert legacy.tmp_holders() == [], (
                "legacy fd-only scan should reproduce the missed mmap"
            )
            with m.PinnedUnderlay(Path(directory)) as pin:
                mapped = m.scan_references(pin, selected_pids=[child.pid])
                assert any(
                    hit["kind"] == "mmap" and "w" in hit["permissions"]
                    for hit in mapped["references"]
                )
                assert mapped["scope"] == "selected-owned-processes"
                child.stdin.write("unmap\n")
                child.stdin.flush()
                assert _receive(child) == "unmapped"
                cleared = m.scan_references(pin, selected_pids=[child.pid])
                assert (
                    cleared["reference_count"] == 0
                    and cleared["activation_authorized"] is False
                )
            child.stdin.write("exit\n")
            child.stdin.flush()
            assert child.wait(timeout=5) == 0
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()


def test_module_contains_no_mutating_system_commands():
    import ast

    source = (ROOT / "scripts/security/fr06c5_memory_preflight.py").read_text()
    tree = ast.parse(source)
    assert not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr
        in {
            "system",
            "Popen",
            "run",
            "unlink",
            "mkdir",
            "replace",
            "kill",
            "write_bytes",
            "write_text",
        }
        for n in ast.walk(tree)
    )


@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_os_error_while_reading_maps_is_not_silently_skipped(
    tmp_path, monkeypatch, error
):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, thread = _proc(tmp_path)
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path == thread / "maps":
            raise error("synthetic maps denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with (
        m.PinnedUnderlay(underlay) as pin,
        pytest.raises(m.IncompleteObservation, match="inaccessible"),
    ):
        m.scan_references(pin, proc_root=proc)


def test_nonleader_thread_mapping_is_included(tmp_path):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    asset = underlay / "owned.bin"
    asset.write_bytes(b"owned")
    proc, thread = _proc(tmp_path)
    second = thread.parent / "4322"
    (second / "fd").mkdir(parents=True)
    (second / "stat").write_text(_stat_line(4322, 200))
    (second / "maps").write_text(_maps(asset.stat(), str(asset)))
    (second / "cwd").symlink_to(tmp_path)
    (second / "root").symlink_to(Path("/"))
    with m.PinnedUnderlay(underlay) as pin:
        result = m.scan_references(pin, proc_root=proc)
    assert result["threads_scanned"] == 2 and result["processes_scanned"] == 1
    assert result["references"][0]["tid"] == 4322 and result["reference_count"] == 1


def test_unobserved_selected_process_is_unknown(tmp_path):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, _ = _proc(tmp_path)
    with m.PinnedUnderlay(underlay) as pin, pytest.raises(m.IncompleteObservation):
        m.scan_references(pin, proc_root=proc, selected_pids=[99999])


@pytest.mark.parametrize("bound", ["MAX_ENTRIES", "MAX_DEPTH"])
def test_underlay_inventory_bounds_do_not_return_partial_clear(
    tmp_path, monkeypatch, bound
):
    underlay = tmp_path / "underlay"
    (underlay / "one/two/three").mkdir(parents=True)
    monkeypatch.setattr(m, bound, 1)
    with (
        m.PinnedUnderlay(underlay) as pin,
        pytest.raises(m.IncompleteObservation, match="bound"),
    ):
        pin.snapshot()


def test_out_of_range_mapping_device_is_unknown():
    with pytest.raises(m.IncompleteObservation, match="device"):
        m.mapping_rows("1000-2000 rw-s 0 ffffffffffffffffffffffffffffffff:01 1 /owned")


def test_source_payload_bytes_are_never_read_or_exported(tmp_path, monkeypatch):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    asset = underlay / "owned.bin"
    asset.write_bytes(b"synthetic private payload")
    proc, _ = _proc(tmp_path)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != asset, "preflight must never read source payload"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with m.PinnedUnderlay(underlay) as pin:
        result = m.scan_references(pin, proc_root=proc)
    assert result["status"] == "observed_clear"
    assert "synthetic private payload" not in json.dumps(result)
    assert result["scope"] == "synthetic-proc-fixture"


def test_process_population_change_is_unknown(tmp_path, monkeypatch):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, thread = _proc(tmp_path)
    original = m._bounded_text

    def changed(path):
        data = original(path)
        if path == thread / "maps":
            (proc / "9999").mkdir(exist_ok=True)
        return data

    monkeypatch.setattr(m, "_bounded_text", changed)
    with (
        m.PinnedUnderlay(underlay) as pin,
        pytest.raises(m.IncompleteObservation, match="population changed"),
    ):
        m.scan_references(pin, proc_root=proc)


def test_reference_disappearance_is_not_zero(tmp_path):
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    proc, thread = _proc(tmp_path)
    (thread / "fd/3").symlink_to(tmp_path / "does-not-exist")
    with (
        m.PinnedUnderlay(underlay) as pin,
        pytest.raises(m.IncompleteObservation, match="disappeared"),
    ):
        m.scan_references(pin, proc_root=proc)
