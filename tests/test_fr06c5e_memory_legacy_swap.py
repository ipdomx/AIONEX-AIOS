"""Nonroot filesystem tests; the real swap syscalls are NEVER invoked here.

The native-kernel acceptance is a separate no-network QEMU guest runner. These
unit tests use fake kernels, actual private bindings, descriptors and journals.
"""
from __future__ import annotations

import dataclasses
import errno
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.security import fr06c5_memory_legacy_swap as m
from scripts.security import fr06c5_memory_transaction as txm


class FakeKernel:
    def __init__(self, boot: str, size: int):
        self.value = m.Runtime(boot, (4, 123), (4, 123), True, size-4096, -2, 4096, 1048576, 4096)
        self.effects: list[str] = []
        self.failure: str | None = None
        self.journal = None

    def sample(self, fd, path):
        assert os.fstat(fd).st_ino == path.stat().st_ino
        return self.value

    def disable(self, fd):
        assert self.journal.state().pending == ("apply", 0)
        self.effects.append("disable")
        if self.failure == "before":
            raise OSError(errno.EBUSY, "synthetic pre-syscall failure")
        if self.failure != "no-effect":
            self.value = dataclasses.replace(self.value, active=False, size=0, used=0, priority=0)
        if self.failure == "after":
            raise OSError(errno.EIO, "synthetic acknowledgement failure")

    def restore(self, fd, priority):
        assert self.journal.state().pending == ("undo", 0)
        self.effects.append("restore")
        if self.failure == "before":
            raise OSError(errno.EIO, "synthetic restore failure")
        self.value = dataclasses.replace(self.value, active=True, size=os.fstat(fd).st_size-4096,
                                         used=0, priority=priority)
        if self.failure == "after":
            raise OSError(errno.EIO, "synthetic restore acknowledgement failure")


@pytest.fixture
def case(tmp_path):
    storage, state, journals = (tmp_path/x for x in ("storage", "state", "journals"))
    for path in (storage, state, journals):
        path.mkdir(mode=0o700)
    path = storage/"synthetic-swap"
    with path.open("wb") as f:
        f.truncate(1048576)
    path.chmod(0o600)
    context = txm.BoundContext("a"*40, str(uuid4()), str(uuid4()), 37, "b"*64, "c"*64, "d"*64)
    return SimpleNamespace(path=path, state=state, journals=journals, context=context,
                           operation=str(uuid4()), kernel=FakeKernel(context.boot_id, path.stat().st_size))


def prepare(case):
    return m.LegacySwapAdapter.prepare(case.path, case.state, case.operation,
                                       lambda: case.context, reserve=65536, kernel=case.kernel)


def plan(adapter):
    now = int(time.time())
    return txm.Plan(adapter.operation, adapter.bound, (adapter.step,), now, now+120)


def attach(case, adapter, journal):
    adapter.attach(journal)
    case.kernel.journal = journal
    return txm.MemoryTransaction(journal, adapter)


def test_actual_files_roundtrip_without_kernel_calls(case):
    before = case.path.stat()
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        assert t.apply_next().applied == 1
        assert t.verify_applied().phase == "applied"
        assert case.kernel.effects == ["disable"]
        t.begin_rollback()
        t.undo_next()
        assert t.verify_restored().phase == "restored"
        assert case.kernel.effects == ["disable", "restore"]
    after = case.path.stat()
    assert (before.st_ino, before.st_size, before.st_mode, before.st_mtime_ns) == (
        after.st_ino, after.st_size, after.st_mode, after.st_mtime_ns)


@pytest.mark.parametrize("direction", ["apply", "undo"])
@pytest.mark.parametrize("failure", ["before", "after"])
def test_uncertain_effect_reopens_without_repeating_syscall(case, direction, failure):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        if direction == "undo":
            t.apply_next()
            t.begin_rollback()
        case.kernel.failure = failure
        with pytest.raises(txm.ActionUncertain):
            (t.apply_next if direction == "apply" else t.undo_next)()
        saved = list(case.kernel.effects)
    case.kernel.failure = None
    with m.LegacySwapAdapter.load(case.path, case.state, case.operation, lambda: case.context,
                                  kernel=case.kernel) as adapter, txm.Journal(case.journals, case.operation) as journal:
        t = attach(case, adapter, journal)
        with pytest.raises(txm.ActionUncertain):
            (t.apply_next if direction == "apply" else t.undo_next)()
        t.reconcile_pending()
        assert case.kernel.effects == saved
        if direction == "apply":
            with pytest.raises(txm.TransitionRejected):
                t.apply_next()
            t.begin_rollback()
        if journal.state().applied:
            t.undo_next()
        assert t.verify_restored().phase == "restored"


