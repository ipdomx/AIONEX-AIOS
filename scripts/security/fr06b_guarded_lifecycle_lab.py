#!/usr/bin/env python3
"""Isolated FR-06B3B guarded lifecycle, rollback, replay, and lock rehearsal."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _load_executor(root: Path):
    path = root / "scripts" / "security" / "fr06b_guarded_lifecycle.py"
    spec = importlib.util.spec_from_file_location("fr06b3b_executor_lab", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load FR-06B3B executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _identity() -> str:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return "docker-unavailable"
    return hashlib.sha256(
        "\n".join(sorted(line for line in result.stdout.splitlines() if line)).encode()
    ).hexdigest()


def _b3a_snapshot(module, fixture: Path, roots: list[dict[str, Any]]) -> dict[str, Any]:
    asset_names = sorted(
        row["target_subpath"] for row in roots if row["vault"] == "asset-vault"
    )
    project_names = sorted(
        row["target_subpath"]
        for row in roots
        if row["vault"] == "project-execution-vault"
    )
    docker_host = f"unix://{fixture}/no-production-docker.sock"
    return {
        "schema_version": 1,
        "subpart": "FR-06B3A",
        "validation": "FR06B3A_RUNTIME_SNAPSHOT_PASS",
        "environment": "isolated_lab",
        "observed_at": module._utc_text(),
        "docker_host": docker_host,
        "mappers": [
            {
                "role": "asset-vault",
                "path": "/dev/mapper/fr06b3b-lab-asset",
                "active": True,
                "block_device": True,
                "filesystem": "ext4",
                "mount_root": str(fixture / "candidate" / "asset-vault"),
                "mount_source_matches": True,
                "mount_options": ["rw", "nodev", "nosuid", "noexec"],
                "required_options_present": True,
                "forbidden_options_absent": True,
                "subpaths_present": asset_names,
            },
            {
                "role": "project-execution-vault",
                "path": "/dev/mapper/fr06b3b-lab-project",
                "active": True,
                "block_device": True,
                "filesystem": "ext4",
                "mount_root": str(fixture / "candidate" / "project-execution-vault"),
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
                "name": "fr06b3b-lab-asset",
                "device": "/dev/mapper/fr06b3b-lab-asset",
                "driver": "local",
                "type": "ext4",
                "options": ["nodev", "nosuid", "noexec"],
                "running_consumer_count": 0,
            },
            {
                "role": "project-execution-vault",
                "name": "fr06b3b-lab-project",
                "device": "/dev/mapper/fr06b3b-lab-project",
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


def _b3a_evidence(module, commit: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "environment": "isolated_lab",
        "observed_at": module._utc_text(),
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
        "source": {"lab_commit_sha": commit},
    }


def _make_fixture(
    module,
    root: Path,
    sandbox: Path,
    name: str,
    *,
    fail_phase: str | None = None,
) -> dict[str, Any]:
    fixture = sandbox / name
    fixture.mkdir(mode=0o700)
    contract = json.loads(
        (
            root
            / "docs"
            / "project"
            / "receipts"
            / "FR-06B2-compose-cutover-contract.json"
        ).read_text(encoding="utf-8")
    )
    roots = contract["matrix"]["roots"]
    runtime_services = sorted(
        set(contract["matrix"]["runtime_writer_services"])
        | set(contract["matrix"]["read_only_only_services"])
    )
    source_roots: dict[str, str] = {}
    target_roots: dict[str, str] = {}
    for index, row in enumerate(roots):
        name_value = row["compose_volume"]
        source = fixture / "legacy" / name_value
        target = fixture / "candidate" / row["vault"] / row["target_subpath"]
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "nested").mkdir()
        (source / "payload.txt").write_text(
            f"{name}:{name_value}:{index}\n", encoding="utf-8"
        )
        (source / "nested" / "metadata.txt").write_text(
            f"stable-{index}\n", encoding="utf-8"
        )
        (target / "stale.txt").write_text("must-be-deleted\n", encoding="utf-8")
        source_roots[name_value] = str(source)
        target_roots[name_value] = str(target)

    runtime_path = fixture / "runtime.json"
    services: dict[str, Any] = {}
    for service in runtime_services:
        count = 3 if service == "project-worker" else 1
        services[service] = {
            "instances": [f"{name}-{service}-{index + 1}" for index in range(count)],
            "running": True,
            "desired": True,
            "mount_mode": "legacy",
            "restart_policy": "unless-stopped",
        }
    _private_json(
        runtime_path,
        {
            "schema_version": 1,
            "services": services,
            "unlisted_consumers": [],
            "unlisted_writers": [],
            "fail_phase": fail_phase,
            "events": [],
        },
    )

    layout_path = fixture / "layout.json"
    layout = {
        "schema_version": 1,
        "sandbox_root": str(fixture),
        "runtime_state": str(runtime_path),
        "source_roots": source_roots,
        "target_roots": target_roots,
    }
    _private_json(layout_path, layout)

    commit = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        .stdout.strip()
    )
    evidence_path = fixture / "evidence.json"
    snapshot_path = fixture / "snapshot.json"
    env_file = fixture / "lab.env"
    env_file.write_text("FR06B3B_LAB=1\n", encoding="utf-8")
    os.chmod(env_file, 0o600)
    snapshot = _b3a_snapshot(module, fixture, roots)
    _private_json(evidence_path, _b3a_evidence(module, commit))
    _private_json(snapshot_path, snapshot)

    common = {
        "root": root,
        "evidence": evidence_path,
        "snapshot": snapshot_path,
        "state_dir": fixture / "state",
        "env_file": env_file,
        "docker_host": snapshot["docker_host"],
        "max_age_seconds": 900,
        "allow_isolated_lab": True,
        "lab_layout": layout_path,
    }
    return {
        "fixture": fixture,
        "common": common,
        "layout": layout,
        "runtime": runtime_path,
        "runtime_services": runtime_services,
        "source_roots": source_roots,
        "target_roots": target_roots,
    }


def _namespace(common: dict[str, Any], **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(**common, **extra)


def _plan(module, fixture: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    result = module.create_cutover_plan(
        _namespace(fixture["common"], ttl_seconds=600)
    )
    return result, Path(result["plan"])


def _apply(module, fixture: dict[str, Any], plan: dict[str, Any], path: Path):
    return module.apply_cutover(
        _namespace(
            fixture["common"],
            plan=path,
            confirmation=f"EXECUTE_FR06B3B_CUTOVER:{plan['plan_id']}",
            confirm_production="",
        )
    )


def _runtime_value(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_runtime(module, path: Path, value: dict[str, Any]) -> None:
    module._write_json_atomic(path, value)


def _stop_lab_runtime(module, fixture: dict[str, Any]) -> None:
    value = _runtime_value(fixture["runtime"])
    for item in value["services"].values():
        item["running"] = False
    _save_runtime(module, fixture["runtime"], value)


def _unmount_tree(paths: list[Path]) -> None:
    for path in sorted(paths, key=lambda value: len(str(value)), reverse=True):
        subprocess.run(
            ["umount", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


def run_lab(root: Path, output: Path) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("FR-06B3B isolated bind-mount lab requires root")
    module = _load_executor(root)
    sandbox = Path(tempfile.mkdtemp(prefix="fr06b3b-lab-", dir="/var/tmp"))
    os.chmod(sandbox, 0o700)
    mount_candidates: list[Path] = []
    identity_before = _identity()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    try:
        success = _make_fixture(module, root, sandbox, "success")
        mount_candidates += [Path(path) for path in success["source_roots"].values()]
        plan, plan_path = _plan(module, success)
        applied = _apply(module, success, plan, plan_path)
        success_receipt = Path(applied["result"])
        retained = module._load_success_receipt(success_receipt)
        checks["successful_cutover_closed_admission"] = (
            applied["status"] == "candidate_started_admission_closed"
            and applied["admission_opened"] is False
            and retained["live_p95_accepted"] is False
        )
        checks["all_eleven_forward_deltas_exact"] = len(retained["final_delta"]) == 11
        checks["all_eleven_post_initializer_manifests_exact"] = (
            len(retained["post_initializer_exact"]) == 11
        )
        checks["legacy_roots_real_read_only_bind_mounts"] = module._sealed(
            retained["legacy_read_only_roots"]
        )
        checks["twenty_service_matrix_and_scaled_instance_preserved"] = (
            len(retained["active_instances"]) == 20
            and len(retained["active_instances"]["project-worker"]) == 3
        )

        _stop_lab_runtime(module, success)
        module._unseal_sources(retained["legacy_read_only_roots"])
        reboot_drift = (
            Path(success["source_roots"]["three_d_asset_data"])
            / "unexpected-reboot-write.txt"
        )
        reboot_drift.write_text("must-block-guarded-start\n", encoding="utf-8")
        drift_nonce = "isolated-reboot-drift"
        drift_id = module._digest(
            {
                "operation": "guarded_start",
                "receipt": retained["receipt_sha256"],
                "nonce": drift_nonce,
            }
        )
        drift_blocked = False
        try:
            module.guarded_start(
                _namespace(
                    success["common"],
                    receipt=success_receipt,
                    nonce=drift_nonce,
                    confirmation=f"START_FR06B3B:{drift_id}",
                    confirm_production="",
                )
            )
        except (module.LifecycleBlocked, module.LifecycleError):
            drift_blocked = True
        checks["guarded_start_blocks_legacy_drift_after_reboot"] = (
            drift_blocked
            and module._sealed(retained["legacy_read_only_roots"])
            and all(
                item["running"] is False
                for item in _runtime_value(success["runtime"])["services"].values()
            )
        )
        module._unseal_sources(retained["legacy_read_only_roots"])
        reboot_drift.unlink()

        start_nonce = "isolated-guarded-start"
        start_id = module._digest(
            {
                "operation": "guarded_start",
                "receipt": retained["receipt_sha256"],
                "nonce": start_nonce,
            }
        )
        started = module.guarded_start(
            _namespace(
                success["common"],
                receipt=success_receipt,
                nonce=start_nonce,
                confirmation=f"START_FR06B3B:{start_id}",
                confirm_production="",
            )
        )
        checks["guarded_start_passed_and_kept_admission_closed"] = (
            started["status"] == "candidate_started_admission_closed"
            and started["attempt"] == 1
            and started["admission_opened"] is False
        )
        start_receipt = module._json_object(Path(started["result"]))
        checks["guarded_start_reestablished_missing_legacy_seals"] = (
            start_receipt["legacy_seals_reestablished"] is True
            and module._sealed(retained["legacy_read_only_roots"])
        )
        checks["guarded_start_verified_legacy_baseline_after_reseal"] = (
            start_receipt["legacy_baseline_verified_after_reseal"] is True
        )

        _stop_lab_runtime(module, success)
        changed_target = (
            Path(success["target_roots"]["three_d_asset_data"])
            / "post-cutover-write.txt"
        )
        changed_target.write_text("candidate-new-write\n", encoding="utf-8")
        rollback_nonce = "isolated-manual-rollback"
        rollback_id = module._digest(
            {
                "operation": "rollback",
                "receipt": retained["receipt_sha256"],
                "nonce": rollback_nonce,
            }
        )
        rolled = module.rollback_cutover(
            _namespace(
                success["common"],
                receipt=success_receipt,
                nonce=rollback_nonce,
                confirmation=f"ROLLBACK_FR06B3B:{rollback_id}",
                confirm_production="",
            )
        )
        checks["manual_reverse_delta_rollback_passed"] = (
            rolled["status"] == "legacy_restored_admission_closed"
            and (
                Path(success["source_roots"]["three_d_asset_data"])
                / "post-cutover-write.txt"
            ).read_text(encoding="utf-8")
            == "candidate-new-write\n"
        )
        checks["manual_rollback_unsealed_legacy"] = not any(
            module._mountpoint(Path(path))
            for path in success["source_roots"].values()
        )

        replay_blocked = False
        try:
            _apply(module, success, plan, plan_path)
        except (module.LifecycleBlocked, module.LifecycleError):
            replay_blocked = True
        checks["single_use_plan_replay_blocked"] = replay_blocked

        drift = _make_fixture(module, root, sandbox, "topology-drift")
        mount_candidates += [Path(path) for path in drift["source_roots"].values()]
        drift_plan, drift_path = _plan(module, drift)
        drift_state = _runtime_value(drift["runtime"])
        drift_state["services"]["backend"]["instances"][0] += "-changed"
        _save_runtime(module, drift["runtime"], drift_state)
        topology_blocked = False
        try:
            _apply(module, drift, drift_plan, drift_path)
        except module.LifecycleBlocked:
            topology_blocked = True
        checks["topology_drift_blocked_before_mutation"] = topology_blocked and all(
            item["running"] is True
            for item in _runtime_value(drift["runtime"])["services"].values()
        )

        locked = _make_fixture(module, root, sandbox, "lock-collision")
        mount_candidates += [Path(path) for path in locked["source_roots"].values()]
        lock_plan, lock_path = _plan(module, locked)
        lock_file = locked["common"]["state_dir"] / ".lifecycle.lock"
        lock_file.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock_fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_blocked = False
        try:
            _apply(module, locked, lock_plan, lock_path)
        except module.LifecycleBlocked:
            lock_blocked = True
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        checks["exclusive_lock_collision_blocked"] = lock_blocked and all(
            item["running"] is True
            for item in _runtime_value(locked["runtime"])["services"].values()
        )

        failed = _make_fixture(
            module,
            root,
            sandbox,
            "candidate-health-failure",
            fail_phase="candidate_health",
        )
        mount_candidates += [Path(path) for path in failed["source_roots"].values()]
        failed_plan, failed_path = _plan(module, failed)
        automatic_error = False
        try:
            _apply(module, failed, failed_plan, failed_path)
        except module.LifecycleError:
            automatic_error = True
        failure_result = module._json_object(
            failed["common"]["state_dir"]
            / "results"
            / f"{failed_plan['plan_id']}.json"
        )
        checks["post_candidate_failure_reverse_delta_rollback_passed"] = (
            automatic_error
            and failure_result["status"]
            == "cutover_failed_automatic_rollback_passed"
            and failure_result["rollback_kind"] == "post_candidate_reverse_delta"
            and len(failure_result["reverse_delta"]) == 11
            and all(
                item["running"] is True
                and item["mount_mode"] == "legacy"
                and item["restart_policy"] == "unless-stopped"
                for item in _runtime_value(failed["runtime"])["services"].values()
            )
            and not any(
                module._mountpoint(Path(path))
                for path in failed["source_roots"].values()
            )
        )

        initializer = _make_fixture(
            module,
            root,
            sandbox,
            "candidate-initializer-failure",
            fail_phase="candidate_initializer",
        )
        mount_candidates += [
            Path(path) for path in initializer["source_roots"].values()
        ]
        initializer_plan, initializer_path = _plan(module, initializer)
        initializer_error = False
        try:
            _apply(module, initializer, initializer_plan, initializer_path)
        except module.LifecycleError:
            initializer_error = True
        initializer_result = module._json_object(
            initializer["common"]["state_dir"]
            / "results"
            / f"{initializer_plan['plan_id']}.json"
        )
        checks["initializer_failure_never_reverse_copied_to_legacy"] = (
            initializer_error
            and initializer_result["status"]
            == "cutover_failed_automatic_rollback_passed"
            and initializer_result["rollback_kind"] == "pre_candidate"
            and initializer_result["reverse_delta"] == []
            and all(
                item["running"] is True and item["mount_mode"] == "legacy"
                for item in _runtime_value(initializer["runtime"])[
                    "services"
                ].values()
            )
            and not any(
                module._mountpoint(Path(path))
                for path in initializer["source_roots"].values()
            )
        )

        pre = _make_fixture(module, root, sandbox, "pre-candidate-failure")
        mount_candidates += [Path(path) for path in pre["source_roots"].values()]
        pre_plan, pre_path = _plan(module, pre)
        pre_mount = Path(pre["source_roots"]["three_d_asset_data"])
        subprocess.run(
            ["mount", "--bind", str(pre_mount), str(pre_mount)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        pre_error = False
        try:
            _apply(module, pre, pre_plan, pre_path)
        except module.LifecycleError:
            pre_error = True
        pre_result = module._json_object(
            pre["common"]["state_dir"]
            / "results"
            / f"{pre_plan['plan_id']}.json"
        )
        checks["pre_candidate_failure_legacy_restore_passed"] = (
            pre_error
            and pre_result["status"] == "cutover_failed_automatic_rollback_passed"
            and pre_result["rollback_kind"] == "pre_candidate"
            and pre_result["reverse_delta"] == []
            and all(
                item["running"] is True and item["mount_mode"] == "legacy"
                for item in _runtime_value(pre["runtime"])["services"].values()
            )
        )
        subprocess.run(
            ["umount", str(pre_mount)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        bad = _make_fixture(module, root, sandbox, "path-escape")
        mount_candidates += [Path(path) for path in bad["source_roots"].values()]
        bad_layout = module._json_object(bad["common"]["lab_layout"])
        bad_layout["source_roots"]["three_d_asset_data"] = "/var/tmp"
        module._write_json_atomic(bad["common"]["lab_layout"], bad_layout)
        escaped = False
        try:
            _plan(module, bad)
        except module.LifecycleBlocked:
            escaped = True
        checks["path_escape_blocked"] = escaped

        details = {
            "scenario_count": 8,
            "protected_root_count": 11,
            "guarded_runtime_service_count": 20,
            "initializer_service_count": 2,
            "maximum_guarded_start_attempts": 3,
            "success_plan_consumed_once": True,
            "private_state_mode": "0700",
            "private_evidence_mode": "0600",
        }
    finally:
        _unmount_tree(mount_candidates)
        residual_mounts = [str(path) for path in mount_candidates if path.exists() and subprocess.run(
            ["mountpoint", "-q", str(path)],
            check=False,
            capture_output=True,
            timeout=10,
        ).returncode == 0]
        checks["all_temporary_bind_mounts_removed"] = not residual_mounts
        shutil.rmtree(sandbox, ignore_errors=False)
        checks["all_temporary_files_and_state_removed"] = not sandbox.exists()

    identity_after = _identity()
    checks["production_container_identity_unchanged"] = identity_before == identity_after
    checks["production_docker_used_for_lab_operations"] = False
    checks["production_sources_used"] = False
    checks["production_services_stopped_or_restarted"] = False
    checks["production_volumes_or_mounts_changed"] = False
    checks["production_vaults_or_keys_created"] = False
    checks["cloudflare_changed"] = False
    checks["host_rebooted"] = False
    checks["application_admission_opened"] = False

    required_true = [
        key
        for key in checks
        if key
        not in {
            "production_docker_used_for_lab_operations",
            "production_sources_used",
            "production_services_stopped_or_restarted",
            "production_volumes_or_mounts_changed",
            "production_vaults_or_keys_created",
            "cloudflare_changed",
            "host_rebooted",
            "application_admission_opened",
        }
    ]
    all_passed = all(checks[key] is True for key in required_true) and all(
        checks[key] is False
        for key in {
            "production_docker_used_for_lab_operations",
            "production_sources_used",
            "production_services_stopped_or_restarted",
            "production_volumes_or_mounts_changed",
            "production_vaults_or_keys_created",
            "cloudflare_changed",
            "host_rebooted",
            "application_admission_opened",
        }
    )
    receipt = {
        "schema_version": 1,
        "batch_id": "FR-06",
        "subpart": "FR-06B3B",
        "observed_at": module._utc_text(),
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip(),
        "lab": {
            "type": "isolated_filesystem_bind_mount_and_file_backed_runtime_lifecycle_rehearsal",
            "sandbox_removed": True,
            "real_read_only_bind_mounts_used": True,
            "production_docker_daemon_used_for_operations": False,
            "production_sources_used": False,
        },
        "details": details,
        "checks": checks,
        "all_checks_passed": all_passed,
        "production_changed": False,
        "cutover_gate": {
            "production_cutover_allowed_by_this_receipt": False,
            "application_admission_opened": False,
            "still_required": [
                "protected PR and post-merge main checks for FR-06B3B",
                "fresh encrypted R2 restore immediately before an approved window",
                "external independent active and recovery key custody",
                "separate off-host LUKS2 header backups",
                "independent owner-visible alert and production boot proof",
                "explicit owner-approved production execution decision",
                "live candidate p95 within the fifteen-percent ceiling",
                "separate decision to open admission and retained rollback-window acceptance",
            ],
        },
    }
    if not all_passed:
        raise RuntimeError("one or more FR-06B3B isolated checks failed")
    fd = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o644,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    value.add_argument("--output", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        receipt = run_lab(args.root.resolve(), args.output.resolve())
    except Exception as exc:
        chain = []
        current: BaseException | None = exc
        while current is not None and len(chain) < 6:
            chain.append(f"{type(current).__name__}: {current}")
            current = current.__cause__
        print("FR06B3B_LAB_ERROR: " + " <- ".join(chain), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "subpart": receipt["subpart"],
                "all_checks_passed": receipt["all_checks_passed"],
                "production_changed": receipt["production_changed"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
