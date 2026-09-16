from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C4C3A-candidate-runtime-reconstruction-contract.json').read_text())
def test_scope_is_candidate_only():
 x=c();assert x['subpart']=='FR-06C4C3A';assert x['executor']['production_cutover_capability'] is False;assert x['executor']['live_docker_stop_capability'] is False;assert x['executor']['historical_runtime_copy_capability'] is False
def test_daemons_are_isolated_and_no_app_containers():
 d=c()['candidate_daemons'];assert d['shares_live_socket_or_state'] is False;assert d['application_containers_permitted'] is False;assert d['network_bridge_created'] is False;assert d['iptables_mutation_permitted'] is False
def test_authority_counts_fixed():
 a=c()['authorities'];assert a['count']==17 and a['rebuild_from_exact_source']==10 and a['pull_by_digest']==7;assert a['byte_identical_rebuild_claimed'] is False
def test_executor_has_no_historical_copy_and_no_live_stop():
 t=(ROOT/'scripts/security/fr06c4_candidate_runtime.py').read_text();assert 'rsync' not in t;assert "systemctl','stop" not in t;assert "historical_runtime_copy_performed':False" in t
def test_candidate_dockerd_has_no_bridge_or_iptables():
 t=(ROOT/'scripts/security/fr06c4_candidate_runtime.py').read_text();assert '--bridge=none' in t and '--iptables=false' in t and '--ip-forward=false' in t
def test_build_base_images_are_digest_pinned():
 files=['web-dashboard/backend/Dockerfile','web-dashboard/backend/Dockerfile.security-tools','web-dashboard/docker/postgres.Dockerfile','web-dashboard/docker/nginx.Dockerfile','web-dashboard/frontend/Dockerfile','vip-frontend/Dockerfile']
 for f in files:
  for line in (ROOT/f).read_text().splitlines():
   if not line.startswith('FROM '):continue
   source=line.split()[1]
   if source in {'builder','runtime','base'}:continue
   assert '@sha256:' in source, (f,line)
def test_capacity_reserve_is_16gib():
 x=c()['capacity'];assert x['vault_bytes']-x['maximum_candidate_used_bytes']>=16*1024**3
def test_external_refs_are_exact_digests():
 t=(ROOT/'scripts/security/fr06c4_candidate_runtime.py').read_text();refs=re.findall(r"'([^']+@sha256:[0-9a-f]{64})'",t);assert len(set(refs))>=7
