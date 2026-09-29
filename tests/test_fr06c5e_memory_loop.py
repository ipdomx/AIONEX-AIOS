"""Owned real files and journal with an explicit fake kernel boundary.
Native LOOP_CONFIGURE/CLR_FD acceptance is a separate no-network QEMU guest.
"""
from __future__ import annotations

import dataclasses
import errno
import os
import stat
import struct
import time
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.security import fr06c5_memory_loop as m
from scripts.security.fr06c5_memory_backing import BackingAdapter
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
    def __init__(self, context):
        self.context = context
        self.info = None
        self.holders = ()
        self.mounts = self.swaps = 0
        self.extra_consumers = ()
        self.events = []
        self.failure = None
        self.change = lambda sample: sample
        self.node_identity = {"st_dev": 1, "st_ino": 17, "st_mode": stat.S_IFBLK | 0o660,
                              "st_uid": 0, "st_gid": 6, "st_rdev": os.makedev(7, 3)}

    def open(self, number):
        return os.open('/dev/null', os.O_RDONLY | os.O_CLOEXEC)

    def node(self, fd, number):
        return self.node_identity.copy()

    def sample(self, fd, number, backing_fd):
        value = m.Runtime(self.context.boot_id, (11, 12), (11, 12), self.info,
                          0 if self.info is None else self.info.size_limit // 512, 0, 512,
                          self.holders, self.mounts, self.swaps, self.consumers(backing_fd))
        return self.change(value)

    def consumers(self, fd):
        return (() if self.info is None else ('loop3',)) + self.extra_consumers

    def configure(self, fd, backing_fd, number, capacity, marker):
        self.events.append('configure')
        if self.failure == 'before':
            raise OSError('synthetic ioctl failure before effect')
        if self.failure != 'noop':
            info = os.fstat(backing_fd)
            self.info = m.LoopInfo(info.st_dev, info.st_ino, number, 0, capacity, 0, marker)
        if self.failure == 'after':
            raise OSError('synthetic failure after kernel effect')

    def detach(self, fd):
        self.events.append('detach')
        if self.failure == 'before':
            raise OSError('synthetic detach failure')
        if self.failure == 'deferred':
            self.info = dataclasses.replace(self.info, flags=4)
        elif self.failure != 'noop':
            self.info = None
        if self.failure == 'after':
            raise OSError('synthetic failure after detach')


def plan(adapter):
    now = int(time.time())
    return Plan(adapter.operation, adapter.bound, (adapter.step,), now, now+300)


@pytest.fixture
def case(tmp_path):
    context = BoundContext('e'*40, str(uuid4()), str(uuid4()), 36, 'a'*64, 'b'*64, 'c'*64)
    kernel = FakeKernel(context)
    parent, state, journals, loops, loopjournals = [tmp_path/n for n in ('files','backing-state','backing-journal','loop-state','loop-journal')]
    for path in (parent,state,journals,loops,loopjournals):
        path.mkdir(mode=0o700)
    operation = str(uuid4())
    with BackingAdapter.prepare(parent/'random-swap.backing', state, operation, lambda: context,
                                capacity=16384, reserve=4096, reader=kernel) as owner, \
            Journal(journals, operation, create=plan(owner)) as journal:
        owner.attach(journal)
        tx = MemoryTransaction(journal, owner)
        tx.apply_next(); tx.verify_applied()
        yield SimpleNamespace(owner=owner, kernel=kernel, loops=loops, journals=loopjournals,
                              operation=operation, context=context, tmp=tmp_path)

@contextmanager
def opened(case):
    with m.LoopAdapter.prepare(case.owner, case.loops, number=3, kernel=case.kernel) as adapter, \
            Journal(case.journals, case.operation, create=plan(adapter)) as journal:
        adapter.attach(journal)
        yield adapter, journal, MemoryTransaction(journal, adapter)


def test_apply_and_verified_undo_preserve_backing(case):
    before = os.fstat(case.owner.fd)
    with opened(case) as (adapter, journal, tx):
        assert tx.apply_next().applied == 1
        assert tx.verify_applied().phase == 'applied'
        assert case.kernel.info.marker == 'AIONEX-C5E7:'+case.operation
        assert adapter.observe(adapter.step, case.operation).owned_by_operation
        tx.begin_rollback(); tx.undo_next()
        assert tx.verify_restored().phase == 'restored'
        assert journal.state().pending is None
    assert case.kernel.events == ['configure','detach']
    assert (before.st_dev,before.st_ino,before.st_size) == tuple(getattr(os.fstat(case.owner.fd),k) for k in ('st_dev','st_ino','st_size'))


