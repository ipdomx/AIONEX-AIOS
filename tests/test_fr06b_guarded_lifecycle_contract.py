from __future__ import annotations

import argparse
import fcntl
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts" / "security" / "fr06b_guarded_lifecycle.py"
LAB = ROOT / "scripts" / "security" / "fr06b_guarded_lifecycle_lab.py"
CONTRACT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B3B-guarded-lifecycle-contract.json"
)
PROOF = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B3B-isolated-guarded-lifecycle.json"
)
B2 = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B2-compose-cutover-contract.json"
)
B3A = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B3A-admission-restart-contract.json"
)
RECEIPT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B3B-guarded-lifecycle.md"
)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _module():
    spec = importlib.util.spec_from_file_location("fr06b3b_test_module", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _admission_inputs(tmp_path: Path) -> tuple[dict, dict]:
    b2 = _json(B2)
    asset_names = sorted(
        item["target_subpath"]
        for item in b2["matrix"]["roots"]
        if item["vault"] == "asset-vault"
    )
    project_names = ["project_execution_data"]
    docker_host = f"unix://{tmp_path}/docker.sock"
    snapshot = {
        "schema_version": 1,
        "subpart": "FR-06B3A",
        "validation": "FR06B3A_RUNTIME_SNAPSHOT_PASS",
        "environment": "isolated_lab",
        "observed_at": _now(),
        "docker_host": docker_host,
        "mappers": [
            {
                "role": "asset-vault",
                "path": "/dev/mapper/fr06b3b-test-asset",
                "active": True,
                "block_device": True,
                "filesystem": "ext4",
                "mount_root": str(tmp_path / "candidate" / "asset-vault"),
                "mount_source_matches": True,
                "mount_options": ["rw", "nodev", "nosuid", "noexec"],
                "required_options_present": True,
                "forbidden_options_absent": True,
                "subpaths_present": asset_names,
            },
            {
                "role": "project-execution-vault",
                "path": "/dev/mapper/fr06b3b-test-project",
                "active": True,
                "block_device": True,
                "filesystem": "ext4",
                "mount_root": str(
                    tmp_path / "candidate" / "project-execution-vault"
                ),
                "mount_source_matches": True,
                "mount_options": ["rw", "nodev", "nosuid"],
                "required_options_present": True,
                "forbidden_options_absent": True,
                "subpaths_present": project_names,
            },
        ],
        "volumes": [
            {
                "role": "asset-vault",
                "name": "fr06b3b-test-asset",
                "device": "/dev/mapper/fr06b3b-test-asset",
                "driver": "local",
                "type": "ext4",
                "options": ["nodev", "nosuid", "noexec"],
                "running_consumer_count": 0,
            },
            {
                "role": "project-execution-vault",
                "name": "fr06b3b-test-project",
                "device": "/dev/mapper/fr06b3b-test-project",
                "driver": "local",
                "type": "ext4",
                "options": ["nodev", "nosuid"],
                "running_consumer_count": 0,
            },
        ],
        "compose": {
            "fr06b2_validation": "FR06B2_COMPOSE_OVERLAY_PASS",
            "restart_validation": "FR06B3A_RESTART_OVERLAY_PASS",
            "guarded_restart_policy": "no",
            "guarded_service_count": 20,
            "initializer_service_count": 2,
            "all_profiles": True,
        },
        "read_only_inspection": True,
        "containers_started_or_created": False,
        "vaults_mounted_or_unlocked": False,
    }
    evidence = {
        "schema_version": 1,
        "environment": "isolated_lab",
        "observed_at": _now(),
        "production_authorization": False,
        "safety": {
            "out_of_band_alert_passed": False,
            "boot_rehearsal_passed": False,
            "docker_restart_rehearsal_passed": True,
            "missing_mapper_rehearsal_passed": True,
            "wrong_key_rehearsal_passed": True,
            "delayed_unlock_rehearsal_passed": True,
            "pre_admission_rollback_passed": True,
            "post_admission_reverse_delta_rollback_passed": True,
        },
        "operations": {
            "admission_closed": True,
            "queues_drained": True,
            "writers_stopped": True,
            "initializers_stopped": True,
            "read_only_consumers_stopped": True,
            "no_unlisted_writable_descriptors": True,
            "final_delta_exact": True,
            "cloudflare_changed": False,
        },
        "source": {"lab_commit_sha": "a" * 40},
    }
    return evidence, snapshot


def _plan_fixture(tmp_path: Path) -> argparse.Namespace:
    module = _module()
    b2 = _json(B2)
    runtime_services = sorted(
        set(b2["matrix"]["runtime_writer_services"])
        | set(b2["matrix"]["read_only_only_services"])
    )
    sources: dict[str, str] = {}
    targets: dict[str, str] = {}
    for row in b2["matrix"]["roots"]:
        name = row["compose_volume"]
        source = tmp_path / "legacy" / name
        target = tmp_path / "candidate" / row["vault"] / row["target_subpath"]
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "payload.txt").write_text(name, encoding="utf-8")
        sources[name] = str(source)
        targets[name] = str(target)
    runtime_path = tmp_path / "runtime.json"
    module._write_json_atomic(
        runtime_path,
        {
            "schema_version": 1,
            "services": {
                service: {
                    "instances": [f"{service}-1"],
                    "running": True,
                    "desired": True,
                    "mount_mode": "legacy",
                    "restart_policy": "unless-stopped",
                }
                for service in runtime_services
            },
            "unlisted_consumers": [],
            "unlisted_writers": [],
            "fail_phase": None,
        },
    )
    evidence, snapshot = _admission_inputs(tmp_path)
    evidence_path = tmp_path / "evidence.json"
    snapshot_path = tmp_path / "snapshot.json"
    layout_path = tmp_path / "layout.json"
    env_file = tmp_path / "lab.env"
    module._write_json_atomic(evidence_path, evidence)
    module._write_json_atomic(snapshot_path, snapshot)
    module._write_json_atomic(
        layout_path,
        {
            "schema_version": 1,
            "sandbox_root": str(tmp_path),
            "runtime_state": str(runtime_path),
            "source_roots": sources,
            "target_roots": targets,
        },
    )
    env_file.write_text("LAB=1\n", encoding="utf-8")
    return argparse.Namespace(
        root=ROOT,
        evidence=evidence_path,
        snapshot=snapshot_path,
        state_dir=tmp_path / "state",
        env_file=env_file,
        docker_host=snapshot["docker_host"],
        max_age_seconds=900,
        allow_isolated_lab=True,
        lab_layout=layout_path,
        ttl_seconds=600,
    )


