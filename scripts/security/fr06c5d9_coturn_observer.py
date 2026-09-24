#!/usr/bin/env python3
"""Read private Coturn allocation evidence without authorizing host cutover.

The supported profile is the pinned, single-instance, UDP-relay-only deployment.
The metrics endpoint must already be explicitly enabled on container loopback.
This tool does not enable it, restart anything, or turn missing samples into zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

SCHEMA = 'aionex.coturn-allocation-observation.v1'
SCOPE = ('project_execution+backup_cycles+academy_course_packages+'
         'notification_delivery_dispatch+security_remediation_preparation+'
         'security_scan_requests+studio_job_requests+realtime_media_requests')
IMAGE = 'sha256:75e9ebd1e19005bec0c7f591d29afe22f959916ac8d9c852452f27db8c789828'
CONFIG_DESTINATION = '/etc/coturn/turnserver.conf'
METRIC = 'turn_total_allocations'
MAX_RESPONSE_BYTES = 262144
MAX_INTERVAL_SECONDS = 30.0

# Uses the existing application's validated authority reader; it never commits,
# changes the authority, or reads user/project content.
AUTHORITY_READER = '''import asyncio,json,signal
from sqlalchemy import text
signal.alarm(8)
from app.db.base import SessionLocal
from app.services.host_maintenance_admission import read_admission_snapshot
async def main():
 async with SessionLocal() as session:
  await session.execute(text("SET LOCAL statement_timeout = '5s'"))
  await session.execute(text("SET LOCAL lock_timeout = '3s'"))
  state=await read_admission_snapshot(session,required_scope="realtime_media_requests")
  print(json.dumps({"schema_version":state.schema_version,"scope":state.scope,
   "generation":state.generation,"status":state.status,"enabled":state.enabled,
   "operation_id":state.operation_id,"changed_at":state.changed_at.isoformat() if state.changed_at else None,
   "full_host_closure":state.full_host_closure}))
asyncio.run(main())
'''

# Runs with the host interpreter but only inside the pinned network namespace.
# Proxies and redirects are disabled. Only this metric family crosses the pipe.
METRICS_READER = '''import hashlib,json,signal,urllib.request
signal.alarm(5)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
url="http://127.0.0.1:9641/metrics"
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
with opener.open(urllib.request.Request(url,headers={"Accept":"text/plain"}),timeout=3) as response:
 if response.status!=200 or response.geturl()!=url: raise RuntimeError("metrics unavailable")
 raw=response.read(262145)
 if len(raw)>262144: raise RuntimeError("metrics response exceeds bound")
 body=raw.decode("utf-8",errors="strict")
 family=[line for line in body.splitlines() if line.startswith("# TYPE turn_total_allocations ") or line.startswith("turn_total_allocations")]
 print(json.dumps({"family":"\\n".join(family),"body_sha256":hashlib.sha256(raw).hexdigest(),"body_bytes":len(raw)}))
'''


class ObservationBlocked(RuntimeError):
    """An observation cannot be safely bound to the current maintenance state."""


def _fail(reason: str) -> NoReturn:
    raise ObservationBlocked(reason)


def _time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        _fail('invalid timestamp')
    assert parsed is not None
    return parsed


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9a-f]{'+str(length)+'}', value))


def validate_authority(payload: Any, operation_id: str, generation: int) -> dict[str, Any]:
    required = {'schema_version','scope','generation','status','enabled',
                'operation_id','changed_at','full_host_closure'}
    if not _uuid(operation_id) or type(generation) is not int or generation < 8:
        _fail('invalid requested authority')
    if not isinstance(payload, dict) or set(payload) != required:
        _fail('invalid authority fields')
    if (
        type(payload['schema_version']) is not int or payload['schema_version'] != 8
        or type(payload['generation']) is not int or payload['generation'] != generation
        or payload['operation_id'] != operation_id or payload['status'] != 'closed'
        or payload['enabled'] is not False or payload['full_host_closure'] is not False
        or payload['scope'] != SCOPE
    ):
        _fail('requested Realtime authority is not closed')
    _time(payload['changed_at'])
    return dict(payload)


def parse_allocations(family: Any) -> int:
    """Missing, incomplete, duplicated or non-UDP samples are UNKNOWN, not zero."""
    if not isinstance(family, str) or len(family.encode()) > MAX_RESPONSE_BYTES:
        _fail('invalid metric family')
    types = 0
    values: list[int] = []
    for line in family.splitlines():
        if not line:
            continue
        if line == '# TYPE turn_total_allocations gauge':
            types += 1
            continue
        match = re.fullmatch(r'turn_total_allocations\{type="UDP"\} ([^\s]+)', line)
        if match is None:
            _fail('metric family is incomplete or outside the UDP profile')
        try:
            value = Decimal(match.group(1))
        except InvalidOperation:
            _fail('invalid allocation value')
        if not value.is_finite() or value < 0 or value > 2**53 or value != value.to_integral_value():
            _fail('invalid allocation count')
        values.append(int(value))
    if types != 1 or len(values) != 1:
        _fail('allocation metric is missing or duplicated')
    return values[0]


def validate_config(body: str) -> None:
    """Accept only an explicit private observer on the deployed UDP-only profile."""
    keys = {'prometheus','prometheus-address','prometheus-port','prometheus-path',
            'prometheus-username-labels','no-tcp-relay','no-udp-relay','include','config'}
    options: dict[str, str] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        key = key.strip()
        if key not in keys:
            continue
        if key in options:
            _fail('duplicate observer configuration')
        options[key] = value.strip() if sep else ''
    enabled = {'','1','true','yes'}
    if (
        'prometheus' not in options or options['prometheus'] not in enabled
        or options.get('prometheus-address') != '127.0.0.1'
        or options.get('prometheus-port') != '9641'
        or options.get('prometheus-path','/metrics') != '/metrics'
        or 'no-tcp-relay' not in options or options['no-tcp-relay'] not in enabled
        or any(k in options for k in ['no-udp-relay','prometheus-username-labels','include','config'])
    ):
        _fail('private UDP-only metrics profile is not enabled')


def _run(args: list[str], *, pass_fds: tuple[int, ...] = ()) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False,
                            timeout=10, pass_fds=pass_fds)
    if result.returncode:
        _fail('observer command failed')
    return result.stdout


@dataclass(frozen=True)
class Epoch:
    container_id: str
    image: str
    pid: int
    started_at: str
    restart_count: int
    boot_id: str
    process_start_ticks: int
    netns_inode: int


class DockerObserver:
    """Fixed read operations on one Compose deployment, never container control."""

    def __init__(self, project: str = 'web-dashboard') -> None:
        if project != 'web-dashboard' and not re.fullmatch(r'aionex-disposable-[a-z0-9-]{1,64}', project):
            _fail('observer project is outside AIOS or its disposable lab')
        self.project = project

    def _inspect(self, service: str) -> dict[str, Any]:
        if service not in {'backend','realtime-turn'}:
            _fail('unsupported observation service')
        rows = _run(['docker','ps','--no-trunc','--filter',
            'label=com.docker.compose.project='+self.project,'--filter',
            'label=com.docker.compose.service='+service,'--format','{{.ID}}']).split()
        if len(rows) != 1 or not _hex(rows[0],64):
            _fail('expected one exact running service')
        data = json.loads(_run(['docker','inspect',rows[0]]))
        if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],dict):
            _fail('invalid container inspection')
        container = data[0]
        state = container.get('State',{})
        labels = container.get('Config',{}).get('Labels',{})
        if (
            container.get('Id') != rows[0]
            or labels.get('com.docker.compose.project') != self.project
            or labels.get('com.docker.compose.service') != service
            or state.get('Running') is not True or state.get('Status') != 'running'
            or state.get('Paused') is not False or state.get('Restarting') is not False
            or type(state.get('Pid')) is not int or state['Pid'] <= 0
        ):
            _fail('container identity is not stable and running')
        if service == 'realtime-turn' and (
                container.get('Image') != IMAGE
                or container.get('Path') != '/usr/bin/turnserver'
                or container.get('Args') != ['-c',CONFIG_DESTINATION]
                or container.get('Config',{}).get('User') not in {'65534:65534','nobody:nogroup'}
                or container.get('HostConfig',{}).get('NetworkMode') == 'host'
                or (container.get('HostConfig',{}).get('PortBindings') or {}).get('9641/tcp')
        ):
            _fail('Coturn image, command or private-network profile differs')
        return container

    def epoch(self, service: str) -> Epoch:
        container = self._inspect(service)
        state = container['State']
        pid = state['Pid']
        started = state.get('StartedAt')
        _time(started)
        restarts = container.get('RestartCount')
        if type(restarts) is not int or restarts < 0:
            _fail('invalid restart epoch')
        raw = Path(f'/proc/{pid}/stat').read_text()
        parts = raw[raw.rfind(')')+2:].split()
        ticks = int(parts[19])
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if not _uuid(boot) or ticks <= 0:
            _fail('invalid host process epoch')
        return Epoch(container['Id'],container['Image'],pid,started,restarts,
                     boot,ticks,os.stat(f'/proc/{pid}/ns/net').st_ino)

    def config_digest(self, epoch: Epoch) -> str:
        container = self._inspect('realtime-turn')
        if container['Id'] != epoch.container_id:
            _fail('Coturn changed before configuration validation')
        matches = [m for m in container.get('Mounts',[]) if m.get('Destination')==CONFIG_DESTINATION]
        if len(matches)!=1 or matches[0].get('Type')!='bind' or matches[0].get('RW') is not False:
            _fail('expected exact read-only Coturn configuration mount')
        path = matches[0].get('Source')
        if not isinstance(path,str) or not Path(path).is_absolute():
            _fail('invalid Coturn configuration path')
        fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
                or info.st_uid!=65534 or info.st_gid!=65534 or info.st_mode & 0o077
            ):
                _fail('configuration is not private to the pinned non-root service')
            mounted=os.stat(f'/proc/{epoch.pid}/root{CONFIG_DESTINATION}')
            if (mounted.st_dev,mounted.st_ino)!=(info.st_dev,info.st_ino):
                _fail('mounted configuration inode differs from inspected source')
            if info.st_size>65536 or max(info.st_mtime,info.st_ctime)>_time(epoch.started_at).timestamp():
                _fail('configuration does not predate the running process')
            body=os.read(fd,65537)
            after=os.fstat(fd)
            stable=lambda x: (x.st_dev,x.st_ino,x.st_mode,x.st_uid,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
            if len(body)>65536 or stable(info)!=stable(after):
                _fail('configuration changed during read')
            validate_config(body.decode('utf-8',errors='strict'))
            return hashlib.sha256(body).hexdigest()
        finally:
            os.close(fd)

    def authority(self, backend: Epoch) -> Any:
        return json.loads(_run(['docker','exec','--user','1000:1000',backend.container_id,
                               '/opt/venv/bin/python','-c',AUTHORITY_READER]))

    @contextmanager
    def network_namespace(self, epoch: Epoch) -> Iterator[int]:
        fd=os.open(f'/proc/{epoch.pid}/ns/net',os.O_RDONLY)
        try:
            if os.fstat(fd).st_ino!=epoch.netns_inode or self.epoch('realtime-turn')!=epoch:
                _fail('Coturn network namespace changed')
            yield fd
        finally:
            os.close(fd)

    def sample(self, netns_fd: int) -> dict[str, Any]:
        payload=json.loads(_run(['/usr/bin/nsenter',f'--net=/proc/self/fd/{netns_fd}',
            '--','/usr/bin/python3','-I','-c',METRICS_READER],pass_fds=(netns_fd,)))
        if not isinstance(payload,dict) or set(payload)!={'family','body_sha256','body_bytes'}:
            _fail('invalid metrics response envelope')
        if not _hex(payload['body_sha256'],64) or type(payload['body_bytes']) is not int or not 0<payload['body_bytes']<=MAX_RESPONSE_BYTES:
            _fail('metrics response bounds are invalid')
        return {'udp_allocations':parse_allocations(payload['family']),
                'body_sha256':payload['body_sha256'],'body_bytes':payload['body_bytes']}


def collect_observation(*, operation_id: str, generation: int,
                        observer: DockerObserver | None = None) -> dict[str, Any]:
    """Bracket two real samples with authority and container/process epoch reads."""
    if not _uuid(operation_id) or type(generation) is not int or generation < 8:
        _fail('invalid requested authority')
    observer=observer or DockerObserver()
    clock=time.monotonic()
    backend=observer.epoch('backend')
    before=validate_authority(observer.authority(backend),operation_id,generation)
    turn=observer.epoch('realtime-turn')
    config=observer.config_digest(turn)
    with observer.network_namespace(turn) as fd:
        first=observer.sample(fd)
        time.sleep(.25)
        second=observer.sample(fd)
    if observer.epoch('realtime-turn')!=turn or observer.epoch('backend')!=backend:
        _fail('service epoch changed during observation')
    if observer.config_digest(turn)!=config:
        _fail('observer configuration changed during observation')
    after=validate_authority(observer.authority(backend),operation_id,generation)
    if after!=before:
        _fail('authority changed during observation')
    # Final epoch read protects against restart while the final DB read ran.
    if observer.epoch('realtime-turn')!=turn or observer.epoch('backend')!=backend:
        _fail('service epoch changed during final authority check')
    elapsed=time.monotonic()-clock
    if not 0<=elapsed<=MAX_INTERVAL_SECONDS:
        _fail('observation interval exceeded bound')
    return {'schema':SCHEMA,'operation_id':operation_id,'generation':generation,
        'authority':after,'compose_project':observer.project,
        'container_epoch':vars(turn),'backend_epoch':vars(backend),
        'config_sha256':config,'observed_at':datetime.now().astimezone().isoformat(),
        'elapsed_seconds':elapsed,'samples':[first,second],
        'supported_profile':'one_pinned_coturn_instance_udp_relay_only',
        'allocation_zero_observed':first['udp_allocations']==0 and second['udp_allocations']==0,
        'missing_metric_is_zero':False,'production_deployment_performed':False,
        'credential_expiry_verified':False,'turn_allocation_drain_verified':False,
        'provider_drain_verified':False,'full_host_closure':False,
        'migration_0064_rollout_allowed':False}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation-id',required=True)
    parser.add_argument('--generation',type=int,required=True)
    parser.add_argument('--project',default='web-dashboard')
    args=parser.parse_args()
    try:
        result=collect_observation(operation_id=args.operation_id,generation=args.generation,
                                   observer=DockerObserver(args.project))
    except (ObservationBlocked,OSError,ValueError,KeyError,IndexError,TypeError,subprocess.SubprocessError):
        # Suppress raw config, response body, credentials and command diagnostics.
        print(json.dumps({'status':'COTURN_OBSERVATION_BLOCKED','turn_allocation_drain_verified':False}))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
