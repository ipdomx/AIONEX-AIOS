#!/usr/bin/env python3
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,secrets,shutil,stat,subprocess,time
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any
ROOT=Path('/opt/AIOS');DASH=ROOT/'web-dashboard';STATE=Path('/var/lib/aionex/fr06c5-cutover');C5=Path('/var/lib/aionex/fr06c5-host-state');BOOT=Path('/var/lib/aionex/fr06c5-bootstrap');MOUNT=Path('/mnt/aionex/fr06-host-state-vault');MAX_TTL=900;MAX_AGE=3600;CONFIRM='FR06C5_PRODUCTION_HOST_STATE_CUTOVER'
SYSTEMD=((ROOT/'deploy/systemd/aionex-fr06c5-host-state-bind.service',Path('/etc/systemd/system/aionex-fr06c5-host-state-bind.service')),(ROOT/'deploy/systemd/docker.service.d/34-aionex-fr06c5-host-state-gate.conf',Path('/etc/systemd/system/docker.service.d/34-aionex-fr06c5-host-state-gate.conf')))
WRAPPERS=tuple((ROOT/'deploy/bin'/n,Path('/usr/local/sbin')/n) for n in ('aionex-phase22c-2-tunnel','aionex-phase22c-tunnel','trendbost-mcp-bridge-tunnel'))
PATHS=(('operator',Path('/root/.config/aionex'),MOUNT/'operator-state',False),('app-secrets',ROOT/'web-dashboard/secrets',MOUNT/'app-secrets',False),('deploy-key',Path('/root/.ssh/aionex_aios_deploy'),MOUNT/'ssh/aionex_aios_deploy',True),('cpanel-key',Path('/root/.ssh/aionex_cpanel_ai_vip_e_net_ed25519'),MOUNT/'ssh/aionex_cpanel_ai_vip_e_net_ed25519',True))
TUNNELS=('aionex-phase22c-2-tunnel.service','aionex-phase22c-tunnel.service','trendbost-mcp-bridge-tunnel.service')
PROC = Path('/proc')
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
def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _ensure_directory(path):
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        _fsync_directory(directory.parent)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise B('journal directory is not a real directory')


def _write_all(fd, data):
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise E('journal write made no progress')
        remaining = remaining[written:]


def store(p, v):
    _ensure_directory(p.parent)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        _write_all(fd, json.dumps(v, sort_keys=True, indent=2).encode() + b'\n')
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(p.parent)


def atomic_store(p, v):
    _ensure_directory(p.parent)
    temporary = p.parent / (p.name + '.aionex-new-' + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        _write_all(fd, json.dumps(v, sort_keys=True, indent=2).encode() + b'\n')
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(temporary, p)
        _fsync_directory(p.parent)
    finally:
        if fd is not None:
            os.close(fd)
        if temporary.exists():
            temporary.unlink()


def attempt_path(plan_id):
    if not isinstance(plan_id, str) or len(plan_id) != 64 or any(c not in '0123456789abcdef' for c in plan_id):
        raise B('attempt plan identifier is invalid')
    return STATE / 'attempts' / (plan_id + '.json')


def update_attempt(path, **changes):
    forbidden = {'schema_version', 'subpart', 'plan_id', 'merge_sha', 'plan', 'topology',
                 'boot_id', 'resource_snapshot_sha256', 'created_at'}
    if forbidden.intersection(changes):
        raise B('attempt authority cannot change')
    record = jread(path)
    if record.get('candidate_start_attempted') is True and changes.get('candidate_start_attempted') is False:
        raise B('candidate-start barrier cannot be cleared')
    record.update(changes)
    record['updated_at'] = utc()
    atomic_store(path, record)
    return record


def unresolved_attempt_gate():
    directory = STATE / 'attempts'
    if not os.path.lexists(directory):
        return
    if directory.is_symlink() or not directory.is_dir():
        raise B('attempt directory requires reconciliation')
    for path in sorted(directory.iterdir()):
        if path.suffix != '.json':
            raise B('unfinished journal artifact requires reconciliation')
        private(path, 'prior attempt')
        record = jread(path)
        plan_record = record.get('plan') or {}
        plan_id = record.get('plan_id')
        authority_valid = (
            record.get('schema_version') == 2
            and record.get('subpart') == 'FR-06C5D'
            and path == attempt_path(plan_id)
            and plan_record.get('plan_id') == plan_id
            and digest({k: v for k, v in plan_record.items() if k != 'plan_id'}) == plan_id
            and record.get('merge_sha') == plan_record.get('merge_sha')
            and record.get('topology') == plan_record.get('topology')
            and record.get('resource_snapshot_sha256') == digest(plan_record.get('resource_snapshot'))
        )
        if not authority_valid:
            raise B('prior host-state attempt authority requires reconciliation')
        if record.get('candidate_start_attempted') is not False:
            raise B('prior candidate start remains an irreversible replay barrier')
        phase = record.get('phase')
        safe_terminal = phase == 'failed_before_live_mutation' or (
            phase == 'legacy_restored_prestart' and record.get('rollback_verified') is True
        )
        if not safe_terminal:
            raise B('prior host-state cutover attempt requires reconciliation')


@contextmanager
def operation_lock():
    _ensure_directory(STATE)
    fd = os.open(STATE / 'operation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    locked = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
            raise B('operation lock metadata is unsafe')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise B('another host-state operation holds the lock') from exc
        locked = True
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()

def parsez(v,label):
 if not isinstance(v,str) or not v.endswith('Z'):raise B(f'{label} must be UTC Z')
 try:return datetime.fromisoformat(v[:-1]+'+00:00').astimezone(timezone.utc)
 except ValueError as x:raise B(f'{label} invalid') from x
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def digest(v):return hashlib.sha256(canon(v)).hexdigest()
def gitgate(sha):
 heads=run(['git','-C',str(ROOT),'rev-parse','HEAD','origin/main']).splitlines()
 if heads!=[sha,sha] or run(['git','-C',str(ROOT),'status','--porcelain=v1']):raise B('production source is not clean exact accepted main')
def topology(require_healthy=True,deadline=None):
 def docker(args):
  budget=30 if deadline is None else min(30,deadline-time.monotonic())
  if budget<=0:raise B('container health timeout')
  return run(['docker',*args],budget)
 ids=[x.strip() for x in docker(['ps','--no-trunc','--format','{{.ID}}']).splitlines() if x.strip()]
 if len(ids)!=36 or len(set(ids))!=36:raise B('running container count or identity is not exact 36')
 inspected=json.loads(docker(['inspect',*ids]))
 if not isinstance(inspected,list) or len(inspected)!=36:raise B('container inspection set is incomplete')
 by_id={d.get('Id'):d for d in inspected if isinstance(d,dict)}
 if len(by_id)!=36 or set(by_id)!=set(ids):raise B('container inspection identities differ from running set')
 rows=[]
 for cid in ids:
  d=by_id[cid];config=d.get('Config') or {};labels=config.get('Labels') or {};service=labels.get('com.docker.compose.service');project=labels.get('com.docker.compose.project');state=d.get('State') or {};name=str(d.get('Name','')).lstrip('/')
  if project!='web-dashboard' or not service or not name:raise B('live topology is not exact web-dashboard set')
  if state.get('Running') is not True or state.get('Paused') is True or state.get('Restarting') is True or state.get('Status')!='running':raise B('container is not stably running')
  test=(config.get('Healthcheck') or {}).get('Test') or [];has_healthcheck=bool(test) and test[0]!='NONE'
  health=str((state.get('Health') or {}).get('Status') or ('starting' if has_healthcheck else 'none'))
  if has_healthcheck and health=='none':health='starting'
  if health not in {'healthy','none','starting','unhealthy'}:raise B('container health state is invalid')
  if require_healthy and health not in {'healthy','none'}:raise B('live container health is not ready')
  rows.append({'id':cid,'name':name,'service':service,'health':health,'restart':current_restart(cid,d)})
 if len({r['name'] for r in rows})!=36:raise B('container names are not unique')
 services={}
 for row in rows:services.setdefault(row['service'],[]).append(row['id'])
 if len(services.get('project-worker',[]))!=4:raise B('project-worker scale drifted')
 return {'containers':sorted(rows,key=lambda x:x['name']),'services':{k:sorted(v) for k,v in sorted(services.items())},'container_count':36,'project_worker_scale':4}
def bind_unit_preflight():
    raw = run([
        'systemctl', 'show', 'aionex-fr06c5-host-state-bind.service',
        '--property=LoadState', '--property=ActiveState', '--property=SubState',
        '--property=FragmentPath', '--property=DropInPaths', '--property=Job', '--no-pager',
    ])
    properties = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    expected = {'LoadState': 'not-found', 'ActiveState': 'inactive', 'SubState': 'dead',
                'FragmentPath': '', 'DropInPaths': '', 'Job': ''}
    if properties != expected:
        raise B('preexisting or pending host-state bind unit requires reconciliation')

def c5gate():
 bind_unit_preflight()
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
def _mount_rows(target=None):
 args=['findmnt','--kernel','--json','--output','ID,TARGET,SOURCE,FSROOT,MAJ:MIN,OPTIONS']
 args+=['--target',str(target)] if target is not None else ['--list']
 rows=json.loads(run(args)).get('filesystems',[])
 if not isinstance(rows,list) or not rows:raise B('mount inventory unavailable')
 out=[]
 for row in rows:
  if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k] for k in ('target','source','fsroot','maj:min','options')):raise B('mount identity unavailable')
  out.append({'id':int(row['id']),'target':row['target'],'source':row['source'],'fsroot':row['fsroot'],'device':row['maj:min'],'options':sorted(row['options'].split(','))})
 return out
