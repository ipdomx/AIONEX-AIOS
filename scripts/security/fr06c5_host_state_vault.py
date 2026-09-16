#!/usr/bin/env python3
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,secrets,shutil,stat,subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path('/opt/AIOS');IMAGE=Path('/var/lib/aionex/fr06-vaults/host-state-vault.luks2');MAPPER_NAME='aionex-host-state-vault';MAPPER=Path('/dev/mapper')/MAPPER_NAME;MOUNT=Path('/mnt/aionex/fr06-host-state-vault');STATE=Path('/var/lib/aionex/fr06c5-host-state');RUN=Path('/run/aionex-fr06c5-host-state');KEYS=Path('/dev/shm/aionex-fr06c5-host-state-keys');SIZE=32*1024**3;OPTS=('nodev','nosuid','noexec');CONFIRM='PROVISION_FR06C5_EMPTY_HOST_STATE_VAULT';UNLOCK_CONFIRM='UNLOCK_FR06C5_HOST_STATE_VAULT';MAX_TTL=900
class B(RuntimeError):pass
def now():return datetime.now(timezone.utc)
def utc(v=None):return (v or now()).isoformat(timespec='seconds').replace('+00:00','Z')
def run(a,t=300):
 r=subprocess.run(a,capture_output=True,text=True,timeout=t,check=False)
 if r.returncode:raise B(f'{a[0]} failed')
 return r.stdout.strip()
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def digest(v):return hashlib.sha256(canon(v)).hexdigest()
def fsha(p):
 h=hashlib.sha256();fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  with os.fdopen(fd,'rb',closefd=False) as f:
   for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 finally:os.close(fd)
 return h.hexdigest()
def private(p,label,maxb=65536):
 s=os.lstat(p)
 if stat.S_ISLNK(s.st_mode) or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=0 or stat.S_IMODE(s.st_mode)&0o077 or not 1<=s.st_size<=maxb:raise B(f'{label} unsafe')
def bundle(p,purpose):
 p=p.resolve(strict=True);private(p,purpose)
 if p.parent!=KEYS or run(['findmnt','-n','-o','FSTYPE','--target',str(p)])!='tmpfs':raise B('key bundle must be on fixed tmpfs root')
 d=json.loads(p.read_text())
 if set(d)!={'schema_version','purpose','host_state_vault'} or d['schema_version']!=1 or d['purpose']!=purpose:raise B('bundle schema invalid')
 raw=d['host_state_vault']
 if not isinstance(raw,str) or len(raw)!=128:raise B('key length invalid')
 try:key=bytes.fromhex(raw)
 except ValueError as e:raise B('key encoding invalid') from e
 if len(key)!=64:raise B('key size invalid')
 return key,fsha(p)
def gitgate(sha):
 heads=run(['git','-C',str(ROOT),'rev-parse','HEAD','origin/main']).splitlines()
 if heads!=[sha,sha] or run(['git','-C',str(ROOT),'status','--porcelain=v1']):raise B('production source is not clean exact main')
def mount_vault():
 MOUNT.mkdir(parents=True,exist_ok=True)
 if not os.path.ismount(MOUNT):run(['mount','-o',','.join(OPTS),str(MAPPER),str(MOUNT)])
def verify_host():
 if not MAPPER.exists():raise B('host-state mapper missing')
 if run(['blkid','-o','value','-s','TYPE',str(MAPPER)])!='ext4':raise B('host-state filesystem not ext4')
 row=run(['findmnt','-n','-o','SOURCE,FSTYPE,OPTIONS','--target',str(MOUNT)]).split(None,2)
 if len(row)!=3 or os.path.realpath(row[0])!=os.path.realpath(MAPPER) or row[1]!='ext4' or not set(OPTS).issubset(set(row[2].split(','))):raise B('host-state mount drifted')
 for sub in ('operator-state','app-secrets','ssh'):
  p=MOUNT/sub
  if not p.is_dir() or p.is_symlink():raise B('host-state subpath unavailable')
 return {'status':'host-ready','validation':'FR06C5_HOST_STATE_VAULT_READY','mapper':str(MAPPER),'mount_root':str(MOUNT),'subpaths':['operator-state','app-secrets','ssh'],'admission_opened':False}
def status(require=False):
 try:return verify_host()
 except Exception as e:
  if require:raise
  return {'status':'not-ready','validation':'FR06C5_HOST_STATE_VAULT_NOT_READY','reason':str(e)}
def write_exclusive(p,v):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:os.write(fd,json.dumps(v,sort_keys=True,indent=2).encode()+b'\n');os.fsync(fd)
 finally:os.close(fd)