def test_contract_preserves_exact_scope_and_closed_terminal_state() -> None:
    contract = _json(CONTRACT)
    scope = contract["scope"]
    assert contract["subpart"] == "FR-06B3B"
    assert scope["protected_root_count"] == 11
    assert scope["protected_mount_count"] == 54
    assert scope["runtime_writer_service_definition_count"] == 18
    assert scope["read_only_only_service_definition_count"] == 2
    assert scope["initializer_service_definition_count"] == 2
    assert scope["guarded_runtime_service_definition_count"] == 20
    assert contract["invariant"]["success_terminal_state"] == (
        "candidate_started_admission_closed"
    )
    assert contract["invariant"]["opens_application_admission"] is False
    assert contract["invariant"]["changes_cloudflare"] is False
    assert contract["invariant"]["creates_or_unlocks_vaults"] is False


def test_contract_requires_single_use_dual_confirmation_and_exact_binding() -> None:
    binding = _json(CONTRACT)["admission_binding"]
    assert binding["evidence_and_snapshot_hash_bound_into_plan"] is True
    assert binding["contract_hash_bound_into_plan"] is True
    assert binding["maximum_plan_ttl_seconds"] == 900
    assert binding["one_time_plan_nonce"] is True
    assert binding["exclusive_nonblocking_lock"] is True
    assert binding["one_time_reservation_written_before_first_mutation"] is True
    assert binding["exact_dynamic_confirmation_required"] is True
    assert binding["second_fixed_production_confirmation_required"] is True


