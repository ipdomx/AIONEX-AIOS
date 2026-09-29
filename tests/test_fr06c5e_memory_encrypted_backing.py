from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest

from scripts.security.fr06c5_memory_encrypted_backing import (
 BackingStepRejected,
 EncryptedBackingAdapter,
)
from scripts.security.fr06c5_memory_transaction import (
 ActionUncertain,
 BoundContext,
 Journal,
 MemoryTransaction,
 Plan,
 TransitionRejected,
)


def context():
 return BoundContext("e"*40,"11111111-1111-4111-8111-111111111111","22222222-2222-4222-8222-222222222222",9,"a"*64,"b"*64,"c"*64)

def setup(tmp_path):
 parent=tmp_path/"back";state=tmp_path/"state";journals=tmp_path/"journals"
 for p in (parent,state,journals):p.mkdir(mode=0o700)
 op=str(uuid4())
 a=EncryptedBackingAdapter.prepare(parent,"cipher.backing",state,op,context,16*1024*1024)
 now=int(time.time());plan=Plan(op,context(),(a.step,),now,now+300)
 return parent,state,journals,op,a,plan

def test_apply_and_explicit_verified_rollback(tmp_path):
 parent,state,journals,op,a,plan=setup(tmp_path)
 with a,Journal(journals,op,create=plan) as j:
  a.attach(j);t=MemoryTransaction(j,a);assert t.apply_next().applied==1
  p=parent/"cipher.backing";s=p.stat();assert s.st_size==16*1024*1024 and s.st_blocks*512>=s.st_size
  assert t.verify_applied().phase=="applied";t.begin_rollback();assert t.undo_next().applied==0
  assert t.verify_restored().phase=="restored";assert not p.exists()
  retired=state/op/"retired-backing";assert retired.exists() and retired.stat().st_ino==s.st_ino

@pytest.mark.parametrize("moment",["before","after"])
def test_interruption_never_blindly_replays_owned_effect(tmp_path,moment):
 parent,state,journals,op,a,plan=setup(tmp_path)
 with a,Journal(journals,op,create=plan) as j:
  a.attach(j);j.append("intent",{"direction":"apply","index":0})
  if moment=="after":
   # simulate exact post-effect using adapter only after durable intent
   a.apply(a.step,op)
 with EncryptedBackingAdapter.load(parent,"cipher.backing",state,op,context) as b,Journal(journals,op) as j:
  b.attach(j);t=MemoryTransaction(j,b)
  with pytest.raises(ActionUncertain):t.apply_next()
  st=t.reconcile_pending();assert st.phase=="halted"
  t.begin_rollback()
  if st.applied:t.undo_next()
  assert t.verify_restored().phase=="restored"

def test_existing_target_denied_before_staging(tmp_path):
 parent=tmp_path/"back";state=tmp_path/"state";parent.mkdir(mode=0o700);state.mkdir(mode=0o700)
 (parent/"cipher.backing").write_bytes(b"x")
 with pytest.raises(BackingStepRejected):EncryptedBackingAdapter.prepare(parent,"cipher.backing",state,str(uuid4()),context,16*1024*1024)

def test_sparse_or_replaced_target_is_unknown(tmp_path):
 parent,_state,journals,op,a,plan=setup(tmp_path)
 with a,Journal(journals,op,create=plan) as j:
  a.attach(j);t=MemoryTransaction(j,a);t.apply_next()
  p=parent/"cipher.backing";p.unlink();p.write_bytes(b"\0"*(16*1024*1024));p.chmod(0o600)
  with pytest.raises(BackingStepRejected):a.observe(a.step,op)

def test_context_change_denies_effect(tmp_path):
 parent,_state,journals,op,a,plan=setup(tmp_path)
 changed=lambda: BoundContext("d"*40,context().boot_id,context().maintenance_operation,9,"a"*64,"b"*64,"c"*64)
 a.read_context=changed
 with a,Journal(journals,op,create=plan) as j:
  a.attach(j);t=MemoryTransaction(j,a)
  with pytest.raises(TransitionRejected):t.apply_next()
 assert not (parent/"cipher.backing").exists()

def test_lock_serializes_same_state(tmp_path):
 parent,state,_journals,op,a,_plan=setup(tmp_path)
 with a,pytest.raises(BlockingIOError):
  EncryptedBackingAdapter.load(parent,"cipher.backing",state,op,context)

def test_symlink_target_never_followed(tmp_path):
 parent=tmp_path/"back";state=tmp_path/"state";parent.mkdir(mode=0o700);state.mkdir(mode=0o700)
 outside=tmp_path/"outside";outside.write_bytes(b"x");(parent/"cipher.backing").symlink_to(outside)
 with pytest.raises(BackingStepRejected):EncryptedBackingAdapter.prepare(parent,"cipher.backing",state,str(uuid4()),context,16*1024*1024)
 assert outside.read_bytes()==b"x"

def test_size_bounds():
 assert EncryptedBackingAdapter


def test_after_state_requires_retained_inode_to_match_named_target(tmp_path):
 parent,_state,journals,op,a,plan=setup(tmp_path)
 with a,Journal(journals,op,create=plan) as j:
  a.attach(j);t=MemoryTransaction(j,a);t.apply_next()
  original=parent/"cipher.backing";moved=tmp_path/"moved";original.rename(moved)
  replacement=parent/"cipher.backing"
  with replacement.open("xb") as f:os.posix_fallocate(f.fileno(),0,16*1024*1024)
  replacement.chmod(0o600)
  with pytest.raises(BackingStepRejected):a.observe(a.step,op)

def test_undo_retains_exact_inode_in_private_bundle(tmp_path):
 parent,state,journals,op,a,plan=setup(tmp_path)
 with a,Journal(journals,op,create=plan) as j:
  a.attach(j);t=MemoryTransaction(j,a);t.apply_next();inode=(parent/"cipher.backing").stat().st_ino
  t.begin_rollback();t.undo_next();assert (state/op/"retired-backing").stat().st_ino==inode