def test_return_code_without_effect_never_accepted(case):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        case.kernel.failure = "no-effect"
        with pytest.raises(txm.ActionUncertain):
            t.apply_next()
        assert journal.state().pending == ("apply", 0)
        with pytest.raises(txm.TransitionRejected):
            t.verify_applied()


@pytest.mark.parametrize("change", ["boot", "namespace", "init", "page", "size", "priority", "used", "available", "active-type"])
def test_runtime_drift_prevents_effect(case, change):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        changes = {"boot": {"boot_id": str(uuid4())}, "namespace": {"namespace": (4, 456)},
                   "init": {"init_namespace": (4, 777)}, "page": {"page_size": 65536},
                   "size": {"size": 17}, "priority": {"priority": 20}, "used": {"used": -1},
                   "available": {"available": -1}, "active-type": {"active": 1}}
        case.kernel.value = dataclasses.replace(case.kernel.value, **changes[change])
        with pytest.raises((txm.TransitionRejected, OSError)):
            t.apply_next()
        assert case.kernel.effects == []


def test_reserve_rechecked_after_plan_and_intent(case):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        case.kernel.value = dataclasses.replace(case.kernel.value, available=32768)
        with pytest.raises(txm.ActionUncertain):
            t.apply_next()
        assert case.kernel.effects == []
        assert journal.state().pending == ("apply", 0)


@pytest.mark.parametrize("attribute", ["source_commit", "boot_id", "maintenance_operation", "maintenance_generation", "preflight_sha256"])
def test_fresh_bound_context_required(case, attribute):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        values = {"source_commit": "e"*40, "boot_id": str(uuid4()), "maintenance_operation": str(uuid4()),
                  "maintenance_generation": 39, "preflight_sha256": "e"*64}
        case.context = dataclasses.replace(case.context, **{attribute: values[attribute]})
        with pytest.raises(txm.TransitionRejected):
            t.apply_next()
        assert case.kernel.effects == []


@pytest.mark.parametrize("change", ["mode", "size", "replacement", "hardlink", "symlink", "xattr", "parent", "lock", "binding"])
def test_resource_identity_changes_prevent_any_kernel_effect(case, change):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        if change == "mode":
            case.path.chmod(0o644)
        elif change == "size":
            with case.path.open("ab") as f:
                f.write(b"x")
        elif change in {"replacement", "symlink"}:
            moved = case.path.with_name("original")
            case.path.rename(moved)
            if change == "symlink":
                case.path.symlink_to(moved)
            else:
                case.path.write_bytes(b"new")
        elif change == "hardlink":
            os.link(case.path, case.path.with_name("extra"))
        elif change == "xattr":
            os.setxattr(case.path, "user.synthetic-swap", b"test")
        elif change == "parent":
            original_parent = case.path.parent
            original_parent.rename(original_parent.with_name("renamed"))
            original_parent.mkdir(mode=0o700)
        elif change == "lock":
            p = case.state/".legacy-swap.lock"
            p.rename(case.state/".former-lock")
            p.touch(mode=0o600)
        else:
            p = case.state/case.operation/"binding.json"
            p.write_text(p.read_text()+" ")
        with pytest.raises((txm.TransitionRejected, OSError)):
            t.apply_next()
        assert case.kernel.effects == []


def test_no_effect_without_pending_intent_or_wrong_direction(case):
    with prepare(case) as adapter:
        with pytest.raises(m.SwapStepRejected):
            adapter.apply(adapter.step, case.operation)
        with txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
            attach(case, adapter, journal)
            with pytest.raises(m.SwapStepRejected):
                adapter.apply(adapter.step, case.operation)
            journal.append("intent", {"direction": "apply", "index": 0})
            with pytest.raises(m.SwapStepRejected):
                adapter.undo(adapter.step, case.operation)
        assert case.kernel.effects == []


