"""Private filesystem/journal tests; kernel effects here are explicit doubles.
Native mount/unmount and process-loss acceptance run in a separate QEMU guest.
"""
from __future__ import annotations

import dataclasses
import os
import stat
import time
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.security import fr06c5_memory_tmpfs_stage as m
from scripts.security.fr06c5_memory_transaction import (
    ActionUncertain,
    BoundContext,
    BoundStep,
    Journal,
    MemoryTransaction,
    Plan,
    TransitionRejected,
)


class FakeKernel:
    def __init__(self, case):
        self.case = case
        self.active = False
        self.fault = None
        self.change = lambda value: value
        self.calls = []
        self.data = 0
        self.attributes = 0
        self.busy = False
        self.available = 1024**3

    def sample(self, bundle_fd, target):
        fd = os.open('mount', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=bundle_fd)
        try:
            visible = m._visible(fd)
            entries = len(os.listdir(fd))
        finally:
            os.close(fd)
        mount = None
        if self.active:
            mount = m.Mount(71, 13, m.Device(0, 331), '/', str(target), ('nodev','nosuid','rw'), (),
                            'tmpfs', m.marker(self.case.operation), ('nr_inodes=4096','rw','size=4096k'))
            visible = (os.makedev(0, 331), 1, stat.S_IFDIR | 0o1777, 0, 0)
            entries += self.data
        return self.change(m.Runtime(self.case.context.boot_id, (11,12), (11,12), mount, visible,
                                     entries, self.attributes, int(self.active), 0, self.available,
                                     4*1024**2 if self.active else 1024**3, 4096, int(bool(self.data)), True))

    def create(self, bundle_fd, operation, capacity, inodes):
        self.calls.append('create')
        assert operation == self.case.operation and capacity == 4*1024**2 and inodes == 4096
        if self.fault == 'before':
            raise OSError('synthetic before create')
        if self.fault != 'noop':
            self.active = True
        if self.fault == 'after':
            raise OSError('synthetic after create')

    def remove(self, bundle_fd):
        self.calls.append('remove')
        if self.fault == 'before' or self.busy:
            raise OSError(16, 'synthetic busy mount')
        if self.fault != 'noop':
            self.active = False
        if self.fault == 'after':
            raise OSError('synthetic after remove')


@pytest.fixture
def case(tmp_path):
    parent, journals = tmp_path/'stage', tmp_path/'journals'
    parent.mkdir(mode=0o700); journals.mkdir(mode=0o700)
    context = BoundContext('e'*40, str(uuid4()), str(uuid4()), 36, 'a'*64, 'b'*64, 'c'*64)
    c = SimpleNamespace(tmp=tmp_path, parent=parent, journals=journals, operation=str(uuid4()), context=context)
    c.kernel = FakeKernel(c)
    return c


def prepare(c, **kw):
    profile = {'capacity':4*1024**2, 'inodes':4096, 'reserve':16*1024**2, **kw}
    return m.TmpfsStageAdapter.prepare(c.parent,c.operation,lambda:c.context,kernel=c.kernel,**profile)


def plan(a):
    now=int(time.time())
    return Plan(a.operation,a.bound,(a.step,),now,now+300)


@contextmanager
def opened(c):
    with prepare(c) as a, Journal(c.journals,c.operation,create=plan(a)) as j:
        a.attach(j)
        yield a,j,MemoryTransaction(j,a)


@contextmanager
def reopened(c):
    with m.TmpfsStageAdapter.load(c.parent,c.operation,lambda:c.context,kernel=c.kernel) as a, Journal(c.journals,c.operation) as j:
        a.attach(j)
        yield a,j,MemoryTransaction(j,a)


def test_private_mount_and_explicit_recovery_preserve_original_directory(case):
    with opened(case) as (a,j,tx):
        original = a.target.stat()
        assert not a.observe(a.step,case.operation).owned_by_operation
        tx.apply_next(); assert tx.verify_applied().phase=='applied'
        assert a.observe(a.step,case.operation).owned_by_operation
        tx.begin_rollback();tx.undo_next();assert tx.verify_restored().phase=='restored'
        assert a.target.stat().st_ino==original.st_ino and stat.S_IMODE(a.target.stat().st_mode)==0o700
        assert case.kernel.calls==['create','remove'] and j.state().pending is None


@pytest.mark.parametrize('direction',['apply','undo'])
@pytest.mark.parametrize('failure',['before','after','noop'])
def test_interrupted_native_result_requires_reconciliation_and_no_replay(case,direction,failure):
    with opened(case) as (_,j,tx):
        if direction=='undo':tx.apply_next();tx.begin_rollback()
        case.kernel.fault=failure
        with pytest.raises(ActionUncertain):(tx.undo_next if direction=='undo' else tx.apply_next)()
        assert j.state().pending==(direction,0)
        calls=list(case.kernel.calls)
        with pytest.raises(ActionUncertain):(tx.undo_next if direction=='undo' else tx.apply_next)()
        assert case.kernel.calls==calls
    case.kernel.fault=None
    with reopened(case) as (_,j,tx):
        tx.reconcile_pending();assert case.kernel.calls==calls
        if direction=='apply':
            with pytest.raises(TransitionRejected):tx.apply_next()
            tx.begin_rollback()
        if j.state().applied:tx.undo_next()
        assert tx.verify_restored().phase=='restored'


