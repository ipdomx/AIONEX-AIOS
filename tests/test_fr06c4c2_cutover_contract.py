import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C4C2-clean-runtime-cutover-contract.json').read_text())
def test_candidate_is_reconstructed_not_copied():
 r=c()['candidate_reconstruction']; assert r['historical_docker_root_copy'] is False; assert r['historical_containerd_root_copy'] is False; assert r['historical_build_cache_copy'] is False; assert r['image_authority_count']==17
def test_exact_five_authoritative_external_volumes():
 v=c()['external_authoritative_volumes']; assert len(v)==5; assert set(v)=={'aionex-fr06-asset-vault','aionex-fr06-project-execution-vault','aionex-fr06-database-vault','aionex-fr06-local-backup-vault','aionex-fr06-operations-vault'}
def test_runtime_caches_are_rebuilt_or_empty():
 r=c()['rebuildable_runtime_state']; assert 'rebuilt' in r['web-dashboard_ollama_model_data']; assert 'rebuilt' in r['web-dashboard_project_npm_cache_data']; assert r['web-dashboard_postgres_socket'].endswith('empty'); assert r['docker_buildkit_cache']=='not copied'
def test_cutover_stops_both_daemons_before_bind_mount_switch():
 order='\n'.join(c()['live_cutover_order']); assert 'stop Docker then containerd' in order; assert 'start containerd then Docker' in order; assert 'exactly the previously-running service topology' in order
def test_rollback_never_reverse_copies_runtime_layers():
 r=c()['rollback']; assert r['legacy_underlay_retained'] is True; assert r['blind_runtime_reverse_copy_allowed'] is False; assert 'never reverse-copy' in r['after_candidate_runtime_started']
def test_source_merge_is_inert():
 b=c()['production_boundary']; assert all(v is False for v in b.values())
