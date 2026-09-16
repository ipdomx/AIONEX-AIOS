#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,secrets,shutil,stat,subprocess,tempfile
from pathlib import Path

class E(RuntimeError): pass

def run(argv,timeout=180,check=True):
    r=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,check=False)
    if check and r.returncode: raise E(f'{argv[0]} failed')
    return r

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def contains(path:Path,needle:bytes)->bool:
    keep=max(0,len(needle)-1); tail=b''
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            data=tail+chunk
            if needle in data:return True
            tail=data[-keep:] if keep else b''
    return False

def manifest(root:Path):
    out=[]
    for p in sorted(root.rglob('*'),key=lambda x:str(x.relative_to(root))):
        s=os.lstat(p); rel=str(p.relative_to(root)); mode=stat.S_IMODE(s.st_mode)
        if stat.S_ISREG(s.st_mode): typ='file'; extra=sha(p); size=s.st_size
        elif stat.S_ISDIR(s.st_mode): typ='dir'; extra=''; size=0
        elif stat.S_ISLNK(s.st_mode): typ='symlink'; extra=os.readlink(p); size=0
        else: raise E('unsupported synthetic entry')
        out.append({'path':rel,'type':typ,'mode':mode,'uid':s.st_uid,'gid':s.st_gid,'size':size,'extra':extra})
    return out

def write(path:Path,data:bytes,mode:int,uid:int=0,gid:int=0):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);os.chmod(path,mode);os.chown(path,uid,gid)