@pytest.mark.parametrize('profile',[{'capacity':0},{'capacity':True},{'capacity':m.MAX_CAPACITY+4096},
    {'capacity':m.MIN_CAPACITY+1},{'inodes':0},{'inodes':True},{'inodes':1048577},{'reserve':0},{'reserve':True}])
def test_profile_denied_before_staging_or_kernel(case,profile):
    with pytest.raises(m.TmpfsRejected):prepare(case,**profile)
    assert not (case.parent/case.operation).exists() and case.kernel.calls==[]


@pytest.mark.parametrize('problem',['low-memory','namespace','boot','propagation','nested','entries','attributes'])
def test_prepare_requires_current_safe_baseline(case,problem):
    edits={'low-memory':{'available':0},'namespace':{'namespace':(91,92),'init_namespace':(91,92)},
           'boot':{'boot_id':str(uuid4())},'propagation':{'parent_private':False},'nested':{'nested':1},
           'entries':{'entries':1},'attributes':{'attributes':1}}
    if problem=='namespace':
        edits[problem]={'namespace':(91,92)}
    case.kernel.change=lambda sample:dataclasses.replace(sample,**edits[problem])
    with pytest.raises(m.TmpfsRejected):prepare(case)
    assert case.kernel.calls==[]


@pytest.mark.parametrize('kind',['binding','lock','lock-mode','parent','bundle','extra','context','target'])
def test_identity_and_context_changes_prevent_native_action(case,kind):
    with opened(case) as (a,j,tx):
        if kind=='binding':
            p=case.parent/case.operation/'binding.json';p.write_text(p.read_text()+' ')
        elif kind=='lock':
            p=case.parent/'.tmpfs-stage.lock';p.rename(case.parent/'old-lock');p.touch(mode=0o600)
        elif kind=='lock-mode':(case.parent/'.tmpfs-stage.lock').chmod(0o644)
        elif kind=='parent':case.parent.rename(case.tmp/'old-parent');case.parent.mkdir(mode=0o700)
        elif kind=='bundle':
            (case.parent/case.operation).rename(case.parent/'old-bundle');(case.parent/case.operation).mkdir(mode=0o700)
        elif kind=='extra':(case.parent/case.operation/'unexpected').write_text('x')
        elif kind=='context':case.context=dataclasses.replace(case.context,maintenance_generation=38)
        else:a.target.rename(case.parent/case.operation/'original');a.target.mkdir(mode=0o700)
        with pytest.raises((RuntimeError,OSError)):tx.apply_next()
        assert case.kernel.calls==[] and j.state().pending is None


@pytest.mark.parametrize('field,value',[('source','foreign'),('kind','ext4'),('root','/child'),
    ('device',m.Device(0,99)),('options',('rw',)),('options',('nodev','nosuid','ro')),
    ('optional',('shared:1',)),('target','/tmp')])
def test_foreign_or_modified_mount_is_never_adopted_after_reopening(case,field,value):
    with opened(case) as (_,_,tx):tx.apply_next()
    case.kernel.change=lambda s:dataclasses.replace(s,mount=dataclasses.replace(s.mount,**{field:value}))
    with reopened(case) as (_,_,tx):
        tx.begin_rollback()
        with pytest.raises(m.TmpfsRejected):tx.undo_next()
    assert case.kernel.calls==['create']


@pytest.mark.parametrize('field,value',[('aliases',2),('nested',1),('capacity',4096),('inodes',0),
    ('namespace',(101,102)),('init_namespace',(101,102)),('parent_private',False),
    ('visible',(os.makedev(0,331),1,stat.S_IFDIR|0o777,0,0)),('entries',True)])
def test_changed_native_profile_or_aliases_prevent_removal(case,field,value):
    with opened(case) as (_,_,tx):
        tx.apply_next();tx.begin_rollback()
        case.kernel.change=lambda s:dataclasses.replace(s,**{field:value})
        with pytest.raises(m.TmpfsRejected):tx.undo_next()
        assert case.kernel.calls==['create']


@pytest.mark.parametrize('problem',['data','attributes','deleted-blocks','busy'])
def test_never_drop_nonempty_or_busy_tmpfs(case,problem):
    with opened(case) as (_,j,tx):
        tx.apply_next();tx.begin_rollback()
        if problem=='data':case.kernel.data=1
        elif problem=='attributes':case.kernel.attributes=1
        elif problem=='deleted-blocks':case.kernel.change=lambda s:dataclasses.replace(s,used_blocks=1)
        else:case.kernel.busy=True
        with pytest.raises(m.TmpfsRejected if problem!='busy' else ActionUncertain):tx.undo_next()
        assert case.kernel.active and j.state().pending==(('undo',0) if problem=='busy' else None)
        case.kernel.data=case.kernel.attributes=0;case.kernel.busy=False;case.kernel.change=lambda s:s
        if j.state().pending is not None:tx.reconcile_pending()
        tx.undo_next();assert tx.verify_restored().phase=='restored'


