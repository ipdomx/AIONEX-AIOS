"""Synthetic proc metadata only: no live process inspection or subprocess calls."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import errno
import os
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scanner(tmp_path, monkeypatch):
    spec = spec_from_file_location(
        "fr06c5_underlay_scan", ROOT / "scripts/security/fr06c5_host_state_cutover.py"
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    proc = tmp_path / "proc"
    proc.mkdir()
    operator = tmp_path / "legacy-operator"
    key = tmp_path / "legacy-key"
    monkeypatch.setattr(module, "PROC", proc)
    monkeypatch.setattr(
        module,
        "PATHS",
        (
            ("operator", operator, tmp_path / "candidate-operator", False),
            ("deploy-key", key, tmp_path / "candidate-key", True),
        ),
    )

    def deny_subprocess(*args, **kwargs):
        raise AssertionError("underlay metadata scan must not invoke subprocesses")

    monkeypatch.setattr(module.subprocess, "run", deny_subprocess)
    leaders = set()
    actual_iterdir = Path.iterdir

    def proc_iterdir(path):
        # Real proc root enumeration omits nonleader TIDs, even though direct
        # /proc/TID/map_files aliases exist. Preserve that distinction here.
        if path == proc:
            return iter(proc / str(pid) for pid in sorted(leaders))
        return actual_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", proc_iterdir)

    def add_thread(pid=101, tid=None):
        tid = pid if tid is None else tid
        leaders.add(pid)
        process = proc / str(pid)
        thread = process / "task" / str(tid)
        fd = thread / "fd"
        fd.mkdir(parents=True)
        for kind in ("cwd", "root"):
            (thread / kind).symlink_to(tmp_path / "outside")
        alias = proc / str(tid)
        mapping = alias / "map_files"
        mapping.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            pid=pid, tid=tid, process=process, thread=thread, fd=fd, mapping=mapping
        )

    def add_reference(thread, kind, target=None):
        target = operator / "state" if target is None else target
        if kind == "fd":
            reference = thread.fd / "7"
        elif kind == "mmap":
            reference = thread.mapping / "1000-2000"
        else:
            reference = thread.thread / kind
            reference.unlink()
        reference.symlink_to(target)
        return reference

    return SimpleNamespace(
        m=module,
        proc=proc,
        operator=operator,
        key=key,
        add_thread=add_thread,
        add_reference=add_reference,
    )


def test_empty_synthetic_proc_and_compatibility_aliases(scanner):
    assert scanner.m.hidden_underlay_references() == []
    assert scanner.m.require_zero_hidden_underlay_references() == 0
    assert scanner.m.hidden_underlay_fds() == []
    assert scanner.m.require_zero_hidden_underlay_fds() == 0


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_visible_reference_blocks_gate_with_metadata_only(scanner, kind):
    thread = scanner.add_thread()
    scanner.add_reference(thread, kind)
    holders = scanner.m.hidden_underlay_references()
    expected = {"kind": kind, "pid": 101, "tid": 101, "role": "operator"}
    if kind == "fd":
        expected["fd"] = "7"
    if kind == "mmap":
        expected["range"] = "1000-2000"
    assert holders == [expected]
    assert str(scanner.operator) not in repr(holders)
    with pytest.raises(scanner.m.B, match="visible process references"):
        scanner.m.require_zero_hidden_underlay_references()
    with pytest.raises(scanner.m.B, match="visible process references"):
        scanner.m.require_zero_hidden_underlay_fds()


def test_file_mapping_survives_closed_descriptor(scanner):
    thread = scanner.add_thread()
    descriptor = scanner.add_reference(thread, "fd")
    scanner.add_reference(thread, "mmap")
    descriptor.unlink()  # FD closed; the mapped file reference remains.
    assert list(thread.fd.iterdir()) == []
    holders = scanner.m.hidden_underlay_references()
    assert len(holders) == 1 and holders[0]["kind"] == "mmap"
    with pytest.raises(scanner.m.B):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_nonleader_reference_is_not_hidden_by_leader(scanner, kind):
    scanner.add_thread()
    thread = scanner.add_thread(tid=109)
    scanner.add_reference(thread, kind)
    assert [p.name for p in scanner.proc.iterdir()] == ["101"]
    holders = scanner.m.hidden_underlay_references()
    assert len(holders) == 1
    assert holders[0]["pid"] == 101
    assert holders[0]["tid"] == 109
    assert holders[0]["kind"] == kind


def test_outside_references_and_sibling_prefixes_are_not_counted(scanner):
    thread = scanner.add_thread()
    scanner.add_reference(thread, "fd", str(scanner.operator) + "-other/config")
    scanner.add_reference(thread, "mmap", str(scanner.key) + ".other")
    assert scanner.m.require_zero_hidden_underlay_references() == 0


def test_deleted_exact_key_reference_is_still_counted(scanner):
    thread = scanner.add_thread()
    scanner.add_reference(thread, "fd", str(scanner.key) + " (deleted)")
    holders = scanner.m.hidden_underlay_references()
    assert holders == [
        {"kind": "fd", "pid": 101, "tid": 101, "role": "deploy-key", "fd": "7"}
    ]


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO, errno.EMFILE])
@pytest.mark.parametrize("area", ["proc", "tasks", "fd", "mappings"])
def test_enumeration_errors_fail_closed(scanner, monkeypatch, error, area):
    thread = scanner.add_thread()
    target = {
        "proc": scanner.proc,
        "tasks": thread.process / "task",
        "fd": thread.fd,
        "mappings": thread.mapping,
    }[area]
    previous = Path.iterdir

    def fail(path):
        if path == target:
            raise OSError(error, "synthetic enumeration failure")
        return previous(path)

    monkeypatch.setattr(Path, "iterdir", fail)
    with pytest.raises(scanner.m.B):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO, errno.EMFILE])
@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_reference_read_errors_fail_closed(scanner, monkeypatch, error, kind):
    thread = scanner.add_thread()
    target = scanner.add_reference(thread, kind)
    previous = os.readlink

    def fail(path, *args, **kwargs):
        if Path(path) == target:
            raise OSError(error, "synthetic reference failure")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "readlink", fail)
    with pytest.raises(scanner.m.B):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("error", [errno.ENOENT, errno.ESRCH])
def test_process_disappearance_is_verified_before_ignoring(scanner, monkeypatch, error):
    thread = scanner.add_thread()
    target = thread.process / "task"
    previous = Path.iterdir

    def disappear(path):
        if path == target:
            shutil.rmtree(thread.process)
            raise OSError(error, "synthetic vanished process")
        return previous(path)

    monkeypatch.setattr(Path, "iterdir", disappear)
    assert scanner.m.require_zero_hidden_underlay_references() == 0


@pytest.mark.parametrize("error", [errno.ENOENT, errno.ESRCH])
def test_thread_disappearance_is_verified_before_ignoring(scanner, monkeypatch, error):
    thread = scanner.add_thread()
    previous = Path.iterdir

    def disappear(path):
        if path == thread.fd:
            shutil.rmtree(thread.thread)
            raise OSError(error, "synthetic vanished thread")
        return previous(path)

    monkeypatch.setattr(Path, "iterdir", disappear)
    assert scanner.m.require_zero_hidden_underlay_references() == 0


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
@pytest.mark.parametrize("error", [errno.ENOENT, errno.ESRCH])
def test_reference_disappearance_is_verified_before_ignoring(
    scanner, monkeypatch, error, kind
):
    thread = scanner.add_thread()
    target = scanner.add_reference(thread, kind)
    previous = os.readlink

    def disappear(path, *args, **kwargs):
        if Path(path) == target:
            target.unlink()
            raise OSError(error, "synthetic vanished reference")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "readlink", disappear)
    assert scanner.m.require_zero_hidden_underlay_references() == 0


@pytest.mark.parametrize("area", ["tasks", "fd", "mappings"])
def test_missing_reference_directory_with_remaining_owner_is_rejected(
    scanner, monkeypatch, area
):
    thread = scanner.add_thread()
    target = {
        "tasks": thread.process / "task",
        "fd": thread.fd,
        "mappings": thread.mapping,
    }[area]
    previous = Path.iterdir

    def missing(path):
        if path == target:
            raise FileNotFoundError("synthetic missing reference directory")
        return previous(path)

    monkeypatch.setattr(Path, "iterdir", missing)
    with pytest.raises(scanner.m.B, match="remaining process or thread"):
        scanner.m.require_zero_hidden_underlay_references()


def test_missing_link_with_existing_reference_is_rejected(scanner, monkeypatch):
    thread = scanner.add_thread()
    retained = scanner.proc.parent / "retained-reference"
    retained.write_text("synthetic reference")
    target = scanner.add_reference(thread, "fd", retained)
    previous = os.readlink

    def missing(path, *args, **kwargs):
        if Path(path) == target:
            raise FileNotFoundError("synthetic missing target")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "readlink", missing)
    with pytest.raises(scanner.m.B, match="could not be verified"):
        scanner.m.require_zero_hidden_underlay_references()


def test_disappearance_verification_error_fails_closed(scanner, monkeypatch):
    thread = scanner.add_thread()
    target = scanner.add_reference(thread, "fd")
    previous_readlink = os.readlink
    previous_stat = os.stat

    def missing(path, *args, **kwargs):
        if Path(path) == target:
            raise FileNotFoundError("synthetic initial disappearance")
        return previous_readlink(path, *args, **kwargs)

    def denied(path, *args, **kwargs):
        if Path(path) == target:
            raise PermissionError(errno.EACCES, "synthetic verification failure")
        return previous_stat(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "readlink", missing)
    monkeypatch.setattr(scanner.m.os, "stat", denied)
    with pytest.raises(scanner.m.B, match="cannot verify"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("kind", ["cwd", "root"])
@pytest.mark.parametrize("error", [errno.ENOENT, errno.ESRCH])
def test_kernel_style_absent_magic_reference_with_remaining_task(
    scanner, monkeypatch, kind, error
):
    thread = scanner.add_thread()
    target = thread.thread / kind
    assert target.is_symlink() and thread.thread.is_dir()
    # Synthetic dangling symlink models a proc magic-link placeholder whose
    # referenced FS object is absent while the task itself remains.
    with pytest.raises(FileNotFoundError):
        os.stat(target)
    previous = os.readlink

    def absent_magic_link(path, *args, **kwargs):
        if Path(path) == target:
            raise OSError(error, "synthetic absent kernel FS reference")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "readlink", absent_magic_link)
    assert scanner.m.require_zero_hidden_underlay_references() == 0
    assert target.is_symlink() and thread.thread.is_dir()
