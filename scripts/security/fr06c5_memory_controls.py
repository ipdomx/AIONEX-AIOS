#!/usr/bin/env python3
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,secrets,shutil,stat,subprocess,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path('/opt/AIOS');STATE=Path('/var/lib/aionex/fr06c5-memory-controls');BACKING=Path('/var/lib/aionex/fr06-vaults/random-swap.backing');LEGACY=Path('/swap.img');MAPPER_NAME='aionex-fr06c5-swap';MAPPER=Path('/dev/mapper')/MAPPER_NAME;KEY=Path('/run/aionex-fr06c5-swap.key');FSTAB=Path('/etc/fstab');FSTAB_BACKUP=STATE/'fstab.before';SWAP_UNIT_SRC=ROOT/'deploy/systemd/aionex-fr06c5-encrypted-swap.service';SWAP_UNIT_DST=Path('/etc/systemd/system/aionex-fr06c5-encrypted-swap.service');TMP_SRC=ROOT/'deploy/systemd/tmp.mount';TMP_DST=Path('/etc/systemd/system/tmp.mount');MAX_TTL=900;MAX_AGE=3600;RESERVE=8*1024**3;SWAP_SIZE=8*1024**3;CONFIRM='FR06C5_PRODUCTION_MEMORY_CONTROLS';ROLLBACK_CONFIRM='FR06C5_PRODUCTION_MEMORY_CONTROLS_ROLLBACK';LEGACY_LINE='/swap.img\tnone\tswap\tsw\t0\t0';DISABLED_LINE='# AIONEX_FR06C5_LEGACY_SWAP_DISABLED /swap.img none swap sw 0 0'
class E(RuntimeError):pass
class B(E):pass
def now():return datetime.now(timezone.utc)
def utc(v=None):return (v or now()).isoformat(timespec='seconds').replace('+00:00','Z')
def run(a,t=120,check=True):
 r=subprocess.run(a,capture_output=True,text=True,timeout=t,check=False)
 if check and r.returncode:raise E(f'{a[0]} failed with exit code {r.returncode}; output withheld')
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
def private(p,label,maxb=16*1024*1024):
 try:s=os.lstat(p)
 except OSError as e:raise B(f'{label} unavailable') from e
 if stat.S_ISLNK(s.st_mode) or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=0 or s.st_mode&0o077 or not 1<=s.st_size<=maxb:raise B(f'{label} unsafe')
def store(p,v):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:os.write(fd,json.dumps(v,sort_keys=True,indent=2).encode()+b'\n');os.fsync(fd)
 finally:os.close(fd)
def jread(p):
 private(p,p.name);v=json.loads(p.read_text())
 if not isinstance(v,dict):raise B('JSON object required')
 return v
def parsez(v,label):
 if not isinstance(v,str) or not v.endswith('Z'):raise B(f'{label} must be UTC Z')
 try:return datetime.fromisoformat(v[:-1]+'+00:00').astimezone(timezone.utc)
 except ValueError as e:raise B(f'{label} invalid') from e
def gitgate(sha):
 heads=run(['git','-C',str(ROOT),'rev-parse','HEAD','origin/main']).splitlines()
 if heads!=[sha,sha] or run(['git','-C',str(ROOT),'status','--porcelain=v1']):raise B('production source is not clean exact accepted main')
def swap_rows():
 rows=[]
 for line in Path('/proc/swaps').read_text().splitlines()[1:]:
  if not line.strip():continue
  c=line.split();rows.append({'name':c[0],'type':c[1],'size_bytes':int(c[2])*1024,'used_bytes':int(c[3])*1024,'priority':int(c[4])})
 return rows
def same_swap_device(name,target):
 """Match swap aliases by block-device identity; unresolved paths block the caller."""
 try:
  expected=os.stat(target)
  if not stat.S_ISBLK(expected.st_mode):raise B('expected swap mapper is not a block device')
  observed=os.stat(name)
 except OSError as e:raise B('swap device identity unavailable') from e
 return stat.S_ISBLK(observed.st_mode) and observed.st_rdev==expected.st_rdev
def mem_available():
 for line in Path('/proc/meminfo').read_text().splitlines():
  if line.startswith('MemAvailable:'):return int(line.split()[1])*1024
 raise B('MemAvailable unavailable')
def exact_mount(p):
 r=subprocess.run(['findmnt','-n','-o','TARGET','--target',str(p)],capture_output=True,text=True,check=False)
 return r.returncode==0 and r.stdout.strip()==str(p)
