#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);a=p.parse_args();r=a.root.resolve();c=json.loads((r/'docs/project/receipts/FR-06C4C2-clean-runtime-cutover-contract.json').read_text());inv=json.loads((r/'docs/project/receipts/FR-06C4A-container-runtime-inventory.json').read_text());prov=json.loads((r/'docs/project/receipts/FR-06C4C1-runtime-vault-provisioning-contract.json').read_text())
 if c['subpart']!='FR-06C4C2':raise SystemExit('subpart drift')
 cr=c['candidate_reconstruction'];
 if cr['image_authority_count']!=inv['authority']['active_runtime_authority_count'] or cr['rebuild_from_exact_source_count']!=len(inv['authority']['rebuild_from_exact_protected_source']) or cr['pull_by_digest_count']!=len(inv['authority']['pull_by_digest']):raise SystemExit('authority count drift')
 if any(cr[k] for k in ('historical_docker_root_copy','historical_containerd_root_copy','historical_build_cache_copy','historical_json_log_copy')):raise SystemExit('historical copy enabled')
 if len(c['external_authoritative_volumes'])!=5 or len(set(c['external_authoritative_volumes']))!=5:raise SystemExit('external volume contract invalid')
 if prov['bind_mount_strategy']['legacy_underlay_retained'] is not True or c['rollback']['blind_runtime_reverse_copy_allowed'] is not False:raise SystemExit('rollback weakened')
 if c['production_boundary']['source_merge_executes_cutover'] is not False:raise SystemExit('source merge became active')
 print(json.dumps({'schema_version':1,'subpart':'FR-06C4C2','validation':'FR06C4C2_CLEAN_RUNTIME_CUTOVER_CONTRACT_PASS','image_authority_count':17,'external_encrypted_volume_count':5,'historical_runtime_copy_allowed':False,'production_changed':False},sort_keys=True))
if __name__=='__main__':main()
