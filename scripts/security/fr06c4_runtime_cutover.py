#!/usr/bin/env python3
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,secrets,shutil,stat,subprocess,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any
ROOT=Path('/opt/AIOS');DASH=ROOT/'web-dashboard';ENV=DASH/'.env.production';STATE=Path('/var/lib/aionex/fr06c4-cutover');CANDIDATE=Path('/var/lib/aionex/fr06c4-candidate/accepted.json');C4_STATE=Path('/var/lib/aionex/fr06c4-runtime');MAX_TTL=900;MAX_EVIDENCE_AGE=3600;CONFIRM='FR06C4_PRODUCTION_RUNTIME_CUTOVER';ROLLBACK_CONFIRM='FR06C4_PRODUCTION_RUNTIME_ROLLBACK'
COMPOSE=(DASH/'docker-compose.production.yml',DASH/'docker-compose.fr06-assets.yml',DASH/'docker-compose.fr06-admission.yml',DASH/'docker-compose.fr06-database.yml',DASH/'docker-compose.fr06-database-admission.yml',DASH/'docker-compose.fr06-backup.yml',DASH/'docker-compose.fr06-operations.yml',DASH/'docker-compose.fr06-operations-admission.yml')
SYSTEMD=(
(ROOT/'deploy/systemd/aionex-fr06c4-runtime-bind.service',Path('/etc/systemd/system/aionex-fr06c4-runtime-bind.service')),
(ROOT/'deploy/systemd/containerd.service.d/30-aionex-fr06c4-runtime-gate.conf',Path('/etc/systemd/system/containerd.service.d/30-aionex-fr06c4-runtime-gate.conf')),
(ROOT/'deploy/systemd/docker.service.d/33-aionex-fr06c4-runtime-gate.conf',Path('/etc/systemd/system/docker.service.d/33-aionex-fr06c4-runtime-gate.conf')))
VOLUMES={
'aionex-fr06-asset-vault':('ext4','/dev/mapper/aionex-asset-vault','nodev,nosuid,noexec'),
'aionex-fr06-project-execution-vault':('ext4','/dev/mapper/aionex-project-execution-vault','nodev,nosuid'),
'aionex-fr06-database-vault':('ext4','/dev/mapper/aionex-database-vault','nodev,nosuid,noexec'),
'aionex-fr06-local-backup-vault':('ext4','/dev/mapper/aionex-local-backup-vault','nodev,nosuid,noexec'),
'aionex-fr06-operations-vault':('ext4','/dev/mapper/aionex-operations-vault','nodev,nosuid,noexec')}
class E(RuntimeError):pass
class B(E):pass
def now():return datetime.now(timezone.utc)
def utc(v=None):return (v or now()).isoformat(timespec='seconds').replace('+00:00','Z')
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def digest(v):return hashlib.sha256(canon(v)).hexdigest()
def run(a,timeout=180,cwd=None):
 r=subprocess.run(a,capture_output=True,text=True,timeout=timeout,check=False,cwd=cwd)
 if r.returncode:raise E(f'{a[0]} failed with exit code {r.returncode}; output withheld')
 return r.stdout.strip()
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
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:os.write(fd,json.dumps(v,sort_keys=True,indent=2).encode()+b'\n');os.fsync(fd)
 finally:os.close(fd)
def active(unit):return subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0
def parsez(value,label):
 if not isinstance(value,str) or not value.endswith('Z'):raise B(f'{label} must be RFC3339 UTC Z')
 try:return datetime.fromisoformat(value[:-1]+'+00:00').astimezone(timezone.utc)
 except ValueError as x:raise B(f'{label} invalid') from x
def gitgate(sha):
 heads=run(['git','-C',str(ROOT),'rev-parse','HEAD','origin/main']).splitlines()
 if heads!=[sha,sha] or run(['git','-C',str(ROOT),'status','--porcelain=v1']):raise B('production source is not clean exact accepted main')
def docker_json(args):return json.loads(run(['docker',*args],120))
def compose(args,timeout=900):
 c=['docker','compose','--env-file',str(ENV),'--profile','*']
 for f in COMPOSE:c+=['-f',str(f)]
 c+=args;return run(c,timeout,cwd=str(DASH))
