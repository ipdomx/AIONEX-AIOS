"""Real private bindings/journals; explicit mount doubles. Native acceptance is a separate VM."""
from __future__ import annotations

import dataclasses
import os
import time
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_fr06c5e_memory_tmpfs_stage as staged

from scripts.security import fr06c5_memory_tmpfs_publication as m
from scripts.security.fr06c5_memory_transaction import (
    ActionUncertain,
    Journal,
    MemoryTransaction,
    Plan,
)

case = staged.case


class FakeKernel:
    def __init__(self, c):
        self.c = c
        self.reference = False
        self.published = False
        self.failure = None
        self.calls = []
        self.change = lambda s: s
        self.busy = False

    def sample(self, stage, public_parent, public, bundle, reference):
        native_stage = self.c.case.kernel.sample(stage.bundle_fd, stage.target)
        fd = os.open(public.name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=public_parent)
        try:
            original = staged.m._visible(fd)
        finally:
            os.close(fd)
        fd = os.open('underlay', os.O_RDONLY | os.O_DIRECTORY, dir_fd=bundle)
        try:
            private = staged.m._visible(fd)
        finally:
            os.close(fd)
        root = m.Mount(13, 1, m.Device.number(original[0]), '/', '/', ('rw',), (), 'ext4', '/synthetic', ('rw',))
        mount = native_stage.mount
        if self.published:
            mount = dataclasses.replace(mount, target=str(public))
        rows = [root, mount]
        if self.reference:
            rows.append(m.Mount(90, 13, m.Device.number(original[0]), str(public), str(reference), ('rw',), (),
                                'ext4', '/synthetic', ('rw',)))
        return self.change(m.Runtime(self.c.case.context.boot_id, (11, 12), (11, 12), tuple(rows),
                                     tuple(stage.binding['original']) if self.published else native_stage.visible,
                                     native_stage.visible if self.published else original,
                                     original if self.reference else private))

    def effect(self, name, fn):
        self.calls.append(name)
        if self.failure == 'before' or (self.busy and name == 'release'):
            raise OSError(16, 'synthetic effect failed')
        if self.failure != 'noop':
            fn()
        if self.failure == 'after':
            raise OSError('synthetic interruption after effect')

    def preserve(self, public_parent, name, bundle):
        assert name == 'tmp'
        self.effect('preserve', lambda: setattr(self, 'reference', True))

    def move(self, source_parent, source_name, target_parent, target_name):
        undo = source_name == 'tmp'
        self.effect('return' if undo else 'publish', lambda: setattr(self, 'published', not undo))

    def release(self, bundle):
        self.effect('release', lambda: setattr(self, 'reference', False))


def plan(a):
    now = int(time.time())
    return Plan(a.operation, a.bound, a.steps, now, now + 300)


@contextmanager
def publication_case(case):
    public_parent, state, journals = (case.tmp / name for name in ('public-parent', 'publication-state', 'publication-journals'))
    for p in (public_parent, state, journals):
        p.mkdir(mode=0o700)
    public = public_parent / 'tmp'
    public.mkdir(mode=0o1777)
    public.chmod(0o1777)
    (public / 'old-canary').write_bytes(b'original-data')
    with staged.opened(case) as (stage, stage_journal, tx):
        tx.apply_next()
        tx.verify_applied()
        c = SimpleNamespace(case=case, stage=stage, stage_journal=stage_journal, public=public, state=state, journals=journals,
                            proof=m.FrozenEvidence(case.context, 'd' * 64, 'e' * 64, 'f' * 64))
        c.kernel = FakeKernel(c)
        yield c


@contextmanager
def opened(c, *, load=False):
    method = m.TmpfsPublicationAdapter.load if load else m.TmpfsPublicationAdapter.prepare
    with method(c.stage, c.public, c.state, lambda: c.proof, kernel=c.kernel) as a:
        kwargs = {} if load else {'create': plan(a)}
        with Journal(c.journals, c.case.operation, **kwargs) as j:
            a.attach(j)
            yield a, j, MemoryTransaction(j, a)


