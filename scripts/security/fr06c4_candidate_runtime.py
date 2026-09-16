#!/usr/bin/env python3
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,secrets,signal,stat,subprocess,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path('/opt/AIOS');VAULT=Path('/mnt/aionex/fr06-container-runtime-vault');DOCKER_ROOT=VAULT/'docker';CONTAINERD_ROOT=VAULT/'containerd';RUN=Path('/run/aionex-fr06c4-candidate');CD_STATE=RUN/'containerd';CD_SOCK=CD_STATE/'containerd.sock';DOCKER_SOCK=RUN/'docker.sock';DOCKER_EXEC=RUN/'docker-exec';PID=RUN/'dockerd.pid';CD_PID=RUN/'containerd.pid';STATE=Path('/var/lib/aionex/fr06c4-candidate');C4_STATE=Path('/var/lib/aionex/fr06c4-runtime');MAX_TTL=1800;MAX_USED=48*1024**3;CONFIRM='RECONSTRUCT_FR06C4_CANDIDATE_RUNTIME'
PULLS=('cloudflare/cloudflared:2026.7.0@sha256:5e49861633763e8933475477c20bae6039ed47f32c1d267a34babc347f28f0df','coturn/coturn@sha256:75e9ebd1e19005bec0c7f591d29afe22f959916ac8d9c852452f27db8c789828','livekit/egress@sha256:a3e61a70479694a5075cff3c081ab633f34d3bfa778adc6089935c96908b6550','livekit/livekit-server@sha256:d0d1cfdbe95617647bbe91630454526c2cdd88cec83f41114b3495b444918b9a','ollama/ollama@sha256:1685741456770df6e3cceb2a945a5f75e020f658d1701509668d6f4688f1dd3f','redis:7-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf','zaproxy/zap-stable:2.17.0@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef')
BUILDS=(('aionex-aios-backend:local','web-dashboard/backend','Dockerfile','project-worker',()),('aionex-aios-media-worker:local','web-dashboard/backend','Dockerfile','media-worker',()),('aionex-aios-video-provider-worker:local','web-dashboard/backend','Dockerfile','media-worker',()),('aionex-aios-image-derivative-worker:local','web-dashboard/backend','Dockerfile','image-derivative-worker',()),('aionex-aios-project-worker:local','web-dashboard/backend','Dockerfile','project-worker',()),('aionex-aios-security-tools:local','web-dashboard/backend','Dockerfile.security-tools',None,()),('aionex-aios-postgres:16-hardened','web-dashboard/docker','postgres.Dockerfile',None,()),('aionex-aios-nginx:hardened','web-dashboard/docker','nginx.Dockerfile',None,()),('web-dashboard-frontend','web-dashboard/frontend','Dockerfile',None,(('NEXT_PUBLIC_USER_PORTAL_URL','https://ai.vip-e.net'),)),('web-dashboard-portal','vip-frontend','Dockerfile',None,(('AIOS_BACKEND_ORIGIN','https://api.vip-e.net'),('NEXT_PUBLIC_API_URL','https://api.vip-e.net/api/v1'))))
class E(RuntimeError):pass
class B(E):pass
def now():return datetime.now(timezone.utc)
def utc(v=None):return (v or now()).isoformat(timespec='seconds').replace('+00:00','Z')
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def digest(v):return hashlib.sha256(canon(v)).hexdigest()
def cmd(a,timeout=120):
 r=subprocess.run(a,capture_output=True,text=True,timeout=timeout,check=False)
 if r.returncode:raise E(f'{a[0]} failed with exit code {r.returncode}; output withheld')
 return r.stdout.strip()
def gitgate(sha):
 heads=cmd(['git','-C',str(ROOT),'rev-parse','HEAD','origin/main']).splitlines()
 if heads!=[sha,sha] or cmd(['git','-C',str(ROOT),'status','--porcelain=v1']):raise B('production source is not clean exact accepted main')
def private(p,label,maxb=8*1024*1024):
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
def host_ready():
 d=json.loads(cmd(['python3',str(ROOT/'scripts/security/fr06c4_runtime_vault.py'),'status','--require-host-ready']))
 if d.get('validation')!='FR06C4_RUNTIME_VAULT_HOST_READY':raise B('runtime vault not host-ready')
 for p in (DOCKER_ROOT,CONTAINERD_ROOT):
  if not p.is_dir() or p.is_symlink():raise B('candidate runtime subpath unsafe')
 return d
