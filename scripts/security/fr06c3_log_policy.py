#!/usr/bin/env python3
"""Guarded FR-06C3E activation of volatile host logging.

Source merge is inert. Production apply is single-use, evidence-bound and
rollback-capable. No Redis data or application admission is modified here.
"""
from __future__ import annotations
import argparse, fcntl, hashlib, json, os, secrets, shutil, stat, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PRODUCTION_ROOT=Path('/opt/AIOS')
STATE_ROOT=Path('/var/lib/aionex/fr06c3-log-policy')
C3_STATE=Path('/var/lib/aionex/fr06c3')
REDIS_CLOSEOUT=C3_STATE/'c3e-redis-closeout.json'
SOURCE_MOUNT=PRODUCTION_ROOT/'deploy/systemd/var-log.mount'
SOURCE_JOURNAL=PRODUCTION_ROOT/'deploy/systemd/journald.conf.d/30-aionex-fr06-volatile.conf'
TARGET_MOUNT=Path('/etc/systemd/system/var-log.mount')
TARGET_JOURNAL=Path('/etc/systemd/journald.conf.d/30-aionex-fr06-volatile.conf')
MAX_PLAN_TTL_SECONDS=900
MAX_EVIDENCE_AGE_SECONDS=3600
MAX_WINDOW_SECONDS=4*60*60
APPLY_CONFIRMATION='FR06C3_PRODUCTION_VOLATILE_LOG_CUTOVER'
ROLLBACK_CONFIRMATION='FR06C3_PRODUCTION_VOLATILE_LOG_ROLLBACK'
SENSITIVE_KEYS={'key','private_key','recovery_key','secret','secret_key','token','passphrase','password'}
DIRECT_LOG_SERVICES=('rsyslog.service','fail2ban.service','unattended-upgrades.service')
ALLOWED_PRECUTOVER_LOG_HOLDER_COMMS={'systemd-journal','rsyslogd','fail2ban-server','unattended-upgr'}

class PolicyError(RuntimeError): pass
class PolicyBlocked(PolicyError): pass

def _now()->datetime:return datetime.now(timezone.utc)
def _utc(v:datetime|None=None)->str:return (v or _now()).isoformat(timespec='seconds').replace('+00:00','Z')
def _canonical(v:Any)->bytes:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def _digest(v:Any)->str:return hashlib.sha256(_canonical(v)).hexdigest()
def _sha(path:Path)->str:
    h=hashlib.sha256(); fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        with os.fdopen(fd,'rb',closefd=False) as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    finally:os.close(fd)
    return h.hexdigest()
def _run(argv:list[str],timeout:int=120)->str:
    try:r=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,check=False)
    except (OSError,subprocess.SubprocessError) as exc:raise PolicyError(f'command unavailable or timed out: {argv[0]}') from exc
    if r.returncode!=0:raise PolicyError(f'{argv[0]} failed with exit code {r.returncode}; output withheld')
    return r.stdout.strip()
def _json(path:Path)->dict[str,Any]:
    try:v=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as exc:raise PolicyError(f'cannot read JSON: {path}') from exc
    if not isinstance(v,dict):raise PolicyError('JSON object required')
    return v
def _private(path:Path,label:str,maximum:int=8*1024*1024)->os.stat_result:
    try:i=os.lstat(path)
    except OSError as exc:raise PolicyBlocked(f'{label} unavailable') from exc
    if stat.S_ISLNK(i.st_mode) or not stat.S_ISREG(i.st_mode) or i.st_nlink!=1:raise PolicyBlocked(f'{label} must be single-link regular')
    if i.st_uid!=0 or stat.S_IMODE(i.st_mode)&0o077 or not 1<=i.st_size<=maximum:raise PolicyBlocked(f'{label} ownership/mode/size unsafe')
    return i
def _parse(v:Any,label:str)->datetime:
    if not isinstance(v,str) or not v.endswith('Z'):raise PolicyBlocked(f'{label} must be RFC3339 UTC Z')
    try:return datetime.fromisoformat(v[:-1]+'+00:00').astimezone(timezone.utc)
    except ValueError as exc:raise PolicyBlocked(f'{label} invalid') from exc