def test_preserve_publish_and_restore_keep_both_parent_journals_and_old_data(case):
    with publication_case(case) as c, opened(c) as (a, j, tx):
        original = c.public.stat()
        tx.apply_next()
        assert c.kernel.reference and not c.kernel.published
        tx.apply_next()
        assert tx.verify_applied().phase == 'applied'
        assert all(a.observe(s, a.operation).owned_by_operation for s in a.steps)
        tx.begin_rollback()
        tx.undo_next()
        assert c.kernel.reference and not c.kernel.published
        tx.undo_next()
        assert tx.verify_restored().phase == 'restored'
        assert c.stage_journal.state().phase == 'applied'
        assert c.kernel.calls == ['preserve', 'publish', 'return', 'release']
        assert c.public.stat().st_ino == original.st_ino and (c.public / 'old-canary').read_bytes() == b'original-data'
        assert j.state().pending is None and c.case.kernel.active


@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('direction', ['apply', 'undo'])
@pytest.mark.parametrize('failure', ['before', 'after', 'noop'])
def test_interrupted_effect_is_observed_not_repeated_and_explicitly_recovered(case, index, direction, failure):
    with publication_case(case) as c:
        with opened(c) as (_, j, tx):
            if direction == 'undo':
                tx.apply_next(); tx.apply_next(); tx.begin_rollback()
                if index == 0:
                    tx.undo_next()
            elif index == 1:
                tx.apply_next()
            c.kernel.failure = failure
            effect = tx.apply_next if direction == 'apply' else tx.undo_next
            with pytest.raises(ActionUncertain):
                effect()
            assert j.state().pending == (direction, index)
            saved = list(c.kernel.calls)
            with pytest.raises(ActionUncertain):
                effect()
            assert c.kernel.calls == saved
        c.kernel.failure = None
        with opened(c, load=True) as (_, j, tx):
            tx.reconcile_pending()
            assert c.kernel.calls == saved
            if direction == 'apply':
                with pytest.raises(m.TransitionRejected):
                    tx.apply_next()
                tx.begin_rollback()
            while j.state().applied:
                tx.undo_next()
            assert tx.verify_restored().phase == 'restored'
            assert not c.kernel.reference and not c.kernel.published


@pytest.mark.parametrize('field', ['writer_fence_sha256', 'encrypted_swap_sha256', 'underlay_scan_sha256', 'context'])
def test_independent_proof_changes_prevent_any_effect(case, field):
    with publication_case(case) as c, opened(c) as (_, j, tx):
        value = dataclasses.replace(c.proof.context, maintenance_generation=41) if field == 'context' else '0' * 64
        c.proof = dataclasses.replace(c.proof, **{field: value})
        with pytest.raises(m.PublicationRejected):
            tx.apply_next()
        assert not c.kernel.calls and j.state().pending is None


@pytest.mark.parametrize('kind', ['binding', 'lock', 'lock-mode', 'parent', 'public-parent', 'bundle', 'extra', 'stage-journal'])
def test_changed_binding_or_parent_never_authorizes_resource_effect(case, kind):
    with publication_case(case) as c, opened(c) as (_, j, tx):
        if kind == 'binding':
            p = c.state / c.case.operation / 'binding.json'; p.write_bytes(p.read_bytes() + b' ')
        elif kind == 'lock':
            p = c.state / '.publication.lock'; p.rename(c.state / 'old-lock'); p.touch(mode=0o600)
        elif kind == 'lock-mode':
            (c.state / '.publication.lock').chmod(0o644)
        elif kind == 'parent':
            c.state.rename(c.case.tmp / 'old-state'); c.state.mkdir(mode=0o700)
        elif kind == 'public-parent':
            c.public.parent.rename(c.case.tmp / 'old-public'); c.public.parent.mkdir(mode=0o700)
        elif kind == 'bundle':
            p = c.state / c.case.operation; p.rename(c.state / 'old-bundle'); p.mkdir(mode=0o700)
        elif kind == 'extra':
            (c.state / c.case.operation / 'unknown').write_text('keep')
        else:
            c.stage_journal.append('rollback_started', {})
        with pytest.raises((RuntimeError, OSError)):
            tx.apply_next()
        assert c.kernel.calls == [] and j.state().pending is None


