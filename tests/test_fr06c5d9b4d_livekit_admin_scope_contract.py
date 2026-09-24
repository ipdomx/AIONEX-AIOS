"""Scope and reporting contract for a real-provider authorization correction."""
from __future__ import annotations
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'web-dashboard/backend/app/realtime/livekit_runtime.py'

def test_participant_grants_bind_same_room_as_payload_with_minimal_privilege():
    tree=ast.parse(SOURCE.read_text())
    runtime=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveKitRuntime')
    for name in ('remove_participant','list_room_participant_inventory'):
        fn=next(n for n in runtime.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
        call=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='self._twirp')
        kw={k.arg:k.value for k in call.keywords}
        grant={ast.literal_eval(k):v for k,v in zip(kw['video_grant'].keys,kw['video_grant'].values)}
        payload={ast.literal_eval(k):v for k,v in zip(kw['payload'].keys,kw['payload'].values)}
        assert set(grant)=={'roomAdmin','room'}
        assert ast.literal_eval(grant['roomAdmin']) is True
        assert ast.dump(grant['room'])==ast.dump(payload['room'])

def test_signed_transport_regressions_are_retained():
    test=ROOT/'web-dashboard/backend/tests/test_fr06c5d9b4d_livekit_room_scope.py'
    source=test.read_text()
    assert 'test_signed_admin_token_keeps_room_binding_through_http_boundary' in source
    assert 'jwt.decode' in source
    assert 'aios-rt-room-a' in source and 'aios-rt-room-b' in source

def test_plan_retains_non_deployment_boundary_and_phase36_receipt():
    plan=json.loads((ROOT/'docs/project/PLAN.json').read_text())
    item=next(x for x in plan['batches'] if x['id']=='FR-06')['host_state_cutover_admission']['realtime_livekit_room_admin_scope_source']
    assert item['source_part']=='FR-06C5D9B4D'
    assert item['participant_admin_grant_keys']==['roomAdmin','room']
    assert item['real_disposable_livekit_failure_reproduced'] is True
    for key in ('production_database_migrated','production_deployment_verified','audio_video_media_session_tested','egress_recording_tested','turn_allocation_drain_verified','provider_drain_verified','full_host_closure','migration_0064_rollout_allowed'):
        assert item[key] is False
    assert all((ROOT/p).is_file() for p in item['evidence'])