def _walk(v:Any,path:str='$')->None:
    if isinstance(v,dict):
        for k,c in v.items():
            n=str(k).casefold().replace('-','_')
            if n in SENSITIVE_KEYS or n.endswith('_key_material'):raise PolicyBlocked(f'embedded secret material rejected at {path}.{k}')
            _walk(c,f'{path}.{k}')
    elif isinstance(v,list):
        for i,c in enumerate(v):_walk(c,f'{path}[{i}]')
def _git_gate(root:Path,sha:str)->None:
    heads=_run(['git','-C',str(root),'rev-parse','HEAD','origin/main']).splitlines()
    if heads!=[sha,sha] or _run(['git','-C',str(root),'status','--porcelain=v1']):raise PolicyBlocked('production source is not clean exact accepted main')
def _source_policy()->dict[str,str]:
    for p in (SOURCE_MOUNT,SOURCE_JOURNAL):
        if not p.is_file():raise PolicyBlocked(f'repository policy source missing: {p.name}')
    mt=SOURCE_MOUNT.read_text(); jt=SOURCE_JOURNAL.read_text()
    for required in ('What=tmpfs','Where=/var/log','Options=mode=0755,nodev,nosuid,noexec,size=1G'):
        if required not in mt:raise PolicyBlocked('repository var-log.mount drifted')
    if 'Storage=volatile' not in jt:raise PolicyBlocked('repository journald policy drifted')
    return {'mount_sha256':_sha(SOURCE_MOUNT),'journal_sha256':_sha(SOURCE_JOURNAL)}
def _service_active(name:str)->bool:
    return subprocess.run(['systemctl','is-active','--quiet',name],check=False).returncode==0
def _log_fd_holders()->list[dict[str,Any]]:
    rows=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            comm=(proc/'comm').read_text(encoding='utf-8').strip()
            for fd in (proc/'fd').iterdir():
                try:target=os.readlink(fd)
                except OSError:continue
                if not (target=='/var/log' or target.startswith('/var/log/')):continue
                try:device=os.stat(fd).st_dev
                except OSError:continue
                rows.append({'pid':int(proc.name),'comm':comm,'fd':fd.name,'target':target,'device':int(device)})
        except (OSError,PermissionError):continue
    return rows
def _require_known_log_holders()->list[dict[str,Any]]:
    rows=_log_fd_holders();unknown=sorted({r['comm'] for r in rows if r['comm'] not in ALLOWED_PRECUTOVER_LOG_HOLDER_COMMS})
    if unknown:raise PolicyBlocked('unknown direct /var/log holder(s): '+','.join(unknown))
    inactive=[name for name in DIRECT_LOG_SERVICES if not _service_active(name)]
    if inactive:raise PolicyBlocked('required direct log service is not active: '+','.join(inactive))
    return rows
def _hidden_underlay_holders()->list[dict[str,Any]]:
    current_dev=os.stat('/var/log').st_dev
    return [r for r in _log_fd_holders() if r['device']!=current_dev]
def _evidence(path:Path,sha:str)->dict[str,Any]:
    p=path.resolve(strict=True);_private(p,'policy evidence');v=_json(p);_walk(v)
    if v.get('schema_version')!=1 or v.get('subpart')!='FR-06C3E' or v.get('environment')!='production' or v.get('production_authorization') is not True:raise PolicyBlocked('policy evidence metadata invalid')
    now=_now();age=(now-_parse(v.get('observed_at'),'observed_at')).total_seconds()
    if age< -300 or age>MAX_EVIDENCE_AGE_SECONDS:raise PolicyBlocked('policy evidence stale/future-dated')
    src=v.get('source')
    if not isinstance(src,dict) or src.get('merge_sha')!=sha or src.get('protected_pr_checks_passed') is not True or src.get('post_merge_main_checks_passed') is not True:raise PolicyBlocked('source CI evidence incomplete')
    a=v.get('approvals')
    if not isinstance(a,dict) or a.get('owner_authorized') is not True:raise PolicyBlocked('owner authorization missing')
    start=_parse(a.get('window_starts_at'),'window start');end=_parse(a.get('window_ends_at'),'window end')
    if end<=start or (end-start).total_seconds()>MAX_WINDOW_SECONDS or not start<=now<=end:raise PolicyBlocked('maintenance window invalid/inactive')
    return v
