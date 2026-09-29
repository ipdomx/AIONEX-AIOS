"""Real ownership journals/files; explicitly synthetic mapper boundary in pytest.
Native libcryptsetup and kernel effects are tested separately in a QEMU guest.
"""
from __future__ import annotations

import ctypes
import dataclasses
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_fr06c5e_memory_loop as loop_fixture

from scripts.security import fr06c5_memory_mapper as m
from scripts.security.fr06c5_memory_transaction import (
    ActionUncertain,
    Journal,
    MemoryTransaction,
    TransitionRejected,
)
from scripts.security.fr06c5_memory_volatile_key import LockedKey, VolatileKeyRejected

case = loop_fixture.case
loop_opened = loop_fixture.opened
plan = loop_fixture.plan


class FakeMapper:
    def __init__(self, case):
        self.case = case
        self.value = None
        self.calls = []
        self.failure = None
        self.change = lambda x:x

    def sample(self, operation):
        return self.change(m.Runtime(self.case.context.boot_id,(11,12),(11,12),self.value))

    def create(self, fd, number, capacity, operation):
        self.calls.append('create')
        if self.failure == 'before':raise OSError('synthetic failure before effect')
        if self.failure != 'noop':
            self.value = m.MapperInfo(m.Device(253,9),m.mapper_uuid(operation),capacity//512,0,0,
                (m.Device(7,3),),(),0,0,m.CryptMetadata('PLAIN','aes-xts-plain64',512,512,'/dev/loop3',0,capacity//512,'read/write',()))
            self.case.kernel.holders = ('253:9',)
        if self.failure == 'after':raise OSError('synthetic failure after effect')

    def remove(self, operation):
        self.calls.append('remove')
        if self.failure == 'before':raise OSError('synthetic failure before remove')
        if self.failure != 'noop':
            self.value = None
            self.case.kernel.holders = ()
        if self.failure == 'after':raise OSError('synthetic failure after remove')


@contextmanager
def mapper_case(case):
    parent,journals = case.tmp/'mapper-state',case.tmp/'mapper-journal'
    parent.mkdir(mode=0o700);journals.mkdir(mode=0o700)
    with loop_opened(case) as (loop,_,tx):
        tx.apply_next();tx.verify_applied()
        kernel=FakeMapper(case)
        yield SimpleNamespace(loop=loop,kernel=kernel,parent=parent,journals=journals,case=case)


@contextmanager
def opened(c):
    with m.MapperAdapter.prepare(c.loop,c.parent,kernel=c.kernel) as adapter, Journal(c.journals,c.loop.operation,create=plan(adapter)) as journal:
        adapter.attach(journal)
        yield adapter,journal,MemoryTransaction(journal,adapter)


def test_apply_and_owned_explicit_remove_leave_parents_applied(case):
    with mapper_case(case) as c,opened(c) as (adapter,journal,tx):
        tx.apply_next();assert tx.verify_applied().phase=='applied'
        assert adapter.observe(adapter.step,adapter.operation).owned_by_operation
        tx.begin_rollback();tx.undo_next();assert tx.verify_restored().phase=='restored'
        assert c.kernel.calls==['create','remove']
        assert c.loop.journal.state().phase=='applied' and c.loop.backing.journal.state().phase=='applied'
        assert journal.state().pending is None


@pytest.mark.parametrize('direction',['apply','undo'])
@pytest.mark.parametrize('timing',['before','after','noop'])
def test_unknown_native_result_no_replay_and_explicit_recovery(case,direction,timing):
    with mapper_case(case) as c:
        with opened(c) as (_,journal,tx):
            if direction=='undo':tx.apply_next();tx.begin_rollback()
            c.kernel.failure=timing
            with pytest.raises(ActionUncertain):(tx.apply_next if direction=='apply' else tx.undo_next)()
            assert journal.state().pending==(direction,0)
            count=len(c.kernel.calls)
            with pytest.raises(ActionUncertain):(tx.apply_next if direction=='apply' else tx.undo_next)()
            assert len(c.kernel.calls)==count
        c.kernel.failure=None
        with m.MapperAdapter.load(c.loop,c.parent,kernel=c.kernel) as adapter,Journal(c.journals,c.loop.operation) as journal:
            adapter.attach(journal);tx=MemoryTransaction(journal,adapter)
            tx.reconcile_pending();assert len(c.kernel.calls)==count
            if direction=='apply':
                with pytest.raises(TransitionRejected):tx.apply_next()
                tx.begin_rollback()
            if journal.state().applied:tx.undo_next()
            assert tx.verify_restored().phase=='restored'


@pytest.mark.parametrize('field,value',[('holders',(m.Device(253,10),)),('mounts',1),('swaps',1)])
def test_consumers_prevent_remove_without_native_call(case,field,value):
    with mapper_case(case) as c,opened(c) as (_,journal,tx):
        tx.apply_next();tx.begin_rollback()
        c.kernel.value=dataclasses.replace(c.kernel.value,**{field:value})
        with pytest.raises(ActionUncertain):tx.undo_next()
        assert c.kernel.calls==['create']
        c.kernel.value=dataclasses.replace(c.kernel.value,**{field:() if field=='holders' else 0})
        tx.reconcile_pending();tx.undo_next();assert tx.verify_restored().phase=='restored'
        assert journal.state().pending is None


@pytest.mark.parametrize('field,value',[('uuid','CRYPT-PLAIN-foreign'),('sectors',9),('readonly',1),('suspended',1),
    ('slaves',(m.Device(7,4),)),('device',m.Device(253,12)),('mounts',-1),('swaps',True),('holders',[])])
def test_wrong_mapper_after_reopening_never_adopted(case,field,value):
    with mapper_case(case) as c:
        with opened(c) as (_,_,tx):tx.apply_next()
        c.kernel.value=dataclasses.replace(c.kernel.value,**{field:value})
        with m.MapperAdapter.load(c.loop,c.parent,kernel=c.kernel) as adapter,Journal(c.journals,c.loop.operation) as journal:
            adapter.attach(journal);tx=MemoryTransaction(journal,adapter);tx.begin_rollback()
            with pytest.raises(m.MapperRejected):tx.undo_next()
            assert c.kernel.calls==['create']


@pytest.mark.parametrize('field,value',[('kind','LUKS2'),('cipher','aes-cbc-plain'),('key_bits',256),('sector_size',4096),
    ('offset_sectors',1),('size_sectors',1),('mode','read-only'),('device_path','/dev/loop4'),('flags',('discards',))])
def test_wrong_crypto_profile_rejected(case,field,value):
    with mapper_case(case) as c,opened(c) as (adapter,_,tx):
        tx.apply_next()
        c.kernel.value=dataclasses.replace(c.kernel.value,crypt=dataclasses.replace(c.kernel.value.crypt,**{field:value}))
        with pytest.raises(m.MapperRejected):adapter.observe(adapter.step,adapter.operation)
        assert c.kernel.calls==['create']


@pytest.mark.parametrize('kind',['binding','lock','parent','context','loop-journal','loop-consumer'])
def test_parent_and_evidence_changes_prevent_effect(case,kind):
    with mapper_case(case) as c,opened(c) as (_,journal,tx):
        if kind=='binding':
            p=c.parent/c.loop.operation/'binding.json';p.write_text(p.read_text()+' ')
        elif kind=='lock':
            p=c.parent/'.mapper-owner.lock';p.rename(c.parent/'old');p.touch(mode=0o600)
        elif kind=='parent':c.parent.rename(case.tmp/'original');c.parent.mkdir(mode=0o700)
        elif kind=='context':case.owner.read_context=lambda:dataclasses.replace(case.context,maintenance_generation=37)
        elif kind=='loop-journal':c.loop.journal.append('rollback_started',{})
        else:case.kernel.mounts=1
        with pytest.raises((RuntimeError,OSError)):tx.apply_next()
        assert c.kernel.calls==[] and journal.state().pending is None


def test_mapper_lock_exclusive_and_direct_call_requires_intent(case):
    with mapper_case(case) as c,opened(c) as (adapter,_,_):
        with pytest.raises(BlockingIOError):m.MapperAdapter.load(c.loop,c.parent,kernel=c.kernel)
        with pytest.raises(m.MapperRejected):adapter.apply(adapter.step,adapter.operation)
        assert c.kernel.calls==[]


@pytest.mark.parametrize('field,value',[('boot_id','1'*36),('namespace',(1,2)),('init_namespace',(1,2))])
def test_namespace_or_boot_change_denies_before_binding(case,field,value):
    with mapper_case(case) as c:
        c.kernel.change=lambda sample:dataclasses.replace(sample,**{field:value})
        with pytest.raises(m.MapperRejected):m.MapperAdapter.prepare(c.loop,c.parent,kernel=c.kernel)
        assert c.kernel.calls==[]


def test_unknown_existing_device_not_adopted(case):
    with mapper_case(case) as c:
        c.kernel.create(c.loop.fd,3,16384,c.loop.operation)
        with pytest.raises(m.MapperRejected):m.MapperAdapter.prepare(c.loop,c.parent,kernel=c.kernel)
        assert c.kernel.calls==['create']


def test_locked_key_protected_single_use_and_closed():
    with LockedKey() as key:
        address=key._address
        flags=[]
        active=False
        for line in Path('/proc/self/smaps').read_text().splitlines():
            if '-' in line.split()[0]:
                left,right=(int(v,16) for v in line.split()[0].split('-'))
                active=left<=address<right
            elif active and line.startswith('VmFlags:'):flags=line.split()[1:]
        assert {'lo','dd','dc'}.issubset(flags)
        seen=[]
        key.use(lambda ptr,size:seen.append(size==64 and any(ctypes.string_at(ptr,size))))
        assert seen==[True]
        with pytest.raises(VolatileKeyRejected):key.use(lambda *_:None)
    assert key._address==0 and key._page is None and not key._locked
    with pytest.raises(VolatileKeyRejected):key.use(lambda *_:None)
    key.close()


def test_key_wiped_before_memory_unlock(monkeypatch):
    key=LockedKey();observed=[]
    original=key._lib.munlock
    def unlock(ptr,size):
        observed.append(not any(ctypes.string_at(ptr,size)))
        return original(ptr,size)
    monkeypatch.setattr(key._lib,'munlock',unlock)
    key.close();assert observed==[True]


def test_callback_failure_still_wipes_key():
    key=LockedKey()
    with pytest.raises(RuntimeError),key:
        key.use(lambda *_:(_ for _ in ()).throw(RuntimeError('synthetic consumer failure')))
    assert key._page is None and key._address==0


def test_memory_lock_denial_never_returns_unprotected_key(monkeypatch):
    import scripts.security.fr06c5_memory_volatile_key as v
    entropy_called=[]
    class Fn:
        def __init__(self,result,side=None): self.result,self.side=result,side
        def __call__(self,*args):
            if self.side:self.side()
            return self.result
    class Deny:
        def __init__(self):
            self.mlock=Fn(-1); self.munlock=Fn(0); self.getrandom=Fn(64,lambda:entropy_called.append(True))
    monkeypatch.setattr(v.ctypes,'CDLL',lambda *_a,**_k:Deny())
    with pytest.raises(VolatileKeyRejected,match="Memory locking failed"):
        LockedKey()
    assert entropy_called==[]


def test_mapper_status_header_cannot_be_rebound_to_another_operation():
    operation='11111111-1111-4111-8111-111111111111'
    status=f'/dev/mapper/{m.mapper_name(operation)} is active.\n  type: PLAIN\n  cipher: aes-xts-plain64\n  keysize: 512 bits\n  sector size: 512\n  device: /dev/loop3\n  offset: 0 sectors\n  size: 32 sectors\n  mode: read/write\n'
    assert m.parse_mapper_status(status,operation).key_bits==512
    with pytest.raises(m.MapperRejected):m.parse_mapper_status(status,'22222222-2222-4222-8222-222222222222')


def test_mapper_and_loop_cannot_be_observed_in_different_namespaces(case):
    with mapper_case(case) as c:
        c.kernel.change=lambda sample:dataclasses.replace(sample,namespace=(101,102),init_namespace=(101,102))
        c.case.kernel.change=lambda sample:dataclasses.replace(sample,namespace=(11,12),init_namespace=(11,12))
        with pytest.raises(m.MapperRejected):m.MapperAdapter.prepare(c.loop,c.parent,kernel=c.kernel)
        assert c.kernel.calls==[]


def test_key_use_in_real_forked_child_is_denied():
    with LockedKey() as key:
        pid=os.fork()
        if pid==0:
            try:key.use(lambda *_:None)
            except VolatileKeyRejected:os._exit(0)
            os._exit(2)
        _,status=os.waitpid(pid,0)
        assert os.waitstatus_to_exitcode(status)==0
        called=[];key.use(lambda *_:called.append(True));assert called==[True]


@pytest.mark.parametrize('failure',['zero','partial','negative'])
def test_entropy_failure_wipes_partial_mapping(monkeypatch,failure):
    import scripts.security.fr06c5_memory_volatile_key as v
    lib=ctypes.CDLL(None,use_errno=True)
    native_unlock=lib.munlock
    native_unlock.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    native_unlock.restype=ctypes.c_int
    wipes=[];calls=[]
    class Function:
        def __init__(self,fn):self.fn=fn
        def __call__(self,*args):return self.fn(*args)
    def random(ptr,size,flags):
        calls.append(size)
        if failure=='partial' and len(calls)==1:
            ctypes.memset(ptr,127,8);return 8
        ctypes.set_errno(5)
        return -1 if failure=='negative' else 0
    def unlock(ptr,size):
        wipes.append(not any(ctypes.string_at(ptr,size)))
        return native_unlock(ptr,size)
    lib.getrandom=Function(random);lib.munlock=Function(unlock)
    monkeypatch.setattr(v.ctypes,'CDLL',lambda *a,**kw:lib)
    with pytest.raises(VolatileKeyRejected):v.LockedKey()
    assert wipes==[True] and len(calls)==(2 if failure=='partial' else 1)


@pytest.mark.parametrize('failure',['init','format','activate',None])
def test_native_creation_uses_locked_pointer_and_never_reveals_key(case,monkeypatch,failure):
    k=m.LinuxMapperKernel();calls=[]
    class Library:
        def crypt_init(self,target,path):
            calls.append(('init',path));target._obj.value=17
            return -5 if failure=='init' else 0
        def crypt_set_log_callback(self,*args):calls.append(('silent-log',))
        def crypt_format(self,context,kind,cipher,mode,uuid,key,size,params):
            calls.append(('format',kind,cipher,mode,uuid,key,size))
            assert params._obj.size==32 and params._obj.sector_size==512
            return -5 if failure=='format' else 0
        def crypt_activate_by_volume_key(self,context,name,pointer,size,flags):
            assert isinstance(pointer,ctypes.c_void_p) and pointer.value and size==64 and flags==0
            calls.append(('activate',name,size,flags))
            return -5 if failure=='activate' else 0
        def crypt_free(self,*args):calls.append(('free',))
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    monkeypatch.setattr(m.os,'fstat',lambda fd:SimpleNamespace(st_mode=__import__('stat').S_IFBLK,st_rdev=os.makedev(7,3)))
    monkeypatch.setattr(k,'sample',lambda op:m.Runtime(case.context.boot_id,(11,12),(11,12),None))
    monkeypatch.setattr(k,'_library',lambda:Library())
    monkeypatch.setattr(m.resource,'setrlimit',lambda which,limits:calls.append(('core-limit',limits[0])))
    if failure:
        with pytest.raises(m.MapperRejected):k.create(10,3,16384,case.operation)
    else:k.create(10,3,16384,case.operation)
    assert calls[-1]==('free',) and ('core-limit',0) in calls
    assert sum(c[0]=='activate' for c in calls)==int(failure in {None,'activate'})


@pytest.mark.parametrize('succeeds',[False,True])
def test_native_removal_is_single_key_free_task_without_retry_flags(case,monkeypatch,succeeds):
    calls=[]
    class Function:
        def __init__(self,name,result):self.name,self.result=name,result
        def __call__(self,*args):calls.append((self.name,args));return self.result
    lib=SimpleNamespace(**{n:Function(n,r) for n,r in {
        'dm_task_create':17,'dm_task_set_name':1,'dm_task_set_uuid':1,'dm_task_run':int(succeeds),
        'dm_task_get_errno':16,'dm_task_destroy':None,'dm_task_update_nodes':None}.items()})
    monkeypatch.setattr(m.ctypes,'CDLL',lambda *a,**kw:lib)
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    k=m.LinuxMapperKernel()
    monkeypatch.setattr(k,'sample',lambda op:SimpleNamespace(mapper=SimpleNamespace(uuid=m.mapper_uuid(op),holders=(),mounts=0,swaps=0)))
    if succeeds:k.remove(case.operation)
    else:
        with pytest.raises(OSError):k.remove(case.operation)
    assert sum(n=='dm_task_run' for n,_ in calls)==1
    assert calls[0]==('dm_task_create',(2,)) and calls[-1]==('dm_task_destroy',(17,))
    assert sum(n=='dm_task_set_uuid' for n,_ in calls)==0
    assert sum(n=='dm_task_update_nodes' for n,_ in calls)==int(succeeds)




def test_native_memory_lock_denial_uses_real_process_limit():
    code = "import resource\nfrom scripts.security.fr06c5_memory_volatile_key import LockedKey,VolatileKeyRejected\nresource.setrlimit(resource.RLIMIT_MEMLOCK,(0,0))\ntry: LockedKey()\nexcept VolatileKeyRejected: print('DENIED_BEFORE_ENTROPY')\nelse: raise SystemExit(1)\n"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["runuser", "-u", "nobody", "--", sys.executable, "-c", code], cwd=root,
                            capture_output=True, text=True, timeout=10, check=False,
                            env={**os.environ, "PYTHONPATH": str(root)})
    assert result.returncode == 0 and result.stdout.strip() == "DENIED_BEFORE_ENTROPY"
