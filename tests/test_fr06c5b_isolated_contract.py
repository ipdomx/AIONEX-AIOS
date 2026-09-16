from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C5B-isolated-host-state-contract.json').read_text())
def test_scope_is_synthetic_only():
 x=c(); assert x['lab']['production_operator_state_read'] is False; assert x['lab']['production_application_secrets_read'] is False; assert x['scope_boundary']['production_changed'] is False
def test_luks_recovery_contract():
 x=c()['lab']; assert x['synthetic_metadata_preserved'] and x['wrong_key_rejected'] and x['independent_recovery_key_required'] and x['active_key_reopen_required'] and x['closed_plaintext_marker_absent']
def test_bootstrap_is_minimal_and_excludes_deploy_keys():
 b=c()['bootstrap_rehearsal']; assert b['dedicated_minimal_bootstrap'] and b['deployment_private_keys_excluded'] and b['deployment_private_keys_remain_in_encrypted_host_state']
def test_bootstrap_keeps_required_preunlock_paths():
 b=c()['bootstrap_rehearsal']; assert b['three_tunnel_configs_use_environment_reference'] and b['shared_bridge_upstream_preserved'] and b['break_glass_authorized_keys_preserved']
def test_swap_is_random_key_and_not_enabled():
 s=c()['swap_rehearsal']; assert s['actual_swapon_permitted'] is False and s['random_key_tmpfs_only'] and s['new_random_key_cannot_read_prior_swap_signature'] and s['persistent_recovery_key'] is False
def test_tmpfs_is_disposable_only():
 t=c()['tmpfs_rehearsal']; assert t['mount_only_disposable_path'] and t['production_tmp_mount_permitted'] is False and t['data_disappears_after_unmount']
def test_next_subpart():assert c()['next_subpart'].startswith('FR-06C5C')