def _mount_at(path):
 rows=_mount_rows(path)
 if len(rows)!=1:raise B('visible mount identity ambiguous')
 return rows[0]
def _mount_owner(row):
 return {k:row[k] for k in ('id','target','fsroot','device')}
def _exists(path):return os.path.lexists(path)
def _identity(path,content=False,link=False):
 s=os.lstat(path)
 if link:
  if not stat.S_ISLNK(s.st_mode):raise B('owned enable link type changed')
 elif stat.S_ISLNK(s.st_mode) or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):raise B('resource type unsafe')
 if not stat.S_ISDIR(s.st_mode) and s.st_nlink!=1:raise B('resource link count unsafe')
 value={'dev':s.st_dev,'ino':s.st_ino,'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'type':stat.S_IFMT(s.st_mode)}
 if not stat.S_ISDIR(s.st_mode):value['nlink']=s.st_nlink
 if link:value['target']=os.readlink(path)
 if content:
  if not stat.S_ISREG(s.st_mode):raise B('gate is not a regular file')
  value.update(size=s.st_size,sha256=fsha(path))
 return value
def _boot_id():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def _enable_links():
 unit=SYSTEMD[0][1]
 return ((unit.parent/'multi-user.target.wants'/unit.name,unit),)
def _unexpected_unit_links():
 unit=SYSTEMD[0][1];expected={str(p) for p,_ in _enable_links()};found=[]
 # Include runtime enablement and aliases, without asking systemctl to remove them.
 roots={unit.parent,Path('/run/systemd/system')}
 for root in roots:
  if not root.is_dir():continue
  for p in root.rglob('*'):
   if not p.is_symlink():continue
   target=os.readlink(p)
   if (p.name==unit.name or Path(target).name==unit.name) and str(p) not in expected:found.append(str(p))
 return found
def mount_targets():return [row['target'] for row in _mount_rows()]
def _candidate_paths_safe():
 if not stat.S_ISDIR(_identity(MOUNT)['type']) or _mount_at(MOUNT)['target']!=str(MOUNT):raise B('candidate vault root is not an exact directory mount')
 for _,_,candidate,isfile in PATHS:
  try:parts=candidate.relative_to(MOUNT).parts
  except ValueError as x:raise B('candidate escaped fixed vault root') from x
  current=MOUNT
  for index,part in enumerate(parts):
   current=current/part;last=index==len(parts)-1
   if not _exists(current):
    if last and isfile:continue
    raise B('candidate parent directory unavailable')
   identity=_identity(current)
   if last and isfile:
    if not stat.S_ISREG(identity['type']):raise B('candidate key type unsafe')
   elif not stat.S_ISDIR(identity['type']):raise B('candidate directory type unsafe')
def reject_nested_mounts():
 mounts=mount_targets()
 for _,src,_,_ in PATHS:
  base=str(src).rstrip('/')
  if any(m==base or m.startswith(base+'/') for m in mounts):raise B(f'unexpected mount under host-state source: {src}')
 if any(m.startswith(str(MOUNT).rstrip('/')+'/') for m in mounts):raise B('unexpected mount inside candidate vault')
 _candidate_paths_safe()
def capture_resources():
 reject_nested_mounts()
 if _unexpected_unit_links():raise B('preexisting host-state unit link')
 legacy={}
 for role,src,candidate,isfile in PATHS:
  identity=_identity(src)
  if bool(stat.S_ISREG(identity['type']))!=isfile:raise B('legacy resource type drifted')
  legacy[role]={'path':str(src),'candidate':str(candidate),'is_file':isfile,'identity':identity,'base_mount':_mount_at(src),'seal':{'state':'absent','owned':None}}
 gates={}
 for src,dst in SYSTEMD:
  if _exists(dst):raise B('preexisting host-state gate')
  gates[str(dst)]={'source':str(src),'source_identity':_identity(src,content=True),'parent_identity':_identity(dst.parent),'state':'absent','owned':None}
 links={}
 for link,target in _enable_links():
  if _exists(link):raise B('preexisting host-state enable link')
  links[str(link)]={'target':str(target),'parent_identity':_identity(link.parent),'state':'absent','owned':None}
 return {'schema_version':1,'boot_id':_boot_id(),'vault_mount':_mount_at(MOUNT),'vault_identity':_identity(MOUNT),'legacy':legacy,'gates':gates,'enable_links':links}
def validate_resources(snapshot):
 if snapshot!=capture_resources():raise B('resource snapshot changed before live mutation')
 return True
def _resources(attempt):
 journal=jread(attempt);r=journal.get('resources')
 if not isinstance(r,dict) or r.get('schema_version')!=1 or r.get('boot_id')!=_boot_id():raise B('resource journal unavailable or boot changed')
 if r.get('vault_mount')!=_mount_at(MOUNT) or r.get('vault_identity')!=_identity(MOUNT):raise B('candidate vault identity changed')
 _candidate_paths_safe()
 if any(m.startswith(str(MOUNT).rstrip('/')+'/') for m in mount_targets()):raise B('unexpected mount inside candidate vault')
 if set(r.get('legacy',{}))!={x[0] for x in PATHS} or set(r.get('gates',{}))!={str(x[1]) for x in SYSTEMD} or set(r.get('enable_links',{}))!={str(x[0]) for x in _enable_links()}:raise B('resource journal scope drifted')
 for role,src,candidate,isfile in PATHS:
  x=r['legacy'][role]
  if x.get('path')!=str(src) or x.get('candidate')!=str(candidate) or x.get('is_file')!=isfile:raise B('legacy resource journal scope drifted')
 for src,dst in SYSTEMD:
  if r['gates'][str(dst)].get('source')!=str(src):raise B('gate source journal scope drifted')
 for link,target in _enable_links():
  if r['enable_links'][str(link)].get('target')!=str(target):raise B('enable link journal scope drifted')
 return journal,r
def _save_resources(attempt,r):update_attempt(attempt,resources=r)
def _same_legacy(entry):
 return _identity(Path(entry['path']))==entry['identity']
def _expected_root(path,base):
 return str(Path(base['fsroot'])/Path(path).relative_to(Path(base['target'])))
def _seal_matches(row,entry):
 base=entry['base_mount']
 return row['target']==entry['path'] and row['device']==base['device'] and row['fsroot']==_expected_root(entry['path'],base)
def _candidate_matches(row,entry):
 src=Path(entry['candidate']);dst=Path(entry['path']);a=os.stat(src);b=os.stat(dst);base=_mount_at(src)
 return (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino) and row['target']==str(dst) and row['device']==base['device'] and row['fsroot']==_expected_root(src,base)
def _check_mount_resources(journal,r,allow_candidate):
 rows=_mount_rows()
 allowed_phase={'bind_activation_started','bind_active'}
 candidate_intent=journal.get('bind_activation_attempted') is True or journal.get('phase') in allowed_phase or journal.get('rollback_from_phase') in allowed_phase
 for entry in r['legacy'].values():
  path=entry['path'];seal=entry['seal'];owned=seal.get('owned');stack=[row for row in rows if row['target']==path]
  if any(row['target'].startswith(path.rstrip('/')+'/') for row in rows):raise B('unexpected nested mount during resource rollback')
  if not stack:
   if owned is not None and seal['state'] not in {'remove_intent','removed'}:raise B('owned seal disappeared without removal intent')
   if not _same_legacy(entry) or _mount_at(path)!=entry['base_mount']:raise B('legacy resource identity changed')
   continue
  if owned is None or seal['state']=='removed':raise B('unrecorded legacy mount preserved')
  saved=[row for row in stack if _mount_owner(row)==_mount_owner(owned)]
  if len(saved)!=1 or not _seal_matches(saved[0],entry):raise B('recorded seal identity changed')
  if seal['state']=='sealed':
   recorded_options=set(owned.get('options',[]));current_options=set(saved[0]['options'])
   if not {'ro','nodev','nosuid','noexec'}.issubset(recorded_options) or current_options!=recorded_options:raise B('completed legacy seal options drifted')
  visible=_mount_at(path)
  if _mount_owner(visible)==_mount_owner(owned):
   if len(stack)!=1 or not _same_legacy(entry):raise B('legacy seal stack or inode changed')
  elif not (allow_candidate and candidate_intent and len(stack)==2 and any(row['id']==visible['id'] for row in stack) and _candidate_matches(visible,entry)):
   raise B('foreign mount above owned legacy seal preserved')
def _check_enable_staging(entry,link):
 staging=entry.get('staging')
 if staging is None:return
 if not isinstance(staging,dict) or not isinstance(staging.get('path'),str):raise B('enable link staging journal invalid')
 path=Path(staging['path']);prefix='.aionex-enable-';suffix=path.name.removeprefix(prefix)
 if path.parent!=link.parent or not path.name.startswith(prefix) or len(suffix)!=32 or any(c not in '0123456789abcdef' for c in suffix):raise B('enable link staging scope drifted')
 # A leftover stage is never silently adopted or recursively removed. It can
 # contain an unrecorded creation/publication effect and requires reconciliation.
 if _exists(path):raise B('enable link publication stage unresolved; resources preserved')
 state=staging.get('state');identity=staging.get('identity')
 if state in {'remove_intent','removed'} and isinstance(identity,dict):return
 if state=='create_intent' and identity is None:return
 raise B('enable link publication stage disappeared without removal intent')
def _check_file_resources(r):
 for name,entry in r['enable_links'].items():_check_enable_staging(entry,Path(name))
 if _unexpected_unit_links():raise B('unexpected host-state unit link preserved')
 for section,link in (('gates',False),('enable_links',True)):
  for name,entry in r[section].items():
   p=Path(name)
   if _identity(p.parent)!=entry['parent_identity']:raise B('resource parent identity changed')
   if not _exists(p):
    if entry.get('owned') is not None and entry['state'] not in {'remove_intent','removed'}:raise B('owned gate or link disappeared without removal intent')
   elif entry.get('owned') is None or _identity(p,content=not link,link=link)!=entry['owned']:
    raise B('unowned or replaced gate/link preserved')
def rollback_resources_preflight(attempt):
 journal,r=_resources(attempt);_check_mount_resources(journal,r,True);_check_file_resources(r)
 return True
def verify_legacy_targets(attempt):
 journal,r=_resources(attempt);_check_mount_resources(journal,r,False);_check_file_resources(r)
 for entry in r['legacy'].values():
  if any(row['target']==entry['path'] for row in _mount_rows()):raise B('legacy mount remained after rollback')
 for section in ('gates','enable_links'):
  if any(_exists(Path(name)) for name in r[section]):raise B('host-state gate/link remained after rollback')
 return True
def exact_mount(p):return _mount_at(p)['target']==str(p)
def sealed(p):
 row=_mount_at(p)
 return row['target']==str(p) and {'ro','nodev','nosuid','noexec'}.issubset(row['options'])
def seal(p,attempt):
 journal,r=_resources(attempt);entry=next((v for v in r['legacy'].values() if v['path']==str(p)),None)
 if entry is None or entry['seal']['state']!='absent':raise B('seal not owned by a fresh resource intent')
 if not _same_legacy(entry) or _mount_at(p)!=entry['base_mount']:raise B('legacy source changed before seal')
 if any(m==str(p) or m.startswith(str(p).rstrip('/')+'/') for m in mount_targets()):raise B('preexisting mount before seal')
 entry['seal']['state']='create_intent';_save_resources(attempt,r)
 run(['mount','--bind',str(p),str(p)])
 row=_mount_at(p)
 if not _seal_matches(row,entry) or not _same_legacy(entry):raise B('new seal identity not proved')
 entry['seal'].update(state='remount_intent',owned=row);_save_resources(attempt,r)
 run(['mount','-o','remount,bind,ro,nodev,nosuid,noexec',str(p)])
 current=_mount_at(p)
 if _mount_owner(current)!=_mount_owner(row) or not sealed(p):raise B('legacy seal did not become read-only')
 entry['seal'].update(state='sealed',owned=current);_save_resources(attempt,r)
def unseal_all_checked(attempt):
 journal,r=_resources(attempt);_check_mount_resources(journal,r,False);_check_file_resources(r)
 for entry in reversed(list(r['legacy'].values())):
  p=Path(entry['path']);seal_entry=entry['seal'];owned=seal_entry.get('owned')
  if owned is None:continue
  journal,r=_resources(attempt);_check_mount_resources(journal,r,False);_check_file_resources(r)
  entry=next(x for x in r['legacy'].values() if x['path']==str(p));seal_entry=entry['seal']
  if not exact_mount(p):
   seal_entry['state']='removed';_save_resources(attempt,r);continue
  if _mount_owner(_mount_at(p))!=_mount_owner(owned):raise B('refusing unowned legacy unmount')
  seal_entry['state']='remove_intent';_save_resources(attempt,r);run(['umount',str(p)],120)
  if exact_mount(p) or not _same_legacy(entry) or _mount_at(p)!=entry['base_mount']:raise B('legacy seal removal not verified')
  seal_entry['state']='removed';_save_resources(attempt,r)
def precopy():
 for role,src,dst,isfile in PATHS:
  if isfile:
   dst.parent.mkdir(parents=True,exist_ok=True,mode=0o700);run(['rsync','-aHAX','--numeric-ids',str(src),str(dst)],300)
  else:
   dst.mkdir(parents=True,exist_ok=True,mode=0o700);run(['rsync','-aHAX','--numeric-ids','--delete',str(src)+'/',str(dst)+'/'],1800)
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
def hidden_underlay_references():
    """Inspect visible proc references; this is not proof about every kernel reference."""
    def verified_absent(reference, follow=False):
        try:
            (os.stat if follow else os.lstat)(reference)
        except (FileNotFoundError, ProcessLookupError):
            return True
        except OSError as exc:
            raise B('cannot verify a vanished process reference; underlay scan incomplete') from exc
        return False

    def entries(directory, owner):
        try:
            return sorted(directory.iterdir(), key=lambda value: value.name)
        except (FileNotFoundError, ProcessLookupError) as exc:
            if verified_absent(owner):
                return None
            raise B('reference directory unavailable for a remaining process or thread') from exc
        except OSError as exc:
            raise B('cannot enumerate process references; underlay scan incomplete') from exc

    def link(reference):
        try:
            return os.readlink(reference)
        except (FileNotFoundError, ProcessLookupError) as exc:
            # Kernel/zombie tasks can retain a magic-link placeholder without
            # a referenced FS object. Follow it to prove absence, not lstat.
            if verified_absent(reference, follow=True):
                return None
            raise B('process reference disappearance could not be verified') from exc
        except OSError as exc:
            raise B('cannot inspect a process reference; underlay scan incomplete') from exc

    holders = []

    def inspect_reference(reference, kind, pid, tid, identifier=None):
        target = link(reference)
        if target is None:
            return
        clean = target[:-10] if target.endswith(' (deleted)') else target
        for role, source, _, isfile in PATHS:
            base = str(source)
            if (isfile and clean == base) or (
                not isfile and (clean == base or clean.startswith(base.rstrip('/') + '/'))
            ):
                record = {'kind': kind, 'pid': pid, 'tid': tid, 'role': role}
                if identifier is not None:
                    record['range' if kind == 'mmap' else 'fd'] = identifier
                holders.append(record)

    try:
        processes = sorted(PROC.iterdir(), key=lambda value: value.name)
    except OSError as exc:
        raise B('cannot enumerate host processes; underlay scan incomplete') from exc
    for process in processes:
        if not process.name.isdigit():
            continue
        threads = entries(process / 'task', process)
        if threads is None:
            continue
        for thread in threads:
            if not thread.name.isdigit():
                continue
            pid, tid = int(process.name), int(thread.name)
            descriptors = entries(thread / 'fd', thread)
            if descriptors is None:
                continue
            for descriptor in descriptors:
                inspect_reference(descriptor, 'fd', pid, tid, descriptor.name)
            for kind in ('cwd', 'root'):
                inspect_reference(thread / kind, kind, pid, tid)
            # Linux exposes map_files through /proc/TID, not task/TID/map_files.
            # Scan each live thread alias so an exited leader cannot hide its
            # surviving threads' mappings. FD and FS tables can be unshared.
            mappings = entries(PROC / thread.name / 'map_files', thread)
            if mappings is None:
                continue
            for mapping in mappings:
                inspect_reference(mapping, 'mmap', pid, tid, mapping.name)
    return holders


def require_zero_hidden_underlay_references():
    holders = hidden_underlay_references()
    if holders:
        raise B('legacy host-state source has visible process references before bind activation')
    return 0


def hidden_underlay_fds():
    """Compatibility alias; now includes cwd, root and file mappings."""
    return hidden_underlay_references()


def require_zero_hidden_underlay_fds():
    """Compatibility alias for the complete visible-reference gate."""
    return require_zero_hidden_underlay_references()

def bootstrap_match():
 key=Path('/root/.config/aionex-bootstrap/control-plane.key');up=Path('/root/.config/aionex-bootstrap/trendbost-mcp-upstream.url')
 if fsha(key)!=fsha(Path('/root/.config/aionex/aionex-tunnel-runtime.key')):raise B('bootstrap control-plane key drifted from sealed operator source')
 if fsha(up)!=fsha(Path('/root/.config/aionex/trendbost-mcp-upstream.url')):raise B('bootstrap bridge upstream drifted from sealed operator source')
def _resource_sync_parent(path):
 fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 try:os.fsync(fd)
 finally:os.close(fd)
def _resource_write_all(fd,data):
 view=memoryview(data)
 while view:
  count=os.write(fd,view)
  if count<=0:raise E('gate write made no progress')
  view=view[count:]
def _record_gate_file(attempt,r,name,fd):
 entry=r['gates'][name];p=Path(name);s=os.fstat(fd)
 current=_identity(p,content=True)
 if (current['dev'],current['ino'])!=(s.st_dev,s.st_ino):raise B('created gate identity replaced')
 entry['owned']=current;_save_resources(attempt,r)
def _publish_link_noreplace(staged,destination):
 # renameat2 preserves the staged symlink inode and atomically refuses any
 # existing destination. There is deliberately no overwrite-capable fallback.
 import ctypes
 try:rename=ctypes.CDLL(None,use_errno=True).renameat2
 except (AttributeError,OSError) as x:raise B('atomic no-replace enable publication unavailable') from x
 rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
 rename.restype=ctypes.c_int
 if rename(-100,os.fsencode(staged),-100,os.fsencode(destination),1)!=0:raise OSError(ctypes.get_errno(),'atomic enable link publication failed')
def _install_enable_link(attempt,r,link,target):
 entry=r['enable_links'][str(link)]
 if entry['state']!='absent' or _exists(link):raise B('enable link install precondition changed')
 stage=link.parent/('.aionex-enable-'+secrets.token_hex(16));staged=stage/'link'
 staging={'path':str(stage),'state':'create_intent','identity':None}
 entry.update(state='create_intent',staging=staging);_save_resources(attempt,r)
 stage.mkdir(mode=0o700);_resource_sync_parent(stage)
 identity=_identity(stage)
 if not stat.S_ISDIR(identity['type']) or identity['mode']!=0o700 or identity['uid']!=os.geteuid():raise B('enable link staging directory is not private')
 staging.update(state='created',identity=identity);_save_resources(attempt,r)
 os.symlink(str(target),staged);expected=_identity(staged,link=True)
 if expected['target']!=str(target):raise B('created enable link target replaced; ownership not claimed')
 _resource_sync_parent(staged)
 # The journal owns the private inode before that inode enters systemd's
 # enable path. Observing a same-target replacement can never grant ownership.
 entry.update(owned=expected,state='publish_intent');_save_resources(attempt,r)
 if _identity(stage)!=identity or _identity(link.parent)!=entry['parent_identity']:raise B('enable link publication parent changed')
 _publish_link_noreplace(staged,link)
 if _identity(link,link=True)!=expected or _exists(staged):raise B('published enable link identity replaced; foreign resource preserved')
 _resource_sync_parent(staged);_resource_sync_parent(link)
 staging['state']='remove_intent';_save_resources(attempt,r)
 if _identity(stage)!=identity:raise B('enable link staging identity changed before removal')
 stage.rmdir();_resource_sync_parent(stage)
 if _exists(stage):raise B('enable link staging directory remained after removal')
 staging['state']='removed';entry['state']='installed';_save_resources(attempt,r)
def install_gates(attempt):
 journal,r=_resources(attempt);_check_file_resources(r)
 for src,dst in SYSTEMD:
  name=str(dst);entry=r['gates'][name]
  if entry['state']!='absent' or _exists(dst) or _identity(src,content=True)!=entry['source_identity']:raise B('gate install precondition changed')
  data=src.read_bytes()
  if hashlib.sha256(data).hexdigest()!=entry['source_identity']['sha256']:raise B('gate source changed while reading')
  entry['state']='create_intent';_save_resources(attempt,r)
  fd=os.open(dst,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o644)
  try:
   os.fchmod(fd,0o644);_record_gate_file(attempt,r,name,fd)
   try:_resource_write_all(fd,data);os.fsync(fd)
   except Exception:
    try:_record_gate_file(attempt,r,name,fd);_resource_sync_parent(dst)
    except Exception:pass
    raise
   _record_gate_file(attempt,r,name,fd);_resource_sync_parent(dst)
   if entry['owned']['sha256']!=entry['source_identity']['sha256']:raise B('installed gate content mismatch')
   entry['state']='installed';_save_resources(attempt,r)
  finally:os.close(fd)
 for link,target in _enable_links():
  _check_file_resources(r);_install_enable_link(attempt,r,link,target)
 run(['systemctl','daemon-reload'])
def remove_gates_checked(attempt):
 rollback_resources_preflight(attempt)
 for section,link in (('enable_links',True),('gates',False)):
  _,r=_resources(attempt)
  for name in reversed(list(r[section])):
   rollback_resources_preflight(attempt);_,r=_resources(attempt);entry=r[section][name];p=Path(name)
   if not _exists(p):
    if entry.get('owned') is not None:entry['state']='removed';_save_resources(attempt,r)
    continue
   if entry.get('owned') is None or _identity(p,content=not link,link=link)!=entry['owned']:raise B('refusing removal of unowned gate/link')
   entry['state']='remove_intent';_save_resources(attempt,r);p.unlink();_resource_sync_parent(p)
   if _exists(p):raise B('owned gate/link remained after removal')
   entry['state']='removed';_save_resources(attempt,r)
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
def current_restart(container_id,inspected=None):
 if inspected is None:
  payload=json.loads(run(['docker','inspect',container_id],30))
  if not isinstance(payload,list) or len(payload)!=1:raise B('restart policy inspection is incomplete')
  inspected=payload[0]
 if not isinstance(inspected,dict) or inspected.get('Id')!=container_id:raise B('restart policy container identity mismatch')
 policy=(inspected.get('HostConfig') or {}).get('RestartPolicy')
 if not isinstance(policy,dict):raise B('container restart policy is unavailable')
 name=policy.get('Name') or 'no';count=policy.get('MaximumRetryCount',0)
 if name not in {'no','always','unless-stopped','on-failure'} or not isinstance(count,int) or isinstance(count,bool) or count<0 or (name!='on-failure' and count!=0):raise B('container restart policy is invalid')
 return name+(f':{count}' if name=='on-failure' and count>0 else '')

def restart_targets(t):
 rows=t.get('containers') or [];seen=set();targets=[]
 if not rows:raise B('planned restart policies are empty')
 for row in rows:
  cid=row.get('id');restart=row.get('restart')
  if not isinstance(cid,str) or not cid or cid in seen or not isinstance(restart,str):raise B('planned restart policy identity is invalid')
  name,separator,count=restart.partition(':')
  if name not in {'no','always','unless-stopped','on-failure'} or (separator and (name!='on-failure' or not count.isdigit() or int(count)<=0 or str(int(count))!=count)):raise B('planned restart policy is invalid')
  seen.add(cid);targets.append((cid,restart))
 return targets
def quiesce_restart_policies(t):
 targets=restart_targets(t)
 for cid,restart in targets:
  if current_restart(cid)!=restart:raise B('container restart policy changed after planning')
 try:
  for cid,_ in targets:
   run(['docker','update','--restart=no',cid],60)
   if current_restart(cid)!='no':raise B('container restart policy did not quiesce')
  for cid,_ in targets:
   if current_restart(cid)!='no':raise B('container restart policy did not remain quiesced')
 except Exception as original:
  try:restore_restart_policies(t)
  except Exception as restore_error:raise E('restart policy quiesce failed and original policy restoration failed') from restore_error
  raise E('restart policy quiesce failed; all original policies restored') from original
def restore_restart_policies(t):
 targets=restart_targets(t);failures=[]
 for cid,restart in targets:
  try:run(['docker','update','--restart='+restart,cid],60)
  except Exception:failures.append(cid)
 for cid,restart in targets:
  try:
   if current_restart(cid)!=restart:failures.append(cid)
  except Exception:failures.append(cid)
 if failures:raise B('container restart policy restoration failed or remained unverified')
def stop_live(t):
 ids=[r['id'] for r in t['containers']];run(['docker','stop','--time','60',*ids],180)
 if run(['docker','ps','-q']).strip():raise B('running Docker containers remained')
 run(['systemctl','stop','docker.service','docker.socket'],120)
 if active('docker.service'):raise B('Docker remained active')
HEALTH_PROBE_USER_AGENT='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
HTTP_ACCEPTANCE_URLS=('http://127.0.0.1:8080/health','http://127.0.0.1:8080/ready','https://api.vip-e.net/health','https://api.vip-e.net/ready','https://ai.vip-e.net/')

def wait_for_topology(t,timeout_seconds=300,poll_seconds=5):
 if timeout_seconds<=0 or poll_seconds<=0:raise B('container health polling bounds are invalid')
 expected=t.get('containers') or [];expected_ids={r['id'] for r in expected};services={}
 for row in expected:services.setdefault(row['service'],[]).append(row['id'])
 services={k:sorted(v) for k,v in sorted(services.items())}
 if len(expected)!=36 or len(expected_ids)!=36 or t.get('container_count')!=36 or t.get('project_worker_scale')!=4 or len(services.get('project-worker',[]))!=4 or t.get('services')!=services:raise B('planned acceptance topology is invalid')
 identity={(r['id'],r['name'],r['service']) for r in expected};policies=dict(restart_targets(t));deadline=time.monotonic()+timeout_seconds
 while True:
  n=topology(require_healthy=False,deadline=deadline)
  if {(r['id'],r['name'],r['service']) for r in n['containers']}!=identity or n['services']!=services or n['container_count']!=36 or n['project_worker_scale']!=4:raise B('container identity or service topology drifted')
  if {r['id']:r['restart'] for r in n['containers']}!=policies:raise B('container restart policies drifted during acceptance')
  if all(r['health'] in {'healthy','none'} for r in n['containers']):return n
  remaining=deadline-time.monotonic()
  if remaining<=0:raise B('container health timeout')
  time.sleep(min(poll_seconds,remaining))

def http_and_tunnel_acceptance(timeout_seconds=90,poll_seconds=5):
 if timeout_seconds<=0 or poll_seconds<=0:raise B('HTTP acceptance polling bounds are invalid')
 deadline=time.monotonic()+timeout_seconds
 while True:
  ready=True
  for url in HTTP_ACCEPTANCE_URLS:
   remaining=deadline-time.monotonic()
   if remaining<=0:raise B('HTTP health or portal acceptance timeout')
   budget=min(25,remaining)
   try:code=run(['curl','-sS','--connect-timeout',str(min(10,budget)),'--max-time',str(budget),'--user-agent',HEALTH_PROBE_USER_AGENT,'-o','/dev/null','-w','%{http_code}',url],budget)
   except (E,subprocess.TimeoutExpired):ready=False;break
   if code!='200':
    if code not in {'000','429','500','502','503','504'}:raise B('HTTP health or portal acceptance failed')
    ready=False;break
  if ready:
   for unit in TUNNELS:
    remaining=deadline-time.monotonic()
    if remaining<=0:raise B('control tunnel acceptance timeout')
    if run(['systemctl','is-active',unit],min(10,remaining),check=False)!='active':ready=False;break
  if ready:return
  remaining=deadline-time.monotonic()
  if remaining<=0:raise B('HTTP or control tunnel acceptance timeout')
  time.sleep(min(poll_seconds,remaining))

def legacy_acceptance(t):
 def encrypted_runtime_ready():
  runtime=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'status','--require-ready'],30))
  if runtime.get('validation')!='FR06C4_RUNTIME_BIND_READY':raise B('encrypted container runtime regressed during rollback')
 wait_for_topology(t);encrypted_runtime_ready();http_and_tunnel_acceptance();encrypted_runtime_ready()
 return wait_for_topology(t,timeout_seconds=30)