@pytest.mark.parametrize('field,value', [('mount_id', 777), ('parent_id', 777), ('source', 'foreign'), ('root', '/different'),
                                        ('kind', 'ext4'), ('options', ('rw',)), ('optional', ('shared:1',)),
                                        ('device', m.Device(0, 777))])
def test_same_marker_is_insufficient_if_mount_identity_or_profile_changed(case, field, value):
    with publication_case(case) as c, opened(c) as (_, _, tx):
        tx.apply_next(); tx.apply_next(); tx.begin_rollback()
        c.kernel.change = lambda s: dataclasses.replace(s, mounts=tuple(dataclasses.replace(r, **{field: value})
                                                        if r.target == str(c.public) else r for r in s.mounts))
        with pytest.raises(m.PublicationRejected):
            tx.undo_next()
        assert c.kernel.calls == ['preserve', 'publish']


@pytest.mark.parametrize('problem', ['namespace', 'init-namespace', 'boot', 'public-inode', 'reference-inode', 'stage-inode', 'alias', 'nested'])
def test_unknown_kernel_reference_topology_is_not_zero_or_owned(case, problem):
    with publication_case(case) as c, opened(c) as (_, _, tx):
        tx.apply_next(); tx.apply_next(); tx.begin_rollback()
        def change(s):
            if problem == 'namespace':
                return dataclasses.replace(s, namespace=(7, 8), init_namespace=(7, 8))
            if problem == 'init-namespace':
                return dataclasses.replace(s, init_namespace=(7, 8))
            if problem == 'boot':
                return dataclasses.replace(s, boot_id=str(uuid4()))
            if problem.endswith('-inode'):
                key = problem.split('-')[0]; v = list(getattr(s, key)); v[1] += 1
                return dataclasses.replace(s, **{key: tuple(v)})
            root = next(r for r in s.mounts if r.target == str(c.public))
            other = dataclasses.replace(root, mount_id=999, target=str(c.public / 'nested') if problem == 'nested' else '/elsewhere')
            return dataclasses.replace(s, mounts=(*s.mounts, other))
        c.kernel.change = change
        with pytest.raises(m.PublicationRejected):
            tx.undo_next()
        assert c.kernel.published


def test_reference_busy_recovery_never_uses_forced_or_lazy_unmount(case):
    with publication_case(case) as c, opened(c) as (_, j, tx):
        tx.apply_next(); tx.apply_next(); tx.begin_rollback(); tx.undo_next()
        c.kernel.busy = True
        with pytest.raises(ActionUncertain):
            tx.undo_next()
        assert c.kernel.reference and not c.kernel.published and j.state().pending == ('undo', 0)
        c.kernel.busy = False
        tx.reconcile_pending(); tx.undo_next()
        assert tx.verify_restored().phase == 'restored'


def test_parent_staging_is_not_removed_or_reset_during_publication(case):
    with publication_case(case) as c, opened(c) as (_, _, tx):
        tx.apply_next(); tx.apply_next()
        assert c.case.kernel.calls == ['create'] and c.stage_journal.state().phase == 'applied'
        with pytest.raises(BlockingIOError):
            m.TmpfsPublicationAdapter.load(c.stage, c.public, c.state, lambda: c.proof, kernel=c.kernel)


def test_no_direct_effect_without_matching_journal(case):
    with publication_case(case) as c, m.TmpfsPublicationAdapter.prepare(c.stage, c.public, c.state, lambda: c.proof, kernel=c.kernel) as a:
        with pytest.raises(m.PublicationRejected):
            a.apply(a.steps[0], a.operation)
        assert c.kernel.calls == []


@pytest.mark.parametrize('field,value', [('writer_fence_sha256', None), ('underlay_scan_sha256', ''), ('encrypted_swap_sha256', 'bad')])
def test_missing_independent_evidence_is_rejected(case, field, value):
    with publication_case(case) as c, pytest.raises(m.PublicationRejected):
        dataclasses.replace(c.proof, **{field: value})


