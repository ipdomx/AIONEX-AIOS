"""Real Linux file-step effects on owned nonroot fixtures; never live /etc.

The context reader is an explicit lab proof, not a production authority adapter.
No mount, swap, systemctl, external provider or real credential is used.
"""
from __future__ import annotations

import dataclasses
import errno
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.security import fr06c5_memory_config_files as m
from scripts.security import fr06c5_memory_transaction as txm
from scripts.security.fr06c5_memory_boot_plan import SWAP_UNIT, TMP_UNIT

FSTAB = b"# synthetic, owned laboratory only\nUUID=fixture-root / ext4 defaults 0 1\n/swap.img\tnone\tswap\tsw\t0\t0 # preserved annotation\n"
UNITS = {"install_swap_unit": SWAP_UNIT.encode(), "install_tmp_unit": TMP_UNIT.encode()}


def setup(tmp_path):
    root = tmp_path / "owned-root"
    (root / "etc/systemd/system").mkdir(parents=True)
    root.chmod(0o700)
    fstab = root / "etc/fstab"
    fstab.write_bytes(FSTAB)
    fstab.chmod(0o644)
    config = tmp_path / "config-state"
    journals = tmp_path / "journals"
    config.mkdir(mode=0o700)
    journals.mkdir(mode=0o700)
    context = txm.BoundContext("a" * 40, str(uuid4()), str(uuid4()), 36,
                              "b" * 64, "c" * 64, "d" * 64)
    operation = str(uuid4())
    return root, config, journals, context, operation


def plan_for(adapter):
    now = int(time.time())
    return txm.Plan(adapter.operation, adapter.bound_context, adapter.steps, now, now + 900)


def transaction(adapter, journal):
    adapter.attach(journal)
    return txm.MemoryTransaction(journal, adapter)


def all_applied(tx):
    while tx.journal.state().applied < len(tx.plan.steps):
        tx.apply_next()
    assert tx.verify_applied().phase == "applied"


def all_restored(tx):
    if tx.journal.state().phase != "rolling_back":
        tx.begin_rollback()
    while tx.journal.state().applied:
        tx.undo_next()
    assert tx.verify_restored().phase == "restored"


def assert_baseline(root, original):
    assert (root / "etc/fstab").read_bytes() == FSTAB
    current = (root / "etc/fstab").stat()
    assert (current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid, current.st_mtime_ns) == original
    assert not (root / m.TARGETS["install_swap_unit"]).exists()
    assert not (root / m.TARGETS["install_tmp_unit"]).exists()


def identity(path):
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_mtime_ns)


def test_real_three_step_apply_restore_retains_original_inode_and_all_other_bytes(tmp_path):
    root, config, journals, context, operation = setup(tmp_path)
    original = identity(root / "etc/fstab")
    unrelated = root / "etc/unrelated"
    unrelated.write_bytes(b"do not touch\n")
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter:
        assert_baseline(root, original)
        plan = plan_for(adapter)
        with txm.Journal(journals, operation, create=plan) as journal:
            tx = transaction(adapter, journal)
            all_applied(tx)
            for name, content in UNITS.items():
                assert (root / m.TARGETS[name]).read_bytes() == content
            assert (root / "etc/fstab").read_bytes() == m.disable_legacy_fstab(FSTAB, operation)
            # The original exists as exactly the same inode inside private staging.
            spec = adapter.spec["files"]["disable_legacy_fstab"]
            retained = root / "etc" / spec["stage_name"] / "candidate"
            assert identity(retained) == original
            all_restored(tx)
        assert_baseline(root, original)
        assert unrelated.read_bytes() == b"do not touch\n"


@pytest.mark.parametrize("point", [0, 1, 2, 3])
def test_reopen_after_each_completed_step_then_explicit_rollback(tmp_path, point):
    root, config, journals, context, operation = setup(tmp_path)
    original = identity(root / "etc/fstab")
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter:
        plan = plan_for(adapter)
        with txm.Journal(journals, operation, create=plan) as journal:
            tx = transaction(adapter, journal)
            for _ in range(point):
                tx.apply_next()
    with m.ConfigFileAdapter.load(root, config, operation, lambda: context) as adapter, txm.Journal(journals, operation) as journal:
        tx = transaction(adapter, journal)
        assert journal.state().applied == point
        all_restored(tx)
    assert_baseline(root, original)


