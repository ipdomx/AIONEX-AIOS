from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C5C1-host-state-provision-bootstrap-contract.json').read_text())
def test_source_merge_is_inert():
 p=c()['production_boundary'];assert p['source_merge_copies_bootstrap_key'] is False;assert p['source_merge_provisions_vault'] is False;assert p['source_merge_moves_secrets'] is False;assert p['source_merge_stops_docker'] is False
def test_vault_contract():
 v=c()['vault'];assert v['preallocated_bytes']==32*1024**3;assert v['keyslots']==2;assert set(v['mount_options'])=={'nodev','nosuid','noexec'}
def test_minimal_bootstrap_excludes_deploy_keys():
 b=c()['bootstrap'];assert b['deployment_private_keys_excluded'] is True;assert b['apply_restarts_tunnels'] is False
def test_wrappers_use_bootstrap_only():
 for n in ('aionex-phase22c-2-tunnel','aionex-phase22c-tunnel','trendbost-mcp-bridge-tunnel'):
  t=(ROOT/'deploy/bin'/n).read_text();assert '/root/.config/aionex-bootstrap/control-plane.key' in t;assert '/root/.config/aionex/aionex-tunnel-runtime.key' not in t
def test_tracked_mcp2_source_prefers_bootstrap_with_legacy_fallback():
 t=(ROOT/'ops/mcp2/server.py').read_text();assert 'BOOTSTRAP_TUNNEL_RUNTIME_KEY' in t and 'LEGACY_TUNNEL_RUNTIME_KEY' in t
 assert c()['bootstrap']['tracked_mcp2_source_prefers_bootstrap_with_legacy_fallback_before_cutover'] is True
def test_trendbost_upstream_bootstrap_copy_is_prepared_without_false_source_claim():
 b=c()['bootstrap'];assert b['trendbost_upstream_bootstrap_copy_prepared_for_c6_legacy_retirement'] is True
 t=(ROOT/'scripts/security/fr06c5_bootstrap.py').read_text();assert "trendbost-mcp-upstream.url" in t
def test_bind_private_keys_read_only_and_docker_stopped():
 t=(ROOT/'scripts/security/fr06c5_host_state_bind.py').read_text();assert "Docker must be stopped" in t;assert "',ro' if ro" in t;assert 'sealed_underlay' in t;assert "'ro' in opts" in t
def test_docker_fail_closed_gate():
 t=(ROOT/'deploy/systemd/docker.service.d/34-aionex-fr06c5-host-state-gate.conf').read_text();assert 'Requires=aionex-fr06c5-host-state-bind.service' in t;assert '--require-ready' in t
def test_header_custody_has_no_key_material():
 t=(ROOT/'scripts/security/fr06c5_host_state_header_custody.py').read_text();assert 'recovery_key_stored_in_r2' in t;assert 'active_bundle' not in t and 'recovery_bundle' not in t
def test_provisioning_has_no_state_copy_or_service_restart():
 t=(ROOT/'scripts/security/fr06c5_host_state_vault.py').read_text();assert "production_state_copied':False" in t;assert 'rsync' not in t;assert "systemctl','stop" not in t and "systemctl','restart" not in t
def test_bootstrap_apply_does_not_restart_tunnels():
 t=(ROOT/'scripts/security/fr06c5_bootstrap.py').read_text();assert 'systemctl' not in t;assert "tunnel_services_restarted':False" in t
def test_next_subpart():assert c()['next_subpart'].startswith('FR-06C5D')


def test_bind_uses_findmnt_exact_target_for_file_mounts():
    text=(ROOT/'scripts/security/fr06c5_host_state_bind.py').read_text()
    assert 'def exact_mount' in text
    assert "findmnt','-n','-o','TARGET','--target'" in text
    assert 'os.path.ismount(dst)' not in text


def test_bootstrap_apply_is_exact_main_bound():
    text=(ROOT/'scripts/security/fr06c5_bootstrap.py').read_text()
    assert 'def gitgate' in text and "--merge-sha" in text and "'merge_sha':merge_sha" in text

def test_header_prefix_is_restricted():
    text=(ROOT/'scripts/security/fr06c5_host_state_header_custody.py').read_text()
    assert 'PREFIX=re.compile' in text and "'..' in prefix.split('/')" in text


def test_mcp2_live_install_is_explicit_gate():
    c=json.loads((ROOT/'docs/project/receipts/FR-06C5C1-host-state-provision-bootstrap-contract.json').read_text())
    m=c['bootstrap']['mcp2_live_install']
    assert m['installer']=='ops/mcp2/install.py'
    assert m['canonical_source']=='ops/mcp2/server.py'
    assert m['live_target']=='/opt/AIOS/tools/aionex_phase22c_mcp2.py'
    assert m['required_after_source_merge_before_c5d'] is True
    assert m['restart_performed_by_installer'] is False
    assert m['expected_live_hash_must_equal_canonical_source'] is True


def test_mcp2_bootstrap_probe_cannot_crash_non_root_import():
    text=(ROOT/'ops/mcp2/server.py').read_text()
    assert '_path_exists_without_import_failure' in text
    assert 'except OSError' in text
    assert 'BOOTSTRAP_TUNNEL_RUNTIME_KEY' in text
    assert 'LEGACY_TUNNEL_RUNTIME_KEY' in text