def test_inactive_baseline_or_foreign_journal_not_adopted(case):
    case.kernel.value = dataclasses.replace(case.kernel.value, active=False, size=0, priority=0, used=0)
    with pytest.raises(m.SwapStepRejected):
        prepare(case)
    assert case.kernel.effects == []


@pytest.mark.parametrize("priority", [-3, -1, 32768])
def test_unrestorable_legacy_priority_rejected(case, priority):
    case.kernel.value = dataclasses.replace(case.kernel.value, priority=priority)
    with pytest.raises(m.SwapStepRejected):
        prepare(case)


@pytest.mark.parametrize("priority", [-2, 0, 42, 32767])
def test_explicit_priority_roundtrip(case, priority):
    case.kernel.value = dataclasses.replace(case.kernel.value, priority=priority)
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        t.apply_next()
        t.begin_rollback()
        t.undo_next()
        assert t.verify_restored().phase == "restored"
        assert case.kernel.value.priority == priority


@pytest.mark.parametrize("raw", ["", "MemAvailable: 0 MB\n", "MemAvailable: -1 kB\n", "MemAvailable: 1 kB\nMemAvailable: 2 kB\n"])
def test_invalid_meminfo_never_zero_success(raw):
    with pytest.raises(m.SwapStepRejected):
        m.memory_available(raw)


def test_meminfo_correct_units():
    assert m.memory_available("MemTotal: 99 kB\nMemAvailable: 42 kB\n") == 42*1024


@pytest.mark.parametrize("swaps", ["/foreign file 1020 0 -2\n", "{p} file 1020 0 -2\n{p} file 1020 0 -3\n", "/dev/dm-42 partition 1020 0 -2\n"])
def test_native_reader_rejects_extra_or_foreign_swap_without_payload_reads(case, monkeypatch, swaps):
    monkeypatch.setattr(m, "_read_text", lambda _: "Filename Type Size Used Priority\n"+swaps.format(p=case.path))
    fd = os.open(case.path, os.O_RDONLY)
    try:
        with pytest.raises((RuntimeError, OSError)):
            m.LinuxSwapKernel().sample(fd, case.path)
    finally:
        os.close(fd)


def test_native_reader_descriptor_inode_join_on_synthetic_swaps(case, monkeypatch):
    boot = case.context.boot_id
    def text(path):
        return {"/proc/swaps": f"Filename Type Size Used Priority\n{case.path} file 1020 0 -2\n",
                "/proc/meminfo": "MemAvailable: 4096 kB\n", "/proc/sys/kernel/random/boot_id": boot+"\n"}[path]
    monkeypatch.setattr(m, "_read_text", text)
    original_stat = m.os.stat
    def fixture_stat(path, *args, **kwargs):
        return original_stat("/proc/self/ns/mnt" if str(path) == "/proc/1/ns/mnt" else path, *args, **kwargs)
    monkeypatch.setattr(m.os, "stat", fixture_stat)
    fd = os.open(case.path, os.O_RDONLY)
    try:
        sample = m.LinuxSwapKernel().sample(fd, case.path)
        assert sample.active and sample.available == 4194304 and sample.size == 1044480
    finally:
        os.close(fd)


@pytest.mark.parametrize("priority", [None, -2, 0, 123, 32767])
def test_native_call_exact_fd_and_flags_without_invoking_libc(case, monkeypatch, priority):
    calls = []
    class Function:
        def __call__(self, *args):
            calls.append(args)
            return 0
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    monkeypatch.setattr(m, "file_identity", lambda _: {})
    monkeypatch.setattr(m.ctypes, "CDLL", lambda *args, **kw: SimpleNamespace(swapoff=Function(), swapon=Function()))
    m.LinuxSwapKernel._native(91, priority)
    assert calls == [(b"/proc/self/fd/91",)] if priority is None else calls == [(
        b"/proc/self/fd/91", 0 if priority == -2 else 0x8000 | priority)]


def test_native_mutation_refuses_nonroot_before_libc(monkeypatch):
    monkeypatch.setattr(m.os, "geteuid", lambda: 65534)
    with pytest.raises(m.SwapStepRejected, match="require root"):
        m.LinuxSwapKernel._native(91, None)