def tmp_holders():
 hits=[];me=os.getpid()
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit() or int(proc.name)==me:continue
  pid=int(proc.name)
  for label,path in [('cwd',proc/'cwd'),('root',proc/'root')]:
   try:t=os.readlink(path)
   except OSError:continue
   if t=='/tmp' or t.startswith('/tmp/') : hits.append({'pid':pid,'kind':label,'target':t})
  fdroot=proc/'fd'
  try:fds=list(fdroot.iterdir())
  except OSError:continue
  for fd in fds:
   try:t=os.readlink(fd)
   except OSError:continue
   clean=t[:-10] if t.endswith(' (deleted)') else t
   if clean=='/tmp' or clean.startswith('/tmp/'):hits.append({'pid':pid,'kind':'fd','fd':fd.name,'target':t})
 return hits
def host_state_receipt(p):
 d=jread(p)
 if d.get('status')!='encrypted_host_state_started_admission_closed' or d.get('candidate_host_state_authoritative') is not True:return None
 return d
def evidence(p,sha):
 d=jread(p)
 if d.get('schema_version')!=1 or d.get('subpart')!='FR-06C5E' or d.get('environment')!='production' or d.get('production_authorization') is not True:raise B('evidence metadata invalid')
 age=(now()-parsez(d.get('observed_at'),'observed_at')).total_seconds()
 if age < -300 or age > MAX_AGE:raise B('evidence stale/future-dated')
 s=d.get('source') or {}
 if s.get('merge_sha')!=sha or s.get('protected_pr_checks_passed') is not True or s.get('post_merge_main_checks_passed') is not True:raise B('source CI evidence incomplete')
 a=d.get('approvals') or {};start=parsez(a.get('window_starts_at'),'window start');end=parsez(a.get('window_ends_at'),'window end')
 if a.get('owner_authorized') is not True or end<=start or not start<=now()<=end or (end-start).total_seconds()>4*3600:raise B('maintenance window invalid')
 return d
def current_preflight(host_receipt):
 if host_state_receipt(host_receipt) is None:raise B('accepted host-state cutover receipt required')
 rows=swap_rows();legacy=[r for r in rows if r['name']==str(LEGACY)];enc=[r for r in rows if same_swap_device(r['name'],MAPPER)] if MAPPER.exists() else []
 if len(legacy)!=1 or enc:raise B('expected only active legacy swap before activation')
 if not LEGACY.is_file() or exact_mount(Path('/tmp')):raise B('legacy swap or /tmp preflight drifted')
 available=mem_available();used=legacy[0]['used_bytes']
 if available < used+RESERVE:raise B('insufficient available memory for safe swapoff reserve')
 holders=tmp_holders()
 if holders:raise B(f'/tmp hidden-underlay holders present: {len(holders)}')
 return {'legacy_swap':legacy[0],'mem_available_bytes':available,'reserve_bytes':RESERVE,'tmp_hidden_underlay_fd_count':0}
def plan(a):
 if os.geteuid()!=0:raise B('root required')
 gitgate(a.merge_sha);evidence(a.evidence.resolve(),a.merge_sha);private(a.host_state_receipt.resolve(),'host-state receipt');pre=current_preflight(a.host_state_receipt.resolve())
 if not 1<=a.ttl_seconds<=MAX_TTL:raise B('plan TTL invalid')
 n=now();body={'schema_version':1,'subpart':'FR-06C5E','operation':'memory-controls','created_at':utc(n),'expires_at':utc(n+timedelta(seconds=a.ttl_seconds)),'merge_sha':a.merge_sha,'evidence_sha256':fsha(a.evidence.resolve()),'host_state_receipt_sha256':fsha(a.host_state_receipt.resolve()),'preflight':pre,'nonce':secrets.token_hex(32),'cloudflare_change_permitted':False};body['plan_id']=digest(body);p=STATE/'plans'/f"{body['plan_id']}.json";store(p,body);return {'status':'memory_controls_plan_ready','plan_id':body['plan_id'],'plan':str(p),'production_executed':False}
def loadplan(p,e,h):
 d=jread(p);pid=d.get('plan_id')
 if not isinstance(pid,str) or digest({k:v for k,v in d.items() if k!='plan_id'})!=pid:raise B('plan digest invalid')
 if now()>parsez(d['expires_at'],'plan expiry'):raise B('plan expired')
 if d['evidence_sha256']!=fsha(e) or d['host_state_receipt_sha256']!=fsha(h):raise B('bound evidence changed')
 return d
def atomic_copy(src,dst,mode=0o644):
 dst.parent.mkdir(parents=True,exist_ok=True,mode=0o755);tmp=dst.parent/(dst.name+'.aionex-new');shutil.copyfile(src,tmp);os.chmod(tmp,mode);os.replace(tmp,dst)
