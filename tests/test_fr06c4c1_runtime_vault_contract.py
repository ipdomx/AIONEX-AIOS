import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C4C1-runtime-vault-provisioning-contract.json').read_text())
def test_c4c1_provisioning_is_inert_by_source_merge():
 b=c()['production_boundary']; assert b['source_merge_provisions_vault'] is False; assert b['source_merge_stops_docker'] is False; assert b['source_merge_stops_containerd'] is False; assert b['historical_runtime_copy_capability'] is False
def test_runtime_vault_size_paths_and_keys():
 v=c()['vault']; assert v['preallocated_bytes']==64*1024**3; assert v['subpaths']==['docker','containerd']; assert v['mount_options']==['nodev','nosuid']; assert v['keyslots']==2; assert v['tmpfs_key_inputs_only'] is True
def test_bind_mounts_cover_standard_runtime_roots_and_keep_underlay():
 b=c()['bind_mount_strategy']; assert b['legacy_underlay_retained'] is True; assert b['requires_vault_host_ready_before_first_bind'] is True; assert b['requires_both_daemons_stopped'] is True; assert b['atomic_failure_cleanup'] is True
 t=(ROOT/b['bind_executor']).read_text(); assert "Path('/var/lib/docker')" in t; assert "Path('/var/lib/containerd')" in t; assert 'runtime vault not host-ready' in t
def test_daemon_gates_require_runtime_mounts():
 b=c()['boot_fail_closed']; assert b['missing_mapper_or_mount'].startswith('containerd and Docker fail')
 assert 'fr06c4_runtime_bind.py status --require-ready' in (ROOT/b['containerd_dropin']).read_text(); assert 'fr06c4_runtime_bind.py status --require-ready' in (ROOT/b['docker_dropin']).read_text()
def test_provisioner_cannot_copy_or_stop_runtime():
 t=(ROOT/'scripts/security/fr06c4_runtime_vault.py').read_text(); assert 'rsync' not in t; assert "'docker','stop'" not in t; assert "'containerd','stop'" not in t; assert 'systemctl\',\'stop' not in t
def test_unlock_requires_both_daemons_stopped():
 t=(ROOT/'scripts/security/fr06c4_runtime_vault.py').read_text(); assert 'Docker and containerd must be stopped before unlock' in t


def test_bind_executor_never_binds_before_vault_gate_and_cleans_partial_failure():
    b=c()['bind_mount_strategy']; t=(ROOT/b['bind_executor']).read_text(); assert 'ready()' in t; assert "mount','--bind" in t; assert 'for dst in reversed(mounted)' in t; assert 'Docker and containerd must be stopped before runtime bind' in t


def test_runtime_header_custody_is_single_new_r2_object_with_full_readback():
    h=c()['header_custody']; assert h['object_count']==1; assert h['new_object_required'] is True; assert h['full_sha256_readback_required'] is True; assert h['recovery_key_stored_in_r2'] is False
    t=(ROOT/h['script']).read_text(); assert 'IfNoneMatch' in t; assert 'full readback failed' in t; assert 'fr06c4/luks2-headers' in t