@pytest.mark.parametrize("step_index", [0, 1, 2])
@pytest.mark.parametrize("direction", ["apply", "undo"])
def test_directory_sync_failure_keeps_intent_without_repeat_or_false_rollback(tmp_path, monkeypatch, step_index, direction):
    root, config, journals, context, operation = setup(tmp_path)
    original = identity(root / "etc/fstab")
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        if direction == "apply":
            for _ in range(step_index):
                tx.apply_next()
        else:
            all_applied(tx)
            tx.begin_rollback()
            for _ in range(2 - step_index):
                tx.undo_next()
        original_fsync = os.fsync
        affected = adapter.parents[adapter.steps[step_index].name]
        def fail(fd):
            if fd == affected:
                raise OSError(errno.EIO, "synthetic directory fsync failure")
            original_fsync(fd)
        with monkeypatch.context() as patch:
            patch.setattr(m.os, "fsync", fail)
            with pytest.raises(txm.ActionUncertain):
                (tx.apply_next if direction == "apply" else tx.undo_next)()
            assert journal.state().pending == (direction, step_index)
            with pytest.raises(txm.ActionUncertain):
                (tx.apply_next if direction == "apply" else tx.undo_next)()
        observed = tx.reconcile_pending()
        assert observed.pending is None
        all_restored(tx)
    assert_baseline(root, original)


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("direction", ["apply", "undo"])
@pytest.mark.parametrize("step_index", [0, 1, 2])
def test_native_process_kill_recovers_owned_files_without_repeating_rename(tmp_path, phase, direction, step_index):
    root, config, journals, context, operation = setup(tmp_path)
    original = identity(root / "etc/fstab")
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)):
        pass
    payload = {"root": str(root), "config": str(config), "journals": str(journals),
               "context": dataclasses.asdict(context), "operation": operation,
               "phase": phase, "direction": direction, "index": step_index}
    child_code = '''import json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts.security import fr06c5_memory_config_files as m
from scripts.security import fr06c5_memory_transaction as t
p=json.loads(sys.argv[2]);context=t.BoundContext(**p['context'])
with m.ConfigFileAdapter.load(Path(p['root']),Path(p['config']),p['operation'],lambda:context) as a, t.Journal(Path(p['journals']),p['operation']) as j:
 a.attach(j);x=t.MemoryTransaction(j,a)
 if p['direction']=='apply':
  for _ in range(p['index']):x.apply_next()
 else:
  for _ in range(3):x.apply_next()
  x.verify_applied();x.begin_rollback()
  for _ in range(2-p['index']):x.undo_next()
 original=m.rename_owned
 def blocked(*args,**kw):
  if p['phase']=='after':original(*args,**kw)
  print('OWNED_CHILD_AT_DURABLE_INTENT',flush=True)
  time.sleep(60)
 m.rename_owned=blocked
 (x.apply_next if p['direction']=='apply' else x.undo_next)()
'''
    process = subprocess.Popen([sys.executable, "-c", child_code, str(ROOT), json.dumps(payload)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 15)[0], "Owned child did not reach barrier"
        assert process.stdout.readline().strip() == "OWNED_CHILD_AT_DURABLE_INTENT"
        # Only this just-created laboratory process is signalled.
        process.send_signal(signal.SIGKILL)
        assert process.wait(timeout=5) == -signal.SIGKILL
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    with m.ConfigFileAdapter.load(root, config, operation, lambda: context) as adapter, txm.Journal(journals, operation) as journal:
        tx = transaction(adapter, journal)
        assert journal.state().pending == (direction, step_index)
        with pytest.raises(txm.ActionUncertain):
            (tx.apply_next if direction == "apply" else tx.undo_next)()
        state = tx.reconcile_pending()
        assert state.phase == ("halted" if direction == "apply" else "rolling_back")
        all_restored(tx)
    assert_baseline(root, original)


@pytest.mark.parametrize("kind", ["target", "stage", "parent", "root", "lock", "manifest", "extra_stage", "hardlink", "permissions"])
def test_changed_or_unowned_resources_deny_before_effect(tmp_path, kind):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        item = adapter.spec["files"]["install_swap_unit"]
        parent = root / "etc/systemd/system"
        staging = parent / item["stage_name"]
        if kind == "target":
            (parent / item["name"]).write_bytes(b"unowned\n")
        elif kind == "stage":
            staging.rename(parent / "displaced-stage")
            staging.mkdir(mode=0o700)
        elif kind == "parent":
            parent.rename(parent.with_name("displaced-parent"))
            parent.mkdir()
        elif kind == "root":
            root.rename(root.with_name("displaced-root"))
            root.mkdir(mode=0o700)
        elif kind == "lock":
            (config / ".config.lock").rename(config / "displaced-lock")
            (config / ".config.lock").touch(mode=0o600)
        elif kind == "manifest":
            with (config / operation / "manifest.json").open("ab") as stream:
                stream.write(b" ")
        elif kind == "extra_stage":
            (staging / "unreviewed").write_bytes(b"x")
        elif kind == "hardlink":
            os.link(staging / "candidate", parent / "unowned-alias")
        else:
            (staging / "candidate").chmod(0o666)
        with pytest.raises((txm.TransitionRejected, OSError)):
            tx.apply_next()
        assert journal.state().pending is None and journal.state().applied == 0


@pytest.mark.parametrize("target", ["fstab", "unit", "parent", "stage"])
def test_symlinks_never_followed(tmp_path, target):
    root, config, _journals, context, operation = setup(tmp_path)
    outside = tmp_path / "unowned-file"
    outside.write_bytes(b"must remain\n")
    if target == "fstab":
        (root / "etc/fstab").unlink()
        (root / "etc/fstab").symlink_to(outside)
    elif target == "unit":
        (root / m.TARGETS["install_tmp_unit"]).symlink_to(outside)
    elif target == "parent":
        system = root / "etc/systemd/system"
        system.rmdir()
        system.symlink_to(tmp_path)
    else:
        (root / "etc/systemd/system" / f".aionex-memory-{operation}-0").symlink_to(tmp_path)
    with pytest.raises((m.FileStepRejected, OSError)):
        m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS)
    assert outside.read_bytes() == b"must remain\n"


