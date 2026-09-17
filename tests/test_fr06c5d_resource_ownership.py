"""Behavioral isolation tests for C5D attempt-owned host resources.

All payloads are synthetic files under tmp_path. Mounts and systemctl are a
stateful fake; an autouse guard rejects every real subprocess invocation.
"""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import errno
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_real_subprocess(monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected real subprocess in resource ownership test")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def resources(tmp_path, monkeypatch):
    spec = spec_from_file_location(
        "c5d_resource_ownership",
        ROOT / "scripts/security/fr06c5_host_state_cutover.py",
    )
    m = module_from_spec(spec)
    spec.loader.exec_module(m)

    legacy_root = tmp_path / "legacy"
    candidate_root = tmp_path / "candidate"
    source_root = tmp_path / "tracked-systemd"
    unit_root = tmp_path / "systemd"
    for root in (legacy_root, candidate_root, source_root, unit_root):
        root.mkdir()
    (candidate_root / "ssh").mkdir()
    (unit_root / "docker.service.d").mkdir()
    (unit_root / "multi-user.target.wants").mkdir()

    paths = []
    for role, is_file in (
        ("operator", False),
        ("app-secrets", False),
        ("deploy-key", True),
        ("cpanel-key", True),
    ):
        legacy = legacy_root / role
        candidate = (candidate_root / "ssh" / role) if is_file else (candidate_root / role)
        if is_file:
            legacy.write_text("synthetic legacy payload for " + role)
            candidate.write_text("synthetic candidate payload for " + role)
        else:
            legacy.mkdir()
            candidate.mkdir()
        paths.append((role, legacy, candidate, is_file))

    gates = []
    for name, destination in (
        ("aionex-fr06c5-host-state-bind.service",
         unit_root / "aionex-fr06c5-host-state-bind.service"),
        ("34-aionex-fr06c5-host-state-gate.conf",
         unit_root / "docker.service.d" / "34-aionex-fr06c5-host-state-gate.conf"),
    ):
        source = source_root / name
        source.write_text("[Unit]\nDescription=Synthetic isolated test gate\n")
        gates.append((source, destination))

    monkeypatch.setattr(m, "MOUNT", candidate_root)
    monkeypatch.setattr(m, "PATHS", tuple(paths))
    monkeypatch.setattr(m, "SYSTEMD", tuple(gates))
    monkeypatch.setattr(m, "_boot_id", lambda: "synthetic-boot-id")
    unexpected_links = []
    monkeypatch.setattr(m, "_unexpected_unit_links", lambda: list(unexpected_links))

    bases = [
        {
            "id": 10, "target": str(legacy_root), "source": "/dev/fake-legacy",
            "fsroot": "/native", "device": "8:1", "options": ["rw", "relatime"],
        },
        {
            "id": 11, "target": str(candidate_root), "source": "/dev/fake-candidate",
            "fsroot": "/vault", "device": "253:9", "options": ["rw", "relatime"],
        },
    ]
    layers = []
    visible = {}
    candidate_ids = set()
    controls = {}
    events = []
    observations = []
    attempt = tmp_path / "attempt.json"

    def at(path):
        name = str(path)
        if name in visible:
            matches = [row for row in layers if row["id"] == visible[name]]
            assert len(matches) == 1
            return deepcopy(matches[0])
        matches = [
            row for row in bases
            if name == row["target"] or name.startswith(row["target"] + "/")
        ]
        assert matches, "fake mount lookup escaped synthetic source paths"
        return deepcopy(max(matches, key=lambda row: len(row["target"])))

    def mount_rows(target=None):
        if target is not None:
            return [at(target)]
        return deepcopy(bases + layers)

    monkeypatch.setattr(m, "_mount_rows", mount_rows)
    monkeypatch.setattr(m, "_mount_at", at)

    def add_layer(path, *, kind="seal", mount_id=None):
        name = str(path)
        if mount_id is None:
            mount_id = 100 + len(layers)
            while any(row["id"] == mount_id for row in bases + layers):
                mount_id += 1
        if kind == "candidate":
            candidate = next(dst for _, src, dst, _ in paths if str(src) == name)
            base = at(candidate)
            fsroot = str(Path(base["fsroot"]) / candidate.relative_to(Path(base["target"])))
            candidate_ids.add(mount_id)
        else:
            base = bases[0]
            fsroot = str(Path(base["fsroot"]) / Path(path).relative_to(legacy_root))
        row = {
            "id": mount_id, "target": name, "source": base["source"],
            "fsroot": fsroot, "device": base["device"], "options": ["rw"],
        }
        if kind == "foreign":
            row.update(source="/dev/foreign", fsroot="/foreign", device="9:9")
        layers.append(row)
        visible[name] = mount_id
        return row

    def remove_visible(path):
        name = str(path)
        mount_id = visible.pop(name)
        layers[:] = [row for row in layers if row["id"] != mount_id]
        remaining = [row for row in layers if row["target"] == name]
        if remaining:
            visible[name] = remaining[-1]["id"]

    original_stat = os.stat

    def simulated_stat(path, *args, **kwargs):
        if not isinstance(path, int):
            name = os.fspath(path)
            if isinstance(name, str) and visible.get(name) in candidate_ids:
                path = next(dst for _, src, dst, _ in paths if str(src) == name)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(m.os, "stat", simulated_stat)

    def journal():
        return json.loads(attempt.read_text())

    def seal_entry(path):
        return next(
            entry["seal"]
            for entry in journal()["resources"]["legacy"].values()
            if entry["path"] == str(path)
        )

    def fake_run(argv, *args, **kwargs):
        argv = list(map(str, argv))
        events.append(tuple(argv))
        if argv[:2] == ["mount", "--bind"]:
            path = Path(argv[2])
            assert argv[2] == argv[3]
            observed = deepcopy(seal_entry(path))
            observations.append(("bind", observed))
            assert observed["state"] == "create_intent"
            assert observed["owned"] is None
            add_layer(path)
            if controls.get("bind_effect_then_error"):
                raise m.E("synthetic bind reported failure after effect")
            return ""
        if argv[:2] == ["mount", "-o"]:
            path = Path(argv[-1])
            observed = deepcopy(seal_entry(path))
            observations.append(("remount", observed))
            assert observed["state"] == "remount_intent"
            assert observed["owned"]["id"] == visible[str(path)]
            row = next(row for row in layers if row["id"] == visible[str(path)])
            if not controls.get("remount_no_effect"):
                row["options"] = ["ro", "nodev", "nosuid", "noexec"]
            if controls.get("remount_effect_then_error"):
                raise m.E("synthetic remount reported failure after effect")
            return ""
        if argv[0] == "umount":
            path = Path(argv[1])
            observed = deepcopy(seal_entry(path))
            observations.append(("umount", observed))
            assert observed["state"] == "remove_intent"
            assert observed["owned"]["id"] == visible[str(path)]
            if controls.get("umount_busy"):
                raise m.E("synthetic EBUSY")
            if not controls.get("umount_no_effect"):
                remove_visible(path)
            return ""
        if argv == ["systemctl", "daemon-reload"]:
            return ""
        raise AssertionError("unapproved command in isolated resource fake: " + repr(argv))

    monkeypatch.setattr(m, "run", fake_run)

    def begin():
        snapshot = m.capture_resources()
        attempt.write_text(json.dumps({
            "schema_version": 1,
            "phase": "legacy_runtime_stopped",
            "bind_activation_attempted": False,
            "resources": snapshot,
        }))
        attempt.chmod(0o600)
        return snapshot

    def seal_all():
        for _, path, _, _ in paths:
            m.seal(path, attempt)

    return SimpleNamespace(
        m=m, paths=paths, gates=gates, layers=layers, bases=bases,
        visible=visible, controls=controls, events=events,
        observations=observations, attempt=attempt, begin=begin,
        journal=journal, seal_entry=seal_entry, seal_all=seal_all,
        add_layer=add_layer, remove_visible=remove_visible,
        unexpected_links=unexpected_links, tmp=tmp_path,
    )


@pytest.mark.parametrize("path_index,nested", [(2, False), (3, False), (0, True)])
def test_capture_rejects_key_mount_and_nested_mount(resources, path_index, nested):
    s = resources
    path = s.paths[path_index][1]
    if nested:
        path = path / "nested-mount"
    s.add_layer(path, kind="foreign")
    before = deepcopy(s.layers)
    with pytest.raises(s.m.B, match="unexpected mount"):
        s.m.capture_resources()
    assert s.layers == before
    assert s.events == []


@pytest.mark.parametrize("kind", ["matching-gate", "dangling-gate", "dangling-link"])
def test_capture_preserves_preexisting_gate_or_enable_link(resources, kind):
    s = resources
    source, destination = s.gates[0]
    if kind == "matching-gate":
        destination.write_bytes(source.read_bytes())
        prior = destination.lstat()
    elif kind == "dangling-gate":
        destination.symlink_to(s.tmp / "missing-unit")
        prior = destination.lstat()
    else:
        destination = s.m._enable_links()[0][0]
        destination.symlink_to(s.tmp / "missing-unit")
        prior = destination.lstat()
    with pytest.raises(s.m.B, match="preexisting host-state"):
        s.m.capture_resources()
    assert os.path.lexists(destination)
    assert destination.lstat().st_ino == prior.st_ino
    assert s.events == []


def test_capture_rejects_unexpected_runtime_or_alias_link(resources):
    s = resources
    s.unexpected_links.append("/run/systemd/system/synthetic-alias.service")
    with pytest.raises(s.m.B, match="preexisting host-state unit link"):
        s.m.capture_resources()
    assert s.events == []


def test_snapshot_revalidation_detects_new_gate_without_mutation(resources):
    s = resources
    snapshot = s.begin()
    s.gates[-1][1].write_text("foreign gate")
    with pytest.raises(s.m.B, match="preexisting"):
        s.m.validate_resources(snapshot)
    assert s.events == []
    assert s.gates[-1][1].read_text() == "foreign gate"


def test_seal_intent_checkpoint_failure_prevents_mount(resources, monkeypatch):
    s = resources
    s.begin()
    original = s.m._save_resources

    def fail_create_intent(attempt, resource_map):
        if any(entry["seal"]["state"] == "create_intent"
               for entry in resource_map["legacy"].values()):
            raise OSError("synthetic journal failure before mount")
        return original(attempt, resource_map)

    monkeypatch.setattr(s.m, "_save_resources", fail_create_intent)
    with pytest.raises(OSError, match="before mount"):
        s.m.seal(s.paths[0][1], s.attempt)
    assert s.events == []
    assert s.layers == []
    assert s.seal_entry(s.paths[0][1])["state"] == "absent"


def test_seal_and_unseal_journal_intents_are_visible_at_effect_time(resources):
    s = resources
    s.begin()
    s.seal_all()
    assert all(s.seal_entry(path)["state"] == "sealed" for _, path, _, _ in s.paths)
    assert s.m.rollback_resources_preflight(s.attempt) is True
    s.m.unseal_all_checked(s.attempt)
    assert s.layers == []
    assert s.m.verify_legacy_targets(s.attempt) is True
    assert [kind for kind, _ in s.observations].count("bind") == len(s.paths)
    assert [kind for kind, _ in s.observations].count("remount") == len(s.paths)
    assert [kind for kind, _ in s.observations].count("umount") == len(s.paths)
    s.events.clear()
    s.m.unseal_all_checked(s.attempt)
    assert s.events == []


@pytest.mark.parametrize("mode", ["remount_effect_then_error", "remount_no_effect"])
def test_recorded_partial_remount_can_remove_only_its_owned_seal(resources, mode):
    s = resources
    s.begin()
    path = s.paths[2][1]
    s.controls[mode] = True
    with pytest.raises(s.m.E):
        s.m.seal(path, s.attempt)
    recorded = s.seal_entry(path)
    assert recorded["state"] == "remount_intent"
    assert recorded["owned"]["id"] == s.visible[str(path)]
    s.controls.clear()
    s.events.clear()
    s.m.unseal_all_checked(s.attempt)
    assert s.events == [("umount", str(path))]
    assert s.layers == []
    assert s.m.verify_legacy_targets(s.attempt) is True


@pytest.mark.parametrize("failure", ["bind-return", "ownership-checkpoint"])
def test_unrecorded_mount_effect_is_preserved_for_reconciliation(resources, monkeypatch, failure):
    s = resources
    s.begin()
    path = s.paths[0][1]
    if failure == "bind-return":
        s.controls["bind_effect_then_error"] = True
    else:
        original = s.m._save_resources

        def fail_record_owned(attempt, resource_map):
            if resource_map["legacy"]["operator"]["seal"]["state"] == "remount_intent":
                raise OSError("synthetic ownership checkpoint failure")
            return original(attempt, resource_map)

        monkeypatch.setattr(s.m, "_save_resources", fail_record_owned)
    with pytest.raises((s.m.E, OSError)):
        s.m.seal(path, s.attempt)
    assert s.seal_entry(path) == {"state": "create_intent", "owned": None}
    before = deepcopy(s.layers)
    s.events.clear()
    with pytest.raises(s.m.B, match="unrecorded legacy mount"):
        s.m.rollback_resources_preflight(s.attempt)
    with pytest.raises(s.m.B, match="unrecorded legacy mount"):
        s.m.unseal_all_checked(s.attempt)
    assert s.layers == before
    assert s.events == []


def test_hidden_owned_seal_under_valid_candidate_is_visible_to_preflight(resources):
    s = resources
    s.begin()
    path = s.paths[0][1]
    s.m.seal(path, s.attempt)
    owned_id = s.seal_entry(path)["owned"]["id"]
    candidate = s.add_layer(path, kind="candidate", mount_id=20)
    assert candidate["id"] < owned_id
    s.m.update_attempt(s.attempt, phase="bind_activation_started", bind_activation_attempted=True)
    s.events.clear()
    assert s.m.rollback_resources_preflight(s.attempt) is True
    with pytest.raises(s.m.B, match="foreign mount above"):
        s.m.unseal_all_checked(s.attempt)
    assert s.events == []
    s.remove_visible(path)
    s.m.unseal_all_checked(s.attempt)
    assert s.events == [("umount", str(path))]
    assert s.layers == []


def test_valid_candidate_without_attempt_intent_cannot_authorize_cleanup(resources):
    s = resources
    s.begin()
    path = s.paths[0][1]
    s.m.seal(path, s.attempt)
    s.add_layer(path, kind="candidate")
    s.events.clear()
    with pytest.raises(s.m.B, match="foreign mount above"):
        s.m.rollback_resources_preflight(s.attempt)
    assert s.events == []


@pytest.mark.parametrize("foreign_position", ["between", "above"])
def test_foreign_layer_with_hidden_seal_blocks_every_target_before_cleanup(resources, foreign_position):
    s = resources
    s.begin()
    s.seal_all()
    path = s.paths[0][1]
    if foreign_position == "between":
        s.add_layer(path, kind="foreign")
    s.add_layer(path, kind="candidate")
    if foreign_position == "above":
        s.add_layer(path, kind="foreign")
    s.m.update_attempt(s.attempt, phase="bind_activation_started", bind_activation_attempted=True)
    before = deepcopy(s.layers)
    s.events.clear()
    with pytest.raises(s.m.B, match="foreign mount above"):
        s.m.rollback_resources_preflight(s.attempt)
    with pytest.raises(s.m.B):
        s.m.unseal_all_checked(s.attempt)
    assert s.layers == before
    assert s.events == []


def test_last_cleanup_mount_identity_drift_blocks_first_unmount(resources):
    s = resources
    s.begin()
    s.seal_all()
    path = s.paths[1][1]  # app-secrets sorts first and is last in reverse cleanup order.
    row = next(row for row in s.layers if row["id"] == s.visible[str(path)])
    row["fsroot"] = "/foreign-replacement"
    before = deepcopy(s.layers)
    s.events.clear()
    with pytest.raises(s.m.B, match="recorded seal identity changed"):
        s.m.unseal_all_checked(s.attempt)
    assert s.events == []
    assert s.layers == before


@pytest.mark.parametrize("mode", ["umount_busy", "umount_no_effect"])
def test_failed_or_noop_unmount_retains_pending_ownership(resources, mode):
    s = resources
    s.begin()
    path = s.paths[-1][1]
    s.m.seal(path, s.attempt)
    before = deepcopy(s.layers)
    s.controls[mode] = True
    s.events.clear()
    with pytest.raises(s.m.E):
        s.m.unseal_all_checked(s.attempt)
    assert s.events == [("umount", str(path))]
    assert s.layers == before
    assert s.seal_entry(path)["state"] == "remove_intent"
    with pytest.raises(s.m.B, match="legacy mount remained"):
        s.m.verify_legacy_targets(s.attempt)


def test_installed_gates_and_exact_enable_link_are_removed_idempotently(resources):
    s = resources
    s.begin()
    s.m.install_gates(s.attempt)
    for source, destination in s.gates:
        assert destination.read_bytes() == source.read_bytes()
    link, target = s.m._enable_links()[0]
    assert link.is_symlink()
    assert os.readlink(link) == str(target)
    saved = s.journal()["resources"]["enable_links"][str(link)]
    assert saved["owned"]["ino"] == link.lstat().st_ino
    assert s.events == [("systemctl", "daemon-reload")]
    s.events.clear()
    s.m.remove_gates_checked(s.attempt)
    assert all(not os.path.lexists(destination) for _, destination in s.gates)
    assert not os.path.lexists(link)
    assert s.events == [("systemctl", "daemon-reload")]
    assert s.m.verify_legacy_targets(s.attempt) is True
    s.events.clear()
    s.m.remove_gates_checked(s.attempt)
    assert s.events == [("systemctl", "daemon-reload")]


def test_gate_creation_intent_failure_leaves_all_destinations_absent(resources, monkeypatch):
    s = resources
    s.begin()
    original = s.m._save_resources

    def fail_gate_intent(attempt, resource_map):
        if any(entry["state"] == "create_intent" for entry in resource_map["gates"].values()):
            raise OSError("synthetic gate intent checkpoint")
        return original(attempt, resource_map)

    monkeypatch.setattr(s.m, "_save_resources", fail_gate_intent)
    with pytest.raises(OSError, match="gate intent"):
        s.m.install_gates(s.attempt)
    assert all(not os.path.lexists(destination) for _, destination in s.gates)
    assert s.events == []


def test_gate_appearing_after_preflight_is_never_overwritten(resources, monkeypatch):
    s = resources
    s.begin()
    source, destination = s.gates[0]
    original = s.m._save_resources
    injected = []

    def create_foreign_after_intent(attempt, resource_map):
        result = original(attempt, resource_map)
        if resource_map["gates"][str(destination)]["state"] == "create_intent" and not injected:
            destination.write_text("foreign arrived at exclusive-create boundary")
            injected.append(destination.lstat().st_ino)
        return result

    monkeypatch.setattr(s.m, "_save_resources", create_foreign_after_intent)
    with pytest.raises(FileExistsError):
        s.m.install_gates(s.attempt)
    assert destination.read_text() == "foreign arrived at exclusive-create boundary"
    assert destination.lstat().st_ino == injected[0]
    with pytest.raises(s.m.B, match="unowned or replaced"):
        s.m.remove_gates_checked(s.attempt)
    assert s.events == []


def test_same_hash_replacement_at_last_gate_blocks_link_and_first_gate_removal(resources):
    s = resources
    s.begin()
    s.m.install_gates(s.attempt)
    destination = s.gates[0][1]  # Last gate in reverse removal order.
    saved_inode = destination.lstat().st_ino
    replacement = s.tmp / "replacement-gate"
    replacement.write_bytes(destination.read_bytes())
    replacement.chmod(destination.stat().st_mode & 0o777)
    os.replace(replacement, destination)
    assert destination.lstat().st_ino != saved_inode
    original_paths = [dst for _, dst in s.gates] + [s.m._enable_links()[0][0]]
    before = {str(path): path.lstat().st_ino for path in original_paths}
    s.events.clear()
    with pytest.raises(s.m.B, match="unowned or replaced"):
        s.m.remove_gates_checked(s.attempt)
    assert {str(path): path.lstat().st_ino for path in original_paths} == before
    assert s.events == []


def test_current_source_changes_do_not_change_owned_gate_cleanup_fingerprint(resources):
    s = resources
    s.begin()
    s.m.install_gates(s.attempt)
    for source, _ in s.gates:
        source.write_text("tracked source changed after this attempt installed its file")
    s.m.remove_gates_checked(s.attempt)
    assert all(not os.path.lexists(dst) for _, dst in s.gates)
    assert s.m.verify_legacy_targets(s.attempt) is True


@pytest.mark.parametrize("change", ["same-target-new-inode", "new-target"])
def test_enable_link_identity_drift_prevents_all_cleanup(resources, change):
    s = resources
    s.begin()
    s.m.install_gates(s.attempt)
    link, target = s.m._enable_links()[0]
    old_inode = link.lstat().st_ino
    replacement = s.tmp / "replacement-enable-link"
    replacement.symlink_to(target if change == "same-target-new-inode" else s.tmp / "foreign-unit")
    os.replace(replacement, link)
    assert link.lstat().st_ino != old_inode
    expected_target = os.readlink(link)
    s.events.clear()
    with pytest.raises(s.m.B, match="unowned or replaced"):
        s.m.remove_gates_checked(s.attempt)
    assert os.readlink(link) == expected_target
    assert all(dst.exists() for _, dst in s.gates)
    assert s.events == []


@pytest.mark.parametrize("write_mode", ["short", "zero", "partial-error"])
def test_gate_write_loop_handles_short_zero_and_partial_failure(resources, monkeypatch, write_mode):
    s = resources
    path = s.tmp / "write-all-target"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    original_write = os.write
    count = 0
    payload = b"complete synthetic gate payload"

    def controlled_write(target_fd, data):
        nonlocal count
        if target_fd != fd:
            return original_write(target_fd, data)
        count += 1
        if write_mode == "zero":
            return 0
        if write_mode == "partial-error" and count > 1:
            raise OSError(errno.ENOSPC, "synthetic disk full")
        return original_write(target_fd, data[:3])

    monkeypatch.setattr(s.m.os, "write", controlled_write)
    try:
        if write_mode == "short":
            s.m._resource_write_all(fd, payload)
        else:
            with pytest.raises((s.m.E, OSError)):
                s.m._resource_write_all(fd, payload)
    finally:
        os.close(fd)
    expected = payload if write_mode == "short" else b"" if write_mode == "zero" else payload[:3]
    assert path.read_bytes() == expected
    assert count < len(payload) + 2


def test_partial_gate_write_is_recorded_then_safely_removed(resources, monkeypatch):
    s = resources
    s.begin()
    destination = s.gates[0][1]
    original_write = os.write
    failed_once = []

    def fail_only_gate_payload(fd, data):
        fd_path = os.readlink("/proc/self/fd/" + str(fd))
        if fd_path == str(destination):
            if failed_once:
                raise OSError(errno.ENOSPC, "synthetic partial gate payload failure")
            failed_once.append(True)
            return original_write(fd, data[:7])
        return original_write(fd, data)

    monkeypatch.setattr(s.m.os, "write", fail_only_gate_payload)
    with pytest.raises(OSError, match="partial gate"):
        s.m.install_gates(s.attempt)
    saved = s.journal()["resources"]["gates"][str(destination)]
    assert destination.read_bytes() == s.gates[0][0].read_bytes()[:7]
    assert saved["owned"]["size"] == 7
    assert saved["owned"]["sha256"] == s.m.fsha(destination)
    assert saved["state"] == "create_intent"
    assert not os.path.lexists(s.gates[1][1])
    assert s.events == []
    s.m.remove_gates_checked(s.attempt)
    assert not os.path.lexists(destination)
    assert s.events == [("systemctl", "daemon-reload")]


def test_second_gate_source_drift_cleans_only_successful_first_install(resources, monkeypatch):
    s = resources
    s.begin()
    first = s.gates[0][1]
    second_source, second = s.gates[1]
    original = s.m._save_resources
    changed = []

    def drift_second_source_after_first_install(attempt, resource_map):
        result = original(attempt, resource_map)
        if resource_map["gates"][str(first)]["state"] == "installed" and not changed:
            second_source.write_text("synthetic second source drift")
            changed.append(True)
        return result

    monkeypatch.setattr(s.m, "_save_resources", drift_second_source_after_first_install)
    with pytest.raises(s.m.B, match="precondition changed"):
        s.m.install_gates(s.attempt)
    assert first.exists()
    assert not os.path.lexists(second)
    assert not os.path.lexists(s.m._enable_links()[0][0])
    assert s.events == []
    s.m.remove_gates_checked(s.attempt)
    assert not os.path.lexists(first)
    assert s.m.verify_legacy_targets(s.attempt) is True


def test_unrecorded_enable_link_effect_is_preserved(resources, monkeypatch):
    s = resources
    s.begin()
    link, target = s.m._enable_links()[0]
    original = s.m._save_resources

    def fail_link_ownership(attempt, resource_map):
        if resource_map["enable_links"][str(link)]["state"] == "installed":
            raise OSError("synthetic enable-link ownership checkpoint")
        return original(attempt, resource_map)

    monkeypatch.setattr(s.m, "_save_resources", fail_link_ownership)
    with pytest.raises(OSError, match="enable-link ownership"):
        s.m.install_gates(s.attempt)
    assert link.is_symlink()
    assert os.readlink(link) == str(target)
    saved = s.journal()["resources"]["enable_links"][str(link)]
    assert saved["state"] == "create_intent" and saved["owned"] is None
    with pytest.raises(s.m.B, match="unowned or replaced"):
        s.m.remove_gates_checked(s.attempt)
    assert link.is_symlink()
    assert all(dst.exists() for _, dst in s.gates)
    assert s.events == []


def test_boot_change_blocks_resource_cleanup_before_effect(resources, monkeypatch):
    s = resources
    s.begin()
    s.seal_all()
    s.m.install_gates(s.attempt)
    before = deepcopy(s.layers)
    monkeypatch.setattr(s.m, "_boot_id", lambda: "another-boot-id")
    s.events.clear()
    with pytest.raises(s.m.B, match="boot changed"):
        s.m.rollback_resources_preflight(s.attempt)
    with pytest.raises(s.m.B, match="boot changed"):
        s.m.remove_gates_checked(s.attempt)
    assert s.layers == before
    assert all(dst.exists() for _, dst in s.gates)
    assert s.events == []


@pytest.mark.parametrize("which", ["vault-root", "candidate-directory", "candidate-parent", "legacy-root"])
def test_capture_rejects_symlink_roots_and_candidate_ancestors(resources, which):
    s = resources
    if which == "vault-root":
        path = s.m.MOUNT
    elif which == "candidate-directory":
        path = s.paths[0][2]
    elif which == "candidate-parent":
        path = s.paths[2][2].parent
    else:
        path = s.paths[0][1]
    moved = s.tmp / ("original-" + which)
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=True)
    before = path.lstat().st_ino
    with pytest.raises(s.m.B):
        s.m.capture_resources()
    assert path.is_symlink()
    assert path.lstat().st_ino == before
    assert s.events == []