def plan(a):
 if os.geteuid()!=0:raise B('root required')
 gitgate(a.merge_sha)
 if IMAGE.exists() or MAPPER.exists():raise B('host-state vault already exists')
 active,ad=bundle(a.active_bundle,'active');recovery,rd=bundle(a.recovery_bundle,'recovery')
 if active==recovery:raise B('active/recovery keys must differ')
 if shutil.disk_usage('/var/lib/aionex').free<SIZE+16*1024**3:raise B('insufficient free space plus reserve')
 if not 1<=a.ttl_seconds<=MAX_TTL:raise B('ttl invalid')
 t=now();body={'schema_version':1,'subpart':'FR-06C5C1','operation':'provision-empty-host-state-vault','created_at':utc(t),'expires_at':utc(t+timedelta(seconds=a.ttl_seconds)),'nonce':secrets.token_hex(32),'merge_sha':a.merge_sha,'active_bundle_sha256':ad,'recovery_bundle_sha256':rd,'size_bytes':SIZE,'production_state_copy_permitted':False,'service_stop_or_restart_permitted':False,'bind_install_permitted':False};body['plan_id']=digest(body);RUN.mkdir(parents=True,exist_ok=True,mode=0o700);p=RUN/f"plan-{body['plan_id']}.json";write_exclusive(p,body);return {'status':'planned','plan':str(p),'plan_id':body['plan_id'],'confirmation':'PROVISION-'+body['plan_id'][:16],'production_executed':False}
def loadplan(p):
 private(p,'plan',1024*1024);d=json.loads(p.read_text());pid=d.get('plan_id')
 if not isinstance(pid,str) or digest({k:v for k,v in d.items() if k!='plan_id'})!=pid:raise B('plan digest invalid')
 if now()>datetime.fromisoformat(d['expires_at'].replace('Z','+00:00')):raise B('plan expired')
 return d
