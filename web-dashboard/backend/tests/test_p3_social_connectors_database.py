"""Real PostgreSQL contract for the P3 social connect flow and tenancy.

Every case runs in a private random schema of an explicitly test-named
database and drives the real ``/api/v1/social`` router. Graph API traffic is
answered in-process by ``httpx.MockTransport``; no provider is contacted.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1.endpoints import social as social_api
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    Organization,
    SocialConnection,
    SocialOAuthState,
    User,
)
from app.services import social_connectors as framework
from app.services.social_meta_provider import DEFAULT_SCOPES, MetaConnector
from tests.test_p3_social_connectors import (
    APP_ID,
    APP_SECRET,
    PAGE_TOKEN,
    PAGE_TOKEN_TWO,
    USER_TOKEN_LONG,
    USER_TOKEN_SHORT,
    GraphStub,
)

PREFIX = "/api/v1/social"
COOKIE = social_api.BINDING_COOKIE
SECRETS = (APP_SECRET, USER_TOKEN_SHORT, USER_TOKEN_LONG, PAGE_TOKEN, PAGE_TOKEN_TWO, "fernet:")


def _required_tables():
    tables = {
        model.__table__
        for model in (AuditEvent, GrowthSocialAccount, Organization, SocialConnection, SocialOAuthState, User)
    }
    while True:
        expanded = tables | {key.column.table for table in tables for key in table.foreign_keys}
        if expanded == tables:
            return list(tables)
        tables = expanded


def _actor(user_id: str, org_id: str, name: str) -> UserRecord:
    return UserRecord(
        id=user_id, email=f"{name}-{user_id}@example.test", name=name, role="User",
        password_hash="unused-synthetic-hash", organization_id=org_id,
        organization_name=f"{name} org", organization_plan="business", permissions=[],
    )


def _assert_no_secrets(response: httpx.Response) -> None:
    text = response.text
    for value in SECRETS:
        assert value not in text, value
    assert "ciphertext" not in text


@pytest_asyncio.fixture
async def social_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("social connector contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])", (url.database or "").lower()
    ) is None:
        raise RuntimeError("social connector tests require an isolated test database")
    schema = f"p3_social_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "application_name": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_a, org_c = str(uuid4()), str(uuid4())
    user_a, user_b, user_c = str(uuid4()), str(uuid4()), str(uuid4())
    stub = GraphStub()
    case = SimpleNamespace(
        sessions=sessions,
        stub=stub,
        alice=_actor(user_a, org_a, "alice"),
        bob=_actor(user_b, org_a, "bob"),  # same organization, different member
        carol=_actor(user_c, org_c, "carol"),  # different organization
    )
    case.current = case.alice

    monkeypatch.setattr(settings, "META_APP_ID", APP_ID)
    monkeypatch.setattr(settings, "META_APP_ID_FILE", "")
    monkeypatch.setattr(settings, "META_APP_SECRET", APP_SECRET)
    monkeypatch.setattr(settings, "META_APP_SECRET_FILE", "")
    monkeypatch.setattr(settings, "META_GRAPH_API_VERSION", "v26.0")
    monkeypatch.setattr(
        settings, "META_OAUTH_REDIRECT_URI", "https://api.vip-e.net/api/v1/social/oauth/meta/callback"
    )
    monkeypatch.setattr(settings, "META_OAUTH_SCOPES", ",".join(DEFAULT_SCOPES))
    monkeypatch.setattr(settings, "META_OAUTH_USE_PKCE", True)
    monkeypatch.setattr(settings, "SOCIAL_PORTAL_URL", "https://ai.vip-e.net")
    monkeypatch.setitem(
        framework._REGISTRY, "meta", lambda: MetaConnector(transport=httpx.MockTransport(stub))
    )

    async def no_rate_limit(_actor, _action):
        return None

    monkeypatch.setattr(social_api, "enforce_rate_limit", no_rate_limit)

    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(sync, tables=_required_tables())
            )
        async with sessions() as session:
            for org_id in (org_a, org_c):
                session.add(Organization(
                    id=org_id, name=f"Org {org_id[:8]}", slug=f"p3-{org_id}",
                    plan="business", status="active",
                ))
            await session.flush()
            for actor in (case.alice, case.bob, case.carol):
                session.add(User(
                    id=actor.id, organization_id=actor.organization_id, name=actor.name,
                    email=actor.email, password_hash="unused-synthetic-hash", status="active",
                ))
            await session.commit()

        async def request_db():
            async with sessions() as session:
                yield session

        async def actor_dependency():
            return case.current

        app = FastAPI()
        app.include_router(social_api.router, prefix=PREFIX)
        app.dependency_overrides[get_db] = request_db
        app.dependency_overrides[current_user] = actor_dependency
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://isolated.test"
        ) as client:
            case.client = client
            yield case
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


async def _start(case, locale: str = "ar") -> tuple[str, str, str]:
    response = await case.client.post(PREFIX + "/connect/meta/start", json={"locale": locale})
    assert response.status_code == 200, response.text
    _assert_no_secrets(response)
    set_cookie_header = response.headers["set-cookie"]
    match = re.search(rf"{COOKIE}=([^;]+)", set_cookie_header)
    assert match is not None
    binding = match.group(1).strip('"')
    set_cookie = set_cookie_header.lower()
    assert "httponly" in set_cookie and "path=/api/v1/social/oauth" in set_cookie
    assert "samesite=lax" in set_cookie
    case.client.cookies.clear()
    query = {key: values[0] for key, values in parse_qs(urlsplit(response.json()["authorize_url"]).query).items()}
    return query["state"], binding, query["code_challenge"]


async def _callback(case, *, binding: str | None, **params: str) -> dict[str, str]:
    headers = {"Cookie": f"{COOKIE}={binding}"} if binding else {}
    response = await case.client.get(PREFIX + "/oauth/meta/callback", params=params, headers=headers)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert USER_TOKEN_LONG not in location and "good-code" not in location
    parts = urlsplit(location)
    assert parts.netloc == "ai.vip-e.net"
    result = {key: values[0] for key, values in parse_qs(parts.query).items()}
    result["path"] = parts.path
    return result


@pytest.mark.asyncio
async def test_state_validation_rejects_missing_wrong_binding_replay_denial_and_expiry(social_case):
    case = social_case
    missing = await _callback(case, binding=None, code="good-code")
    assert missing["result"] == "error" and missing["code"] == "oauth-state-missing"
    forged = await _callback(case, binding="x", code="good-code", state="forged-state")
    assert forged["code"] == "oauth-state-invalid"

    state, binding, _challenge = await _start(case, "ar")
    mismatch = await _callback(case, binding="another-browser", code="good-code", state=state)
    assert mismatch["code"] == "oauth-state-binding-mismatch"
    assert mismatch["path"] == "/ar/social/"
    replay = await _callback(case, binding=binding, code="good-code", state=state)
    assert replay["code"] == "oauth-state-replayed"

    state, binding, _challenge = await _start(case, "fr")
    denied = await _callback(case, binding=binding, state=state, error="access_denied")
    assert denied["code"] == "oauth-access-denied" and denied["path"] == "/fr/social/"

    state, binding, _challenge = await _start(case)
    async with case.sessions() as session:
        row = await session.scalar(
            select(SocialOAuthState).where(SocialOAuthState.state_hash == framework.digest(state))
        )
        assert row is not None and row.user_id == case.alice.id
        assert state not in json.dumps([row.state_hash, row.browser_binding_hash])
        assert row.code_verifier_ciphertext and row.code_verifier_ciphertext.startswith("fernet:v1:")
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    expired = await _callback(case, binding=binding, code="good-code", state=state)
    assert expired["code"] == "oauth-state-expired"

    # No grant was stored by any failed attempt, and no Graph call was made.
    assert case.stub.requests == []
    async with case.sessions() as session:
        assert (await session.scalars(select(SocialConnection))).all() == []
        actions = {row.action for row in (await session.scalars(select(AuditEvent))).all()}
    assert {"social.oauth.started", "social.oauth.failed"} <= actions


@pytest.mark.asyncio
async def test_full_connect_flow_encrypts_tokens_and_disconnect_revokes(social_case):
    case = social_case
    providers = await case.client.get(PREFIX + "/providers")
    meta = next(item for item in providers.json()["items"] if item["key"] == "meta")
    assert meta["status"] == "configured"
    _assert_no_secrets(providers)

    state, binding, challenge = await _start(case, "ar")
    result = await _callback(case, binding=binding, code="good-code", state=state)
    assert result["result"] == "success" and result["code"] == "connected"
    assert result["path"] == "/ar/social/"
    connection_id = result["connection"]

    # PKCE end to end: the verifier sent on exchange hashes to the challenge.
    exchange = dict(case.stub.requests[0].url.params)
    assert framework.code_challenge_s256(exchange["code_verifier"]) == challenge
    assert dict(case.stub.requests[1].url.params)["grant_type"] == "fb_exchange_token"

    async with case.sessions() as session:
        connection = await session.get(SocialConnection, connection_id)
        assert connection is not None
        assert connection.user_id == case.alice.id
        assert connection.status == "pending_selection"
        assert connection.external_user_id == "99887766"
        assert USER_TOKEN_LONG not in (connection.token_ciphertext or "")
        assert framework.open_token(connection.token_ciphertext) == USER_TOKEN_LONG
        assert set(connection.granted_scopes) == set(DEFAULT_SCOPES)
        state_row = await session.scalar(select(SocialOAuthState))
        assert state_row is not None and state_row.consumed_at is not None

    listed = await case.client.get(PREFIX + "/connections")
    assert [item["id"] for item in listed.json()["items"]] == [connection_id]
    _assert_no_secrets(listed)

    assets = await case.client.get(f"{PREFIX}/connections/{connection_id}/assets")
    assert assets.status_code == 200, assets.text
    _assert_no_secrets(assets)
    ids = {item["asset_id"] for item in assets.json()["items"]}
    assert ids == {"facebook:1111111", "instagram:17841400000000001", "facebook:2222222"}

    unknown = await case.client.post(
        f"{PREFIX}/connections/{connection_id}/assets", json={"asset_ids": ["facebook:404404"]}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "asset-not-available"

    connected = await case.client.post(
        f"{PREFIX}/connections/{connection_id}/assets",
        json={"asset_ids": ["facebook:1111111", "instagram:17841400000000001"]},
    )
    assert connected.status_code == 200, connected.text
    _assert_no_secrets(connected)
    items = {item["provider"]: item for item in connected.json()["items"]}
    assert set(items) == {"facebook", "instagram"}
    assert items["instagram"]["handle"] == "main.brand"
    assert items["instagram"]["linked_external_id"] == "1111111"
    assert all(item["credential_stored"] is True for item in items.values())

    async with case.sessions() as session:
        rows = (await session.scalars(select(GrowthSocialAccount))).all()
        assert len(rows) == 2
        for row in rows:
            assert row.created_by_id == case.alice.id and row.connected_via == "oauth"
            assert PAGE_TOKEN not in (row.token_ciphertext or "")
            assert framework.open_token(row.token_ciphertext) == PAGE_TOKEN
        connection = await session.get(SocialConnection, connection_id)
        assert connection is not None and connection.status == "active"

    mine = await case.client.get(PREFIX + "/accounts")
    assert len(mine.json()["items"]) == 2
    _assert_no_secrets(mine)

    health = await case.client.post(f"{PREFIX}/accounts/{items['facebook']['id']}/health")
    assert health.status_code == 200, health.text
    assert health.json()["health_state"] == "healthy"
    assert health.json()["last_health_at"]
    _assert_no_secrets(health)

    first = await case.client.delete(f"{PREFIX}/accounts/{items['facebook']['id']}")
    assert first.status_code == 200
    assert first.json()["connection_revoked"] is False
    assert case.stub.revoked is False
    last = await case.client.delete(f"{PREFIX}/accounts/{items['instagram']['id']}")
    assert last.status_code == 200
    assert last.json()["connection_revoked"] is True
    assert last.json()["provider_revoked"] is True
    assert case.stub.revoked is True
    _assert_no_secrets(last)

    async with case.sessions() as session:
        for row in (await session.scalars(select(GrowthSocialAccount))).all():
            assert row.status == "revoked"
            assert row.token_ciphertext is None and row.credential_ref is None
        connection = await session.get(SocialConnection, connection_id)
        assert connection is not None
        assert connection.status == "revoked" and connection.token_ciphertext is None
        actions = {row.action for row in (await session.scalars(select(AuditEvent))).all()}
        audit_text = json.dumps(
            [row.details for row in (await session.scalars(select(AuditEvent))).all()]
        )
    assert {
        "social.oauth.started",
        "social.oauth.connected",
        "social.account.connected",
        "social.account.health_checked",
        "social.account.disconnected",
        "social.connection.revoked",
    } <= actions
    for value in SECRETS:
        assert value not in audit_text

    assert (await case.client.get(PREFIX + "/accounts")).json()["items"] == []


@pytest.mark.asyncio
async def test_members_and_other_organizations_cannot_see_or_touch_accounts(social_case):
    case = social_case
    state, binding, _challenge = await _start(case)
    connection_id = (await _callback(case, binding=binding, code="good-code", state=state))["connection"]
    connected = await case.client.post(
        f"{PREFIX}/connections/{connection_id}/assets", json={"asset_ids": ["facebook:1111111"]}
    )
    account_id = connected.json()["items"][0]["id"]

    for intruder in (case.bob, case.carol):
        case.current = intruder
        assert (await case.client.get(PREFIX + "/accounts")).json()["items"] == []
        assert (await case.client.get(PREFIX + "/connections")).json()["items"] == []
        for response in (
            await case.client.get(f"{PREFIX}/connections/{connection_id}/assets"),
            await case.client.post(
                f"{PREFIX}/connections/{connection_id}/assets",
                json={"asset_ids": ["facebook:1111111"]},
            ),
            await case.client.delete(f"{PREFIX}/connections/{connection_id}"),
            await case.client.post(f"{PREFIX}/accounts/{account_id}/health"),
            await case.client.delete(f"{PREFIX}/accounts/{account_id}"),
        ):
            assert response.status_code == 404, response.text

    # Another user's state cannot be completed from Bob's browser either: the
    # state belongs to Alice and the binding cookie never left her browser.
    case.current = case.alice
    state, _alice_binding, _challenge = await _start(case)
    hijack = await _callback(case, binding="bob-browser", code="good-code", state=state)
    assert hijack["code"] == "oauth-state-binding-mismatch"

    case.current = case.alice
    still_mine = await case.client.get(PREFIX + "/accounts")
    assert [item["id"] for item in still_mine.json()["items"]] == [account_id]
    async with case.sessions() as session:
        row = await session.get(GrowthSocialAccount, account_id)
        assert row is not None and row.status == "active" and row.token_ciphertext


@pytest.mark.asyncio
async def test_not_configured_provider_refuses_to_start(social_case, monkeypatch):
    case = social_case
    for name in ("META_APP_ID", "META_APP_SECRET"):
        monkeypatch.setattr(settings, name, "")
    providers = await case.client.get(PREFIX + "/providers")
    meta = next(item for item in providers.json()["items"] if item["key"] == "meta")
    assert meta["status"] == "not_configured" and meta["connectable"] is False
    started = await case.client.post(PREFIX + "/connect/meta/start", json={"locale": "en"})
    assert started.status_code == 409
    assert started.json()["detail"]["code"] == "provider-not-configured"
    assert COOKIE not in started.headers.get("set-cookie", "")
    coming = await case.client.post(PREFIX + "/connect/tiktok/start", json={"locale": "en"})
    assert coming.status_code == 409
    assert coming.json()["detail"]["code"] == "provider-coming-soon"
    async with case.sessions() as session:
        assert (await session.scalars(select(SocialOAuthState))).all() == []
