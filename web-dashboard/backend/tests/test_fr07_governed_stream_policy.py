"""Governance changes across real WebSockets, PostgreSQL and Redis.

The policy rows are synthetic fixture changes. Transport, JWT validation,
backplane delivery and the policy reader are the actual application functions.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.db.models import OwnerControlRecord
from app.services import conversation_governance as governance
from tests import test_fr07d_event_stream_revocation as sockets

live = sockets.live


async def set_policy(live, scope: str, enabled: bool, *, malformed: bool = False):
    key = {"global": governance.GLOBAL, "plan": "plan:enterprise", "user": "user:" + live.users[0]}[scope]
    async with live.sessions() as session, session.begin():
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == governance.POLICY, OwnerControlRecord.resource_id == key).with_for_update())
        if row is None:
            row = OwnerControlRecord(id=str(uuid4()), domain=governance.POLICY, resource_id=key, version=1)
            session.add(row)
        row.enabled = enabled
        row.status = "active" if enabled else "suspended"
        row.payload = {"schema": 99 if malformed else 1, "values": {"enabled": enabled}}
        row.version += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["global", "plan", "user"])
async def test_governance_suspension_stops_next_real_cross_replica_event(live, scope):
    async with sockets.connection(live) as connection:
        assert (await sockets.receive_json(connection))["type"] == "connected"
        await live.publisher.publish(live.organizations[0], {"type": "before-policy-change"})
        assert (await sockets.receive_json(connection))["type"] == "before-policy-change"
        await set_policy(live, scope, False)
        await live.publisher.publish(live.organizations[0], {"type": "must-not-deliver"})
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(connection.recv(), 3)
        assert connection.close_code == 4403
    with pytest.raises(InvalidStatus) as denied:
        async with sockets.connection(live):
            raise AssertionError("Suspended governance was bypassed on reconnect")
    assert denied.value.response.status_code == 403


@pytest.mark.asyncio
async def test_user_override_does_not_revoke_another_tenants_socket(live):
    async with sockets.connection(live, 0) as first, sockets.connection(live, 1) as second:
        await sockets.receive_json(first)
        await sockets.receive_json(second)
        await set_policy(live, "user", False)
        await asyncio.wait_for(first.wait_closed(), 3)
        assert first.close_code == 4403
        await live.publisher.publish(live.organizations[1], {"type": "other-tenant-still-authorized"})
        assert (await sockets.receive_json(second))["type"] == "other-tenant-still-authorized"


@pytest.mark.asyncio
async def test_reenabled_policy_requires_new_socket_and_keeps_original_credential(live):
    async with sockets.connection(live) as original:
        await sockets.receive_json(original)
        await set_policy(live, "user", False)
        await asyncio.wait_for(original.wait_closed(), 3)
        assert original.close_code == 4403
        await set_policy(live, "user", True)
        assert original.close_code == 4403
    async with sockets.connection(live) as fresh:
        assert (await sockets.receive_json(fresh))["user_id"] == live.users[0]
        await live.publisher.publish(live.organizations[0], {"type": "new-authorized-connection"})
        assert (await sockets.receive_json(fresh))["type"] == "new-authorized-connection"


@pytest.mark.asyncio
async def test_malformed_governance_closes_instead_of_permitting_stream(live):
    async with sockets.connection(live) as connection:
        await sockets.receive_json(connection)
        await set_policy(live, "global", True, malformed=True)
        await asyncio.wait_for(connection.wait_closed(), 3)
        assert connection.close_code == 1013