def apply(a):
 p=loadplan(a.plan.resolve())
 if a.confirmation!='PROVISION-'+p['plan_id'][:16] or a.confirm_production!=CONFIRM:raise B('confirmation invalid')
 gitgate(a.merge_sha);ak,ad=bundle(a.active_bundle,'active');rk,rd=bundle(a.recovery_bundle,'recovery')
 if p['merge_sha']!=a.merge_sha or p['active_bundle_sha256']!=ad or p['recovery_bundle_sha256']!=rd:raise B('bound input changed')
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700);RUN.mkdir(parents=True,exist_ok=True,mode=0o700);lock=os.open(RUN/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 tmp=KEYS/('apply-'+secrets.token_hex(6));tmp.mkdir(parents=True,mode=0o700);ap=tmp/'active';rp=tmp/'recovery';ap.write_bytes(ak);rp.write_bytes(rk);os.chmod(ap,0o600);os.chmod(rp,0o600);opened=mounted=False
 try:
  IMAGE.parent.mkdir(parents=True,exist_ok=True,mode=0o700);run(['fallocate','-l',str(SIZE),str(IMAGE)],600);os.chmod(IMAGE,0o600)
  run(['cryptsetup','luksFormat','--batch-mode','--type','luks2','--cipher','aes-xts-plain64','--key-size','512','--pbkdf','argon2id','--key-file',str(ap),str(IMAGE)],600);run(['cryptsetup','luksAddKey',str(IMAGE),str(rp),'--key-file',str(ap)],300);run(['cryptsetup','open','--key-file',str(ap),str(IMAGE),MAPPER_NAME],180);opened=True;run(['mkfs.ext4','-q','-L','AIOS06_HOSTSTATE',str(MAPPER)],300);mount_vault();mounted=True
  for sub in ('operator-state','app-secrets','ssh'):(MOUNT/sub).mkdir(mode=0o700);os.chown(MOUNT/sub,0,0);os.chmod(MOUNT/sub,0o700)
  header=RUN/'host-state-vault.header';run(['cryptsetup','luksHeaderBackup',str(IMAGE),'--header-backup-file',str(header)],120);os.chmod(header,0o400);ready=verify_host();receipt={'schema_version':1,'subpart':'FR-06C5C1','status':'empty_host_state_vault_provisioned_admission_closed','completed_at':utc(),'merge_sha':a.merge_sha,'size_bytes':SIZE,'mapper':str(MAPPER),'mount_root':str(MOUNT),'subpaths':['operator-state','app-secrets','ssh'],'active_bundle_sha256':ad,'recovery_bundle_sha256':rd,'header_staging_path':str(header),'header_sha256':fsha(header),'production_state_copied':False,'services_stopped_or_restarted':False,'binds_installed':False,'admission_opened':False,'cloudflare_changed':False,'ready_validation':ready['validation']};write_exclusive(STATE/'provision-receipt.json',receipt);return {'status':receipt['status'],'receipt':str(STATE/'provision-receipt.json'),'production_state_copied':False}
 except Exception:
  if mounted:subprocess.run(['umount',str(MOUNT)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  if opened:subprocess.run(['cryptsetup','close',MAPPER_NAME],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  if IMAGE.exists():IMAGE.unlink()
  raise
 finally:
  for x in (ap,rp):
   try:x.unlink()
   except OSError:pass
  try:tmp.rmdir()
  except OSError:pass
  fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
def prove(a):
 private(STATE/'provision-receipt.json','receipt',1024*1024);r=json.loads((STATE/'provision-receipt.json').read_text());ak,ad=bundle(a.active_bundle,'active');rk,rd=bundle(a.recovery_bundle,'recovery')
 if ad!=r['active_bundle_sha256'] or rd!=r['recovery_bundle_sha256']:raise B('custody changed')
 if os.path.ismount(MOUNT):run(['umount',str(MOUNT)])
 if MAPPER.exists():run(['cryptsetup','close',MAPPER_NAME])
 tmp=KEYS/('prove-'+secrets.token_hex(6));tmp.mkdir(parents=True,mode=0o700);ap=tmp/'active';rp=tmp/'recovery';ap.write_bytes(ak);rp.write_bytes(rk);os.chmod(ap,0o600);os.chmod(rp,0o600)
 try:
  run(['cryptsetup','open','--key-file',str(rp),str(IMAGE),MAPPER_NAME]);mount_vault();verify_host();run(['umount',str(MOUNT)]);run(['cryptsetup','close',MAPPER_NAME]);run(['cryptsetup','open','--key-file',str(ap),str(IMAGE),MAPPER_NAME]);mount_vault();verify_host();out={'schema_version':1,'subpart':'FR-06C5C1','status':'independent_host_state_recovery_key_proved','observed_at':utc(),'recovery_open_passed':True,'active_reopen_passed':True,'key_material_persisted':False,'admission_opened':False};write_exclusive(STATE/'recovery-proof.json',out);return out
 finally:
  for x in (ap,rp):
   try:x.unlink()
   except OSError:pass
  try:tmp.rmdir()
  except OSError:pass
def unlock(a):
 if a.confirmation!=UNLOCK_CONFIRM:raise B('unlock confirmation invalid')
 private(STATE/'provision-receipt.json','receipt',1024*1024);r=json.loads((STATE/'provision-receipt.json').read_text());ak,ad=bundle(a.active_bundle,'active')
 if ad!=r['active_bundle_sha256']:raise B('active custody changed')
 tmp=KEYS/('unlock-'+secrets.token_hex(6));tmp.mkdir(parents=True,mode=0o700);p=tmp/'active';p.write_bytes(ak);os.chmod(p,0o600)
 try:
  if MAPPER.exists() or os.path.ismount(MOUNT):raise B('vault already open')
  run(['cryptsetup','open','--key-file',str(p),str(IMAGE),MAPPER_NAME]);mount_vault();return verify_host()
 finally:
  try:p.unlink();tmp.rmdir()
  except OSError:pass
def wipe():
 removed=[]
 for n in ('active-bundle.json','recovery-bundle.json'):
  p=KEYS/n
  if p.exists():p.unlink();removed.append(n)
 return {'status':'tmpfs_inputs_removed','removed':removed,'key_material_persisted':False}
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);q=s.add_parser('status');q.add_argument('--require-host-ready',action='store_true')
 for n in ('plan','apply'):
  q=s.add_parser(n);q.add_argument('--merge-sha',required=True);q.add_argument('--active-bundle',type=Path,required=True);q.add_argument('--recovery-bundle',type=Path,required=True)
  if n=='plan':q.add_argument('--ttl-seconds',type=int,default=600)
  else:q.add_argument('--plan',type=Path,required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='')
 q=s.add_parser('prove-recovery');q.add_argument('--active-bundle',type=Path,required=True);q.add_argument('--recovery-bundle',type=Path,required=True)
 q=s.add_parser('unlock');q.add_argument('--active-bundle',type=Path,required=True);q.add_argument('--confirmation',required=True);s.add_parser('wipe-inputs');a=p.parse_args()
 try:o=status(a.require_host_ready) if a.cmd=='status' else plan(a) if a.cmd=='plan' else apply(a) if a.cmd=='apply' else prove(a) if a.cmd=='prove-recovery' else unlock(a) if a.cmd=='unlock' else wipe();print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
if __name__=='__main__':raise SystemExit(main())
