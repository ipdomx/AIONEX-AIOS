#!/usr/bin/env python3
"""Compose independent drain proofs without mutating the admission authority."""
from __future__ import annotations
import hashlib,json
from typing import Any
from uuid import UUID
class FullHostClosureBlocked(RuntimeError):pass
def _uuid(v):
 try:return isinstance(v,str) and str(UUID(v))==v
 except ValueError:return False
def _canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def certify(*,studio:Any,turn:Any,graceful:Any,operation_id:str,generation:int)->dict[str,Any]:
 if not _uuid(operation_id) or type(generation) is not int or generation<8:raise FullHostClosureBlocked('valid authority identity required')
 checks=((studio,'process_drain_verified'),(turn,'turn_allocation_drain_verified'),(turn,'credential_expiry_verified'),(graceful,'graceful_stop_verified'))
 for obj,key in checks:
  if getattr(obj,'operation_id',None)!=operation_id or getattr(obj,'generation',None)!=generation or getattr(obj,key,None) is not True or getattr(obj,'full_host_closure',None) is not False:raise FullHostClosureBlocked('component proof incomplete or differently bound')
 body={'schema':'aionex.fr06-full-host-closure.v1','operation_id':operation_id,'generation':generation,'studio_process_drain_verified':True,'turn_allocation_drain_verified':True,'turn_credential_expiry_verified':True,'telegram_observer_graceful_stop_verified':True,'component_full_host_flags_remain_false':True,'full_host_closure':True,'production_activation_authorized':False}
 body['receipt_sha256']=hashlib.sha256(_canon(body)).hexdigest();return body
