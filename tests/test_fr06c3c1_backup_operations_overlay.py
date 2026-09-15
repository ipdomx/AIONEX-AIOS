from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C3C1-backup-operations-overlay-contract.json"


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _validator():
    path = ROOT / "scripts/security/fr06c3_validate_backup_operations_overlay.py"
    spec = importlib.util.spec_from_file_location("fr06c3_overlay_validator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_is_source_only_and_exact_domains() -> None:
    c = _contract()
    assert c["subpart"] == "FR-06C3C1"
    assert c["implementation_status"] == "source_only_mapper_backed_overlays_and_validator"
    assert c["local_backup"]["candidate_docker_volume"] == "aionex-fr06-local-backup-vault"
    assert c["operations"]["candidate_docker_volume"] == "aionex-fr06-operations-vault"
    assert c["operations"]["legacy_aof_copy_authorized"] is False
    assert c["scope_boundary"]["production_vault_created"] is False
    assert c["scope_boundary"]["production_data_copied"] is False


def test_backup_access_modes_are_least_privilege() -> None:
    b = _contract()["local_backup"]
    assert b["consumers"] == {"backend": "ro", "backup-worker": "rw"}
    assert b["candidate_subpath"] == "backups"
    assert "noexec" in b["mount_options"]


def test_operations_redis_is_guarded_and_not_authority() -> None:
    o = _contract()["operations"]
    assert o["candidate_subpath"] == "redis"
    assert o["redis_restart_policy"] == "no"
    assert o["legacy_aof_copy_authorized"] is False
    assert "reconciled" in o["recovery_policy"]


def test_validator_passes_example_render() -> None:
    result = _validator().validate(ROOT, ROOT / "web-dashboard/.env.production.example")
    assert result["validation"] == "FR06C3_BACKUP_OPERATIONS_OVERLAY_PASS"
    assert result["legacy_backup_mounts_after_candidate"] == 0
    assert result["legacy_redis_mounts_after_candidate"] == 0
    assert result["redis_restart_policy"] == "no"
    assert result["unrelated_service_or_top_level_drift"] is False
    assert result["production_changed"] is False
