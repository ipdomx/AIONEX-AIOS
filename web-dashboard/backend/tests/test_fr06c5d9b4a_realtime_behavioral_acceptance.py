"""Behavioral acceptance: real disposable PostgreSQL, simulated provider replies.

No production credentials, provider calls, or application service restarts.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import os
import re
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.base import Base
from app.db.models import (
    Organization, OwnerControlRecord, RealtimeProviderResourceOwnership,
    RealtimeRoom, RealtimeRecording, User,
)
from app.realtime.livekit_runtime import LiveKitRuntime, RealtimeProviderProtocolError
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_realtime_resources as registry
from app.services import host_maintenance_realtime_provider_inventory as inventory
from app.services.host_maintenance_realtime_drain import RealtimeDrainUnavailable, measure_realtime_drain
from app.services.host_maintenance_realtime_ambiguity_acceptance import (
    RealtimeAmbiguityAcceptanceBlocked, evaluate_realtime_ambiguity_acceptance,
)
from app.services.host_maintenance_realtime_turn_boundary import evaluate_realtime_turn_boundary


def _dependency_tables():
    needed = set()
    def visit(table):
        if table.name in needed:
            return
        needed.add(table.name)
        for fk in table.foreign_keys:
            visit(fk.column.table)
    for name in (
        'owner_control_records', 'realtime_provider_resources', 'realtime_rooms',
        'realtime_participants', 'realtime_admission_grants', 'realtime_recordings',
    ):
        visit(Base.metadata.tables[name])
    return [t for t in Base.metadata.sorted_tables if t.name in needed]


@pytest_asyncio.fixture
async def case():
    url = make_url(os.environ['DATABASE_URL'])
    assert os.environ.get('ENVIRONMENT') == 'test'
    assert url.drivername == 'postgresql+asyncpg'
    assert re.search(r'(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)', url.database or '')
    schema = 'rt_behavior_' + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={
        'server_settings': {'search_path': schema, 'statement_timeout': '5000'},
    })
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    case = SimpleNamespace(sessions=sessions, schema=schema, org=str(uuid4()), user=str(uuid4()))
    created = False
    try:
        async with admin.begin() as conn:
            await conn.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=_dependency_tables()))
        async with sessions() as session, session.begin():
            session.add(OwnerControlRecord(
                id=str(uuid4()), domain=admission.DOMAIN, resource_id=admission.RESOURCE_ID,
                status='open', enabled=True, version=16, payload={
                    'schema_version':8, 'scope':admission.REALTIME_REQUEST_COVERAGE_SCOPE,
                    'generation':16, 'operation_id':str(uuid4()), 'reason':'isolated-behavior-test',
                    'changed_at':datetime.now(UTC).isoformat(), 'full_host_closure':False,
                },
            ))
            session.add(Organization(id=case.org, name='Isolated test', slug=uuid4().hex))
            await session.flush()
            session.add(User(id=case.user, organization_id=case.org, email=uuid4().hex+'@example.invalid',
                             name='Isolated test', password_hash='not-a-real-password-hash'))
        yield case
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def _close(case):
    return await admission.close_admission(
        operation_id=str(uuid4()), expected_generation=16,
        reason='isolated behavior closure', session_factory=case.sessions,
    )


async def _rows(case):
    async with case.sessions() as session:
        result = await session.execute(select(RealtimeProviderResourceOwnership.__table__).order_by(
            RealtimeProviderResourceOwnership.id
        ))
        return [dict(row) for row in result.mappings()]


async def _reserve(case, kind):
    async with case.sessions() as session, session.begin():
        return await registry.reserve_provider_resource(
            session, organization_id=case.org, resource_kind=kind,
            local_resource_id=str(uuid4()), owner_incarnation=str(uuid4()),
        )


async def _room(case):
    key = str(uuid4())
    async with case.sessions() as session, session.begin():
        session.add(RealtimeRoom(id=key, organization_id=case.org, created_by_id=case.user,
                                room_key=key, idempotency_key=key, status='closed'))
    return key


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['room','participant_session','egress','recording_file'])
@pytest.mark.parametrize('state', ['reserved','submitted','active','unresolved'])
async def test_unfinished_real_ledger_blocks_without_mutation(case, kind, state):
    owner = await _reserve(case, kind)
    if state != 'reserved':
        assert await registry.begin_provider_io(owner, session_factory=case.sessions)
    expiry = datetime.now(UTC)+timedelta(minutes=5) if kind=='participant_session' else None
    if state == 'active':
        await registry.observe_provider_active(owner, provider_ref_sha256='a'*64,
                                              expires_at=expiry, session_factory=case.sessions)
    if state == 'unresolved':
        await registry.mark_provider_unresolved(owner, reason='simulated_provider_timeout',
                                               expires_at=expiry, session_factory=case.sessions)
    await _close(case)
    before = await _rows(case)
    with pytest.raises(RealtimeAmbiguityAcceptanceBlocked):
        await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)
    assert await _rows(case) == before
    snapshot = await measure_realtime_drain(session_factory=case.sessions)
    assert snapshot.unfinished_provider_ids == (owner.id,)
    assert owner.nonce not in repr(snapshot)
    assert not snapshot.provider_drain_verified and not snapshot.full_host_closure


@pytest.mark.asyncio
async def test_open_authority_is_not_empty_acceptance(case):
    with pytest.raises(RealtimeDrainUnavailable, match='closed'):
        await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)


@pytest.mark.asyncio
async def test_expired_session_remains_blocked_until_explicit_settlement(case):
    owner = await _reserve(case, 'participant_session')
    assert await registry.begin_provider_io(owner, session_factory=case.sessions)
    await registry.observe_provider_active(owner, provider_ref_sha256='a'*64,
        expires_at=datetime.now(UTC)+timedelta(milliseconds=100), session_factory=case.sessions)
    await asyncio.sleep(.15)
    await _close(case)
    snap = await measure_realtime_drain(session_factory=case.sessions)
    assert snap.expired_unsettled_session_ids == (owner.id,)
    with pytest.raises(RealtimeAmbiguityAcceptanceBlocked, match='expired_participant'):
        await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)
    assert await registry.settle_participant_session_expired(owner, session_factory=case.sessions)
    accepted = await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)
    assert accepted.ambiguity_free and not accepted.migration_0064_rollout_allowed
    assert len(await _rows(case)) == 1


@pytest.mark.asyncio
async def test_legacy_ambiguous_failed_recording_remains_blocked(case):
    room = await _room(case)
    key = str(uuid4())
    async with case.sessions() as session, session.begin():
        session.add(RealtimeRecording(id=key, organization_id=case.org, room_id=room,
            requested_by_id=case.user, idempotency_key=key, title='Isolated recording',
            status='failed', error_code='provider_start_uncertain', output_relpath=key+'.mp4',
            consent_version='isolated-test', retention_until=datetime.now(UTC)+timedelta(days=1)))
    await _close(case)
    with pytest.raises(RealtimeAmbiguityAcceptanceBlocked, match='legacy_ambiguous_recording'):
        await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)


@pytest.mark.asyncio
async def test_cancel_after_committed_bundle_keeps_both_submitted_owners(case):
    owners = tuple([await _reserve(case, kind) for kind in ['egress', 'recording_file']])
    started = asyncio.Event()
    async def writer():
        assert await registry.begin_provider_io_bundle(owners, session_factory=case.sessions)
        started.set()
        await asyncio.Event().wait()
    task = asyncio.create_task(writer())
    try:
        await asyncio.wait_for(started.wait(), 5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await _close(case)
    with pytest.raises(RealtimeAmbiguityAcceptanceBlocked, match='provider_io_submitted'):
        await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)
    assert len(await _rows(case)) == 2
    assert all(row['state']=='submitted' for row in await _rows(case))


@pytest.mark.asyncio
async def test_process_exit_after_committed_begin_preserves_uncertain_intent(case):
    env = dict(os.environ, RT_TEST_SCHEMA=case.schema, RT_TEST_ORG=case.org)
    code = '''import asyncio,os
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.services import host_maintenance_realtime_resources as registry
async def main():
 engine=create_async_engine(os.environ['DATABASE_URL'],connect_args={'server_settings':{'search_path':os.environ['RT_TEST_SCHEMA']}})
 sessions=async_sessionmaker(engine,expire_on_commit=False)
 async with sessions() as session, session.begin():
  owner=await registry.reserve_provider_resource(session,organization_id=os.environ['RT_TEST_ORG'],resource_kind='egress',local_resource_id=str(uuid4()),owner_incarnation=str(uuid4()))
 assert await registry.begin_provider_io(owner,session_factory=sessions)
 os._exit(73)
asyncio.run(main())
'''
    proc = await asyncio.create_subprocess_exec(sys.executable, '-c', code, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 15)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    assert proc.returncode == 73, (out, err)
    await _close(case)
    with pytest.raises(RealtimeAmbiguityAcceptanceBlocked, match='provider_io_submitted'):
        await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)
    assert [r['state'] for r in await _rows(case)] == ['submitted']


@pytest.mark.asyncio
async def test_clean_inventory_keeps_turn_rollout_and_full_host_blocked(case, monkeypatch):
    closed = await _close(case)
    calls = []
    async def fake(**kwargs):
        calls.append(kwargs['method'])
        return {'rooms': []}
    monkeypatch.setattr(inventory.livekit_runtime, '_twirp', fake)
    result = await evaluate_realtime_turn_boundary(session_factory=case.sessions)
    assert calls == ['ListRooms']
    assert result.provider_inventory.drain.authority == closed
    assert result.livekit_room_drain_verified and result.connected_presence_provider_drain_verified
    assert result.rollout_blocker_reasons == ('coturn_allocation_inventory_unavailable',)
    assert not result.turn_allocation_drain_verified
    assert not result.migration_0064_rollout_allowed and not result.full_host_closure
    assert not result.provider_drain_verified and await _rows(case) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('transition', ['reopen','supersede','reopen_reclose'])
async def test_authority_change_during_inventory_rejected(case, monkeypatch, transition):
    closed = await _close(case)
    async def fake(**kwargs):
        if transition in {'reopen','reopen_reclose'}:
            opened = await admission.open_admission(operation_id=closed.operation_id,
                expected_generation=closed.generation, reason='isolated concurrent reopen',
                session_factory=case.sessions)
            if transition=='reopen_reclose':
                await admission.close_admission(operation_id=str(uuid4()),
                    expected_generation=opened.generation, reason='isolated reclose',
                    session_factory=case.sessions)
        else:
            await admission.close_admission(operation_id=str(uuid4()),
                expected_generation=closed.generation, reason='isolated supersede',
                session_factory=case.sessions)
        return {'rooms': []}
    monkeypatch.setattr(inventory.livekit_runtime, '_twirp', fake)
    with pytest.raises((RealtimeDrainUnavailable, inventory.RealtimeProviderInventoryUnavailable)):
        await inventory.collect_livekit_provider_inventory(session_factory=case.sessions)


@pytest.mark.asyncio
async def test_late_local_blocker_during_inventory_rejected(case, monkeypatch):
    room = await _room(case)
    await _close(case)
    async def fake(**kwargs):
        async with case.sessions() as session, session.begin():
            obj = await session.get(RealtimeRoom, room)
            obj.status = 'open'
        return {'rooms': []}
    monkeypatch.setattr(inventory.livekit_runtime, '_twirp', fake)
    with pytest.raises(inventory.RealtimeProviderInventoryUnavailable):
        await inventory.collect_livekit_provider_inventory(session_factory=case.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', [None, {}, {'name':None}, {'name':123}, {'name':''}, {'name':' aios-rt-fixture '}])
@pytest.mark.parametrize('method', ['list_aios_room_inventory','list_aios_room_name_hashes'])
async def test_malformed_room_entries_fail_closed(monkeypatch, entry, method):
    runtime = LiveKitRuntime()
    async def fake(**kwargs):
        return {'rooms':[entry], 'participants':[]}
    monkeypatch.setattr(runtime, '_twirp', fake)
    with pytest.raises(RealtimeProviderProtocolError):
        await getattr(runtime, method)()


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', [None, {}, {'identity':None}, {'identity':123}, {'identity':''}, {'identity':' participant-fixture '}])
async def test_malformed_participant_entries_fail_closed(monkeypatch, entry):
    runtime = LiveKitRuntime()
    async def fake(**kwargs):
        return {'participants':[entry]}
    monkeypatch.setattr(runtime, '_twirp', fake)
    with pytest.raises(RealtimeProviderProtocolError):
        await runtime.list_room_participant_inventory(provider_room_name='aios-rt-fixture')


@pytest.mark.asyncio
async def test_valid_inventory_is_hash_only_and_reads_each_room_once(monkeypatch):
    runtime = LiveKitRuntime()
    calls = []
    async def fake(**kwargs):
        calls.append(kwargs['method'])
        if kwargs['method']=='ListRooms':
            return {'rooms':[{'name':'other-room'}, {'name':'aios-rt-fixture'}]}
        return {'participants':[{'identity':'participant-fixture'}]}
    monkeypatch.setattr(runtime, '_twirp', fake)
    result = await runtime.list_aios_room_inventory()
    assert calls == ['ListRooms','ListParticipants']
    assert len(result)==1 and result[0].participant_count==1
    assert result[0].provider_room_name_sha256==hashlib.sha256(b'aios-rt-fixture').hexdigest()
    assert result[0].participant_identity_sha256==(hashlib.sha256(b'participant-fixture').hexdigest(),)
    assert 'aios-rt-fixture' not in repr(result) and 'participant-fixture' not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'rooms':None}, {'rooms':'bad'}, {'rooms':{}}, {'rooms':True}])
@pytest.mark.parametrize('method', ['list_aios_room_inventory','list_aios_room_name_hashes'])
async def test_missing_or_wrong_room_list_is_not_empty(monkeypatch, body, method):
    runtime = LiveKitRuntime()
    async def fake(**kwargs):
        return body
    monkeypatch.setattr(runtime, '_twirp', fake)
    with pytest.raises(RealtimeProviderProtocolError):
        await getattr(runtime, method)()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['list_aios_room_inventory','list_aios_room_name_hashes'])
async def test_duplicate_room_identity_blocks_inventory(monkeypatch, method):
    runtime = LiveKitRuntime()
    async def fake(**kwargs):
        return {'rooms':[{'name':'aios-rt-fixture'}, {'name':'aios-rt-fixture'}], 'participants':[]}
    monkeypatch.setattr(runtime, '_twirp', fake)
    with pytest.raises(RealtimeProviderProtocolError, match='duplicate'):
        await getattr(runtime, method)()


@pytest.mark.asyncio
async def test_duplicate_participant_identity_blocks_inventory(monkeypatch):
    runtime = LiveKitRuntime()
    async def fake(**kwargs):
        return {'participants':[{'identity':'participant-fixture'}, {'identity':'participant-fixture'}]}
    monkeypatch.setattr(runtime, '_twirp', fake)
    with pytest.raises(RealtimeProviderProtocolError, match='duplicate'):
        await runtime.list_room_participant_inventory(provider_room_name='aios-rt-fixture')


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [TimeoutError, asyncio.CancelledError, RealtimeProviderProtocolError])
async def test_provider_error_or_cancellation_cannot_produce_evidence(case, monkeypatch, error):
    closed = await _close(case)
    async def fake(**kwargs):
        raise error('simulated provider failure')
    monkeypatch.setattr(inventory.livekit_runtime, '_twirp', fake)
    before = await _rows(case)
    with pytest.raises(error):
        await inventory.collect_livekit_provider_inventory(session_factory=case.sessions)
    assert await _rows(case) == before
    async with case.sessions() as session:
        assert await admission.read_admission_snapshot(session, required_scope='realtime_media_requests') == closed


@pytest.mark.asyncio
async def test_provider_inventory_has_total_deadline(case, monkeypatch):
    await _close(case)
    async def fake(**kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(inventory.livekit_runtime, '_twirp', fake)
    monkeypatch.setattr(inventory, '_PROVIDER_INVENTORY_TIMEOUT_SECONDS', .01)
    started = asyncio.get_running_loop().time()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(inventory.collect_livekit_provider_inventory(session_factory=case.sessions), 2)
    assert asyncio.get_running_loop().time() - started < 1
    assert await _rows(case) == []


@pytest.mark.asyncio
async def test_unfinished_ledger_blocks_provider_calls(case, monkeypatch):
    owner = await _reserve(case, 'egress')
    assert await registry.begin_provider_io(owner, session_factory=case.sessions)
    await _close(case)
    calls = []
    async def fake(**kwargs):
        calls.append(kwargs)
        return {'rooms': []}
    monkeypatch.setattr(inventory.livekit_runtime, '_twirp', fake)
    with pytest.raises(inventory.RealtimeProviderInventoryUnavailable):
        await inventory.collect_livekit_provider_inventory(session_factory=case.sessions)
    assert calls == []
    assert [r['state'] for r in await _rows(case)] == ['submitted']


@pytest.mark.asyncio
async def test_nonempty_provider_observation_preserves_counts_without_drain_claim(case, monkeypatch):
    await _close(case)
    async def fake(**kwargs):
        if kwargs['method'] == 'ListRooms':
            return {'rooms':[{'name':'aios-rt-fixture'}]}
        return {'participants':[{'identity':'participant-fixture-1'}, {'identity':'participant-fixture-2'}]}
    monkeypatch.setattr(inventory.livekit_runtime, '_twirp', fake)
    result = await inventory.collect_livekit_provider_inventory(session_factory=case.sessions)
    assert result.provider_participant_count == 2
    assert len(result.provider_aios_room_hashes) == 1
    assert result.revalidated_drain.authority == result.drain.authority
    assert result.revalidated_drain.observed_at >= result.drain.observed_at
    assert result.authority_revalidated
    assert not result.livekit_room_drain_verified and not result.connected_presence_provider_drain_verified
    assert not result.turn_allocation_drain_verified and not result.provider_drain_verified
    assert not result.full_host_closure


@pytest.mark.asyncio
async def test_other_tenant_history_never_hides_unowned_livekit_room(case):
    room = await _room(case)
    async with case.sessions() as session, session.begin():
        row = await session.get(RealtimeRoom, room)
        row.provider_adapter = 'livekit'
        owner = await registry.reserve_provider_resource(session, organization_id=str(uuid4()),
            resource_kind='room', local_resource_id=room, owner_incarnation=str(uuid4()))
    await registry.settle_not_started(owner, session_factory=case.sessions)
    await _close(case)
    snapshot = await measure_realtime_drain(session_factory=case.sessions)
    assert snapshot.legacy_unowned_room_ids == (room,)
    with pytest.raises(RealtimeAmbiguityAcceptanceBlocked):
        await evaluate_realtime_ambiguity_acceptance(session_factory=case.sessions)