@pytest.mark.parametrize('direction', ['apply','undo'])
@pytest.mark.parametrize('moment', ['before','after','noop'])
def test_uncertain_effect_is_not_replayed_and_readonly_reconciliation(case, direction, moment):
    with opened(case) as (adapter,journal,tx):
        if direction=='undo':
            tx.apply_next(); tx.begin_rollback()
        case.kernel.failure=moment
        with pytest.raises(ActionUncertain):
            (tx.apply_next if direction=='apply' else tx.undo_next)()
        calls=len(case.kernel.events)
        with pytest.raises(ActionUncertain):
            (tx.apply_next if direction=='apply' else tx.undo_next)()
        assert len(case.kernel.events)==calls
    case.kernel.failure=None
    with m.LoopAdapter.load(case.owner, case.loops, number=3, kernel=case.kernel) as adapter, Journal(case.journals,case.operation) as journal:
        adapter.attach(journal);tx=MemoryTransaction(journal,adapter)
        tx.reconcile_pending();assert len(case.kernel.events)==calls
        if direction=='apply':
            with pytest.raises(TransitionRejected):tx.apply_next()
            tx.begin_rollback()
        if journal.state().applied:tx.undo_next()
        assert tx.verify_restored().phase=='restored'


@pytest.mark.parametrize('field,value', [('holders',('253:9',)),('mounts',1),('swaps',1)])
def test_consumer_prevents_detach_without_ioctl(case, field, value):
    with opened(case) as (_,journal,tx):
        tx.apply_next();tx.begin_rollback();setattr(case.kernel,field,value)
        with pytest.raises(ActionUncertain):tx.undo_next()
        assert journal.state().pending==('undo',0)
        assert case.kernel.events==['configure']
        setattr(case.kernel,field,() if field=='holders' else 0)
        tx.reconcile_pending();tx.undo_next();assert tx.verify_restored().phase=='restored'


def test_deferred_autoclear_is_unknown_not_success(case):
    with opened(case) as (_,journal,tx):
        tx.apply_next();tx.begin_rollback();case.kernel.failure='deferred'
        with pytest.raises(ActionUncertain):tx.undo_next()
        with pytest.raises(m.LoopRejected):tx.reconcile_pending()
        assert journal.state().pending==('undo',0)
        assert case.kernel.info.flags==4


@pytest.mark.parametrize('field,value', [('marker','foreign'),('backing_inode',123),('backing_device',999),
    ('flags',4),('flags',1),('flags',8),('offset',512),('size_limit',8192),('number',4)])
def test_foreign_or_partial_loop_rejected_after_reopening(case,field,value):
    with opened(case) as (_,journal,tx):
        tx.apply_next()
        case.kernel.info=dataclasses.replace(case.kernel.info,**{field:value})
        count=len(case.kernel.events)
    with m.LoopAdapter.load(case.owner,case.loops,number=3,kernel=case.kernel) as adapter, Journal(case.journals,case.operation) as journal:
        adapter.attach(journal);tx=MemoryTransaction(journal,adapter);tx.begin_rollback()
        with pytest.raises(m.LoopRejected):tx.undo_next()
        assert len(case.kernel.events)==count


@pytest.mark.parametrize('state', ['before','after','restored'])
def test_additional_backing_consumer_invalidates_observation(case,state):
    with opened(case) as (adapter,_,tx):
        if state!='before':tx.apply_next()
        if state=='restored':tx.begin_rollback();tx.undo_next()
        case.kernel.extra_consumers=('loop4',)
        with pytest.raises(m.LoopRejected):adapter.observe(adapter.step,case.operation)


@pytest.mark.parametrize('field,value', [('boot_id','11111111-1111-4111-8111-111111111111'),
    ('namespace',(31,32)),('init_namespace',(31,32)),('readonly',1),('readonly',False),
    ('block_size',4096),('sectors',True),('holders',[]),('backing_consumers',[]),('mounts',-1)])
def test_kernel_sample_unknown_is_not_zero(case,field,value):
    case.kernel.change=lambda sample:dataclasses.replace(sample,**{field:value})
    with pytest.raises(m.LoopRejected):
        m.LoopAdapter.prepare(case.owner,case.loops,number=3,kernel=case.kernel)
    assert not case.kernel.events


def test_binding_lock_is_exclusive(case):
    with opened(case),pytest.raises(BlockingIOError):
        m.LoopAdapter.load(case.owner,case.loops,number=3,kernel=case.kernel)