def test_contract_handles_reboot_lost_seals_without_weakening_admission() -> None:
    contract = _json(CONTRACT)
    guarded = contract["guarded_start"]
    rollback = contract["manual_rollback"]
    assert guarded["legacy_seal_layout_must_match_cutover_receipt"] is True
    assert guarded["missing_or_partial_seals_after_reboot_reestablished_under_lock"] is True
    assert guarded["reseal_requires_quiescent_legacy_and_candidate_roots"] is True
    assert guarded["resealed_legacy_manifest_must_equal_cutover_baseline"] is True
    assert guarded["lock_held_quiescence_rechecked_before_every_start_attempt"] is True
    assert guarded["opens_admission"] is False
    assert rollback["missing_or_partial_seals_after_reboot_accepted_after_quiescence"] is True
    assert rollback["legacy_seals_removed_before_reverse_delta"] is True
    assert rollback["opens_admission"] is False


def test_contract_keeps_production_closed_and_points_to_b4() -> None:
    contract = _json(CONTRACT)
    assert all(value is False for value in contract["scope_boundary"].values())
    assert contract["next_subpart"]["id"] == "FR-06B4"
    assert (
        contract["next_subpart"]["production_execution_requires_new_owner_decision"]
        is True
    )
    assert len(contract["production_gates_still_required"]) >= 8


def test_contract_loader_matches_b2_and_b3a() -> None:
    module = _module()
    b2, b3a = module._load_contracts(ROOT)
    runtime, initializers = module._service_matrix(b2)
    assert len(runtime) == 20
    assert len(initializers) == 2
    assert b3a["restart_policy"]["guarded_runtime_policy"] == "no"
    assert b3a["admission_gate"]["production_authorization_capability"] is False


def test_executor_has_no_shell_vault_unlock_admission_open_or_cloudflare_mutator() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert '["cryptsetup"' not in source
    assert '["rclone"' not in source
    assert '"docker", "volume", "create"' not in source
    assert "cloudflared" not in source
    assert "cloudflare.com" not in source
    assert "open_admission" not in source
    assert "admission_opened" in source
    assert source.count('"admission_opened": False') >= 8
    assert '"mount", "--bind"' in source
    assert '"remount,bind,ro,nodev,nosuid"' in source
    assert '"rsync"' in source


def test_executor_does_not_offer_unbounded_restart_or_unrelated_compose_actions() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "MAX_START_ATTEMPTS = 3" in source
    assert '"down"' not in source
    assert '"restart"' not in source
    assert '"kill"' not in source
    assert '"--remove-orphans"' not in source
    assert '"--pull",\n                "never"' in source
    assert '"--no-deps"' in source


def test_b3a_lab_preflight_is_re_evaluated_but_never_authorizes_production(
    tmp_path: Path,
) -> None:
    module = _module()
    evidence, snapshot = _admission_inputs(tmp_path)
    result = module._evaluate_admission(
        ROOT,
        evidence,
        snapshot,
        allow_isolated_lab=True,
        max_age_seconds=900,
    )
    assert result["decision"] == "isolated_lab_ready"
    assert result["preflight_passed"] is True
    assert result["production_authorized"] is False
    assert result["executor_present"] is False