def test_capture_rejects_nested_vault_mount_but_allows_vault_root(resources):
    s = resources
    assert s.m.capture_resources()["schema_version"] == 1
    nested = {
        "id": 777, "target": str(s.m.MOUNT / "unexpected-nested-mount"),
        "source": "/dev/foreign", "fsroot": "/", "device": "9:9",
        "options": ["rw"],
    }
    s.layers.append(nested)
    s.visible[nested["target"]] = nested["id"]
    with pytest.raises(s.m.B):
        s.m.capture_resources()
    assert s.layers == [nested]
    assert s.events == []


def test_candidate_key_absence_is_allowed_before_copy_if_parent_is_real(resources):
    s = resources
    for _, _, candidate, is_file in s.paths:
        if is_file:
            candidate.unlink()
    snapshot = s.m.capture_resources()
    assert snapshot["schema_version"] == 1
    assert s.events == []


def test_candidate_parent_absence_blocks_before_copy(resources):
    s = resources
    parent = s.paths[2][2].parent
    for path in parent.iterdir():
        path.unlink()
    parent.rmdir()
    with pytest.raises((s.m.B, FileNotFoundError)):
        s.m.capture_resources()
    assert s.events == []


@pytest.mark.parametrize("substitution", ["create-foreign", "replace-after-create"])
def test_foreign_symlink_substituted_during_creation_never_becomes_owned(resources, monkeypatch, substitution):
    s = resources
    s.begin()
    link, target = s.m._enable_links()[0]
    foreign_target = s.tmp / "foreign-substituted-unit"
    foreign_target.write_text("synthetic foreign service")
    original_symlink = os.symlink
    substituted_inode = []

    def substitute_link(source, destination, *args, **kwargs):
        assert Path(destination) == link
        assert str(source) == str(target)
        if substitution == "create-foreign":
            original_symlink(str(foreign_target), destination, *args, **kwargs)
        else:
            original_symlink(source, destination, *args, **kwargs)
            replacement = s.tmp / "injected-enable-link"
            original_symlink(str(foreign_target), replacement)
            os.replace(replacement, destination)
        substituted_inode.append(link.lstat().st_ino)

    monkeypatch.setattr(s.m.os, "symlink", substitute_link)
    with pytest.raises(s.m.B):
        s.m.install_gates(s.attempt)
    saved = s.journal()["resources"]["enable_links"][str(link)]
    assert saved["state"] == "create_intent"
    assert saved["owned"] is None
    assert os.readlink(link) == str(foreign_target)
    assert link.lstat().st_ino == substituted_inode[0]
    assert all(destination.exists() for _, destination in s.gates)
    assert s.events == []
    with pytest.raises(s.m.B, match="unowned or replaced"):
        s.m.remove_gates_checked(s.attempt)
    assert link.lstat().st_ino == substituted_inode[0]
    assert os.readlink(link) == str(foreign_target)
    assert all(destination.exists() for _, destination in s.gates)
    assert s.events == []