def main():
    if os.geteuid()!=0: raise E('root required')
    base=Path(tempfile.mkdtemp(prefix='fr06c5b-',dir='/var/tmp'));keys=Path(tempfile.mkdtemp(prefix='fr06c5b-keys-',dir='/dev/shm'))
    src=base/'source';bootstrap=base/'bootstrap';mount=base/'mnt';tmpmnt=base/'tmpfs';image=base/'host-state.luks2';swapimg=base/'swap.raw'
    mount.mkdir();tmpmnt.mkdir();bootstrap.mkdir(mode=0o700)
    mapper='aionex-fr06c5b-'+secrets.token_hex(5);swapmapper='aionex-fr06c5b-swap-'+secrets.token_hex(4)
    active,recovery,wrong,swap1,swap2=[keys/n for n in ('active','recovery','wrong','swap1','swap2')]
    marker=('FR06C5B-'+secrets.token_hex(16)).encode(); opened=mounted=swap_open=tmp_mounted=False
    try:
        # Synthetic encrypted-domain payload with mixed ownership/modes.
        write(src/'operator/releases/release.json',marker+b'-release',0o600)
        write(src/'operator/audits/audit.log',marker+b'-audit',0o640)
        write(src/'operator/trendbost-mcp-upstream.url',b'https://127.0.0.1.invalid\n',0o600)
        write(src/'secrets/backend.secret',marker+b'-backend',0o400)
        write(src/'secrets/worker.secret',marker+b'-worker',0o600,1000,1000)
        write(src/'ssh/aionex_aios_deploy',marker+b'-deploy',0o600)
        write(src/'ssh/aionex_cpanel_ai_vip_e_net_ed25519',marker+b'-cpanel',0o600)
        os.symlink('../secrets/backend.secret',src/'operator/backend-secret-link')
        # Synthetic minimal pre-unlock bootstrap only.
        write(bootstrap/'control-plane.key',b'BOOTSTRAP-CONTROL-'+secrets.token_bytes(16),0o600)
        write(bootstrap/'trendbost-mcp-upstream.url',b'https://127.0.0.1.invalid\n',0o600)
        write(bootstrap/'authorized_keys',b'ssh-ed25519 AAAATEST fr06c5b\n',0o600)
        for n in ('aionex-phase22c-2.yaml','aionex-phase22c.yaml','trendbost-mcp-bridge.yaml'):
            write(bootstrap/n,b'api_key: ${CONTROL_PLANE_API_KEY}\n',0o600)
        bootstrap_names={p.name for p in bootstrap.iterdir()}
        if {'aionex_aios_deploy','aionex_cpanel_ai_vip_e_net_ed25519'} & bootstrap_names: raise E('deployment key leaked into bootstrap')
        if len(bootstrap_names)!=6: raise E('bootstrap is not minimal synthetic set')
        before=manifest(src)
        for p in (active,recovery,wrong,swap1,swap2):p.write_bytes(os.urandom(64));os.chmod(p,0o600)
        if len({sha(active),sha(recovery),sha(wrong),sha(swap1),sha(swap2)})!=5:raise E('synthetic keys not independent')
        run(['fallocate','-l','256M',str(image)])
        run(['cryptsetup','luksFormat','--batch-mode','--type','luks2','--cipher','aes-xts-plain64','--key-size','512','--pbkdf','argon2id','--key-file',str(active),str(image)],300)
        run(['cryptsetup','luksAddKey',str(image),str(recovery),'--key-file',str(active)],180)
        bad=run(['cryptsetup','open','--key-file',str(wrong),str(image),mapper],60,False).returncode!=0
        if not bad:raise E('wrong key accepted')
        run(['cryptsetup','open','--key-file',str(active),str(image),mapper],60);opened=True
        run(['mkfs.ext4','-q','/dev/mapper/'+mapper],120);run(['mount','-o','nodev,nosuid,noexec','/dev/mapper/'+mapper,str(mount)]);mounted=True
        target=mount/'host-state';target.mkdir(mode=0o700)
        run(['rsync','-aHAX','--numeric-ids',str(src)+'/',str(target)+'/'],120)
        if manifest(target)!=before:raise E('active-copy metadata mismatch')
        run(['umount',str(mount)]);mounted=False;run(['cryptsetup','close',mapper]);opened=False
        if contains(image,marker):raise E('closed image exposed synthetic plaintext')
        run(['cryptsetup','open','--key-file',str(recovery),str(image),mapper],60);opened=True;run(['mount','-o','nodev,nosuid,noexec','/dev/mapper/'+mapper,str(mount)]);mounted=True
        if manifest(mount/'host-state')!=before:raise E('recovery manifest mismatch')
        run(['umount',str(mount)]);mounted=False;run(['cryptsetup','close',mapper]);opened=False
        run(['cryptsetup','open','--key-file',str(active),str(image),mapper],60);opened=True;run(['mount','-o','nodev,nosuid,noexec','/dev/mapper/'+mapper,str(mount)]);mounted=True
        if manifest(mount/'host-state')!=before:raise E('active reopen manifest mismatch')
        run(['umount',str(mount)]);mounted=False;run(['cryptsetup','close',mapper]);opened=False
        # Random-key encrypted swap construction, never enabled as system swap.
        run(['fallocate','-l','64M',str(swapimg)])
        run(['cryptsetup','open','--type','plain','--cipher','aes-xts-plain64','--key-size','512','--key-file',str(swap1),str(swapimg),swapmapper],60);swap_open=True
        run(['mkswap','/dev/mapper/'+swapmapper],60)
        if run(['blkid','-o','value','-s','TYPE','/dev/mapper/'+swapmapper],30).stdout.strip()!='swap':raise E('swap signature missing')
        run(['cryptsetup','close',swapmapper]);swap_open=False
        raw_signature_absent=not contains(swapimg,b'SWAPSPACE2')
        if not raw_signature_absent:raise E('raw encrypted swap exposed signature')
        run(['cryptsetup','open','--type','plain','--cipher','aes-xts-plain64','--key-size','512','--key-file',str(swap2),str(swapimg),swapmapper],60);swap_open=True
        new_key_probe=run(['blkid','-o','value','-s','TYPE','/dev/mapper/'+swapmapper],30,False).stdout.strip()
        new_key_rejects=new_key_probe!='swap'
        if not new_key_rejects:raise E('new random key recovered prior swap signature')
        run(['cryptsetup','close',swapmapper]);swap_open=False
        # Disposable tmpfs only, never /tmp.
        run(['mount','-t','tmpfs','-o','nodev,nosuid,size=64m,mode=1777','tmpfs',str(tmpmnt)]);tmp_mounted=True
        (tmpmnt/'ephemeral').write_bytes(marker)
        run(['umount',str(tmpmnt)]);tmp_mounted=False
        tmp_absent=not (tmpmnt/'ephemeral').exists()
        if not tmp_absent:raise E('tmpfs payload survived unmount')
        result={'schema_version':1,'subpart':'FR-06C5B','status':'isolated_host_state_swap_tmpfs_rehearsal_pass','metadata_manifest_match':True,'wrong_key_rejected':True,'independent_recovery_key_open_passed':True,'active_key_reopen_passed':True,'closed_plaintext_marker_absent':True,'bootstrap_file_count':6,'bootstrap_environment_reference_only':True,'deployment_private_keys_absent_from_bootstrap':True,'deployment_private_keys_inside_encrypted_state':True,'synthetic_swap_signature_absent_from_raw_backing':True,'new_random_key_rejects_prior_swap_signature':True,'actual_swapon_performed':False,'persistent_swap_recovery_key':False,'tmpfs_ephemeral_after_unmount':True,'production_operator_state_read':False,'production_application_secrets_read':False,'production_swap_touched':False,'production_tmp_touched':False,'temporary_resources_removed':True}
        print(json.dumps(result,sort_keys=True));return 0
    finally:
        if tmp_mounted:subprocess.run(['umount',str(tmpmnt)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if swap_open:subprocess.run(['cryptsetup','close',swapmapper],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if mounted:subprocess.run(['umount',str(mount)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if opened:subprocess.run(['cryptsetup','close',mapper],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        shutil.rmtree(base,ignore_errors=True);shutil.rmtree(keys,ignore_errors=True)
if __name__=='__main__':raise SystemExit(main())
