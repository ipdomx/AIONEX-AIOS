from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs/project/receipts/FR-06C3A-operations-backup-inventory.json"
COMPOSE = ROOT / "web-dashboard/docker-compose.production.yml"


def _receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_c3a_is_read_only_and_parent_stays_open() -> None:
    r = _receipt()
    assert r["subpart"] == "FR-06C3A"
    assert r["production_mutation_performed"] is False
    assert r["cloudflare_changed"] is False
    assert r["parent_batch_completed"] is False
    assert "authorizes no production" in r["release_boundary"]


def test_local_backup_domain_contract_is_bounded() -> None:
    r = _receipt()["local_backup_domain"]
    assert r["legacy_runtime_volume"] == "web-dashboard_backup_data"
    assert r["planned_vault_bytes"] == 16 * 1024**3
    assert r["readers"] == ["backend"]
    assert r["writers"] == ["backup-worker"]
    assert r["symlink_count"] == 0
    assert "stop backup-worker" in r["cutover_rule"]
    assert "independent restore" in r["cutover_rule"]


def test_redis_is_not_promoted_to_recovery_authority() -> None:
    r = _receipt()
    ops = r["operations_domain"]
    consistency = r["consistency"]
    assert ops["redis_aof_enabled"] is True
    assert ops["redis_appendfsync"] == "everysec"
    assert ops["redis_maxmemory_policy"] == "noeviction"
    assert ops["redis_rebuildable_from_durable_authorities"] is True
    assert consistency["redis_is_not_disaster_recovery_authority"] is True
    assert consistency["redis_raw_live_copy_allowed"] is False
    assert ops["docker_json_logs_excluded_to_container_runtime_domain"] is True


def test_current_compose_mounts_match_inventory() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "backup_data:/var/lib/aionex/backups:ro" in text
    assert "backup_data:/var/lib/aionex/backups:rw" in text
    assert 'volumes: ["redis_data:/data"]' in text
    assert '"--appendonly", "yes"' in text
    assert '"--maxmemory-policy", "noeviction"' in text


def test_c3_order_keeps_production_after_isolated_rehearsal() -> None:
    order = _receipt()["required_order"]
    assert order[0].startswith("FR-06C3A")
    assert order[1].startswith("FR-06C3B isolated")
    assert order[2].startswith("FR-06C3C protected")
    assert order[3].startswith("FR-06C3D production")
    assert order[4].startswith("FR-06C3E production")
