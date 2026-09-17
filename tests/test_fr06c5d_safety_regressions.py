"""Nonroot behavioral checks for the durable C5D transaction boundary.

System lifecycle calls are denied unless a test installs an explicit fake.
Only temporary files and flock locks are real.
"""
from copy import deepcopy
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import json
import os
import stat

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = spec_from_file_location("c5d_transaction", ROOT / "scripts/security/fr06c5_host_state_cutover.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module(tmp_path, monkeypatch):
    m = load_module()
    monkeypatch.setattr(m, "STATE", tmp_path / "state")
    monkeypatch.setattr(m, "private", lambda *args, **kwargs: None)
    monkeypatch.setattr(m, "boot_id", lambda: "synthetic-boot")
    def denied(*args, **kwargs):
        raise AssertionError("unmocked subprocess is forbidden")
    monkeypatch.setattr(m.subprocess, "run", denied)
    return m


@pytest.fixture
def cutover(module, tmp_path, monkeypatch):
    m = module
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    topology = {
        "containers": [{"id": "container-1", "name": "backend-1", "service": "backend",
                        "health": "healthy", "restart": "on-failure:4"}],
        "services": {"backend": ["container-1"]}, "container_count": 1, "project_worker_scale": 1,
    }
    resources = {"synthetic_original": "legacy-identity"}
    body = {
        "schema_version": 2, "subpart": "FR-06C5D", "operation": "host-state-cutover",
        "merge_sha": "b" * 40, "evidence_sha256": "e" * 64,
        "topology": topology, "resource_snapshot": resources, "boot_id": m.boot_id(),
        "created_at": m.utc(), "expires_at": m.utc(m.now() + timedelta(seconds=600)),
        "nonce": "synthetic-plan",
    }
    body["plan_id"] = m.digest(body)
    plan_path = tmp_path / "plan.json"
    m.store(plan_path, body)
    args = SimpleNamespace(
        plan=plan_path, evidence=tmp_path / "evidence.json", merge_sha=body["merge_sha"],
        confirmation="EXECUTE_FR06C5_HOST_STATE_CUTOVER:" + body["plan_id"],
        confirm_production=m.CONFIRM, ttl_seconds=600,
    )
    calls = []
    daemon = {"running": True}
    watch = {"watch.timer": True}
    monkeypatch.setattr(m, "fsha", lambda path: "e" * 64)
    monkeypatch.setattr(m, "gitgate", lambda sha: None)
    monkeypatch.setattr(m, "evidence", lambda *args: {})
    monkeypatch.setattr(m, "c5gate", lambda: None)
    monkeypatch.setattr(m, "topology", lambda: deepcopy(topology))
    monkeypatch.setattr(m, "active", lambda unit: daemon["running"] if unit == "docker.service" else True)
    monkeypatch.setattr(m, "capture_resources", lambda: deepcopy(resources), raising=False)
    monkeypatch.setattr(m, "validate_resources", lambda snapshot: None, raising=False)
    monkeypatch.setattr(m, "reject_nested_mounts", lambda: None)
    monkeypatch.setattr(m, "PATHS", (("synthetic", tmp_path / "legacy", tmp_path / "candidate", False),))
    monkeypatch.setattr(m, "precopy", lambda: calls.append("precopy"))
    monkeypatch.setattr(m, "watcher_states", lambda: dict(watch))
    monkeypatch.setattr(m, "stop_watchers", lambda states: calls.append("stop-watchers"))
    monkeypatch.setattr(m, "restore_watchers", lambda states: calls.append("restore-watchers"))
    monkeypatch.setattr(m, "quiesce_restart_policies", lambda t: calls.append("quiesce-policies"))
    monkeypatch.setattr(m, "restore_restart_policies", lambda t: calls.append("restore-policies"))
    def stop_live(t):
        calls.append("stop-live")
        daemon["running"] = False
    monkeypatch.setattr(m, "stop_live", stop_live)
    monkeypatch.setattr(m, "seal", lambda path, attempt: calls.append("seal"))
    monkeypatch.setattr(m, "exact_copy_and_manifest", lambda: {"synthetic": {"matched": True}})
    monkeypatch.setattr(m, "bootstrap_match", lambda: None)
    monkeypatch.setattr(m, "require_zero_hidden_underlay_fds", lambda: 0)
    monkeypatch.setattr(m, "install_gates", lambda attempt: calls.append("install-gates"))
    monkeypatch.setattr(m, "rollback_resources_preflight", lambda attempt: calls.append("resource-preflight"), raising=False)
    monkeypatch.setattr(m, "remove_gates_checked", lambda attempt: calls.append("remove-gates"))
    monkeypatch.setattr(m, "unseal_all_checked", lambda attempt: calls.append("unseal"))
    monkeypatch.setattr(m, "verify_legacy_targets", lambda attempt: calls.append("verify-legacy"), raising=False)
    monkeypatch.setattr(m, "legacy_acceptance", lambda t: calls.append("legacy-accepted"))
    monkeypatch.setattr(m, "acceptance", lambda t: calls.append("candidate-accepted"))
    def run(argv, *unused, **kwargs):
        command = tuple(argv)
        calls.append(command)
        if argv[0] == "python3" and "fr06c5_host_state_bind.py" in argv[1]:
            if "rollback" in argv:
                return json.dumps({"validation": "FR06C5_HOST_STATE_BIND_REMOVED"})
            if "status" in argv:
                return json.dumps({"validation": "FR06C5_HOST_STATE_BIND_READY"})
        if argv[:4] == ["systemctl", "start", "docker.socket", "docker.service"]:
            daemon["running"] = True
            return ""
        if argv[:4] == ["systemctl", "stop", "docker.service", "docker.socket"]:
            daemon["running"] = False
            return ""
        if argv[:2] == ["docker", "start"]:
            return ""
        if argv[:2] in (["systemctl", "start"], ["systemctl", "stop"]) and argv[2] == "aionex-fr06c5-host-state-bind.service":
            return ""
        raise AssertionError("unexpected fake lifecycle command: " + repr(argv))
    monkeypatch.setattr(m, "run", run)
    return SimpleNamespace(m=m, args=args, plan=body, calls=calls, daemon=daemon,
                           resources=resources, topology=topology, run=run)


def claim(module, planned, **changes):
    data = {
        "schema_version": 2, "subpart": "FR-06C5D", "plan_id": planned["plan_id"],
        "merge_sha": planned["merge_sha"], "plan": deepcopy(planned),
        "topology": deepcopy(planned["topology"]), "boot_id": module.boot_id(),
        "resources": deepcopy(planned["resource_snapshot"]),
        "resource_snapshot_sha256": module.digest(planned["resource_snapshot"]),
        "phase": "claimed", "candidate_start_attempted": False,
    }
    data.update(changes)
    path = module.attempt_path(planned["plan_id"])
    module.store(path, data)
    return path


def test_store_handles_short_writes_and_persists_private_claim(module, tmp_path, monkeypatch):
    original_write = os.write
    monkeypatch.setattr(module.os, "write", lambda fd, data: original_write(fd, data[:3]))
    path = tmp_path / "claim.json"
    module.store(path, {"payload": "abcdef" * 30})
    assert json.loads(path.read_text()) == {"payload": "abcdef" * 30}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        module.store(path, {"replacement": True})


def test_zero_write_retains_failed_claim_and_blocks_replay(module, monkeypatch):
    path = module.attempt_path("a" * 64)
    monkeypatch.setattr(module.os, "write", lambda fd, data: 0)
    with pytest.raises(module.E, match="no progress"):
        module.store(path, {"phase": "claimed"})
    assert path.exists()
    with pytest.raises(module.E):
        module.unresolved_attempt_gate()


def test_atomic_write_failure_preserves_previous_journal(module, tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    module.store(path, {"phase": "before"})
    monkeypatch.setattr(module.os, "write", lambda fd, data: 0)
    with pytest.raises(module.E, match="no progress"):
        module.atomic_store(path, {"phase": "after"})
    assert json.loads(path.read_text()) == {"phase": "before"}
    assert list(tmp_path.glob("*.aionex-new-*")) == []


def test_store_fsyncs_parent_after_file(module, tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    kinds = []
    real_fsync = module.os.fsync
    def tracked(fd):
        kinds.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        real_fsync(fd)
    monkeypatch.setattr(module.os, "fsync", tracked)
    module.store(path, {"persisted": True})
    assert kinds == ["file", "directory"]


def test_lock_refuses_second_open_and_releases_after_exception(module):
    with module.operation_lock():
        with pytest.raises(module.B, match="holds the lock"):
            with module.operation_lock():
                pytest.fail("second lock acquired")
    with pytest.raises(RuntimeError):
        with module.operation_lock():
            raise RuntimeError("synthetic crash")
    with module.operation_lock():
        pass


@pytest.mark.parametrize("identifier", ["../escape", "", "f" * 63, "G" * 64, None])
def test_attempt_path_rejects_non_digest_identifiers(module, identifier):
    with pytest.raises(module.B, match="identifier"):
        module.attempt_path(identifier)


@pytest.mark.parametrize("phase,candidate,verified,allowed", [
    ("failed_before_live_mutation", False, False, True),
    ("legacy_restored_prestart", False, True, True),
    ("legacy_restored_prestart", False, False, False),
    ("accepted", True, False, False),
    ("accepted", False, True, False),
    ("candidate_start_attempted", True, False, False),
    ("rollback_failed", False, False, False),
    ("unknown", False, False, False),
])
def test_only_proven_prestart_terminal_attempts_allow_another_plan(cutover, phase, candidate, verified, allowed):
    s = cutover
    claim(s.m, s.plan, phase=phase, candidate_start_attempted=candidate, rollback_verified=verified)
    if allowed:
        s.m.unresolved_attempt_gate()
    else:
        with pytest.raises(s.m.B):
            s.m.unresolved_attempt_gate()


def test_terminal_attempt_with_changed_authority_is_rejected(cutover):
    s = cutover
    path = claim(s.m, s.plan, phase="failed_before_live_mutation")
    value = json.loads(path.read_text())
    value["topology"] = {}
    path.write_text(json.dumps(value))
    with pytest.raises(s.m.B, match="authority"):
        s.m.unresolved_attempt_gate()


def test_candidate_barrier_cannot_be_cleared(cutover):
    s = cutover
    path = claim(s.m, s.plan, candidate_start_attempted=True)
    with pytest.raises(s.m.B, match="cannot be cleared"):
        s.m.update_attempt(path, candidate_start_attempted=False)
    with pytest.raises(s.m.B, match="authority cannot change"):
        s.m.update_attempt(path, topology={})


def test_every_mutable_apply_gate_runs_under_lock(cutover, monkeypatch):
    s = cutover
    checked = []
    def locked(label):
        def check(*args):
            with pytest.raises(s.m.B, match="holds the lock"):
                with s.m.operation_lock():
                    pytest.fail("gate ran before lock acquisition")
            checked.append(label)
        return check
    monkeypatch.setattr(s.m, "gitgate", locked("git"))
    monkeypatch.setattr(s.m, "evidence", locked("evidence"))
    monkeypatch.setattr(s.m, "c5gate", locked("vault"))
    real_gate = s.m.unresolved_attempt_gate
    def attempts():
        locked("attempts")()
        real_gate()
    monkeypatch.setattr(s.m, "unresolved_attempt_gate", attempts)
    s.m.apply(s.args)
    assert checked == ["git", "evidence", "vault", "attempts", "vault", "git", "evidence"]


def test_success_journal_is_durable_at_candidate_start_call(cutover, monkeypatch):
    s = cutover
    witnessed = []
    def run(argv, *args, **kwargs):
        if argv[:4] == ["systemctl", "start", "docker.socket", "docker.service"]:
            record = json.loads(s.m.attempt_path(s.plan["plan_id"]).read_text())
            assert record["phase"] == "candidate_start_attempted"
            assert record["candidate_start_attempted"] is True
            assert record["topology"] == s.topology
            assert record["plan"] == s.plan
            witnessed.append(True)
        return s.run(argv, *args, **kwargs)
    monkeypatch.setattr(s.m, "run", run)
    result = s.m.apply(s.args)
    assert result["status"] == "encrypted_host_state_started_admission_closed"
    assert witnessed == [True]
    assert json.loads(s.m.attempt_path(s.plan["plan_id"]).read_text())["phase"] == "accepted"


def test_another_plan_cannot_replay_after_accepted_candidate_even_without_binds(cutover):
    s = cutover
    previous = deepcopy(s.plan)
    previous["nonce"] = "prior"
    previous["plan_id"] = s.m.digest({k: v for k, v in previous.items() if k != "plan_id"})
    claim(s.m, previous, phase="accepted", candidate_start_attempted=True)
    with pytest.raises(s.m.B, match="replay barrier"):
        s.m.apply(s.args)
    assert s.calls == []
    assert not s.m.attempt_path(s.plan["plan_id"]).exists()


def test_same_plan_is_consumed_after_pre_live_failure(cutover, monkeypatch):
    s = cutover
    def fail():
        raise s.m.B("synthetic precopy")
    monkeypatch.setattr(s.m, "precopy", fail)
    with pytest.raises(s.m.E, match="before live mutation"):
        s.m.apply(s.args)
    assert s.calls == []
    record = json.loads(s.m.attempt_path(s.plan["plan_id"]).read_text())
    assert record["phase"] == "failed_before_live_mutation"
    with pytest.raises(s.m.B, match="already attempted"):
        s.m.apply(s.args)
    assert s.calls == []


def test_resource_change_after_plan_prevents_claim_and_live_mutation(cutover, monkeypatch):
    s = cutover
    monkeypatch.setattr(s.m, "capture_resources", lambda: {"replacement": True})
    with pytest.raises(s.m.B, match="resources changed"):
        s.m.apply(s.args)
    assert s.calls == []
    assert not s.m.attempt_path(s.plan["plan_id"]).exists()


def test_plan_from_previous_boot_fails_before_claim(cutover, monkeypatch):
    s = cutover
    monkeypatch.setattr(s.m, "boot_id", lambda: "later-boot")
    with pytest.raises(s.m.B, match="another boot"):
        s.m.apply(s.args)
    assert s.calls == []


def test_failed_candidate_marker_write_never_starts_or_rolls_back(cutover, monkeypatch):
    s = cutover
    real_update = s.m.update_attempt
    def update(path, **changes):
        if changes.get("phase") == "candidate_start_attempted":
            raise OSError("synthetic journal failure")
        return real_update(path, **changes)
    monkeypatch.setattr(s.m, "update_attempt", update)
    with pytest.raises(s.m.E, match="blind rollback is prohibited"):
        s.m.apply(s.args)
    assert not any(isinstance(c, tuple) and c[:4] == ("systemctl", "start", "docker.socket", "docker.service") for c in s.calls)
    assert "restore-policies" not in s.calls
    assert "unseal" not in s.calls
    assert json.loads(s.m.attempt_path(s.plan["plan_id"]).read_text())["candidate_start_attempted"] is True


CRASH_PHASES = [
    "precopy_started", "watcher_stop_started", "watchers_stopped",
    "restart_policy_quiesce_started", "restart_policies_quiesced",
    "application_stop_started", "legacy_runtime_stopped", "legacy_seal_started",
    "legacy_sources_sealed", "gate_install_started", "gates_installed",
    "bind_activation_started", "bind_active", "candidate_start_attempted", "accepted",
]


@pytest.mark.parametrize("phase", CRASH_PHASES)
def test_new_process_detects_crash_at_each_durable_phase(cutover, monkeypatch, phase):
    s = cutover
    real_update = s.m.update_attempt
    def update(path, **changes):
        result = real_update(path, **changes)
        if changes.get("phase") == phase:
            raise SystemExit("simulated process loss")
        return result
    monkeypatch.setattr(s.m, "update_attempt", update)
    with pytest.raises(SystemExit, match="process loss"):
        s.m.apply(s.args)
    fresh = load_module()
    fresh.STATE = s.m.STATE
    fresh.private = lambda *args: None
    with pytest.raises(fresh.B):
        fresh.unresolved_attempt_gate()
    with s.m.operation_lock():
        pass


def test_rollback_rejects_foreign_resources_before_any_lifecycle(cutover, monkeypatch):
    s = cutover
    attempt = claim(s.m, s.plan, phase="gate_install_started")
    def foreign(attempt):
        raise s.m.B("foreign resource")
    monkeypatch.setattr(s.m, "rollback_resources_preflight", foreign)
    with pytest.raises(s.m.B, match="foreign"):
        s.m.rollback_prestart(s.topology, {"watch.timer": True}, "gate_install_started", attempt)
    assert s.calls == []


def test_existing_gate_alone_does_not_trigger_docker_stop_or_gate_removal(cutover):
    s = cutover
    attempt = claim(s.m, s.plan, phase="application_stop_started")
    s.m.rollback_prestart(s.topology, {"watch.timer": True}, "application_stop_started", attempt)
    assert "remove-gates" not in s.calls and "unseal" not in s.calls
    assert not any(isinstance(c, tuple) and c[:2] == ("systemctl", "stop") for c in s.calls)
    assert s.calls.index("verify-legacy") < next(i for i, c in enumerate(s.calls) if isinstance(c, tuple) and c[:2] == ("docker", "start"))


def test_rollback_orders_owned_cleanup_and_legacy_identity_before_start(cutover):
    s = cutover
    attempt = claim(s.m, s.plan, phase="bind_active")
    s.daemon["running"] = False
    result = s.m.rollback_prestart(s.topology, {"watch.timer": True}, "bind_active", attempt)
    assert result["status"] == "legacy_runtime_fully_restored"
    ordered = ["resource-preflight", "remove-gates", "unseal", "verify-legacy"]
    positions = [s.calls.index(c) for c in ordered]
    assert positions == sorted(positions)
    docker_start = next(i for i, c in enumerate(s.calls) if isinstance(c, tuple) and c[:4] == ("systemctl", "start", "docker.socket", "docker.service"))
    assert positions[-1] < docker_start < s.calls.index("legacy-accepted")


@pytest.mark.parametrize("helper", ["remove_gates_checked", "unseal_all_checked", "verify_legacy_targets"])
def test_cleanup_failure_never_restarts_legacy(cutover, monkeypatch, helper):
    s = cutover
    attempt = claim(s.m, s.plan, phase="bind_active")
    s.daemon["running"] = False
    def fail(*args):
        raise s.m.B("synthetic ownership failure")
    monkeypatch.setattr(s.m, helper, fail)
    with pytest.raises(s.m.B, match="ownership"):
        s.m.rollback_prestart(s.topology, {}, "bind_active", attempt)
    assert not any(isinstance(c, tuple) and c[:2] in (("docker", "start"), ("systemctl", "start")) for c in s.calls)


def test_failed_restoration_retains_unresolved_journal(cutover, monkeypatch):
    s = cutover
    def stop(t):
        raise s.m.B("partial stop")
    def acceptance(t):
        raise s.m.B("health not restored")
    monkeypatch.setattr(s.m, "stop_live", stop)
    monkeypatch.setattr(s.m, "legacy_acceptance", acceptance)
    with pytest.raises(s.m.E, match="rollback failed"):
        s.m.apply(s.args)
    record = json.loads(s.m.attempt_path(s.plan["plan_id"]).read_text())
    assert record["phase"] == "rollback_failed" and record["rollback_verified"] is False
    with pytest.raises(s.m.B, match="reconciliation"):
        s.m.unresolved_attempt_gate()


@pytest.mark.parametrize("phase", ["unknown", "candidate_start_attempted", "accepted", "rollback_failed"])
def test_unrecognized_or_poststart_phase_has_no_automatic_rollback(cutover, phase):
    s = cutover
    attempt = claim(s.m, s.plan, phase=phase)
    with pytest.raises(s.m.B, match="unknown cutover phase"):
        s.m.rollback_prestart(s.topology, {}, phase, attempt)
    assert s.calls == []

@pytest.mark.parametrize("drift", ["plan-expired", "window-expired", "source", "topology", "plan-replaced"])
def test_authority_drift_during_precopy_cannot_begin_live_mutation(cutover, monkeypatch, drift):
    s = cutover
    after = {"copy": False}
    def precopy():
        s.calls.append("precopy")
        after["copy"] = True
        if drift == "plan-expired":
            frozen = s.m.now() + timedelta(seconds=900)
            monkeypatch.setattr(s.m, "now", lambda: frozen)
        if drift == "plan-replaced":
            alternate = deepcopy(s.plan)
            alternate["nonce"] = "replacement"
            alternate["plan_id"] = s.m.digest({k: v for k, v in alternate.items() if k != "plan_id"})
            s.args.plan.write_text(json.dumps(alternate))
    monkeypatch.setattr(s.m, "precopy", precopy)
    if drift == "window-expired":
        def evidence(*args):
            if after["copy"]:
                raise s.m.B("maintenance window expired")
        monkeypatch.setattr(s.m, "evidence", evidence)
    elif drift == "source":
        def gitgate(*args):
            if after["copy"]:
                raise s.m.B("source advanced")
        monkeypatch.setattr(s.m, "gitgate", gitgate)
    elif drift == "topology":
        monkeypatch.setattr(s.m, "topology", lambda: {} if after["copy"] else deepcopy(s.topology))
    with pytest.raises(s.m.E, match="before live mutation"):
        s.m.apply(s.args)
    assert s.calls == ["precopy"]
    assert json.loads(s.m.attempt_path(s.plan["plan_id"]).read_text())["phase"] == "failed_before_live_mutation"


@pytest.mark.parametrize("changed,value", [
    ("LoadState", "loaded"), ("ActiveState", "active"), ("ActiveState", "activating"),
    ("SubState", "start"), ("FragmentPath", "/old/unit.service"),
    ("DropInPaths", "/old/override.conf"), ("Job", "99"), ("LoadState", "error"),
])
def test_preexisting_bind_unit_blocks_adoption(module, monkeypatch, changed, value):
    props = {"LoadState": "not-found", "ActiveState": "inactive", "SubState": "dead",
             "FragmentPath": "", "DropInPaths": "", "Job": ""}
    props[changed] = value
    monkeypatch.setattr(module, "run", lambda argv: "\n".join(k + "=" + v for k, v in props.items()))
    with pytest.raises(module.B, match="preexisting or pending"):
        module.bind_unit_preflight()


def test_missing_inactive_bind_unit_is_accepted(module, monkeypatch):
    monkeypatch.setattr(module, "run", lambda argv: "LoadState=not-found\nActiveState=inactive\nSubState=dead\nFragmentPath=\nDropInPaths=\nJob=")
    module.bind_unit_preflight()