def test_memory_reserve_rechecked_immediately_before_mount(case):
    with opened(case) as (_,j,tx):
        case.kernel.available=0
        with pytest.raises(ActionUncertain):tx.apply_next()
        assert case.kernel.calls==[] and j.state().pending==('apply',0)


def test_lock_serialization_and_foreign_intent_rejected(case):
    with opened(case) as (a,_,_):
        with pytest.raises(BlockingIOError):m.TmpfsStageAdapter.load(case.parent,case.operation,lambda:case.context,kernel=case.kernel)
        with pytest.raises(m.TmpfsRejected):a.apply(a.step,case.operation)
        with pytest.raises(m.TmpfsRejected):a.observe(a.step,str(uuid4()))
        with pytest.raises(m.TmpfsRejected):a.observe(BoundStep('activate_tmpfs','a'*64,'b'*64),case.operation)
        assert case.kernel.calls==[]


def test_replaced_or_populated_original_cannot_be_restored_verified(case):
    with opened(case) as (a,_,tx):
        tx.apply_next();tx.begin_rollback();tx.undo_next()
        (a.target/'foreign-data').write_bytes(b'keep this')
        with pytest.raises(m.TmpfsRejected):tx.verify_restored()
        assert (a.target/'foreign-data').read_bytes()==b'keep this'


def test_existing_operation_never_reset_or_reprepared(case):
    with prepare(case):pass
    before=sorted((case.parent/case.operation).iterdir())
    with pytest.raises(FileExistsError):prepare(case)
    assert sorted((case.parent/case.operation).iterdir())==before


def test_no_native_call_without_exact_attached_journal(case):
    with prepare(case) as a:
        with pytest.raises(m.TmpfsRejected):a.apply(a.step,case.operation)
        assert case.kernel.calls==[]


def test_native_unmount_uses_only_zero_flags_and_retains_error(case,monkeypatch):
    calls=[]
    class Function:
        def __call__(self,*args):calls.append(args);return -1
    lib=SimpleNamespace(umount2=Function())
    monkeypatch.setattr(m.ctypes,'CDLL',lambda *a,**kw:lib)
    monkeypatch.setattr(m.os,'geteuid',lambda:case.parent.stat().st_uid)
    # Only substitute the privilege predicate; the native call itself is a double.
    monkeypatch.setattr(m,'_dir_identity',lambda *a,**kw:{})
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    with pytest.raises(OSError):m.LinuxTmpfsKernel().remove(12)
    assert calls==[(b'/proc/self/fd/12/mount',0)]


def test_native_mount_has_fixed_bounded_profile_and_no_shell(case,monkeypatch):
    calls=[]
    class Function:
        def __call__(self,*args):calls.append(args);return 0
    lib=SimpleNamespace(mount=Function())
    monkeypatch.setattr(m.ctypes,'CDLL',lambda *a,**kw:lib)
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    monkeypatch.setattr(m,'_dir_identity',lambda *a,**kw:{})
    m.LinuxTmpfsKernel().create(12,case.operation,4*1024**2,4096)
    assert calls==[(m.marker(case.operation).encode(),b'/proc/self/fd/12/mount',b'tmpfs',6,
                    b'mode=1777,uid=0,gid=0,size=4194304,nr_inodes=4096')]


@pytest.mark.parametrize('content',[b'',b'partial',b'bad\0value\n',b'\xff\n'])
def test_kernel_text_never_turns_incomplete_or_garbled_data_into_clear(tmp_path,content):
    p=tmp_path/'kernel';p.write_bytes(content)
    with pytest.raises((m.TmpfsRejected,UnicodeError)):m._text(str(p))


def test_kernel_text_is_chunk_bounded_for_proc_sysctl(monkeypatch):
    import io
    requests=[]
    class Stream(io.BytesIO):
        def read(self,size=-1):
            requests.append(size)
            assert 0 <= size <= 4096
            return super().read(size)
    monkeypatch.setattr(m.Path,'open',lambda *a,**kw:Stream(b'123\n'))
    assert m._text('/synthetic/kernel')=='123\n' and requests==[4096,4096]


def test_kernel_text_rejects_overall_bound(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'MAX_TEXT',8)
    p=tmp_path/'kernel';p.write_bytes(b'123456789\n')
    with pytest.raises(m.TmpfsRejected):m._text(str(p))


@pytest.mark.parametrize('problem',['data','attributes','blocks'])
def test_final_staging_acceptance_requires_empty_instance(case,problem):
    with opened(case) as (_,_,tx):
        tx.apply_next()
        if problem=='data':case.kernel.data=1
        elif problem=='attributes':case.kernel.attributes=1
        else:case.kernel.change=lambda s:dataclasses.replace(s,used_blocks=1)
        with pytest.raises(m.TmpfsRejected):tx.verify_applied()
        assert case.kernel.active and case.kernel.calls==['create']
