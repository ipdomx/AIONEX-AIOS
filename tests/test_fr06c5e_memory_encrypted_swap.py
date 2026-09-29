"""Owned files/journals with an explicit fake kernel; native effects only in QEMU."""
from __future__ import annotations

import dataclasses
import json
import os
import struct
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
import test_fr06c5e_memory_mapper as fixture

from scripts.security import fr06c5_memory_encrypted_swap as m
from scripts.security.fr06c5_memory_transaction import (
    ActionUncertain,
    Journal,
    MemoryTransaction,
    TransitionRejected,
)

case = fixture.case


class FakeSwap:
    def __init__(self, c):
        self.c = c
        self.path = c.case.tmp/'block-metadata'
        self.path.write_bytes(b'\0' * 4096)
        self.active = False
        self.used = 0
        self.available = 10**9
        self.priority = 23
        self.failure = None
        self.calls = []
        self.change = lambda x: x

    def open(self, operation):
        return os.open(self.path, os.O_RDWR)

    def node(self, fd, operation):
        a = os.fstat(fd)
        return {'st_dev': a.st_dev, 'st_ino': a.st_ino, 'st_rdev': os.makedev(253,9), 'st_mode': 0o60600, 'st_uid': 0, 'st_gid': 0}

    def read_header(self, fd):
        return os.pread(fd, 4096, 0)

    def write_header(self, fd, content):
        self.calls.append('header')
        if self.failure == 'header-before': raise OSError('synthetic prewrite loss')
        if self.failure == 'header-partial':
            os.pwrite(fd,content[:1500],0)
            raise OSError('synthetic partial write')
        os.pwrite(fd,content,0)
        if self.failure == 'header-after': raise OSError('synthetic loss after write')

    def sync(self, fd):
        self.calls.append('sync')
        if self.failure == 'sync': raise OSError('synthetic fsync loss')
        os.fsync(fd)

    def sample(self, fd, operation):
        return self.change(m.SwapRuntime(self.c.case.context.boot_id,(11,12),(11,12),self.active,
             12288 if self.active else 0,self.used if self.active else 0,self.priority if self.active else 0,
             self.available,16384,4096))

    def activate(self, fd, priority):
        self.calls.append('activate')
        if self.failure == 'before': raise OSError('synthetic before syscall')
        if self.failure != 'noop':
            self.active = True
            self.c.kernel.value=dataclasses.replace(self.c.kernel.value,swaps=1)
        if self.failure == 'after': raise OSError('synthetic after syscall')

    def deactivate(self, fd):
        self.calls.append('deactivate')
        if self.failure == 'before': raise OSError('synthetic before syscall')
        if self.failure != 'noop':
            self.active=False
            self.c.kernel.value=dataclasses.replace(self.c.kernel.value,swaps=0)
        if self.failure == 'after': raise OSError('synthetic after syscall')


@contextmanager
def volume(case):
    with fixture.mapper_case(case) as c, fixture.opened(c) as (mapper,_,tx):
        tx.apply_next();tx.verify_applied()
        root,journals=case.tmp/'swap-state',case.tmp/'swap-journals'
        root.mkdir(mode=0o700);journals.mkdir(mode=0o700)
        yield SimpleNamespace(mapper=mapper,kernel=FakeSwap(c),root=root,journals=journals,c=c,case=case)


def prepare(v):
    return m.EncryptedSwapAdapter.prepare(v.mapper,v.root,priority=23,reserve=4096,kernel=v.kernel)


def reload(v):
    return m.EncryptedSwapAdapter.load(v.mapper,v.root,kernel=v.kernel)


@contextmanager
def activated_context(v):
    with prepare(v) as a:
        a.initialize_header()
        with Journal(v.journals,a.operation,create=fixture.plan(a)) as j:
            a.attach(j)
            yield a,j,MemoryTransaction(j,a)


