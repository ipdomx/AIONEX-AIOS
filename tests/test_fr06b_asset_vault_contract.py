from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B1-asset-vault-copy-contract.json"
)
LAB = ROOT / "docs" / "project" / "receipts" / "FR-06B1-isolated-asset-copy.json"
RECEIPT = (
    ROOT / "docs" / "project" / "receipts" / "FR-06B1-asset-vault-copy.md"
)
ADR = ROOT / "docs" / "architecture" / "ADR-001-FR-06-host-data-encryption.md"
SCRIPT = ROOT / "scripts" / "security" / "fr06b_asset_vault_lab.sh"
HELPER = ROOT / "scripts" / "security" / "fr06b_asset_copy_manifest.py"
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
PROJECT_DELIVERY = (
    ROOT
    / "web-dashboard"
    / "backend"
    / "app"
    / "services"
    / "three_d_project_delivery.py"
)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _load_helper():
    spec = importlib.util.spec_from_file_location("fr06b_manifest", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fr06b1_splits_executable_project_output_from_passive_assets() -> None:
    contract = _json(CONTRACT)
    refinement = contract["architecture_refinement"]
    assert refinement["supersedes_only_the_fr06a_asset_vault_grouping"] is True
    assert refinement["total_fr06_domain_vaults_after_refinement"] == 7
    vaults = {item["vault"]: item for item in refinement["vaults"]}
    assert set(vaults) == {"asset-vault", "project-execution-vault"}
    assert len(vaults["asset-vault"]["roots"]) == 10
    assert "noexec" in vaults["asset-vault"]["mount_options_minimum"]
    assert vaults["asset-vault"]["executable_content_allowed"] is False
    assert vaults["project-execution-vault"]["roots"] == [
        "project_execution_data"
    ]
    assert vaults["project-execution-vault"]["noexec_allowed"] is False
    assert "npm run build" in vaults["project-execution-vault"][
        "executable_content_reason"
    ]


def test_fr06b1_contract_accounts_for_all_eleven_authoritative_roots() -> None:
    roots = _json(CONTRACT)["source_roots"]
    expected = {
        "three_d_asset_data",
        "media_asset_data",
        "project_execution_data",
        "studio_asset_data",
        "course_package_data",
        "realtime_recording_data",
        "portal_asset_data",
        "mobile_release_data",
        "audio_song_ingress_data",
        "security_source_data",
        "security_remediation_data",
    }
    assert len(roots) == 11
    assert {item["compose_volume"] for item in roots} == expected
    assert {item["runtime_volume"] for item in roots} == {
        f"web-dashboard_{name}" for name in expected
    }
    assert len({item["target_subpath"] for item in roots}) == 11
    assert sum(item["target_vault"] == "project-execution-vault" for item in roots) == 1


def test_project_output_really_has_an_execution_requirement() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    delivery = PROJECT_DELIVERY.read_text(encoding="utf-8")
    assert "PROJECT_EXECUTION_OUTPUT_ROOT: /var/lib/aionex/project-executions" in compose
    assert "project_execution_data:/var/lib/aionex/project-executions" in compose
    assert '["npm", "run", "build"]' in delivery
    assert "cwd=delivery_root" in delivery


def test_fr06b1_copy_policy_rejects_unsafe_types_and_limits_receipt_data() -> None:
    policy = _json(CONTRACT)["copy_and_integrity_contract"]
    rejected = set(policy["rejected_source_types"])
    assert {
        "symbolic link",
        "regular file with st_nlink other than one",
        "FIFO",
        "socket",
        "block device",
        "character device",
    } == rejected
    assert "O_NOFOLLOW" in policy["file_hash"]
    assert "source-before equals source-after" in policy["stable_copy_requirement"]
    assert "do not persist user filenames" in policy["receipt_privacy"]


def test_fr06b1_manifest_helper_accepts_safe_tree_and_rejects_symlink(
    tmp_path: Path,
) -> None:
    helper = _load_helper()
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    payload = root / "payload.bin"
    payload.write_bytes(b"fr06b-safe-payload")
    os.chmod(payload, 0o600)
    manifest = helper.build_manifest(root)
    assert manifest["summary"]["regular_files"] == 1
    assert manifest["summary"]["payload_bytes"] == len(b"fr06b-safe-payload")
    link = root / "link"
    link.symlink_to(payload.name)
    with pytest.raises(helper.ManifestError, match="symbolic link rejected"):
        helper.build_manifest(root)


def test_fr06b1_manifest_helper_rejects_hardlink_and_fifo(tmp_path: Path) -> None:
    helper = _load_helper()
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    first = root / "first"
    first.write_bytes(b"same inode")
    second = root / "second"
    os.link(first, second)
    with pytest.raises(helper.ManifestError, match="hard-linked file rejected"):
        helper.build_manifest(root)
    second.unlink()
    first.unlink()
    fifo = root / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(helper.ManifestError, match="special file rejected"):
        helper.build_manifest(root)


def test_fr06b1_docker_contract_fails_closed_and_preserves_least_privilege() -> None:
    docker = _json(CONTRACT)["docker_fail_closed_contract"]
    assert docker["binding"].startswith("Docker local volumes")
    assert "volume.subpath" in docker["compose_mapping"]
    assert docker["plain_host_bind_to_vault_underlay_allowed"] is False
    assert "does not start" in docker["missing_mapper_behavior"]
    assert "noexec" in docker["passive_asset_execution_behavior"]
    assert "only on project-execution-vault" in docker[
        "project_execution_behavior"
    ]


def test_fr06b1_isolated_lab_proves_copy_recovery_and_fail_closed_behavior() -> None:
    lab = _json(LAB)
    assert lab["subpart"] == "FR-06B1"
    assert lab["all_checks_passed"] is True
    assert lab["production_changed"] is False
    assert lab["lab"]["keys_created_only_on_tmpfs"] is True
    assert lab["lab"]["key_material_persisted"] is False
    evidence = lab["copy_evidence"]
    assert evidence["totals"]["root_count"] == 11
    assert evidence["totals"]["regular_files"] > 0
    assert evidence["totals"]["payload_bytes"] > 0
    assert len(evidence["roots"]) == 11
    assert len(evidence["vaults"]) == 2
    assert {item["vault"] for item in evidence["vaults"]} == {
        "asset-vault",
        "project-execution-vault",
    }
    assert all(item["stable_copy_attempts"] <= 3 for item in evidence["roots"])
    assert evidence["copy_performance"]["production_p95_gate_evaluated"] is False
    serialized = json.dumps(lab, sort_keys=True)
    assert '"entries"' not in serialized
    checks = lab["checks"]
    for name in (
        "all_eleven_roots_present",
        "source_pre_and_post_manifests_stable",
        "copy_metadata_and_content_match",
        "independent_recovery_keys_open_verified",
        "wrong_key_rejected_for_both_vaults",
        "closed_raw_plaintext_markers_absent",
        "recovery_payload_manifests_match",
        "compose_volume_subpath_supported",
        "docker_local_volume_backed_by_mapper_verified",
        "passive_asset_noexec_enforced",
        "project_execution_exec_exception_verified",
        "missing_mapper_failed_closed_without_plaintext_fallback",
        "temporary_docker_resources_removed",
        "temporary_mappings_mounts_keys_and_files_removed",
        "production_container_ids_unchanged",
    ):
        assert checks[name] is True
    assert checks["production_services_stopped_or_restarted"] is False
    assert checks["production_compose_changed"] is False
    assert checks["production_volumes_changed"] is False
    assert checks["live_block_devices_formatted"] is False
    assert checks["cloudflare_changed"] is False


def test_fr06b1_keeps_every_live_cutover_gate_closed() -> None:
    contract = _json(CONTRACT)
    boundary = contract["fr06b1_scope_boundary"]
    assert boundary["production_compose_change_allowed"] is False
    assert boundary["production_service_stop_or_restart_allowed"] is False
    assert boundary["production_volume_write_allowed"] is False
    assert boundary["production_vault_file_creation_allowed"] is False
    assert boundary["fr06b_or_fr06_parent_completion_claimed"] is False
    gates = "\n".join(contract["live_cutover_gates"])
    for required in (
        "fresh encrypted R2 recovery point",
        "outside the unencrypted root",
        "out-of-band",
        "all writers",
        "p95 regression",
        "original plaintext Docker volumes",
        "rollback",
    ):
        assert required in gates
    lab_gate = _json(LAB)["cutover_gate"]
    assert lab_gate["live_cutover_allowed_by_this_receipt"] is False
    assert len(lab_gate["still_required"]) >= 8


def test_fr06b1_scripts_are_safely_scoped_and_syntax_valid() -> None:
    shell = SCRIPT.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    bash_result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    python_result = subprocess.run(
        ["python3", "-m", "py_compile", str(HELPER)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert bash_result.returncode == 0, bash_result.stderr
    assert python_result.returncode == 0, python_result.stderr
    assert "mktemp -d /var/tmp/aionex-fr06b1-lab.XXXXXX" in shell
    assert "mktemp -d /dev/shm/aionex-fr06b1-keys.XXXXXX" in shell
    assert 'mount -o remount,bind,ro,nodev,nosuid,noexec "$source_mirror"' in shell
    assert "volume:\n          subpath: __fr06b_probe" in shell
    assert "missing mapper unexpectedly started against a fallback directory" in shell
    assert "/dev/md0" not in shell
    assert "docker-compose.production.yml" not in shell
    assert "\nsystemctl " not in shell
    assert "\nreboot" not in shell
    assert "O_NOFOLLOW" in helper
    assert "st_nlink != 1" in helper


def test_fr06b1_receipt_and_adr_do_not_overclaim_live_encryption() -> None:
    receipt = RECEIPT.read_text(encoding="utf-8")
    adr = ADR.read_text(encoding="utf-8")
    assert "project-execution-vault" in adr
    assert "volume.subpath" in adr
    assert "do not migrate live data" in adr
    assert "does not protect data from live root" in adr
    assert "does not claim" in receipt.casefold()
    assert "FR-06B2" in _json(CONTRACT)["next_action"]
