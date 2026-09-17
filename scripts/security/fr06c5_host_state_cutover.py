#!/usr/bin/env python3
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,secrets,shutil,stat,subprocess,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any
ROOT=Path('/opt/AIOS');DASH=ROOT/'web-dashboard';STATE=Path('/var/lib/aionex/fr06c5-cutover');C5=Path('/var/lib/aionex/fr06c5-host-state');BOOT=Path('/var/lib/aionex/fr06c5-bootstrap');MOUNT=Path('/mnt/aionex/fr06-host-state-vault');MAX_TTL=900;MAX_AGE=3600;CONFIRM='FR06C5_PRODUCTION_HOST_STATE_CUTOVER'
SYSTEMD=((ROOT/'deploy/systemd/aionex-fr06c5-host-state-bind.service',Path('/etc/systemd/system/aionex-fr06c5-host-state-bind.service')),(ROOT/'deploy/systemd/docker.service.d/34-aionex-fr06c5-host-state-gate.conf',Path('/etc/systemd/system/docker.service.d/34-aionex-fr06c5-host-state-gate.conf')))
WRAPPERS=tuple((ROOT/'deploy/bin'/n,Path('/usr/local/sbin')/n) for n in ('aionex-phase22c-2-tunnel','aionex-phase22c-tunnel','trendbost-mcp-bridge-tunnel'))
PATHS=(('operator',Path('/root/.config/aionex'),MOUNT/'operator-state',False),('app-secrets',ROOT/'web-dashboard/secrets',MOUNT/'app-secrets',False),('deploy-key',Path('/root/.ssh/aionex_aios_deploy'),MOUNT/'ssh/aionex_aios_deploy',True),('cpanel-key',Path('/root/.ssh/aionex_cpanel_ai_vip_e_net_ed25519'),MOUNT/'ssh/aionex_cpanel_ai_vip_e_net_ed25519',True))
TUNNELS=('aionex-phase22c-2-tunnel.service','aionex-phase22c-tunnel.service','trendbost-mcp-bridge-tunnel.service')
class E(RuntimeError):pass
class B(E):pass
def now():return datetime.now(timezone.utc)
def utc(v=None):return (v or now()).isoformat(timespec='seconds').replace('+00:00','Z')
def run(a,t=180,cwd=None,check=True):
 r=subprocess.run(a,capture_output=True,text=True,timeout=t,check=False,cwd=cwd)
 if check and r.returncode:raise E(f'{a[0]} failed with exit code {r.returncode}; output withheld')
 return r.stdout.strip()
def active(u):return subprocess.run(['systemctl','is-active','--quiet',u]).returncode==0
def fsha(p):
 h=hashlib.sha256();fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  with os.fdopen(fd,'rb',closefd=False) as f:
   for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 finally:os.close(fd)
 return h.hexdigest()
def private(p,label,maxb=16*1024*1024):
 try:s=os.lstat(p)
 except OSError as x:raise B(f'{label} unavailable') from x
 if stat.S_ISLNK(s.st_mode) or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=0 or s.st_mode&0o077 or not 1<=s.st_size<=maxb:raise B(f'{label} unsafe')
def jread(p):
 try:v=json.loads(p.read_text())
 except Exception as x:raise E(f'cannot read {p.name}') from x
 if not isinstance(v,dict):raise E('JSON object required')
 return v
def store(p,v):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
 try:os.write(fd,json.dumps(v,sort_keys=True,indent=2).encode()+b'\n');os.fsync(fd)
 finally:os.close(fd)
def atomic_store(p,v):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=p.parent/(p.name+'.aionex-new-'+secrets.token_hex(4));fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
 try:os.write(fd,json.dumps(v,sort_keys=True,indent=2).encode()+b'\n');os.fsync(fd)
 finally:os.close(fd)
 os.replace(tmp,p);d=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 try:os.fsync(d)
 finally:os.close(d)
def attempt_path(plan_id):return STATE/'attempts'/f'{plan_id}.json'
def update_attempt(path,**changes):
 d=jread(path);d.update(changes);d['updated_at']=utc();atomic_store(path,d);return d
