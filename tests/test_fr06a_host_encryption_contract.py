from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06A-host-encryption-contract.json"
)
INVENTORY = (
    ROOT / "docs" / "project" / "receipts" / "FR-06A-live-storage-inventory.json"
)
LAB = ROOT / "docs" / "project" / "receipts" / "FR-06A-isolated-luks-lab.json"
RECEIPT = (
    ROOT / "docs" / "project" / "receipts" / "FR-06A-host-encryption-contract.md"
)
ADR = ROOT / "docs" / "architecture" / "ADR-001-FR-06-host-data-encryption.md"
SCRIPT = ROOT / "scripts" / "security" / "fr06a_luks_lab.sh"
PLAN = ROOT / "docs" / "project" / "PLAN.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fr06a_inventory_proves_live_root_is_not_encrypted() -> None:
    inventory = _json(INVENTORY)
    host = inventory["host"]
    assert host["block_layout"].endswith("md0p2 ext4 root")
    assert host["root_source"] == "/dev/md0p2"
    assert host["root_filesystem"] == "ext4"
    assert host["root_encrypted"] is False
    assert host["active_dm_crypt_mappings"] == 0
    assert host["tpm_devices"] == 0
    assert inventory["production_changed"] is False
    assert inventory["cloudflare_changed"] is False


def test_fr06a_inventory_accounts_for_every_compose_volume() -> None:
    inventory = _json(INVENTORY)
    volumes = {item["name"]: item for item in inventory["volumes"]}
    expected = {
        "web-dashboard_postgres_data",
        "web-dashboard_backup_data",
        "web-dashboard_redis_data",
        "web-dashboard_three_d_asset_data",
        "web-dashboard_media_asset_data",
        "web-dashboard_project_execution_data",
        "web-dashboard_studio_asset_data",
        "web-dashboard_course_package_data",
        "web-dashboard_realtime_recording_data",
        "web-dashboard_portal_asset_data",
        "web-dashboard_mobile_release_data",
        "web-dashboard_audio_song_ingress_data",
        "web-dashboard_security_source_data",
        "web-dashboard_security_remediation_data",
        "web-dashboard_project_npm_cache_data",
        "web-dashboard_security_tool_cache_data",
        "web-dashboard_ollama_model_data",
        "web-dashboard_postgres_socket",
    }
    assert set(volumes) == expected
    assert volumes["web-dashboard_postgres_data"]["fr06_stage"] == "FR-06C"
    assert volumes["web-dashboard_media_asset_data"]["fr06_stage"] == "FR-06B"
    assert "wipe_and_rebuild" in volumes[
        "web-dashboard_project_npm_cache_data"
    ]["disposition"]


def test_fr06a_does_not_omit_swap_logs_tmp_secrets_or_writable_layers() -> None:
    inventory = _json(INVENTORY)
    classes = {item["class"] for item in inventory["host_exposures"]}
    assert {
        "swap",
        "docker_json_logs",
        "system_and_journal_logs",
        "temporary_and_build_data",
        "temporary_release_data",
        "application_secret_material",
        "operator_secret_and_release_material",
        "container_writable_layers",
    } <= classes
    assert inventory["compose_logging"]["driver"] == "json-file"
    assert inventory["postgres"]["pg_wal_inside_pgdata_volume"] is True
    assert inventory["postgres"]["raw_live_copy_allowed"] is False


def test_fr06a_selects_reversible_luks2_domain_vaults() -> None:
    contract = _json(CONTRACT)
    decision = contract["architecture_decision"]
    assert decision["selected_path"] == "preallocated_file_backed_luks2_domain_vaults"
    assert {item["vault"] for item in decision["vault_layout"]} == {
        "asset-vault",
        "database-vault",
        "operations-vault",
        "local-backup-vault",
        "container-runtime-vault",
        "host-state-vault",
    }
    rejected = {item["option"]: item["reason"] for item in decision["not_selected"]}
    assert "destructive" in rejected["retrofit full-root LUKS or repartition md0"]
    assert "offline disk" in rejected[
        "persistent unlock key on the same unencrypted root"
    ]
    assert decision["cloudflare_change_required"] is False


def test_fr06a_crypto_and_key_contract_cannot_persist_unlock_key_on_root() -> None:
    contract = _json(CONTRACT)
    crypto = contract["crypto_contract"]
    keys = contract["key_management"]
    assert crypto["format"] == "LUKS2"
    assert crypto["cipher"] == "aes-xts-plain64"
    assert crypto["key_bits"] == 512
    assert crypto["pbkdf"] == "argon2id"
    assert crypto["container_allocation"] == "preallocated_regular_file_not_sparse"
    assert keys["tpm_available"] is False
    assert keys["active_unlock_material_runtime_location"].endswith(
        "/run/credentials"
    )
    assert keys["persistent_unlock_material_on_root_allowed"] is False
    assert keys[
        "raw_unlock_material_in_git_reports_logs_images_or_vault_files_allowed"
    ] is False
    assert keys["recovery_key_required"] is True
    assert keys["luks_header_backup_required"] is True
    assert keys["header_backup_is_sufficient_without_key"] is False