def rollback_prestart(t, watch, phase, attempt):
    record = jread(attempt)
    if record.get('candidate_start_attempted') is not False or record.get('boot_id') != boot_id():
        raise B('rollback authority changed or candidate start was attempted')
    no_live = {'claimed', 'precopy_started'}
    watcher_only = {'watcher_stop_started', 'watchers_stopped'}
    policy_only = {'restart_policy_quiesce_started', 'restart_policies_quiesced'}
    live_phases = {
        'application_stop_started', 'legacy_runtime_stopped', 'legacy_seal_started',
        'legacy_sources_sealed', 'gate_install_started', 'gates_installed',
        'bind_activation_started', 'bind_active',
    }
    if phase in no_live:
        return {'status': 'no_live_mutation_to_rollback'}
    if phase in watcher_only:
        restore_watchers(watch)
        return {'status': 'watchers_restored'}
    if phase in policy_only:
        if not active('docker.service'):
            raise B('Docker unexpectedly inactive during policy-only rollback')
        restore_restart_policies(t)
        restore_watchers(watch)
        legacy_acceptance(t)
        return {'status': 'policies_and_watchers_restored'}
    if phase not in live_phases:
        raise B('unknown cutover phase requires reconciliation')
    rollback_resources_preflight(attempt)
    if phase in {'bind_activation_started', 'bind_active'}:
        run(['systemctl','stop','docker.service','docker.socket'],120)
        if active('docker.service'):
            raise B('Docker remained active during rollback')
        run(['systemctl', 'stop', 'aionex-fr06c5-host-state-bind.service'], 120)
        result = json.loads(run([
            'python3', str(ROOT / 'scripts/security/fr06c5_host_state_bind.py'), 'rollback'
        ], 120))
        if result.get('validation') != 'FR06C5_HOST_STATE_BIND_REMOVED':
            raise B('candidate host-state bind rollback not verified')
    if phase in {'gate_install_started', 'gates_installed', 'bind_activation_started', 'bind_active'}:
        remove_gates_checked(attempt)
    if phase in {'legacy_seal_started', 'legacy_sources_sealed', 'gate_install_started',
                 'gates_installed', 'bind_activation_started', 'bind_active'}:
        unseal_all_checked(attempt)
    verify_legacy_targets(attempt)
    if not active('docker.service'):
        run(['systemctl', 'start', 'docker.socket', 'docker.service'], 180)
    if not active('docker.service'):
        raise B('legacy Docker failed to restart')
    run(['docker', 'start', *[r['id'] for r in t['containers']]], 180)
    restore_restart_policies(t)
    restore_watchers(watch)
    legacy_acceptance(t)
    return {'status': 'legacy_runtime_fully_restored'}

