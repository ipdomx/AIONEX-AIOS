"""Executable quota consistency tests on disposable PostgreSQL only.

Service functions and row locks are real. No provider/network application calls,
production database, user records, or billing gateway is used.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.auth import UserRecord
from app.db.base import Base
from app.db.models import Organization, OwnerControlRecord, User
from app.services import free_tier as quotas


def _dependency_tables():
    needed = set()
    def visit(table):
        if table.name in needed:
            return
        needed.add(table.name)
        for fk in table.foreign_keys:
            visit(fk.column.table)
    for name in ('owner_control_records', 'projects', 'users'):
        visit(Base.metadata.tables[name])
    return [table for table in Base.metadata.sorted_tables if table.name in needed]


@pytest_asyncio.fixture
async def case():
    url = make_url(os.environ['DATABASE_URL'])
    assert os.environ.get('ENVIRONMENT') == 'test'
    assert url.drivername == 'postgresql+asyncpg'
    assert re.search(r'(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)', url.database or '')
    schema = 'fr07_quota_' + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={
        'server_settings': {'search_path': schema, 'statement_timeout': '5000'},
    })
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = UserRecord(id=str(uuid4()), email=uuid4().hex+'@example.invalid',
        name='Isolated test', role=quotas.FREE_USER_ROLE_NAME,
        password_hash='not-a-password', organization_id=str(uuid4()),
        organization_name='Isolated test', organization_plan='free', permissions=[])
    state = SimpleNamespace(sessions=sessions, admin=admin, actor=actor, schema=schema)
    created = False
    try:
        async with admin.begin() as conn:
            await conn.execute(CreateSchema(schema)); created = True
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=_dependency_tables()))
        async with sessions() as session, session.begin():
            session.add(Organization(id=actor.organization_id, name=actor.organization_name,
                                     slug=uuid4().hex, plan='free'))
            await session.flush()
            session.add(User(id=actor.id, organization_id=actor.organization_id,
                             email=actor.email, name=actor.name, password_hash='test-hash'))
            await quotas.get_free_tier_policy(session)
            await quotas._ensure_account_record(session, actor.id)
        yield state
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def _account(case, session):
    return await session.scalar(select(OwnerControlRecord).where(
        OwnerControlRecord.domain == quotas.FREE_TIER_ACCOUNT_DOMAIN,
        OwnerControlRecord.resource_id == case.actor.id))


async def _stored(case):
    async with case.sessions() as session:
        record = await _account(case, session)
        return dict(record.payload), record.version


async def _expire(case):
    async with case.sessions() as session, session.begin():
        record = await _account(case, session)
        record.payload = {**record.payload,
            'period_started_at': (datetime.now(UTC)-timedelta(days=31)).isoformat(),
            'period_ends_at': (datetime.now(UTC)-timedelta(days=1)).isoformat(),
            'user_messages_used': 5, 'assistant_responses_used': 7}


async def _consume(case, kind='message'):
    async with case.sessions() as session, session.begin():
        if kind == 'message':
            await quotas.consume_user_message(session, case.actor, characters=10)
        else:
            await quotas.consume_assistant_response(session, case.actor)


@pytest.mark.asyncio
async def test_expired_status_projection_does_not_reset_durable_usage(case):
    await _expire(case)
    before = await _stored(case)
    async with case.sessions() as session, session.begin():
        status = await quotas.get_free_tier_status(session, case.actor)
        assert status['usage']['user_messages'] == 0
        assert status['usage']['assistant_responses'] == 0
    assert await _stored(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,counter', [
    ('message','user_messages_used'), ('response','assistant_responses_used'),
])
async def test_status_view_does_not_hold_a_usage_write_lock_or_lose_rollover_counts(case, kind, counter):
    await _expire(case)
    async with case.sessions() as status_session:
        await quotas.get_free_tier_status(status_session, case.actor)
        # The status view must be non-mutating. A consumer is permitted to commit
        # before the status transaction finishes, without losing its counter.
        await asyncio.wait_for(_consume(case, kind), timeout=3)
        await status_session.commit()
    payload, _ = await _stored(case)
    assert payload[counter] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,policy_key', [
    ('message','monthly_user_message_limit'),
    ('response','monthly_assistant_response_limit'),
])
async def test_preloaded_account_cannot_bypass_current_counter_after_lock(case, kind, policy_key):
    async with case.sessions() as setup, setup.begin():
        await quotas.update_free_tier_policy(setup, {policy_key:1})
    async with case.sessions() as stale:
        held = await _account(case, stale)  # Retain the ORM identity-map object.
        assert held is not None
        await _consume(case, kind)
        with pytest.raises(HTTPException) as rejected:
            if kind == 'message':
                await quotas.consume_user_message(stale, case.actor, characters=10)
            else:
                await quotas.consume_assistant_response(stale, case.actor)
        assert rejected.value.status_code == 429
        await stale.rollback()
    payload, _ = await _stored(case)
    assert payload['user_messages_used' if kind=='message' else 'assistant_responses_used'] == 1


@pytest.mark.asyncio
async def test_parallel_consumers_respect_the_exact_owner_limit(case):
    async with case.sessions() as setup, setup.begin():
        await quotas.update_free_tier_policy(setup, {'monthly_user_message_limit':5})
    async def attempt():
        try:
            await _consume(case)
            return 1
        except HTTPException as exc:
            assert exc.status_code == 429
            return 0
    accepted = await asyncio.wait_for(asyncio.gather(*(attempt() for _ in range(12))), 5)
    assert sum(accepted) == 5
    assert (await _stored(case))[0]['user_messages_used'] == 5


@pytest.mark.asyncio
async def test_same_transaction_preserves_both_message_and_response_reservations(case):
    async with case.sessions() as session, session.begin():
        await quotas.consume_user_message(session, case.actor, characters=10)
        await quotas.consume_assistant_response(session, case.actor)
        status = await quotas.get_free_tier_status(session, case.actor)
        assert status['usage']['user_messages'] == status['usage']['assistant_responses'] == 1
    payload, _ = await _stored(case)
    assert payload['user_messages_used'] == payload['assistant_responses_used'] == 1


@pytest.mark.asyncio
async def test_rollback_releases_uncommitted_usage(case):
    before = await _stored(case)
    async with case.sessions() as session:
        await quotas.consume_user_message(session, case.actor, characters=10)
        await session.rollback()
    assert await _stored(case) == before


@pytest.mark.asyncio
async def test_different_accounts_keep_independent_counters(case):
    actor2 = UserRecord(**{**vars(case.actor), 'id':str(uuid4()), 'email':uuid4().hex+'@example.invalid'})
    async with case.sessions() as setup, setup.begin():
        setup.add(User(id=actor2.id, organization_id=actor2.organization_id,
                       email=actor2.email, name=actor2.name, password_hash='test-hash'))
    async with case.sessions() as first:
        await quotas.consume_user_message(first, case.actor, characters=10)
        async with case.sessions() as second, second.begin():
            await asyncio.wait_for(quotas.consume_user_message(second, actor2, characters=10), 3)
        await first.commit()
    assert (await _stored(case))[0]['user_messages_used'] == 1
    async with case.sessions() as session:
        other = await quotas.get_free_tier_status(session, actor2)
        assert other['usage']['user_messages'] == 1


@pytest.mark.asyncio
async def test_suspended_policy_does_not_consume_a_counter(case):
    async with case.sessions() as setup, setup.begin():
        await quotas.update_free_tier_policy(setup, {'enabled':False})
    before = await _stored(case)
    with pytest.raises(HTTPException) as error:
        await _consume(case)
    assert error.value.status_code == 403
    assert await _stored(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,counter', [
    ('message','user_messages_used'), ('response','assistant_responses_used'),
])
async def test_preloaded_account_cannot_lose_another_committed_increment(case, kind, counter):
    async with case.sessions() as stale:
        held = await _account(case, stale)
        assert held.payload[counter] == 0
        await _consume(case, kind)
        if kind == 'message':
            await quotas.consume_user_message(stale, case.actor, characters=10)
        else:
            await quotas.consume_assistant_response(stale, case.actor)
        await stale.commit()
    assert (await _stored(case))[0][counter] == 2


@pytest.mark.asyncio
async def test_current_status_keeps_committed_counts_unchanged(case):
    await _consume(case)
    before = await _stored(case)
    async with case.sessions() as session, session.begin():
        status = await quotas.get_free_tier_status(session, case.actor)
        assert status['usage']['user_messages'] == 1
    assert await _stored(case) == before


@pytest.mark.asyncio
async def test_rollover_is_applied_only_when_consuming(case):
    await _expire(case)
    await _consume(case)
    payload, _ = await _stored(case)
    assert payload['user_messages_used'] == 1
    assert payload['assistant_responses_used'] == 0
    assert datetime.fromisoformat(payload['period_ends_at']) > datetime.now(UTC)


@pytest.mark.asyncio
async def test_two_same_transaction_message_consumptions_are_not_erased_by_refresh(case):
    async with case.sessions() as session, session.begin():
        await quotas.consume_user_message(session, case.actor, characters=10)
        await quotas.consume_user_message(session, case.actor, characters=10)
    assert (await _stored(case))[0]['user_messages_used'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('period_end', [None, 'invalid-date'])
async def test_unusable_period_end_is_projected_without_mutating_history(case, period_end):
    async with case.sessions() as setup, setup.begin():
        record = await _account(case, setup)
        record.payload = {**record.payload, 'period_ends_at':period_end, 'user_messages_used':9}
    before = await _stored(case)
    async with case.sessions() as session, session.begin():
        status = await quotas.get_free_tier_status(session, case.actor)
        assert status['usage']['user_messages'] == 0
    assert await _stored(case) == before
    await _consume(case)
    assert (await _stored(case))[0]['user_messages_used'] == 1


@pytest.mark.asyncio
async def test_parallel_first_consumers_initialize_one_account_without_lost_counts(case):
    async with case.sessions() as setup, setup.begin():
        record = await _account(case, setup)
        await setup.delete(record)
    await asyncio.wait_for(asyncio.gather(*(_consume(case) for _ in range(8))), 5)
    assert (await _stored(case))[0]['user_messages_used'] == 8


@pytest.mark.asyncio
async def test_locked_storage_adjustment_refreshes_preloaded_account(case):
    async with case.sessions() as stale:
        held = await _account(case, stale)
        assert held.payload['storage_bytes_used'] == 0
        async with case.sessions() as other, other.begin():
            await quotas.adjust_storage_usage(other, case.actor, 10)
        await quotas.adjust_storage_usage(stale, case.actor, 5)
        await stale.commit()
    assert (await _stored(case))[0]['storage_bytes_used'] == 15


@pytest.mark.asyncio
async def test_non_free_actor_keeps_existing_bypass_semantics(case):
    actor = UserRecord(**{**vars(case.actor), 'role':'Member', 'organization_plan':'professional'})
    before = await _stored(case)
    async with case.sessions() as session, session.begin():
        await quotas.consume_user_message(session, actor, characters=10)
        await quotas.consume_assistant_response(session, actor)
        assert await quotas.get_free_tier_status(session, actor) == {
            'plan':'professional', 'free_tier':False}
    assert await _stored(case) == before
