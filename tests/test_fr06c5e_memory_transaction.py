"""Private non-root files and exclusively owned child processes; no kernel changes.

A file adapter provides real identity/content observations and real fsynced file
writes. It is a laboratory adapter, not a swap, mount, systemd or host adapter.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import multiprocessing
import os
import stat
import sys
import time
from dataclasses import asdict, replace
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fr06_memory_transaction", ROOT / "scripts/security/fr06c5_memory_transaction.py")
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Files:
    def __init__(self, root, plan):
        self.root, self.plan = root, plan
        self.ctx = plan.context
        self.calls = []
        self.hook = lambda stage, direction: None
        self.noop = False
        self.root_identity = (root.stat().st_dev, root.stat().st_ino)
        self.identities = {step.name: ((root / step.name).stat().st_dev, (root / step.name).stat().st_ino) for step in plan.steps}

    def context(self):
        return self.ctx

    def observe(self, step, operation):
        path = self.root / step.name
        value = path.lstat()
        identity = (value.st_dev, value.st_ino) == self.identities[step.name]
        identity &= (self.root.stat().st_dev, self.root.stat().st_ino) == self.root_identity
        identity &= stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and stat.S_IMODE(value.st_mode) == 0o600
        data = path.read_bytes() if identity else b"unverified"
        return m.Observation(sha(data), identity, data == after(operation, step.name))

    def _effect(self, step, operation, direction):
        self.calls.append((direction, step.name))
        with (self.root / "effects.log").open("a") as stream:
            stream.write(direction + ":" + step.name + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.hook("before", direction)
        if not self.noop:
            path = self.root / step.name
            fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
            try:
                value = os.fstat(fd)
                assert (value.st_dev, value.st_ino) == self.identities[step.name]
                payload = after(operation, step.name) if direction == "apply" else before(step.name)
                os.ftruncate(fd, 0)
                assert os.write(fd, payload) == len(payload)
                os.fsync(fd)
            finally:
                os.close(fd)
        self.hook("after", direction)

    def apply(self, step, operation):
        self._effect(step, operation, "apply")

    def undo(self, step, operation):
        self._effect(step, operation, "undo")


def before(name):
    return ("original-owned-laboratory-file:" + name).encode()


def after(operation, name):
    return ("changed-by-owned-laboratory-operation:" + operation + ":" + name).encode()


def make_case(tmp_path, count=2):
    parent, files = tmp_path / "journal", tmp_path / "files"
    parent.mkdir(mode=0o700)
    files.mkdir(mode=0o700)
    operation = str(uuid4())
    context = m.BoundContext("a" * 40, str(uuid4()), str(uuid4()), 37, "b" * 64, "c" * 64, "d" * 64)
    steps = tuple(m.BoundStep(name, sha(before(name)), sha(after(operation, name))) for name in m.STEPS[:count])
    plan = m.Plan(operation, context, steps, int(time.time()) - 1, int(time.time()) + 600)
    for step in steps:
        path = files / step.name
        path.write_bytes(before(step.name))
        path.chmod(0o600)
    return parent, files, plan, Files(files, plan)


def open_new(parent, plan):
    return m.Journal(parent, plan.operation, create=plan)


@pytest.mark.parametrize("failure", ["systemctl", "boot_stop", "remove_unit", "swapon"])
def test_prepared_rollback_negative_control_swallows_failure(failure):
    """Run ONLY extracted old control flow; all effects are inert test doubles."""
    called = []
    class FakePath:
        def exists(self):
            return True
        def unlink(self):
            called.append("unlink")
            if failure == "remove_unit":
                raise PermissionError("Synthetic unit removal failure")
    def run(args, **kwargs):
        called.append(args[0])
        return SimpleNamespace(returncode=1 if args[0] == failure else 0)
    def boot_stop():
        called.append("boot_stop")
        if failure == "boot_stop":
            raise RuntimeError("Synthetic encrypted-swap stop failure")
    namespace = {"subprocess": SimpleNamespace(run=run, DEVNULL=-3),
                 "boot_swap_stop": boot_stop, "restore_fstab": lambda: None,
                 "SWAP_UNIT_DST": FakePath(), "TMP_DST": FakePath(), "LEGACY": FakePath()}
    loader = SourceFileLoader("inert_legacy_rollback", str(ROOT / "tests/fixtures/fr06c5e/prepared_rollback.py.txt"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    baseline = importlib.util.module_from_spec(spec)
    vars(baseline).update(namespace)
    loader.exec_module(baseline)
    assert baseline.rollback_internal() is None
    assert "boot_stop" in called and "swapon" in called
    # Returning normally despite each synthetic failure is the reproduced defect.


def test_apply_and_explicit_reverse_rollback_are_verified_from_actual_files(tmp_path):
    parent, files, plan, adapter = make_case(tmp_path, 3)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        for step in plan.steps:
            transaction.apply_next()
            assert (files / step.name).read_bytes() == after(plan.operation, step.name)
        assert transaction.verify_applied().phase == "applied"
        transaction.begin_rollback()
        for step in reversed(plan.steps):
            transaction.undo_next()
            assert (files / step.name).read_bytes() == before(step.name)
        assert transaction.verify_restored().phase == "restored"
        assert adapter.calls == [("apply", step.name) for step in plan.steps] + [("undo", step.name) for step in reversed(plan.steps)]
    with m.Journal(parent, plan.operation) as journal:
        assert journal.state().phase == "restored"


@pytest.mark.parametrize("direction", ["apply", "undo"])
@pytest.mark.parametrize("when", ["before", "after", "noop"])
def test_failure_never_becomes_success_or_automatic_retry(tmp_path, direction, when):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        if direction == "undo":
            transaction.apply_next()
            transaction.verify_applied()
            transaction.begin_rollback()
        def fail(stage, actual):
            if stage == when:
                raise OSError("Synthetic effect error")
        adapter.hook = fail
        adapter.noop = when == "noop"
        action = transaction.apply_next if direction == "apply" else transaction.undo_next
        with pytest.raises(m.ActionUncertain):
            action()
        assert journal.state().pending == (direction, 0)
        calls = list(adapter.calls)
        with pytest.raises(m.ActionUncertain):
            action()
        assert adapter.calls == calls
        reconciled = transaction.reconcile_pending()
        assert adapter.calls == calls, "Reconciliation must not execute a physical action"
        assert reconciled.pending is None
        if direction == "apply":
            assert reconciled.phase == "halted"
            with pytest.raises(m.TransitionRejected):
                transaction.apply_next()
            transaction.begin_rollback()
        adapter.hook = lambda stage, actual: None
        adapter.noop = False
        if journal.state().applied:
            transaction.undo_next()
        assert transaction.verify_restored().phase == "restored"


@pytest.mark.parametrize("field", ["source_commit", "boot_id", "maintenance_operation", "maintenance_generation",
                                   "host_state_receipt_sha256", "preflight_sha256", "boot_graph_sha256"])
def test_bound_context_drift_blocks_effects_before_intent(tmp_path, field):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    changed = 38 if field == "maintenance_generation" else str(uuid4()) if field in {"boot_id", "maintenance_operation"} else "f" * (40 if field == "source_commit" else 64)
    adapter.ctx = replace(adapter.ctx, **{field: changed})
    with open_new(parent, plan) as journal:
        with pytest.raises(m.TransitionRejected):
            m.MemoryTransaction(journal, adapter).apply_next()
        assert adapter.calls == [] and journal.state().pending is None


def test_context_changes_during_effect_retain_intent_and_block_recovery(tmp_path):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        def change(stage, direction):
            if stage == "after":
                adapter.ctx = replace(adapter.ctx, maintenance_generation=38)
        adapter.hook = change
        with pytest.raises(m.ActionUncertain):
            transaction.apply_next()
        with pytest.raises(m.TransitionRejected):
            transaction.reconcile_pending()
        assert journal.state().pending == ("apply", 0)


@pytest.mark.parametrize("kind", ["content", "replacement", "hardlink", "permissions"])
def test_changed_or_unowned_resource_cannot_be_undone(tmp_path, kind):
    parent, files, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        transaction.apply_next()
        transaction.verify_applied()
        transaction.begin_rollback()
        path = files / plan.steps[0].name
        if kind == "content":
            path.write_bytes(b"belongs-to-another-operation")
        elif kind == "replacement":
            other = files / "replacement"
            other.write_bytes(path.read_bytes())
            other.chmod(0o600)
            os.replace(other, path)
        elif kind == "hardlink":
            os.link(path, files / "other-link")
        else:
            path.chmod(0o644)
        current = path.read_bytes()
        with pytest.raises(m.TransitionRejected):
            transaction.undo_next()
        assert path.read_bytes() == current and len(adapter.calls) == 1
        with pytest.raises(m.TransitionRejected):
            transaction.verify_restored()


def test_final_verification_covers_untouched_steps_not_only_executed_steps(tmp_path):
    parent, files, plan, adapter = make_case(tmp_path, 2)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        transaction.apply_next()
        transaction.begin_rollback()
        transaction.undo_next()
        (files / plan.steps[1].name).write_bytes(b"unrelated-change")
        with pytest.raises(m.TransitionRejected):
            transaction.verify_restored()
        assert journal.state().phase == "rolling_back"


def test_forward_expiry_blocks_apply_but_not_explicit_same_context_recovery(tmp_path):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter, clock=lambda: plan.expires_at + 1)
        with pytest.raises(m.TransitionRejected):
            transaction.apply_next()
        transaction.begin_rollback()
        assert transaction.verify_restored().phase == "restored"


def test_terminal_results_cannot_be_replayed_and_early_finalization_rejected(tmp_path):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        with pytest.raises(m.TransitionRejected):
            transaction.verify_applied()
        transaction.apply_next()
        transaction.verify_applied()
        with pytest.raises(m.TransitionRejected):
            transaction.apply_next()
        transaction.begin_rollback()
        transaction.undo_next()
        transaction.verify_restored()
        with pytest.raises(m.JournalRejected):
            transaction.begin_rollback()
    with pytest.raises(FileExistsError):
        open_new(parent, plan)


def test_exclusive_lock_and_reopening_after_close(tmp_path):
    parent, _, plan, _ = make_case(tmp_path)
    with open_new(parent, plan), pytest.raises(BlockingIOError):
        m.Journal(parent, plan.operation)
    with m.Journal(parent, plan.operation) as journal:
        assert journal.state().phase == "applying"


@pytest.mark.parametrize("target", ["operation", "parent", "lock"])
def test_live_journal_identity_replacement_is_rejected(tmp_path, target):
    parent, _, plan, _ = make_case(tmp_path)
    with open_new(parent, plan) as journal:
        if target == "operation":
            (parent / plan.operation).rename(parent / "displaced")
            (parent / plan.operation).mkdir(mode=0o700)
        elif target == "parent":
            parent.rename(tmp_path / "displaced")
            parent.mkdir(mode=0o700)
        else:
            lock = parent / plan.operation / ".lock"
            lock.rename(lock.with_name("displaced.lock"))
            lock.write_bytes(b"")
            lock.chmod(0o600)
        with pytest.raises(m.JournalRejected):
            journal.state()


@pytest.mark.parametrize("damage", ["truncated", "gap", "hash", "duplicate-key", "extra", "symlink", "hardlink", "plan", "mode", "fifo"])
def test_torn_corrupt_or_untrusted_journal_never_reopens_for_effects(tmp_path, damage):
    parent, _, plan, _ = make_case(tmp_path)
    with open_new(parent, plan):
        pass
    directory = parent / plan.operation
    event = directory / "00000000.json"
    if damage == "truncated":
        event.write_bytes(b'{"body":')
    elif damage == "gap":
        event.rename(directory / "00000001.json")
    elif damage == "hash":
        data = json.loads(event.read_text())
        data["sha256"] = "0" * 64
        event.write_text(json.dumps(data) + "\n")
    elif damage == "duplicate-key":
        event.write_text('{"body":{},"body":{}}\n')
    elif damage == "extra":
        (directory / "unfinished.tmp").write_bytes(b"pending")
    elif damage == "symlink":
        data = event.read_bytes()
        event.unlink()
        other = tmp_path / "foreign"
        other.write_bytes(data)
        event.symlink_to(other)
    elif damage == "hardlink":
        os.link(event, tmp_path / "other-link")
    elif damage == "plan":
        path = directory / "plan.json"
        data = json.loads(path.read_text())
        data["context"]["maintenance_generation"] += 1
        path.write_text(json.dumps(data) + "\n")
    elif damage == "mode":
        event.chmod(0o644)
    else:
        event.unlink()
        os.mkfifo(event, 0o600)
    with pytest.raises((m.JournalRejected, OSError, ValueError)):
        m.Journal(parent, plan.operation)


def test_symlink_parent_never_followed(tmp_path):
    parent, _, plan, _ = make_case(tmp_path)
    link = tmp_path / "alias"
    link.symlink_to(parent, target_is_directory=True)
    with pytest.raises((m.JournalRejected, OSError)):
        open_new(link, plan)
    assert list(parent.iterdir()) == []


def test_private_parent_required(tmp_path):
    parent, _, plan, _ = make_case(tmp_path)
    parent.chmod(0o755)
    with pytest.raises(m.JournalRejected):
        open_new(parent, plan)


@pytest.mark.parametrize("failure", ["write", "file-fsync", "directory-fsync"])
def test_intent_durability_failure_prevents_effect_and_poisoned_session(tmp_path, monkeypatch, failure):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        original_sync, original_write = os.fsync, os.write
        def sync(fd):
            is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
            if failure == ("directory-fsync" if is_dir else "file-fsync"):
                raise OSError("Synthetic storage durability error")
            return original_sync(fd)
        def write(fd, data):
            if failure == "write":
                original_write(fd, data[:8])
                raise OSError("Synthetic torn record")
            return original_write(fd, data)
        monkeypatch.setattr(m.os, "fsync", sync)
        monkeypatch.setattr(m.os, "write", write)
        with pytest.raises(OSError):
            m.MemoryTransaction(journal, adapter).apply_next()
        assert adapter.calls == []
        with pytest.raises(m.JournalRejected):
            journal.state()


def test_partial_write_is_completed_before_effect(tmp_path, monkeypatch):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        original = os.write
        journal_writes = []
        def short(fd, data):
            # Affect only create-only journal records, not the adapter's file.
            target = os.readlink(f"/proc/self/fd/{fd}")
            if target.startswith(str(parent)):
                journal_writes.append(len(data))
                return original(fd, data[:7])
            return original(fd, data)
        monkeypatch.setattr(m.os, "write", short)
        m.MemoryTransaction(journal, adapter).apply_next()
        assert len(journal_writes) > 10 and journal.state().applied == 1


@pytest.mark.parametrize("direction", ["apply", "undo"])
@pytest.mark.parametrize("stage", ["before", "after"])
def test_sigkill_owned_process_reopens_as_pending_and_recovers_without_replay(tmp_path, direction, stage):
    parent, files, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        if direction == "undo":
            transaction.apply_next()
            transaction.begin_rollback()
    ctx = multiprocessing.get_context("fork")
    receiving, sending = ctx.Pipe(duplex=False)
    def child():
        receiving.close()
        local = Files(files, plan)
        def stop_at(point, actual):
            if point == stage:
                sending.send({"point": point, "direction": actual})
                while True:
                    time.sleep(1)
        local.hook = stop_at
        with m.Journal(parent, plan.operation) as journal:
            transaction = m.MemoryTransaction(journal, local)
            (transaction.apply_next if direction == "apply" else transaction.undo_next)()
    process = ctx.Process(target=child)
    process.start()
    sending.close()
    try:
        assert receiving.poll(10), "Owned child did not reach the intended crash boundary"
        assert receiving.recv() == {"point": stage, "direction": direction}
        process.kill()
        process.join(10)
        assert process.exitcode == -9
    finally:
        if process.is_alive():
            process.kill()
            process.join(10)
        receiving.close()
    effects_before = (files / "effects.log").read_text()
    with m.Journal(parent, plan.operation) as journal:
        assert journal.state().pending == (direction, 0)
        recovery = m.MemoryTransaction(journal, Files(files, plan))
        with pytest.raises(m.ActionUncertain):
            (recovery.apply_next if direction == "apply" else recovery.undo_next)()
        recovery.reconcile_pending()
        assert (files / "effects.log").read_text() == effects_before
        if direction == "apply":
            with pytest.raises(m.TransitionRejected):
                recovery.apply_next()
            recovery.begin_rollback()
        if journal.state().applied:
            recovery.undo_next()
        assert recovery.verify_restored().phase == "restored"
    assert (files / plan.steps[0].name).read_bytes() == before(plan.steps[0].name)


@pytest.mark.parametrize("invalid", ["bool-generation", "open", "bad-hash", "bad-uuid", "duplicates", "reversed", "equal", "ttl", "bool-schema"])
def test_invalid_plan_cannot_start_journal(tmp_path, invalid):
    _, _, plan, _ = make_case(tmp_path)
    data = asdict(plan)
    data["steps"] = list(data["steps"])
    if invalid == "bool-generation":
        data["context"]["maintenance_generation"] = True
    elif invalid == "open":
        data["context"]["maintenance_closed"] = False
    elif invalid == "bad-hash":
        data["context"]["preflight_sha256"] = "unknown"
    elif invalid == "bad-uuid":
        data["operation"] = "../escape"
    elif invalid == "duplicates":
        data["steps"] *= 2
    elif invalid == "reversed":
        data["steps"].reverse()
    elif invalid == "equal":
        data["steps"][0]["after_sha256"] = data["steps"][0]["before_sha256"]
    elif invalid == "bool-schema":
        data["schema_version"] = True
    else:
        data["expires_at"] = data["created_at"] + 901
    with pytest.raises((ValueError, TypeError)):
        m.Plan.decode(data)


def test_module_has_no_kernel_or_production_execution_adapter():
    text = (ROOT / "scripts/security/fr06c5_memory_transaction.py").read_text()
    assert "import subprocess" not in text and "os.system" not in text
    assert "def boot_swap_start" not in text and "def rollback_internal" not in text
    assert "No default adapter exists" in text


def test_access_time_updates_do_not_count_as_journal_content_mutation(tmp_path, monkeypatch):
    parent, _, plan, _ = make_case(tmp_path)
    with open_new(parent, plan) as journal:
        original_stat, original_read = os.fstat, os.read
        accessed = set()
        def info(fd):
            value = original_stat(fd)
            if fd in accessed:
                fields = {key: getattr(value, key) for key in dir(value) if key.startswith("st_")}
                fields["st_atime"] += 1
                fields["st_atime_ns"] += 1000000000
                return SimpleNamespace(**fields)
            return value
        def read(fd, size):
            result = original_read(fd, size)
            accessed.add(fd)
            return result
        monkeypatch.setattr(m.os, "fstat", info)
        monkeypatch.setattr(m.os, "read", read)
        assert journal.state().phase == "applying"


@pytest.mark.parametrize("direction", ["apply", "undo"])
def test_lost_outcome_record_keeps_durable_intent_and_reconciliation_is_readonly(tmp_path, monkeypatch, direction):
    parent, files, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        if direction == "undo":
            transaction.apply_next()
            transaction.begin_rollback()
        original = journal._write
        def lose(name, value):
            if value.get("body", {}).get("kind") == "settled":
                raise OSError("Simulated loss before outcome record publication")
            return original(name, value)
        monkeypatch.setattr(journal, "_write", lose)
        with pytest.raises(OSError):
            (transaction.apply_next if direction == "apply" else transaction.undo_next)()
        assert journal.state().pending == (direction, 0)
    effect_log = (files / "effects.log").read_bytes()
    with m.Journal(parent, plan.operation) as journal:
        transaction = m.MemoryTransaction(journal, Files(files, plan))
        transaction.reconcile_pending()
        assert (files / "effects.log").read_bytes() == effect_log
        if direction == "apply":
            transaction.begin_rollback()
            transaction.undo_next()
        assert transaction.verify_restored().phase == "restored"


def test_unowned_after_fingerprint_does_not_authorize_adoption_or_delete(tmp_path, monkeypatch):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        adapter.hook = lambda stage, direction: (_ for _ in ()).throw(OSError("interrupted")) if stage == "after" else None
        with pytest.raises(m.ActionUncertain):
            transaction.apply_next()
        monkeypatch.setattr(adapter, "observe", lambda step, op: m.Observation(step.after_sha256, True, False))
        with pytest.raises(m.TransitionRejected):
            transaction.reconcile_pending()
        assert journal.state().pending == ("apply", 0)
        assert len(adapter.calls) == 1


def test_rollback_receipt_cannot_be_emitted_after_context_changes_at_final_probe(tmp_path):
    parent, _, plan, adapter = make_case(tmp_path, 1)
    with open_new(parent, plan) as journal:
        transaction = m.MemoryTransaction(journal, adapter)
        transaction.begin_rollback()
        original = adapter.observe
        def observe(step, operation):
            result = original(step, operation)
            adapter.ctx = replace(adapter.ctx, boot_id=str(uuid4()))
            return result
        adapter.observe = observe
        with pytest.raises(m.TransitionRejected):
            transaction.verify_restored()
        assert journal.state().phase == "rolling_back"