def unresolved_attempt_gate():
 d=STATE/'attempts'
 if not d.exists():return
 for p in sorted(d.glob('*.json')):
  private(p,'prior attempt');a=jread(p)
  if a.get('phase') not in {'failed_before_live_mutation','legacy_restored_prestart','accepted'}:raise B('prior host-state cutover attempt requires reconciliation')
def parsez(v,label):
 if not isinstance(v,str) or not v.endswith('Z'):raise B(f'{label} must be UTC Z')
 try:return datetime.fromisoformat(v[:-1]+'+00:00').astimezone(timezone.utc)
 except ValueError as x:raise B(f'{label} invalid') from x
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def digest(v):return hashlib.sha256(canon(v)).hexdigest()
def gitgate(sha):
 heads=run(['git','-C',str(ROOT),'rev-parse','HEAD','origin/main']).splitlines()
 if heads!=[sha,sha] or run(['git','-C',str(ROOT),'status','--porcelain=v1']):raise B('production source is not clean exact accepted main')
def topology():
 raw=run(['docker','ps','--format','{{.ID}}']);ids=[x for x in raw.splitlines() if x.strip()];rows=[]
 if len(ids)!=36:raise B('running container count is not 36')
 for cid in ids:
  d=json.loads(run(['docker','inspect',cid]))[0];labels=(d.get('Config') or {}).get('Labels') or {};service=labels.get('com.docker.compose.service');project=labels.get('com.docker.compose.project');state=d.get('State') or {};health=str((state.get('Health') or {}).get('Status','none'))
  if project!='web-dashboard' or not service or health not in {'healthy','none'}:raise B('live topology is not exact healthy web-dashboard set')
  rp=(d.get('HostConfig') or {}).get('RestartPolicy') or {};rpn=str(rp.get('Name') or 'no');mr=int(rp.get('MaximumRetryCount') or 0);restart=rpn+(f':{mr}' if rpn=='on-failure' and mr>0 else '');rows.append({'id':d['Id'],'name':str(d.get('Name','')).lstrip('/'),'service':service,'health':health,'restart':restart})
 services={}
 for r in rows:services.setdefault(r['service'],[]).append(r['id'])
 if len(services.get('project-worker',[]))!=4:raise B('project-worker scale drifted')
 return {'containers':sorted(rows,key=lambda x:x['name']),'services':{k:sorted(v) for k,v in sorted(services.items())},'container_count':36,'project_worker_scale':4}
def c5gate():
 expected=((BOOT/'bootstrap-receipt.json','minimal_management_bootstrap_installed'),(C5/'provision-receipt.json','empty_host_state_vault_provisioned_admission_closed'),(C5/'recovery-proof.json','independent_host_state_recovery_key_proved'),(C5/'header-custody.json','off_host_host_state_header_verified'))
 for p,status in expected:
  private(p,p.name);d=jread(p)
  if d.get('status')!=status:raise B(f'{p.name} status unacceptable')
 v=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c5_host_state_vault.py'),'status','--require-host-ready']))
 if v.get('validation')!='FR06C5_HOST_STATE_VAULT_READY':raise B('host-state vault not ready')
 b=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c5_host_state_bind.py'),'status']))
 if b.get('validation')=='FR06C5_HOST_STATE_BIND_READY':raise B('host-state bind already active')
 for src,dst in WRAPPERS:
  if not dst.is_file() or fsha(src)!=fsha(dst):raise B('installed tunnel wrapper drifted')
 if fsha(ROOT/'ops/mcp2/server.py')!=fsha(ROOT/'tools/aionex_phase22c_mcp2.py'):raise B('live MCP2 source not updated to accepted tracked source')
 for u in TUNNELS:
  if not active(u):raise B('required control tunnel inactive')
 r=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'status','--require-ready']))
 if r.get('validation')!='FR06C4_RUNTIME_BIND_READY':raise B('encrypted container runtime no longer accepted')
