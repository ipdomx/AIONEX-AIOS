"""Real loopback WebSockets + disposable PostgreSQL/Redis revocation acceptance.

No production DB, token, peer, provider, user or media device is used. Transport
and persistence are real; only the idle-check interval is shortened in tests.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.api.v1.endpoints import websocket as endpoint
from app.core import auth
from app.core.config import settings
from app.db import redis as redis_module
from app.db.base import Base
from app.db.models import Organization, Permission, Role, RolePermission, User
from app.realtime.runtime import RealtimeEventRuntime


def dependency_tables():
    seen = set()

    def visit(table):
        if table.name in seen:
            return
        seen.add(table.name)
        for foreign_key in table.foreign_keys:
            visit(foreign_key.column.table)

    for name in ("users", "role_permissions", "owner_control_records"):
        visit(Base.metadata.tables[name])
    return [t for t in Base.metadata.sorted_tables if t.name in seen]


@pytest_asyncio.fixture
async def live(monkeypatch):
    url = make_url(os.environ["DATABASE_URL"])
    assert os.environ.get("ENVIRONMENT") == "test"
    assert url.drivername == "postgresql+asyncpg"
    assert re.search(r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)", url.database or "")
    redis_url = os.environ["REDIS_URL"]
    assert make_url(redis_url).host in {"redis", "localhost", "127.0.0.1"} or "disposable" in (make_url(redis_url).host or "")
    schema = "fr07_ws_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={
        "server_settings": {"search_path": schema, "statement_timeout": "5000"},
    })
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(redis_url, decode_responses=True)
    runtime, publisher = RealtimeEventRuntime(), RealtimeEventRuntime()
    server = task = listener = None
    created = False
    state = SimpleNamespace(sessions=sessions, users=[], actors=[], credentials=[],
                            roles=[], organizations=[], runtime=runtime, publisher=publisher)

    async def real_redis():
        return redis

    monkeypatch.setattr(auth, "get_redis", real_redis)
    monkeypatch.setattr(redis_module, "get_redis", real_redis)
    monkeypatch.setattr(endpoint, "SessionLocal", sessions)
    monkeypatch.setattr(endpoint, "realtime_event_runtime", runtime)
    monkeypatch.setattr(endpoint, "IDLE_REVALIDATION_SECONDS", 0.1, raising=False)
    try:
        async with admin.begin() as conn:
            await conn.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=dependency_tables()))
        async with sessions() as session, session.begin():
            permission = Permission(id=str(uuid4()), code="projects:read")
            session.add(permission)
            for _ in range(2):
                org = Organization(id=str(uuid4()), name="Disposable socket tenant", slug=uuid4().hex, plan="enterprise")
                session.add(org)
                await session.flush()
                role = Role(id=str(uuid4()), organization_id=org.id, name="Builder")
                session.add(role)
                await session.flush()
                user = User(id=str(uuid4()), organization_id=org.id, role_id=role.id,
                            name="Disposable socket user", email=uuid4().hex+"@example.invalid",
                            password_hash="not-an-account-password", auth_version=0)
                session.add_all([user, RolePermission(role_id=role.id, permission_id=permission.id)])
                await session.flush()
                actor = await auth.auth_service.get_user_by_id(session, user.id)
                state.organizations.append(org.id)
                state.roles.append(role.id)
                state.users.append(user.id)
                state.actors.append(actor)
                state.credentials.append(auth.auth_service.create_access_token(actor))
        await runtime.start()
        await publisher.start()
        app = FastAPI()
        app.include_router(endpoint.router, prefix="/api/v1/realtime")
        from main import websocket_endpoint
        app.add_api_websocket_route("/ws/{client_id}", websocket_endpoint)
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(64)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
            lifespan="off", access_log=False, log_level="error", ws="websockets-sansio"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
                raise AssertionError("Disposable websocket server exited")
            await asyncio.sleep(0.01)
        assert server.started
        state.base = f"ws://127.0.0.1:{port}"
        yield state
    finally:
        if server is not None:
            server.should_exit = True
        if task is not None:
            await asyncio.wait_for(task, 10)
        if listener is not None:
            listener.close()
        await publisher.stop()
        await runtime.stop()
        await asyncio.sleep(0)
        assert not [t for t in asyncio.all_tasks() if not t.done()
                    and t.get_name() == "aionex-realtime-redis-listener"]
        await redis.aclose()
        await engine.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


def connection(live, index=0, credential=None):
    value = credential if credential is not None else live.credentials[index]
    return connect(live.base+"/api/v1/realtime/connect?token="+value,
                   open_timeout=3, close_timeout=2, ping_interval=None)


async def receive_json(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 3))


async def mutate(live, change):
    async with live.sessions() as session, session.begin():
        user = await session.get(User, live.users[0])
        if change == "suspended":
            user.status = "suspended"
        elif change == "banned":
            user.status = "banned"
        elif change == "deleted":
            user.deleted_at = datetime.now(UTC)
        elif change == "generation":
            user.auth_version += 1
        elif change == "organization":
            user.organization_id = live.organizations[1]
        elif change == "org_suspended":
            org = await session.get(Organization, live.organizations[0])
            org.status = "suspended"
        elif change == "free_plan":
            org = await session.get(Organization, live.organizations[0])
            org.plan = "free"
        elif change == "role_suspended":
            role = await session.get(Role, live.roles[0])
            role.status = "suspended"
        elif change == "role_removed":
            user.role_id = None
        elif change == "permission_removed":
            await session.execute(delete(RolePermission).where(RolePermission.role_id == live.roles[0]))
        else:
            raise AssertionError("Unknown isolated mutation")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["suspended", "banned", "deleted", "generation",
    "organization", "org_suspended", "free_plan", "role_suspended", "role_removed", "permission_removed"])
async def test_committed_revocation_prevents_next_cross_replica_event(live, change):
    async with connection(live) as ws:
        assert (await receive_json(ws))["type"] == "connected"
        await live.publisher.publish(live.organizations[0], {"type": "authorized-before"})
        assert (await receive_json(ws))["type"] == "authorized-before"
        await mutate(live, change)
        await live.publisher.publish(live.organizations[0], {"type": "must-not-deliver"})
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(ws.recv(), 3)
        assert ws.close_code == 4403


@pytest.mark.asyncio
async def test_idle_socket_is_closed_after_actual_redis_logout(live):
    async with connection(live) as ws:
        assert (await receive_json(ws))["type"] == "connected"
        await auth.auth_service.revoke_access_token(live.credentials[0])
        await asyncio.wait_for(ws.wait_closed(), 3)
        assert ws.close_code == 4403
    with pytest.raises(InvalidStatus) as rejected:
        async with connection(live):
            raise AssertionError("Revoked credential was reaccepted")
    assert rejected.value.response.status_code == 403


@pytest.mark.asyncio
async def test_expiration_closes_idle_socket_without_waiting_for_client_ping(live):
    claims = auth.auth_service._access_payload(live.actors[0])
    claims["exp"] = int((datetime.now(UTC)+timedelta(seconds=2)).timestamp())
    temporary = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    async with connection(live, credential=temporary) as ws:
        assert (await receive_json(ws))["type"] == "connected"
        await asyncio.wait_for(ws.wait_closed(), 4)
        assert ws.close_code == 4403


@pytest.mark.asyncio
async def test_revocation_isolated_to_user_and_tenant_across_real_backplane(live):
    async with connection(live, 0) as first, connection(live, 1) as second:
        assert (await receive_json(first))["organization_id"] == live.organizations[0]
        assert (await receive_json(second))["organization_id"] == live.organizations[1]
        await live.publisher.publish(live.organizations[0], {"type": "tenant-a"})
        await live.publisher.publish(live.organizations[1], {"type": "tenant-b"})
        assert (await receive_json(first))["type"] == "tenant-a"
        assert (await receive_json(second))["type"] == "tenant-b"
        await mutate(live, "generation")
        await asyncio.wait_for(first.wait_closed(), 3)
        await second.send("ping")
        assert (await receive_json(second)) == {"type": "pong"}
        await live.publisher.publish(live.organizations[1], {"type": "still-authorized"})
        assert (await receive_json(second))["type"] == "still-authorized"


@pytest.mark.asyncio
async def test_legacy_global_broadcast_is_denied_directly_by_application(live):
    with pytest.raises(InvalidStatus) as rejected:
        async with connect(live.base+"/ws/untrusted-client", open_timeout=3, close_timeout=2):
            raise AssertionError("Legacy anonymous global socket accepted")
    assert rejected.value.response.status_code == 403
    assert live.runtime.connected_count() == 0


@pytest.mark.asyncio
async def test_reconnect_uses_fresh_identity_and_does_not_restore_old_authority(live):
    async with connection(live) as original:
        await receive_json(original)
        await mutate(live, "generation")
        await asyncio.wait_for(original.wait_closed(), 3)
    async with live.sessions() as session:
        actor = await auth.auth_service.get_user_by_id(session, live.users[0])
    fresh = auth.auth_service.create_access_token(actor)
    async with connection(live, credential=fresh) as ws:
        assert (await receive_json(ws))["user_id"] == live.users[0]
        await ws.send("ping")
        assert (await receive_json(ws))["type"] == "pong"


@pytest.mark.asyncio
async def test_authentication_store_outage_closes_not_just_drops_one_event(live, monkeypatch):
    async with connection(live) as ws:
        await receive_json(ws)

        async def unavailable():
            raise ConnectionError("synthetic Redis outage")

        monkeypatch.setattr(auth, "get_redis", unavailable)
        await asyncio.wait_for(ws.wait_closed(), 3)
        assert ws.close_code == 1013


@pytest.mark.asyncio
async def test_event_stream_does_not_accept_arbitrary_large_control_payloads(live):
    async with connection(live) as ws:
        await receive_json(ws)
        await ws.send("x"*1025)
        await asyncio.wait_for(ws.wait_closed(), 3)
        assert ws.close_code == 1009


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["role_removed", "permission_removed", "suspended", "free_plan"])
async def test_new_connection_cannot_reacquire_removed_stream_entitlement(live, change):
    await mutate(live, change)
    with pytest.raises(InvalidStatus) as rejected:
        async with connection(live):
            raise AssertionError("Connection reacquired removed entitlement")
    assert rejected.value.response.status_code == 403


@pytest.mark.asyncio
async def test_last_revoked_subscriber_retires_listener_then_new_subscription_works(live):
    async with connection(live) as original:
        await receive_json(original)
        await mutate(live, "generation")
        await live.publisher.publish(live.organizations[0], {"type": "denied"})
        await asyncio.wait_for(original.wait_closed(), 3)
    async with live.sessions() as session:
        actor = await auth.auth_service.get_user_by_id(session, live.users[0])
    fresh = auth.auth_service.create_access_token(actor)
    async with connection(live, credential=fresh) as reopened:
        await receive_json(reopened)
        for index in range(4):
            await live.publisher.publish(live.organizations[0], {"type": "new-subscription", "index": index})
            assert (await receive_json(reopened))["index"] == index


@pytest.mark.asyncio
async def test_same_account_on_multiple_sockets_is_revoked_on_all_of_them(live):
    async with connection(live) as first, connection(live) as second:
        await receive_json(first)
        await receive_json(second)
        await mutate(live, "generation")
        await asyncio.wait_for(asyncio.gather(first.wait_closed(), second.wait_closed()), 3)
        assert first.close_code == second.close_code == 4403