def test_journal_intent_is_required_even_for_direct_adapter_calls(tmp_path):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter:
        with pytest.raises(m.FileStepRejected):
            adapter.apply(adapter.steps[0], operation)
        with txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
            adapter.attach(journal)
            with pytest.raises(m.FileStepRejected):
                adapter.apply(adapter.steps[0], operation)
            assert journal.state().pending is None


@pytest.mark.parametrize("change", ["operation", "boot", "source", "generation"])
def test_fresh_bound_context_is_required_before_each_effect(tmp_path, change):
    root, config, journals, context, operation = setup(tmp_path)
    current = [context]
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: current[0], UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        changes = {"operation": {"maintenance_operation": str(uuid4())}, "boot": {"boot_id": str(uuid4())},
                   "source": {"source_commit": "e" * 40}, "generation": {"maintenance_generation": 38}}
        current[0] = dataclasses.replace(context, **changes[change])
        with pytest.raises(m.FileStepRejected):
            tx.apply_next()
        assert journal.state().pending is None


def test_config_lock_serializes_cooperating_operations_and_reopens_after_close(tmp_path):
    root, config, _journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS), pytest.raises(BlockingIOError):
        m.ConfigFileAdapter.load(root, config, operation, lambda: context)
    with m.ConfigFileAdapter.load(root, config, operation, lambda: context) as adapter:
        assert len(adapter.steps) == 3


def test_rename_failure_is_uncertain_until_readonly_reconciliation(tmp_path, monkeypatch):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        def unsupported(*args, **kwargs):
            raise OSError(errno.ENOSYS, "synthetic unsupported syscall")
        with monkeypatch.context() as patch:
            patch.setattr(m, "rename_owned", unsupported)
            with pytest.raises(txm.ActionUncertain):
                tx.apply_next()
        assert tx.reconcile_pending().phase == "halted"
        assert journal.state().applied == 0
        all_restored(tx)


def test_no_replace_keeps_file_created_after_observation(tmp_path, monkeypatch):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        original_rename = m.rename_owned
        def raced(source_fd, source, dest_fd, dest, *, exchange):
            fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644, dir_fd=dest_fd)
            os.write(fd, b"other-writer\n")
            os.close(fd)
            original_rename(source_fd, source, dest_fd, dest, exchange=exchange)
        monkeypatch.setattr(m, "rename_owned", raced)
        with pytest.raises(txm.ActionUncertain):
            tx.apply_next()
        assert (root / m.TARGETS["install_swap_unit"]).read_bytes() == b"other-writer\n"
        with pytest.raises(txm.TransitionRejected):
            tx.reconcile_pending()
        assert journal.state().pending == ("apply", 0)


