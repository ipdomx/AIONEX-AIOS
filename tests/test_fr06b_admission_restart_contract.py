from __future__ import annotations

import importlib.util
import inspect
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B3A-admission-restart-contract.json"
)
B2_CONTRACT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B2-compose-cutover-contract.json"
)
OVERLAY = ROOT / "web-dashboard" / "docker-compose.fr06-admission.yml"
GATE = ROOT / "scripts" / "security" / "fr06b_cutover_admission.py"
PROOF = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B3A-isolated-admission-restart.json"
)
RECEIPT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B3A-admission-restart.md"
)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _gate():
    spec = importlib.util.spec_from_file_location("fr06b3a_gate", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _snapshot(environment: str) -> dict:
    production = environment == "production"
    asset_mapper = (
        "/dev/mapper/aionex-asset-vault"
        if production
        else "/dev/mapper/fr06b3a-lab-asset"
    )
    project_mapper = (
        "/dev/mapper/aionex-project-execution-vault"
        if production
        else "/dev/mapper/fr06b3a-lab-project"
    )
    return {
        "schema_version": 1,
        "subpart": "FR-06B3A",
        "validation": "FR06B3A_RUNTIME_SNAPSHOT_PASS",
        "environment": environment,
        "observed_at": _now(),
        "docker_host": (
            "unix:///var/run/docker.sock"
            if production
            else "unix:///var/tmp/fr06b3a-lab/docker.sock"
        ),
        "mappers": [
            {
                "role": "asset-vault",
                "path": asset_mapper,
                "active": True,
                "block_device": True,
                "filesystem": "ext4",
                "mount_source_matches": True,
                "mount_options": ["rw", "nodev", "nosuid", "noexec"],
                "required_options_present": True,
                "forbidden_options_absent": True,
                "subpaths_present": [
                    "three_d_asset_data",
                    "media_asset_data",
                    "studio_asset_data",
                    "course_package_data",
                    "realtime_recording_data",
                    "portal_asset_data",
                    "mobile_release_data",
                    "audio_song_ingress_data",
                    "security_source_data",
                    "security_remediation_data",
                ],
            },
            {
                "role": "project-execution-vault",
                "path": project_mapper,
                "active": True,
                "block_device": True,
                "filesystem": "ext4",
                "mount_source_matches": True,
                "mount_options": ["rw", "nodev", "nosuid"],
                "required_options_present": True,
                "forbidden_options_absent": True,
                "subpaths_present": ["project_execution_data"],
            },
        ],
        "volumes": [
            {
                "role": "asset-vault",
                "name": (
                    "aionex-fr06-asset-vault"
                    if production
                    else "fr06b3a-lab-asset"
                ),
                "device": asset_mapper,
                "driver": "local",
                "type": "ext4",
                "options": ["nodev", "nosuid", "noexec"],
                "running_consumer_count": 0,
            },
            {
                "role": "project-execution-vault",
                "name": (
                    "aionex-fr06-project-execution-vault"
                    if production
                    else "fr06b3a-lab-project"
                ),
                "device": project_mapper,
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


def _evidence(environment: str) -> dict:
    production = environment == "production"
    value = {
        "schema_version": 1,
        "environment": environment,
        "observed_at": _now(),
        "production_authorization": production,
        "safety": {
            "out_of_band_alert_passed": production,
            "boot_rehearsal_passed": production,
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
        "source": (
            {
                "pr_head_sha": "a" * 40,
                "merge_sha": "b" * 40,
                "protected_pr_checks_passed": True,
                "post_merge_main_checks_passed": True,
            }
            if production
            else {"lab_commit_sha": "a" * 40}
        ),
    }
    if production:
        value["operations"] = {
            "admission_closed": True,
            "cloudflare_changed": False,
            "baseline_p95_ms": 100,
        }
        value["safety"].pop("boot_rehearsal_passed")
        value["safety"]["out_of_band_alert_ref"] = (
            "pagerduty://events/fr06-test"
        )
        value["approvals"] = {
            "owner_authorized": True,
            "maintenance_window_ref": "ticket://maintenance/fr06-window",
        }
        value["recovery"] = {
            "encrypted_r2_restore": {
                "passed": True,
                "observed_at": _now(),
                "ref": "r2://aionex-recovery/fr06/restore-receipt",
            },
            "active_key_ref": "kms://aionex/fr06/active",
            "recovery_key_ref": "offline://custodian-b/fr06/recovery",
            "asset_header_ref": "vault://offhost-a/fr06/asset-header",
            "project_header_ref": "vault://offhost-b/fr06/project-header",
            "custody_independent": True,
            "headers_separate_from_recovery_key": True,
        }
    return value


def test_contract_scopes_twenty_runtime_services_and_two_initializers() -> None:
    contract = _json(CONTRACT)
    b2 = _json(B2_CONTRACT)
    restart = contract["restart_policy"]
    expected = sorted(
        set(b2["matrix"]["runtime_writer_services"])
        | set(b2["matrix"]["read_only_only_services"])
    )
    assert restart["guarded_runtime_policy"] == "no"
    assert restart["rejected_alternative"]["policy"] == "on-failure:5"
    assert restart["rejected_alternative"]["decision"].startswith("rejected")
    assert sorted(restart["protected_runtime_services"]) == expected
    assert restart["protected_runtime_service_count"] == len(expected) == 20
    assert restart["initializer_services"] == b2["matrix"]["initializer_services"]
    assert restart["initializer_policy"] == "no"
    assert restart["latent_profile_service_included"] == "audio-song-worker-secondary"
    assert restart["explicit_guarded_start_required_after_every_daemon_start"] is True
    assert restart["standalone_systemd_gate_claimed"] is False


def test_restart_overlay_is_narrow_and_complete() -> None:
    contract = _json(CONTRACT)
    text = OVERLAY.read_text(encoding="utf-8")
    expected = contract["restart_policy"]["protected_runtime_services"]
    sections = [
        line[2:-2]
        for line in text.splitlines(keepends=True)
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":\n")
    ]
    assert sorted(sections) == sorted(expected)
    assert text.count('    restart: "no"\n') == 20
    assert "backup-asset-root-init:" not in text
    assert "realtime-recording-init:" not in text
    for forbidden in ("image:", "command:", "volumes:", "ports:", "environment:"):
        assert forbidden not in text


def test_restart_overlay_renders_without_unrelated_drift() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI unavailable")
    module = _gate()
    result = module.validate_restart_overlay(
        ROOT, ROOT / "web-dashboard" / ".env.production.example"
    )
    assert result == {
        "fr06b2_validation": "FR06B2_COMPOSE_OVERLAY_PASS",
        "restart_validation": "FR06B3A_RESTART_OVERLAY_PASS",
        "guarded_restart_policy": "no",
        "guarded_service_count": 20,
        "initializer_service_count": 2,
        "all_profiles": True,
    }


def test_evaluator_admits_only_explicit_isolated_lab() -> None:
    module = _gate()
    evidence = _evidence("isolated_lab")
    snapshot = _snapshot("isolated_lab")
    admitted = module.evaluate(evidence, snapshot, True, 3600)
    assert admitted["preflight_passed"] is True
    assert admitted["decision"] == "isolated_lab_ready"
    assert admitted["production_authorized"] is False
    blocked = module.evaluate(evidence, snapshot, False, 3600)
    assert blocked["preflight_passed"] is False
    assert blocked["blockers"] == ["isolated_lab_requires_explicit_flag"]


def test_isolated_lab_does_not_claim_external_alert_boot_checks_or_live_p95() -> None:
    module = _gate()
    evidence = _evidence("isolated_lab")
    assert evidence["safety"]["out_of_band_alert_passed"] is False
    assert evidence["safety"]["boot_rehearsal_passed"] is False
    assert "baseline_p95_ms" not in evidence["operations"]
    result = module.evaluate(evidence, _snapshot("isolated_lab"), True, 3600)
    assert result["preflight_passed"] is True
    assert result["production_authorized"] is False


@pytest.mark.parametrize(
    ("path", "value", "blocker"),
    [
        (("mappers", 0, "subpaths_present"), ["forged"] * 10, "asset-vault:subpath_matrix"),
        (("volumes", 0, "options"), ["nodev", "nosuid", "noexec", "bind"], "asset-vault:volume_options"),
        (("volumes", 1, "device"), "/dev/mapper/wrong", "project-execution-vault:production_volume_device"),
    ],
)
def test_evaluator_rejects_forged_runtime_topology(path, value, blocker: str) -> None:
    module = _gate()
    snapshot = _snapshot("production")
    collection, index, field = path
    snapshot[collection][index][field] = value
    result = module.evaluate(_evidence("production"), snapshot, False, 3600)
    assert result["preflight_passed"] is False
    assert blocker in result["blockers"]


def test_evaluator_can_admit_complete_production_references() -> None:
    module = _gate()
    result = module.evaluate(
        _evidence("production"), _snapshot("production"), False, 3600
    )
    assert result["preflight_passed"] is True
    assert result["production_authorized"] is False
    assert result["decision"] == "production_preflight_ready"
    assert result["executor_present"] is False
    assert result["blockers"] == []
    assert "boot_rehearsal_passed" not in _evidence("production")["safety"]
    assert "candidate_p95_ms" not in _evidence("production")["operations"]
    assert "final_delta_exact" not in _evidence("production")["operations"]


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        (
            lambda item: item["recovery"].update(
                active_key_ref="file:///root/fr06-active.key"
            ),
            "recovery:active_key_ref:local_reference_forbidden",
        ),
        (
            lambda item: item["recovery"].update(
                recovery_key_ref=item["recovery"]["active_key_ref"]
            ),
            "recovery:custody_references_not_distinct",
        ),
        (
            lambda item: item["operations"].update(candidate_p95_ms=115.01),
            "operations:candidate_p95_ms_is_post_cutover",
        ),
        (
            lambda item: item["operations"].update(final_delta_exact=True),
            "operations:final_delta_exact:premature_preflight_claim",
        ),
        (
            lambda item: item["safety"].update(delayed_unlock_rehearsal_passed=False),
            "safety:delayed_unlock_rehearsal_passed",
        ),
    ],
)
def test_evaluator_fails_closed_on_production_gate_drift(mutation, blocker: str) -> None:
    module = _gate()
    evidence = _evidence("production")
    mutation(evidence)
    result = module.evaluate(evidence, _snapshot("production"), False, 3600)
    assert result["preflight_passed"] is False
    assert blocker in result["blockers"]
    assert result["production_authorized"] is False


def test_evaluator_rejects_embedded_secret_material() -> None:
    module = _gate()
    evidence = _evidence("production")
    evidence["recovery"]["key_material"] = "must-never-be-accepted"
    with pytest.raises(module.AdmissionError, match="embedded secret material"):
        module.evaluate(evidence, _snapshot("production"), False, 3600)


def test_evaluator_rejects_stale_evidence() -> None:
    module = _gate()
    evidence = _evidence("production")
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    evidence["observed_at"] = stale.isoformat(timespec="seconds").replace("+00:00", "Z")
    result = module.evaluate(evidence, _snapshot("production"), False, 3600)
    assert "evidence_stale" in result["blockers"]
    assert result["preflight_passed"] is False


def test_runtime_inspection_helpers_are_read_only_and_fail_on_non_block_mapper(
    tmp_path: Path,
) -> None:
    module = _gate()
    source = inspect.getsource(module.inspect_runtime)
    mount_source = inspect.getsource(module._mount_snapshot)
    volume_source = inspect.getsource(module._docker_volume_snapshot)
    assert "subprocess" not in source
    assert '["mount"' not in mount_source
    assert '["umount"' not in mount_source
    assert '"create"' not in volume_source
    assert '"start"' not in volume_source
    assert "shell=True" not in GATE.read_text(encoding="utf-8")
    fake_mapper = tmp_path / "not-a-block-device"
    fake_mapper.write_bytes(b"")
    with pytest.raises(module.AdmissionBlocked, match="mapper_not_block_device"):
        module._mount_snapshot(tmp_path, fake_mapper, "asset-vault", [])


def test_cli_uses_distinct_exit_code_for_well_formed_block() -> None:
    evidence = _evidence("isolated_lab")
    snapshot = _snapshot("isolated_lab")
    evidence_path = ROOT / ".fr06b3a-test-evidence.json"
    snapshot_path = ROOT / ".fr06b3a-test-snapshot.json"
    try:
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(GATE),
                "evaluate",
                "--evidence",
                str(evidence_path),
                "--snapshot",
                str(snapshot_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 2
        parsed = json.loads(result.stdout)
        assert parsed["decision"] == "blocked"
        assert parsed["production_authorized"] is False
    finally:
        evidence_path.unlink(missing_ok=True)
        snapshot_path.unlink(missing_ok=True)


def test_scope_boundary_stays_closed() -> None:
    contract = _json(CONTRACT)
    assert all(value is False for value in contract["scope_boundary"].values())
    assert contract["next_subpart"]["id"] == "FR-06B3B"
    assert contract["next_subpart"]["production_execution_still_requires_owner_window"] is True


def test_retained_lab_proof_and_receipt_are_truthful() -> None:
    proof = _json(PROOF)
    assert proof["subpart"] == "FR-06B3A"
    assert proof["all_checks_passed"] is True
    assert proof["production_changed"] is False
    checks = proof["checks"]
    for key in (
        "isolated_docker_daemon_verified",
        "unless_stopped_control_restored_after_daemon_restart",
        "on_failure_5_control_restored_after_daemon_restart",
        "restart_no_candidates_not_restored_after_daemon_restart",
        "missing_mapper_blocked_admission",
        "missing_mapper_blocked_container_start",
        "wrong_key_rejected_for_both_vaults",
        "delayed_unlock_required_fresh_admission",
        "explicit_guarded_start_after_unlock_succeeded",
        "recovery_keys_reopened_both_vaults",
        "stable_final_delta_exact",
        "retained_legacy_read_only_rejected_write",
        "pre_admission_rollback_passed",
        "post_admission_reverse_delta_rollback_passed",
        "temporary_resources_removed",
        "production_container_ids_unchanged",
    ):
        assert checks[key] is True
    for key in (
        "host_boot_rehearsed",
        "external_alert_rehearsed",
        "protected_checks_claimed",
        "live_p95_measured",
    ):
        assert checks[key] is False
    assert proof["cutover_gate"]["production_cutover_allowed_by_this_receipt"] is False
    receipt = " ".join(RECEIPT.read_text(encoding="utf-8").casefold().split())
    assert "does not authorize production cutover" in receipt
    assert "does not install a systemd unit" in receipt
    assert "does not close fr-06b or fr-06" in receipt