def acceptance(t):
 def encrypted_binds_ready():
  bind=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c5_host_state_bind.py'),'status','--require-ready'],30))
  if bind.get('validation')!='FR06C5_HOST_STATE_BIND_READY':raise B('host-state bind acceptance failed')
  runtime=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_bind.py'),'status','--require-ready'],30))
  if runtime.get('validation')!='FR06C4_RUNTIME_BIND_READY':raise B('container runtime bind regressed')
 encrypted_binds_ready();wait_for_topology(t);http_and_tunnel_acceptance();encrypted_binds_ready()
 return wait_for_topology(t,timeout_seconds=30)
def inspect():return {'schema_version':1,'subpart':'FR-06C5D','observed_at':utc(),'topology':topology(),'docker_active':active('docker.service'),'containerd_active':active('containerd.service'),'production_changed':False}
def plan(a):
    if os.geteuid() != 0:
        raise B('root required')
    with operation_lock():
        gitgate(a.merge_sha)
        evidence(a.evidence.resolve(), a.merge_sha)
        c5gate()
        unresolved_attempt_gate()
        current = topology()
        if not active('docker.service') or not active('containerd.service'):
            raise B('live runtime not active')
        if not 1 <= a.ttl_seconds <= MAX_TTL:
            raise B('plan TTL invalid')
        resources = capture_resources()
        created = now()
        body = {
            'schema_version': 2, 'subpart': 'FR-06C5D', 'operation': 'host-state-cutover',
            'created_at': utc(created), 'expires_at': utc(created + timedelta(seconds=a.ttl_seconds)),
            'merge_sha': a.merge_sha, 'evidence_sha256': fsha(a.evidence.resolve()),
            'topology': current, 'resource_snapshot': resources, 'boot_id': boot_id(),
            'nonce': secrets.token_hex(32), 'blind_post_start_rollback_permitted': False,
            'cloudflare_change_permitted': False,
        }
        body['plan_id'] = digest(body)
        path = STATE / 'plans' / (body['plan_id'] + '.json')
        store(path, body)
        return {'status': 'host_state_cutover_plan_ready', 'plan_id': body['plan_id'],
                'plan': str(path), 'production_executed': False}