def topology():
 raw=run(['docker','ps','--filter','label=com.docker.compose.project=web-dashboard','--format','{{json .}}']);rows=[]
 for line in raw.splitlines():
  if not line.strip():continue
  d=json.loads(line);cid=d['ID'];item=json.loads(run(['docker','inspect',cid]))[0];labels=item.get('Config',{}).get('Labels') or {};state=item.get('State') or {};service=labels.get('com.docker.compose.service')
  if not service:continue
  rows.append({'id':cid,'name':str(item.get('Name','')).lstrip('/'),'service':service,'image':str(item.get('Image','')),'health':str((state.get('Health') or {}).get('Status','none'))})
 if len(rows)!=36 or any(r['health'] not in {'healthy','none'} for r in rows):raise B('live topology is not exactly 36 healthy/healthless containers')
 services={}
 for r in rows:services.setdefault(r['service'],[]).append(r['id'])
 if len(services.get('project-worker',[]))!=4:raise B('project-worker scale drifted')
 return {'containers':sorted(rows,key=lambda x:x['name']),'services':{k:sorted(v) for k,v in sorted(services.items())},'container_count':36,'service_count':len(services),'project_worker_scale':4}
def c4gate():
 private(CANDIDATE,'candidate reconstruction receipt');c=jread(CANDIDATE)
 if c.get('status')!='isolated_candidate_runtime_reconstruction_accepted' or c.get('authority_count')!=17 or c.get('application_container_count')!=0 or c.get('historical_runtime_copy_performed') is not False:raise B('candidate runtime reconstruction not accepted')
 if Path('/run/aionex-fr06c4-candidate/docker.sock').exists() or Path('/run/aionex-fr06c4-candidate/containerd/containerd.sock').exists():raise B('candidate reconstruction daemons are still active')
 for pidfile in (Path('/run/aionex-fr06c4-candidate/dockerd.pid'),Path('/run/aionex-fr06c4-candidate/containerd.pid')):
  if pidfile.exists():raise B('candidate daemon pidfile remained after reconstruction')
 for p,label,status in ((C4_STATE/'provision-receipt.json','runtime vault receipt','empty_container_runtime_vault_provisioned_admission_closed'),(C4_STATE/'recovery-proof.json','runtime recovery proof','independent_runtime_recovery_key_proved'),(C4_STATE/'header-custody.json','runtime header custody','off_host_runtime_header_verified')):
  private(p,label);d=jread(p)
  if d.get('status')!=status:raise B(f'{label} unacceptable')
 d=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_vault.py'),'status','--require-host-ready']))
 if d.get('validation')!='FR06C4_RUNTIME_VAULT_HOST_READY':raise B('runtime vault not host-ready')
 b=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'status']))
 if b.get('validation')=='FR06C4_RUNTIME_BIND_READY':raise B('candidate runtime already live-bound')
def evidence(p,sha):
 private(p,'cutover evidence');d=jread(p)
 if d.get('schema_version')!=1 or d.get('subpart')!='FR-06C4C3B' or d.get('environment')!='production' or d.get('production_authorization') is not True:raise B('cutover evidence metadata invalid')
 age=(now()-parsez(d.get('observed_at'),'evidence observed_at')).total_seconds()
 if age < -300 or age > MAX_EVIDENCE_AGE:raise B('cutover evidence stale/future-dated')
 src=d.get('source') or {}
 if src.get('merge_sha')!=sha or src.get('protected_pr_checks_passed') is not True or src.get('post_merge_main_checks_passed') is not True:raise B('source CI evidence incomplete')
 r=d.get('recovery') or {}
 for k,w in {'backup_status':'completed','offsite_status':'completed','restore_status':'completed','restore_validated':True,'restore_offsite_validated':True}.items():
  if r.get(k)!=w:raise B(f'recovery gate failed: {k}')
 restore_age=(now()-parsez(r.get('restore_completed_at'),'restore completed_at')).total_seconds()
 if restore_age < -300 or restore_age > MAX_EVIDENCE_AGE:raise B('restore validation stale/future-dated')
 ops=d.get('operations') or {}
 for k in ('active_backup_jobs','active_restore_validations','active_durable_external_jobs','active_realtime_sessions','active_livekit_rooms'):
  if ops.get(k)!=0:raise B(f'operations not drained: {k}')
 if ops.get('admission_closed') is not True or ops.get('cloudflare_changed') is not False:raise B('admission/Cloudflare preflight unsafe')
 a=d.get('approvals') or {};start=datetime.fromisoformat(str(a.get('window_starts_at','')).replace('Z','+00:00'));end=datetime.fromisoformat(str(a.get('window_ends_at','')).replace('Z','+00:00'))
 if a.get('owner_authorized') is not True or not start<=now()<=end or end<=start or (end-start).total_seconds()>4*3600:raise B('maintenance window invalid')
 return d
