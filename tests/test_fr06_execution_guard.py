"""Isolated kernel-lock and journal tests; no Docker, provider, GitHub or host effects."""
from __future__ import annotations

import copy
import importlib.util
import json
import multiprocessing
import os
import stat
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/security/fr06_execution_guard.py"
spec = importlib.util.spec_from_file_location("fr06_guard_tested", SOURCE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
SHA = "7" * 40
TARGET = "8" * 40
BINDING = m.Binding(SHA, SHA, "00000000-0000-4000-8000-000000000001",
                    "00000000-0000-4000-8000-000000000002", 41, True, "closed")
RESULT = m.ObservedResult("observed_complete", "9" * 64)


@pytest.fixture
def directory(tmp_path):
    p = tmp_path / "private-guard"
    p.mkdir(mode=0o700)
    return p


def guard(directory, name="interactive-one", invocation="interactive"):
    return m.ExecutionGuard(directory, run_id=name, invocation_type=invocation)


def perform(g, **kwargs):
    values = dict(action="source_merge", target_commit=TARGET, expected=BINDING,
                  observe=lambda: BINDING, invoke=lambda: RESULT)
    values.update(kwargs)
    return g.perform(**values)


def raw_records(directory):
    return [json.loads(line) for line in (directory / "effects.jsonl").read_text().splitlines()]


def test_observations_and_callback_happen_while_lock_is_held(directory):
    calls = []
    with guard(directory) as g:
        def observe():
            with pytest.raises(m.ConcurrentOwner):
                with guard(directory, "competing-observer", "watchdog"):
                    pass
            calls.append("observe")
            return BINDING
        def invoke():
            with pytest.raises(m.ConcurrentOwner):
                with guard(directory, "competing-executor", "scheduled"):
                    pass
            assert g.pending()["kind"] == "intent"
            calls.append("effect")
            return RESULT
        ack = perform(g, observe=observe, invoke=invoke)
        assert ack["payload"]["outcome"] == "observed_complete"
        assert g.pending() is None
    assert calls == ["observe", "observe", "effect"]
    rows = raw_records(directory)
    assert [r["kind"] for r in rows] == ["intent", "result"]
    assert rows[1]["previous"] == rows[0]["sha256"]
    assert rows[0]["payload"]["binding"] == asdict(BINDING)
    for p in directory.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    with guard(directory, "next-scheduled", "scheduled") as next_guard:
        perform(next_guard)
    assert len(raw_records(directory)) == 4


@pytest.mark.parametrize("field,value", [
    ("source_commit", "$head"), ("main_commit", "0" * 40), ("source_commit", None),
    ("source_clean", False), ("source_clean", 1), ("generation", True),
    ("generation", 7), ("generation", "41"), ("boot_id", "unknown"),
    ("operation_id", "unknown"), ("maintenance_status", "open"),
])
def test_invalid_expected_context_never_writes_intent_or_calls_effect(directory, field, value):
    calls = []
    with guard(directory) as g:
        with pytest.raises(m.GuardBlocked):
            perform(g, expected=replace(BINDING, **{field: value}), invoke=lambda: calls.append(1))
        assert g.pending() is None
    assert calls == [] and raw_records(directory) == []


@pytest.mark.parametrize("field,value", [
    ("source_commit", "0" * 40), ("main_commit", "0" * 40), ("source_clean", False),
    ("boot_id", "00000000-0000-4000-8000-000000000003"),
    ("operation_id", "00000000-0000-4000-8000-000000000004"),
    ("generation", 42), ("maintenance_status", "open"),
])
@pytest.mark.parametrize("phase", ["before_intent", "after_intent"])
def test_context_drift_prevents_effect_and_never_replays(directory, field, value, phase):
    calls = []
    changed = replace(BINDING, **{field: value})
    snapshots = iter([changed] if phase == "before_intent" else [BINDING, changed])
    with guard(directory) as g:
        with pytest.raises(m.GuardBlocked, match="context"):
            perform(g, observe=lambda: next(snapshots), invoke=lambda: calls.append(1))
    assert calls == []
    with guard(directory, "later") as g:
        if phase == "after_intent":
            assert g.pending() is not None
            with pytest.raises(m.UncertainEffect):
                perform(g, invoke=lambda: calls.append(2))
        else:
            assert g.pending() is None
    assert calls == []


@pytest.mark.parametrize("outcome,digest", [("unknown", "9"*64), ("observed_complete", "$digest"),
    ("timeout", "9"*64), ("observed_no_effect", "short")])
def test_unproven_callback_outcome_preserves_uncertainty(directory, outcome, digest):
    with guard(directory) as g:
        with pytest.raises(m.GuardBlocked):
            perform(g, invoke=lambda: m.ObservedResult(outcome, digest))
    with guard(directory, "different") as g:
        assert g.pending() is not None
        with pytest.raises(m.UncertainEffect):
            perform(g)
    assert len(raw_records(directory)) == 1


def test_callback_exception_stays_uncertain_without_replay(directory):
    called = []
    def timeout():
        called.append(1)
        raise TimeoutError("synthetic unknown outcome")
    with guard(directory) as g:
        with pytest.raises(TimeoutError):
            perform(g, invoke=timeout)
    before = (directory / "effects.jsonl").read_bytes()
    for invocation in ("watchdog", "scheduled", "interactive"):
        with guard(directory, "later-" + invocation, invocation) as g:
            with pytest.raises(m.UncertainEffect):
                perform(g, invoke=timeout)
    assert called == [1]
    assert (directory / "effects.jsonl").read_bytes() == before


def test_no_effect_result_is_explicit_and_not_a_retry(directory):
    with guard(directory) as g:
        perform(g, invoke=lambda: m.ObservedResult("observed_no_effect", "a" * 64))
    with guard(directory, "second") as g:
        perform(g)
    r = raw_records(directory)
    assert r[1]["payload"]["outcome"] == "observed_no_effect"
    assert r[0]["payload"]["request_id"] != r[2]["payload"]["request_id"]


@pytest.mark.parametrize("name", ["$dir", "new\nrun", "../run", "a" * 121, ""])
def test_bad_run_identity_rejected_without_files(directory, name):
    with pytest.raises(m.GuardBlocked):
        guard(directory, name)
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize("invocation", ["scheduled-success", "unknown", ""])
def test_invalid_invocation_rejected(directory, invocation):
    with pytest.raises(m.GuardBlocked):
        guard(directory, invocation=invocation)


@pytest.mark.parametrize("action,target", [("shell", TARGET), ("source_merge", "$head"),
    ("reboot", TARGET), ("source_merge", "a" * 39)])
def test_unknown_actions_and_targets_are_not_recorded(directory, action, target):
    with guard(directory) as g:
        with pytest.raises(m.GuardBlocked):
            perform(g, action=action, target_commit=target)
    assert raw_records(directory) == []


def test_guard_not_usable_outside_context_or_reusable(directory):
    g = guard(directory)
    with pytest.raises(m.GuardBlocked):
        perform(g)
    with g:
        perform(g)
    with pytest.raises(m.GuardBlocked):
        perform(g)
    with pytest.raises(m.GuardBlocked):
        with g:
            pass


@pytest.mark.parametrize("name", ["execution.lock", "effects.jsonl"])
def test_symlinks_never_followed(directory, name):
    victim = directory.parent / "unrelated"
    victim.write_text("preserve")
    (directory / name).symlink_to(victim)
    with pytest.raises((m.GuardBlocked, OSError)):
        with guard(directory):
            pass
    assert victim.read_text() == "preserve"


@pytest.mark.parametrize("name", ["execution.lock", "effects.jsonl"])
def test_hardlinks_rejected(directory, name):
    victim = directory.parent / "unrelated"
    victim.write_text("")
    victim.chmod(0o600)
    os.link(victim, directory / name)
    with pytest.raises(m.GuardBlocked):
        with guard(directory):
            pass
    assert victim.read_text() == ""


@pytest.mark.parametrize("name", ["execution.lock", "effects.jsonl"])
def test_untrusted_file_permissions_rejected(directory, name):
    p = directory / name
    p.write_text("")
    p.chmod(0o644)
    with pytest.raises(m.GuardBlocked):
        with guard(directory):
            pass


def test_directory_symlink_or_untrusted_mode_rejected(directory):
    link = directory.parent / "alias"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises((m.GuardBlocked, OSError)):
        with guard(link):
            pass
    directory.chmod(0o755)
    with pytest.raises(m.GuardBlocked):
        with guard(directory):
            pass


def test_directory_absence_never_provisions_a_production_root(directory):
    absent = directory / "absent"
    with pytest.raises(OSError):
        with guard(absent):
            pass
    assert not absent.exists()


@pytest.mark.parametrize("name", ["execution.lock", "effects.jsonl"])
def test_replaced_path_is_not_accepted_as_same_lock(directory, name):
    calls = []
    with guard(directory) as g:
        p = directory / name
        p.rename(directory / (name + ".preserved"))
        p.write_text("")
        p.chmod(0o600)
        with pytest.raises(m.GuardBlocked):
            perform(g, invoke=lambda: calls.append(1))
    assert calls == []


def test_root_rename_is_detected_before_effect(directory):
    calls = []
    with guard(directory) as g:
        directory.rename(directory.parent / "preserved-root")
        directory.mkdir(mode=0o700)
        with pytest.raises(m.GuardBlocked):
            perform(g, invoke=lambda: calls.append(1))
    assert calls == []


@pytest.mark.parametrize("suffix", [b'{"partial":', b'garbage\n', b'\n', b'\xff\n'])
def test_partial_or_corrupt_tail_blocks_without_truncation(directory, suffix):
    with guard(directory) as g:
        perform(g)
    p = directory / "effects.jsonl"
    p.write_bytes(p.read_bytes() + suffix)
    original = p.read_bytes()
    with pytest.raises(m.GuardBlocked):
        with guard(directory, "reconcile"):
            pass
    assert p.read_bytes() == original


def test_chain_tampering_blocks(directory):
    with guard(directory) as g:
        perform(g)
    p = directory / "effects.jsonl"
    rows = raw_records(directory)
    rows[0]["payload"]["binding"]["generation"] = 42
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(m.GuardBlocked, match="chain"):
        with guard(directory):
            pass


def test_duplicate_fields_are_not_accepted(directory):
    with guard(directory) as g:
        perform(g)
    p = directory / "effects.jsonl"
    raw = p.read_bytes().replace(b'"sequence":1', b'"sequence":1,"sequence":1', 1)
    p.write_bytes(raw)
    with pytest.raises(m.GuardBlocked, match="duplicate"):
        with guard(directory):
            pass


def test_short_writes_are_fully_persisted(directory, monkeypatch):
    real = os.write
    monkeypatch.setattr(m.os, "write", lambda fd, b: real(fd, b[:17]))
    with guard(directory) as g:
        perform(g)
    with guard(directory, "reader") as g:
        assert g.pending() is None
    assert len(raw_records(directory)) == 2


def test_intent_fsync_failure_prevents_effect(directory, monkeypatch):
    calls = []
    with guard(directory) as g:
        real = os.fsync
        def broken(fd):
            if fd == g._journal:
                raise OSError("synthetic disk failure")
            return real(fd)
        with monkeypatch.context() as p:
            p.setattr(m.os, "fsync", broken)
            with pytest.raises(OSError):
                perform(g, invoke=lambda: calls.append(1))
    assert calls == []
    with guard(directory, "recovery") as g:
        with pytest.raises(m.UncertainEffect):
            perform(g)


def _probe_competitor(directory, connection):
    try:
        with guard(directory, "child-watchdog", "watchdog"):
            connection.send("acquired")
    except m.ConcurrentOwner:
        connection.send("concurrent_owner")
    except BaseException as exc:
        connection.send(type(exc).__name__)
    finally:
        connection.close()


def _crash_after_intent(directory, connection):
    with guard(directory, "crash-scheduled", "scheduled") as g:
        def crash():
            connection.send("intent-durable")
            connection.close()
            os._exit(23)
        perform(g, invoke=crash)


def _forked_guard_use(g, connection):
    try:
        perform(g)
        connection.send("unexpected-effect")
    except m.GuardBlocked:
        connection.send("process-mismatch")
    finally:
        g._close()
        connection.close()


def test_real_processes_contend_on_one_kernel_lock(directory):
    ctx = multiprocessing.get_context("fork")
    with guard(directory) as g:
        parent, child = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_probe_competitor, args=(directory, child))
        process.start(); child.close()
        try:
            assert parent.poll(5), "competitor did not report"
            assert parent.recv() == "concurrent_owner"
            process.join(5)
            assert process.exitcode == 0
            perform(g)
        finally:
            if process.is_alive():
                process.terminate(); process.join(5)
            parent.close()
    with guard(directory, "after-release", "scheduled") as successor:
        perform(successor)