def test_header_layout_matches_kernel_uapi():
    operation='11111111-1111-4111-8111-111111111111'
    data=m.header_bytes(operation,16*1024**2)
    assert len(data)==4096 and data[-10:]==b'SWAPSPACE2'
    assert struct.unpack_from('<III',data,1024)==(1,4095,0)
    assert data[1036:1052]==UUID(operation).bytes
    assert data[1052:1068]==b'AIONEX-C5E9'.ljust(16,b'\0')
    assert not any(data[:1024]) and not any(data[1068:-10])


@pytest.mark.parametrize('capacity',[True,0,-1,4096,16383,16385,64*1024**3+4096])
def test_bad_header_geometry(capacity):
    with pytest.raises(m.EncryptedSwapRejected):m.header_bytes('11111111-1111-4111-8111-111111111111',capacity)


def test_activation_and_undo_leave_prepared_header_and_owned_parents(case):
    with volume(case) as v,activated_context(v) as (a,j,tx):
        assert a.observe(a.step,a.operation).fingerprint==a.step.before_sha256
        assert tx.apply_next().applied==1 and tx.verify_applied().phase=='applied'
        assert a.observe(a.step,a.operation).owned_by_operation
        tx.begin_rollback();tx.undo_next();assert tx.verify_restored().phase=='restored'
        assert not v.kernel.active and v.kernel.calls==['header','sync','activate','deactivate']
        assert v.kernel.path.read_bytes()==a.header
        assert v.mapper.journal.state().phase=='applied' and j.state().pending is None


@pytest.mark.parametrize('direction',['apply','undo'])
@pytest.mark.parametrize('failure',['before','after','noop'])
def test_uncertain_kernel_return_never_replayed(case,direction,failure):
    with volume(case) as v:
        with activated_context(v) as (a,j,tx):
            if direction=='undo':tx.apply_next();tx.begin_rollback()
            v.kernel.failure=failure
            with pytest.raises(ActionUncertain):(tx.apply_next if direction=='apply' else tx.undo_next)()
            count=len(v.kernel.calls)
            with pytest.raises(ActionUncertain):(tx.apply_next if direction=='apply' else tx.undo_next)()
            assert len(v.kernel.calls)==count and j.state().pending==(direction,0)
        v.kernel.failure=None
        with reload(v) as a, Journal(v.journals,a.operation) as j:
            a.attach(j);tx=MemoryTransaction(j,a);tx.reconcile_pending()
            assert len(v.kernel.calls)==count
            if direction=='apply':
                with pytest.raises(TransitionRejected):tx.apply_next()
                tx.begin_rollback()
            if j.state().applied:tx.undo_next()
            assert tx.verify_restored().phase=='restored'


@pytest.mark.parametrize('failure',['header-before','header-after','header-partial','sync'])
def test_incomplete_header_preparation_is_preserved_not_reformatted(case,failure):
    with volume(case) as v:
        with prepare(v) as a:
            v.kernel.failure=failure
            with pytest.raises(OSError):a.initialize_header()
            assert (v.root/a.operation/'header-intent.json').is_file()
            assert not (v.root/a.operation/'header-ready.json').exists()
        v.kernel.failure=None
        with reload(v) as a:
            before=len(v.kernel.calls)
            with pytest.raises(m.EncryptedSwapRejected):a.initialize_header()
            assert len(v.kernel.calls)==before
            if failure in {'header-after','sync'}:
                a.reconcile_header()
                assert v.kernel.calls[-1]=='sync' and v.kernel.calls.count('header')==1
                with Journal(v.journals,a.operation,create=fixture.plan(a)) as j:
                    a.attach(j);tx=MemoryTransaction(j,a);tx.apply_next();tx.begin_rollback();tx.undo_next();tx.verify_restored()
            else:
                with pytest.raises(m.EncryptedSwapRejected):a.reconcile_header()
                assert len(v.kernel.calls)==before


def test_header_intent_is_durable_before_native_write(case,monkeypatch):
    with volume(case) as v, prepare(v) as a:
        original=v.kernel.write_header
        def write(fd,content):
            record=json.loads((v.root/a.operation/'header-intent.json').read_text())
            assert record['binding_sha256']==a.binding_hash and record['status']=='initialization-intent'
            original(fd,content)
        monkeypatch.setattr(v.kernel,'write_header',write)
        a.initialize_header()


