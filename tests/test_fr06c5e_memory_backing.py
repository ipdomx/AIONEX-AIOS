"""Owned-file tests only. Native loop/swap consumers are exercised in a QEMU VM.
No test here attaches a loop, formats a swap, mounts or changes host services.
"""
from __future__ import annotations

import dataclasses
import errno
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.security import fr06c5_memory_backing as m
from scripts.security import fr06c5_memory_transaction as txm

ROOT = Path(__file__).resolve().parents[1]


class FakeConsumers:
    def __init__(self):
        self.rows = ()
        self.calls = 0
        self.error = None

    def consumers(self, _fd):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


def make_case(tmp_path):
    files, state, journals = (tmp_path / n for n in ("files", "state", "journals"))
    for path in (files, state, journals):
        path.mkdir(mode=0o700)
    context = txm.BoundContext("a"*40, str(uuid4()), str(uuid4()), 36, "b"*64, "c"*64, "d"*64)
    return SimpleNamespace(target=files/"random-swap.backing", state=state, journals=journals,
                           context=context, operation=str(uuid4()), reader=FakeConsumers())


def prepared(case):
    return m.BackingAdapter.prepare(case.target, case.state, case.operation, lambda: case.context,
                                   capacity=1024*1024, reserve=4096, reader=case.reader)


def plan(adapter):
    now = int(time.time())
    return txm.Plan(adapter.operation, adapter.bound, (adapter.step,), now, now+600)


def attach(case, adapter):
    journal = txm.Journal(case.journals, case.operation, create=plan(adapter))
    adapter.attach(journal)
    return journal, txm.MemoryTransaction(journal, adapter)


def test_real_allocation_is_staged_published_and_retained_on_rollback(tmp_path):
    case = make_case(tmp_path)
    with prepared(case) as a:
        original = os.fstat(a.fd)
        assert original.st_size == 1024*1024 and original.st_blocks*512 >= original.st_size
        assert stat.S_IMODE(original.st_mode) == 0o600 and not case.target.exists()
        assert set(os.listdir(a.bundle_fd)) == {"preparation-intent.json", "created-inode.json", "manifest.json"}
        j, t = attach(case, a)
        with j:
            assert t.apply_next().applied == 1
            assert case.target.stat().st_ino == original.st_ino
            assert t.verify_applied().phase == "applied"
            t.begin_rollback()
            t.undo_next()
            assert t.verify_restored().phase == "restored"
            assert not case.target.exists()
            retained = case.target.parent / a.spec["stage_name"] / "candidate"
            assert retained.stat().st_ino == original.st_ino and retained.stat().st_size == original.st_size
            assert case.reader.calls >= 4


@pytest.mark.parametrize("capacity", [0, 1, 4096, 8193, True, -4096, m.MAX_BACKING+4096, 4096.0])
def test_invalid_capacity_no_preparation(tmp_path, capacity):
    case = make_case(tmp_path)
    with pytest.raises(m.BackingRejected):
        m.BackingAdapter.prepare(case.target, case.state, case.operation, lambda: case.context,
                                capacity=capacity, reserve=4096, reader=case.reader)
    assert list(case.state.iterdir()) == [] and list(case.target.parent.iterdir()) == []


@pytest.mark.parametrize("reserve", [0, -1, True, 1, 4096.0])
def test_invalid_reserve_no_preparation(tmp_path, reserve):
    case = make_case(tmp_path)
    with pytest.raises(m.BackingRejected):
        m.BackingAdapter.prepare(case.target, case.state, case.operation, lambda: case.context,
                                capacity=8192, reserve=reserve, reader=case.reader)


@pytest.mark.parametrize("kind", ["file", "symlink", "directory"])
def test_preexisting_target_never_adopted_or_changed(tmp_path, kind):
    case = make_case(tmp_path)
    if kind == "file": case.target.write_bytes(b"original")
    elif kind == "directory": case.target.mkdir()
    else: case.target.symlink_to(case.target.parent/"missing")
    info = case.target.lstat()
    with pytest.raises(m.BackingRejected): prepared(case)
    assert case.target.lstat() == info
    assert not (case.state/case.operation).exists()


