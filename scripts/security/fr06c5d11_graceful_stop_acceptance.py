#!/usr/bin/env python3
"""Pure verifier for D11 graceful-stop evidence; performs no container control."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID
SERVICES=("telegram-worker","user-telegram-worker","operations-observer")
class GracefulStopBlocked(RuntimeError):pass
def _uuid(v):
 try:return isinstance(v,str) and str(UUID(v))==v
 except ValueError:return False
@dataclass(frozen=True)
class GracefulStopAcceptance:
 operation_id:str;generation:int;services:tuple[str,...]=SERVICES;graceful_stop_verified:bool=True;full_host_closure:bool=False
def accept(*,before:dict[str,Any],after:dict[str,Any])->GracefulStopAcceptance:
 for x in (before,after):
  if not isinstance(x,dict) or set(x)!={"authority","services"}:raise GracefulStopBlocked("exact evidence fields required")
 a=before["authority"]
 if a!=after["authority"] or not _uuid(a.get("operation_id")) or type(a.get("generation")) is not int or a["generation"]<8 or a.get("status")!="closed" or a.get("enabled") is not False or a.get("full_host_closure") is not False:raise GracefulStopBlocked("same closed authority required")
 if set(before["services"])!=set(SERVICES) or set(after["services"])!=set(SERVICES):raise GracefulStopBlocked("exact service set required")
 for name in SERVICES:
  b,c=before["services"][name],after["services"][name]
  if set(b)!={"container_id","restart_count","running","restart_policy"} or set(c)!={"container_id","restart_count","running","restart_policy","exit_code"}:raise GracefulStopBlocked("service evidence fields differ")
  if not isinstance(b["container_id"],str) or len(b["container_id"])!=64 or type(b["restart_count"]) is not int or b["running"] is not True:raise GracefulStopBlocked("running baseline required")
  if b["restart_policy"]!="no":raise GracefulStopBlocked("restart policy must be quiesced before stop")
  if c["container_id"]!=b["container_id"] or c["restart_count"]!=b["restart_count"] or c["running"] is not False or c["restart_policy"]!="no" or c["exit_code"]!=0:raise GracefulStopBlocked("same epoch clean stop required")
 return GracefulStopAcceptance(a["operation_id"],a["generation"])