def inspect():return {'schema_version':1,'subpart':'FR-06C4C3B','observed_at':utc(),'docker_active':active('docker.service'),'containerd_active':active('containerd.service'),'topology':topology(),'production_changed':False}
def plan(a):
 if os.geteuid()!=0:raise B('root required')
 gitgate(a.merge_sha);evidence(a.evidence.resolve(),a.merge_sha);c4gate();t=topology()
 if not active('docker.service') or not active('containerd.service'):raise B('live daemons must be active')
 if not 1<=a.ttl_seconds<=MAX_TTL:raise B('plan TTL invalid')
 n=now();body={'schema_version':1,'subpart':'FR-06C4C3B','operation':'live-runtime-cutover','created_at':utc(n),'expires_at':utc(n+timedelta(seconds=a.ttl_seconds)),'merge_sha':a.merge_sha,'evidence_sha256':hashlib.sha256(a.evidence.resolve().read_bytes()).hexdigest(),'candidate_receipt_sha256':hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),'topology':t,'nonce':secrets.token_hex(32),'historical_runtime_copy_permitted':False,'cloudflare_change_permitted':False};body['plan_id']=digest(body);p=STATE/'plans'/f"{body['plan_id']}.json";store(p,body);return {'status':'runtime_cutover_plan_ready','plan_id':body['plan_id'],'plan':str(p),'production_executed':False}
def loadplan(p,e):
 private(p,'cutover plan');d=jread(p);pid=d.get('plan_id')
 if not isinstance(pid,str) or digest({k:v for k,v in d.items() if k!='plan_id'})!=pid:raise B('plan digest invalid')
 if now()>datetime.fromisoformat(d['expires_at'].replace('Z','+00:00')):raise B('plan expired')
 if d['evidence_sha256']!=hashlib.sha256(e.read_bytes()).hexdigest() or d['candidate_receipt_sha256']!=hashlib.sha256(CANDIDATE.read_bytes()).hexdigest():raise B('bound evidence/candidate changed')
 return d
def atomic_install(src,dst):
 if not src.is_file():raise B('systemd source missing')
 dst.parent.mkdir(parents=True,exist_ok=True,mode=0o755);tmp=dst.parent/(dst.name+'.aionex-new');shutil.copyfile(src,tmp);os.chmod(tmp,0o644);os.replace(tmp,dst)
def install_gates():
 for src,dst in SYSTEMD:atomic_install(src,dst)
 run(['systemctl','daemon-reload']);run(['systemctl','enable','aionex-fr06c4-runtime-bind.service'])