@pytest.mark.parametrize("entry", [
    b"", b"# no swap\n", b"/swap.img none swap sw 0 0\n/swap.img none swap sw 0 0\n",
    b"/swap.img none swap sw 0 0\n/dev/sda2 none swap sw 0 0\n", b"/swap.img /tmp ext4 defaults 0 0\n",
    b"UUID=alias none swap sw 0 0\n", b"/swap\\056img none swap sw 0 0\n",
    b"/swap.img none swap sw 0\n", b"/swap.img none swap sw 0 0\r\n", b"/swap.img none swap sw 0 0\0\n",
    b"# AIONEX_C5E3_DISABLED old\n/swap.img none swap sw 0 0\n",
])
def test_ambiguous_fstab_is_rejected(entry):
    with pytest.raises(m.FileStepRejected):
        m.disable_legacy_fstab(entry, str(uuid4()))


@pytest.mark.parametrize("entry", [b"/swap.img none swap sw 0 0", b"  /swap.img\tnone\tswap\tsw\t0\t0\n"])
def test_fstab_preserves_indentation_newline_and_comments(entry):
    operation = str(uuid4())
    original = b"# header\n" + entry
    assert m.disable_legacy_fstab(original, operation) == b"# header\n# AIONEX_C5E3_DISABLED " + operation.encode() + b" " + entry


def test_filesystem_adapter_does_not_accept_kernel_or_wrong_operation_steps(tmp_path):
    root, config, _journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter:
        with pytest.raises(m.FileStepRejected):
            adapter.observe(txm.BoundStep("activate_tmpfs", "a" * 64, "b" * 64), operation)
        with pytest.raises(m.FileStepRejected):
            adapter.observe(adapter.steps[0], str(uuid4()))


def test_staging_write_short_chunks_and_reopened_stable_metadata(tmp_path, monkeypatch):
    root, config, _journals, context, operation = setup(tmp_path)
    original_write = os.write
    monkeypatch.setattr(m.os, "write", lambda fd, data: original_write(fd, data[:37]))
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter:
        step = adapter.steps[0]
        for _ in range(3):
            assert adapter.observe(step, operation).fingerprint == step.before_sha256
    with m.ConfigFileAdapter.load(root, config, operation, lambda: context) as adapter:
        assert adapter.steps[0] == step


def test_partial_staging_never_replaced_or_treated_as_complete(tmp_path):
    root, config, _journals, context, operation = setup(tmp_path)
    (root / "etc/fstab").unlink()
    with pytest.raises(m.FileStepRejected):
        m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS)
    assert not (root / m.TARGETS["install_swap_unit"]).exists()
    with pytest.raises(FileExistsError):
        m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS)
    with pytest.raises((m.FileStepRejected, ValueError)):
        m.ConfigFileAdapter.load(root, config, operation, lambda: context)


@pytest.mark.parametrize("step_index", [0, 1, 2])
def test_rollback_refuses_byte_identical_but_different_inode(tmp_path, step_index):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        for _ in range(step_index + 1):
            tx.apply_next()
        target = root / m.TARGETS[adapter.steps[step_index].name]
        content = target.read_bytes()
        original = target.with_name(target.name + ".displaced")
        target.rename(original)
        target.write_bytes(content)
        target.chmod(0o644)
        tx.begin_rollback()
        with pytest.raises(txm.TransitionRejected):
            tx.undo_next()
        assert journal.state().pending is None
        assert target.read_bytes() == content and original.read_bytes() == content


def test_exchange_race_retains_foreign_inode_and_refuses_reconciliation(tmp_path, monkeypatch):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        tx.apply_next()
        tx.apply_next()
        original_rename = m.rename_owned
        original = root / "etc/fstab.original-before-race"
        def raced(source_fd, source, dest_fd, dest, *, exchange):
            assert exchange is True
            target = root / "etc/fstab"
            target.rename(original)
            target.write_bytes(b"unexpected-writer\n")
            target.chmod(0o644)
            original_rename(source_fd, source, dest_fd, dest, exchange=exchange)
        monkeypatch.setattr(m, "rename_owned", raced)
        with pytest.raises(txm.ActionUncertain):
            tx.apply_next()
        spec = adapter.spec["files"]["disable_legacy_fstab"]
        staged = root / "etc" / spec["stage_name"] / "candidate"
        assert staged.read_bytes() == b"unexpected-writer\n"
        assert original.read_bytes() == FSTAB
        with pytest.raises(txm.TransitionRejected):
            tx.reconcile_pending()
        assert journal.state().pending == ("apply", 2)