def evidence(p,sha):
 private(p,'cutover evidence');d=jread(p)
 if d.get('schema_version')!=1 or d.get('subpart')!='FR-06C5D' or d.get('environment')!='production' or d.get('production_authorization') is not True:raise B('evidence metadata invalid')
 age=(now()-parsez(d.get('observed_at'),'observed_at')).total_seconds()
 if age < -300 or age > MAX_AGE:raise B('evidence stale/future-dated')
 src=d.get('source') or {}
 if src.get('merge_sha')!=sha or src.get('protected_pr_checks_passed') is not True or src.get('post_merge_main_checks_passed') is not True:raise B('source CI evidence incomplete')
 rec=d.get('recovery') or {}
 for k,w in {'backup_status':'completed','offsite_status':'completed','restore_status':'completed','restore_validated':True,'restore_offsite_validated':True}.items():
  if rec.get(k)!=w:raise B(f'recovery gate failed: {k}')
 rage=(now()-parsez(rec.get('restore_completed_at'),'restore_completed_at')).total_seconds()
 if rage < -300 or rage > MAX_AGE:raise B('restore validation stale')
 ops=d.get('operations') or {}
 for k in ('active_backup_jobs','active_restore_validations','active_durable_external_jobs','active_realtime_sessions','active_livekit_rooms'):
  if ops.get(k)!=0:raise B(f'operations not drained: {k}')
 if ops.get('admission_closed') is not True or ops.get('cloudflare_changed') is not False:raise B('admission/Cloudflare unsafe')
 a=d.get('approvals') or {};start=parsez(a.get('window_starts_at'),'window start');end=parsez(a.get('window_ends_at'),'window end')
 if a.get('owner_authorized') is not True or end<=start or not start<=now()<=end or (end-start).total_seconds()>4*3600:raise B('maintenance window invalid')
 return d
def source_entry(path):
 s=os.lstat(path)
 if stat.S_ISLNK(s.st_mode):raise B('symlink in host-state source rejected')
 if stat.S_ISREG(s.st_mode) and s.st_nlink!=1:raise B('hardlinked host-state file rejected')
 if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):raise B('special host-state entry rejected')
 return s
def tree_manifest(root):
 root=root.resolve(strict=True);h=hashlib.sha256();files=dirs=payload=0
 def add(rel,p):
  nonlocal files,dirs,payload
  s=source_entry(p);mode=stat.S_IMODE(s.st_mode);base=f'{rel}\0{mode:o}\0{s.st_uid}\0{s.st_gid}\0'
  if stat.S_ISDIR(s.st_mode):dirs+=1;h.update((base+'D\n').encode());return
  files+=1;payload+=s.st_size;fh=fsha(p);h.update((base+f'F\0{s.st_size}\0{fh}\n').encode())
 add('.',root)
 for p in sorted(root.rglob('*'),key=lambda x:str(x.relative_to(root))):add(str(p.relative_to(root)),p)
 return {'aggregate_sha256':h.hexdigest(),'files':files,'directories':dirs,'payload_bytes':payload}