def test_no_journal_or_no_prepared_header_never_activates(case):
    with volume(case) as v,prepare(v) as a:
        with pytest.raises(m.EncryptedSwapRejected):a.apply(a.step,a.operation)
        with Journal(v.journals,a.operation,create=fixture.plan(a)) as j, pytest.raises(m.EncryptedSwapRejected):
            a.attach(j)
        assert v.kernel.calls==[]


def test_preexisting_matching_header_not_adopted(case):
    with volume(case) as v,prepare(v) as a:
        v.kernel.path.write_bytes(a.header)
        with pytest.raises(m.EncryptedSwapRejected):a.initialize_header()
        assert v.kernel.calls==[] and not (v.root/a.operation/'header-intent.json').exists()


def test_header_cannot_be_initialized_twice_or_while_active(case):
    with volume(case) as v,activated_context(v) as (a,_,tx):
        with pytest.raises(m.EncryptedSwapRejected):a.initialize_header()
        tx.apply_next()
        with pytest.raises(m.EncryptedSwapRejected):a.initialize_header()
        with pytest.raises(m.EncryptedSwapRejected):a.reconcile_header()
        assert v.kernel.calls==['header','sync','activate']


@pytest.mark.parametrize('what',['binding','intent','ready','parent','lock','node','context','parent-journal','header'])
def test_changed_identity_or_preparation_denies_without_syscall(case,what):
    with volume(case) as v,activated_context(v) as (a,j,tx):
        if what in {'binding','intent','ready'}:
            n={'binding':'binding.json','intent':'header-intent.json','ready':'header-ready.json'}[what]
            p=v.root/a.operation/n;x=json.loads(p.read_text());x['operation']='22222222-2222-4222-8222-222222222222';p.write_text(json.dumps(x))
        elif what=='parent':v.root.rename(v.case.tmp/'old-root');v.root.mkdir(mode=0o700)
        elif what=='lock':p=v.root/'.encrypted-swap.lock';p.rename(v.root/'old-lock');p.touch(mode=0o600)
        elif what=='node':old=v.kernel.node;v.kernel.node=lambda fd,op:{**old(fd,op),'st_ino':7}
        elif what=='context':case.owner.read_context=lambda:dataclasses.replace(case.context,maintenance_generation=77)
        elif what=='parent-journal':v.mapper.journal.append('rollback_started',{})
        else:v.kernel.path.write_bytes(b'X'*4096)
        with pytest.raises((RuntimeError,OSError,ValueError)):tx.apply_next()
        assert v.kernel.calls==['header','sync'] and j.state().pending is None


@pytest.mark.parametrize('field,value',[('boot_id','wrong'),('namespace',(1,2)),('init_namespace',(1,2)),('namespace',[]),
    ('active',1),('capacity',8192),('page_size',8192),('available',-1),('used',1),('size',1),('priority',1)])
def test_bad_runtime_does_not_authorize_effect(case,field,value):
    with volume(case) as v,activated_context(v) as (_,_,tx):
        v.kernel.change=lambda sample:dataclasses.replace(sample,**{field:value})
        with pytest.raises(m.EncryptedSwapRejected):tx.apply_next()
        assert v.kernel.calls==['header','sync']


@pytest.mark.parametrize('field,value',[('holders',(m.Device(253,10),)),('mounts',1),('swaps',1)])
def test_foreign_consumers_block_activation(case,field,value):
    with volume(case) as v,activated_context(v) as (_,_,tx):
        v.c.kernel.value=dataclasses.replace(v.c.kernel.value,**{field:value})
        with pytest.raises(m.EncryptedSwapRejected):tx.apply_next()
        assert v.kernel.calls==['header','sync']


def test_swapoff_reserve_is_rechecked_and_failure_retains_pending(case):
    with volume(case) as v,activated_context(v) as (_,j,tx):
        tx.apply_next();tx.begin_rollback()
        v.kernel.available=8192;v.kernel.used=8192
        with pytest.raises(ActionUncertain):tx.undo_next()
        assert j.state().pending==('undo',0) and v.kernel.calls[-1]=='activate'
        v.kernel.available=16384
        tx.reconcile_pending();tx.undo_next();assert tx.verify_restored().phase=='restored'