def _c3_gate(root:Path)->str:
    _private(REDIS_CLOSEOUT,'C3E Redis closeout');d=_json(REDIS_CLOSEOUT)
    if d.get('status')!='redis_cutover_accepted' or d.get('legacy_aof_copied') is not False:raise PolicyBlocked('accepted Redis closeout missing')
    raw=_run(['python3',str(root/'scripts/security/fr06c3_vault_provision.py'),'status','--require-host-ready'])
    try:s=json.loads(raw)
    except json.JSONDecodeError as exc:raise PolicyBlocked('C3 host-ready status invalid') from exc
    if s.get('validation')!='FR06C3_VAULTS_HOST_READY':raise PolicyBlocked('C3 host vaults not ready')
    return _sha(REDIS_CLOSEOUT)
def _fstype()->str:return _run(['findmnt','-n','-o','FSTYPE','--target','/var/log'])
def inspect()->dict[str,Any]:
    enabled=subprocess.run(['systemctl','is-enabled','var-log.mount'],capture_output=True,text=True,check=False).stdout.strip()
    holders=_log_fd_holders()
    return {'schema_version':1,'subpart':'FR-06C3E','observed_at':_utc(),'var_log_fstype':_fstype(),'var_log_mount_enabled':enabled,'direct_log_services':{name:('active' if _service_active(name) else 'inactive') for name in DIRECT_LOG_SERVICES},'direct_log_holder_count':len(holders),'direct_log_holder_comms':sorted({r['comm'] for r in holders}),'repository_policy':_source_policy(),'read_only_inspection':True,'production_changed':False}
