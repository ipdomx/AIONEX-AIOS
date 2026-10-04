"""C5E13 source-only tests; live systemd is never invoked."""
from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.security import fr06c5_memory_systemd_reload as m
from scripts.security import fr06c5_memory_transaction as txm
from scripts.security.fr06c5_memory_boot_plan import SWAP_UNIT, TMP_UNIT


class FakeManager:
    def __init__(self, root: Path):
        self.root = root
        self.need_reload = True
        self.calls: list[str] = []
        self.failure: str | None = None
        self.journal = None

    def snapshot(self, units: tuple[str, ...]) -> m.ManagerSnapshot:
        assert units == tuple(m.UNIT_PATHS)
        observed = []
        for name in units:
            path = str(self.root / m.UNIT_PATHS[name])
            observed.append(
                m.UnitState(
                    name=name,
                    load_state="not-found" if self.need_reload else "loaded",
                    fragment_path="" if self.need_reload else path,
                    need_daemon_reload=self.need_reload,
                )
            )
        return m.ManagerSnapshot(self.need_reload, tuple(observed))

    def daemon_reload(self) -> None:
        assert self.journal is not None
        assert self.journal.state().pending == ("apply", 0)
        self.calls.append("daemon-reload")
        if self.failure == "before":
            raise OSError("synthetic pre-effect reload failure")
        self.need_reload = False
        if self.failure == "after":
            raise OSError("synthetic acknowledgement failure")


def make_case(tmp_path):
    root = tmp_path / "owned-root"
    units = root / "etc/systemd/system"
    units.mkdir(parents=True)
    root.chmod(0o700)
    for name, payload in (
        ("aionex-fr06c5-encrypted-swap.service", SWAP_UNIT),
        ("tmp.mount", TMP_UNIT),
    ):
        path = units / name
        path.write_text(payload)
        path.chmod(0o644)
    state = tmp_path / "state"
    journals = tmp_path / "journals"
    state.mkdir(mode=0o700)
    journals.mkdir(mode=0o700)
    context = txm.BoundContext(
        "a" * 40,
        str(uuid4()),
        str(uuid4()),
        41,
        "b" * 64,
        "c" * 64,
        "d" * 64,
    )
    operation = str(uuid4())
    manager = FakeManager(root)
    return SimpleNamespace(
        root=root,
        state=state,
        journals=journals,
        context=context,
        operation=operation,
        manager=manager,
    )


def prepare(case):
    return m.SystemdReloadAdapter.prepare(
        root=case.root,
        state_parent=case.state,
        operation=case.operation,
        context=lambda: case.context,
        manager=case.manager,
    )


def load(case):
    return m.SystemdReloadAdapter.load(
        root=case.root,
        state_parent=case.state,
        operation=case.operation,
        context=lambda: case.context,
        manager=case.manager,
    )


def plan(adapter):
    now = int(time.time())
    return txm.Plan(
        adapter.operation,
        adapter.bound,
        (adapter.step,),
        now - 1,
        now + 600,
    )


def attach(case, adapter, journal):
    adapter.attach(journal)
    case.manager.journal = journal
    return txm.MemoryTransaction(journal, adapter)


def test_reload_is_durable_intent_bound_and_independently_read_back(tmp_path):
    case = make_case(tmp_path)
    adapter = prepare(case)
    with txm.Journal(
        case.journals, case.operation, create=plan(adapter)
    ) as journal:
        transaction = attach(case, adapter, journal)
        result = transaction.apply_next()
        assert result.applied == 1
        assert case.manager.calls == ["daemon-reload"]
        assert case.manager.need_reload is False
        assert transaction.verify_applied().phase == "applied"
        observed = adapter.observe(adapter.step, case.operation)
        assert observed.identity_verified is True
        assert observed.owned_by_operation is True
        assert observed.fingerprint == adapter.step.after_sha256


@pytest.mark.parametrize(
    ("failure", "expected_after"),
    [("before", False), ("after", True)],
)
def test_uncertain_reload_reconciles_by_readback_without_replay(
    tmp_path, failure, expected_after
):
    case = make_case(tmp_path)
    adapter = prepare(case)
    with txm.Journal(
        case.journals, case.operation, create=plan(adapter)
    ) as journal:
        transaction = attach(case, adapter, journal)
        case.manager.failure = failure
        with pytest.raises(txm.ActionUncertain):
            transaction.apply_next()
        assert journal.state().pending == ("apply", 0)
        assert case.manager.calls == ["daemon-reload"]
    case.manager.failure = None
    with txm.Journal(case.journals, case.operation) as journal:
        adapter = load(case)
        transaction = attach(case, adapter, journal)
        before = list(case.manager.calls)
        reconciled = transaction.reconcile_pending()
        assert case.manager.calls == before
        assert reconciled.pending is None
        assert reconciled.applied == int(expected_after)
        assert reconciled.phase == "halted"


def test_reload_has_no_fabricated_inverse(tmp_path):
    case = make_case(tmp_path)
    adapter = prepare(case)
    with txm.Journal(
        case.journals, case.operation, create=plan(adapter)
    ) as journal:
        transaction = attach(case, adapter, journal)
        transaction.apply_next()
        transaction.verify_applied()
        transaction.begin_rollback()
        with pytest.raises(txm.ActionUncertain):
            transaction.undo_next()
        assert case.manager.calls == ["daemon-reload"]
        assert journal.state().pending == ("undo", 0)


