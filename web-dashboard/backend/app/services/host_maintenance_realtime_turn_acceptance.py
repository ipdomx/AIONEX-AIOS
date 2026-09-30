"""Promote bounded Coturn zero-allocation observations only after credential expiry.

This is a pure verifier. It does not scrape Coturn, sleep, mutate admission,
settle rows, or change provider state. Production collection remains an explicit
operator action under one closed authority generation.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

class TurnDrainAcceptanceUnavailable(RuntimeError):
    """TURN drain evidence is incomplete, stale, or differently bound."""

def _time(v: Any) -> datetime:
    if not isinstance(v,str): raise TurnDrainAcceptanceUnavailable("timestamp missing")
    try: d=datetime.fromisoformat(v)
    except ValueError as e: raise TurnDrainAcceptanceUnavailable("timestamp invalid") from e
    if d.utcoffset() is None: raise TurnDrainAcceptanceUnavailable("timestamp lacks timezone")
    return d

def _uuid(v: Any) -> bool:
    try:return isinstance(v,str) and str(UUID(v))==v
    except ValueError:return False

@dataclass(frozen=True,slots=True)
class TurnDrainAcceptance:
    operation_id:str; generation:int; authority_closed_at:datetime
    first_observed_at:datetime; final_observed_at:datetime; required_quiet_seconds:int
    credential_expiry_verified:bool=True; turn_allocation_drain_verified:bool=True
    full_host_closure:bool=False

def accept_turn_drain(*, first:dict[str,Any], final:dict[str,Any], max_credential_ttl_seconds:int) -> TurnDrainAcceptance:
    if type(max_credential_ttl_seconds) is not int or not 60<=max_credential_ttl_seconds<=3600:
        raise TurnDrainAcceptanceUnavailable("reviewed credential TTL required")
    required={"schema","operation_id","generation","authority","observed_at","samples","allocation_zero_observed","credential_expiry_verified","turn_allocation_drain_verified","full_host_closure"}
    for value in (first,final):
        if not isinstance(value,dict) or not required.issubset(value): raise TurnDrainAcceptanceUnavailable("observation fields incomplete")
        if value["schema"]!="aionex.coturn-allocation-observation.v1" or value["allocation_zero_observed"] is not True:
            raise TurnDrainAcceptanceUnavailable("zero allocation observation required")
        if value["credential_expiry_verified"] is not False or value["turn_allocation_drain_verified"] is not False or value["full_host_closure"] is not False:
            raise TurnDrainAcceptanceUnavailable("raw observation overclaims acceptance")
        if not isinstance(value["samples"],list) or len(value["samples"])!=2 or any(x!={"udp_allocations":0} for x in value["samples"]):
            raise TurnDrainAcceptanceUnavailable("two explicit zero UDP samples required")
    op=first["operation_id"]; gen=first["generation"]
    if not _uuid(op) or type(gen) is not int or gen<8 or final["operation_id"]!=op or final["generation"]!=gen:
        raise TurnDrainAcceptanceUnavailable("authority identity changed")
    if first["authority"]!=final["authority"]: raise TurnDrainAcceptanceUnavailable("authority changed across quiet interval")
    authority=first["authority"]
    if authority.get("operation_id")!=op or authority.get("generation")!=gen or authority.get("status")!="closed" or authority.get("enabled") is not False or authority.get("full_host_closure") is not False:
        raise TurnDrainAcceptanceUnavailable("closed authority required")
    closed=_time(authority.get("changed_at")); a=_time(first["observed_at"]); b=_time(final["observed_at"])
    quiet=timedelta(seconds=max_credential_ttl_seconds)
    if a<closed or b<a or b-closed<quiet or b-a<quiet:
        raise TurnDrainAcceptanceUnavailable("credential-expiry quiet interval incomplete")
    return TurnDrainAcceptance(op,gen,closed,a,b,max_credential_ttl_seconds)