def file_manifest(path):
 p=path.resolve(strict=True);s=source_entry(p)
 if not stat.S_ISREG(s.st_mode):raise B('private-key source is not regular')
 return {'sha256':fsha(p),'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size}
def mount_targets():
 raw=run(['findmnt','-rn','-o','TARGET'])
 out=[]
 for line in raw.splitlines():
  value=line.replace('\040',' ').replace('\011','\t').replace('\134','\\')
  out.append(value)
 return out
def reject_nested_mounts():
 mounts=mount_targets()
 for _,src,_,isfile in PATHS:
  if isfile:continue
  base=str(src).rstrip('/')
  nested=[m for m in mounts if m==base or m.startswith(base+'/')]
  if nested:raise B(f'unexpected mount under host-state source: {src}')
def precopy():
 for role,src,dst,isfile in PATHS:
  if isfile:
   dst.parent.mkdir(parents=True,exist_ok=True,mode=0o700);run(['rsync','-aHAX','--numeric-ids',str(src),str(dst)],300)
  else:
   dst.mkdir(parents=True,exist_ok=True,mode=0o700);run(['rsync','-aHAX','--numeric-ids','--delete',str(src)+'/',str(dst)+'/'],1800)
def exact_mount(p):
 r=subprocess.run(['findmnt','-n','-o','TARGET','--target',str(p)],capture_output=True,text=True,check=False)
 return r.returncode==0 and r.stdout.strip()==str(p)
def sealed(p):
 if not exact_mount(p):return False
 r=subprocess.run(['findmnt','-n','-o','OPTIONS','--target',str(p)],capture_output=True,text=True,check=False)
 return r.returncode==0 and 'ro' in set(r.stdout.strip().split(','))
def seal(p):
 if sealed(p):return
 run(['mount','--bind',str(p),str(p)]);run(['mount','-o','remount,bind,ro,nodev,nosuid,noexec',str(p)])
 if not sealed(p):raise B('legacy host-state seal failed')
def unseal_all_checked():
 for _,src,_,_ in reversed(PATHS):
  if exact_mount(src):
   run(['umount',str(src)],120)
   if exact_mount(src):raise B('legacy host-state seal remained after rollback')
def exact_copy_and_manifest():
 for _,src,dst,isfile in PATHS:
  if isfile:run(['rsync','-aHAX','--numeric-ids',str(src),str(dst)],300)
  else:run(['rsync','-aHAX','--numeric-ids','--delete',str(src)+'/',str(dst)+'/'],1800)
 out={}
 for role,src,dst,isfile in PATHS:
  a=file_manifest(src) if isfile else tree_manifest(src);b=file_manifest(dst) if isfile else tree_manifest(dst)
  if a!=b:raise B(f'exact host-state manifest mismatch: {role}')
  out[role]=a
 return out
def hidden_underlay_fds():
 holders=[]
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  fdroot=proc/'fd'
  try:fds=list(fdroot.iterdir())
  except OSError:continue
  for fdpath in fds:
   try:target=os.readlink(fdpath)
   except OSError:continue
   clean=target[:-10] if target.endswith(' (deleted)') else target
   for role,src,_,isfile in PATHS:
    base=str(src)
    if (isfile and clean==base) or (not isfile and (clean==base or clean.startswith(base.rstrip('/')+'/'))):
     holders.append({'pid':int(proc.name),'fd':fdpath.name,'role':role})
 return holders

def require_zero_hidden_underlay_fds():
 holders=hidden_underlay_fds()
 if holders:raise B('legacy host-state source has open file descriptors before bind activation')
 return 0

def bootstrap_match():
 key=Path('/root/.config/aionex-bootstrap/control-plane.key');up=Path('/root/.config/aionex-bootstrap/trendbost-mcp-upstream.url')
 if fsha(key)!=fsha(Path('/root/.config/aionex/aionex-tunnel-runtime.key')):raise B('bootstrap control-plane key drifted from sealed operator source')
 if fsha(up)!=fsha(Path('/root/.config/aionex/trendbost-mcp-upstream.url')):raise B('bootstrap bridge upstream drifted from sealed operator source')
def atomic_install(src,dst):
 dst.parent.mkdir(parents=True,exist_ok=True,mode=0o755);tmp=dst.parent/(dst.name+'.aionex-new');shutil.copyfile(src,tmp);os.chmod(tmp,0o644);os.replace(tmp,dst)
def install_gates():
 for src,dst in SYSTEMD:
  atomic_install(src,dst)
  if fsha(src)!=fsha(dst):raise B('installed host-state gate hash mismatch')
 run(['systemctl','daemon-reload']);run(['systemctl','enable','aionex-fr06c5-host-state-bind.service'])
def remove_gates_checked():
 enabled=subprocess.run(['systemctl','is-enabled','aionex-fr06c5-host-state-bind.service'],capture_output=True,text=True,check=False).stdout.strip() in {'enabled','static'}
 if enabled:run(['systemctl','disable','aionex-fr06c5-host-state-bind.service'],60)
 for src,dst in SYSTEMD:
  if dst.exists():
   if dst.is_symlink() or not dst.is_file() or fsha(src)!=fsha(dst):raise B('refusing to remove drifted host-state gate')
   dst.unlink()
 run(['systemctl','daemon-reload'])
def watcher_states():return {u:active(u) for u in ('aionex-runtime-watch.timer','aionex-runtime-watch.service')}
def stop_watchers(states):
 for u,on in states.items():
  if on:run(['systemctl','stop',u],60)
 for u,on in states.items():
  if on and active(u):raise B('runtime watcher failed to stop')
def restore_watchers(states):
 for u,on in states.items():
  if on:run(['systemctl','start',u],60)
 for u,on in states.items():
  if on and not active(u):raise B('runtime watcher failed to restore')
def current_restart(container_id):
 d=json.loads(run(['docker','inspect',container_id]))[0];rp=(d.get('HostConfig') or {}).get('RestartPolicy') or {};name=str(rp.get('Name') or 'no');count=int(rp.get('MaximumRetryCount') or 0);return name+(f':{count}' if name=='on-failure' and count>0 else '')
def quiesce_restart_policies(t):
 for r in t['containers']:run(['docker','update','--restart=no',r['id']],60)
 for r in t['containers']:
  if current_restart(r['id'])!='no':raise B('container restart policy did not quiesce')
def restore_restart_policies(t):
 for r in t['containers']:run(['docker','update','--restart='+r['restart'],r['id']],60)
 for r in t['containers']:
  if current_restart(r['id'])!=r['restart']:raise B('container restart policy did not restore')
def stop_live(t):
 ids=[r['id'] for r in t['containers']];run(['docker','stop','--time','60',*ids],180)
 if run(['docker','ps','-q']).strip():raise B('running Docker containers remained')
 run(['systemctl','stop','docker.service','docker.socket'],120)
 if active('docker.service'):raise B('Docker remained active')
def legacy_acceptance(t):
 n=topology()
 if {r['id'] for r in n['containers']}!={r['id'] for r in t['containers']} or set(n['services'])!=set(t['services']) or n['project_worker_scale']!=t['project_worker_scale']:raise B('legacy topology failed rollback acceptance')
 r=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'status','--require-ready']))
 if r.get('validation')!='FR06C4_RUNTIME_BIND_READY':raise B('encrypted container runtime regressed during rollback')
 for u in ('http://127.0.0.1:8080/health','http://127.0.0.1:8080/ready','https://api.vip-e.net/health','https://api.vip-e.net/ready','https://ai.vip-e.net/'):
  if run(['curl','-ksS','-o','/dev/null','-w','%{http_code}',u],30)!='200':raise B('legacy HTTP rollback acceptance failed')
 for u in TUNNELS:
  if not active(u):raise B('control tunnel regressed during rollback')
 return n