def test_process_death_releases_lock_but_not_unknown_intent(directory):
    ctx = multiprocessing.get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_crash_after_intent, args=(directory, child))
    process.start(); child.close()
    try:
        assert parent.poll(5), "crash process did not record intent"
        assert parent.recv() == "intent-durable"
        process.join(5)
        assert process.exitcode == 23
        calls = []
        with guard(directory, "post-crash", "watchdog") as g:
            assert g.pending()["run_id"] == "crash-scheduled"
            with pytest.raises(m.UncertainEffect):
                perform(g, invoke=lambda: calls.append(1))
        assert calls == []
    finally:
        if process.is_alive():
            process.terminate(); process.join(5)
        parent.close()


def test_inherited_guard_is_not_authority_and_child_cannot_unlock_parent(directory):
    ctx = multiprocessing.get_context("fork")
    with guard(directory) as g:
        parent, child = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_forked_guard_use, args=(g, child))
        process.start(); child.close()
        try:
            assert parent.poll(5)
            assert parent.recv() == "process-mismatch"
            process.join(5)
            assert process.exitcode == 0
            with pytest.raises(m.ConcurrentOwner):
                with guard(directory, "still-locked"):
                    pass
            perform(g)
        finally:
            if process.is_alive():
                process.terminate(); process.join(5)
            parent.close()