def state_gate():
 for p,label,status in ((C4_STATE/'provision-receipt.json','runtime vault receipt','empty_container_runtime_vault_provisioned_admission_closed'),(C4_STATE/'recovery-proof.json','runtime recovery proof','independent_runtime_recovery_key_proved'),(C4_STATE/'header-custody.json','runtime header custody','off_host_runtime_header_verified')):
  private(p,label);d=jread(p)
  if d.get('status')!=status:raise B(f'{label} unacceptable')
def docker(a,timeout=1800):return cmd(['docker','-H',f'unix://{DOCKER_SOCK}',*a],timeout)
def wait_socket(p,proc,seconds):
 end=time.time()+seconds
 while time.time()<end:
  if proc.poll() is not None:raise E('candidate daemon exited before socket readiness')
  if p.exists():return
  time.sleep(.2)
 raise E('candidate daemon socket readiness timed out')
def _pid_alive(pid):
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False
 except PermissionError:return True
def stop_candidate():
 pids=[]
 for p in (PID,CD_PID):
  try:pids.append(int(p.read_text().strip()))
  except Exception:pass
 for pid in pids:
  try:os.kill(pid,signal.SIGTERM)
  except ProcessLookupError:pass
 for _ in range(200):
  if all(not _pid_alive(pid) for pid in pids):break
  time.sleep(.1)
 if any(_pid_alive(pid) for pid in pids):raise E('candidate daemon failed to terminate after bounded SIGTERM wait')
 for p in (DOCKER_SOCK,CD_SOCK,PID,CD_PID):
  try:p.unlink()
  except OSError:pass
 if DOCKER_SOCK.exists() or CD_SOCK.exists():raise E('candidate daemon socket remained after stop')
 return {'status':'candidate_daemons_stopped','production_daemons_changed':False,'candidate_processes_remaining':0}
def start_candidate():
 RUN.mkdir(parents=True,exist_ok=True,mode=0o700);CD_STATE.mkdir(parents=True,exist_ok=True,mode=0o700);DOCKER_EXEC.mkdir(parents=True,exist_ok=True,mode=0o700)
 if DOCKER_SOCK.exists() or CD_SOCK.exists():raise B('candidate daemon already active')
 clog=open(RUN/'containerd.log','ab',buffering=0);cp=subprocess.Popen(['containerd','--root',str(CONTAINERD_ROOT),'--state',str(CD_STATE),'--address',str(CD_SOCK),'--log-level','warn'],stdout=clog,stderr=clog,start_new_session=True);CD_PID.write_text(str(cp.pid));wait_socket(CD_SOCK,cp,30)
 dlog=open(RUN/'dockerd.log','ab',buffering=0);dp=subprocess.Popen(['dockerd','--data-root',str(DOCKER_ROOT),'--exec-root',str(DOCKER_EXEC),'--pidfile',str(PID),'-H',f'unix://{DOCKER_SOCK}','--containerd',str(CD_SOCK),'--bridge=none','--iptables=false','--ip-forward=false','--ip-masq=false','--userland-proxy=false','--storage-driver=overlayfs'],stdout=dlog,stderr=dlog,start_new_session=True);wait_socket(DOCKER_SOCK,dp,45)
 for _ in range(60):
  try:docker(['info'],30);return
  except Exception:time.sleep(.5)
 raise E('candidate Docker API readiness timed out')
def inspect():return {'schema_version':1,'subpart':'FR-06C4C3A','observed_at':utc(),'host_ready':host_ready()['validation'],'live_docker_active':active('docker.service'),'live_containerd_active':active('containerd.service'),'candidate_docker_socket':DOCKER_SOCK.exists(),'candidate_containerd_socket':CD_SOCK.exists(),'production_changed':False}
def evidence(p,sha):
 private(p,'candidate evidence');d=jread(p);src=d.get('source') or {}
 if d.get('schema_version')!=1 or d.get('subpart')!='FR-06C4C3A' or d.get('environment')!='production' or d.get('production_authorization') is not True:raise B('candidate evidence metadata invalid')
 if src.get('merge_sha')!=sha or src.get('protected_pr_checks_passed') is not True or src.get('post_merge_main_checks_passed') is not True:raise B('candidate source CI evidence incomplete')
 return d
def plan(a):
 if os.geteuid()!=0:raise B('root required')
 gitgate(a.merge_sha);e=evidence(a.evidence.resolve(),a.merge_sha);state_gate();host_ready()
 if not active('docker.service') or not active('containerd.service'):raise B('live Docker/containerd must remain active')
 if DOCKER_SOCK.exists() or CD_SOCK.exists() or (STATE/'accepted.json').exists():raise B('candidate already active or accepted')
 if not 1<=a.ttl_seconds<=MAX_TTL:raise B('plan TTL invalid')
 t=now();body={'schema_version':1,'subpart':'FR-06C4C3A','operation':'candidate-reconstruction','created_at':utc(t),'expires_at':utc(t+timedelta(seconds=a.ttl_seconds)),'merge_sha':a.merge_sha,'evidence_sha256':hashlib.sha256(a.evidence.resolve().read_bytes()).hexdigest(),'nonce':secrets.token_hex(32),'authority_count':17,'historical_runtime_copy_permitted':False,'live_daemon_stop_permitted':False};body['plan_id']=digest(body);p=STATE/'plans'/f"{body['plan_id']}.json";store(p,body);return {'status':'candidate_reconstruction_plan_ready','plan_id':body['plan_id'],'plan':str(p),'production_executed':False}
