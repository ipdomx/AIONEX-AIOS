from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C5D-host-state-live-cutover-contract.json').read_text())
def test_source_merge_inert():
 s=c()['scope_boundary'];assert s['source_merge_executes_cutover'] is False;assert s['source_merge_reads_secret_contents'] is False;assert s['source_merge_stops_docker'] is False
def test_cutover_seals_legacy_before_final_delta():
 x=c()['cutover'];assert x['seal_all_legacy_sources_read_only_before_final_delta'] and x['exact_metadata_and_content_manifest_match']
def test_bootstrap_and_exact_topology_required():
 x=c()['cutover'];assert x['bootstrap_key_and_shared_upstream_must_match_sealed_source'] and x['capture_exact_36_container_topology']
def test_post_start_blind_rollback_forbidden():
 r=c()['rollback'];assert r['post_candidate_start_blind_rollback_allowed'] is False;assert r['reverse_copy_to_legacy_allowed'] is False
def test_executor_has_prestart_only_rollback_path():
 t=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text();assert 'not candidate_start_attempted' in t;assert 'blind rollback is prohibited' in t;assert 'post_start_failure_requires_reconciliation' in t
def test_executor_uses_rsync_numeric_ids_and_delete():
 t=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text();assert "'--numeric-ids'" in t and "'--delete'" in t
def test_executor_keeps_containerd_running():
 t=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text();assert "systemctl','stop','docker.service','docker.socket" in t;assert "systemctl','stop','containerd.service" not in t
def test_acceptance_covers_both_encrypted_binds():
 a=c()['acceptance'];assert 'FR06C5_HOST_STATE_BIND_READY' in a;assert 'FR06C4_RUNTIME_BIND_READY remains true' in a
def test_next_subpart():assert c()['next_subpart'].startswith('FR-06C5E')


def test_file_seals_use_findmnt_exact_target():
    text=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text()
    assert 'def exact_mount' in text
    assert "findmnt','-n','-o','TARGET','--target'" in text
    assert 'os.path.ismount(src)' not in text


def test_restart_policies_are_quiesced_to_prevent_daemon_autostart():
    text=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text()
    assert 'def quiesce_restart_policies' in text and "docker','update','--restart=no" in text
    assert 'def restore_restart_policies' in text
    c0=c()['cutover']; assert c0['capture_and_quiesce_all_restart_policies_before_docker_stop'] is True

def test_divergence_boundary_precedes_explicit_start_batch():
    text=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text()
    apply=text[text.index('def apply(a):'):text.index('def main():')]
    marker="candidate_start_attempted=True;update_attempt(attempt,phase='candidate_start_attempted',candidate_start_attempted=True)"
    start="run(['systemctl','start','docker.socket','docker.service'],180)"
    assert marker in apply and start in apply and apply.index(marker)<apply.index(start)
    assert c()['rollback']['post_candidate_start_blind_rollback_allowed'] is False


def test_nested_mounts_are_rejected_before_precopy():
    text=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text()
    assert 'def reject_nested_mounts' in text
    assert text.index('reject_nested_mounts()') < text.index('precopy()')
    assert 'unexpected mount under host-state source' in text


def test_hidden_underlay_fd_gate_is_fail_closed():
    code=(ROOT/'scripts/security/fr06c5_host_state_cutover.py').read_text()
    assert 'def hidden_underlay_fds()' in code
    assert 'require_zero_hidden_underlay_fds()' in code
    assert "'hidden_underlay_fd_count':hidden_fd_count" in code
    c=json.loads((ROOT/'docs/project/receipts/FR-06C5D-host-state-live-cutover-contract.json').read_text())
    assert c['cutover']['require_zero_hidden_underlay_fds_before_bind'] is True
