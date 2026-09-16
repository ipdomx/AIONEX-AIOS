#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
import yaml

def die(msg:str)->None: raise SystemExit(msg)
def run(args:list[str])->str:
    r=subprocess.run(args,capture_output=True,text=True,check=False,timeout=60)
    if r.returncode: die(f'{args[0]} failed')
    return r.stdout.strip()
def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]); ap.add_argument('--live',action='store_true'); a=ap.parse_args(); root=a.root.resolve()
    c=json.loads((root/'docs/project/receipts/FR-06C4A-container-runtime-inventory.json').read_text())
    if c.get('subpart')!='FR-06C4A' or c.get('production_changed') is not False: die('C4A contract invalid')
    rt=c['runtime']; au=c['authority']; cv=c['candidate_vault']; sb=c['scope_boundary']
    if rt['running_container_count']!=36 or rt['unique_running_image_count']!=17: die('observed topology contract drifted')
    if au['active_runtime_authority_count']!=17 or au['all_running_images_have_reconstruction_authority'] is not True: die('image authority incomplete')
    if len(au['rebuild_from_exact_protected_source'])!=10 or len(au['pull_by_digest'])!=7: die('authority classes incomplete')
    if any('@sha256:' not in x for x in au['pull_by_digest']): die('external runtime authority is not digest-pinned')
    if cv['preallocated_bytes']!=64*1024**3 or cv['filesystem']!='ext4': die('runtime vault contract drifted')
    if rt['containerd_root_payload_bytes'] <= cv['preallocated_bytes']: die('historical-copy rejection no longer evidenced')
    if sb['historical_runtime_copy_allowed'] is not False or sb['production_runtime_cutover_authorized_by_c4a'] is not False: die('C4A scope weakened')
    compose=yaml.safe_load((root/'web-dashboard/docker-compose.production.yml').read_text())
    text=(root/'web-dashboard/docker-compose.production.yml').read_text()
    for image in au['pull_by_digest']:
        if image not in text: die(f'pinned authority missing from compose: {image}')
    for image,spec in au['rebuild_from_exact_protected_source'].items():
        p=root/spec['context']; dockerfile=p/spec['dockerfile']
        if not p.exists() or not dockerfile.is_file(): die(f'rebuild authority missing: {image}')
    result={'schema_version':1,'subpart':'FR-06C4A','validation':'FR06C4A_RUNTIME_INVENTORY_PASS','production_changed':False,'running_container_count_contract':36,'unique_image_authority_count':17,'historical_containerd_copy_allowed':False}
    if a.live:
        info=json.loads(run(['docker','info','--format','{{json .}}']))
        if info.get('DockerRootDir')!='/var/lib/docker' or info.get('Driver')!='overlayfs': die('live Docker root/driver drifted')
        ids=run(['docker','ps','-q']).splitlines()
        active=set()
        for cid in ids:
            d=json.loads(run(['docker','inspect',cid]))[0]; active.add((d['Config']['Image'],d['Image']))
        if len(ids)!=36 or len(active)!=17: die('live runtime topology drifted')
        result['live_topology_match']=True
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__': main()
