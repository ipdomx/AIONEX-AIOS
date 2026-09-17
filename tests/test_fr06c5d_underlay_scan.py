"""Synthetic proc metadata only: no live process inspection or subprocess calls."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import errno
import os
import shutil
import stat

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
    operator.mkdir()
    (operator / "state").write_bytes(b"synthetic state")
    key.write_bytes(b"synthetic key")
    (tmp_path / "outside").mkdir()
    actual_stat = os.stat
    reference_stats = {}

    def proc_stat(path, *args, **kwargs):
        if (
            not isinstance(path, int) and kwargs.get("dir_fd") is None
            and kwargs.get("follow_symlinks", True) and Path(path) in reference_stats
        ):
            return reference_stats[Path(path)]
        return actual_stat(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "stat", proc_stat)
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
        if target is None:
            target = operator if kind in ("cwd", "root") else operator / "state"
        target = Path(target)
        assert target.is_relative_to(tmp_path)
        deleted = str(target).endswith(" (deleted)")
        if not deleted and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind in ("cwd", "root"):
                target.mkdir()
            else:
                target.write_bytes(b"synthetic outside object")
        if kind == "fd":
            reference = thread.fd / "7"
        elif kind == "mmap":
            reference = thread.mapping / "1000-2000"
        else:
            reference = thread.thread / kind
            reference.unlink()
        reference.symlink_to(target)
        if deleted:
            # Proc magic links stat the held inode despite readlink's suffix.
            reference_stats[reference] = actual_stat(str(target)[:-10])
        return reference

    return SimpleNamespace(
        m=module,
        root=tmp_path,
        proc=proc,
        reference_stats=reference_stats,
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
    readlink_failed = False

    def missing(path, *args, **kwargs):
        nonlocal readlink_failed
        if Path(path) == target:
            readlink_failed = True
            raise FileNotFoundError("synthetic initial disappearance")
        return previous_readlink(path, *args, **kwargs)

    def denied(path, *args, **kwargs):
        if Path(path) == target and readlink_failed:
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
    target.unlink()
    target.symlink_to(scanner.root / "absent-kernel-fs")
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


def reference_info(original, **changes):
    values = {
        "st_dev": original.st_dev, "st_ino": original.st_ino,
        "st_mode": original.st_mode, "st_nlink": original.st_nlink,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("kind", ["fd", "mmap"])
def test_external_hardlink_is_detected_by_inode_not_displayed_path(scanner, kind):
    thread = scanner.add_thread()
    alias = scanner.root / "outside" / "hardlink"
    alias.hardlink_to(scanner.operator / "state")
    scanner.add_reference(thread, kind, alias)
    holders = scanner.m.hidden_underlay_references()
    assert len(holders) == 1 and holders[0]["role"] == "operator"
    assert holders[0]["kind"] == kind
    assert str(alias) not in repr(holders)
    with pytest.raises(scanner.m.B):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_external_bind_alias_and_nonleader_are_detected_by_identity(scanner, kind):
    scanner.add_thread()
    thread = scanner.add_thread(tid=109)
    alias = scanner.root / "outside" / "bind-alias"
    reference = scanner.add_reference(thread, kind, alias)
    source = scanner.operator if kind in ("cwd", "root") else scanner.operator / "state"
    scanner.reference_stats[reference] = source.stat()
    holders = scanner.m.hidden_underlay_references()
    assert len(holders) == 1
    assert holders[0]["kind"] == kind and holders[0]["role"] == "operator"
    assert holders[0]["tid"] == 109 and holders[0]["pid"] == 101
    assert str(alias) not in repr(holders) and str(source) not in repr(holders)


def test_unrelated_inode_on_same_filesystem_is_allowed(scanner):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, "fd", scanner.root / "outside" / "unrelated")
    assert reference.stat().st_dev == scanner.operator.stat().st_dev
    assert reference.stat().st_ino != (scanner.operator / "state").stat().st_ino
    assert scanner.m.require_zero_hidden_underlay_references() == 0


def test_equal_inode_number_on_other_device_is_not_source_identity(scanner):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, "fd", scanner.root / "outside" / "other-device")
    source = (scanner.operator / "state").stat()
    scanner.reference_stats[reference] = reference_info(source, st_dev=source.st_dev + 1)
    assert scanner.m.require_zero_hidden_underlay_references() == 0


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_unknown_unlinked_source_filesystem_object_requires_reconciliation(scanner, kind):
    thread = scanner.add_thread()
    alias = scanner.root / "outside" / "no-current-provenance"
    reference = scanner.add_reference(thread, kind, alias)
    info = reference.stat()
    assert info.st_dev == scanner.operator.stat().st_dev
    scanner.reference_stats[reference] = reference_info(info, st_nlink=0)
    holders = scanner.m.hidden_underlay_references()
    assert len(holders) == 1
    assert holders[0]["role"] == "unresolved-legacy-filesystem"
    assert holders[0]["reason"] == "unlinked-reference-provenance-unverified"
    assert str(alias) not in repr(holders) and str(scanner.operator) not in repr(holders)
    with pytest.raises(scanner.m.B):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("kind", ["fd", "mmap"])
def test_deleted_external_alias_with_known_inode_retains_source_role(scanner, kind):
    thread = scanner.add_thread()
    alias = scanner.root / "outside" / "deleted-alias"
    reference = scanner.add_reference(thread, kind, alias)
    reference.unlink()
    reference.symlink_to(str(alias) + " (deleted)")
    scanner.reference_stats[reference] = (scanner.operator / "state").stat()
    holders = scanner.m.hidden_underlay_references()
    assert len(holders) == 1 and holders[0]["role"] == "operator"
    assert "reason" not in holders[0]


def test_deleted_lexical_source_without_current_inode_is_still_blocked(scanner):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, "fd", str(scanner.key) + " (deleted)")
    original = scanner.key.stat()
    scanner.reference_stats[reference] = reference_info(
        original, st_ino=original.st_ino + 900000, st_nlink=0
    )
    holders = scanner.m.hidden_underlay_references()
    assert len(holders) == 1 and holders[0]["role"] == "deploy-key"


@pytest.mark.parametrize("object_kind", ["other-device-file", "socket", "pipe"])
def test_unlinked_nonlegacy_device_or_special_object_is_not_ambiguous(scanner, object_kind):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, "fd", scanner.root / "outside" / "unrelated")
    info = reference.stat()
    changes = {"st_nlink": 0}
    if object_kind == "other-device-file":
        changes["st_dev"] = info.st_dev + 1
    elif object_kind == "socket":
        changes["st_mode"] = stat.S_IFSOCK | 0o600
    else:
        changes["st_mode"] = stat.S_IFIFO | 0o600
    scanner.reference_stats[reference] = reference_info(info, **changes)
    assert scanner.m.require_zero_hidden_underlay_references() == 0


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO, errno.EMFILE])
def test_reference_identity_stat_errors_fail_closed(scanner, monkeypatch, kind, error):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, kind)
    previous = os.stat

    def denied(path, *args, **kwargs):
        if not isinstance(path, int) and Path(path) == reference:
            raise OSError(error, "synthetic identity stat failure")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "stat", denied)
    with pytest.raises(scanner.m.B, match="cannot inspect process reference identity"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("error", [errno.ENOENT, errno.ESRCH])
def test_reference_stat_disappearance_requires_absence_confirmation(scanner, monkeypatch, error):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, "fd")
    previous = os.stat
    called = False

    def transient(path, *args, **kwargs):
        nonlocal called
        if not isinstance(path, int) and Path(path) == reference and not called:
            called = True
            raise OSError(error, "synthetic temporary stat failure")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "stat", transient)
    with pytest.raises(scanner.m.B, match="stat disappearance could not be verified"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_reused_reference_identity_is_rejected(scanner, monkeypatch, kind):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, kind, scanner.root / "outside" / "reused")
    previous = os.stat
    calls = 0

    def reused(path, *args, **kwargs):
        nonlocal calls
        info = previous(path, *args, **kwargs)
        if not isinstance(path, int) and Path(path) == reference:
            calls += 1
            if calls > 1:
                return reference_info(info, st_ino=info.st_ino + 1)
        return info

    monkeypatch.setattr(scanner.m.os, "stat", reused)
    with pytest.raises(scanner.m.B, match="reference identity changed"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("kind", ["fd", "cwd", "root", "mmap"])
def test_reference_disappearing_during_final_stat_is_verified(scanner, monkeypatch, kind):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, kind)
    previous = os.stat
    calls = 0

    def disappeared(path, *args, **kwargs):
        nonlocal calls
        if not isinstance(path, int) and Path(path) == reference:
            calls += 1
            if calls == 2:
                reference.unlink()
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "stat", disappeared)
    assert scanner.m.require_zero_hidden_underlay_references() == 0
    assert calls == 3


@pytest.mark.parametrize("area", ["root", "ancestor", "nested"])
def test_identity_inventory_rejects_symlinks(scanner, area):
    if area == "root":
        scanner.key.unlink()
        scanner.key.symlink_to(scanner.operator / "state")
    elif area == "nested":
        (scanner.operator / "alias").symlink_to(scanner.root / "outside")
    else:
        alias = scanner.root / "alias-parent"
        alias.symlink_to(scanner.operator)
        scanner.m.PATHS = (("operator", alias / "state", scanner.root / "candidate", True),)
    with pytest.raises(scanner.m.B):
        scanner.m.require_zero_hidden_underlay_references()


def test_identity_inventory_rejects_special_entries(scanner):
    os.mkfifo(scanner.operator / "fifo")
    with pytest.raises(scanner.m.B, match="symlinks and special entries"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("role", ["operator", "deploy-key"])
def test_identity_inventory_rejects_changed_source_type(scanner, role):
    scanner.m.PATHS = tuple(
        (name, source, dest, not is_file if name == role else is_file)
        for name, source, dest, is_file in scanner.m.PATHS
    )
    with pytest.raises(scanner.m.B, match="source type changed"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO, errno.EMFILE])
def test_identity_inventory_enumeration_errors_fail_closed(scanner, monkeypatch, error):
    previous = os.scandir
    source = scanner.operator.stat()

    def denied(path):
        if isinstance(path, int):
            info = os.fstat(path)
            if (info.st_dev, info.st_ino) == (source.st_dev, source.st_ino):
                raise OSError(error, "synthetic source enumeration failure")
        return previous(path)

    monkeypatch.setattr(scanner.m.os, "scandir", denied)
    with pytest.raises(scanner.m.B, match="cannot complete legacy identity inventory"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO, errno.EMFILE])
def test_identity_inventory_open_errors_fail_closed(scanner, monkeypatch, error):
    previous = os.open

    def denied(path, *args, **kwargs):
        if path == scanner.operator.name:
            raise OSError(error, "synthetic source directory open failure")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "open", denied)
    with pytest.raises(scanner.m.B, match="cannot complete legacy identity inventory"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("error", [errno.ENOENT, errno.ESRCH, errno.EACCES, errno.EIO])
def test_identity_inventory_entry_stat_failure_is_never_assumed_absent(
    scanner, monkeypatch, error
):
    previous = os.stat

    def denied(path, *args, **kwargs):
        if path == "state" and kwargs.get("dir_fd") is not None:
            raise OSError(error, "synthetic source metadata failure")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "stat", denied)
    with pytest.raises(scanner.m.B, match="cannot complete legacy identity inventory"):
        scanner.m.require_zero_hidden_underlay_references()


def test_replaced_source_inode_during_inventory_is_rejected(scanner, monkeypatch):
    previous = os.stat
    replacement = scanner.root / "replacement"
    replacement.write_bytes(b"replacement inode")
    calls = 0

    def replaced(path, *args, **kwargs):
        nonlocal calls
        if path == "state" and kwargs.get("dir_fd") is not None:
            calls += 1
            if calls == 2:
                os.replace(replacement, scanner.operator / "state")
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "stat", replaced)
    with pytest.raises(scanner.m.B, match="legacy entry changed"):
        scanner.m.require_zero_hidden_underlay_references()


def test_replaced_source_directory_between_stat_and_open_is_rejected(scanner, monkeypatch):
    previous = os.open
    replacement = scanner.root / "replacement-directory"
    replacement.mkdir()
    changed = False

    def replaced(path, *args, **kwargs):
        nonlocal changed
        if path == scanner.operator.name and not changed:
            changed = True
            scanner.operator.rename(scanner.root / "former-source")
            replacement.rename(scanner.operator)
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "open", replaced)
    with pytest.raises(scanner.m.B, match="directory changed while opening"):
        scanner.m.require_zero_hidden_underlay_references()


@pytest.mark.parametrize("change", ["new-entry", "replaced-inode", "removed-entry", "new-link"])
def test_inventory_change_while_scanning_references_blocks_zero_result(scanner, monkeypatch, change):
    thread = scanner.add_thread()
    reference = scanner.add_reference(thread, "fd", scanner.root / "outside" / "unrelated")
    replacement = scanner.root / "replacement"
    replacement.write_bytes(b"replacement inode")
    previous = os.readlink
    changed = False

    def change_source(path, *args, **kwargs):
        nonlocal changed
        if Path(path) == reference and not changed:
            changed = True
            if change == "new-entry":
                (scanner.operator / "new-entry").write_bytes(b"new source inode")
            elif change == "replaced-inode":
                os.replace(replacement, scanner.operator / "state")
            elif change == "removed-entry":
                (scanner.operator / "state").unlink()
            else:
                (scanner.root / "outside" / "new-hardlink").hardlink_to(
                    scanner.operator / "state"
                )
        return previous(path, *args, **kwargs)

    monkeypatch.setattr(scanner.m.os, "readlink", change_source)
    with pytest.raises(scanner.m.B, match="identity inventory changed"):
        scanner.m.require_zero_hidden_underlay_references()


def test_inventory_reads_metadata_without_opening_regular_content(scanner, monkeypatch):
    thread = scanner.add_thread()
    scanner.add_reference(thread, "fd", scanner.root / "outside" / "unrelated")
    previous = os.open

    def directory_only(path, flags, *args, **kwargs):
        assert flags & os.O_DIRECTORY
        assert flags & os.O_NOFOLLOW
        return previous(path, flags, *args, **kwargs)

    def no_content(*args, **kwargs):
        raise AssertionError("scanner must not read source or maps file contents")

    monkeypatch.setattr(scanner.m.os, "open", directory_only)
    monkeypatch.setattr(Path, "read_bytes", no_content)
    monkeypatch.setattr(Path, "read_text", no_content)
    assert scanner.m.require_zero_hidden_underlay_references() == 0