@pytest.mark.parametrize("changed_option", ["ro", "nodev", "nosuid", "noexec", "ro-to-rw"])
@pytest.mark.parametrize("hidden", [False, True])
def test_completed_seal_option_drift_blocks_preflight_and_all_cleanup(resources, changed_option, hidden):
    s = resources
    s.begin()
    s.seal_all()
    s.m.install_gates(s.attempt)
    path = s.paths[1][1]
    owned = s.seal_entry(path)
    assert owned["state"] == "sealed"
    row = next(row for row in s.layers if row["id"] == owned["owned"]["id"])
    removed_option = "ro" if changed_option == "ro-to-rw" else changed_option
    row["options"].remove(removed_option)
    if changed_option == "ro-to-rw":
        row["options"].append("rw")
    if hidden:
        s.add_layer(path, kind="candidate")
        s.m.update_attempt(s.attempt, phase="bind_activation_started", bind_activation_attempted=True)
    before = deepcopy(s.layers)
    file_paths = [destination for _, destination in s.gates] + [s.m._enable_links()[0][0]]
    file_inodes = {str(path): path.lstat().st_ino for path in file_paths}
    s.events.clear()
    with pytest.raises(s.m.B, match="options"):
        s.m.rollback_resources_preflight(s.attempt)
    with pytest.raises(s.m.B, match="options"):
        s.m.remove_gates_checked(s.attempt)
    with pytest.raises(s.m.B, match="options"):
        s.m.unseal_all_checked(s.attempt)
    assert s.layers == before
    assert {str(path): path.lstat().st_ino for path in file_paths} == file_inodes
    assert s.events == []