def loadplan(p,e):
 private(p,'candidate plan');d=jread(p);pid=d.get('plan_id')
 if not isinstance(pid,str) or digest({k:v for k,v in d.items() if k!='plan_id'})!=pid:raise B('plan digest invalid')
 if now()>datetime.fromisoformat(d['expires_at'].replace('Z','+00:00')):raise B('plan expired')
 if d['evidence_sha256']!=hashlib.sha256(e.read_bytes()).hexdigest():raise B('evidence changed after planning')
 return d
def build_one(tag,context,dockerfile,target,args):
 argv=['build','--network','host','--pull','-f',str(ROOT/context/dockerfile),'-t',tag]
 if target:argv+=['--target',target]
 for k,v in args:argv+=['--build-arg',f'{k}={v}']
 argv.append(str(ROOT/context));docker(argv,3600)
def reconstruct(a):
 p=loadplan(a.plan.resolve(),a.evidence.resolve())
 if a.confirmation!=f"EXECUTE_FR06C4_CANDIDATE_RECONSTRUCTION:{p['plan_id']}" or a.confirm_production!=CONFIRM:raise B('exact candidate reconstruction confirmation required')
 gitgate(a.merge_sha);evidence(a.evidence.resolve(),a.merge_sha);state_gate();host_ready()
 if p['merge_sha']!=a.merge_sha or not active('docker.service') or not active('containerd.service'):raise B('source or live runtime changed')
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(STATE/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try:
  start_candidate()
  if docker(['ps','-aq'],30).strip():raise B('candidate contains containers before reconstruction')
  for ref in PULLS:docker(['pull',ref],1800)
  for row in BUILDS:build_one(*row)
  if docker(['ps','-aq'],30).strip():raise B('candidate reconstruction left containers behind')
  docker(['builder','prune','-af'],900)
  docker(['image','prune','-f'],300)
  rows=[]
  for ref in [x[0] for x in BUILDS]+list(PULLS):
   v=json.loads(docker(['image','inspect',ref],60));
   if not isinstance(v,list) or len(v)!=1:raise B('candidate image inspect incomplete')
   item=v[0];iid=str(item.get('Id',''));size=int(item.get('Size',0))
   if '@sha256:' in ref and iid!='sha256:'+ref.rsplit('@sha256:',1)[1]:raise B('external image digest mismatch')
   rows.append({'authority':ref,'image_id':iid,'size_bytes':size})
  used=sum(p.stat().st_size for p in VAULT.rglob('*') if p.is_file())
  if used>MAX_USED:raise B('candidate runtime exceeded capacity ceiling')
  body={'schema_version':1,'subpart':'FR-06C4C3A','status':'isolated_candidate_runtime_reconstruction_accepted','completed_at':utc(),'merge_sha':a.merge_sha,'authority_count':17,'images':rows,'candidate_used_file_bytes':used,'application_container_count':0,'historical_runtime_copy_performed':False,'live_docker_remained_active':active('docker.service'),'live_containerd_remained_active':active('containerd.service'),'admission_opened':False,'cloudflare_changed':False}
  if not body['live_docker_remained_active'] or not body['live_containerd_remained_active']:raise B('live runtime changed during reconstruction')
  store(STATE/'accepted.json',body);return {'status':body['status'],'receipt':str(STATE/'accepted.json'),'authority_count':17,'production_cutover_executed':False}
 finally:
  stop_candidate();fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def parser():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);s.add_parser('inspect');s.add_parser('stop-candidate');q=s.add_parser('plan');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--ttl-seconds',type=int,default=1200);q=s.add_parser('reconstruct');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--plan',type=Path,required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='');return p
def main():
 a=parser().parse_args()
 try:o=inspect() if a.cmd=='inspect' else stop_candidate() if a.cmd=='stop-candidate' else plan(a) if a.cmd=='plan' else reconstruct(a);print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
 except Exception as e:print(json.dumps({'status':'error','reason':type(e).__name__},sort_keys=True));return 1
if __name__=='__main__':raise SystemExit(main())