def test_fsync_failure_prevents_kernel_invocation(case, monkeypatch):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        def fail(_):
            raise OSError(errno.EIO, "synthetic journal sync error")
        monkeypatch.setattr(txm.os, "fsync", fail)
        with pytest.raises(OSError):
            t.apply_next()
        assert case.kernel.effects == []


def test_preparation_not_replayed_or_overwritten(case):
    with prepare(case):
        pass
    with pytest.raises(FileExistsError):
        prepare(case)


def test_external_activation_after_disable_is_not_silently_removed(case):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        t.apply_next()
        case.kernel.value = dataclasses.replace(case.kernel.value, active=True, size=1044480, priority=-2)
        t.begin_rollback()
        with pytest.raises(txm.TransitionRejected):
            t.undo_next()
        assert case.kernel.effects == ["disable"]


def test_binding_manifest_and_journal_fingerprints_cannot_diverge(case):
    with prepare(case) as adapter:
        p = dataclasses.replace(plan(adapter), steps=(txm.BoundStep(m.STEP, "f"*64, "e"*64),))
        with txm.Journal(case.journals, case.operation, create=p) as journal, pytest.raises(m.SwapStepRejected):
            adapter.attach(journal)


def test_only_metadata_never_swap_payload_read(case, monkeypatch):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        original = m.os.read
        def guarded(fd, count):
            if os.fstat(fd).st_ino == case.path.stat().st_ino:
                raise AssertionError("Swap payload must not be read")
            return original(fd, count)
        monkeypatch.setattr(m.os, "read", guarded)
        t.apply_next()
        t.begin_rollback()
        t.undo_next()
        assert t.verify_restored().phase == "restored"


@pytest.mark.parametrize("field,value", [("priority", -2.0), ("page_size", 4096.0), ("namespace", [4, 123])])
def test_ambiguous_runtime_types_rejected(case, field, value):
    with prepare(case) as adapter, txm.Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        t = attach(case, adapter, journal)
        case.kernel.value = dataclasses.replace(case.kernel.value, **{field: value})
        with pytest.raises(txm.TransitionRejected):
            t.apply_next()
        assert case.kernel.effects == []


def test_original_permission_or_parent_not_relaxed_on_load(case):
    with prepare(case):
        pass
    case.state.chmod(0o755)
    with pytest.raises(txm.TransitionRejected):
        m.LegacySwapAdapter.load(case.path, case.state, case.operation, lambda: case.context, kernel=case.kernel)


def test_same_state_directory_serializes_cooperating_controllers(case):
    with prepare(case), pytest.raises(BlockingIOError):
        m.LegacySwapAdapter.load(case.path, case.state, case.operation, lambda: case.context, kernel=case.kernel)


def test_missing_binding_or_torn_json_not_repaired(case):
    with prepare(case):
        pass
    p = case.state/case.operation/"binding.json"
    p.write_text('{"schema":')
    with pytest.raises((ValueError, txm.TransitionRejected)):
        m.LegacySwapAdapter.load(case.path, case.state, case.operation, lambda: case.context, kernel=case.kernel)
    assert p.read_text() == '{"schema":'


def test_expired_plan_cannot_disable_swap(case):
    with prepare(case) as adapter:
        p = dataclasses.replace(plan(adapter), created_at=int(time.time())-100, expires_at=int(time.time())-1)
        with txm.Journal(case.journals, case.operation, create=p) as journal:
            t = attach(case, adapter, journal)
            with pytest.raises(txm.TransitionRejected):
                t.apply_next()
            assert case.kernel.effects == []


def test_native_errno_cannot_be_mistaken_for_completion(monkeypatch):
    class Fail:
        def __call__(self, *args):
            return -1
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    monkeypatch.setattr(m, "file_identity", lambda _: {})
    monkeypatch.setattr(m.ctypes, "CDLL", lambda *args, **kw: SimpleNamespace(swapoff=Fail()))
    monkeypatch.setattr(m.ctypes, "get_errno", lambda: errno.ENOMEM)
    with pytest.raises(OSError) as e:
        m.LinuxSwapKernel._native(91, None)
    assert e.value.errno == errno.ENOMEM