@pytest.fixture
def rollback_runtime(resources, monkeypatch):
    """Run root rollback with real resource code and an explicit runtime model.

    Authority is a schema2 journal built from the real captured snapshot. No
    read_attempt/jread/update_attempt/resource validation is bypassed. Only
    service commands and the unrelated policy/health callbacks are simulated.
    """
    s = resources
    snapshot = s.begin()
    monkeypatch.setattr(s.m, "boot_id", s.m._boot_id)
    topology = {
        "containers": [
            {"id": "synthetic-container-a", "name": "synthetic-a",
             "service": "backend", "health": "healthy", "restart": "unless-stopped"},
            {"id": "synthetic-container-b", "name": "synthetic-b",
             "service": "worker", "health": "none", "restart": "on-failure:3"},
        ],
        "services": {
            "backend": ["synthetic-container-a"],
            "worker": ["synthetic-container-b"],
        },
        "container_count": 2,
        "project_worker_scale": 1,
    }
    watch = {"synthetic-runtime-watch.timer": True}
    plan = {
        "schema_version": 2, "subpart": "FR-06C5D",
        "operation": "host-state-cutover", "created_at": s.m.utc(),
        "expires_at": s.m.utc(s.m.now() + s.m.timedelta(seconds=600)),
        "merge_sha": "c" * 40, "evidence_sha256": "d" * 64,
        "topology": topology, "resource_snapshot": snapshot,
        "boot_id": s.m.boot_id(), "nonce": "e" * 64,
        "blind_post_start_rollback_permitted": False,
        "cloudflare_change_permitted": False,
    }
    plan["plan_id"] = s.m.digest(plan)
    s.m.atomic_store(s.attempt, {
        "schema_version": 2, "subpart": "FR-06C5D",
        "plan_id": plan["plan_id"], "merge_sha": plan["merge_sha"],
        "plan": plan, "topology": topology, "boot_id": s.m.boot_id(),
        "watchers": watch, "resources": snapshot,
        "resource_snapshot_sha256": s.m.digest(snapshot),
        "phase": "legacy_runtime_stopped", "created_at": s.m.utc(),
        "candidate_start_attempted": False, "bind_activation_attempted": False,
    })
    s.seal_all()
    s.m.install_gates(s.attempt)
    s.m.update_attempt(s.attempt, phase="gates_installed")
    s.events.clear()
    base_run = s.m.run
    runtime = {"docker": False, "socket": False, "container_ids": [],
               "bind_unit_active": False, "start_snapshots": [], "callbacks": []}

    def assert_resources_gone():
        assert s.layers == []
        assert all(not os.path.lexists(destination) for _, destination in s.gates)
        assert all(not os.path.lexists(link) for link, _ in s.m._enable_links())
        assert s.m.verify_legacy_targets(s.attempt) is True
        journal = s.journal()
        assert journal["candidate_start_attempted"] is False
        for entry in journal["resources"]["legacy"].values():
            assert entry["seal"]["state"] == "removed"
        for section in ("gates", "enable_links"):
            assert all(entry["state"] == "removed"
                       for entry in journal["resources"][section].values())

    def active(unit):
        mapping = {
            "docker.service": runtime["docker"],
            "docker.socket": runtime["socket"],
            "aionex-fr06c5-host-state-bind.service": runtime["bind_unit_active"],
        }
        assert unit in mapping, "unexpected live service probe in rollback integration test"
        return mapping[unit]

    def run(argv, *args, **kwargs):
        argv = list(map(str, argv))
        if argv[:3] == ["systemctl", "start", "docker.socket"]:
            assert argv == ["systemctl", "start", "docker.socket", "docker.service"]
            assert_resources_gone()
            runtime["start_snapshots"].append(deepcopy(s.journal()["resources"]))
            s.events.append(tuple(argv))
            runtime["socket"] = True
            runtime["docker"] = True
            return ""
        if argv == ["systemctl", "stop", "docker.service", "docker.socket"]:
            s.events.append(tuple(argv))
            runtime["docker"] = False
            runtime["socket"] = False
            return ""
        if argv == ["systemctl", "stop", "aionex-fr06c5-host-state-bind.service"]:
            s.events.append(tuple(argv))
            runtime["bind_unit_active"] = False
            return ""
        if argv and argv[0] == "python3" and argv[-1] == "rollback":
            assert Path(argv[1]).name == "fr06c5_host_state_bind.py"
            assert not runtime["docker"]
            s.events.append(tuple(argv))
            # Model the external bind helper removing only visible candidate
            # layers. C5D's resource preflight and seal cleanup remain real.
            for entry in s.journal()["resources"]["legacy"].values():
                path = Path(entry["path"])
                visible = s.m._mount_at(path)
                if visible["id"] != entry["seal"]["owned"]["id"]:
                    assert s.m._candidate_matches(visible, entry)
                    s.remove_visible(path)
            return json.dumps({
                "validation": "FR06C5_HOST_STATE_BIND_REMOVED",
                "restoration_complete": False,
            })
        if argv[:2] == ["docker", "start"]:
            assert runtime["docker"]
            assert_resources_gone()
            assert argv[2:] == [row["id"] for row in topology["containers"]]
            s.events.append(tuple(argv))
            runtime["container_ids"] = argv[2:]
            return ""
        return base_run(argv, *args, **kwargs)

    def policies(actual):
        assert actual == topology
        assert_resources_gone()
        assert runtime["container_ids"] == [row["id"] for row in topology["containers"]]
        runtime["callbacks"].append("policies")

    def watchers(actual):
        assert actual == watch
        assert_resources_gone()
        runtime["callbacks"].append("watchers")

    def acceptance(actual):
        assert actual == topology
        assert_resources_gone()
        assert runtime["callbacks"] == ["policies", "watchers"]
        runtime["callbacks"].append("acceptance")
        return topology

    def set_phase(phase):
        if phase == "bind_active":
            for _, path, _, _ in s.paths:
                s.add_layer(path, kind="candidate")
            runtime["bind_unit_active"] = True
            s.m.update_attempt(s.attempt, phase=phase, bind_activation_attempted=True)
        else:
            assert phase == "gates_installed"
            s.m.update_attempt(s.attempt, phase=phase)
        s.events.clear()

    monkeypatch.setattr(s.m, "active", active)
    monkeypatch.setattr(s.m, "run", run)
    monkeypatch.setattr(s.m, "restore_restart_policies", policies)
    monkeypatch.setattr(s.m, "restore_watchers", watchers)
    monkeypatch.setattr(s.m, "legacy_acceptance", acceptance)
    return SimpleNamespace(
        s=s, topology=topology, watch=watch, runtime=runtime,
        assert_resources_gone=assert_resources_gone, set_phase=set_phase,
    )