def rollback_prestart(t,watch,phase):
 no_live={'claimed','precopy_started'}
 watcher_only={'watcher_stop_started','watchers_stopped'}
 policy_only={'restart_policy_quiesce_started','restart_policies_quiesced'}
 if phase in no_live:return {'status':'no_live_mutation_to_rollback'}
 if phase in watcher_only:
  restore_watchers(watch);return {'status':'watchers_restored'}
 if phase in policy_only:
  if not active('docker.service'):raise B('Docker unexpectedly inactive during policy-only rollback')
  restore_restart_policies(t);restore_watchers(watch);legacy_acceptance(t);return {'status':'policies_and_watchers_restored'}
 # Application stop may have partially stopped containers; later phases may also
 # own seals, gates and candidate bind mounts. Reconcile conservatively.
 bind_unit=Path('/etc/systemd/system/aionex-fr06c5-host-state-bind.service')
 gates_present=any(dst.exists() for _,dst in SYSTEMD)
 if gates_present or phase in {'gate_install_started','gates_installed','bind_activation_started','bind_active'}:
  run(['systemctl','stop','docker.service','docker.socket'],120)
  if active('docker.service'):raise B('Docker remained active during rollback')
  if bind_unit.exists():run(['systemctl','stop','aionex-fr06c5-host-state-bind.service'],120)
  rb=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c5_host_state_bind.py'),'rollback'],120))
  if rb.get('validation')!='FR06C5_HOST_STATE_BIND_REMOVED':raise B('candidate host-state bind rollback not verified')
  remove_gates_checked()
 if phase in {'legacy_seal_started','legacy_sources_sealed','gate_install_started','gates_installed','bind_activation_started','bind_active'}:
  unseal_all_checked()
 if not active('docker.service'):
  run(['systemctl','start','docker.socket','docker.service'],180)
 if not active('docker.service'):raise B('legacy Docker failed to restart')
 run(['docker','start',*[r['id'] for r in t['containers']]],180);restore_restart_policies(t);restore_watchers(watch);legacy_acceptance(t);return {'status':'legacy_runtime_fully_restored'}
