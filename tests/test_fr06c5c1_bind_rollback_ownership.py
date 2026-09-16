"""Behavioral host-state bind rollback tests; no real host commands are allowed."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bind(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "fr06c5_bind_ownership", ROOT / "scripts/security/fr06c5_host_state_bind.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def denied(*args, **kwargs):
        pytest.fail(f"unexpected real subprocess: {args!r}")

    monkeypatch.setattr(module.subprocess, "run", denied)
    monkeypatch.setattr(module, "active", lambda unit: False)
    return module


def simulated_pair(bind, monkeypatch, tmp_path, initial="owned"):
    source = tmp_path / "source"
    target = tmp_path / "legacy"
    source.mkdir()
    target.mkdir()
    state = {"mount": initial}
    monkeypatch.setattr(bind, "PAIRS", ((source, target, False),))
    monkeypatch.setattr(bind, "exact_mount", lambda dst: state["mount"] != "absent")
    monkeypatch.setattr(bind, "same", lambda src, dst: state["mount"] == "owned")
    monkeypatch.setattr(bind, "sealed_underlay", lambda dst: state["mount"] == "seal")
    return source, target, state


def test_existing_legacy_seal_is_preserved_without_claiming_full_restoration(
    bind, monkeypatch, tmp_path
):
    _, target, state = simulated_pair(bind, monkeypatch, tmp_path, "seal")
    result = bind.rollback()
    assert state["mount"] == "seal"
    assert result["removed_bind_targets"] == []
    assert result["preserved_legacy_seals"] == [str(target)]
    assert result["restoration_complete"] is False
    assert result["status"] == "owned_host_state_binds_removed"


def test_foreign_mount_blocks_before_any_owned_mount_is_removed(
    bind, monkeypatch, tmp_path
):
    foreign = tmp_path / "foreign"
    owned = tmp_path / "owned"
    monkeypatch.setattr(
        bind, "PAIRS",
        ((tmp_path / "source1", foreign, False),
         (tmp_path / "source2", owned, False)),
    )
    monkeypatch.setattr(bind, "exact_mount", lambda dst: True)
    monkeypatch.setattr(bind, "same", lambda src, dst: dst == owned)
    monkeypatch.setattr(bind, "sealed_underlay", lambda dst: False)
    with pytest.raises(bind.B, match="unexpected host-state mount preserved"):
        bind.rollback()


def test_busy_owned_mount_failure_is_not_reported_as_restored(
    bind, monkeypatch, tmp_path
):
    _, target, state = simulated_pair(bind, monkeypatch, tmp_path)
    commands = []

    def busy(args, **kwargs):
        commands.append(args)
        assert args == ["umount", str(target)]
        return subprocess.CompletedProcess(args, 32, "", "target is busy")

    monkeypatch.setattr(bind.subprocess, "run", busy)
    with pytest.raises(bind.B, match="umount failed"):
        bind.rollback()
    assert commands == [["umount", str(target)]]
    assert state["mount"] == "owned"


@pytest.mark.parametrize("exposed", ["seal", "absent"])
def test_owned_mount_is_removed_once_and_exposed_seal_is_preserved(
    bind, monkeypatch, tmp_path, exposed
):
    _, target, state = simulated_pair(bind, monkeypatch, tmp_path)
    commands = []

    def unmount(args, **kwargs):
        commands.append(args)
        assert args == ["umount", str(target)]
        state["mount"] = exposed
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bind.subprocess, "run", unmount)
    result = bind.rollback()
    assert result["validation"] == "FR06C5_HOST_STATE_BIND_REMOVED"
    assert result["removed_bind_targets"] == [str(target)]
    assert result["preserved_legacy_seals"] == (
        [str(target)] if exposed == "seal" else []
    )
    assert result["restoration_complete"] is False
    assert bind.rollback()["removed_bind_targets"] == []
    assert state["mount"] == exposed
    assert commands == [["umount", str(target)]]


def test_successful_umount_exit_still_requires_owned_mount_to_disappear(
    bind, monkeypatch, tmp_path
):
    _, target, state = simulated_pair(bind, monkeypatch, tmp_path)

    def ineffective(args, **kwargs):
        assert args == ["umount", str(target)]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bind.subprocess, "run", ineffective)
    with pytest.raises(bind.B, match="owned host-state bind remained"):
        bind.rollback()
    assert state["mount"] == "owned"


def test_foreign_mount_revealed_after_owned_unbind_is_never_unmounted(
    bind, monkeypatch, tmp_path
):
    _, target, state = simulated_pair(bind, monkeypatch, tmp_path)
    commands = []

    def unmount(args, **kwargs):
        commands.append(args)
        assert args == ["umount", str(target)]
        state["mount"] = "foreign"
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bind.subprocess, "run", unmount)
    with pytest.raises(bind.B, match="unexpected host-state mount preserved after"):
        bind.rollback()
    assert state["mount"] == "foreign"
    assert commands == [["umount", str(target)]]


@pytest.mark.parametrize(
    "filesystem_root,device,options,accepted",
    [
        ("/root/.config/aionex", "8:1", "ro,nodev,nosuid,noexec", True),
        ("/unrelated", "8:1", "ro,nodev,nosuid,noexec", False),
        ("/root/.config/aionex", "253:1", "ro,nodev,nosuid,noexec", False),
        ("/root/.config/aionex", "8:1", "rw,nodev,nosuid,noexec", False),
    ],
)
def test_only_a_read_only_bind_of_the_original_legacy_path_is_a_seal(
    bind, monkeypatch, filesystem_root, device, options, accepted
):
    target = Path("/root/.config/aionex")
    parent = {"target": "/", "fsroot": "/", "maj:min": "8:1", "options": "rw"}
    current = {
        "target": str(target), "fsroot": filesystem_root,
        "maj:min": device, "options": options,
    }
    monkeypatch.setattr(bind, "exact_mount", lambda dst: True)
    monkeypatch.setattr(
        bind, "mount_record", lambda dst: current if dst == target else parent
    )
    assert bind.sealed_underlay(target) is accepted


def test_seal_identity_accounts_for_the_parent_filesystem_root(bind, monkeypatch):
    target = Path("/root/.config/aionex")
    parent = {
        "target": "/root", "fsroot": "/isolated-root",
        "maj:min": "8:2", "options": "rw",
    }
    current = {
        "target": str(target), "fsroot": "/isolated-root/.config/aionex",
        "maj:min": "8:2", "options": "ro,nodev,nosuid,noexec",
    }
    monkeypatch.setattr(bind, "exact_mount", lambda dst: True)
    monkeypatch.setattr(
        bind, "mount_record", lambda dst: current if dst == target else parent
    )
    assert bind.sealed_underlay(target) is True


def test_unreadable_seal_identity_fails_closed(bind, monkeypatch):
    monkeypatch.setattr(bind, "exact_mount", lambda dst: True)

    def unavailable(dst):
        raise bind.B("findmnt failed")

    monkeypatch.setattr(bind, "mount_record", unavailable)
    assert bind.sealed_underlay(Path("/root/.config/aionex")) is False


def test_malformed_mount_record_is_rejected(bind, monkeypatch):
    monkeypatch.setattr(bind, "run", lambda args: '{"filesystems": [{"target": "/"}]}')
    with pytest.raises(bind.B, match="mount identity unavailable"):
        bind.mount_record(Path("/root/.config/aionex"))


@pytest.mark.parametrize("busy_cleanup", [False, True])
def test_partial_bind_attempt_cleanup_uses_ownership_and_propagates_failure(
    bind, monkeypatch, tmp_path, busy_cleanup
):
    source, target, state = simulated_pair(bind, monkeypatch, tmp_path, "seal")
    monkeypatch.setattr(bind.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bind, "vault_ready", lambda: None)
    commands = []

    def command(args, timeout=60):
        commands.append(args)
        if args == ["mount", "--bind", str(source), str(target)]:
            state["mount"] = "owned"
            raise bind.B("simulated failure after bind took effect")
        assert args == ["umount", str(target)]
        if busy_cleanup:
            raise bind.B("umount failed")
        state["mount"] = "seal"
        return ""

    monkeypatch.setattr(bind, "run", command)
    message = (
        "owned-bind cleanup incomplete" if busy_cleanup
        else "simulated failure after bind took effect"
    )
    with pytest.raises(bind.B, match=message):
        bind.apply()
    assert state["mount"] == ("owned" if busy_cleanup else "seal")
    assert commands == [
        ["mount", "--bind", str(source), str(target)],
        ["umount", str(target)],
    ]


def test_apply_rejects_and_preserves_unexpected_existing_mount(
    bind, monkeypatch, tmp_path
):
    _, _, state = simulated_pair(bind, monkeypatch, tmp_path, "foreign")
    monkeypatch.setattr(bind.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bind, "vault_ready", lambda: None)
    with pytest.raises(bind.B, match="without accepted read-only seal"):
        bind.apply()
    assert state["mount"] == "foreign"
