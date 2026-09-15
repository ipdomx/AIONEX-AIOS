from __future__ import annotations

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C2-database-vault-contract.json"
LAB = ROOT / "docs/project/receipts/FR-06C2-isolated-database-migration.json"
OVERLAY = ROOT / "web-dashboard/docker-compose.fr06-database.yml"
ADMISSION = ROOT / "web-dashboard/docker-compose.fr06-database-admission.yml"
VALIDATOR = ROOT / "scripts/security/fr06c2_validate_database_overlay.py"
GIB = 1024**3


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fr06c2_contract_is_source_only_and_forbids_online_raw_copy() -> None:
    value = _json(CONTRACT)
    assert value["batch_id"] == "FR-06"
    assert value["subpart"] == "FR-06C2A"
    assert value["implementation_status"] == "source_contract_and_isolated_rehearsal_only"
    assert value["database"]["online_raw_pgdata_copy_allowed"] is False
    assert value["database"]["required_shutdown_state"] == "shut down"
    assert value["database"]["planned_vault_bytes"] == 16 * GIB
    assert value["scope_boundary"]["production_pgdata_copied"] is False
    assert value["scope_boundary"]["parent_fr06_completed"] is False


def test_database_vault_crypto_and_mapper_contract_is_explicit() -> None:
    vault = _json(CONTRACT)["candidate_vault"]
    assert vault["role"] == "database-vault"
    assert vault["mapper"] == "/dev/mapper/aionex-database-vault"
    assert vault["docker_volume"] == "aionex-fr06-database-vault"
    assert vault["mount_options"] == ["nodev", "nosuid", "noexec"]
    assert vault["format"] == "LUKS2"
    assert vault["cipher"] == "aes-xts-plain64"
    assert vault["key_bits"] == 512
    assert vault["pbkdf"] == "argon2id"
    assert vault["production_key_on_unencrypted_root_allowed"] is False
    assert vault["target_subpath"] == "pgdata"


def test_pgdata_consumers_and_database_clients_are_fully_guarded() -> None:
    value = _json(CONTRACT)
    assert value["database"]["pgdata_consumers"] == [
        "postgres",
        "postgres-credential-reconciler",
    ]
    clients = value["database_clients"]["services"]
    assert len(clients) == 24
    assert value["database_clients"]["service_definition_count"] == 24
    assert value["database_clients"]["candidate_restart_policy"] == "no"
    assert value["database_clients"]["postgres_restart_policy"] == "no"
    admission = ADMISSION.read_text(encoding="utf-8")
    for service in [*clients, "postgres"]:
        assert f"  {service}:" in admission


def test_overlay_uses_external_database_volume_without_plaintext_fallback() -> None:
    text = OVERLAY.read_text(encoding="utf-8")
    assert "source: fr06_database_vault" in text
    assert "target: /var/lib/postgresql/data" in text
    assert "name: aionex-fr06-database-vault" in text
    assert "external: true" in text
    assert text.count("subpath: pgdata") == 2
    assert "postgres_data:/var/lib/postgresql/data" not in text


def test_source_overlay_validator_passes_example_environment() -> None:
    result = subprocess.run(
        [
            "python3",
            str(VALIDATOR),
            "--root",
            str(ROOT),
            "--env-file",
            str(ROOT / "web-dashboard/.env.production.example"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["validation"] == "FR06C2_DATABASE_OVERLAY_PASS"
    assert value["database_client_service_count"] == 24
    assert value["legacy_pgdata_mounts_after_merge"] == 0
    assert value["unrelated_service_or_top_level_drift"] is False
    assert value["production_changed"] is False


def test_isolated_physical_migration_recovery_passed_without_production_data() -> None:
    value = _json(LAB)
    assert value["status"] == "isolated_database_physical_migration_recovery_pass"
    assert value["production_pgdata_used"] is False
    assert value["production_mutation_performed"] is False
    assert value["source_cluster_state_before_copy"] == "shut down"
    assert value["online_raw_copy_performed"] is False
    assert value["pg_wal_included"] is True
    assert value["source_candidate_manifest_match"] is True
    assert value["wrong_key_rejected"] is True
    assert value["independent_recovery_key_open_passed"] is True
    assert value["row_validated_after_active_open"] is True
    assert value["row_validated_after_recovery_open"] is True
    assert value["closed_raw_plaintext_marker_absent"] is True
    assert value["keys_only_on_tmpfs"] is True
    assert value["production_container_identity_unchanged"] is True
    assert value["temporary_resources_removed"] is True
    assert value["production_cutover_authorized"] is False


def test_recovery_and_rollback_gates_precede_any_production_cutover() -> None:
    value = _json(CONTRACT)
    gates = value["production_cutover_gates"]
    assert any("R2" in item and "restore" in item for item in gates)
    assert any("clean shutdown" in item for item in gates)
    assert any("manifest" in item for item in gates)
    assert any("legacy PGDATA" in item for item in gates)
    rollback = value["rollback"]
    assert rollback["legacy_pgdata_deleted"] is False
    assert rollback["blind_candidate_to_legacy_copy_allowed"] is False
