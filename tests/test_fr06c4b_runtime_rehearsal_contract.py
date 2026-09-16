import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def c(): return json.loads((ROOT/'docs/project/receipts/FR-06C4B-isolated-runtime-rehearsal-contract.json').read_text())
def test_isolated_lab_never_uses_production_runtime_roots():
    l=c()['lab']; assert l['uses_production_docker_root'] is False; assert l['uses_production_containerd_root'] is False; assert l['copies_historical_runtime_layers'] is False; assert l['synthetic_runtime_only'] is True
def test_lab_requires_luks2_recovery_and_wrong_key():
    l=c()['lab']; assert l['vault_format']=='LUKS2/ext4'; assert l['wrong_key_must_fail'] is True; assert l['independent_recovery_key_required'] is True; assert l['closed_plaintext_marker_must_be_absent'] is True
def test_production_boundary_is_inert():
    b=c()['production_boundary']; assert all(v is False for v in b.values())
def test_lab_script_has_no_production_runtime_paths_as_copy_sources():
    t=(ROOT/'scripts/security/fr06c4b_runtime_isolated_lab.py').read_text(); assert '/var/lib/docker' not in t; assert '/var/lib/containerd' not in t; assert 'rsync' not in t