def _store(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:os.write(fd,json.dumps(value,sort_keys=True,indent=2).encode()+b'\n');os.fsync(fd)
    finally:os.close(fd)
def _lock()->int:
    STATE_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(STATE_ROOT/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as exc:os.close(fd);raise PolicyBlocked('another log-policy operation holds lock') from exc
    return fd
def plan(args:argparse.Namespace)->dict[str,Any]:
    root=args.root.resolve()
    if os.geteuid()!=0 or root!=PRODUCTION_ROOT:raise PolicyBlocked('production log policy requires root and /opt/AIOS')
    if not 1<=args.ttl_seconds<=MAX_PLAN_TTL_SECONDS:raise PolicyBlocked('plan TTL outside bounded range')
    _git_gate(root,args.merge_sha);_evidence(args.evidence.resolve(),args.merge_sha);src=_source_policy();closeout=_c3_gate(root);holders=_require_known_log_holders()
    if _fstype()=='tmpfs':raise PolicyBlocked('/var/log is already tmpfs')
    now=_now();body={'schema_version':1,'subpart':'FR-06C3E','operation':'volatile-log-cutover','created_at':_utc(now),'expires_at':_utc(now+timedelta(seconds=args.ttl_seconds)),'nonce':secrets.token_hex(32),'merge_sha':args.merge_sha,'evidence_sha256':_sha(args.evidence.resolve()),'redis_closeout_sha256':closeout,**src,'prior_var_log_fstype':_fstype(),'managed_direct_log_services':list(DIRECT_LOG_SERVICES),'precutover_holder_count':len(holders),'precutover_holder_comms':sorted({r['comm'] for r in holders}),'cloudflare_change_permitted':False,'admission_opened':False};body['plan_id']=_digest(body);p=STATE_ROOT/'plans'/f"{body['plan_id']}.json";_store(p,body);return {'decision':'volatile_log_plan_ready','plan_id':body['plan_id'],'plan':str(p),'production_executed':False}
def _load_plan(path:Path,evidence:Path)->dict[str,Any]:
    _private(path,'log policy plan');v=_json(path);pid=v.get('plan_id')
    if not isinstance(pid,str) or _digest({k:x for k,x in v.items() if k!='plan_id'})!=pid:raise PolicyBlocked('plan digest mismatch')
    if v.get('subpart')!='FR-06C3E' or v.get('operation')!='volatile-log-cutover':raise PolicyBlocked('plan scope invalid')
    if _now()>_parse(v.get('expires_at'),'plan expiry'):raise PolicyBlocked('plan expired')
    if v.get('evidence_sha256')!=_sha(evidence.resolve()):raise PolicyBlocked('evidence changed after planning')
    return v
def _atomic_install(source:Path,target:Path,mode:int)->None:
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o755);tmp=target.parent/(target.name+'.aionex-new')
    if tmp.exists():tmp.unlink()
    shutil.copyfile(source,tmp);os.chmod(tmp,mode);os.replace(tmp,target)
def _remove_if_exact(path:Path,wanted_sha:str)->None:
    if path.exists() and not path.is_symlink() and path.is_file() and _sha(path)==wanted_sha:path.unlink()
def _verify_live()->dict[str,Any]:
    if _fstype()!='tmpfs':raise PolicyBlocked('/var/log is not tmpfs after activation')
    opts=set(_run(['findmnt','-n','-o','OPTIONS','--target','/var/log']).split(','))
    if not {'nodev','nosuid','noexec'}.issubset(opts):raise PolicyBlocked('/var/log mount options drifted')
    if not _service_active('systemd-journald.service'):raise PolicyBlocked('journald did not return active')
    inactive=[name for name in DIRECT_LOG_SERVICES if not _service_active(name)]
    if inactive:raise PolicyBlocked('direct log service did not return active: '+','.join(inactive))
    if subprocess.run(['systemctl','is-enabled','var-log.mount'],capture_output=True,text=True,check=False).stdout.strip() not in {'enabled','static'}:raise PolicyBlocked('var-log.mount is not enabled')
    cat=_run(['systemd-analyze','cat-config','systemd/journald.conf'])
    if 'Storage=volatile' not in cat:raise PolicyBlocked('journald volatile drop-in not effective')
    hidden=_hidden_underlay_holders()
    if hidden:raise PolicyBlocked('process still holds plaintext /var/log underlay after activation')
    return {'validation':'FR06C3_VOLATILE_LOG_RUNTIME_READY','var_log_fstype':'tmpfs','mount_options':sorted(opts),'direct_log_services_active':list(DIRECT_LOG_SERVICES),'hidden_underlay_fd_count':0,'journald_storage':'volatile'}
def _rollback_installed(src:dict[str,str])->None:
    for service in DIRECT_LOG_SERVICES:subprocess.run(['systemctl','stop',service],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    subprocess.run(['systemctl','disable','var-log.mount'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    subprocess.run(['systemctl','stop','var-log.mount'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    _remove_if_exact(TARGET_MOUNT,src['mount_sha256']);_remove_if_exact(TARGET_JOURNAL,src['journal_sha256'])
    subprocess.run(['systemctl','daemon-reload'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    subprocess.run(['systemctl','restart','systemd-journald.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    for service in DIRECT_LOG_SERVICES:subprocess.run(['systemctl','start',service],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
def apply(args:argparse.Namespace)->dict[str,Any]:
    p=_load_plan(args.plan.resolve(),args.evidence.resolve())
    if args.confirmation!=f"EXECUTE_FR06C3_VOLATILE_LOG_CUTOVER:{p['plan_id']}" or args.confirm_production!=APPLY_CONFIRMATION:raise PolicyBlocked('exact production log-policy confirmation required')
    root=args.root.resolve();_git_gate(root,args.merge_sha);_evidence(args.evidence.resolve(),args.merge_sha);src=_source_policy();closeout=_c3_gate(root);_require_known_log_holders()
    if p.get('merge_sha')!=args.merge_sha or p.get('redis_closeout_sha256')!=closeout or p.get('mount_sha256')!=src['mount_sha256'] or p.get('journal_sha256')!=src['journal_sha256'] or p.get('managed_direct_log_services')!=list(DIRECT_LOG_SERVICES):raise PolicyBlocked('plan-bound source/state changed')
    reservation=STATE_ROOT/'reservations'/f"{p['plan_id']}.json"
    if reservation.exists():raise PolicyBlocked('plan already consumed')
    fd=_lock();_store(reservation,{'plan_id':p['plan_id'],'reserved_at':_utc()})
    try:
        for service in DIRECT_LOG_SERVICES:_run(['systemctl','stop',service])
        _atomic_install(SOURCE_JOURNAL,TARGET_JOURNAL,0o644);_atomic_install(SOURCE_MOUNT,TARGET_MOUNT,0o644)
        _run(['systemctl','daemon-reload']);_run(['systemctl','enable','var-log.mount']);_run(['systemctl','start','var-log.mount'])
        _run(['systemctl','restart','systemd-journald.service']);_run(['systemd-tmpfiles','--create','--prefix=/var/log'])
        if _hidden_underlay_holders():raise PolicyBlocked('plaintext /var/log underlay still has open file descriptors after journald restart')
        for service in DIRECT_LOG_SERVICES:_run(['systemctl','start',service])
        runtime=_verify_live()
        body={'schema_version':1,'subpart':'FR-06C3E','operation':'volatile-log-cutover','operation_id':p['plan_id'],'status':'volatile_log_boundary_active','completed_at':_utc(),'merge_sha':args.merge_sha,'runtime':runtime,'plaintext_underlay_retained_for_rollback':True,'secure_erase_claimed':False,'admission_opened':False,'cloudflare_changed':False,'production_execution':True};result=dict(body);result['receipt_sha256']=_digest(body);out=STATE_ROOT/'results'/f"{p['plan_id']}.json";_store(out,result);return {'status':body['status'],'result':str(out),'validation':runtime['validation']}
    except Exception as exc:
        _rollback_installed(src);raise PolicyError('volatile log activation failed; legacy log path restoration attempted') from exc
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def rollback(args:argparse.Namespace)->dict[str,Any]:
    _private(args.receipt.resolve(),'log cutover receipt');r=_json(args.receipt.resolve());body={k:v for k,v in r.items() if k!='receipt_sha256'}
    if r.get('receipt_sha256')!=_digest(body) or r.get('status')!='volatile_log_boundary_active':raise PolicyBlocked('successful log cutover receipt required')
    op=_digest({'operation':'volatile-log-rollback','receipt':r['receipt_sha256'],'nonce':args.nonce})
    if args.confirmation!=f'ROLLBACK_FR06C3_VOLATILE_LOG:{op}' or args.confirm_production!=ROLLBACK_CONFIRMATION:raise PolicyBlocked('exact rollback confirmation required')
    src=_source_policy();fd=_lock()
    try:_rollback_installed(src);out=STATE_ROOT/'results'/f'{op}.json';_store(out,{'schema_version':1,'subpart':'FR-06C3E','operation':'volatile-log-rollback','operation_id':op,'status':'legacy_log_path_restored','completed_at':_utc(),'secure_erase_claimed':False,'cloudflare_changed':False});return {'status':'legacy_log_path_restored','result':str(out)}
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    s.add_parser('inspect-runtime')
    pl=s.add_parser('plan');pl.add_argument('--root',type=Path,default=PRODUCTION_ROOT);pl.add_argument('--merge-sha',required=True);pl.add_argument('--evidence',type=Path,required=True);pl.add_argument('--ttl-seconds',type=int,default=600)
    ap=s.add_parser('apply');ap.add_argument('--root',type=Path,default=PRODUCTION_ROOT);ap.add_argument('--merge-sha',required=True);ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--confirmation',required=True);ap.add_argument('--confirm-production',default='')
    rb=s.add_parser('rollback');rb.add_argument('--receipt',type=Path,required=True);rb.add_argument('--nonce',required=True);rb.add_argument('--confirmation',required=True);rb.add_argument('--confirm-production',default='')
    return p
def main()->int:
    a=parser().parse_args()
    try:
        if a.command=='inspect-runtime':v=inspect()
        elif a.command=='plan':v=plan(a)
        elif a.command=='apply':v=apply(a)
        else:v=rollback(a)
        print(json.dumps(v,sort_keys=True));return 0
    except PolicyBlocked as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
    except PolicyError as e:print(json.dumps({'status':'error','reason':str(e)},sort_keys=True));return 1
if __name__=='__main__':raise SystemExit(main())
