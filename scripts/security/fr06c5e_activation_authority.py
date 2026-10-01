#!/usr/bin/env python3
"""Issue a short-lived C5E activation authority from exact accepted evidence.

Pure verifier only: it never mutates swap, mounts, systemd, Docker, admission or
host state. The resulting receipt is bound to source commit, boot, maintenance
operation/generation and the three prerequisite receipt digests.
"""
from __future__ import annotations
import hashlib,json,re,time
from typing import Any
from uuid import UUID
HEX40=re.compile(r'[0-9a-f]{40}\Z');HEX64=re.compile(r'[0-9a-f]{64}\Z')
class ActivationBlocked(RuntimeError): pass
def _uuid(v):
 try:return isinstance(v,str) and str(UUID(v))==v
 except ValueError:return False
def _canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def issue(*,closure:dict[str,Any],source_commit:str,boot_id:str,host_state_receipt_sha256:str,preflight_sha256:str,boot_graph_sha256:str,now:int|None=None,ttl_seconds:int=900)->dict[str,Any]:
 if not HEX40.fullmatch(source_commit) or not _uuid(boot_id):raise ActivationBlocked('exact source and boot identity required')
 if any(not HEX64.fullmatch(x) for x in (host_state_receipt_sha256,preflight_sha256,boot_graph_sha256)):raise ActivationBlocked('exact prerequisite digests required')
 if type(ttl_seconds) is not int or not 60<=ttl_seconds<=900:raise ActivationBlocked('bounded activation TTL required')
 required={'schema','operation_id','generation','studio_process_drain_verified','turn_allocation_drain_verified','turn_credential_expiry_verified','telegram_observer_graceful_stop_verified','component_full_host_flags_remain_false','full_host_closure','production_activation_authorized','receipt_sha256'}
 if not isinstance(closure,dict) or set(closure)!=required:raise ActivationBlocked('exact full-host closure receipt required')
 body={k:v for k,v in closure.items() if k!='receipt_sha256'}
 if hashlib.sha256(_canon(body)).hexdigest()!=closure['receipt_sha256']:raise ActivationBlocked('closure digest differs')
 if closure['schema']!='aionex.fr06-full-host-closure.v1' or closure['full_host_closure'] is not True or closure['production_activation_authorized'] is not False or any(closure[k] is not True for k in ('studio_process_drain_verified','turn_allocation_drain_verified','turn_credential_expiry_verified','telegram_observer_graceful_stop_verified','component_full_host_flags_remain_false')):raise ActivationBlocked('full-host closure incomplete')
 if not _uuid(closure['operation_id']) or type(closure['generation']) is not int or closure['generation']<8:raise ActivationBlocked('maintenance identity invalid')
 issued=int(time.time()) if now is None else now
 if type(issued) is not int or issued<=0:raise ActivationBlocked('trusted issue time required')
 out={'schema':'aionex.fr06c5e-activation-authority.v1','source_commit':source_commit,'boot_id':boot_id,'operation_id':closure['operation_id'],'generation':closure['generation'],'full_host_closure_receipt_sha256':closure['receipt_sha256'],'host_state_receipt_sha256':host_state_receipt_sha256,'preflight_sha256':preflight_sha256,'boot_graph_sha256':boot_graph_sha256,'issued_at_epoch':issued,'expires_at_epoch':issued+ttl_seconds,'maintenance_closed':True,'full_host_closure':True,'production_activation_authorized':True}
 out['receipt_sha256']=hashlib.sha256(_canon(out)).hexdigest();return out