def test_fr06a_boot_fails_closed_without_plaintext_fallback() -> None:
    boot = _json(CONTRACT)["boot_and_service_contract"]
    assert boot["unattended_unlock_allowed_without_tpm_or_external_kms"] is False
    assert boot["current_mode"].startswith("manual operator unlock")
    assert boot["fail_closed"] is True
    assert boot["services_must_not_start_before_required_vaults_are_mounted"] is True
    assert "no plaintext fallback" in boot["missing_key_behavior"]
    assert "out-of-band alert" in boot["owner_alert_pre_cutover_requirement"]
    assert "remain unavailable" in boot["unexpected_reboot_behavior"]


def test_fr06a_coverage_matches_fr06b_and_fr06c_boundaries() -> None:
    coverage = _json(CONTRACT)["coverage_contract"]
    assert len(coverage["FR-06B"]) == 11
    assert {
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
    } == set(coverage["FR-06B"])
    fr06c = "\n".join(coverage["FR-06C"])
    for required in (
        "postgres_data including pg_wal",
        "backup_data",
        "Docker logs",
        "temporary files",
        "writable-layer spill",
        "secrets",
        "swap",
    ):
        assert required in fr06c
    assert coverage["plaintext_fallback_mount_allowed"] is False
    assert coverage["rebuildable_exclusions_must_be_wiped_before_release"] is True


def test_fr06a_migration_preserves_source_until_verified_cutover() -> None:
    migration = _json(CONTRACT)["migration_contract"]
    assert migration["fr06a_live_data_migration_allowed"] is False
    assert migration["live_raid_reformat_or_repartition_allowed"] is False
    assert migration["source_deletion_before_verified_cutover_allowed"] is False
    sequence = "\n".join(migration["per_vault_sequence"])
    assert "fresh encrypted R2 recovery point" in sequence
    assert "stop only services" in sequence
    assert "retain the original source" in sequence.casefold()
    assert "wipe the original plaintext only after" in sequence.casefold()
    assert migration["cloudflare_changes_allowed"] is False


def test_fr06a_isolated_lab_proves_recovery_and_wrong_key_behavior() -> None:
    lab = _json(LAB)
    assert lab["all_checks_passed"] is True
    assert lab["lab"]["keys_created_only_on_tmpfs"] is True
    assert lab["lab"]["key_material_persisted"] is False
    assert lab["lab"]["cipher"] == "aes-xts-plain64"
    checks = lab["checks"]
    for name in (
        "luks2_format_verified",
        "active_key_open_verified",
        "secondary_recovery_key_open_verified",
        "wrong_key_rejected",
        "closed_raw_plaintext_marker_absent",
        "closed_mapper_absent",
        "header_backup_created_private",
        "erased_keyslots_rejected",
        "header_restore_verified",
        "payload_checksum_after_header_restore_verified",
        "cleanup_verified",
    ):
        assert checks[name] is True
    assert checks["live_block_devices_formatted"] is False
    assert checks["production_mounts_changed"] is False
    assert checks["production_services_touched"] is False
    assert checks["reboot_performed"] is False


def test_fr06a_performance_evidence_is_conservative() -> None:
    contract = _json(CONTRACT)
    lab = _json(LAB)
    performance = lab["performance"]
    assert performance["encrypted_to_plain_write_ratio"] >= 0.7
    assert performance["read_comparison_recorded"] is False
    assert contract["performance_acceptance"]["fr06a_feasibility_passed"] is True
    assert (
        contract["performance_acceptance"][
            "read_comparison_accepted_from_loopback_lab"
        ]
        is False
    )
    assert "not a production SLO" in performance["note"]


def test_fr06a_lab_script_is_safely_scoped_and_syntax_valid() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "mktemp -d /var/tmp/aionex-fr06a-lab.XXXXXX" in source
    assert "mktemp -d /dev/shm/aionex-fr06a-keys.XXXXXX" in source
    assert '[[ "$IMAGE" == /var/tmp/aionex-fr06a-lab.*/vault.luks2 ]]' in source
    assert "cryptsetup luksFormat" in source
    assert 'cryptsetup luksErase --batch-mode "$IMAGE"' in source
    assert 'cryptsetup luksHeaderRestore --batch-mode "$IMAGE"' in source
    assert 'grep -aF -m1 "$MARKER" "$IMAGE"' in source
    assert 'cryptsetup open --type luks --key-file "$WRONG_KEY"' in source
    assert "/dev/md0" not in source
    assert "docker compose" not in source
    assert "\nsystemctl " not in source
    assert "\nreboot" not in source


def test_fr06a_receipt_and_adr_do_not_overclaim_production_encryption() -> None:
    receipt = RECEIPT.read_text(encoding="utf-8")
    adr = ADR.read_text(encoding="utf-8")
    boundary = "\n".join(_json(CONTRACT)["scope_boundary"]["fr06a_does_not_claim"])
    assert "production data encrypted at rest" in boundary
    assert "full-disk encryption" in boundary
    assert "safe unattended reboot" in boundary
    assert "does not claim" in receipt.casefold()
    assert "does not protect data from live root" in adr
    assert "FR-06B" in _json(CONTRACT)["scope_boundary"]["next_action"]


def test_fr06_plan_keeps_asset_and_database_migrations_after_fr06a() -> None:
    plan = _json(PLAN)
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    subparts = "\n".join(fr06["sub_batches"])
    assert "FR-06A نموذج التهديد والمفاتيح وتجربة أداء/إقلاع معزولة" in subparts
    assert "FR-06B أصول المستخدمين والمشاريع" in subparts
    assert "FR-06C بيانات المحادثات" in subparts
    assert fr06["depends_on"] == ["FR-05"]
