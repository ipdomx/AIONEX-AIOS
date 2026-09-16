#!/usr/bin/env python3
"""Guarded FR-06C3E Redis empty/reconciliation production cutover.

Redis is operational state, not DR authority. This executor never copies AOF.
It starts the encrypted candidate empty and restores only the exact previously
running client topology. A failure after any candidate client starts fails
closed instead of blindly resurrecting stale legacy Redis state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
from typing import Any

SCHEMA_VERSION = 1
SUBPART = "FR-06C3E"
PRODUCTION_ROOT = Path("/opt/AIOS")
DASHBOARD = PRODUCTION_ROOT / "web-dashboard"
PRODUCTION_ENV = DASHBOARD / ".env.production"
STATE_ROOT = Path("/var/lib/aionex/fr06c3-redis-cutover")
C3_STATE = Path("/var/lib/aionex/fr06c3")
C3D_CLOSEOUT = C3_STATE / "c3d-closeout.json"
LEGACY_VOLUME = "web-dashboard_redis_data"
CANDIDATE_VOLUME = "aionex-fr06-operations-vault"
CANDIDATE_SOURCE = Path("/mnt/aionex/fr06-operations-vault/redis")
TARGET = "/data"
REDIS_SERVICE = "redis"
MAX_EVIDENCE_AGE_SECONDS = 3600
MAX_PLAN_TTL_SECONDS = 900
MAX_WINDOW_SECONDS = 4 * 60 * 60
CUTOVER_CONFIRMATION = "FR06C3_PRODUCTION_REDIS_CUTOVER"
CANDIDATE_UID = 999
CANDIDATE_GID = 1000
CANDIDATE_MODE = 0o700
SENSITIVE_KEYS = {"key", "private_key", "recovery_key", "secret", "secret_key", "token", "passphrase", "password"}
ACCEPTED_COMPOSE = [
    DASHBOARD / "docker-compose.production.yml",
    DASHBOARD / "docker-compose.fr06-assets.yml",
    DASHBOARD / "docker-compose.fr06-admission.yml",
    DASHBOARD / "docker-compose.fr06-database.yml",
    DASHBOARD / "docker-compose.fr06-database-admission.yml",
    DASHBOARD / "docker-compose.fr06-backup.yml",
]
CANDIDATE_COMPOSE = [*ACCEPTED_COMPOSE, DASHBOARD / "docker-compose.fr06-operations.yml", DASHBOARD / "docker-compose.fr06-operations-admission.yml"]
CONTRACT_PATH = PRODUCTION_ROOT / "docs/project/receipts/FR-06C3C3-cutover-lifecycle-contract.json"


class CutoverError(RuntimeError): pass
class CutoverBlocked(CutoverError): pass


def _utc_now() -> datetime: return datetime.now(timezone.utc)
def _utc(value: datetime | None = None) -> str: return (value or _utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")
def _canonical(value: Any) -> bytes: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
def _digest(value: Any) -> str: return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    h=hashlib.sha256(); fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        with os.fdopen(fd,"rb",closefd=False) as f:
            for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    finally: os.close(fd)
    return h.hexdigest()


def _run(argv:list[str],*,cwd:Path|None=None,timeout:int=180)->str:
    try: r=subprocess.run(argv,cwd=cwd,capture_output=True,text=True,timeout=timeout,check=False)
    except (OSError,subprocess.SubprocessError) as exc: raise CutoverError(f"command unavailable or timed out: {argv[0]}") from exc
    if r.returncode!=0: raise CutoverError(f"{argv[0]} failed with exit code {r.returncode}; output withheld")
    return r.stdout.strip()


def _json(path:Path)->dict[str,Any]:
    try: v=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise CutoverError(f"cannot read JSON: {path}") from exc
    if not isinstance(v,dict): raise CutoverError("JSON object required")
    return v


def _private_regular(path:Path,label:str,maximum:int=8*1024*1024)->os.stat_result:
    try: info=os.lstat(path)
    except OSError as exc: raise CutoverBlocked(f"{label} unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1: raise CutoverBlocked(f"{label} must be single-link regular file")
    if info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o077 or not 1<=info.st_size<=maximum: raise CutoverBlocked(f"{label} ownership/mode/size unsafe")
    return info


def _parse_time(v:Any,label:str)->datetime:
    if not isinstance(v,str) or not v.endswith("Z"): raise CutoverBlocked(f"{label} must be RFC3339 UTC Z")
    try: return datetime.fromisoformat(v[:-1]+"+00:00").astimezone(timezone.utc)
    except ValueError as exc: raise CutoverBlocked(f"{label} invalid") from exc


def _walk_sensitive(v:Any,path:str="$")->None:
    if isinstance(v,dict):
        for k,c in v.items():
            n=str(k).casefold().replace("-","_")
            if n in SENSITIVE_KEYS or n.endswith("_key_material"): raise CutoverBlocked(f"embedded secret material rejected at {path}.{k}")
            _walk_sensitive(c,f"{path}.{k}")
    elif isinstance(v,list):
        for i,c in enumerate(v): _walk_sensitive(c,f"{path}[{i}]")


def _git_gate(root:Path,sha:str)->None:
    heads=_run(["git","rev-parse","HEAD","origin/main"],cwd=root).splitlines()
    if heads!=[sha,sha] or _run(["git","status","--porcelain=v1"],cwd=root): raise CutoverBlocked("production source is not clean exact accepted main")


def _evidence(path:Path,merge_sha:str)->dict[str,Any]:
    p=path.resolve(strict=True); _private_regular(p,"cutover evidence"); v=_json(p); _walk_sensitive(v)
    if v.get("schema_version")!=1 or v.get("subpart")!=SUBPART or v.get("environment")!="production" or v.get("production_authorization") is not True: raise CutoverBlocked("cutover evidence metadata invalid")
    now=_utc_now(); age=(now-_parse_time(v.get("observed_at"),"evidence observed_at")).total_seconds()
    if age< -300 or age>MAX_EVIDENCE_AGE_SECONDS: raise CutoverBlocked("cutover evidence stale/future-dated")
    source=v.get("source")
    if not isinstance(source,dict) or source.get("merge_sha")!=merge_sha or source.get("protected_pr_checks_passed") is not True or source.get("post_merge_main_checks_passed") is not True: raise CutoverBlocked("source CI evidence incomplete")
    recovery=v.get("recovery")
    if not isinstance(recovery,dict): raise CutoverBlocked("fresh recovery evidence missing")
    for k,w in {"backup_status":"completed","offsite_status":"completed","restore_status":"completed","restore_validated":True,"restore_offsite_validated":True}.items():
        if recovery.get(k)!=w: raise CutoverBlocked(f"fresh recovery gate failed: {k}")
    if (now-_parse_time(recovery.get("restore_completed_at"),"restore completed_at")).total_seconds()>MAX_EVIDENCE_AGE_SECONDS: raise CutoverBlocked("restore validation stale")
    ops=v.get("operations")
    if not isinstance(ops,dict): raise CutoverBlocked("operations preflight missing")
    for k in ("active_backup_jobs","active_restore_validations","active_durable_external_jobs","active_realtime_sessions","active_livekit_rooms"):
        if ops.get(k)!=0: raise CutoverBlocked(f"operations not drained: {k}")
    if ops.get("admission_closed") is not True or ops.get("cloudflare_changed") is not False: raise CutoverBlocked("admission/Cloudflare preflight unsafe")
    a=v.get("approvals")
    if not isinstance(a,dict) or a.get("owner_authorized") is not True: raise CutoverBlocked("owner authorization missing")
    start=_parse_time(a.get("window_starts_at"),"window start"); end=_parse_time(a.get("window_ends_at"),"window end")
    if end<=start or (end-start).total_seconds()>MAX_WINDOW_SECONDS or not start<=now<=end: raise CutoverBlocked("maintenance window invalid/inactive")
    return v


def _compose(files:list[Path],args:list[str],timeout:int=300)->str:
    cmd=["docker","compose","--env-file",str(PRODUCTION_ENV),"--profile","*"]
    for p in files: cmd += ["-f",str(p)]
    cmd += args; env=os.environ.copy(); env["AIOS_ENV_FILE"]=str(PRODUCTION_ENV)
    r=subprocess.run(cmd,cwd=DASHBOARD,env=env,capture_output=True,text=True,timeout=timeout,check=False)
    if r.returncode!=0: raise CutoverError(f"docker compose failed with exit code {r.returncode}; output withheld")
    return r.stdout.strip()


def _containers(service:str,running_only:bool=True)->list[dict[str,Any]]:
    cmd=["docker","ps"] if running_only else ["docker","ps","-a"]
    cmd += ["--filter","label=com.docker.compose.project=web-dashboard","--filter",f"label=com.docker.compose.service={service}","--format","{{.ID}}"]
    result=[]
    for cid in [x for x in _run(cmd).splitlines() if x.strip()]:
        item=json.loads(_run(["docker","inspect",cid]))[0]; state=item.get("State") or {}
        result.append({"id":cid,"name":str(item.get("Name","")).lstrip("/"),"image":str(item.get("Image","")),"health":str((state.get("Health") or {}).get("Status","none")),"running":bool(state.get("Running"))})
    return sorted(result,key=lambda r:r["name"])


def _contract(root:Path)->dict[str,Any]:
    path=root/"docs/project/receipts/FR-06C3C3-cutover-lifecycle-contract.json"; c=_json(path); clients=(c.get("redis_cutover") or {}).get("database_clients")
    if not isinstance(clients,list) or len(clients)!=26 or len(set(clients))!=26: raise CutoverBlocked("Redis client contract incomplete")
    return c


def _topology(root:Path)->dict[str,Any]:
    clients=_contract(root)["redis_cutover"]["database_clients"]; active={}
    for service in clients:
        rows=_containers(str(service))
        if rows: active[str(service)]=[r["id"] for r in rows]
    redis=_containers(REDIS_SERVICE)
    if len(redis)!=1 or redis[0]["health"] not in {"healthy","none"}: raise CutoverBlocked("exactly one healthy Redis container required")
    if not active: raise CutoverBlocked("no running Redis clients found")
    return {"redis_id":redis[0]["id"],"redis_image_id":redis[0]["image"],"active_clients":active,"active_service_count":len(active),"active_container_count":sum(len(v) for v in active.values())}


def _validate_c3_state(root:Path)->None:
    for p,label in ((C3_STATE/"provision-receipt.json","C3 provision receipt"),(C3_STATE/"recovery-proof.json","C3 recovery proof"),(C3_STATE/"header-custody.json","C3 header custody"),(C3D_CLOSEOUT,"C3D closeout")):
        _private_regular(p,label)
    p=_json(C3_STATE/"provision-receipt.json"); r=_json(C3_STATE/"recovery-proof.json"); h=_json(C3_STATE/"header-custody.json"); d=_json(C3D_CLOSEOUT)
    if p.get("status")!="empty_c3_vaults_provisioned_admission_closed": raise CutoverBlocked("C3 provision receipt unacceptable")
    if r.get("status")!="independent_c3_recovery_keys_proved": raise CutoverBlocked("C3 recovery proof unacceptable")
    if h.get("status")!="off_host_headers_verified" or h.get("object_count")!=2 or h.get("full_readback_verified") is not True: raise CutoverBlocked("C3 header custody unacceptable")
    if d.get("status")!="local_backup_cutover_accepted" or d.get("post_cutover_restore_validated") is not True: raise CutoverBlocked("C3D local-backup closeout missing")
    status=json.loads(_run(["python3",str(root/"scripts/security/fr06c3_vault_provision.py"),"status"]))
    rows={row["role"]:row for row in status.get("vaults",[])}
    if status.get("validation")!="FR06C3_EMPTY_VAULTS_READY" or int(rows.get("operations-vault",{}).get("running_consumer_count",-1))!=0: raise CutoverBlocked("operations-vault not ready with zero consumers")


def _volume_source(name:str)->Path:
    value=json.loads(_run(["docker","volume","inspect",name]));
    if not isinstance(value,list) or len(value)!=1: raise CutoverBlocked(f"volume unavailable: {name}")
    p=Path(str(value[0].get("Mountpoint",""))).resolve(strict=True)
    if not p.is_dir() or p.is_symlink(): raise CutoverBlocked(f"volume path unsafe: {name}")
    return p


def _sealed(path:Path)->bool:
    r=subprocess.run(["findmnt","-n","-o","OPTIONS","--target",str(path)],capture_output=True,text=True,check=False)
    return r.returncode==0 and "ro" in set(r.stdout.strip().split(","))


def _seal(path:Path)->None:
    if _sealed(path): return
    _run(["mount","--bind",str(path),str(path)]); _run(["mount","-o","remount,bind,ro,nodev,nosuid,noexec",str(path)])
    if not _sealed(path): raise CutoverBlocked("legacy Redis read-only seal failed")


def _unseal(path:Path)->None:
    if _sealed(path): _run(["umount",str(path)])


def _dbsize(container_id:str)->int:
    return int(_run(["docker","exec",container_id,"redis-cli","DBSIZE"]).strip())


def _stop_ids(ids:list[str])->None:
    if ids: _run(["docker","stop","-t","60",*ids],timeout=120)


def _all_client_ids(topology:dict[str,Any])->list[str]: return [cid for s in sorted(topology["active_clients"]) for cid in topology["active_clients"][s]]


def _wait(service:str,expected:int)->None:
    deadline=time.time()+180
    while time.time()<deadline:
        rows=_containers(service)
        if len(rows)==expected and all(r["health"] not in {"starting","unhealthy"} for r in rows): return
        time.sleep(2)
    raise CutoverBlocked(f"service did not become healthy at expected scale: {service}")


def _start_redis(files:list[Path])->dict[str,Any]:
    _compose(files,["up","-d","--no-deps","--force-recreate",REDIS_SERVICE],timeout=240); _wait(REDIS_SERVICE,1); rows=_containers(REDIS_SERVICE)
    if len(rows)!=1: raise CutoverBlocked("candidate Redis topology invalid")
    return rows[0]


def _start_clients(files:list[Path],topology:dict[str,Any])->None:
    for service in sorted(topology["active_clients"]):
        count=len(topology["active_clients"][service]); args=["up","-d","--no-deps","--force-recreate"]
        if count>1: args += ["--scale",f"{service}={count}"]
        args += [service]; _compose(files,args,timeout=300)
    for service in sorted(topology["active_clients"]): _wait(service,len(topology["active_clients"][service]))


def _stop_candidate(topology:dict[str,Any])->None:
    services=sorted(topology["active_clients"])
    if services:
        try: _compose(CANDIDATE_COMPOSE,["stop","-t","60",*services],timeout=180)
        except Exception: pass
    try: _compose(CANDIDATE_COMPOSE,["stop","-t","60",REDIS_SERVICE],timeout=120)
    except Exception: pass


def _start_legacy(topology:dict[str,Any])->None:
    _start_redis(ACCEPTED_COMPOSE); _start_clients(ACCEPTED_COMPOSE,topology)


def _candidate_mount_ok()->bool:
    rows=_containers(REDIS_SERVICE)
    if len(rows)!=1:return False
    item=json.loads(_run(["docker","inspect",rows[0]["id"]]))[0]; matches=[m for m in item.get("Mounts",[]) if m.get("Destination")==TARGET]
    return len(matches)==1 and matches[0].get("Name")==CANDIDATE_VOLUME


def _harden_candidate_root()->dict[str,Any]:
    try:
        before=os.lstat(CANDIDATE_SOURCE)
    except OSError as exc:
        raise CutoverBlocked("candidate Redis root is unavailable after startup") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise CutoverBlocked("candidate Redis root is unsafe after startup")
    if (before.st_uid,before.st_gid)!=(CANDIDATE_UID,CANDIDATE_GID):
        raise CutoverBlocked("candidate Redis root ownership drifted after startup")
    try:
        os.chmod(CANDIDATE_SOURCE,CANDIDATE_MODE)
    except OSError as exc:
        raise CutoverBlocked("candidate Redis root could not be re-hardened after startup") from exc
    after=os.lstat(CANDIDATE_SOURCE)
    if stat.S_ISLNK(after.st_mode) or not stat.S_ISDIR(after.st_mode):
        raise CutoverBlocked("candidate Redis root became unsafe during hardening")
    if (after.st_uid,after.st_gid)!=(CANDIDATE_UID,CANDIDATE_GID) or stat.S_IMODE(after.st_mode)!=CANDIDATE_MODE:
        raise CutoverBlocked("candidate Redis root hardening did not hold")
    return {"uid":after.st_uid,"gid":after.st_gid,"mode":"0700"}


def _store(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700); fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try: os.write(fd,json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode()+b"\n"); os.fsync(fd)
    finally: os.close(fd)


def _lock()->int:
    STATE_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700); fd=os.open(STATE_ROOT/"operation.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as exc: os.close(fd); raise CutoverBlocked("another Redis cutover holds lock") from exc
    return fd


def _reserve(op:str,kind:str)->None: _store(STATE_ROOT/"reservations"/f"{op}.json",{"operation_id":op,"kind":kind,"reserved_at":_utc()})


def _preflight(root:Path,evidence_path:Path,merge_sha:str)->tuple[dict[str,Any],dict[str,Any]]:
    if os.geteuid()!=0 or root.resolve()!=PRODUCTION_ROOT: raise CutoverBlocked("production cutover requires root and /opt/AIOS")
    for p in [PRODUCTION_ENV,*ACCEPTED_COMPOSE,*CANDIDATE_COMPOSE]:
        if not p.is_file(): raise CutoverBlocked(f"required Compose source missing: {p.name}")
    _git_gate(root.resolve(),merge_sha); e=_evidence(evidence_path.resolve(),merge_sha); _validate_c3_state(root.resolve())
    legacy=_volume_source(LEGACY_VOLUME); candidate=CANDIDATE_SOURCE.resolve(strict=True)
    if not candidate.is_dir() or candidate.is_symlink() or any(candidate.iterdir()): raise CutoverBlocked("candidate Redis subpath must be empty before first cutover")
    topology=_topology(root.resolve()); consumers=[x for x in _run(["docker","ps","--filter",f"volume={LEGACY_VOLUME}","--format","{{.ID}}"]).splitlines() if x]
    if consumers!=[topology["redis_id"]] and set(consumers)!={topology["redis_id"]}: raise CutoverBlocked("legacy Redis volume consumer topology drifted")
    return e,{"topology":topology,"legacy_source":str(legacy),"candidate_source":str(candidate),"legacy_dbsize":_dbsize(topology["redis_id"])}


def inspect_runtime(root:Path)->dict[str,Any]:
    topology=_topology(root); return {"schema_version":1,"subpart":SUBPART,"observed_at":_utc(),**topology,"legacy_source":str(_volume_source(LEGACY_VOLUME)),"candidate_source":str(CANDIDATE_SOURCE),"legacy_dbsize":_dbsize(topology["redis_id"]),"read_only_inspection":True,"production_changed":False}


def create_plan(args:argparse.Namespace)->dict[str,Any]:
    if not 1<=args.ttl_seconds<=MAX_PLAN_TTL_SECONDS: raise CutoverBlocked("plan TTL outside bounded range")
    _,runtime=_preflight(args.root.resolve(),args.evidence.resolve(),args.merge_sha); now=_utc_now(); body={"schema_version":1,"subpart":SUBPART,"operation":"redis-empty-cutover","created_at":_utc(now),"expires_at":_utc(now+timedelta(seconds=args.ttl_seconds)),"nonce":secrets.token_hex(32),"merge_sha":args.merge_sha,"evidence_sha256":_file_digest(args.evidence.resolve()),**runtime,"legacy_aof_copy_permitted":False,"candidate_initial_dbsize":0,"admission_will_remain_closed":True,"cloudflare_change_permitted":False,"legacy_deletion_permitted":False}; body["plan_id"]=_digest(body); path=STATE_ROOT/"plans"/f"{body['plan_id']}.json"; _store(path,body); return {"decision":"redis_cutover_plan_ready","plan_id":body["plan_id"],"plan":str(path),"expires_at":body["expires_at"],"production_executed":False}


def _load_plan(path:Path,evidence:Path)->dict[str,Any]:
    _private_regular(path,"cutover plan");v=_json(path);pid=v.get("plan_id")
    if not isinstance(pid,str) or _digest({k:x for k,x in v.items() if k!="plan_id"})!=pid: raise CutoverBlocked("plan digest mismatch")
    if v.get("subpart")!=SUBPART or v.get("operation")!="redis-empty-cutover": raise CutoverBlocked("plan scope invalid")
    if _utc_now()>_parse_time(v.get("expires_at"),"plan expiry"): raise CutoverBlocked("plan expired")
    if v.get("evidence_sha256")!=_file_digest(evidence.resolve()): raise CutoverBlocked("evidence changed after planning")
    return v


def _write_result(op:str,body:dict[str,Any])->Path:
    result=dict(body);result["receipt_sha256"]=_digest(body);path=STATE_ROOT/"results"/f"{op}.json";_store(path,result);return path


def apply_cutover(args:argparse.Namespace)->dict[str,Any]:
    plan=_load_plan(args.plan.resolve(),args.evidence.resolve())
    if args.confirmation!=f"EXECUTE_FR06C3_REDIS_CUTOVER:{plan['plan_id']}" or args.confirm_production!=CUTOVER_CONFIRMATION: raise CutoverBlocked("exact Redis cutover confirmation required")
    _,runtime=_preflight(args.root.resolve(),args.evidence.resolve(),args.merge_sha)
    if plan.get("merge_sha")!=args.merge_sha or plan.get("topology")!=runtime["topology"] or plan.get("legacy_source")!=runtime["legacy_source"] or plan.get("legacy_dbsize")!=runtime["legacy_dbsize"]: raise CutoverBlocked("Redis topology/state changed after planning")
    op=plan["plan_id"]
    if (STATE_ROOT/"reservations"/f"{op}.json").exists(): raise CutoverBlocked("plan already consumed")
    topology=runtime["topology"];legacy=Path(runtime["legacy_source"]); fd=_lock();_reserve(op,"redis-cutover");candidate_started=False;clients_started=False
    try:
        _stop_ids(_all_client_ids(topology)); _stop_ids([topology["redis_id"]])
        for service in topology["active_clients"]:
            if _containers(service): raise CutoverBlocked("planned Redis client remained running")
        if _containers(REDIS_SERVICE): raise CutoverBlocked("legacy Redis remained running")
        _seal(legacy)
        redis=_start_redis(CANDIDATE_COMPOSE);candidate_started=True
        if not _candidate_mount_ok(): raise CutoverBlocked("candidate Redis mount acceptance failed")
        initial=_dbsize(redis["id"])
        if initial!=0: raise CutoverBlocked("candidate Redis did not start empty")
        root_hardening=_harden_candidate_root()
        _start_clients(CANDIDATE_COMPOSE,topology);clients_started=True
        if not _sealed(legacy): raise CutoverBlocked("legacy Redis seal drifted")
        body={"schema_version":1,"subpart":SUBPART,"operation":"redis-empty-cutover","operation_id":op,"status":"candidate_redis_started_admission_closed","completed_at":_utc(),"merge_sha":args.merge_sha,"topology":topology,"legacy_source":str(legacy),"candidate_source":str(CANDIDATE_SOURCE),"legacy_dbsize_at_cutover":runtime["legacy_dbsize"],"legacy_aof_copied":False,"candidate_initial_dbsize":0,"candidate_root_hardening":root_hardening,"legacy_read_only":True,"legacy_deleted":False,"candidate_clients_started":True,"admission_opened":False,"cloudflare_changed":False,"production_execution":True,"parent_fr06_completed":False};path=_write_result(op,body);return {"status":body["status"],"operation_id":op,"result":str(path),"admission_opened":False}
    except Exception as original:
        try:_stop_candidate(topology)
        except Exception:pass
        if not clients_started:
            # No candidate client has produced divergent operational state yet;
            # immediate pre-client rollback may safely return to the exact
            # quiesced pre-cutover Redis state.
            try:
                _unseal(legacy);_start_legacy(topology)
            except Exception as rb: raise CutoverError("Redis cutover failed and pre-client rollback failed; admission remains closed") from rb
            raise CutoverError("Redis cutover failed before client restart; legacy runtime restored and admission remains closed") from original
        # Once any candidate client has started, never resurrect stale legacy
        # AOF blindly. Preserve both sides and require explicit reconciliation.
        raise CutoverError("Redis cutover failed after candidate clients started; all candidate services stopped and manual empty/reconciliation recovery is required") from original
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)


def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="command",required=True)
    i=sub.add_parser("inspect-runtime");i.add_argument("--root",type=Path,default=PRODUCTION_ROOT)
    pl=sub.add_parser("plan-cutover");pl.add_argument("--root",type=Path,default=PRODUCTION_ROOT);pl.add_argument("--merge-sha",required=True);pl.add_argument("--evidence",type=Path,required=True);pl.add_argument("--ttl-seconds",type=int,default=600)
    ap=sub.add_parser("apply-cutover");ap.add_argument("--root",type=Path,default=PRODUCTION_ROOT);ap.add_argument("--merge-sha",required=True);ap.add_argument("--evidence",type=Path,required=True);ap.add_argument("--plan",type=Path,required=True);ap.add_argument("--confirmation",required=True);ap.add_argument("--confirm-production",default="")
    return p


def main()->int:
    a=parser().parse_args()
    try:
        if a.command=="inspect-runtime":r=inspect_runtime(a.root.resolve())
        elif a.command=="plan-cutover":r=create_plan(a)
        else:r=apply_cutover(a)
        print(json.dumps(r,ensure_ascii=False,sort_keys=True));return 0
    except CutoverBlocked as exc:print(json.dumps({"status":"blocked","reason":str(exc)},ensure_ascii=False,sort_keys=True));return 2
    except CutoverError as exc:print(json.dumps({"status":"error","reason":str(exc)},ensure_ascii=False,sort_keys=True));return 1

if __name__=="__main__":raise SystemExit(main())
