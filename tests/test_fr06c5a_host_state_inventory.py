from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C5A-host-state-inventory.json').read_text())
def test_read_only_scope():
 x=c();assert x['scope_boundary']['read_only_inventory'] is True;assert x['scope_boundary']['production_secrets_read'] is False;assert x['scope_boundary']['production_files_moved'] is False
def test_bootstrap_is_minimal_and_preserves_shared_tunnel():
 b=c()['management_bootstrap_exception'];assert b['control_plane_key_count']==1;assert len(b['active_tunnel_configs'])==3;assert b['other_project_tunnel_config_preserved'] is True;assert b['old_or_backup_tunnel_configs_must_not_remain_in_bootstrap'] is True
def test_vault_capacity_covers_current_state_with_margin():
 x=c();used=x['observed_operator_state']['payload_bytes_approx']+x['observed_application_secrets']['payload_bytes_approx'];assert x['host_state_vault']['planned_bytes']>2*used
def test_swap_policy_has_no_persistent_key():
 s=c()['swap'];assert s['current']=='plaintext file swap on root';assert 'random-key encrypted swap' in s['selected'];assert s['hibernation_required'] is False
def test_tmp_policy_is_volatile():assert c()['temporary_data']['tmp']['selected']=='tmpfs'


def test_deploy_private_keys_are_encrypted_not_bootstrap():
    x=c(); b=x['management_bootstrap_exception']; assert b['deployment_private_keys_are_bootstrap'] is False
    assert set(x['host_state_vault']['ssh_private_bind_targets'])=={'/root/.ssh/aionex_aios_deploy','/root/.ssh/aionex_cpanel_ai_vip_e_net_ed25519'}
    assert b['break_glass_authorized_keys_must_remain_available_before_unlock'] is True

def test_tunnel_configs_reference_shared_environment_key():
    b=c()['management_bootstrap_exception']; assert b['active_tunnel_configs_contain_raw_api_key'] is False
    assert b['active_tunnel_configs_api_key_source']=='CONTROL_PLANE_API_KEY environment reference'


def test_shared_bridge_upstream_is_explicit_minimal_bootstrap():
    b=c()['management_bootstrap_exception']
    assert b['shared_bridge_upstream_source']=='/root/.config/aionex/trendbost-mcp-upstream.url'
    assert b['shared_bridge_upstream_bootstrap_target']=='/root/.config/aionex-bootstrap/trendbost-mcp-upstream.url'
    assert c()['selected_bootstrap_path']['control_plane_key_target']=='/root/.config/aionex-bootstrap/control-plane.key'


def test_swap_used_bytes_is_observation_not_zero_gate():
    s=c()["swap"]; assert s["used_bytes_is_dynamic_observation"] is True; assert s["cutover_requires_pre_swapoff_capacity_check"] is True; assert s["bytes"]==8388604*1024
