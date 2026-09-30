#!/usr/bin/env python3
"""Pure final Studio drain verifier over two stable closed-authority observations."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID
class StudioFinalDrainBlocked(RuntimeError):pass
def _uuid(v):
 try:return isinstance(v,str) and str(UUID(v))==v
 except ValueError:return False
@dataclass(frozen=True)
class StudioFinalDrain:
 operation_id:str;generation:int;process_drain_verified:bool=True;full_host_closure:bool=False
def accept(*,first:dict[str,Any],second:dict[str,Any])->StudioFinalDrain:
 for x in (first,second):
  if not isinstance(x,dict) or set(x)!={"schema","admission","studio","backup"} or x["schema"]!="aionex.studio-drain-inputs.v1":raise StudioFinalDrainBlocked("exact Studio drain bundle required")
 a=first["admission"]
 if a!=second["admission"] or not _uuid(a.get("operation_id")) or type(a.get("generation")) is not int or a["generation"]<8 or a.get("status")!="closed" or a.get("enabled") is not False or a.get("full_host_closure") is not False:raise StudioFinalDrainBlocked("same closed authority required")
 for x in (first,second):
  s=x["studio"];b=x["backup"]
  if s.get("is_clear") is not True or s.get("blocker_count")!=0 or s.get("admission_closed") is not True or s.get("full_host_closure") is not False:raise StudioFinalDrainBlocked("Studio blockers remain")
  if any(b.get(k)!=0 for k in ("active_count","unresolved_count","expired_count","unfinished_count")) or b.get("operation_id")!=a["operation_id"] or b.get("generation")!=a["generation"] or b.get("full_host_closure") is not False:raise StudioFinalDrainBlocked("backup/runtime blockers remain")
 if first["studio"].get("executions")!=second["studio"].get("executions") or first["studio"].get("publications")!=second["studio"].get("publications"):raise StudioFinalDrainBlocked("Studio state changed between observations")
 return StudioFinalDrain(a["operation_id"],a["generation"])
