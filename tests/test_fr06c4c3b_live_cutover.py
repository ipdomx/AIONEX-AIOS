from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C4C3B-live-runtime-cutover-contract.json').read_text())
def test_cutover_scope_and_topology():
 x=c();assert x['subpart']=='FR-06C4C3B';assert x['topology']['expected_running_containers']==36;assert x['topology']['project_worker_scale']==4;assert x['scope_boundary']['source_merge_executes_cutover'] is False
def test_never_copies_runtime_layers():
 x=c();assert x['cutover']['historical_runtime_copy'] is False;assert x['rollback']['candidate_layers_reverse_copied_to_legacy'] is False;t=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text();assert 'rsync' not in t
def test_exact_five_external_vaults():
 t=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text();
 for n in ('aionex-fr06-asset-vault','aionex-fr06-project-execution-vault','aionex-fr06-database-vault','aionex-fr06-local-backup-vault','aionex-fr06-operations-vault'):assert n in t
 assert c()['cutover']['external_encrypted_volume_count']==5
def test_guarded_stop_and_bind_order_present():
 t=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text();assert "systemctl','stop','docker.service','docker.socket" in t;assert "systemctl','stop','containerd.service" in t;assert 'aionex-fr06c4-runtime-bind.service' in t
def test_candidate_start_is_no_build_and_model_rebuilt():
 t=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text();assert "'--no-build'" in t;assert 'ollama-model-bootstrap' in t;assert 'gemma3:4b' in t
def test_rollback_removes_c4_gates_before_legacy_start():
 t=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text();i=t.index('def rollback_internal');s=t[i:i+2600];assert s.index('remove_gates()')<s.index("systemctl','start','containerd.service")
def test_compose_set_has_all_encryption_overlays():
 t=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text();
 for n in ('docker-compose.fr06-assets.yml','docker-compose.fr06-database.yml','docker-compose.fr06-backup.yml','docker-compose.fr06-operations.yml','docker-compose.fr06-operations-admission.yml'):assert n in t