def acceptance(t):
 bind=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c5_host_state_bind.py'),'status','--require-ready']))
 if bind.get('validation')!='FR06C5_HOST_STATE_BIND_READY':raise B('host-state bind acceptance failed')
 r=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'status','--require-ready']))
 if r.get('validation')!='FR06C4_RUNTIME_BIND_READY':raise B('container runtime bind regressed')
 for _ in range(60):
  try:n=topology();break
  except Exception:time.sleep(5)
 else:raise B('container health timeout')
 if set(n['services'])!=set(t['services']) or n['project_worker_scale']!=4:raise B('service topology drifted')
 for u in ('http://127.0.0.1:8080/health','http://127.0.0.1:8080/ready','https://api.vip-e.net/health','https://api.vip-e.net/ready','https://ai.vip-e.net/'):
  if run(['curl','-ksS','-o','/dev/null','-w','%{http_code}',u],30)!='200':raise B('HTTP acceptance failed')
 for u in TUNNELS:
  if not active(u):raise B('control tunnel regressed')
 return n
def inspect():return {'schema_version':1,'subpart':'FR-06C5D','observed_at':utc(),'topology':topology(),'docker_active':active('docker.service'),'containerd_active':active('containerd.service'),'production_changed':False}
def plan(a):
 if os.geteuid()!=0:raise B('root required')
 gitgate(a.merge_sha);evidence(a.evidence.resolve(),a.merge_sha);c5gate();unresolved_attempt_gate();t=topology()
 if not active('docker.service') or not active('containerd.service'):raise B('live runtime not active')
 if not 1<=a.ttl_seconds<=MAX_TTL:raise B('plan TTL invalid')
 n=now();body={'schema_version':1,'subpart':'FR-06C5D','operation':'host-state-cutover','created_at':utc(n),'expires_at':utc(n+timedelta(seconds=a.ttl_seconds)),'merge_sha':a.merge_sha,'evidence_sha256':fsha(a.evidence.resolve()),'topology':t,'nonce':secrets.token_hex(32),'blind_post_start_rollback_permitted':False,'cloudflare_change_permitted':False};body['plan_id']=digest(body);p=STATE/'plans'/f"{body['plan_id']}.json";store(p,body);return {'status':'host_state_cutover_plan_ready','plan_id':body['plan_id'],'plan':str(p),'production_executed':False}
def loadplan(p,e):
 private(p,'plan');d=jread(p);pid=d.get('plan_id')
 if not isinstance(pid,str) or digest({k:v for k,v in d.items() if k!='plan_id'})!=pid:raise B('plan digest invalid')
 if now()>parsez(d['expires_at'],'plan expiry'):raise B('plan expired')
 if d['evidence_sha256']!=fsha(e):raise B('evidence changed after planning')
 return d