def test_unit_replacement_after_binding_blocks_before_reload(tmp_path):
    case = make_case(tmp_path)
    adapter = prepare(case)
    target = case.root / m.UNIT_PATHS["tmp.mount"]
    replacement = target.with_name("tmp.mount.replacement")
    replacement.write_text(TMP_UNIT)
    replacement.chmod(0o644)
    os.replace(replacement, target)
    with txm.Journal(
        case.journals, case.operation, create=plan(adapter)
    ) as journal:
        transaction = attach(case, adapter, journal)
        with pytest.raises(m.ReloadStepRejected):
            transaction.apply_next()
        assert case.manager.calls == []
        assert journal.state().pending is None


def test_context_drift_blocks_effect_before_intent(tmp_path):
    case = make_case(tmp_path)
    adapter = prepare(case)
    case.context = dataclasses.replace(
        case.context, maintenance_generation=42
    )
    with txm.Journal(
        case.journals, case.operation, create=plan(adapter)
    ) as journal:
        transaction = attach(case, adapter, journal)
        with pytest.raises(m.ReloadStepRejected):
            transaction.apply_next()
        assert case.manager.calls == []
        assert journal.state().pending is None


def test_prepare_requires_pre_reload_manager_state(tmp_path):
    case = make_case(tmp_path)
    case.manager.need_reload = False
    with pytest.raises(m.ReloadStepRejected, match="pre-reload"):
        prepare(case)


def test_binding_tamper_is_not_repaired_or_adopted(tmp_path):
    case = make_case(tmp_path)
    prepare(case)
    binding = case.state / ("reload-" + case.operation) / "binding.json"
    original = binding.read_bytes()
    replacement = str(uuid4()).encode("ascii")
    tampered = original.replace(case.operation.encode("ascii"), replacement, 1)
    assert tampered != original
    binding.write_bytes(tampered)
    with pytest.raises(m.ReloadStepRejected):
        load(case)


def test_systemctl_backend_uses_exact_commands_with_fake_runner_only():
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        if args[1:3] == ["show", "--property=NeedDaemonReload"]:
            return SimpleNamespace(
                returncode=0,
                stdout="NeedDaemonReload=no\n",
                stderr="",
            )
        if args == ["/usr/bin/systemctl", "daemon-reload"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        unit = args[2]
        return SimpleNamespace(
            returncode=0,
            stdout=(
                f"Id={unit}\n"
                "LoadState=loaded\n"
                f"FragmentPath=/etc/systemd/system/{unit}\n"
                "NeedDaemonReload=no\n"
            ),
            stderr="",
        )

    backend = m.SystemctlManager(runner=runner)
    snap = backend.snapshot(tuple(m.UNIT_PATHS))
    assert snap.manager_need_daemon_reload is False
    assert all(item.load_state == "loaded" for item in snap.units)
    backend.daemon_reload()
    assert calls[-1] == ["/usr/bin/systemctl", "daemon-reload"]
    assert all(kwargs is not None for kwargs in [calls])


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "NeedDaemonReload=maybe\n",
        "NeedDaemonReload=yes\nNeedDaemonReload=no\n",
        "Other=no\n",
    ],
)
def test_systemctl_property_parser_rejects_ambiguous_manager_output(raw):
    if "maybe" in raw:
        with pytest.raises(m.ReloadStepRejected):
            m.SystemctlManager._bool("maybe")
    else:
        with pytest.raises(m.ReloadStepRejected):
            m.SystemctlManager._properties(raw, {"NeedDaemonReload"})


def test_adapter_rejects_direct_effect_without_pending_journal_intent(tmp_path):
    case = make_case(tmp_path)
    adapter = prepare(case)
    with pytest.raises(m.ReloadStepRejected):
        adapter.apply(adapter.step, case.operation)
    assert case.manager.calls == []


def test_unit_file_mode_change_blocks_reload(tmp_path):
    case = make_case(tmp_path)
    adapter = prepare(case)
    target = case.root / m.UNIT_PATHS["tmp.mount"]
    target.chmod(0o600)
    with txm.Journal(
        case.journals, case.operation, create=plan(adapter)
    ) as journal:
        transaction = attach(case, adapter, journal)
        with pytest.raises(m.ReloadStepRejected):
            transaction.apply_next()
        assert case.manager.calls == []


def test_postcondition_requires_exact_fragment_paths(tmp_path):
    case = make_case(tmp_path)

    class WrongFragment(FakeManager):
        def snapshot(self, units):
            base = super().snapshot(units)
            if self.need_reload:
                return base
            changed = list(base.units)
            changed[0] = dataclasses.replace(
                changed[0], fragment_path="/etc/systemd/system/foreign.service"
            )
            return m.ManagerSnapshot(False, tuple(changed))

    case.manager = WrongFragment(case.root)
    adapter = prepare(case)
    with txm.Journal(
        case.journals, case.operation, create=plan(adapter)
    ) as journal:
        transaction = attach(case, adapter, journal)
        with pytest.raises(txm.ActionUncertain):
            transaction.apply_next()
        assert case.manager.calls == ["daemon-reload"]
        assert journal.state().pending == ("apply", 0)
