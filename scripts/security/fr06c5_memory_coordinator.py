#!/usr/bin/env python3
"""FR-06C5E coordinator for already-owned child journals.

This module never performs kernel effects itself and has no production CLI. It
orders independently journaled child transactions, records only durable phase
claims, and halts on uncertainty. Child adapters retain sole resource authority.
"""
from __future__ import annotations

import fcntl, hashlib, json, os, re, stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

HEX64=re.compile(r"[0-9a-f]{64}\Z")
NAME=re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")

class CoordinatorRejected(RuntimeError): pass
class CoordinatorUncertain(CoordinatorRejected): pass

class Child(Protocol):
    def state(self): ...
    def apply_next(self): ...
    def reconcile_pending(self): ...
    def begin_rollback(self): ...
    def undo_next(self): ...
    def verify_applied(self): ...
    def verify_restored(self): ...

@dataclass(frozen=True)
class ChildSpec:
    name:str; plan_sha256:str
    def __post_init__(self):
        if not NAME.fullmatch(self.name) or not HEX64.fullmatch(self.plan_sha256):
            raise ValueError("Bound child name and plan digest required")

@dataclass(frozen=True)
class Plan:
    operation:str; context_sha256:str; children:tuple[ChildSpec,...]; schema_version:int=1
    def __post_init__(self):
        if str(UUID(self.operation))!=self.operation or not HEX64.fullmatch(self.context_sha256): raise ValueError("Bound operation/context required")
        if self.schema_version!=1 or not self.children or len({x.name for x in self.children})!=len(self.children): raise ValueError("Explicit unique child order required")

class Coordinator:
    def __init__(self,parent:Path,plan:Plan,children:dict[str,Child]):
        self.parent=parent; self.plan=plan; self.children=children
        if tuple(children)!=tuple(x.name for x in plan.children): raise CoordinatorRejected("Exact ordered child set required")
        parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        st=parent.stat()
        if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o700: raise CoordinatorRejected("Private coordinator directory required")
        self.fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        self.lock=os.open(".lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.fd)
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self._bind()
    def close(self):
        for x in (self.lock,self.fd):
            if x>=0: os.close(x)
        self.lock=self.fd=-1
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def _canonical(self,v): return json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    def _plan(self): return {"schema_version":1,"operation":self.plan.operation,"context_sha256":self.plan.context_sha256,"children":[{"name":x.name,"plan_sha256":x.plan_sha256} for x in self.plan.children]}
    def _write_new(self,name,v):
        data=self._canonical(v)+b"\n"; fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.fd)
        try: os.write(fd,data); os.fsync(fd); os.fsync(self.fd)
        finally: os.close(fd)
    def _read(self,name):
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self.fd)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_nlink!=1 or st.st_size>65536: raise CoordinatorRejected("Unsafe coordinator record")
            raw=os.read(fd,65537)
            if len(raw)!=st.st_size or not raw.endswith(b"\n"): raise CoordinatorRejected("Incomplete coordinator record")
            return json.loads(raw)
        finally: os.close(fd)
    def _bind(self):
        expected=self._plan()
        try: actual=self._read("plan.json")
        except FileNotFoundError: self._write_new("plan.json",expected); actual=expected
        if actual!=expected: raise CoordinatorRejected("Coordinator plan changed")
        for spec in self.plan.children:
            child=self.children[spec.name]
            try:
                child_plan=child.journal.plan
                digest=hashlib.sha256(self._canonical(asdict(child_plan))).hexdigest()
                context_digest=hashlib.sha256(self._canonical(asdict(child_plan.context))).hexdigest()
            except (AttributeError, TypeError) as exc:
                raise CoordinatorRejected("Child must expose its authoritative typed journal plan") from exc
            if digest!=spec.plan_sha256: raise CoordinatorRejected("Child plan digest differs")
            if context_digest!=self.plan.context_sha256: raise CoordinatorRejected("Child bound context differs")
    def states(self): return {n:c.state() for n,c in self.children.items()}
    def apply_next(self):
        states=self.states()
        for spec in self.plan.children:
            s=states[spec.name]
            if s.pending is not None: raise CoordinatorUncertain(f"{spec.name} has unresolved intent")
            if s.phase in {"restored","applying"} and s.applied < len(self.children[spec.name].journal.plan.steps):
                # restored children cannot be silently re-applied under the same journal.
                if s.phase=="restored": raise CoordinatorRejected("Restored child requires a new operation")
                return spec.name,self.children[spec.name].apply_next()
            if s.phase=="applying": return spec.name,self.children[spec.name].verify_applied()
            if s.phase!="applied": raise CoordinatorRejected(f"{spec.name} not forward-compatible")
        raise CoordinatorRejected("All children already applied")
    def begin_rollback(self):
        states=self.states()
        if any(s.pending is not None for s in states.values()): raise CoordinatorUncertain("Resolve child intent before rollback")
        for spec in reversed(self.plan.children):
            s=states[spec.name]
            if s.phase in {"applied","halted"}: return spec.name,self.children[spec.name].begin_rollback()
            if s.phase=="applying" and s.applied: return spec.name,self.children[spec.name].begin_rollback()
            if s.phase not in {"restored","applying"}: raise CoordinatorRejected("Unknown child rollback state")
        raise CoordinatorRejected("Nothing applied")
    def rollback_next(self):
        states=self.states()
        for spec in reversed(self.plan.children):
            s=states[spec.name]
            if s.pending is not None: raise CoordinatorUncertain(f"{spec.name} has unresolved intent")
            if s.phase=="rolling_back":
                if s.applied: return spec.name,self.children[spec.name].undo_next()
                return spec.name,self.children[spec.name].verify_restored()
            if s.phase in {"applied","halted"} or (s.phase=="applying" and s.applied): raise CoordinatorRejected("Explicit begin_rollback required")
            if s.phase not in {"restored","applying"}: raise CoordinatorRejected("Unknown child rollback state")
        raise CoordinatorRejected("All children restored")
