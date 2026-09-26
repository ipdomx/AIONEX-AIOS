"""Real PostgreSQL policy freshness; synthetic data, no provider or payment I/O.

The FR07A1 fixture creates a separate schema per case and enforces test-only DB
naming. These tests deliberately retain ORM objects across other transactions.
They do not certify revocation of work admitted before an Owner change.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.db.models import OwnerControlRecord
from app.services import free_tier as quotas
from tests.test_fr07a_quota_consistency import _stored, case as case


async def _policy_row(session):
    return await session.scalar(select(OwnerControlRecord).where(
        OwnerControlRecord.domain == quotas.FREE_TIER_POLICY_DOMAIN,
        OwnerControlRecord.resource_id == quotas.FREE_TIER_POLICY_RESOURCE,
    ))


async def _change(case, updates):
    async with case.sessions() as session, session.begin():
        return await quotas.update_free_tier_policy(session, updates)


async def _policy_stored(case):
    async with case.sessions() as session:
        row = await _policy_row(session)
        return dict(row.payload), row.version, row.enabled, row.status


async def _consume(session, actor, kind):
    if kind == "message":
        await quotas.consume_user_message(session, actor, characters=10)
    elif kind == "response":
        await quotas.consume_assistant_response(session, actor)
    else:
        await quotas.assert_free_project_creation_allowed(session, actor)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["message", "response", "project"])
async def test_cached_policy_cannot_bypass_committed_owner_suspension(case, kind):
    before = await _stored(case)
    async with case.sessions() as stale:
        held = await _policy_row(stale)
        assert held.payload["enabled"] is True
        await _change(case, {"enabled": False})
        with pytest.raises(HTTPException) as rejected:
            await _consume(stale, case.actor, kind)
        assert rejected.value.status_code == 403
        await stale.rollback()
    assert await _stored(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,key", [
    ("message", "monthly_user_message_limit"),
    ("response", "monthly_assistant_response_limit"),
])
async def test_cached_policy_respects_owner_lowered_counter_limit(case, kind, key):
    async with case.sessions() as session, session.begin():
        await _consume(session, case.actor, kind)
    before = await _stored(case)
    async with case.sessions() as stale:
        held = await _policy_row(stale)
        assert held.payload[key] > 1
        await _change(case, {key: 1})
        with pytest.raises(HTTPException) as rejected:
            await _consume(stale, case.actor, kind)
        assert rejected.value.status_code == 429
        await stale.rollback()
    assert await _stored(case) == before


@pytest.mark.asyncio
async def test_cached_policy_respects_current_message_length(case):
    async with case.sessions() as stale:
        held = await _policy_row(stale)
        assert held.payload["max_message_characters"] >= 256
        await _change(case, {"max_message_characters": 128})
        with pytest.raises(HTTPException) as rejected:
            await quotas.consume_user_message(stale, case.actor, characters=256)
        assert rejected.value.status_code == 422
        await stale.rollback()
    assert (await _stored(case))[0]["user_messages_used"] == 0


@pytest.mark.asyncio
async def test_cached_policy_respects_current_storage_limit(case):
    async with case.sessions() as stale:
        held = await _policy_row(stale)
        assert held.payload["storage_limit_bytes"] > 2 * 1024 * 1024
        await _change(case, {"storage_limit_bytes": 1024 * 1024})
        with pytest.raises(HTTPException) as rejected:
            await quotas.adjust_storage_usage(stale, case.actor, 2 * 1024 * 1024)
        assert rejected.value.status_code == 413
        await stale.rollback()
    assert (await _stored(case))[0]["storage_bytes_used"] == 0


@pytest.mark.asyncio
async def test_policy_read_refreshes_current_committed_owner_state(case):
    async with case.sessions() as stale:
        held = await _policy_row(stale)
        assert held.payload["enabled"] is True
        await _change(case, {"enabled": False})
        policy = await quotas.get_free_tier_policy(stale)
        assert policy["enabled"] is False
        assert held.payload["enabled"] is False


@pytest.mark.asyncio
async def test_preloaded_owner_patch_preserves_other_committed_owner_fields(case):
    before = await _policy_stored(case)
    async with case.sessions() as stale:
        held = await _policy_row(stale)
        assert held.version == before[1]
        await _change(case, {"enabled": False, "max_message_characters": 128})
        result = await quotas.update_free_tier_policy(
            stale, {"monthly_user_message_limit": 37}
        )
        await stale.commit()
        assert result["enabled"] is False
        assert result["max_message_characters"] == 128
    payload, version, enabled, status = await _policy_stored(case)
    assert payload["monthly_user_message_limit"] == 37
    assert version == before[1] + 2
    assert enabled is False and status == "suspended"


async def _legacy_policy(case):
    async with case.sessions() as session, session.begin():
        row = await _policy_row(session)
        row.payload = {"enabled": True, "project_limit": 2}


@pytest.mark.asyncio
async def test_legacy_policy_read_projects_defaults_without_mutating_history(case):
    await _legacy_policy(case)
    before = await _policy_stored(case)
    async with case.sessions() as session, session.begin():
        result = await quotas.get_free_tier_policy(session)
        assert result["project_limit"] == 2
        assert result["monthly_user_message_limit"] == 100
    assert await _policy_stored(case) == before


@pytest.mark.asyncio
async def test_legacy_policy_read_does_not_block_owner_patch_after_autoflush(case):
    await _legacy_policy(case)
    async with case.sessions() as reader:
        held = await _policy_row(reader)
        await quotas.get_free_tier_policy(reader)
        await reader.flush()
        await asyncio.wait_for(_change(case, {"enabled": False}), timeout=3)
        await reader.commit()
        assert held is not None
    assert (await _policy_stored(case))[0]["enabled"] is False


@pytest.mark.asyncio
async def test_same_transaction_owner_patches_keep_both_changes(case):
    before = await _policy_stored(case)
    async with case.sessions() as session, session.begin():
        await quotas.update_free_tier_policy(session, {"enabled": False})
        result = await quotas.update_free_tier_policy(
            session, {"monthly_user_message_limit": 37}
        )
        assert result["enabled"] is False
    payload, version, enabled, status = await _policy_stored(case)
    assert payload["monthly_user_message_limit"] == 37
    assert version == before[1] + 2
    assert enabled is False and status == "suspended"


@pytest.mark.asyncio
async def test_policy_read_preserves_this_transaction_owner_patch(case):
    async with case.sessions() as session, session.begin():
        await quotas.update_free_tier_policy(session, {"enabled": False})
        result = await quotas.get_free_tier_policy(session)
        assert result["enabled"] is False
    assert (await _policy_stored(case))[0]["enabled"] is False


@pytest.mark.asyncio
async def test_rollback_does_not_publish_owner_patch(case):
    before = await _policy_stored(case)
    async with case.sessions() as session:
        await quotas.update_free_tier_policy(session, {"enabled": False})
        await session.flush()
        await session.rollback()
    assert await _policy_stored(case) == before


@pytest.mark.asyncio
async def test_parallel_owner_patches_preserve_independent_fields(case):
    before = await _policy_stored(case)
    await asyncio.wait_for(asyncio.gather(
        _change(case, {"monthly_user_message_limit": 37}),
        _change(case, {"monthly_assistant_response_limit": 29}),
    ), timeout=5)
    payload, version, _, _ = await _policy_stored(case)
    assert payload["monthly_user_message_limit"] == 37
    assert payload["monthly_assistant_response_limit"] == 29
    assert version == before[1] + 2


@pytest.mark.asyncio
async def test_parallel_first_policy_reads_initialize_only_one_record(case):
    async with case.sessions() as session, session.begin():
        await session.execute(delete(OwnerControlRecord).where(
            OwnerControlRecord.domain == quotas.FREE_TIER_POLICY_DOMAIN
        ))
    async def read():
        async with case.sessions() as session, session.begin():
            return await quotas.get_free_tier_policy(session)
    results = await asyncio.wait_for(asyncio.gather(*(read() for _ in range(8))), 5)
    assert all(result == quotas.DEFAULT_FREE_TIER_POLICY for result in results)
    async with case.sessions() as session:
        count = await session.scalar(select(func.count()).select_from(
            OwnerControlRecord
        ).where(OwnerControlRecord.domain == quotas.FREE_TIER_POLICY_DOMAIN))
        assert count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,key", [
    ("message", "monthly_user_message_limit"),
    ("response", "monthly_assistant_response_limit"),
])
async def test_cached_policy_accepts_owner_increased_counter_limit(case, kind, key):
    await _change(case, {key: 1})
    async with case.sessions() as session, session.begin():
        await _consume(session, case.actor, kind)
    async with case.sessions() as stale:
        held = await _policy_row(stale)
        assert held.payload[key] == 1
        await _change(case, {key: 3})
        await _consume(stale, case.actor, kind)
        await stale.commit()
    counter = "user_messages_used" if kind == "message" else "assistant_responses_used"
    assert (await _stored(case))[0][counter] == 2
