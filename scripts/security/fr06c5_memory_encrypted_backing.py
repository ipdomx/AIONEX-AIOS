"""C5E6 journal-bound creation/removal of the encrypted-swap backing file.

Only the prepare_encrypted_backing step is implemented here.  The adapter creates
one private regular file with posix_fallocate after a durable journal intent and
retains a descriptor plus create-only binding.  Undo removes only the exact inode
owned by this operation after exchanging it into private staging.  It never
creates loop/dm devices, keys, swap signatures, mounts, units, or production CLI.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from scripts.security.fr06c5_memory_config_files import (
    _dir_identity,
    _file,
    _open_dir,
    _write_new,
    rename_owned,
)
from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

STEP="prepare_encrypted_backing"
MIN_SIZE=16*1024*1024
MAX_SIZE=64*1024*1024*1024

class BackingStepRejected(TransitionRejected):
    pass

def _digest(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def _unique(pairs:list[tuple[str,Any]])->dict[str,Any]:
    out={}
    for k,v in pairs:
        if k in out: raise BackingStepRejected("Duplicate binding key")
        out[k]=v
    return out

def _identity(fd:int,size:int)->dict[str,int]:
    s=os.fstat(fd)
    if (not stat.S_ISREG(s.st_mode) or s.st_uid!=os.geteuid() or s.st_gid!=os.getegid()
        or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o600 or s.st_size!=size
        or os.listxattr(fd)):
        raise BackingStepRejected("Backing identity, ownership or size differs")
    return {k:int(getattr(s,k)) for k in ("st_dev","st_ino","st_mode","st_uid","st_gid","st_nlink","st_size","st_mtime_ns","st_ctime_ns")}

def _alloc(fd:int,size:int)->None:
    if not hasattr(os,"posix_fallocate"): raise BackingStepRejected("posix_fallocate unavailable")
    os.posix_fallocate(fd,0,size)
    os.fsync(fd)

def _allocated(fd:int,size:int)->bool:
    s=os.fstat(fd)
    # Sparse files are not accepted as encrypted-swap backing. st_blocks is
    # allocated 512-byte sectors and may exceed logical size for metadata.
    return s.st_size==size and s.st_blocks*512>=size

class EncryptedBackingAdapter:
    def __init__(self,parent:Path,name:str,state:Path,operation:str,context:Callable[[],BoundContext]):
        if str(UUID(operation))!=operation or "/" in name or name in {"",".",".."}:
            raise BackingStepRejected("Canonical operation and basename required")
        self.parent,self.name,self.state,self.operation=parent,name,state,operation
        self.read_context=context
        self.parent_fd=self.state_fd=self.lock_fd=self.bundle_fd=self.fd=-1
        self.journal:Journal|None=None
        try:
            self.parent_fd=_open_dir(parent);self.state_fd=_open_dir(state)
            self.parent_identity=_dir_identity(self.parent_fd,private=True)
            self.state_identity=_dir_identity(self.state_fd,private=True)
            self.lock_fd=os.open(".encrypted-backing.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600,dir_fd=self.state_fd)
            ls=os.fstat(self.lock_fd)
            if not stat.S_ISREG(ls.st_mode) or ls.st_uid!=os.geteuid() or stat.S_IMODE(ls.st_mode)!=0o600 or ls.st_nlink!=1 or ls.st_size:
                raise BackingStepRejected("Unsafe backing lock")
            self.lock_identity=(ls.st_dev,ls.st_ino)
            fcntl.flock(self.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            os.fsync(self.lock_fd);os.fsync(self.state_fd)
        except BaseException:
            self.close();raise

    @classmethod
    def prepare(cls,parent:Path,name:str,state:Path,operation:str,context:Callable[[],BoundContext],size:int)->Self:
        if type(size) is not int or not MIN_SIZE<=size<=MAX_SIZE or size%4096:
            raise BackingStepRejected("Explicit aligned bounded backing size required")
        a=cls(parent,name,state,operation,context)
        try:
            bound=context()
            if not isinstance(bound,BoundContext): raise BackingStepRejected("Independent typed context required")
            try: os.stat(name,dir_fd=a.parent_fd,follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise BackingStepRejected("Backing target already exists")
            os.mkdir(operation,0o700,dir_fd=a.state_fd);os.fsync(a.state_fd)
            a.bundle_fd=os.open(operation,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=a.state_fd)
            bundle=_dir_identity(a.bundle_fd,private=True)
            body={"schema":1,"operation":operation,"context":asdict(bound),"parent":a.parent_identity,
                  "state":a.state_identity,"bundle":bundle,"lock":list(a.lock_identity),
                  "name":name,"size":size}
            _write_new(a.bundle_fd,"binding.json",json.dumps(body,sort_keys=True).encode()+b"\n",0o600)
            a._load()
            if context()!=bound or a.observe(a.step,operation).fingerprint!=a.step.before_sha256:
                raise BackingStepRejected("Baseline changed during preparation")
            return a
        except BaseException:
            a.close();raise

    @classmethod
    def load(cls,parent:Path,name:str,state:Path,operation:str,context:Callable[[],BoundContext])->Self:
        a=cls(parent,name,state,operation,context)
        try:
            a.bundle_fd=os.open(operation,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=a.state_fd)
            a._load();a.context();return a
        except BaseException:
            a.close();raise

    def _load(self)->None:
        self.binding_identity,raw=_file(self.bundle_fd,"binding.json",private=True)
        b=json.loads(raw,object_pairs_hook=_unique)
        if (not isinstance(b,dict) or set(b)!={"schema","operation","context","parent","state","bundle","lock","name","size"}
            or b["schema"]!=1 or b["operation"]!=self.operation or b["parent"]!=self.parent_identity
            or b["state"]!=self.state_identity or b["bundle"]!=_dir_identity(self.bundle_fd,private=True)
            or b["lock"]!=list(self.lock_identity) or b["name"]!=self.name or type(b["size"]) is not int
            or not MIN_SIZE<=b["size"]<=MAX_SIZE or b["size"]%4096):
            raise BackingStepRejected("Backing binding differs")
        self.binding=b;self.bound=BoundContext(**b["context"]);self.binding_hash=hashlib.sha256(raw).hexdigest()
        self.step=BoundStep(STEP,self._fingerprint(None),self._fingerprint("owned"))
        self._identity()

    def _fingerprint(self,state:str|None)->str:
        return _digest({"binding":self.binding_hash,"state":state})

    def _named(self)->tuple[str|None,dict[str,int]|None]:
        try:
            fd=os.open(self.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=self.parent_fd)
        except FileNotFoundError:
            # After explicit undo the exact inode is retained privately rather
            # than deleted.  This still represents the baseline absent target.
            if self.bundle_fd>=0:
                try:
                    retired=os.open("retired-backing",os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=self.bundle_fd)
                except FileNotFoundError:return None,None
                try:
                    ident=_identity(retired,self.binding["size"])
                    if not _allocated(retired,self.binding["size"]): raise BackingStepRejected("Retired backing incomplete")
                    return None,ident
                finally:os.close(retired)
            return None,None
        try:
            ident=_identity(fd,self.binding["size"])
            if not _allocated(fd,self.binding["size"]): raise BackingStepRejected("Backing is sparse or incomplete")
            return "owned",ident
        finally:os.close(fd)

    def _identity(self)->None:
        for path,pinned in ((self.parent,self.parent_identity),(self.state,self.state_identity)):
            fd=_open_dir(path)
            try:
                if _dir_identity(fd,private=True)!=pinned: raise BackingStepRejected("Pinned backing directory changed")
            finally:os.close(fd)
        lock=os.stat(".encrypted-backing.lock",dir_fd=self.state_fd,follow_symlinks=False)
        if (lock.st_dev,lock.st_ino)!=self.lock_identity or lock.st_size or lock.st_nlink!=1: raise BackingStepRejected("Backing lock changed")
        bi,raw=_file(self.bundle_fd,"binding.json",private=True)
        names=set(os.listdir(self.bundle_fd))
        if not names.issubset({"binding.json","retired-backing"}) or "binding.json" not in names:
            raise BackingStepRejected("Backing bundle has unexpected content")
        if "retired-backing" in names:
            fd=os.open("retired-backing",os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=self.bundle_fd)
            try:
                if not _allocated(fd,self.binding["size"]): raise BackingStepRejected("Retired backing incomplete")
            finally: os.close(fd)
        if bi!=self.binding_identity or hashlib.sha256(raw).hexdigest()!=self.binding_hash:
            raise BackingStepRejected("Backing binding changed")
        if self.fd>=0:
            pinned=_identity(self.fd,self.binding["size"])
            named=self._named()[1]
            if named is None or (pinned["st_dev"],pinned["st_ino"])!=(named["st_dev"],named["st_ino"]):
                raise BackingStepRejected("Retained backing inode changed")

    def context(self)->BoundContext:
        self._identity();c=self.read_context()
        if c!=self.bound: raise BackingStepRejected("Independent context changed")
        return c

    def attach(self,journal:Journal)->None:
        if journal.plan.operation!=self.operation or journal.plan.context!=self.bound or journal.plan.steps!=(self.step,):
            raise BackingStepRejected("Single exact backing step required")
        self.journal=journal

    def observe(self,step:BoundStep,operation:str)->Observation:
        if step!=self.step or operation!=self.operation: raise BackingStepRejected("Foreign backing step")
        self._identity();state,_ident=self._named()
        if state=="owned":
            if self.fd<0:
                self.fd=os.open(self.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=self.parent_fd)
                _identity(self.fd,self.binding["size"])
            owned=True
        else:owned=False
        fp=self._fingerprint(state)
        return Observation(fp,fp in {step.before_sha256,step.after_sha256},owned)

    def _effect(self,step:BoundStep,operation:str,undo:bool)->None:
        self.context()
        if self.journal is None or step!=self.step or operation!=self.operation: raise BackingStepRejected("Attached journal required")
        st=self.journal.state();direction="undo" if undo else "apply"
        if st.pending!=(direction,0): raise BackingStepRejected("Durable direction-bound intent required")
        proof=self.observe(step,operation)
        expected=step.after_sha256 if undo else step.before_sha256
        if proof.fingerprint!=expected or (undo and not proof.owned_by_operation): raise BackingStepRejected("Backing state not owned")
        self.context()
        if not undo:
            fd=os.open(self.name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.parent_fd)
            try:
                _alloc(fd,self.binding["size"]);os.fchmod(fd,0o600);os.fsync(fd);os.fsync(self.parent_fd)
                self.fd=os.dup(fd)
            finally:os.close(fd)
        else:
            # Move the exact owned inode into operation-private state; never unlink
            # a pathname that may have been replaced by another actor.
            stage="retired-backing"
            rename_owned(self.parent_fd,self.name,self.bundle_fd,stage,exchange=False)
            os.fsync(self.parent_fd);os.fsync(self.bundle_fd)
            # Keep the retained descriptor through postcondition observation;
            # _named joins it to the privately retired inode after undo.
        self.context()
        outcome=self.observe(step,operation)
        if outcome.fingerprint!=(step.before_sha256 if undo else step.after_sha256):
            raise BackingStepRejected("Backing effect did not establish expected state")

    def apply(self,step:BoundStep,operation:str)->None:self._effect(step,operation,False)
    def undo(self,step:BoundStep,operation:str)->None:self._effect(step,operation,True)

    def close(self)->None:
        for attr in ("fd","bundle_fd","lock_fd","state_fd","parent_fd"):
            fd=getattr(self,attr)
            if fd>=0:os.close(fd);setattr(self,attr,-1)
    def __enter__(self)->Self:return self
    def __exit__(self,*args:object)->None:self.close()
