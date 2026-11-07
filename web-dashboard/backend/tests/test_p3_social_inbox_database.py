"""Real PostgreSQL contract for the P3 unified inbox and Meta callbacks.

Every case runs in a private random schema of an explicitly test-named
database and drives the real ``/api/v1/social`` inbox and Meta callback
routers, the real store and the real poll fallback. Graph API traffic is
answered in-process by ``httpx.MockTransport``; no provider is contacted.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1.endpoints import social as social_api
from app.api.v1.endpoints import social_inbox as inbox_api
from app.api.v1.endpoints import social_meta_callbacks as callbacks_api
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    Organization,
    SocialConnection,
    SocialDataDeletionRequest,
    SocialInboxConversation,
    SocialInboxMessage,
    SocialWebhookEvent,
    User,
)
from app.services import social_connectors as framework
from app.services import social_inbox as inbox_service
from app.services.social_inbox_backfill import InboxBackfill
from app.services.social_meta_inbox import MetaInboxClient
from tests.test_p3_social_inbox import (
    APP_ID,
    APP_SECRET,
    CUSTOMER_IGSID,
    CUSTOMER_PSID,
    IG_ID,
    PAGE_ID,
    PAGE_TOKEN,
    VERIFY_TOKEN,
    InboxGraph,
    feed_payload,
    messenger_payload,
    sign,
    signed_request,
)

PREFIX = "/api/v1/social"
META_USER = "2200000000000001"


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AuditEvent, GrowthSocialAccount, Organization, SocialConnection,
            SocialDataDeletionRequest, SocialInboxConversation, SocialInboxMessage,
            SocialWebhookEvent, User,
        )
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


def _account(actor, provider, kind, external_id, name, *, scopes=(), connection_id=None, linked=None):
    return GrowthSocialAccount(
        id=str(uuid4()),
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        provider=provider,
        account_kind=kind,
        external_account_id=external_id,
        display_name=name,
        status="active",
        health_state="healthy",
        health_reasons=[],
        provider_metadata={"connector": "meta", "linked_external_id": linked},
        settings={},
        version=1,
        connected_via="oauth",
        connection_id=connection_id,
        scopes=list(scopes),
        token_ciphertext=framework.seal_token(PAGE_TOKEN),
    )


@pytest_asyncio.fixture
async def inbox_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("social inbox contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])", (url.database or "").lower()
    ) is None:
        raise RuntimeError("social inbox tests require an isolated test database")
    schema = f"p3_inbox_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "application_name": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_a, org_c = str(uuid4()), str(uuid4())
    graph = InboxGraph()
    case = SimpleNamespace(
        sessions=sessions,
        graph=graph,
        alice=_actor(str(uuid4()), org_a, "alice"),
        bob=_actor(str(uuid4()), org_a, "bob"),
        carol=_actor(str(uuid4()), org_c, "carol"),
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
    monkeypatch.setattr(settings, "META_WEBHOOK_VERIFY_TOKEN", VERIFY_TOKEN)
    monkeypatch.setattr(settings, "META_WEBHOOK_VERIFY_TOKEN_FILE", "")
    monkeypatch.setattr(settings, "SOCIAL_PORTAL_URL", "https://ai.vip-e.net")
    if len(str(settings.SECRET_KEY or "")) < 32:
        monkeypatch.setattr(settings, "SECRET_KEY", "p3-inbox-test-secret-key-0123456789abc")

    async def no_rate_limit(_actor, _action):
        return None

    monkeypatch.setattr(social_api, "enforce_rate_limit", no_rate_limit)
    monkeypatch.setattr(
        inbox_service, "MetaInboxClient", lambda: MetaInboxClient(transport=httpx.MockTransport(graph))
    )
    case.backfill = lambda: InboxBackfill(
        sessions, client=MetaInboxClient(transport=httpx.MockTransport(graph)), interval_seconds=60
    )

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
                    id=org_id, name=f"Org {org_id[:8]}", slug=f"p3i-{org_id}",
                    plan="business", status="active",
                ))
            await session.flush()
            for actor in (case.alice, case.bob, case.carol):
                session.add(User(
                    id=actor.id, organization_id=actor.organization_id, name=actor.name,
                    email=actor.email, password_hash="unused-synthetic-hash", status="active",
                ))
            await session.flush()
            connection = SocialConnection(
                id=str(uuid4()), organization_id=org_a, user_id=case.alice.id, provider="meta",
                external_user_id=META_USER, display_name="Alice Meta", requested_scopes=[],
                granted_scopes=["pages_messaging"], token_ciphertext=framework.seal_token("EAAuser"),
                status="active", health_state="healthy", health_reasons=[], version=1,
            )
            session.add(connection)
            await session.flush()
            fb_scopes = inbox_service.REQUIRED_SCOPES["facebook"]
            ig_scopes = inbox_service.REQUIRED_SCOPES["instagram"]
            case.connection_id = connection.id
            case.fb = _account(case.alice, "facebook", "page", PAGE_ID, "Alice Page", scopes=fb_scopes, connection_id=connection.id)
            case.ig = _account(case.alice, "instagram", "business", IG_ID, "alice.ig", scopes=ig_scopes, connection_id=connection.id, linked=PAGE_ID)
            case.bob_fb = _account(case.bob, "facebook", "page", "3333333", "Bob Page")
            # Another organization connected the same Page: it gets its own copy.
            case.carol_fb = _account(case.carol, "facebook", "page", PAGE_ID, "Carol view", scopes=fb_scopes)
            for row in (case.fb, case.ig, case.bob_fb, case.carol_fb):
                session.add(row)
            await session.commit()

        async def request_db():
            async with sessions() as session:
                yield session

        async def actor_dependency():
            return case.current

        app = FastAPI()
        app.include_router(social_api.router, prefix=PREFIX)
        app.include_router(inbox_api.router, prefix=PREFIX)
        app.include_router(callbacks_api.router, prefix=PREFIX)
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


async def _deliver(case, payload: dict, *, signature: str | None = None):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-Hub-Signature-256": signature or sign(body)}
    return await case.client.post(PREFIX + "/meta/webhooks", content=body, headers=headers)


async def _conversations(case, actor, **params) -> list[dict]:
    case.current = actor
    response = await case.client.get(PREFIX + "/inbox/conversations", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


# --- webhook: challenge, signature, idempotency -----------------------------------------


@pytest.mark.asyncio
async def test_webhook_challenge_and_signature_are_enforced_over_http(inbox_case):
    case = inbox_case
    ok = await case.client.get(PREFIX + "/meta/webhooks", params={
        "hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1158201444",
    })
    assert ok.status_code == 200 and ok.text == "1158201444"
    bad = await case.client.get(PREFIX + "/meta/webhooks", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong-token-000000000", "hub.challenge": "1",
    })
    assert bad.status_code == 403

    body = json.dumps(feed_payload()).encode()
    unsigned = await case.client.post(PREFIX + "/meta/webhooks", content=body, headers={"Content-Type": "application/json"})
    assert unsigned.status_code == 403
    forged = await _deliver(case, feed_payload(), signature=sign(body, "another-app-secret"))
    assert forged.status_code == 403
    async with case.sessions() as session:
        assert await session.scalar(select(func.count(SocialInboxMessage.id))) == 0
        assert await session.scalar(select(func.count(SocialWebhookEvent.id))) == 0


@pytest.mark.asyncio
async def test_redelivered_changes_are_stored_once_per_matching_account(inbox_case):
    case = inbox_case
    first = await _deliver(case, feed_payload())
    assert first.status_code == 200, first.text
    assert first.json() == {"received": 1, "applied": 2, "duplicates": 0}  # Alice and Carol
    again = await _deliver(case, feed_payload())
    assert again.json() == {"received": 1, "applied": 0, "duplicates": 1}

    [mine] = await _conversations(case, case.alice)
    assert (mine["provider"], mine["channel"], mine["unread_count"]) == ("facebook", "comment", 1)
    assert mine["participant_name"] == "Mona" and mine["account_name"] == "Alice Page"
    [theirs] = await _conversations(case, case.carol)
    assert theirs["id"] != mine["id"] and theirs["account_name"] == "Carol view"
    assert await _conversations(case, case.bob) == []

    # An edit is a new change: it updates the text without counting a new unread message.
    edited = await _deliver(case, feed_payload("edited", message="كم السعر للمقاس الكبير؟"))
    assert edited.json()["applied"] == 2
    case.current = case.alice
    thread = (await case.client.get(f"{PREFIX}/inbox/conversations/{mine['id']}")).json()
    assert [item["body"] for item in thread["messages"]] == ["كم السعر للمقاس الكبير؟"]
    assert thread["unread_count"] == 1

    # Messenger and an unknown Page: one DM thread each for Alice and Carol, nothing else.
    await _deliver(case, messenger_payload(timestamp=_now_ms()))
    unknown = feed_payload()
    unknown["entry"][0]["id"] = "9999999"
    assert (await _deliver(case, unknown)).json()["applied"] == 0
    assert [item["channel"] for item in await _conversations(case, case.alice, channel="dm")] == ["dm"]
    assert len(await _conversations(case, case.alice, unread="true")) == 2
    assert await _conversations(case, case.alice, platform="instagram") == []
    async with case.sessions() as session:
        outcomes = (await session.scalars(select(SocialWebhookEvent.outcome))).all()
    assert sorted(outcomes) == ["stored", "stored", "stored", "unmatched"]


# --- tenancy -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_members_and_organizations_cannot_read_or_act(inbox_case):
    case = inbox_case
    await _deliver(case, feed_payload())
    [mine] = await _conversations(case, case.alice)
    case.current = case.alice
    message_id = (await case.client.get(f"{PREFIX}/inbox/conversations/{mine['id']}")).json()["messages"][0]["id"]
    for other in (case.bob, case.carol):
        case.current = other
        assert (await case.client.get(f"{PREFIX}/inbox/conversations/{mine['id']}")).status_code == 404
        assert (await case.client.patch(f"{PREFIX}/inbox/conversations/{mine['id']}", json={"read": True})).status_code == 404
        assert (await case.client.post(f"{PREFIX}/inbox/conversations/{mine['id']}/reply", json={"text": "x"})).status_code == 404
        assert (await case.client.post(f"{PREFIX}/inbox/conversations/{mine['id']}/suggest", json={})).status_code == 404
        assert (await case.client.post(f"{PREFIX}/inbox/messages/{message_id}/visibility", json={"hidden": True})).status_code == 404
        assert (await case.client.post(f"{PREFIX}/inbox/accounts/{case.fb.id}/subscribe")).status_code == 404
    assert case.graph.calls == []

    case.current = case.alice
    assigned = await case.client.patch(
        f"{PREFIX}/inbox/conversations/{mine['id']}", json={"read": True, "status": "pending", "assigned_to_id": case.bob.id}
    )
    assert assigned.status_code == 200, assigned.text
    assert (assigned.json()["unread_count"], assigned.json()["status"], assigned.json()["assigned_to_id"]) == (0, "pending", case.bob.id)
    outsider = await case.client.patch(f"{PREFIX}/inbox/conversations/{mine['id']}", json={"assigned_to_id": case.carol.id})
    assert outsider.status_code == 422 and outsider.json()["detail"]["code"] == "assignee-not-found"


# --- actions against the mocked Graph API ----------------------------------------------


@pytest.mark.asyncio
async def test_comment_reply_and_hide_go_through_graph_and_are_recorded(inbox_case):
    case = inbox_case
    await _deliver(case, feed_payload())
    [conversation] = await _conversations(case, case.alice)
    case.graph.on("POST", f"{PAGE_ID}_2001/comments", (200, {"id": f"{PAGE_ID}_2009"}))
    case.graph.on("POST", f"{PAGE_ID}_2001", (200, {"success": True}))

    replied = await case.client.post(
        f"{PREFIX}/inbox/conversations/{conversation['id']}/reply", json={"text": "السعر 250 جنيه"}
    )
    assert replied.status_code == 200, replied.text
    body = replied.json()
    assert body["status"] == "pending" and body["unread_count"] == 0
    outbound = body["messages"][-1]
    assert (outbound["direction"], outbound["external_message_ref"], outbound["body"]) == (
        "outbound", f"{PAGE_ID}_2009", "السعر 250 جنيه"
    )
    assert outbound["sent_by_id"] == case.alice.id
    assert case.graph.calls[0][:2] == ("POST", f"{PAGE_ID}_2001/comments")

    # The webhook echo of our own reply is deduplicated by its Graph id.
    echo = feed_payload(comment_id=f"{PAGE_ID}_2009", parent=f"{PAGE_ID}_2001", author=PAGE_ID, message="السعر 250 جنيه")
    assert (await _deliver(case, echo)).json()["applied"] == 1  # Carol's copy only

    inbound_id = body["messages"][0]["id"]
    hidden = await case.client.post(f"{PREFIX}/inbox/messages/{inbound_id}/visibility", json={"hidden": True})
    assert hidden.status_code == 200 and hidden.json()["messages"][0]["hidden"] is True
    assert case.graph.calls[-1][3] == {"is_hidden": "true"}
    refused = await case.client.post(f"{PREFIX}/inbox/messages/{outbound['id']}/visibility", json={"hidden": True})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "message-not-moderatable"


@pytest.mark.asyncio
async def test_dm_replies_respect_the_24_hour_window(inbox_case):
    case = inbox_case
    await _deliver(case, messenger_payload(timestamp=_now_ms()))
    [dm] = await _conversations(case, case.alice, channel="dm")
    assert dm["reply_window"]["applies"] is True and dm["reply_window"]["open"] is True
    case.graph.on("POST", f"{PAGE_ID}/messages", (200, {"recipient_id": CUSTOMER_PSID, "message_id": "m_reply_1"}))
    sent = await case.client.post(f"{PREFIX}/inbox/conversations/{dm['id']}/reply", json={"text": "Yes, it is."})
    assert sent.status_code == 200, sent.text
    assert case.graph.calls[-1][3]["recipient"] == {"id": CUSTOMER_PSID}
    assert case.graph.calls[-1][3]["messaging_type"] == "RESPONSE"

    async with case.sessions() as session:
        row = await session.get(SocialInboxConversation, dm["id"])
        row.last_inbound_at = datetime.now(UTC) - timedelta(hours=24, minutes=1)
        await session.commit()
    calls = len(case.graph.calls)
    closed = await case.client.post(f"{PREFIX}/inbox/conversations/{dm['id']}/reply", json={"text": "Late reply"})
    assert closed.status_code == 409 and closed.json()["detail"]["code"] == "messaging-window-closed"
    assert len(case.graph.calls) == calls
    thread = (await case.client.get(f"{PREFIX}/inbox/conversations/{dm['id']}")).json()
    assert thread["reply_window"]["open"] is False

    # A token error marks the account for reconnect and records no reply.
    async with case.sessions() as session:
        row = await session.get(SocialInboxConversation, dm["id"])
        row.last_inbound_at = datetime.now(UTC)
        await session.commit()
    case.graph.on("POST", f"{PAGE_ID}/messages", (400, {"error": {"code": 190, "message": "expired"}}))
    expired = await case.client.post(f"{PREFIX}/inbox/conversations/{dm['id']}/reply", json={"text": "x"})
    assert expired.status_code == 409 and expired.json()["detail"]["code"] == "account-reconnect-required"
    async with case.sessions() as session:
        assert (await session.get(GrowthSocialAccount, case.fb.id)).status == "expired"
        assert await session.scalar(
            select(func.count(SocialInboxMessage.id)).where(SocialInboxMessage.direction == "outbound")
        ) == 1


@pytest.mark.asyncio
async def test_instagram_dm_reply_uses_the_linked_page(inbox_case):
    case = inbox_case
    payload = messenger_payload("aWdfZAG1faXRlbToxOklHTWVzc2FnZAUlEOjE3ODQx", timestamp=_now_ms())
    payload["object"] = "instagram"
    payload["entry"][0]["id"] = IG_ID
    payload["entry"][0]["messaging"][0]["sender"]["id"] = CUSTOMER_IGSID
    payload["entry"][0]["messaging"][0]["recipient"]["id"] = IG_ID
    assert (await _deliver(case, payload)).json()["applied"] == 1
    [dm] = await _conversations(case, case.alice, platform="instagram")
    case.graph.on("POST", f"{PAGE_ID}/messages", (200, {"recipient_id": CUSTOMER_IGSID, "message_id": "aWdfreply1"}))
    sent = await case.client.post(f"{PREFIX}/inbox/conversations/{dm['id']}/reply", json={"text": "أهلاً"})
    assert sent.status_code == 200, sent.text
    assert case.graph.calls[-1][1] == f"{PAGE_ID}/messages"
    assert case.graph.calls[-1][3]["recipient"] == {"id": CUSTOMER_IGSID}


@pytest.mark.asyncio
async def test_status_reports_permissions_and_subscribe_calls_graph(inbox_case):
    case = inbox_case
    case.current = case.bob
    bob = (await case.client.get(PREFIX + "/inbox/status")).json()
    assert bob["live_verified"] is False and bob["webhook_configured"] is True
    assert bob["webhook_url"].endswith("/api/v1/social/meta/webhooks")
    assert [item["state"] for item in bob["accounts"]] == ["awaiting_permission"]
    case.current = case.alice
    alice = (await case.client.get(PREFIX + "/inbox/status")).json()
    assert {item["state"] for item in alice["accounts"]} == {"ready"}
    case.graph.on("POST", f"{PAGE_ID}/subscribed_apps", (200, {"success": True}))
    subscribed = await case.client.post(f"{PREFIX}/inbox/accounts/{case.ig.id}/subscribe")
    assert subscribed.status_code == 200 and subscribed.json()["webhook_subscribed_at"]
    assert case.graph.calls[-1][3] == {"subscribed_fields": "feed,messages"}


# --- poll fallback ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_fallback_is_idempotent_with_webhook_deliveries(inbox_case):
    case = inbox_case
    await _deliver(case, feed_payload())
    graph = case.graph
    graph.on("GET", f"{PAGE_ID}/feed", (200, {"data": [{"id": f"{PAGE_ID}_1001", "comments": {"data": [
        {"id": f"{PAGE_ID}_2001", "message": "كم السعر؟", "from": {"id": "5000000000000001", "name": "Mona"}, "created_time": "2026-11-06T10:00:00+0000"},
        {"id": f"{PAGE_ID}_2005", "message": "Delivery?", "from": {"id": "5000000000000002", "name": "Hany"}, "created_time": "2026-11-06T10:05:00+0000"},
    ]}}]}))
    graph.on("GET", f"{PAGE_ID}/conversations?platform=messenger", (200, {"data": [{"id": "t_1", "participants": {"data": [
        {"id": CUSTOMER_PSID, "name": "Omar"}, {"id": PAGE_ID, "name": "Alice Page"},
    ]}, "messages": {"data": [
        {"id": "m_poll_1", "message": "Hi", "from": {"id": CUSTOMER_PSID}, "created_time": "2026-11-06T10:01:00+0000"},
    ]}}]}))
    graph.on("GET", f"{IG_ID}/media", (200, {"data": []}))
    graph.on("GET", f"{PAGE_ID}/conversations?platform=instagram", (200, {"data": []}))

    backfill = case.backfill()
    # Alice's Page (+2 new), Alice's Instagram (0) and Carol's copy of the Page (+2 new);
    # Bob's Page lacks the inbox permissions and is not polled.
    assert await backfill.run_once() == 4
    assert await backfill.run_once() == 0
    assert all(not call[1].startswith("3333333") for call in graph.calls)
    alice = await _conversations(case, case.alice)
    by_thread = {item["participant_name"]: item for item in alice}
    assert by_thread["Mona"]["unread_count"] == 1 and by_thread["Hany"]["unread_count"] == 1
    assert by_thread["Omar"]["channel"] == "dm"
    # The scheduled entry point runs once (nothing new), then waits for the interval.
    calls = len(graph.calls)
    assert await backfill.run_if_due() == 0 and len(graph.calls) > calls
    calls = len(graph.calls)
    assert await backfill.run_if_due() == 0 and len(graph.calls) == calls


# --- Meta data deletion and deauthorize (App Review) -------------------------------------


@pytest.mark.asyncio
async def test_data_deletion_deletes_tokens_and_inbox_and_returns_a_status_url(inbox_case):
    case = inbox_case
    await _deliver(case, feed_payload())
    request = signed_request({"algorithm": "HMAC-SHA256", "issued_at": int(datetime.now(UTC).timestamp()), "user_id": META_USER})
    forged = await case.client.post(
        PREFIX + "/meta/data-deletion",
        data={"signed_request": signed_request({"algorithm": "HMAC-SHA256", "user_id": META_USER}, "wrong-secret")},
    )
    assert forged.status_code == 403
    response = await case.client.post(PREFIX + "/meta/data-deletion", data={"signed_request": request})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"url", "confirmation_code"}
    assert body["url"] == f"https://ai.vip-e.net/en/legal/data-deletion/?code={body['confirmation_code']}"
    async with case.sessions() as session:
        connection = await session.get(SocialConnection, case.connection_id)
        assert connection.token_ciphertext is None and connection.status == "revoked"
        assert connection.display_name == "Deleted Meta user"
        for account_id in (case.fb.id, case.ig.id):
            account = await session.get(GrowthSocialAccount, account_id)
            assert account.token_ciphertext is None and account.status == "revoked"
        carol = await session.get(GrowthSocialAccount, case.carol_fb.id)
        assert carol.token_ciphertext is not None  # another person's grant is untouched
        owners = (await session.scalars(select(SocialInboxConversation.user_id))).all()
        assert owners == [case.carol.id]
    status = await case.client.get(PREFIX + "/meta/data-deletion/status", params={"code": body["confirmation_code"]})
    assert status.status_code == 200
    assert status.json()["status"] == "completed" and status.json()["kind"] == "deletion"
    assert (status.json()["connections_revoked"], status.json()["accounts_cleared"], status.json()["conversations_deleted"]) == (1, 2, 1)
    missing = await case.client.get(PREFIX + "/meta/data-deletion/status", params={"code": "ABCDEF0123456789"})
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_deauthorize_revokes_tokens_but_keeps_inbox_history(inbox_case):
    case = inbox_case
    await _deliver(case, feed_payload())
    request = signed_request({"algorithm": "HMAC-SHA256", "issued_at": int(datetime.now(UTC).timestamp()), "user_id": META_USER})
    response = await case.client.post(PREFIX + "/meta/deauthorize", data={"signed_request": request})
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True and response.json()["confirmation_code"]
    async with case.sessions() as session:
        account = await session.get(GrowthSocialAccount, case.fb.id)
        assert account.token_ciphertext is None and account.status == "revoked"
        assert await session.scalar(select(func.count(SocialInboxConversation.id))) == 2
    # A revoked account receives nothing more.
    assert (await _deliver(case, feed_payload(comment_id=f"{PAGE_ID}_2010"))).json()["applied"] == 1