def test_no_production_runner_or_installation_is_present():
    source = SOURCE.read_text()
    assert "import subprocess" not in source
    assert "os.system" not in source
    assert "__main__" not in source
    assert "flock" in source and "LOCK_NB" in source


@pytest.mark.parametrize("part,path,value", [
    (0, ("invocation_type",), []),
    (0, ("payload", "action"), {}),
    (1, ("payload", "outcome"), []),
])
def test_malformed_rehashed_journal_uses_explicit_fail_closed_error(directory, part, path, value):
    with guard(directory) as g:
        perform(g)
    rows = raw_records(directory)
    obj = rows[part]
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    previous = "0" * 64
    for row in rows:
        row["previous"] = previous
        row["sha256"] = m._digest({k: v for k, v in row.items() if k != "sha256"})
        previous = row["sha256"]
    p = directory / "effects.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    original = p.read_bytes()
    with pytest.raises(m.GuardBlocked):
        with guard(directory):
            pass
    assert p.read_bytes() == original


def test_nonfinite_journal_is_explicitly_blocked(directory):
    with guard(directory) as g:
        perform(g)
    p = directory / "effects.jsonl"
    rows = raw_records(directory)
    rows[0]["payload"]["target_commit"] = float("nan")
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(m.GuardBlocked):
        with guard(directory):
            pass


@pytest.mark.parametrize("bad", [[], {}])
def test_malformed_invocation_has_no_side_effect(directory, bad):
    with pytest.raises(m.GuardBlocked):
        guard(directory, invocation=bad)
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize("bad", [[], {}])
def test_malformed_action_has_no_intent(directory, bad):
    with guard(directory) as g:
        with pytest.raises(m.GuardBlocked):
            perform(g, action=bad)
        assert g.pending() is None


def test_lock_descriptors_close_on_exec(directory):
    import fcntl
    with guard(directory) as g:
        for fd in (g._root, g._lock, g._journal):
            assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
