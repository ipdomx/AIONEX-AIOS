from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs/project/receipts/FR-06C1-live-inventory-and-sequencing.json"
PLAN = ROOT / "docs/project/receipts/FR-06C1-host-data-plan.md"
ADR = ROOT / "docs/architecture/ADR-001-FR-06-host-data-encryption.md"
GIB = 1024**3


def _receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_fr06c1_is_read_only_and_does_not_close_parent() -> None:
    value = _receipt()
    assert value["batch_id"] == "FR-06"
    assert value["subpart"] == "FR-06C1"
    assert value["production_mutation_performed"] is False
    assert value["cloudflare_changed"] is False
    assert value["parent_batch_completed"] is False
    assert value["subpart_completed"] is False
    assert "source_candidate" in value["status"]


def test_all_five_remaining_domains_and_swap_are_explicit() -> None:
    value = _receipt()
    assert value["database_domain"]["vault"] == "database-vault"
    assert value["operations_domain"]["vault"] == "operations-vault"
    assert value["local_backup_domain"]["vault"] == "local-backup-vault"
    assert value["container_runtime_domain"]["vault"] == "container-runtime-vault"
    assert value["host_state_domain"]["vault"] == "host-state-vault"
    assert value["swap"]["selected_path"].startswith("random-key encrypted swap")
    adr = ADR.read_text(encoding="utf-8")
    for name in (
        "database-vault",
        "operations-vault",
        "local-backup-vault",
        "container-runtime-vault",
        "host-state-vault",
    ):
        assert f"`{name}`" in adr


def test_database_contract_forbids_online_pgdata_copy() -> None:
    database = _receipt()["database_domain"]
    assert database["source_volume"] == "web-dashboard_postgres_data"
    assert database["raw_live_copy_allowed"] is False
    assert database["pg_wal_bytes"] > 0
    assert database["contains_user_and_platform_authoritative_state"] is True
    assert "clean shutdown" in database["cutover_rule"]
    assert database["planned_vault_bytes"] >= 16 * GIB


def test_container_runtime_rejects_blind_historical_copy() -> None:
    runtime = _receipt()["container_runtime_domain"]
    assert runtime["containerd_root"] == "/var/lib/containerd"
    assert runtime["containerd_root_payload_bytes"] > 300 * GIB
    assert runtime["containerd_root_payload_bytes"] > _receipt()["capacity_plan"]["root_available_bytes_at_inventory"]
    assert runtime["historical_runtime_copy_rejected"] is True
    assert "clean encrypted runtime reconstruction" in runtime["selected_path"]
    assert runtime["planned_vault_bytes"] == 64 * GIB
    assert len(runtime["running_services_with_pruned_image_metadata"]) == 5


def test_capacity_plan_retains_large_rollback_headroom() -> None:
    capacity = _receipt()["capacity_plan"]
    assert capacity["total_new_fr06c_preallocated_bytes"] == 136 * GIB
    assert capacity["post_preallocation_headroom_bytes_approx"] >= 128 * GIB
    assert capacity["source_retention_required_during_rollback_window"] is True


def test_rebuildable_caches_are_not_misclassified_as_authoritative() -> None:
    caches = _receipt()["rebuildable_cache_domains"]
    assert "wipe and rebuild" in caches["project_npm_cache"]["action"]
    assert "wipe and rebuild" in caches["security_tool_cache"]["action"]
    assert "wipe and rebuild" in caches["ollama_model_cache"]["action"]
    assert caches["postgres_socket"]["action"].startswith("ephemeral")


def test_bootstrap_exception_is_explicit_residual_risk_not_encryption_claim() -> None:
    host = _receipt()["host_state_domain"]
    assert host["management_bootstrap_exception_required"] is True
    assert host["bootstrap_scope_must_be_minimal_and_separately_risk_documented"] is True
    text = PLAN.read_text(encoding="utf-8")
    assert "minimal reviewed management bootstrap" in text
    assert "documented residual risk for FR-23" in text
    assert "No claim of full-disk encryption" in text


def test_required_order_ends_in_real_reboot_before_parent_closure() -> None:
    order = _receipt()["required_order"]
    assert len(order) == 6
    assert order[0].startswith("FR-06C1")
    assert order[-1].startswith("FR-06C6 real host reboot")
    assert "FR-06 parent closure" in order[-1]