@pytest.mark.parametrize('kind',['binding','lock','bundle','parent','node','backing'])
def test_identity_change_denies_before_any_kernel_effect(case,kind):
    with opened(case) as (_,journal,tx):
        if kind=='binding':
            path=case.loops/case.operation/'binding.json';path.write_text(path.read_text()+' ')
        elif kind=='lock':
            path=case.loops/'.loop-owner.lock';path.rename(case.loops/'old-lock');path.touch(mode=0o600)
        elif kind=='bundle':
            p=case.loops/case.operation;p.rename(case.loops/'old-bundle');p.mkdir(mode=0o700)
        elif kind=='parent':
            case.loops.rename(case.tmp/'old-parent');case.loops.mkdir(mode=0o700)
        elif kind=='node':case.kernel.node_identity['st_ino']+=1
        else:case.owner.target.chmod(0o644)
        with pytest.raises((OSError,RuntimeError)):tx.apply_next()
        assert not case.kernel.events and journal.state().pending is None


def test_backing_journal_must_be_finalized_and_remain_applied(case):
    case.owner.journal.append('rollback_started',{})
    with pytest.raises(m.LoopRejected,match='finalized'):
        m.LoopAdapter.prepare(case.owner,case.loops,number=3,kernel=case.kernel)
    assert not case.kernel.events


def test_context_change_blocks_effect(case):
    with opened(case) as (_,_,tx):
        case.owner.read_context=lambda:dataclasses.replace(case.context,maintenance_generation=37)
        with pytest.raises(RuntimeError):tx.apply_next()
        assert not case.kernel.events


def test_requires_exact_journal_and_direction(case):
    with m.LoopAdapter.prepare(case.owner,case.loops,number=3,kernel=case.kernel) as adapter:
        with pytest.raises(m.LoopRejected):adapter.apply(adapter.step,case.operation)
        with Journal(case.journals,case.operation,create=plan(adapter)) as journal:
            adapter.attach(journal)
            with pytest.raises(m.LoopRejected):adapter.apply(adapter.step,case.operation)
            with pytest.raises(m.LoopRejected):adapter.undo(adapter.step,case.operation)
            with pytest.raises(m.LoopRejected):adapter.observe(adapter.step,str(uuid4()))
            with pytest.raises(m.LoopRejected):adapter.observe(BoundStep(m.STEP,'a'*64,'b'*64),case.operation)
        assert not case.kernel.events


@pytest.mark.parametrize('number',[-1,1024,True,'3',None])
def test_invalid_loop_number_denied_before_kernel(case,number):
    with pytest.raises(m.LoopRejected):m.LoopAdapter.prepare(case.owner,case.loops,number=number,kernel=case.kernel)
    assert not case.kernel.events


def test_symlink_state_directory_is_not_followed(case):
    path=case.tmp/'linked';path.symlink_to(case.loops)
    with pytest.raises(OSError):m.LoopAdapter.prepare(case.owner,path,number=3,kernel=case.kernel)
    assert not case.kernel.events


def test_native_configure_uses_single_atomic_ioctl(case,monkeypatch):
    kernel=m.LinuxLoopKernel();calls=[]
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    monkeypatch.setattr(kernel,'node',lambda fd,number:case.kernel.node_identity)
    monkeypatch.setattr(m,'_metadata',lambda fd,capacity:case.owner.spec['file'])
    monkeypatch.setattr(m,'read_info',lambda fd:None)
    monkeypatch.setattr(m.fcntl,'ioctl',lambda *args:calls.append(args))
    marker='AIONEX-C5E7:'+case.operation
    kernel.configure(17,case.owner.fd,3,16384,marker)
    assert len(calls)==1 and calls[0][:2]==(17,m.LOOP_CONFIGURE)
    data=calls[0][2];assert len(data)==304
    assert struct.unpack('=II',data[:8])==(case.owner.fd,512)
    fields=m.LOOP_STRUCT.unpack(data[8:240])
    assert fields[3:9]==(0,16384,3,0,0,0)
    assert fields[9].rstrip(b'\0')==marker.encode()
    assert data[240:]==b'\0'*64


@pytest.mark.parametrize('error',[errno.ENXIO,errno.EPERM,errno.EIO,errno.ENODEV])
def test_only_enxio_is_unused_kernel_loop(monkeypatch,error):
    def ioctl(*_args):raise OSError(error,'synthetic')
    monkeypatch.setattr(m.fcntl,'ioctl',ioctl)
    if error==errno.ENXIO:assert m.read_info(17) is None
    else:
        with pytest.raises(OSError):m.read_info(17)


def test_read_loop_info_marker_and_erasure(monkeypatch):
    received=[]
    def ioctl(fd,op,data,mutate):
        assert op==m.LOOP_GET_STATUS64 and mutate
        data[:]=m.LOOP_STRUCT.pack(8,100,0,0,16384,3,0,0,0,b'owned'.ljust(64,b'\0'),b'\0'*64,b'\0'*32,0,0)
        received.append(data)
    monkeypatch.setattr(m.fcntl,'ioctl',ioctl)
    assert m.read_info(17)==m.LoopInfo(8,100,3,0,16384,0,'owned')
    assert received[0]==b'\0'*232


