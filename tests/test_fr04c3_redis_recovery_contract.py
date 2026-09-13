import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
POLICY_JSON = ROOT / "docs" / "project" / "receipts" / "FR-04C3-redis-recovery-contract.json"


def _service_block(name: str, next_name: str | None = None) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    block = text.split(f"\n  {name}:", 1)[1]
    if next_name is not None:
        block = block.split(f"\n\n  {next_name}:", 1)[0]
    return block


def test_fr04c3_redis_runtime_is_persistent_but_not_snapshot_source() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    redis = _service_block("redis", "postgres")
    backup = _service_block("backup-worker", "communication-worker")
    init = _service_block("backup-asset-root-init", "backup-worker")

    assert '"redis-server", "--appendonly", "yes"' in redis
    assert '"--maxmemory-policy", "noeviction"' in redis
    assert 'volumes: ["redis_data:/data"]' in redis
    assert "redis_data:" in compose

    assert "redis_data" not in backup
    assert "redis_data" not in init
    assert '"redis_data"' not in SNAPSHOT.read_text(encoding="utf-8")


def test_fr04c3_policy_declares_empty_or_flush_after_restore() -> None:
    policy = json.loads(POLICY_JSON.read_text(encoding="utf-8"))
    assert policy["runtime_volume"] == "redis_data"
    assert policy["asset_snapshot_policy"] == "excluded"
    assert policy["disaster_recovery_contract"]["do_not_restore_redis_data_into_dr_artifact"] is True
    action = policy["disaster_recovery_contract"]["post_restore_action"]
    assert "Start Redis empty" in action
    assert "flush runtime namespaces" in action
    assert "PostgreSQL logical backup" in policy["disaster_recovery_contract"]["rehydration_authorities"]
    assert "redis_data" in policy["explicit_non_asset_volumes"]


def test_fr04c3_redis_never_authoritative_for_durable_records() -> None:
    policy = json.loads(POLICY_JSON.read_text(encoding="utf-8"))
    forbidden = "\n".join(policy["disaster_recovery_contract"]["must_not_become_authoritative"])
    assert "billing" in forbidden
    assert "backup" in forbidden
    assert "restore" in forbidden
    assert "security scan" in forbidden
    rebuildable = "\n".join(policy["disaster_recovery_contract"]["safe_to_rebuild_or_expire"])
    assert "leases" in rebuildable
    assert "challenges" in rebuildable
    assert "rate limit" in rebuildable