def test_disk_reserve_checked_before_any_allocation(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setattr(m.os, "fstatvfs", lambda _: SimpleNamespace(f_bavail=1, f_frsize=4096))
    with pytest.raises(m.BackingRejected, match="Insufficient space"): prepared(case)
    assert not (case.state/case.operation).exists()


@pytest.mark.parametrize("phase", ["before", "partial", "after"])
def test_failed_allocation_retains_intent_and_never_loads_or_retries(tmp_path, monkeypatch, phase):
    case = make_case(tmp_path)
    original = os.posix_fallocate
    called = []

    def fail(fd, offset, length):
        bundle = case.state/case.operation
        assert (bundle/"preparation-intent.json").is_file() and (bundle/"created-inode.json").is_file()
        called.append(fd)
        if phase != "before": original(fd, offset, length if phase == "after" else 4096)
        raise OSError(errno.ENOSPC, "synthetic allocation failure")

    monkeypatch.setattr(m.os, "posix_fallocate", fail)
    with pytest.raises(OSError): prepared(case)
    retained = case.target.parent/(".aionex-backing-"+case.operation)/"candidate"
    assert retained.exists() and not case.target.exists()
    inode = retained.stat().st_ino
    assert not (case.state/case.operation/"manifest.json").exists()
    with pytest.raises((ValueError, m.BackingRejected)):
        m.BackingAdapter.load(case.target, case.state, case.operation, lambda: case.context, case.reader)
    with pytest.raises(FileExistsError): prepared(case)
    assert len(called) == 1 and retained.stat().st_ino == inode


def test_sizing_without_allocated_blocks_is_rejected(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setattr(m.os, "posix_fallocate", lambda fd, offset, length: os.ftruncate(fd, length))
    with pytest.raises(m.BackingRejected, match="fully allocated"): prepared(case)
    assert not case.target.exists()


@pytest.mark.parametrize("when", ["apply", "undo"])
@pytest.mark.parametrize("problem", ["loop", "direct_swap", "unknown", "exception"])
def test_kernel_consumers_or_incomplete_inventory_preserve_resource_and_intent(tmp_path, when, problem):
    case = make_case(tmp_path)
    with prepared(case) as a:
        j, t = attach(case, a)
        with j:
            if when == "undo": t.apply_next(); t.begin_rollback()
            before = os.fstat(a.fd)
            if problem == "loop": case.reader.rows = ("loop3",)
            elif problem == "direct_swap": case.reader.rows = ("direct-file-swap",)
            elif problem == "unknown": case.reader.rows = []
            else: case.reader.error = PermissionError("inventory denied")
            failures = (txm.ActionUncertain,) if when == "undo" else (m.BackingRejected, PermissionError)
            with pytest.raises(failures): (t.undo_next if when == "undo" else t.apply_next)()
            assert os.fstat(a.fd).st_ino == before.st_ino and case.target.exists() == (when == "undo")
            assert j.state().pending == ((when, 0) if when == "undo" else None)
            with pytest.raises(failures): (t.undo_next if when == "undo" else t.apply_next)()


def test_no_effect_without_pending_journal(tmp_path):
    case = make_case(tmp_path)
    with prepared(case) as a:
        with pytest.raises(m.BackingRejected): a.apply(a.step, case.operation)
        j, _ = attach(case, a)
        with j, pytest.raises(m.BackingRejected): a.apply(a.step, case.operation)
    assert not case.target.exists()


@pytest.mark.parametrize("what", ["context", "lock", "state_parent", "file_parent", "manifest", "intent", "created", "stage_extra", "candidate_size", "candidate_mode", "candidate_link"])
def test_changed_binding_or_inode_refuses_publication(tmp_path, what):
    case = make_case(tmp_path)
    with prepared(case) as a:
        j, t = attach(case, a)
        with j:
            if what == "context": case.context = dataclasses.replace(case.context, maintenance_generation=37)
            elif what == "lock":
                (case.state/".backing.lock").rename(case.state/"old-lock"); (case.state/".backing.lock").touch(mode=0o600)
            elif what in {"state_parent", "file_parent"}:
                p = case.state if what == "state_parent" else case.target.parent
                p.rename(p.with_name(p.name+".old")); p.mkdir(mode=0o700)
            elif what in {"manifest", "intent", "created"}:
                n = {"manifest":"manifest.json", "intent":"preparation-intent.json", "created":"created-inode.json"}[what]
                p = case.state/case.operation/n
                data = p.read_bytes(); p.rename(p.with_suffix(".old")); p.write_bytes(data); p.chmod(0o600)
            elif what == "stage_extra": (case.target.parent/a.spec["stage_name"]/"foreign").touch()
            elif what == "candidate_size": os.ftruncate(a.fd, 8192)
            elif what == "candidate_mode": os.fchmod(a.fd, 0o644)
            else: os.link(case.target.parent/a.spec["stage_name"]/"candidate", tmp_path/"alias")
            with pytest.raises((m.BackingRejected, OSError)): t.apply_next()
            assert not case.target.exists()


@pytest.mark.parametrize("phase", ["before", "after"])
def test_other_target_inode_never_overwritten_or_erased(tmp_path, phase):
    case = make_case(tmp_path)
    with prepared(case) as a:
        j, t = attach(case, a)
        with j:
            if phase == "after": t.apply_next(); case.target.rename(case.target.with_name("owned-kept"))
            case.target.write_bytes(b"foreign"); case.target.chmod(0o600)
            with pytest.raises(m.BackingRejected): a.observe(a.step, case.operation)
            assert case.target.read_bytes() == b"foreign"


def test_lock_excludes_competing_operator_but_reopens_after_close(tmp_path):
    case = make_case(tmp_path)
    with prepared(case), pytest.raises(BlockingIOError):
        m.BackingAdapter.load(case.target, case.state, case.operation, lambda: case.context, case.reader)
    with m.BackingAdapter.load(case.target, case.state, case.operation, lambda: case.context, case.reader) as a:
        assert a.observe(a.step, case.operation).fingerprint == a.step.before_sha256


def test_forged_step_or_context_cannot_attach(tmp_path):
    case = make_case(tmp_path)
    with prepared(case) as a:
        p = dataclasses.replace(plan(a), steps=(txm.BoundStep(m.STEP, "e"*64, "f"*64),))
        with txm.Journal(case.journals, case.operation, create=p) as j, pytest.raises(m.BackingRejected): a.attach(j)


@pytest.mark.parametrize("direction", ["apply", "undo"])
@pytest.mark.parametrize("timing", ["before", "after"])
def test_actual_process_loss_before_after_atomic_publication_and_retention(tmp_path, direction, timing):
    case = make_case(tmp_path)
    with prepared(case) as a:
        inode = os.fstat(a.fd).st_ino
        j, t = attach(case, a)
        with j:
            if direction == "undo": t.apply_next(); t.begin_rollback()
    payload = {"target": str(case.target), "state": str(case.state), "journals": str(case.journals),
               "context": dataclasses.asdict(case.context), "operation": case.operation,
               "direction": direction, "timing": timing}
    child = '''import json,os,signal,sys
from pathlib import Path
from scripts.security import fr06c5_memory_backing as m
from scripts.security import fr06c5_memory_transaction as t
p=json.loads(sys.argv[1]); context=t.BoundContext(**p['context'])
class Reader:
 def consumers(self,fd):return ()
real=m.rename_owned
def crash(*args,**kwargs):
 if p['timing']=='before':os.kill(os.getpid(),signal.SIGKILL)
 real(*args,**kwargs)
 os.kill(os.getpid(),signal.SIGKILL)
m.rename_owned=crash
with m.BackingAdapter.load(Path(p['target']),Path(p['state']),p['operation'],lambda:context,Reader()) as a:
 with t.Journal(Path(p['journals']),p['operation']) as j:
  a.attach(j);tx=t.MemoryTransaction(j,a)
  (tx.apply_next if p['direction']=='apply' else tx.undo_next)()
'''
    proc = subprocess.run([sys.executable, "-c", child, json.dumps(payload)], cwd=ROOT,
                          capture_output=True, text=True, timeout=10, check=False,
                          env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE":"1"})
    assert proc.returncode == -signal.SIGKILL, proc.stderr
    with m.BackingAdapter.load(case.target, case.state, case.operation, lambda: case.context, case.reader) as a, txm.Journal(case.journals, case.operation) as j:
        a.attach(j); t = txm.MemoryTransaction(j, a)
        assert j.state().pending == (direction, 0)
        with pytest.raises(txm.ActionUncertain): (t.apply_next if direction == "apply" else t.undo_next)()
        t.reconcile_pending()
        if direction == "apply":
            assert j.state().phase == "halted"
            t.begin_rollback()
        if j.state().applied: t.undo_next()
        assert t.verify_restored().phase == "restored"
        assert os.fstat(a.fd).st_ino == inode and not case.target.exists()


def test_module_has_no_host_activation_or_secret_interface():
    source = (ROOT/"scripts/security/fr06c5_memory_backing.py").read_text()
    assert "argparse" not in source and "subprocess" not in source
    assert "os.posix_fallocate" in source and "rename_owned" in source
    assert "cryptsetup" not in source and "mkswap" not in source


@pytest.mark.parametrize("problem", ["empty", "matching", "unrelated", "unbound", "permission", "missing", "wrong_device", "changed_node", "changed_set", "direct_swap", "swaps_changed", "truncated"])
def test_native_consumer_reader_is_fail_closed_on_synthetic_kernel_boundary(monkeypatch, problem):
    from scripts.security.fr06c5_memory_kernel_observation import Device, LoopMetadata

    scans = 0
    reads = 0
    class FakeRoot:
        def __truediv__(self, name):
            return Path("/sys/class/block") / name
        def iterdir(self):
            nonlocal scans
            scans += 1
            if problem == "empty" or (problem == "changed_set" and scans > 1):
                return []
            return [SimpleNamespace(name="loop0")]
    root = FakeRoot()

    def path(value):
        assert value == "/sys/class/block"
        return root

    header = "Filename Type Size Used Priority\n"

    def text(value):
        nonlocal reads
        if value.endswith("/dev"): return "9:0\n" if problem == "wrong_device" else "7:0\n"
        assert value == "/proc/swaps"
        reads += 1
        if problem == "truncated": return header[:-1]
        if problem == "direct_swap" or (problem == "swaps_changed" and reads > 1): return header + "/owned/backing file 1020 0 -2\n"
        return header

    def info(fd):
        if fd in {10, 30}: return SimpleNamespace(st_mode=stat.S_IFREG|0o600, st_dev=os.makedev(8,1), st_ino=123, st_size=1048576)
        assert fd == 20
        return SimpleNamespace(st_mode=stat.S_IFBLK|0o600, st_rdev=os.makedev(7,0))

    def opened(name, flags, **kwargs):
        if name == "/dev/loop0":
            if problem == "permission": raise PermissionError("synthetic")
            if problem == "missing": raise FileNotFoundError("synthetic")
            return 20
        assert name == "backing" and kwargs["dir_fd"] == 40
        return 30

    def ioctl(_fd):
        if problem == "unbound": raise OSError(errno.ENXIO, "unbound")
        return LoopMetadata(Device(8,1), 123 if problem == "matching" else 456, 0, 0, 0, 0)

    with monkeypatch.context() as patch:
        # Path is only replaced for the sysfs-directory observation; preserve
        # ordinary pathlib parsing used by the direct-file swap branch.
        real_path = m.Path
        patch.setattr(m, "Path", lambda v: path(v) if v == "/sys/class/block" else real_path(v))
        patch.setattr(m, "_read", text)
        patch.setattr(m, "_open_dir", lambda _:40)
        patch.setattr(m.os, "open", opened)
        patch.setattr(m.os, "close", lambda _:None)
        patch.setattr(m.os, "fstat", info)
        patch.setattr(m.os, "stat", lambda *a,**k:SimpleNamespace(st_mode=stat.S_IFBLK|0o600, st_rdev=os.makedev(7,1 if problem=="changed_node" else 0)))
        patch.setattr(m, "read_loop_status", ioctl)
        if problem in {"permission", "missing", "wrong_device", "changed_node", "changed_set", "swaps_changed", "truncated"}:
            with pytest.raises((OSError, RuntimeError)):m.LinuxConsumers().consumers(10)
        else:
            result=m.LinuxConsumers().consumers(10)
            assert result == (("loop0",) if problem=="matching" else ("direct-file-swap",) if problem=="direct_swap" else ())


def test_late_foreign_target_during_consumer_probe_is_preserved(tmp_path):
    case=make_case(tmp_path)
    with prepared(case) as a:
        j,t=attach(case,a)
        with j:
            def late(_fd):
                if not case.target.exists():
                    case.target.write_bytes(b"foreign bytes")
                    case.target.chmod(0o600)
                return ()
            case.reader.consumers=late
            with pytest.raises(m.BackingRejected):t.apply_next()
            assert case.target.read_bytes()==b"foreign bytes"
            assert j.state().pending is None


@pytest.mark.parametrize("where", ["before_allocation", "after_allocation"])
def test_context_change_retains_only_private_preparation(tmp_path, monkeypatch, where):
    case=make_case(tmp_path)
    original=os.posix_fallocate
    seen=0
    initial=case.context
    def context():
        nonlocal seen
        seen+=1
        if where=="before_allocation" and seen>=2:
            return dataclasses.replace(initial,maintenance_generation=37)
        return case.context
    def allocate(fd,offset,length):
        original(fd,offset,length)
        if where=="after_allocation":case.context=dataclasses.replace(initial,maintenance_generation=37)
    monkeypatch.setattr(m.os,"posix_fallocate",allocate)
    with pytest.raises(m.BackingRejected):
        m.BackingAdapter.prepare(case.target,case.state,case.operation,context,
                                capacity=1048576,reserve=4096,reader=case.reader)
    assert not case.target.exists() and (case.state/case.operation/"preparation-intent.json").exists()
    assert not (case.state/case.operation/"manifest.json").exists()


def test_no_raw_backing_content_read_for_metadata_or_observation(tmp_path, monkeypatch):
    case=make_case(tmp_path)
    with prepared(case) as a:
        original=os.read
        def guarded(fd,count):
            if os.fstat(fd).st_ino==os.fstat(a.fd).st_ino:
                raise AssertionError("backing payload read")
            return original(fd,count)
        monkeypatch.setattr(m.os,"read",guarded)
        assert a.observe(a.step,case.operation).fingerprint==a.step.before_sha256
        j,t=attach(case,a)
        with j:
            t.apply_next();t.verify_applied();t.begin_rollback();t.undo_next();t.verify_restored()


@pytest.mark.parametrize("phase", ["staged", "restored"])
def test_unused_baseline_cannot_be_certified_with_a_new_kernel_consumer(tmp_path, phase):
    case=make_case(tmp_path)
    with prepared(case) as a:
        j,t=attach(case,a)
        with j:
            if phase=="restored":
                t.apply_next();t.begin_rollback();t.undo_next()
            case.reader.rows=("loop0",)
            with pytest.raises(m.BackingRejected):
                if phase=="restored":t.verify_restored()
                else:a.observe(a.step,case.operation)
