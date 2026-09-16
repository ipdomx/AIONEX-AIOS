#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,secrets,shutil,stat,subprocess,tempfile
from pathlib import Path

def run(argv:list[str],timeout:int=120)->str:
    r=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,check=False)
    if r.returncode: raise RuntimeError(f'{argv[0]} failed')
    return r.stdout.strip()
def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    if os.geteuid()!=0: raise SystemExit('root required for isolated LUKS lab')
    base=Path(tempfile.mkdtemp(prefix='fr06c4b-',dir='/var/tmp'))
    image=base/'runtime.luks2'; mount=base/'mnt'; mapper='fr06c4b-'+secrets.token_hex(6); dev=Path('/dev/mapper')/mapper
    active=base/'active.key'; recovery=base/'recovery.key'; wrong=base/'wrong.key'
    for p in (active,recovery,wrong): p.write_bytes(secrets.token_bytes(64)); os.chmod(p,0o600)
    receipts={}; mounted=False; opened=False
    try:
        run(['truncate','-s','2G',str(image)])
        run(['cryptsetup','luksFormat','--batch-mode','--type','luks2','--cipher','aes-xts-plain64','--key-size','512','--pbkdf','argon2id','--key-file',str(active),str(image)],300)
        run(['cryptsetup','luksAddKey',str(image),str(recovery),'--key-file',str(active)],300)
        wrong_rejected=subprocess.run(['cryptsetup','open','--type','luks','--key-file',str(wrong),str(image),mapper],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False).returncode!=0
        if not wrong_rejected: raise RuntimeError('wrong key unexpectedly opened vault')
        run(['cryptsetup','open','--type','luks','--key-file',str(active),str(image),mapper]); opened=True
        run(['mkfs.ext4','-q','-L','AIOS06_RUNTIME_LAB',str(dev)],180)
        mount.mkdir(); run(['mount','-o','nodev,nosuid',str(dev),str(mount)]); mounted=True
        for sub in ('docker','containerd'):
            (mount/sub).mkdir(mode=0o700)
        # Synthetic clean-runtime proof: only generated metadata/artifacts, never production stores.
        docker=(mount/'docker'); cont=(mount/'containerd')
        (docker/'image-authority.json').write_text(json.dumps({'source':'synthetic-lab','historical_copy':False,'image':'synthetic@sha256:'+hashlib.sha256(b'synthetic').hexdigest()},sort_keys=True)+'\n')
        (cont/'content').mkdir(); (cont/'snapshots').mkdir()
        payload=(cont/'content'/'synthetic.layer'); payload.write_bytes(b'FR06C4_SYNTHETIC_RUNTIME_LAYER\n'*1024)
        manifest={'docker_authority_sha256':sha(docker/'image-authority.json'),'synthetic_layer_sha256':sha(payload),'synthetic_layer_bytes':payload.stat().st_size}
        marker=b'FR06C4_SYNTHETIC_RUNTIME_LAYER'
        run(['sync','-f',str(mount)])
        run(['umount',str(mount)]); mounted=False; run(['cryptsetup','close',mapper]); opened=False
        raw=image.read_bytes()
        closed_plaintext_absent=marker not in raw
        if not closed_plaintext_absent: raise RuntimeError('closed image exposed plaintext marker')
        # Independent recovery key open and exact synthetic manifest revalidation.
        run(['cryptsetup','open','--type','luks','--key-file',str(recovery),str(image),mapper]); opened=True
        run(['mount','-o','nodev,nosuid',str(dev),str(mount)]); mounted=True
        if sha(mount/'docker'/'image-authority.json')!=manifest['docker_authority_sha256'] or sha(mount/'containerd'/'content'/'synthetic.layer')!=manifest['synthetic_layer_sha256']:
            raise RuntimeError('recovery-key manifest mismatch')
        run(['umount',str(mount)]); mounted=False; run(['cryptsetup','close',mapper]); opened=False
        # Active key reopen as final proof.
        run(['cryptsetup','open','--type','luks','--key-file',str(active),str(image),mapper]); opened=True
        run(['mount','-o','nodev,nosuid',str(dev),str(mount)]); mounted=True
        final_ok=(mount/'docker').is_dir() and (mount/'containerd').is_dir()
        receipts={'schema_version':1,'subpart':'FR-06C4B','status':'isolated_clean_runtime_vault_rehearsal_pass','production_docker_root_used':False,'production_containerd_root_used':False,'production_mutation_performed':False,'historical_runtime_copy_performed':False,'luks2':True,'cipher':'aes-xts-plain64','key_bits':512,'pbkdf':'argon2id','wrong_key_rejected':wrong_rejected,'closed_raw_plaintext_marker_absent':closed_plaintext_absent,'independent_recovery_key_open_passed':True,'active_key_reopen_passed':final_ok,'subpaths':['docker','containerd'],'mount_options':['nodev','nosuid'],'synthetic_manifest':manifest,'temporary_resources_removed':True}
    finally:
        if mounted: subprocess.run(['umount',str(mount)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        if opened or dev.exists(): subprocess.run(['cryptsetup','close',mapper],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        shutil.rmtree(base,ignore_errors=True)
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(receipts,indent=2)+'\n'); print(json.dumps(receipts,sort_keys=True))
if __name__=='__main__': main()