def test_bound_priority_and_size_must_still_match(case):
    with volume(case) as v,activated_context(v) as (a,_,tx):
        tx.apply_next();v.kernel.priority=24
        with pytest.raises(m.EncryptedSwapRejected):a.observe(a.step,a.operation)


def test_cross_mapper_namespace_join_is_required_before_effect(case):
    with volume(case) as v:
        v.kernel.change=lambda sample:dataclasses.replace(sample,namespace=(21,22),init_namespace=(21,22))
        with pytest.raises(m.EncryptedSwapRejected):prepare(v)
        assert v.kernel.calls==[]


def test_exact_step_operation_and_foreign_plan_rejected(case):
    with volume(case) as v,prepare(v) as a:
        a.initialize_header()
        wrong=dataclasses.replace(fixture.plan(a),context=dataclasses.replace(a.bound,maintenance_generation=70))
        with Journal(v.journals,a.operation,create=wrong) as j,pytest.raises(m.EncryptedSwapRejected):a.attach(j)
        with pytest.raises(m.EncryptedSwapRejected):a.observe(a.step,'foreign')


def test_exclusive_preparation_lock_and_reopening(case):
    with volume(case) as v:
        with prepare(v) as a:
            a.initialize_header()
            with pytest.raises(BlockingIOError):reload(v)
        with reload(v) as a:
            a._prepared()
            with pytest.raises(FileExistsError):
                # Lock blocks first if retained; no create-only preparation reuse.
                os.mkdir(a.operation,dir_fd=a.parent_fd)


def test_symlink_header_receipt_not_followed(case):
    with volume(case) as v,activated_context(v) as (a,_,tx):
        p=v.root/a.operation/'header-ready.json';saved=v.case.tmp/'receipt';p.rename(saved);p.symlink_to(saved)
        with pytest.raises(OSError):tx.apply_next()
        assert v.kernel.calls==['header','sync']


@pytest.mark.parametrize('record',['header-intent.json','header-ready.json'])
def test_boolean_schema_is_not_a_valid_header_receipt(case,record):
    with volume(case) as v,activated_context(v) as (a,_,tx):
        p=v.root/a.operation/record
        value=json.loads(p.read_text());value['schema']=True;p.write_text(json.dumps(value))
        with pytest.raises(m.EncryptedSwapRejected):tx.apply_next()
        assert v.kernel.calls==['header','sync']


def test_activation_reserve_cannot_be_bypassed_after_preparation(case):
    with volume(case) as v,activated_context(v) as (_,j,tx):
        v.kernel.available=1
        with pytest.raises(ActionUncertain):tx.apply_next()
        assert v.kernel.calls==['header','sync'] and j.state().pending==('apply',0)


def test_preparation_reserve_denial_performs_no_volume_write(case):
    with volume(case) as v:
        v.kernel.available=1
        with pytest.raises(m.EncryptedSwapRejected):prepare(v)
        assert v.kernel.calls==[]


def test_inactive_header_baseline_is_not_equal_to_parent_mapper_removal(case):
    with volume(case) as v,activated_context(v) as (_a,j,tx):
        tx.apply_next();tx.begin_rollback();tx.undo_next()
        v.c.kernel.value=None;v.c.case.kernel.holders=()
        with pytest.raises(RuntimeError):tx.verify_restored()
        assert j.state().phase=='rolling_back'


def test_native_write_is_single_and_rejects_partial_progress(monkeypatch):
    calls=[]
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    monkeypatch.setattr(m.os,'fstat',lambda fd:SimpleNamespace(st_mode=0o60600))
    monkeypatch.setattr(m.os,'pwrite',lambda fd,data,offset:calls.append((fd,len(data),offset)) or 17)
    with pytest.raises(m.EncryptedSwapRejected):m.LinuxEncryptedSwapKernel().write_header(55,b'x'*4096)
    assert calls==[(55,4096,0)]
