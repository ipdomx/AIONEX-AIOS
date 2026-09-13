from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
RECEIPT = ROOT / "docs" / "project" / "receipts" / "FR-04C2-cache-socket-model-redis-policy.md"
INVENTORY = ROOT / "docs" / "project" / "receipts" / "FR-04A-persistent-root-inventory.json"

EXCLUDED_SOURCE_ROOTS = {
    "project_npm_cache_data",
    "security_tool_cache_data",
    "ollama_model_data",
    "postgres_socket",
    "redis_data",
}
DESTINATION_ONLY_ROOTS = {"backup_data"}


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def test_fr04c2_excluded_roots_not_backup_worker_asset_sources() -> None:
    backup = _service_block("backup-worker", "communication-worker")
    for root in EXCLUDED_SOURCE_ROOTS:
        assert root not in backup
    assert "backup_data:/var/lib/aionex/backups:rw" in backup


def test_fr04c2_excluded_roots_not_snapshot_source_ids() -> None:
    source = SNAPSHOT.read_text(encoding="utf-8")
    for root in EXCLUDED_SOURCE_ROOTS | DESTINATION_ONLY_ROOTS:
        assert f'"{root}"' not in source


def test_fr04c2_policy_receipt_names_all_exclusions_and_redis_contract() -> None:
    text = RECEIPT.read_text(encoding="utf-8")
    inventory = INVENTORY.read_text(encoding="utf-8")
    for root in EXCLUDED_SOURCE_ROOTS | DESTINATION_ONLY_ROOTS:
        assert f"`{root}`" in text
        assert f'"{root}"' in inventory
    assert "Redis AOF" in text
    assert "separate consistency/rebuild contract" in text
    assert "explicit_policy" in inventory
