import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / 'web-dashboard/docker-compose.production.yml'
INVENTORY = ROOT / 'docs/project/receipts/FR-04A-persistent-root-inventory.json'


def _production_named_volumes() -> set[str]:
    text = COMPOSE.read_text(encoding='utf-8')
    tail = text.split('\nvolumes:\n', 1)[1].split('\nnetworks:\n', 1)[0]
    return {line.strip().removesuffix(':') for line in tail.splitlines() if line.startswith('  ') and line.strip().endswith(':')}


def test_every_production_named_volume_has_recovery_classification() -> None:
    data = json.loads(INVENTORY.read_text(encoding='utf-8'))
    classified = {item['name'] for item in data['volumes']}
    assert classified == _production_named_volumes()


def test_missing_user_data_roots_are_explicit_and_cache_exclusions_are_narrow() -> None:
    data = json.loads(INVENTORY.read_text(encoding='utf-8'))
    items = {item['name']: item for item in data['volumes']}
    required = set(data['fr04b_required_additions'])
    assert required
    assert all(items[name]['required_recovery'] == 'include' for name in required)
    assert all(items[name]['current_coverage'] == 'missing' for name in required)
    assert items['postgres_data']['current_coverage'] == 'covered_logically'
    assert items['three_d_asset_data']['current_coverage'] == 'covered_snapshot'
    assert items['redis_data']['required_recovery'] == 'explicit_policy'
    rebuildable = {name for name, item in items.items() if item['required_recovery'] == 'exclude_rebuildable'}
    assert rebuildable == {'project_npm_cache_data', 'security_tool_cache_data', 'ollama_model_data'}