def remove_gates():
 subprocess.run(['systemctl','disable','aionex-fr06c4-runtime-bind.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 for _,dst in SYSTEMD:
  try:dst.unlink()
  except OSError:pass
 subprocess.run(['systemctl','daemon-reload'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def stop_live(ids):
 run(['docker','stop','--time','60',*ids],180)
 if run(['docker','ps','--filter','label=com.docker.compose.project=web-dashboard','-q']).strip():raise B('application containers remained running')
 run(['systemctl','stop','docker.service','docker.socket'],120);run(['systemctl','stop','containerd.service'],120)
 if active('docker.service') or active('containerd.service'):raise B('runtime daemons remained active')
 p=subprocess.run(['pgrep','-f','containerd-shim'],capture_output=True,text=True)
 if p.returncode==0 and p.stdout.strip():raise B('containerd shims remained after daemon stop')
def register_volumes():
 for name,(typ,dev,opts) in VOLUMES.items():
  run(['docker','volume','create','--driver','local','--opt',f'type={typ}','--opt',f'device={dev}','--opt',f'o={opts}',name])
  v=json.loads(run(['docker','volume','inspect',name]))[0];o=v.get('Options') or {}
  if o.get('device')!=dev or set(str(o.get('o','')).split(','))!=set(opts.split(',')) or o.get('type')!=typ:raise B(f'external volume registration drifted: {name}')
def services_args(t):return sorted(t['services'])
def health_accept(t):
 bind=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'status','--require-ready']))
 if bind.get('validation')!='FR06C4_RUNTIME_BIND_READY':raise B('encrypted runtime bind acceptance failed')
 legacy=(
  'web-dashboard_postgres_data','web-dashboard_redis_data','web-dashboard_backup_data','web-dashboard_project_execution_data',
  'web-dashboard_three_d_asset_data','web-dashboard_course_package_data','web-dashboard_media_asset_data','web-dashboard_studio_asset_data',
  'web-dashboard_portal_asset_data','web-dashboard_mobile_release_data','web-dashboard_realtime_recording_data','web-dashboard_audio_song_ingress_data',
  'web-dashboard_security_source_data','web-dashboard_security_remediation_data')
 for volume in legacy:
  if run(['docker','ps','--filter',f'volume={volume}','-q']).strip():raise B(f'legacy authoritative volume is consumed: {volume}')
 for _ in range(60):
  try:n=topology();break
  except Exception:time.sleep(5)
 else:raise B('candidate topology health timed out')
 if set(n['services'])!=set(t['services']) or n['project_worker_scale']!=4:raise B('candidate service topology drifted')
 for u in ('http://127.0.0.1:8080/health','http://127.0.0.1:8080/ready','https://api.vip-e.net/health','https://api.vip-e.net/ready','https://ai.vip-e.net/'):
  code=run(['curl','-ksS','-o','/dev/null','-w','%{http_code}',u],30)
  if code!='200':raise B('HTTP acceptance failed')
 out=run(['docker','exec','web-dashboard-ollama-1','ollama','list'],60)
 if 'gemma3:4b' not in out:raise B('required Ollama model missing')
 return n
def rollback_internal(t):
 subprocess.run(['systemctl','stop','docker.service','docker.socket'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['systemctl','stop','containerd.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['systemctl','stop','aionex-fr06c4-runtime-bind.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'rollback'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 remove_gates();subprocess.run(['systemctl','start','containerd.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);subprocess.run(['systemctl','start','docker.socket','docker.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 time.sleep(2);ids=[r['id'] for r in t['containers']];subprocess.run(['docker','start',*ids],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def apply(a):
 p=loadplan(a.plan.resolve(),a.evidence.resolve())
 if a.confirmation!=f"EXECUTE_FR06C4_RUNTIME_CUTOVER:{p['plan_id']}" or a.confirm_production!=CONFIRM:raise B('exact runtime cutover confirmation required')
 gitgate(a.merge_sha);evidence(a.evidence.resolve(),a.merge_sha);c4gate();t=topology()
 if p['merge_sha']!=a.merge_sha or t!=p['topology']:raise B('live topology changed after planning')
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(STATE/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);bound=False
 try:
  stop_live([r['id'] for r in t['containers']]);install_gates();run(['systemctl','start','aionex-fr06c4-runtime-bind.service'],120);bound=True;run(['systemctl','start','containerd.service'],120);run(['systemctl','start','docker.socket','docker.service'],180);register_volumes()
  compose(['up','-d','--no-build','--scale','project-worker=4',*services_args(t)],1200)
  compose(['run','--rm','--no-deps','ollama-model-bootstrap'],1800)
  n=health_accept(t);body={'schema_version':1,'subpart':'FR-06C4C3B','status':'clean_encrypted_runtime_started_admission_closed','completed_at':utc(),'operation_id':p['plan_id'],'merge_sha':a.merge_sha,'running_containers':36,'unhealthy_running_containers':0,'project_worker_scale':4,'external_encrypted_volume_count':5,'historical_runtime_copy_performed':False,'legacy_runtime_underlays_retained':True,'candidate_runtime_authoritative':True,'admission_opened':False,'cloudflare_changed':False};out=STATE/'results'/f"{p['plan_id']}.json";store(out,{**body,'receipt_sha256':digest(body)});return {'status':body['status'],'result':str(out),'admission_opened':False}
 except Exception as original:
  try:rollback_internal(p['topology'])
  except Exception as rb:raise E('runtime cutover failed and rollback failed; MCP remains independent') from rb
  raise E('runtime cutover failed; legacy runtime rollback attempted') from original
 finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def rollback(a):
 private(a.receipt.resolve(),'cutover receipt');r=jread(a.receipt.resolve());body={k:v for k,v in r.items() if k!='receipt_sha256'}
 if r.get('receipt_sha256')!=digest(body) or r.get('status')!='clean_encrypted_runtime_started_admission_closed':raise B('accepted cutover receipt required')
 op=digest({'operation':'runtime-rollback','receipt':r['receipt_sha256'],'nonce':a.nonce})
 if a.confirmation!=f'ROLLBACK_FR06C4_RUNTIME:{op}' or a.confirm_production!=ROLLBACK_CONFIRM:raise B('exact rollback confirmation required')
 # The pre-cutover legacy topology is retained in the bound plan referenced by operation_id.
 plan_path=STATE/'plans'/f"{r['operation_id']}.json";private(plan_path,'original cutover plan');t=jread(plan_path)['topology'];rollback_internal(t);out=STATE/'results'/f'{op}.json';store(out,{'schema_version':1,'subpart':'FR-06C4C3B','status':'legacy_runtime_restored','completed_at':utc(),'operation_id':op,'candidate_layers_reverse_copied':False,'cloudflare_changed':False});return {'status':'legacy_runtime_restored','result':str(out)}
def parser():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);s.add_parser('inspect-runtime');q=s.add_parser('plan-cutover');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--ttl-seconds',type=int,default=600);q=s.add_parser('apply-cutover');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--plan',type=Path,required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='');q=s.add_parser('rollback');q.add_argument('--receipt',type=Path,required=True);q.add_argument('--nonce',required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='');return p
def main():
 a=parser().parse_args()
 try:o=inspect() if a.cmd=='inspect-runtime' else plan(a) if a.cmd=='plan-cutover' else apply(a) if a.cmd=='apply-cutover' else rollback(a);print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
 except Exception as e:print(json.dumps({'status':'error','reason':str(e)},sort_keys=True));return 1
if __name__=='__main__':raise SystemExit(main())