def test_extended_attributes_require_separate_preservation_review(tmp_path):
    root, config, _journals, context, operation = setup(tmp_path)
    os.setxattr(root / "etc/fstab", "user.synthetic-c5e", b"owned-fixture")
    with pytest.raises(m.FileStepRejected, match="Extended attributes"):
        m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS)
    assert (root / "etc/fstab").read_bytes() == FSTAB


def test_unsupported_renameat2_never_uses_weaker_rename(tmp_path, monkeypatch):
    root, config, journals, context, operation = setup(tmp_path)
    monkeypatch.setattr(m.ctypes, "CDLL", lambda *args, **kwargs: object())
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        with pytest.raises(txm.ActionUncertain):
            tx.apply_next()
        assert not (root / m.TARGETS["install_swap_unit"]).exists()
        assert tx.reconcile_pending().phase == "halted"
        all_restored(tx)


def test_attaching_journal_with_wrong_fingerprints_is_rejected(tmp_path):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter:
        plan = plan_for(adapter)
        forged = dataclasses.replace(plan, steps=(txm.BoundStep("install_swap_unit", "e" * 64, "f" * 64), *plan.steps[1:]))
        with txm.Journal(journals, operation, create=forged) as journal, pytest.raises(m.FileStepRejected, match="fingerprints"):
            adapter.attach(journal)


def test_unknown_configuration_target_is_rejected_before_any_staging(tmp_path):
    root, config, _journals, context, operation = setup(tmp_path)
    with pytest.raises(m.FileStepRejected):
        m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, {**UNITS, "etc/shadow": b"forbidden"})
    assert not (config / operation).exists()


def test_same_operation_staging_cannot_be_automatically_replaced(tmp_path):
    root, config, _journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS):
        pass
    saved = (config / operation / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS)
    assert (config / operation / "manifest.json").read_bytes() == saved


@pytest.mark.parametrize("kind", ["removed", "replaced"])
def test_reopened_adapter_refuses_changed_persistent_lock(tmp_path, kind):
    root, config, _journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS):
        pass
    lock = config / ".config.lock"
    lock.rename(config / "original-lock")
    if kind == "replaced":
        lock.touch(mode=0o600)
    with pytest.raises(m.FileStepRejected):
        m.ConfigFileAdapter.load(root, config, operation, lambda: context)


@pytest.mark.parametrize("changed_index", [0, 2])
def test_other_bound_file_drift_prevents_the_next_file_effect(tmp_path, changed_index):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        tx.apply_next()
        target = root / m.TARGETS[adapter.steps[changed_index].name]
        target.write_bytes(b"another-writer-changed-this\n")
        with pytest.raises(txm.ActionUncertain):
            tx.apply_next()
        assert journal.state().pending == ("apply", 1)
        assert not (root / m.TARGETS["install_tmp_unit"]).exists()
        tx.reconcile_pending()
        tx.begin_rollback()
        with pytest.raises(txm.TransitionRejected):
            tx.undo_next()


def test_adapter_uses_actual_syscall_and_syncs_both_changed_directories(tmp_path, monkeypatch):
    root, config, journals, context, operation = setup(tmp_path)
    with m.ConfigFileAdapter.prepare(root, config, operation, lambda: context, UNITS) as adapter, txm.Journal(journals, operation, create=plan_for(adapter)) as journal:
        tx = transaction(adapter, journal)
        observed = []
        original_sync = os.fsync
        def traced(fd):
            observed.append(fd)
            original_sync(fd)
        monkeypatch.setattr(m.os, "fsync", traced)
        tx.apply_next()
        stage = adapter.stages["install_swap_unit"]
        parent = adapter.parents["install_swap_unit"]
        assert stage in observed and parent in observed
        assert observed.index(stage) < observed.index(parent)
        assert journal.state().pending is None and journal.state().applied == 1
