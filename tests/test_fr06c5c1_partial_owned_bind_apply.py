"""FR06C5 partial-mount maintenance: preserve pre-owned encrypted binds and never unbind them.

All operations use a temporary in-memory mount simulator; no real mount/umount,
Docker stop or private identity content is touched by this test module.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06c5_host_state_bind.py"


def setup_bind(monkeypatch, tmp_path, initial=("owned", "owned", "seal", "seal"), *, drift=None):
    spec = importlib.util.spec_from_file_location("fr06c5_partial_bind_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pairs = []
    states = {}
    for idx in range(4):
        directory = idx < 2
        src = tmp_path / f"vault-{idx}"
        dst = tmp_path / f"legacy-{idx}"
        if directory:
            src.mkdir()
            dst.mkdir()
        else:
            src.write_text("synthetic-only")
            dst.write_text("synthetic-only")
        readonly = not directory
        pairs.append((src, dst, readonly))
        states[str(dst)] = initial[idx]

    calls = []
    monkeypatch.setattr(mod, "PAIRS", tuple(pairs))
    monkeypatch.setattr(mod.os, "geteuid", lambda: 0)
    monkeypatch.setattr(mod, "active", lambda _: False)
    monkeypatch.setattr(mod, "vault_ready", lambda: None)
    monkeypatch.setattr(mod, "exact_mount", lambda dst: states[str(dst)] != "absent")
    monkeypatch.setattr(mod, "same", lambda src, dst: states[str(dst)] == "owned")
    monkeypatch.setattr(mod, "sealed_underlay", lambda dst: states[str(dst)] == "seal")
    monkeypatch.setattr(mod, "status", lambda require=False: {"status": "ready", "validation": "FR06C5_HOST_STATE_BIND_READY"} if all(x == "owned" for x in states.values()) else (_ for _ in ()).throw(AssertionError("incomplete mount")))

    def fake_run(argv, *args, **kwargs):
        calls.append(tuple(argv))
        if argv[0] == "findmnt":
            destination = argv[-1]
            if drift == destination:
                return "rw"
            return "ro,nodev,nosuid,noexec" if any(str(d) == destination and ro for _, d, ro in pairs) else "rw,nodev,nosuid,noexec"
        if argv[:2] == ["mount", "--bind"]:
            target = argv[3]
            assert states[target] in ("seal", "absent")
            states[target] = "owned"
            return ""
        if argv[0] == "mount" and argv[1] == "-o":
            target = argv[-1]
            assert states[target] == "owned"
            return ""
        if argv[0] == "umount":
            target = argv[-1]
            assert states[target] == "owned"
            states[target] = "seal"
            return ""
        pytest.fail(f"unexpected simulated command: {argv!r}")

    monkeypatch.setattr(mod, "run", fake_run)
    return mod, pairs, states, calls


def test_apply_preserves_two_existing_encrypted_directory_binds(monkeypatch, tmp_path):
    mod, pairs, states, calls = setup_bind(monkeypatch, tmp_path)
    result = mod.apply()
    assert result["validation"] == "FR06C5_HOST_STATE_BIND_READY"
    assert list(states.values()) == ["owned"] * 4
    mounted = [call for call in calls if call[:2] == ("mount", "--bind")]
    assert [call[3] for call in mounted] == [str(pairs[2][1]), str(pairs[3][1])]
    assert not any(str(pairs[0][1]) in call or str(pairs[1][1]) in call for call in mounted)
    assert len([call for call in calls if call[:2] == ("mount", "-o")]) == 2


def test_foreign_fourth_target_blocks_before_attempting_third(monkeypatch, tmp_path):
    mod, pairs, states, calls = setup_bind(monkeypatch, tmp_path, ("owned", "owned", "seal", "foreign"))
    with pytest.raises(mod.B, match="without accepted read-only seal"):
        mod.apply()
    assert list(states.values()) == ["owned", "owned", "seal", "foreign"]
    assert not any(call[0] in ("mount", "umount") for call in calls)


def test_existing_owned_bind_with_incorrect_options_fails_closed(monkeypatch, tmp_path):
    mod, pairs, states, calls = setup_bind(monkeypatch, tmp_path, drift=str(tmp_path / "legacy-0"))
    with pytest.raises(mod.B, match="options drifted"):
        mod.apply()
    assert list(states.values()) == ["owned", "owned", "seal", "seal"]
    assert not any(call[0] in ("mount", "umount") for call in calls)


def test_failed_new_file_bind_rolls_back_only_new_mount(monkeypatch, tmp_path):
    mod, pairs, states, calls = setup_bind(monkeypatch, tmp_path)
    original_run = mod.run

    def fail_once(argv, *args, **kwargs):
        if argv[:2] == ["mount", "--bind"] and argv[-1] == str(pairs[2][1]):
            original_run(argv)
            raise mod.B("synthetic failure after owned bind")
        return original_run(argv, *args, **kwargs)

    monkeypatch.setattr(mod, "run", fail_once)
    with pytest.raises(mod.B, match="synthetic failure after owned bind"):
        mod.apply()
    assert list(states.values()) == ["owned", "owned", "seal", "seal"]
    assert ("umount", str(pairs[2][1])) in calls
    assert not any(call[0] == "umount" and call[1] in (str(pairs[0][1]), str(pairs[1][1])) for call in calls)


def test_docker_running_blocks_even_idempotent_apply(monkeypatch, tmp_path):
    mod, pairs, states, calls = setup_bind(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "active", lambda name: name == "docker.service")
    with pytest.raises(mod.B, match="Docker must be stopped"):
        mod.apply()
    assert not calls


def test_repeated_apply_is_a_noop_when_all_four_owned_binds_are_valid(monkeypatch, tmp_path):
    mod, pairs, states, calls = setup_bind(monkeypatch, tmp_path, ("owned",) * 4)
    result = mod.apply()
    assert result["validation"] == "FR06C5_HOST_STATE_BIND_READY"
    assert len([call for call in calls if call[0] == "findmnt"]) == 4
    assert not any(call[0] in ("mount", "umount") for call in calls)
    assert list(states.values()) == ["owned"] * 4


def test_failure_on_final_new_mount_rolls_back_only_new_targets(monkeypatch, tmp_path):
    mod, pairs, states, calls = setup_bind(monkeypatch, tmp_path)
    initial = mod.run

    def fail_final(argv, *args, **kwargs):
        if argv[:2] == ["mount", "--bind"] and argv[-1] == str(pairs[3][1]):
            initial(argv, *args, **kwargs)
            raise mod.B("final synthetic mount refused")
        return initial(argv, *args, **kwargs)

    monkeypatch.setattr(mod, "run", fail_final)
    with pytest.raises(mod.B, match="final synthetic mount refused"):
        mod.apply()
    assert list(states.values()) == ["owned", "owned", "seal", "seal"]
    unmounted = [item[1] for item in calls if item[0] == "umount"]
    assert unmounted == [str(pairs[3][1]), str(pairs[2][1])]
