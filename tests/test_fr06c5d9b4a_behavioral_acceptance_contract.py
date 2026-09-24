"""Track executable behavioral acceptance separately from source shape checks."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'web-dashboard/backend/app/services/host_maintenance_realtime_provider_inventory.py'
BEHAVIOR = ROOT / 'web-dashboard/backend/tests/test_fr06c5d9b4a_realtime_behavioral_acceptance.py'


def test_plan_keeps_d9b4_open_to_behavioral_and_independent_live_acceptance():
    plan = json.loads((ROOT / 'docs/project/PLAN.json').read_text())
    root = next(x for x in plan['batches'] if x['id']=='FR-06')['host_state_cutover_admission']
    assert root['source_part'] == 'FR-06C5D9B4'
    item = root['realtime_behavioral_acceptance_source']
    assert item['source_part'] == 'FR-06C5D9B4A'
    assert item['real_disposable_postgresql'] and item['provider_transport_simulated']
    assert item['authority_revalidated_after_provider_read']
    assert item['tenant_scoped_ownership_history']
    for name in ('production_database_migrated','production_deployment_verified',
                 'live_provider_acceptance_verified','turn_allocation_drain_verified',
                 'migration_0064_rollout_allowed','provider_drain_verified','full_host_closure'):
        assert item[name] is False
    assert BEHAVIOR.is_file()
    assert all((ROOT / path).is_file() for path in item['evidence'])


def test_behavioral_suite_executes_crash_cancellation_and_postgresql_transitions():
    source = BEHAVIOR.read_text()
    tree = ast.parse(source)
    names = {node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef)}
    assert {'test_process_exit_after_committed_begin_preserves_uncertain_intent',
            'test_cancel_after_committed_bundle_keeps_both_submitted_owners',
            'test_authority_change_during_inventory_rejected',
            'test_other_tenant_history_never_hides_unowned_livekit_room'} <= names
    assert 'asyncio.create_subprocess_exec' in source
    assert 'os._exit(73)' in source
    assert 'postgresql+asyncpg' in source
    assert 'DropSchema(schema, cascade=True)' in source


def test_provider_result_requires_second_durable_snapshot_before_return():
    source = SERVICE.read_text()
    first = source.index('drain = await measure_realtime_drain')
    io = source.index('runtime.list_aios_room_inventory()', first)
    second = source.index('revalidated = await measure_realtime_drain', io)
    check = source.index('revalidated.authority != drain.authority', second)
    result = source.index('return RealtimeProviderInventorySnapshot(', check)
    assert first < io < second < check < result
    assert 'asyncio.timeout(_PROVIDER_INVENTORY_TIMEOUT_SECONDS)' in source
    assert 'revalidated_drain=revalidated' in source