def loadplan(path, evidence_path):
    private(path, 'plan')
    result = jread(path)
    plan_id = result.get('plan_id')
    attempt_path(plan_id)
    if result.get('schema_version') != 2 or result.get('subpart') != 'FR-06C5D' or result.get('operation') != 'host-state-cutover':
        raise B('plan schema or operation invalid')
    if digest({k: v for k, v in result.items() if k != 'plan_id'}) != plan_id:
        raise B('plan digest invalid')
    if now() > parsez(result['expires_at'], 'plan expiry'):
        raise B('plan expired')
    if result['evidence_sha256'] != fsha(evidence_path):
        raise B('evidence changed after planning')
    if result.get('boot_id') != boot_id():
        raise B('plan belongs to another boot')
    return result


def apply(a):
    if os.geteuid() != 0:
        raise B('root required')
    with operation_lock():
        # Every authority that can change is read after obtaining the same lock
        # used for planning. No precopy or live mutation precedes the durable claim.
        planned = loadplan(a.plan.resolve(), a.evidence.resolve())
        if a.confirmation != 'EXECUTE_FR06C5_HOST_STATE_CUTOVER:' + planned['plan_id'] or a.confirm_production != CONFIRM:
            raise B('exact production confirmation required')
        gitgate(a.merge_sha)
        evidence(a.evidence.resolve(), a.merge_sha)
        c5gate()
        unresolved_attempt_gate()
        current = topology()
        if planned['merge_sha'] != a.merge_sha or current != planned['topology']:
            raise B('live topology changed after planning')
        if not active('docker.service') or not active('containerd.service'):
            raise B('live runtime not active')
        resources = capture_resources()
        if resources != planned.get('resource_snapshot'):
            raise B('host-state resources changed after planning')
        validate_resources(resources)
        watch = watcher_states()
        attempt = attempt_path(planned['plan_id'])
        candidate_start_attempted = False
        claimed = False
        try:
            try:
                store(attempt, {
                    'schema_version': 2, 'subpart': 'FR-06C5D',
                    'plan_id': planned['plan_id'], 'merge_sha': a.merge_sha, 'plan': planned,
                    'topology': current, 'boot_id': boot_id(), 'watchers': watch,
                    'resources': resources, 'resource_snapshot_sha256': digest(resources),
                    'phase': 'claimed', 'created_at': utc(), 'candidate_start_attempted': False,
                })
            except FileExistsError as exc:
                raise B('host-state cutover plan already attempted') from exc
            claimed = True
            reject_nested_mounts()
            validate_resources(jread(attempt)['resources'])
            update_attempt(attempt, phase='precopy_started')
            precopy()
            # The copy may take longer than the plan's TTL. Revalidate all
            # mutable authorization and identities before the first live stop.
            c5gate()
            if topology() != current:
                raise B('live topology changed during precopy')
            validate_resources(jread(attempt)['resources'])
            if watcher_states() != watch:
                raise B('runtime watcher state changed before mutation')
            confirmed = loadplan(a.plan.resolve(), a.evidence.resolve())
            if confirmed != planned:
                raise B('plan changed during precopy')
            gitgate(a.merge_sha)
            evidence(a.evidence.resolve(), a.merge_sha)
            update_attempt(attempt, phase='watcher_stop_started')
            stop_watchers(watch)
            update_attempt(attempt, phase='watchers_stopped')
            update_attempt(attempt, phase='restart_policy_quiesce_started')
            quiesce_restart_policies(current)
            update_attempt(attempt, phase='restart_policies_quiesced')
            update_attempt(attempt, phase='application_stop_started')
            stop_live(current)
            update_attempt(attempt, phase='legacy_runtime_stopped')
            update_attempt(attempt, phase='legacy_seal_started')
            for _, source, _, _ in PATHS:
                seal(source, attempt)
            update_attempt(attempt, phase='legacy_sources_sealed')
            manifests = exact_copy_and_manifest()
            bootstrap_match()
            hidden_reference_count = require_zero_hidden_underlay_references()
            update_attempt(attempt, phase='gate_install_started')
            install_gates(attempt)
            update_attempt(attempt, phase='gates_installed')
            update_attempt(attempt, phase='bind_activation_started')
            run(['systemctl', 'start', 'aionex-fr06c5-host-state-bind.service'], 120)
            bind = json.loads(run([
                'python3', str(ROOT / 'scripts/security/fr06c5_host_state_bind.py'),
                'status', '--require-ready',
            ]))
            if bind.get('validation') != 'FR06C5_HOST_STATE_BIND_READY':
                raise B('host-state candidate bind did not become ready')
            update_attempt(attempt, phase='bind_active')
            # Set the in-memory barrier before the durable write. A failed write
            # leaves an uncertain attempt for reconciliation, never a blind undo.
            candidate_start_attempted = True
            update_attempt(attempt, phase='candidate_start_attempted', candidate_start_attempted=True)
            run(['systemctl', 'start', 'docker.socket', 'docker.service'], 180)
            run(['docker', 'start', *[r['id'] for r in current['containers']]], 180)
            restore_restart_policies(current)
            restore_watchers(watch)
            acceptance(current)
            body = {
                'schema_version': 1, 'subpart': 'FR-06C5D',
                'status': 'encrypted_host_state_started_admission_closed', 'completed_at': utc(),
                'operation_id': planned['plan_id'], 'merge_sha': a.merge_sha,
                'running_containers': 36, 'unhealthy_running_containers': 0, 'project_worker_scale': 4,
                'manifest': manifests,
                'hidden_underlay_reference_count': hidden_reference_count,
                'hidden_underlay_fd_count': hidden_reference_count,
                'legacy_underlays_read_only': True, 'legacy_underlays_deleted': False,
                'candidate_host_state_authoritative': True, 'bootstrap_remains_outside_vault': True,
                'post_start_blind_rollback_permitted': False, 'admission_opened': False,
                'cloudflare_changed': False,
            }
            result = STATE / 'results' / (planned['plan_id'] + '.json')
            store(result, {**body, 'receipt_sha256': digest(body)})
            update_attempt(attempt, phase='accepted', accepted_receipt=str(result))
            return {'status': body['status'], 'result': str(result), 'admission_opened': False}
        except Exception as original:
            if not claimed:
                raise
            try:
                recorded = jread(attempt)
            except Exception as journal_error:
                raise E('attempt journal unavailable; reconciliation required without automatic rollback') from journal_error
            candidate_start_attempted = candidate_start_attempted or recorded.get('candidate_start_attempted') is not False
            if not candidate_start_attempted:
                phase = str(recorded.get('phase', ''))
                if phase in {'claimed', 'precopy_started'}:
                    update_attempt(attempt, phase='failed_before_live_mutation',
                                   last_error_type=type(original).__name__)
                    raise E('host-state cutover failed before live mutation; plan consumed without outage') from original
                try:
                    rollback = rollback_prestart(current, watch, phase, attempt)
                    update_attempt(attempt, phase='legacy_restored_prestart', rollback_verified=True,
                                   rollback_result=rollback, last_error_type=type(original).__name__)
                except Exception as rollback_error:
                    try:
                        update_attempt(attempt, phase='rollback_failed', rollback_verified=False,
                                       last_error_type=type(original).__name__,
                                       rollback_error_type=type(rollback_error).__name__)
                    except Exception:
                        pass
                    raise E('host-state cutover failed before candidate start and rollback failed; reconciliation required') from rollback_error
                raise E('host-state cutover failed before candidate start; legacy runtime restored and plan consumed') from original
            try:
                update_attempt(attempt, phase='post_start_failure_requires_reconciliation',
                               candidate_start_attempted=True, last_error_type=type(original).__name__)
            except Exception:
                pass
            raise E('host-state cutover failed after candidate start attempt; candidate state may be authoritative and blind rollback is prohibited') from original

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);s.add_parser('inspect-runtime');q=s.add_parser('plan-cutover');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--ttl-seconds',type=int,default=600);q=s.add_parser('apply-cutover');q.add_argument('--merge-sha',required=True);q.add_argument('--evidence',type=Path,required=True);q.add_argument('--plan',type=Path,required=True);q.add_argument('--confirmation',required=True);q.add_argument('--confirm-production',default='');a=p.parse_args()
 try:o=inspect() if a.cmd=='inspect-runtime' else plan(a) if a.cmd=='plan-cutover' else apply(a);print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
 except Exception as e:print(json.dumps({'status':'error','reason':str(e)},sort_keys=True));return 1
if __name__=='__main__':raise SystemExit(main())
