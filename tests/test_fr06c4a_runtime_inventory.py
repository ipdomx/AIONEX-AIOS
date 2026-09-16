import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
C=ROOT/'docs/project/receipts/FR-06C4A-container-runtime-inventory.json'
def contract(): return json.loads(C.read_text())
def test_c4a_is_read_only_and_does_not_authorize_cutover():
    c=contract(); assert c['subpart']=='FR-06C4A'; assert c['production_changed'] is False
    s=c['scope_boundary']; assert s['historical_runtime_copy_allowed'] is False; assert s['production_runtime_cutover_authorized_by_c4a'] is False; assert s['docker_stop_or_restart_permitted_by_c4a'] is False; assert s['vault_provisioning_permitted_by_c4a'] is False
def test_runtime_size_rejects_historical_copy():
    c=contract(); r=c['runtime']; v=c['candidate_vault']; assert r['containerd_root_payload_bytes']>v['preallocated_bytes']; assert v['preallocated_bytes']==64*1024**3; assert r['unique_running_image_count']==17; assert r['unique_running_image_logical_bytes']<16*1024**3
def test_every_active_image_has_exact_authority():
    a=contract()['authority']; assert a['active_runtime_authority_count']==17; assert len(a['rebuild_from_exact_protected_source'])==10; assert len(a['pull_by_digest'])==7; assert all('@sha256:' in x for x in a['pull_by_digest']); assert a['all_running_images_have_reconstruction_authority'] is True
def test_cache_and_runtime_copy_policy_is_clean_rebuild_only():
    c=contract()['cache_policy']; assert c['docker_build_cache']=='do_not_copy'; assert c['containerd_content_store']=='do_not_copy'; assert c['containerd_snapshot_store']=='do_not_copy'; assert c['npm_cache'].startswith('wipe_and_rebuild')
def test_cutover_requires_fail_closed_and_retained_legacy():
    x='\n'.join(contract()['cutover_invariants']); assert 'fail closed' in x; assert 'legacy runtime roots are retained' in x; assert 'admission remains closed' in x
def test_validator_is_read_only():
    t=(ROOT/'scripts/security/fr06c4_validate_runtime_inventory.py').read_text();
    for forbidden in ['docker stop','systemctl stop','cryptsetup','mkfs','mount --','rsync']:
        assert forbidden not in t
