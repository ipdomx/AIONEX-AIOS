from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C3B-backup-operations-contract.json"
LAB = ROOT / "docs/project/receipts/FR-06C3B-isolated-backup-redis-rehearsal.json"
SCRIPT = ROOT / "scripts/security/fr06c3b_backup_redis_isolated_lab.py"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_c3b_scope_is_isolated_only() -> None:
    c = _json(CONTRACT)
    assert c["subpart"] == "FR-06C3B"
    assert c["implementation_status"] == "source_contract_and_isolated_rehearsal_only"
    assert c["scope_boundary"]["production_vault_created"] is False
    assert c["scope_boundary"]["production_volume_copied"] is False
    assert c["scope_boundary"]["production_redis_stopped_or_flushed"] is False
    assert c["scope_boundary"]["cloudflare_changed"] is False


def test_backup_contract_requires_offline_exact_copy_and_fresh_recovery() -> None:
    b = _json(CONTRACT)["local_backup_vault"]
    assert b["planned_bytes"] == 16 * 1024**3
    assert b["readers"] == ["backend"]
    assert b["writers"] == ["backup-worker"]
    assert b["live_copy_while_writer_active_allowed"] is False
    assert "exact offline manifest copy" in b["production_cutover_rule"]
    assert "independent restore" in b["production_cutover_rule"]


def test_redis_contract_rejects_legacy_aof_as_authority() -> None:
    o = _json(CONTRACT)["operations_vault"]
    assert o["planned_bytes"] == 8 * 1024**3
    assert o["redis_is_disaster_recovery_authority"] is False
    assert o["raw_live_aof_copy_allowed"] is False
    assert "PostgreSQL" in o["selected_redis_recovery"]
    assert o["docker_json_logs_owned_by"] == "container-runtime-vault"


def test_isolated_rehearsal_proves_backup_and_redis_boundaries() -> None:
    r = _json(LAB)
    assert r["status"] == "isolated_backup_redis_reconciliation_pass"
    assert r["production_backup_data_used"] is False
    assert r["production_redis_data_used"] is False
    assert r["production_mutation_performed"] is False
    assert r["local_backup_vault"]["wrong_key_rejected"] is True
    assert r["local_backup_vault"]["stable_copy_manifest_match"] is True
    assert r["local_backup_vault"]["recovery_key_manifest_match"] is True
    assert r["local_backup_vault"]["closed_raw_plaintext_marker_absent"] is True
    assert r["operations_vault"]["legacy_redis_aof_copied"] is False
    assert r["operations_vault"]["redis_started_empty"] is True
    assert r["operations_vault"]["explicit_reconciliation_flush_passed"] is True
    assert r["operations_vault"]["redis_empty_after_active_key_reopen"] is True
    assert r["temporary_resources_removed"] is True
    assert r["production_container_identity_unchanged"] is True


def test_lab_source_cannot_claim_production_cutover() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"production_cutover_authorized": False' in text
    assert '"production_backup_data_used": False' in text
    assert '"production_redis_data_used": False' in text
    assert "aionex-fr06c3b-lab-" in text