def test_window_validation_is_bounded_and_current() -> None:
    module = _module()
    now = datetime.now(timezone.utc)
    evidence = {
        "approvals": {
            "owner_authorized": True,
            "window_starts_at": (now - timedelta(minutes=1))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "window_ends_at": (now + timedelta(minutes=5))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }
    }
    module._validate_window(evidence, "production", now)
    evidence["approvals"]["window_ends_at"] = (
        now + timedelta(hours=5)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    with pytest.raises(module.LifecycleBlocked, match="window bounds"):
        module._validate_window(evidence, "production", now)


def test_cutover_plan_binds_hashes_paths_topology_and_expires(
    tmp_path: Path,
) -> None:
    module = _module()
    args = _plan_fixture(tmp_path)
    result = module.create_cutover_plan(args)
    plan = _json(Path(result["plan"]))
    module._validate_plan_digest(plan)
    assert result["decision"] == "cutover_plan_ready"
    assert plan["environment"] == "isolated_lab"
    assert plan["service_count"] == 20
    assert plan["instance_count"] == 20
    assert len(plan["roots"]) == 11
    assert plan["evidence_sha256"] == module._file_digest(args.evidence)
    assert plan["snapshot_sha256"] == module._file_digest(args.snapshot)
    assert plan["admission_will_remain_closed"] is True
    assert plan["cloudflare_change_permitted"] is False
    assert plan["vault_unlock_or_creation_permitted"] is False


def test_plan_digest_and_bound_input_tampering_fail_closed(tmp_path: Path) -> None:
    module = _module()
    args = _plan_fixture(tmp_path)
    result = module.create_cutover_plan(args)
    plan_path = Path(result["plan"])
    plan = _json(plan_path)
    plan["instance_count"] += 1
    with pytest.raises(module.LifecycleBlocked, match="digest mismatch"):
        module._validate_plan_digest(plan)
    args.evidence.write_text(
        args.evidence.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(module.LifecycleBlocked, match="evidence changed"):
        module._load_bound_plan(
            plan_path,
            args.evidence,
            args.snapshot,
            datetime.now(timezone.utc),
        )


def test_plan_rejects_socket_mismatch_and_path_escape(tmp_path: Path) -> None:
    module = _module()
    args = _plan_fixture(tmp_path)
    args.docker_host = f"unix://{tmp_path}/different.sock"
    with pytest.raises(module.LifecycleBlocked, match="Docker socket differs"):
        module.create_cutover_plan(args)

    args = _plan_fixture(tmp_path / "second")
    layout = _json(args.lab_layout)
    layout["source_roots"]["three_d_asset_data"] = "/opt/AIOS"
    module._write_json_atomic(args.lab_layout, layout)
    with pytest.raises(module.LifecycleBlocked, match="escaped"):
        module.create_cutover_plan(args)


def test_private_state_mode_and_nonblocking_lock_are_enforced(
    tmp_path: Path,
) -> None:
    module = _module()
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    with pytest.raises(module.LifecycleBlocked, match="mode 0700"):
        module._secure_state_dir(state, "isolated_lab", tmp_path)

    os.chmod(state, 0o700)
    secured = module._secure_state_dir(state, "isolated_lab", tmp_path)
    first = module._lock(secured)
    try:
        with pytest.raises(module.LifecycleBlocked, match="holds the lock"):
            module._lock(secured)
    finally:
        fcntl.flock(first, fcntl.LOCK_UN)
        os.close(first)


def test_lab_runtime_preserves_exact_scale_and_rejects_unlisted_consumer(
    tmp_path: Path,
) -> None:
    module = _module()
    runtime_path = tmp_path / "runtime.json"
    services = {
        "alpha": {
            "instances": ["alpha-1", "alpha-2"],
            "running": True,
            "desired": True,
            "mount_mode": "legacy",
            "restart_policy": "unless-stopped",
        },
        "beta": {
            "instances": ["beta-1"],
            "running": True,
            "desired": True,
            "mount_mode": "legacy",
            "restart_policy": "unless-stopped",
        },
    }
    module._write_json_atomic(
        runtime_path,
        {
            "schema_version": 1,
            "services": services,
            "unlisted_consumers": [],
            "unlisted_writers": [],
            "fail_phase": None,
        },
    )
    runtime = module.LabRuntime(runtime_path, ["alpha", "beta"], ["init"])
    topology = runtime.topology("legacy")
    assert topology == {"alpha": ["alpha-1", "alpha-2"], "beta": ["beta-1"]}
    runtime.exact_stop(topology, "legacy")
    runtime.start_initializers("candidate")
    runtime.start_services(topology, "candidate")
    runtime.verify(topology, "candidate")
    value = _json(runtime_path)
    value["unlisted_consumers"] = ["foreign"]
    module._write_json_atomic(runtime_path, value)
    with pytest.raises(module.LifecycleBlocked, match="unlisted"):
        runtime.topology("candidate")


def test_writable_descriptor_scan_detects_other_process(tmp_path: Path) -> None:
    module = _module()
    target = tmp_path / "held.txt"
    child_code = (
        "import os,sys,time;"
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT,0o600);"
        "print('ready',flush=True);time.sleep(20)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        found = module._writable_fds([tmp_path])
        assert any(item["pid"] == child.pid for item in found)
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_receipt_digest_is_tamper_evident() -> None:
    module = _module()
    value = module._receipt(
        {
            "schema_version": 1,
            "subpart": "FR-06B3B",
            "status": "candidate_started_admission_closed",
        }
    )
    module._validate_receipt(value)
    value["status"] = "forged"
    with pytest.raises(module.LifecycleBlocked, match="digest mismatch"):
        module._validate_receipt(value)


def test_cli_exposes_only_bounded_lifecycle_commands() -> None:
    result = subprocess.run(
        [sys.executable, str(EXECUTOR), "--help"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    for command in ("plan-cutover", "apply-cutover", "guarded-start", "rollback"):
        assert command in result.stdout
    assert "open-admission" not in result.stdout
    assert "unlock" not in result.stdout
    assert "provision" not in result.stdout


def test_retained_isolated_proof_is_complete_truthful_and_clean() -> None:
    proof = _json(PROOF)
    assert proof["subpart"] == "FR-06B3B"
    assert proof["source_commit"] == "6e1ceb3a05193793ee8e5ad3d81c646678d77957"
    assert proof["all_checks_passed"] is True
    assert proof["production_changed"] is False
    checks = proof["checks"]
    for key in (
        "successful_cutover_closed_admission",
        "all_eleven_forward_deltas_exact",
        "all_eleven_post_initializer_manifests_exact",
        "legacy_roots_real_read_only_bind_mounts",
        "twenty_service_matrix_and_scaled_instance_preserved",
        "guarded_start_passed_and_kept_admission_closed",
        "guarded_start_reestablished_missing_legacy_seals",
        "guarded_start_verified_legacy_baseline_after_reseal",
        "guarded_start_blocks_legacy_drift_after_reboot",
        "manual_reverse_delta_rollback_passed",
        "manual_rollback_unsealed_legacy",
        "single_use_plan_replay_blocked",
        "topology_drift_blocked_before_mutation",
        "exclusive_lock_collision_blocked",
        "post_candidate_failure_reverse_delta_rollback_passed",
        "initializer_failure_never_reverse_copied_to_legacy",
        "pre_candidate_failure_legacy_restore_passed",
        "path_escape_blocked",
        "all_temporary_bind_mounts_removed",
        "all_temporary_files_and_state_removed",
        "production_container_identity_unchanged",
    ):
        assert checks[key] is True
    for key in (
        "production_docker_used_for_lab_operations",
        "production_services_stopped_or_restarted",
        "production_sources_used",
        "production_vaults_or_keys_created",
        "production_volumes_or_mounts_changed",
        "cloudflare_changed",
        "host_rebooted",
        "application_admission_opened",
    ):
        assert checks[key] is False
    assert proof["cutover_gate"]["production_cutover_allowed_by_this_receipt"] is False
    assert proof["cutover_gate"]["application_admission_opened"] is False


def test_lab_source_cleans_all_mounts_and_never_targets_production() -> None:
    source = LAB.read_text(encoding="utf-8")
    assert 'dir="/var/tmp"' in source
    assert '["umount", str(path)]' in source
    assert "shutil.rmtree(sandbox" in source
    assert "no-production-docker.sock" in source
    assert "PRODUCTION_DOCKER_CUTOVER" not in source


def test_human_receipt_preserves_source_only_boundary() -> None:
    text = " ".join(RECEIPT.read_text(encoding="utf-8").casefold().split())
    assert "does not authorize production execution" in text
    assert "does not open application admission" in text
    assert "does not close fr-06b or fr-06" in text
    assert "fr-06b4" in text


def test_cutover_seals_legacy_before_final_delta_and_rechecks_admission() -> None:
    module = _module()
    source = inspect.getsource(module.apply_cutover)
    seal = source.index("sealed = _seal_sources(pairs)")
    delta = source.index("forward_summary = _stable_delta(")
    fresh_admission = source.rindex("_fresh_admitted_snapshot(")
    initializer = source.index('runtime.start_initializers("candidate")')
    post_initializer = source.index("post_initializer_summary = _verify_exact_pairs(")
    runtime_start = source.index('runtime.start_services(active, "candidate")')
    assert seal < delta < fresh_admission < initializer < post_initializer < runtime_start
    assert "legacy read-only seal drifted during final delta" in source
    assert "candidate_runtime_attempted = True" in source
    assert _json(CONTRACT)["cutover"]["post_initializer_exact_manifest_required"] is True


def test_guarded_start_reestablishes_reboot_lost_seals_under_lock() -> None:
    module = _module()
    source = inspect.getsource(module.guarded_start)
    acquire_lock = source.index("lock_fd = _lock(state_dir)")
    quiescence = source.index("_assert_quiescent(", acquire_lock)
    missing_seals = source.index("if not _sealed(sealed):", quiescence)
    tolerant_unseal = source.index("_unseal_sources(sealed, tolerate=True)", missing_seals)
    reseal = source.index("restored_seals = _seal_sources(pairs)", tolerant_unseal)
    baseline = source.index("_validate_legacy_baseline(", reseal)
    attempt_quiescence = source.index("_assert_quiescent(", baseline)
    candidate_start = source.index('runtime.start_services(active, "candidate")')
    assert (
        acquire_lock
        < quiescence
        < missing_seals
        < tolerant_unseal
        < reseal
        < baseline
        < attempt_quiescence
        < candidate_start
    )
    assert "re-established legacy seal layout drifted" in source
    assert '"legacy_seals_reestablished": seals_reestablished' in source
    assert '"legacy_baseline_verified_after_reseal": legacy_baseline_verified' in source


def test_retained_active_topology_rejects_unreviewed_or_unsafe_instances() -> None:
    module = _module()
    assert module._validated_active_instances(
        {"backend": ["safe-instance-1"]},
        ["backend", "frontend"],
    ) == {"backend": ["safe-instance-1"]}
    with pytest.raises(module.LifecycleBlocked, match="unreviewed service"):
        module._validated_active_instances({"foreign": ["instance-1"]}, ["backend"])
    with pytest.raises(module.LifecycleBlocked, match="identifier is invalid"):
        module._validated_active_instances({"backend": ["../../unsafe"]}, ["backend"])
    with pytest.raises(module.LifecycleBlocked, match="duplicated"):
        module._validated_active_instances(
            {"backend": ["same", "same"]},
            ["backend"],
        )


def test_docker_runtime_requires_exact_protected_mount_set(tmp_path: Path) -> None:
    module = _module()
    b2 = _json(B2)
    pairs = [
        {
            "name": row["compose_volume"],
            "vault": row["vault"],
            "target_subpath": row["target_subpath"],
            "source": str(tmp_path / "legacy" / row["compose_volume"]),
            "target": str(
                tmp_path / "candidate" / row["vault"] / row["target_subpath"]
            ),
            "legacy_volume": f"web-dashboard_{row['compose_volume']}",
            "candidate_volume": (
                "aionex-fr06-asset-vault"
                if row["vault"] == "asset-vault"
                else "aionex-fr06-project-execution-vault"
            ),
        }
        for row in b2["matrix"]["roots"]
    ]
    runtime = module.DockerRuntime(
        ROOT,
        tmp_path / "lab.env",
        f"unix://{tmp_path}/docker.sock",
        b2,
        pairs,
    )
    mounts = [
        {
            "Type": "volume",
            "Name": runtime._volume_for(item["root"], "legacy"),
            "Destination": item["target"],
            "RW": item["rw"],
        }
        for item in runtime.mount_matrix["backend"]
    ]
    container = {
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
        "Mounts": mounts,
    }
    runtime._verify_container(container, "backend", "legacy")
    container["Mounts"].append(
        {
            "Type": "volume",
            "Name": "aionex-fr06-asset-vault",
            "Destination": "/unexpected",
            "RW": True,
        }
    )
    with pytest.raises(module.LifecycleBlocked, match="unexpected protected mount"):
        runtime._verify_container(container, "backend", "legacy")


@pytest.mark.parametrize(
    "nonce",
    ["", "short", "../escape", "space is not allowed", "x" * 129],
)
def test_operation_nonce_is_bounded(nonce: str) -> None:
    module = _module()
    with pytest.raises(module.LifecycleBlocked, match="nonce"):
        module._validate_nonce(nonce)
    module._validate_nonce("owner-window-20260914")


def test_production_fresh_inspection_invokes_b3a_runtime_inspector() -> None:
    module = _module()
    source = inspect.getsource(module._fresh_admitted_snapshot)
    assert "module.inspect_runtime(" in source
    assert "asset_mapper=" in source
    assert "project_mapper=" in source
    assert "asset_mount_root=" in source
    assert "project_mount_root=" in source
    assert "asset_volume=" in source
    assert "project_volume=" in source
    assert "_evaluate_admission(" in source
    contract = _json(CONTRACT)
    assert (
        contract["admission_binding"][
            "production_runtime_reinspection_at_plan_apply_and_each_start_attempt"
        ]
        is True
    )
    assert contract["scope"]["exact_protected_mount_set_required"] is True
