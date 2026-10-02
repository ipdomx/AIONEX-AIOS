#!/usr/bin/env python3
"""Fail-closed journaled schema-8 maintenance authority transition.

Only explicit open/close transitions for the existing operation are supported.
The expected generation is bound before effect. A durable intent is fsynced
before the one backend transition call. If an intent already exists, the
operator performs read-only reconciliation and never repeats the transition.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT=Path("/opt/AIOS")
BASE=Path("/var/lib/aionex/fr06-final-maintenance")
SCHEMA="aionex.fr06-maintenance-authority-transition.v1"
READ=r'''import asyncio,json
from app.db.base import SessionLocal
from app.services.host_maintenance_admission import read_admission_snapshot
async def main():
 async with SessionLocal() as s:
  x=await read_admission_snapshot(s,required_scope="realtime_media_requests")
  print(json.dumps({"schema_version":x.schema_version,"scope":x.scope,"generation":x.generation,
   "status":x.status,"enabled":x.enabled,"operation_id":x.operation_id,
   "full_host_closure":x.full_host_closure}))
asyncio.run(main())'''
TRANSITION=r'''import asyncio,json,sys
from app.services.host_maintenance_admission import open_admission,close_admission
async def main():
 action,op,gen,reason=sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4]
 fn=open_admission if action=="open" else close_admission
 x=await fn(operation_id=op,expected_generation=gen,reason=reason)
 print(json.dumps({"schema_version":x.schema_version,"scope":x.scope,"generation":x.generation,
  "status":x.status,"enabled":x.enabled,"operation_id":x.operation_id,
  "full_host_closure":x.full_host_closure}))
asyncio.run(main())'''

class AuthorityTransitionHalted(RuntimeError): pass

def _uuid(v:Any)->bool:
 try:return isinstance(v,str) and str(UUID(v))==v
 except ValueError:return False

def _run(args:list[str],timeout:int=20)->str:
 p=subprocess.run(args,text=True,capture_output=True,check=False,timeout=timeout)
 if p.returncode: raise AuthorityTransitionHalted("fixed transition command failed; no retry")
 return p.stdout.strip()

def _canon(v:Any)->bytes:
 return (json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()

def _root(path:Path)->int:
 r=path.resolve(strict=False);b=BASE.resolve()
 if r==b or b not in r.parents: raise AuthorityTransitionHalted("private operation child required")
 path.mkdir(parents=True,mode=0o700,exist_ok=True)
 s=os.lstat(path)
 if not stat.S_ISDIR(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o700 or s.st_uid!=os.geteuid():
  raise AuthorityTransitionHalted("root-owned 0700 journal required")
 return os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)

def _write(fd:int,name:str,value:Any)->None:
 data=_canon(value)
 out=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=fd)
 try:
  n=0
  while n<len(data): n+=os.write(out,data[n:])
  os.fsync(out)
 finally:os.close(out)
 os.fsync(fd)

def _read(fd:int,name:str)->Any:
 f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
 try:
  s=os.fstat(f)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.geteuid() or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o600 or s.st_size>65536:
   raise AuthorityTransitionHalted("unsafe journal record")
  raw=os.read(f,s.st_size+1)
  if len(raw)!=s.st_size or not raw.endswith(b"\n"): raise AuthorityTransitionHalted("incomplete journal record")
  return json.loads(raw)
 finally:os.close(f)

def _exists(fd:int,name:str)->bool:
 try:os.stat(name,dir_fd=fd,follow_symlinks=False);return True
 except FileNotFoundError:return False

def _source()->dict[str,str]:
 head=_run(["git","-C",str(ROOT),"rev-parse","HEAD"])
 origin=_run(["git","-C",str(ROOT),"rev-parse","origin/main"])
 dirty=_run(["git","-C",str(ROOT),"status","--porcelain"])
 if head!=origin or dirty: raise AuthorityTransitionHalted("source is not clean exact origin/main")
 return {"source_commit":head}

def _snapshot()->dict[str,Any]:
 raw=_run(["docker","exec","web-dashboard-backend-1","/opt/venv/bin/python","-c",READ],20)
 try:v=json.loads(raw)
 except json.JSONDecodeError as e:raise AuthorityTransitionHalted("authority read invalid") from e
 required={"schema_version","scope","generation","status","enabled","operation_id","full_host_closure"}
 if not isinstance(v,dict) or set(v)!=required or v["schema_version"]!=8 or type(v["generation"]) is not int or v["generation"]<8 or v["full_host_closure"] is not False:
  raise AuthorityTransitionHalted("schema-8 authority required")
 if v["status"] not in {"open","closed"} or v["enabled"]!=(v["status"]=="open") or not _uuid(v["operation_id"]):
  raise AuthorityTransitionHalted("authority state malformed")
 return v

def _target(current:dict[str,Any],action:str,operation_id:str)->dict[str,Any]:
 status="open" if action=="open" else "closed"
 return {**current,"generation":current["generation"]+1,"status":status,"enabled":status=="open","operation_id":operation_id,"full_host_closure":False}

def execute(*,action:str,operation_id:str,expected_generation:int,reason:str,journal_root:Path)->dict[str,Any]:
 if action not in {"open","close"} or not _uuid(operation_id) or type(expected_generation) is not int or expected_generation<8:
  raise AuthorityTransitionHalted("explicit valid transition identity required")
 if not isinstance(reason,str) or not reason.strip() or len(reason)>500 or "\x00" in reason:
  raise AuthorityTransitionHalted("bounded transition reason required")
 fd=_root(journal_root)
 try:
  source=_source()
  current=_snapshot()
  desired_from="closed" if action=="open" else "open"
  if current["operation_id"]!=operation_id:
   raise AuthorityTransitionHalted("maintenance operation changed")
  if current.get("full_host_closure") is not False:
   raise AuthorityTransitionHalted("maintenance snapshot overclaims full-host closure")
  intent_name=f"{action}-g{expected_generation}-intent.json"
  accepted_name=f"{action}-g{expected_generation}-accepted.json"
  if _exists(fd,accepted_name):
   receipt=_read(fd,accepted_name)
   if _snapshot()!=receipt["after"]: raise AuthorityTransitionHalted("accepted authority no longer matches")
   return receipt
  if _exists(fd,intent_name):
   intent=_read(fd,intent_name)
   target=intent.get("target")
   now=_snapshot()
   if now==target:
    receipt={"schema":SCHEMA,"action":action,"operation_id":operation_id,"expected_generation":expected_generation,
             "source":source,"before":intent["before"],"after":now,"reconciled_after_intent":True,
             "replayed_transition":False}
    _write(fd,accepted_name,receipt);return receipt
   raise AuthorityTransitionHalted("unresolved transition intent; refusing replay")
  if current["generation"]!=expected_generation or current["status"]!=desired_from or current["enabled"]!=(desired_from=="open"):
   raise AuthorityTransitionHalted("current authority is not the exact transition baseline")
  target=_target(current,action,operation_id)
  intent={"schema":SCHEMA,"action":action,"operation_id":operation_id,"expected_generation":expected_generation,
          "reason":reason,"source":source,"before":current,"target":target,"automatic_retry":False}
  _write(fd,intent_name,intent)
  if _snapshot()!=current: raise AuthorityTransitionHalted("authority changed after durable intent")
  raw=_run(["docker","exec","web-dashboard-backend-1","/opt/venv/bin/python","-c",TRANSITION,action,operation_id,str(expected_generation),reason],30)
  try:returned=json.loads(raw)
  except json.JSONDecodeError as e:raise AuthorityTransitionHalted("transition result invalid; intent retained") from e
  observed=_snapshot()
  if returned!=target or observed!=target: raise AuthorityTransitionHalted("transition result uncertain; intent retained")
  receipt={"schema":SCHEMA,"action":action,"operation_id":operation_id,"expected_generation":expected_generation,
           "source":source,"before":current,"after":observed,"reconciled_after_intent":False,
           "replayed_transition":False}
  _write(fd,accepted_name,receipt);return receipt
 finally:os.close(fd)

def main()->int:
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=["open","close"])
 p.add_argument("--operation-id",required=True);p.add_argument("--expected-generation",required=True,type=int)
 p.add_argument("--reason",required=True);p.add_argument("--journal-root",required=True,type=Path);a=p.parse_args()
 try:r=execute(action=a.action,operation_id=a.operation_id,expected_generation=a.expected_generation,reason=a.reason,journal_root=a.journal_root)
 except (AuthorityTransitionHalted,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
  print(json.dumps({"status":"FR06_MAINTENANCE_AUTHORITY_TRANSITION_HALTED"},sort_keys=True));return 2
 print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