def test_cross_namespace_preparation_rejected_even_if_each_namespace_is_self_consistent(case):
    with publication_case(case) as c:
        c.kernel.change = lambda s: dataclasses.replace(s, namespace=(2, 3), init_namespace=(2, 3))
        with pytest.raises(m.PublicationRejected):
            m.TmpfsPublicationAdapter.prepare(c.stage, c.public, c.state, lambda: c.proof, kernel=c.kernel)
        assert c.kernel.calls == []


def test_preexisting_mount_on_public_is_not_adopted(case):
    with publication_case(case) as c:
        c.kernel.published = True
        with pytest.raises(m.PublicationRejected):
            m.TmpfsPublicationAdapter.prepare(c.stage, c.public, c.state, lambda: c.proof, kernel=c.kernel)
        assert c.kernel.calls == []


def test_native_move_uses_one_ms_move_without_cloning_or_unmounting(monkeypatch):
    calls = []
    class Function:
        def __call__(self, *args):
            calls.append(args)
            return 0
    monkeypatch.setattr(m.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace(mount=Function()))
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    m.LinuxPublicationKernel().move(11, 'mount', 22, 'tmp')
    assert calls == [(b'/proc/self/fd/11/mount', b'/proc/self/fd/22/tmp', None, 8192, None)]


def test_native_reference_release_has_zero_flags_and_retains_busy_errno(monkeypatch):
    calls = []
    class Function:
        def __call__(self, *args):
            calls.append(args)
            return -1
    monkeypatch.setattr(m.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace(umount2=Function()))
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    with pytest.raises(OSError):
        m.LinuxPublicationKernel().release(22)
    assert calls == [(b'/proc/self/fd/22/underlay', 0)]


@pytest.mark.parametrize('index', [0, 1])
def test_forward_action_rechecks_staging_emptiness_after_preparation(case, index):
    with publication_case(case) as c, opened(c) as (_, j, tx):
        if index:
            tx.apply_next()
        c.case.kernel.data = 1
        saved = list(c.kernel.calls)
        with pytest.raises(ActionUncertain):
            tx.apply_next()
        assert c.kernel.calls == saved and j.state().pending == ('apply', index)
        assert not c.kernel.published and c.case.kernel.data == 1
        tx.reconcile_pending(); tx.begin_rollback()
        while j.state().applied:
            tx.undo_next()
        assert tx.verify_restored().phase == 'restored'
        assert c.case.kernel.data == 1


@pytest.mark.parametrize('during_prepare', [False, True])
def test_external_underlay_alias_is_not_ignored(case, during_prepare):
    with publication_case(case) as c:
        def alias(s):
            root = s.mounts[0]
            other = dataclasses.replace(root, mount_id=199, parent_id=13, root=str(c.public), target='/outside-reference')
            return dataclasses.replace(s, mounts=(*s.mounts, other))
        if during_prepare:
            c.kernel.change = alias
            with pytest.raises(m.PublicationRejected):
                m.TmpfsPublicationAdapter.prepare(c.stage, c.public, c.state, lambda: c.proof, kernel=c.kernel)
        else:
            with opened(c) as (_, _, tx):
                tx.apply_next(); tx.apply_next(); tx.begin_rollback()
                c.kernel.change = alias
                with pytest.raises(m.PublicationRejected):
                    tx.undo_next()
                assert c.kernel.published


@pytest.mark.parametrize('field,value', [('parent_id', 222), ('options', ('ro',)), ('optional', ('shared:4',))])
def test_changed_recovery_reference_is_not_owned(case, field, value):
    with publication_case(case) as c, opened(c) as (a, _, tx):
        tx.apply_next(); tx.apply_next(); tx.begin_rollback()
        c.kernel.change = lambda s: dataclasses.replace(s, mounts=tuple(dataclasses.replace(r, **{field: value})
                                                       if r.target == str(a.reference) else r for r in s.mounts))
        with pytest.raises(m.PublicationRejected):
            tx.undo_next()
        assert c.kernel.reference and c.kernel.published