def test_no_new_step_reorders_existing_transaction_contract():
    from scripts.security.fr06c5_memory_transaction import STEPS
    assert STEPS.index('enable_memory_units')<STEPS.index(m.STEP)<STEPS.index('activate_encrypted_swap')
    assert len(STEPS)==len(set(STEPS))


@pytest.mark.parametrize('error',[errno.ENOTTY,errno.EINVAL,errno.EBUSY])
def test_atomic_kernel_failure_has_no_two_ioctl_fallback(case,monkeypatch,error):
    kernel=m.LinuxLoopKernel();calls=[]
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    monkeypatch.setattr(kernel,'node',lambda fd,number:case.kernel.node_identity)
    monkeypatch.setattr(m,'_metadata',lambda fd,capacity:case.owner.spec['file'])
    monkeypatch.setattr(m,'read_info',lambda fd:None)
    def fail(*args):
        calls.append(args[1]);raise OSError(error,'synthetic')
    monkeypatch.setattr(m.fcntl,'ioctl',fail)
    with pytest.raises(OSError):kernel.configure(17,case.owner.fd,3,16384,'AIONEX-C5E7:'+case.operation)
    assert calls==[m.LOOP_CONFIGURE]


@pytest.mark.parametrize('field,value',[(2,99),(6,1),(7,32),(9,b'X'*64),(9,b'first\0second'.ljust(64,b'\0'))])
def test_unsupported_loop_info_is_not_accepted(monkeypatch,field,value):
    fields=[8,100,0,0,16384,3,0,0,0,b'owned'.ljust(64,b'\0'),b'\0'*64,b'\0'*32,0,0]
    fields[field]=value;buffers=[]
    def ioctl(fd,op,data,mutate):
        data[:]=m.LOOP_STRUCT.pack(*fields);buffers.append(data)
    monkeypatch.setattr(m.fcntl,'ioctl',ioctl)
    with pytest.raises(m.LoopRejected):m.read_info(17)
    assert buffers[0]==b'\0'*232


def test_pending_intent_is_persisted_before_native_boundary(case):
    with opened(case) as (adapter,journal,tx):
        original=case.kernel.configure
        def wrapped(*args):
            assert journal.state().pending==('apply',0)
            records=sorted((case.journals/case.operation).glob('[0-9]*.json'))
            assert len(records)==2
            original(*args)
        case.kernel.configure=wrapped
        tx.apply_next();assert journal.state().pending is None
        assert adapter.observe(adapter.step,case.operation).owned_by_operation


def test_second_runtime_sample_change_leaves_intent_unsettled(case):
    with opened(case) as (_,journal,tx):
        calls=0
        def change(sample):
            nonlocal calls
            calls+=1
            return dataclasses.replace(sample,holders=('253:9',)) if calls>=3 else sample
        case.kernel.change=change
        with pytest.raises((ActionUncertain,m.LoopRejected)):tx.apply_next()
        assert case.kernel.events==[] and journal.state().pending==('apply',0)


def test_backing_extent_metadata_growth_is_not_inode_replacement(case,monkeypatch):
    from scripts.security import fr06c5_memory_backing as backing_module
    native_metadata=backing_module._metadata
    def allocated_with_more_extent_metadata(fd,capacity):
        row=native_metadata(fd,capacity)
        return {**row,'st_blocks':row['st_blocks']+8}
    monkeypatch.setattr(backing_module,'_metadata',allocated_with_more_extent_metadata)
    proof=case.owner.observe(case.owner.step,case.operation)
    assert proof.identity_verified and proof.owned_by_operation
    assert proof.fingerprint==case.owner.step.after_sha256


@pytest.mark.parametrize('field,value',[('st_ino',1),('st_dev',2),('st_mode',stat.S_IFREG|0o644),
    ('st_uid',0),('st_gid',0),('st_nlink',2),('st_size',8192),('st_blocks',0),('st_blocks',True)])
def test_allocation_comparison_still_rejects_identity_or_sparse_drift(case,field,value):
    original=case.owner.spec['file']
    if original[field]==value:value+=1
    assert not m.same_allocation({**original,field:value},original)


def test_fully_allocated_accounting_change_does_not_rewrite_historical_manifest(case):
    original=case.owner.spec['file'];larger={**original,'st_blocks':original['st_blocks']+8}
    manifest=case.owner.manifest_hash
    assert m.same_allocation(larger,original) and m.same_allocation(original,larger)
    assert not m.same_allocation({**larger,'unexpected':1},original)
    assert not m.same_allocation(None,original)
    assert case.owner.manifest_hash==manifest