@pytest.mark.parametrize("phase", ["gates_installed", "bind_active"])
def test_root_rollback_removes_all_owned_resources_before_legacy_docker_start(rollback_runtime, phase):
    r = rollback_runtime
    s = r.s
    r.set_phase(phase)
    result = s.m.rollback_prestart(r.topology, r.watch, phase, s.attempt)
    assert result["status"] == "legacy_runtime_fully_restored"
    r.assert_resources_gone()
    assert len(r.runtime["start_snapshots"]) == 1
    assert r.runtime["callbacks"] == ["policies", "watchers", "acceptance"]
    first_start = s.events.index(("systemctl", "start", "docker.socket", "docker.service"))
    unmounts = [i for i, event in enumerate(s.events) if event[0] == "umount"]
    assert len(unmounts) == len(s.paths)
    assert max(unmounts) < first_start
    assert ("systemctl", "daemon-reload") in s.events[:first_start]


@pytest.mark.parametrize("phase", ["gates_installed", "bind_active"])
@pytest.mark.parametrize("failure", ["foreign-gate", "foreign-mount", "EBUSY"])
def test_root_rollback_resource_failure_blocks_every_legacy_start(rollback_runtime, phase, failure):
    r = rollback_runtime
    s = r.s
    r.set_phase(phase)
    if failure == "foreign-gate":
        gate = s.gates[0][1]
        replacement = s.tmp / "foreign-rollback-gate"
        replacement.write_bytes(gate.read_bytes())
        replacement.chmod(gate.stat().st_mode & 0o777)
        os.replace(replacement, gate)
    elif failure == "foreign-mount":
        s.add_layer(s.paths[1][1], kind="foreign")
    else:
        s.controls["umount_busy"] = True
    before = deepcopy(s.layers)
    file_paths = [destination for _, destination in s.gates] + [s.m._enable_links()[0][0]]
    file_inodes = {str(path): path.lstat().st_ino for path in file_paths}
    s.events.clear()
    with pytest.raises(s.m.E):
        s.m.rollback_prestart(r.topology, r.watch, phase, s.attempt)
    assert r.runtime["docker"] is False
    assert r.runtime["socket"] is False
    assert r.runtime["container_ids"] == []
    assert r.runtime["start_snapshots"] == []
    assert r.runtime["callbacks"] == []
    assert not any(event[:2] in {("systemctl", "start"), ("docker", "start")} for event in s.events)
    if failure != "EBUSY":
        assert s.layers == before
        assert {str(path): path.lstat().st_ino for path in file_paths} == file_inodes
        assert s.events == []
    else:
        assert len(s.layers) == len(s.paths)
        assert any(event[0] == "umount" for event in s.events)
        assert all(not os.path.lexists(path) for path in file_paths)