def apply(a):
 p=loadplan(a.plan.resolve(),a.evidence.resolve())
 if a.confirmation!=f"EXECUTE_FR06C5_HOST_STATE_CUTOVER:{p['plan_id']}" or a.confirm_production!=CONFIRM:raise B('exact production confirmation required')
 gitgate(a.merge_sha);evidence(a.evidence.resolve(),a.merge_sha);c5gate();unresolved_attempt_gate();t=topology()
 if p['merge_sha']!=a.merge_sha or t!=p['topology']:raise B('live topology changed after planning')
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(STATE/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);attempt=attempt_path(p['plan_id']);watch={};candidate_start_attempted=False;claimed=False
 try:
  try:store(attempt,{'schema_version':1,'subpart':'FR-06C5D','plan_id':p['plan_id'],'merge_sha':a.merge_sha,'phase':'claimed','created_at':utc(),'candidate_start_attempted':False})
  except FileExistsError as x:raise B('host-state cutover plan already attempted') from x
  claimed=True
  reject_nested_mounts();update_attempt(attempt,phase='precopy_started');precopy();watch=watcher_states();update_attempt(attempt,phase='watcher_stop_started',watchers=watch);stop_watchers(watch);update_attempt(attempt,phase='watchers_stopped');update_attempt(attempt,phase='restart_policy_quiesce_started');quiesce_restart_policies(t);update_attempt(attempt,phase='restart_policies_quiesced');update_attempt(attempt,phase='application_stop_started');stop_live(t);update_attempt(attempt,phase='legacy_runtime_stopped');update_attempt(attempt,phase='legacy_seal_started')
  for _,src,_,_ in PATHS:seal(src)
  update_attempt(attempt,phase='legacy_sources_sealed');manifests=exact_copy_and_manifest();bootstrap_match();hidden_fd_count=require_zero_hidden_underlay_fds();update_attempt(attempt,phase='gate_install_started');install_gates();update_attempt(attempt,phase='gates_installed');update_attempt(attempt,phase='bind_activation_started');run(['systemctl','start','aionex-fr06c5-host-state-bind.service'],120);bind=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c5_host_state_bind.py'),'status','--require-ready']))
  if bind.get('validation')!='FR06C5_HOST_STATE_BIND_READY':raise B('host-state candidate bind did not become ready')
  update_attempt(attempt,phase='bind_active')
  candidate_start_attempted=True;update_attempt(attempt,phase='candidate_start_attempted',candidate_start_attempted=True)
  run(['systemctl','start','docker.socket','docker.service'],180);run(['docker','start',*[r['id'] for r in t['containers']]],180);restore_restart_policies(t);restore_watchers(watch);n=acceptance(t)
  body={'schema_version':1,'subpart':'FR-06C5D','status':'encrypted_host_state_started_admission_closed','completed_at':utc(),'operation_id':p['plan_id'],'merge_sha':a.merge_sha,'running_containers':36,'unhealthy_running_containers':0,'project_worker_scale':4,'manifest':manifests,'hidden_underlay_fd_count':hidden_fd_count,'legacy_underlays_read_only':True,'legacy_underlays_deleted':False,'candidate_host_state_authoritative':True,'bootstrap_remains_outside_vault':True,'post_start_blind_rollback_permitted':False,'admission_opened':False,'cloudflare_changed':False};out=STATE/'results'/f"{p['plan_id']}.json";store(out,{**body,'receipt_sha256':digest(body)});update_attempt(attempt,phase='accepted',accepted_receipt=str(out));return {'status':body['status'],'result':str(out),'admission_opened':False}
 except Exception as original:
  if not claimed:
   raise
  if attempt.exists() and not candidate_start_attempted:
   phase=str(jread(attempt).get('phase','claimed'))
   if phase in {'claimed','precopy_started'}:
    update_attempt(attempt,phase='failed_before_live_mutation',last_error_type=type(original).__name__)
    raise E('host-state cutover failed before live mutation; plan consumed without outage') from original
   try:
    rollback_prestart(p['topology'],watch,phase);update_attempt(attempt,phase='legacy_restored_prestart',last_error_type=type(original).__name__)
   except Exception as rb:
    try:update_attempt(attempt,phase='rollback_failed',last_error_type=type(original).__name__,rollback_error_type=type(rb).__name__)
    except Exception:pass
    raise E('host-state cutover failed before candidate start and rollback failed; reconciliation required') from rb
   raise E('host-state cutover failed before candidate start; legacy runtime restored and plan consumed') from original
  if attempt.exists():
   try:update_attempt(attempt,phase='post_start_failure_requires_reconciliation',candidate_start_attempted=True,last_error_type=type(original).__name__)
   except Exception:pass
  raise E('host-state cutover failed after candidate start attempt; candidate state may be authoritative and blind rollback is prohibited') from original
 finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);s.add_parser('inspect-runtime');q=s.add_parser('plan-cutover');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--ttl-seconds',type=int,default=600);q=s.add_parser('apply-cutover');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--plan',type=Path,required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='');a=p.parse_args()
 try:o=inspect() if a.cmd=='inspect-runtime' else plan(a) if a.cmd=='plan-cutover' else apply(a);print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
 except Exception as e:print(json.dumps({'status':'error','reason':str(e)},sort_keys=True));return 1
if __name__=='__main__':raise SystemExit(main())