def rewrite_fstab_disable():
 text=FSTAB.read_text();matches=[line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#') and line.split()[0]==str(LEGACY)]
 if len(matches)!=1:raise B('exactly one active legacy swap fstab entry required')
 if FSTAB_BACKUP.exists():raise B('fstab rollback backup already exists')
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(FSTAB_BACKUP,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:os.write(fd,text.encode());os.fsync(fd)
 finally:os.close(fd)
 out=[]
 for line in text.splitlines():out.append(DISABLED_LINE if line in matches else line)
 tmp=FSTAB.with_name('.fstab.aionex-fr06c5-new');tmp.write_text('\n'.join(out)+'\n');os.chmod(tmp,0o644);os.chown(tmp,0,0);os.replace(tmp,FSTAB)
def restore_fstab():
 if FSTAB_BACKUP.exists():
  data=FSTAB_BACKUP.read_bytes();tmp=FSTAB.with_name('.fstab.aionex-fr06c5-rollback');tmp.write_bytes(data);os.chmod(tmp,0o644);os.chown(tmp,0,0);os.replace(tmp,FSTAB);FSTAB_BACKUP.unlink()
def backing_prepare():
 BACKING.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 if BACKING.exists():
  s=BACKING.stat()
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)!=0o600 or s.st_size!=SWAP_SIZE:raise B('encrypted swap backing drifted')
  return
 run(['fallocate','-l',str(SWAP_SIZE),str(BACKING)],300);os.chmod(BACKING,0o600);os.chown(BACKING,0,0)
def boot_swap_start():
 if os.geteuid()!=0:raise B('root required')
 if any(r['name']==str(LEGACY) for r in swap_rows()):raise B('legacy plaintext swap is active')
 backing_prepare()
 if MAPPER.exists():
  if any(same_swap_device(r['name'],MAPPER) for r in swap_rows()):return {'status':'encrypted_swap_active','mapper':str(MAPPER),'key_persisted':False}
  raise B('swap mapper exists but is not active')
 KEY.parent.mkdir(parents=True,exist_ok=True);fd=os.open(KEY,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:os.write(fd,os.urandom(64));os.fsync(fd)
 finally:os.close(fd)
 try:
  run(['cryptsetup','open','--type','plain','--cipher','aes-xts-plain64','--key-size','512','--key-file',str(KEY),str(BACKING),MAPPER_NAME],60);KEY.unlink(missing_ok=True);run(['mkswap',str(MAPPER)],60);run(['swapon',str(MAPPER)],60)
 finally:KEY.unlink(missing_ok=True)
 if not any(same_swap_device(r['name'],MAPPER) for r in swap_rows()):raise B('encrypted swap did not activate')
 return {'status':'encrypted_swap_active','mapper':str(MAPPER),'key_persisted':False}
def boot_swap_stop():
 rows=swap_rows()
 if MAPPER.exists():
  if any(same_swap_device(r['name'],MAPPER) for r in rows):run(['swapoff',str(MAPPER)],120)
  run(['cryptsetup','close',MAPPER_NAME],60)
 elif rows:raise B('swap device identity unavailable')
 KEY.unlink(missing_ok=True);return {'status':'encrypted_swap_inactive','key_persisted':False}
def tmp_ready():
 if not exact_mount(Path('/tmp')):return False
 typ=run(['findmnt','-n','-o','FSTYPE','--target','/tmp'])
 opts=set(run(['findmnt','-n','-o','OPTIONS','--target','/tmp']).split(','))
 return typ=='tmpfs' and {'nodev','nosuid','mode=1777'}.issubset(opts)
def verify_live():
 rows=swap_rows()
 if len(rows)!=1 or not same_swap_device(rows[0]['name'],MAPPER):raise B('swap acceptance failed')
 enc=rows
 if KEY.exists():raise B('random swap key persisted')
 if not tmp_ready():raise B('/tmp tmpfs acceptance failed')
 text=FSTAB.read_text()
 if any(line.strip() and not line.lstrip().startswith('#') and line.split()[0]==str(LEGACY) for line in text.splitlines()):raise B('legacy fstab swap entry still active')
 if run(['systemctl','is-enabled','aionex-fr06c5-encrypted-swap.service']) not in {'enabled','static'}:raise B('encrypted swap service not enabled')
 if run(['systemctl','is-enabled','tmp.mount']) not in {'enabled','static'}:raise B('tmp.mount not enabled')
 # The raw backing must not expose a plain mkswap signature.
 with BACKING.open('rb') as f:
  if b'SWAPSPACE2' in f.read(1024*1024):raise B('raw encrypted swap backing exposed swap signature')
 return {'validation':'FR06C5_MEMORY_CONTROLS_READY','encrypted_swap':enc[0],'tmp_fstype':'tmpfs','key_persisted':False,'legacy_swap_active':False}
def rollback_internal():
 subprocess.run(['systemctl','stop','tmp.mount'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['systemctl','disable','tmp.mount'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['systemctl','stop','aionex-fr06c5-encrypted-swap.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['systemctl','disable','aionex-fr06c5-encrypted-swap.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:boot_swap_stop()
 except Exception:pass
 restore_fstab()
 for p in (SWAP_UNIT_DST,TMP_DST):
  try:p.unlink()
  except OSError:pass
 subprocess.run(['systemctl','daemon-reload'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if LEGACY.exists():subprocess.run(['swapon',str(LEGACY)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def apply(a):
 p=loadplan(a.plan.resolve(),a.evidence.resolve(),a.host_state_receipt.resolve())
 if a.confirmation!=f"EXECUTE_FR06C5_MEMORY_CONTROLS:{p['plan_id']}" or a.confirm_production!=CONFIRM:raise B('exact production confirmation required')
 gitgate(a.merge_sha);evidence(a.evidence.resolve(),a.merge_sha);pre=current_preflight(a.host_state_receipt.resolve())
 if p['merge_sha']!=a.merge_sha:raise B('source changed after planning')
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(STATE/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try:
  backing_prepare();atomic_copy(SWAP_UNIT_SRC,SWAP_UNIT_DST);atomic_copy(TMP_SRC,TMP_DST);run(['swapoff',str(LEGACY)],120);rewrite_fstab_disable();run(['systemctl','daemon-reload']);run(['systemctl','enable','aionex-fr06c5-encrypted-swap.service','tmp.mount']);run(['systemctl','start','aionex-fr06c5-encrypted-swap.service'],120);holders=tmp_holders();
  if holders:raise B(f'/tmp holders appeared before mount: {len(holders)}')
  run(['systemctl','start','tmp.mount'],120);live=verify_live();body={'schema_version':1,'subpart':'FR-06C5E','status':'random_key_swap_and_tmpfs_active','completed_at':utc(),'operation_id':p['plan_id'],'merge_sha':a.merge_sha,'validation':live['validation'],'encrypted_swap_mapper':str(MAPPER),'encrypted_swap_backing':str(BACKING),'legacy_swap_backing_retained':True,'secure_erase_claimed':False,'random_key_persisted':False,'tmpfs_active':True,'tmp_hidden_underlay_fd_count_at_cutover':0,'cloudflare_changed':False,'admission_opened':False};out=STATE/'results'/f"{p['plan_id']}.json";store(out,{**body,'receipt_sha256':digest(body)});return {'status':body['status'],'result':str(out),'validation':live['validation']}
 except Exception as original:
  try:rollback_internal()
  except Exception as rb:raise E('memory-control activation failed and rollback failed') from rb
  raise E('memory-control activation failed; legacy swap/tmp rollback attempted') from original
 finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def rollback(a):
 r=jread(a.receipt.resolve());body={k:v for k,v in r.items() if k!='receipt_sha256'}
 if r.get('receipt_sha256')!=digest(body) or r.get('status')!='random_key_swap_and_tmpfs_active':raise B('accepted memory-controls receipt required')
 op=digest({'operation':'memory-controls-rollback','receipt':r['receipt_sha256'],'nonce':a.nonce})
 if a.confirmation!=f'ROLLBACK_FR06C5_MEMORY_CONTROLS:{op}' or a.confirm_production!=ROLLBACK_CONFIRM:raise B('exact rollback confirmation required')
 rollback_internal();return {'status':'legacy_swap_and_tmp_underlay_restored','secure_erase_claimed':False}
def inspect():return {'schema_version':1,'subpart':'FR-06C5E','observed_at':utc(),'swap':swap_rows(),'mem_available_bytes':mem_available(),'tmp_exact_mount':exact_mount(Path('/tmp')),'tmp_hidden_underlay_holder_count':len(tmp_holders()),'production_changed':False}
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);s.add_parser('inspect-runtime');s.add_parser('boot-swap-start');s.add_parser('boot-swap-stop');q=s.add_parser('plan');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--host-state-receipt',type=Path,required=True);q.add_argument('--ttl-seconds',type=int,default=600);q=s.add_parser('apply');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--host-state-receipt',type=Path,required=True);q.add_argument('--plan',type=Path,required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='');q=s.add_parser('rollback');q.add_argument('--receipt',type=Path,required=True);q.add_argument('--nonce',required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='');a=p.parse_args()
 try:o=inspect() if a.cmd=='inspect-runtime' else boot_swap_start() if a.cmd=='boot-swap-start' else boot_swap_stop() if a.cmd=='boot-swap-stop' else plan(a) if a.cmd=='plan' else apply(a) if a.cmd=='apply' else rollback(a);print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
 except Exception as e:print(json.dumps({'status':'error','reason':str(e)},sort_keys=True));return 1
if __name__=='__main__':raise SystemExit(main())
