from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C2-database-vault-contract.json"
LAB_RECEIPT = ROOT / "docs/project/receipts/FR-06C2-isolated-database-vault-lab.json"
LAB_SCRIPT = ROOT / "scripts/security/fr06c2_database_vault_lab.sh"
GIB = 1024**3


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_database_vault_contract_is_not_production_authorization() -> None:
    value = _json(CONTRACT)
    assert value["batch_id"] == "FR-06"
    assert value["subpart"] == "FR-06C2"
    assert value["production_authorization"] is False
    assert value["vault"]["preallocated_non_sparse_bytes"] == 16 * GIB
    assert value["vault"]["source_volume"] == "web-dashboard_postgres_data"
    assert value["vault"]["mount_options"] == ["nodev", "nosuid", "noexec"]


def test_database_copy_requires_clean_offline_source_and_wal() -> None:
    consistency = _json(CONTRACT)["consistency"]
    assert consistency["raw_online_pgdata_copy_allowed"] is False
    assert consistency["fresh_encrypted_r2_backup_and_independent_restore_required_before_cutover"] is True
    assert consistency["all_database_clients_stopped_before_final_copy"] is True
    assert consistency["postgres_clean_shutdown_required"] is True
    assert consistency["postmaster_pid_must_be_absent"] is True
    assert consistency["pg_wal_must_be_nonempty_and_included"] is True
    assert consistency["legacy_source_retained_read_only"] is True
    assert consistency["source_and_candidate_file_manifest"] == [
        "relative_path", "size", "mode", "uid", "gid", "sha256"
    ]


def test_database_vault_crypto_and_rollback_are_independent() -> None:
    value = _json(CONTRACT)
    crypto = value["crypto"]
    assert crypto["format"] == "LUKS2"
    assert crypto["cipher"] == "aes-xts-plain64"
    assert crypto["key_bits"] == 512
    assert crypto["pbkdf"] == "argon2id"
    assert crypto["active_and_recovery_keys_independent"] is True
    assert crypto["production_key_persistence_on_root_allowed"] is False
    assert crypto["off_host_header_backup_required"] is True
    assert crypto["header_and_recovery_key_custody_must_be_separate"] is True
    rollback = value["rollback"]
    assert rollback["legacy_data_deleted_during_fr06c2"] is False
    assert "reverse delta" in rollback["after_application_clients_start"]


def test_compose_change_is_additive_and_socket_stays_ephemeral() -> None:
    compose = _json(CONTRACT)["compose"]
    assert compose["base_file_unchanged"] is True
    assert compose["additive_overlay_planned"] == "web-dashboard/docker-compose.fr06-database.yml"
    assert set(compose["affected_definitions"]) == {"postgres", "postgres-credential-reconciler"}
    assert compose["postgres_data_legacy_mounts_after_overlay"] == 0
    assert compose["postgres_socket_remains_ephemeral"] is True
    assert compose["plain_host_bind_fallback_allowed"] is False


def test_isolated_lab_receipt_proves_only_synthetic_boundary() -> None:
    value = _json(LAB_RECEIPT)
    assert value["status"] == "isolated_lab_passed"
    assert value["synthetic_only"] is True
    assert value["source_file_count"] > 1000
    assert value["manifest_match"] is True
    assert value["active_key_open"] is True
    assert value["wrong_key_rejected"] is True
    assert value["recovery_key_reopen"] is True
    assert value["postgres_start_on_encrypted_noexec_mount"] is True
    assert value["synthetic_rows_verified"] == 2
    assert value["pg_wal_bytes"] > 0
    assert value["production_data_touched"] is False
    assert value["production_services_touched"] is False
    assert value["production_vault_created"] is False
    assert value["production_key_created"] is False


def test_lab_script_hard_codes_synthetic_paths_and_tmpfs_keys() -> None:
    text = LAB_SCRIPT.read_text(encoding="utf-8")
    assert '/var/tmp/fr06c2-db-lab-' in text
    assert '/dev/shm/fr06c2-db-lab-' in text
    assert 'production_path_forbidden' in text
    assert 'docker stop -t 60 "$SOURCE_CONTAINER"' in text
    assert 'rows.sort(key=lambda item:item[0])' in text
    assert 'cmp -s "$LAB/source.json" "$LAB/target.json"' in text
    assert 'wrong_key_accepted' in text
    assert 'production_data_touched' in text
    assert '/var/lib/docker/volumes/web-dashboard_postgres_data' not in text


def test_c2_is_split_before_any_live_cutover() -> None:
    parts = _json(CONTRACT)["parts"]
    assert len(parts) == 4
    assert parts[0].startswith("FR-06C2A")
    assert parts[1].startswith("FR-06C2B")
    assert parts[2].startswith("FR-06C2C")
    assert parts[3].startswith("FR-06C2D")
    value = _json(CONTRACT)
    assert value["next_gate"].startswith("FR-06C2A")
    assert value["requires_fr06c2a_postmerge_before_production_provisioning"] is True
