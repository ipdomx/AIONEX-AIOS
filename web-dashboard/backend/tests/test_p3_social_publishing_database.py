"""Real PostgreSQL contract for P3 publishing: API, tenancy and the worker.

Every case runs in a private random schema of an explicitly test-named
database and drives the real ``/api/v1/social`` publishing router and the
real ``SocialPublishWorker``. Graph API traffic is answered in-process by
``httpx.MockTransport``; no provider is contacted.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit
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
from app.api.v1.endpoints import social_publishing as publishing_api
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    Organization,
    SocialConnection,
    SocialMediaUpload,
    SocialPost,
    SocialPostAttempt,
    SocialPostTarget,
    User,
)
from app.services import social_connectors as framework
from app.services.social_meta_publisher import MetaPublisher
from app.services.social_publish_worker import SocialPublishWorker
from tests.test_p3_social_publishing import APP_ID, APP_SECRET, IG_ID, PAGE_ID, PAGE_TOKEN, Graph, _jpeg

PREFIX = "/api/v1/social"


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AuditEvent, GrowthSocialAccount, Organization, SocialConnection, SocialMediaUpload,
            SocialPost, SocialPostAttempt, SocialPostTarget, User,
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


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest_asyncio.fixture
async def publishing_case(monkeypatch, tmp_path):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("social publishing contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])", (url.database or "").lower()
    ) is None:
        raise RuntimeError("social publishing tests require an isolated test database")
    schema = f"p3_publish_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "application_name": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_a, org_c = str(uuid4()), str(uuid4())
    user_a, user_b, user_c = str(uuid4()), str(uuid4()), str(uuid4())
    graph = Graph()
    case = SimpleNamespace(
        sessions=sessions,
        graph=graph,
        alice=_actor(user_a, org_a, "alice"),
        bob=_actor(user_b, org_a, "bob"),
        carol=_actor(user_c, org_c, "carol"),
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
    monkeypatch.setattr(settings, "MEDIA_STORAGE_TYPE", "local")
    monkeypatch.setattr(settings, "MEDIA_STORAGE_ROOT", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "SOCIAL_MEDIA_PUBLIC_BASE_URL", "https://api.vip-e.net")
    if len(str(settings.SECRET_KEY or "")) < 32:
        monkeypatch.setattr(settings, "SECRET_KEY", "p3-publishing-test-secret-key-0123456789")

    async def no_rate_limit(_actor, _action):
        return None

    monkeypatch.setattr(social_api, "enforce_rate_limit", no_rate_limit)

    def worker(**kwargs) -> SocialPublishWorker:
        return SocialPublishWorker(
            session_factory=sessions,
            publisher=MetaPublisher(
                transport=httpx.MockTransport(graph), sleep=_no_sleep, poll_seconds=1
            ),
            **kwargs,
        )

    case.worker = worker

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
                    id=org_id, name=f"Org {org_id[:8]}", slug=f"p3p-{org_id}",
                    plan="business", status="active",
                ))
            await session.flush()
            for actor in (case.alice, case.bob, case.carol):
                session.add(User(
                    id=actor.id, organization_id=actor.organization_id, name=actor.name,
                    email=actor.email, password_hash="unused-synthetic-hash", status="active",
                ))
            await session.flush()
            case.fb = _account(case.alice, "facebook", "page", PAGE_ID, "Alice Page")
            case.ig = _account(case.alice, "instagram", "business", IG_ID, "alice.ig")
            case.bob_fb = _account(case.bob, "facebook", "page", "3333333", "Bob Page")
            case.simulated = _account(case.alice, "facebook", "page", "4444444", "GS-03 page", oauth=False)
            for row in (case.fb, case.ig, case.bob_fb, case.simulated):
                session.add(row)
            await session.commit()

        async def request_db():
            async with sessions() as session:
                yield session

        async def actor_dependency():
            return case.current

        app = FastAPI()
        app.include_router(social_api.router, prefix=PREFIX)
        app.include_router(publishing_api.router, prefix=PREFIX)
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


def _account(actor, provider, kind, external_id, name, *, oauth=True) -> GrowthSocialAccount:
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
        provider_metadata={"connector": "meta"},
        settings={},
        version=1,
        connected_via="oauth" if oauth else None,
        token_ciphertext=framework.seal_token(PAGE_TOKEN) if oauth else None,
    )


def _post(account_ids, **extra):
    body = {"post_type": "text", "caption": "مرحبا من AIONEX", "account_ids": account_ids, "timezone": "Africa/Cairo"}
    body.update(extra)
    return body


async def _create(case, body) -> dict:
    response = await case.client.post(PREFIX + "/posts", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _upload_jpeg(case, width=1080, height=1350) -> dict:
    response = await case.client.post(
        PREFIX + "/media", files={"file": ("photo.jpg", _jpeg(width, height), "image/jpeg")}
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert (item["kind"], item["media_type"], item["width"], item["height"]) == ("image", "image/jpeg", width, height)
    return item


def _feed_ok(graph: Graph, suffix="9001") -> None:
    graph.on("POST", f"{PAGE_ID}/feed", (200, {"id": f"{PAGE_ID}_{suffix}"}))
    graph.on("GET", f"{PAGE_ID}_{suffix}", (200, {"permalink_url": f"https://www.facebook.com/p/{suffix}"}))


# --- tenancy ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_targets_are_limited_to_the_callers_own_oauth_accounts(publishing_case):
    case = publishing_case
    for account_id in (case.bob_fb.id, case.simulated.id, str(uuid4())):
        response = await case.client.post(PREFIX + "/posts", json=_post([account_id]))
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "target-account-not-found"

    post = await _create(case, _post([case.fb.id]))
    for other in (case.bob, case.carol):
        case.current = other
        assert (await case.client.get(f"{PREFIX}/posts/{post['id']}")).status_code == 404
        assert (await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")).status_code == 404
        assert (await case.client.delete(f"{PREFIX}/posts/{post['id']}")).status_code == 404
        assert (await case.client.get(PREFIX + "/posts")).json()["items"] == []

    # Media uploaded by Alice cannot be used by Bob.
    case.current = case.alice
    upload = await _upload_jpeg(case)
    case.current = case.bob
    response = await case.client.post(
        PREFIX + "/posts/validate", json=_post([case.bob_fb.id], post_type="image", media=[upload["ref"]])
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "media-not-found"
    assert "ciphertext" not in response.text and PAGE_TOKEN not in response.text


# --- validation, scheduling, calendar --------------------------------------------------


@pytest.mark.asyncio
async def test_validation_reports_per_target_issues_and_blocks_publishing(publishing_case):
    case = publishing_case
    report = (await case.client.post(PREFIX + "/posts/validate", json=_post([case.fb.id, case.ig.id]))).json()
    by_provider = {item["provider"]: item for item in report["targets"]}
    assert report["valid"] is False
    assert by_provider["facebook"]["issues"] == []
    assert by_provider["instagram"]["issues"][0]["code"] == "instagram-requires-media"
    assert report["rules"]["instagram"]["caption_max"] == 2200

    post = await _create(case, _post([case.fb.id, case.ig.id]))
    response = await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "post-validation-failed"
    assert (await case.client.get(f"{PREFIX}/posts/{post['id']}")).json()["status"] == "draft"


@pytest.mark.asyncio
async def test_schedule_calendar_range_cancel_and_worker_waits_for_due_time(publishing_case):
    case = publishing_case
    post = await _create(case, _post([case.fb.id]))
    past = await case.client.post(
        f"{PREFIX}/posts/{post['id']}/schedule",
        json={"scheduled_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()},
    )
    assert past.status_code == 422 and past.json()["detail"]["code"] == "scheduled-at-in-past"
    when = datetime.now(UTC) + timedelta(hours=2)
    scheduled = await case.client.post(
        f"{PREFIX}/posts/{post['id']}/schedule",
        json={"scheduled_at": when.isoformat(), "timezone": "Asia/Dubai"},
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["status"] == "scheduled" and scheduled.json()["timezone"] == "Asia/Dubai"

    start, end = (when - timedelta(days=1)).isoformat(), (when + timedelta(days=1)).isoformat()
    listed = await case.client.get(PREFIX + "/posts", params={"start": start, "end": end})
    assert [item["id"] for item in listed.json()["items"]] == [post["id"]]
    too_wide = await case.client.get(
        PREFIX + "/posts", params={"start": start, "end": (when + timedelta(days=200)).isoformat()}
    )
    assert too_wide.status_code == 422

    # Not due yet: nothing is claimed and Graph is never called.
    assert await case.worker().run_once() == 0
    assert case.graph.calls == []

    canceled = await case.client.post(f"{PREFIX}/posts/{post['id']}/cancel")
    assert canceled.json()["status"] == "canceled"
    assert canceled.json()["targets"][0]["status"] == "canceled"
    later = case.worker(clock=lambda: datetime.now(UTC) + timedelta(hours=3))
    assert await later.run_once() == 0
    assert case.graph.calls == []
    assert (await case.client.delete(f"{PREFIX}/posts/{post['id']}")).json()["deleted"] is True


# --- worker: publishing, partial failure, token expiry ----------------------------------


@pytest.mark.asyncio
async def test_one_click_publish_to_page_and_instagram_with_partial_failure(publishing_case):
    case = publishing_case
    upload = await _upload_jpeg(case)
    case.graph.on("POST", f"{PAGE_ID}/photos", (200, {"id": "700", "post_id": f"{PAGE_ID}_701"}))
    case.graph.on("GET", f"{PAGE_ID}_701", (200, {"permalink_url": "https://www.facebook.com/p/701"}))
    case.graph.on(
        "POST", f"{IG_ID}/media",
        (400, {"error": {"code": 9004, "error_subcode": 2207052, "message": "Media download failed"}}),
    )
    post = await _create(
        case,
        _post(
            [case.fb.id, case.ig.id],
            post_type="image",
            media=[upload["ref"]],
            overrides={case.ig.id: {"caption": "نسخة إنستجرام #aionex"}},
        ),
    )
    queued = await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")
    assert queued.status_code == 202 and queued.json()["status"] == "publishing"
    assert all(item["status"] == "pending" for item in queued.json()["targets"])

    assert await case.worker().run_once() == 2
    result = (await case.client.get(f"{PREFIX}/posts/{post['id']}")).json()
    assert result["status"] == "partially_failed"
    targets = {item["provider"]: item for item in result["targets"]}
    assert targets["facebook"]["status"] == "published"
    assert targets["facebook"]["remote_post_id"] == f"{PAGE_ID}_701"
    assert targets["facebook"]["permalink"] == "https://www.facebook.com/p/701"
    assert targets["instagram"]["status"] == "failed"
    assert targets["instagram"]["error_code"] == "meta-ig-image-container-error-9004-2207052"
    assert targets["instagram"]["remote_post_id"] is None
    assert [a["outcome"] for a in targets["instagram"]["attempt_log"]] == ["failed"]

    # The per-target override reached Instagram, the main caption reached the Page,
    # and Meta fetched the media through the signed bridge.
    bodies = {path: body for _method, path, _params, body in case.graph.calls}
    assert bodies[f"{IG_ID}/media"]["caption"] == "نسخة إنستجرام #aionex"
    assert bodies[f"{PAGE_ID}/photos"]["caption"] == "مرحبا من AIONEX"
    bridge = urlsplit(bodies[f"{IG_ID}/media"]["image_url"])
    assert bridge.scheme == "https" and bridge.netloc == "api.vip-e.net"
    fetched = await case.client.get(bridge.path)
    assert fetched.status_code == 200 and fetched.content == _jpeg(1080, 1350)
    assert fetched.headers["content-type"].startswith("image/jpeg")
    tampered = bridge.path.replace("/public/", "/public/x")
    assert (await case.client.get(tampered)).status_code == 404

    async with case.sessions() as session:
        actions = set((await session.scalars(select(AuditEvent.action))).all())
    assert {"social.post.created", "social.post.publish_requested", "social.post.target_published", "social.post.target_failed"} <= actions


@pytest.mark.asyncio
async def test_expired_token_marks_account_for_reconnect_without_retry(publishing_case):
    case = publishing_case
    case.graph.on(
        "POST", f"{PAGE_ID}/feed",
        (400, {"error": {"code": 190, "error_subcode": 463, "message": "Session has expired"}}),
    )
    post = await _create(case, _post([case.fb.id]))
    await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")
    await case.worker().run_once()
    result = (await case.client.get(f"{PREFIX}/posts/{post['id']}")).json()
    assert result["status"] == "failed"
    assert result["targets"][0]["error_code"] == "account-reconnect-required"
    async with case.sessions() as session:
        account = await session.get(GrowthSocialAccount, case.fb.id)
    assert account.status == "expired" and account.health_state == "expired"
    assert "token-expired-reconnect-required" in account.health_reasons
    later = case.worker(clock=lambda: datetime.now(UTC) + timedelta(hours=2))
    assert await later.run_once() == 0
    assert len(case.graph.calls) == 1
    # A new post cannot target the account until it is reconnected.
    blocked = await case.client.post(PREFIX + "/posts", json=_post([case.fb.id]))
    assert blocked.status_code == 201
    assert (await case.client.post(f"{PREFIX}/posts/{blocked.json()['id']}/publish")).status_code == 202
    await later.run_once()
    again = (await case.client.get(f"{PREFIX}/posts/{blocked.json()['id']}")).json()
    assert again["targets"][0]["error_code"] == "account-reconnect-required"
    assert len(case.graph.calls) == 1  # no Graph call for an expired account


@pytest.mark.asyncio
async def test_transient_errors_retry_with_backoff_then_succeed(publishing_case):
    case = publishing_case
    case.graph.on(
        "POST", f"{PAGE_ID}/feed",
        (400, {"error": {"code": 32, "message": "Page request limit reached"}}),
        (200, {"id": f"{PAGE_ID}_42"}),
    )
    case.graph.on("GET", f"{PAGE_ID}_42", (200, {"permalink_url": "https://www.facebook.com/p/42"}))
    post = await _create(case, _post([case.fb.id], retry_policy={"max_attempts": 3, "backoff_seconds": 60}))
    await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")
    started = datetime.now(UTC)
    await case.worker().run_once()
    target = (await case.client.get(f"{PREFIX}/posts/{post['id']}")).json()["targets"][0]
    assert target["status"] == "retry_wait" and target["attempts"] == 1
    next_at = datetime.fromisoformat(target["next_attempt_at"])
    assert timedelta(seconds=55) <= next_at - started <= timedelta(seconds=90)

    # Before the backoff elapses nothing is claimed.
    assert await case.worker().run_once() == 0
    later = case.worker(clock=lambda: datetime.now(UTC) + timedelta(seconds=120))
    assert await later.run_once() == 1
    result = (await case.client.get(f"{PREFIX}/posts/{post['id']}")).json()
    assert result["status"] == "published"
    assert result["targets"][0]["remote_post_id"] == f"{PAGE_ID}_42"
    assert [a["outcome"] for a in result["targets"][0]["attempt_log"]] == ["retry_scheduled", "published"]


@pytest.mark.asyncio
async def test_permanent_error_and_exhausted_retries_fail_without_more_calls(publishing_case):
    case = publishing_case
    case.graph.on("POST", f"{PAGE_ID}/feed", (400, {"error": {"code": 2, "message": "Service unavailable"}}))
    post = await _create(case, _post([case.fb.id], retry_policy={"max_attempts": 2, "backoff_seconds": 30}))
    await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")
    await case.worker().run_once()
    await case.worker(clock=lambda: datetime.now(UTC) + timedelta(minutes=5)).run_once()
    result = (await case.client.get(f"{PREFIX}/posts/{post['id']}")).json()
    assert result["status"] == "failed" and result["targets"][0]["attempts"] == 2
    assert len(case.graph.calls) == 2
    await case.worker(clock=lambda: datetime.now(UTC) + timedelta(hours=5)).run_once()
    assert len(case.graph.calls) == 2


# --- worker: lease and idempotency --------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_workers_claim_a_target_once(publishing_case):
    case = publishing_case
    post = await _create(case, _post([case.fb.id]))
    await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")
    first, second = case.worker(), case.worker()
    claims = await asyncio.gather(first.claim_due(), second.claim_due())
    assert sorted(len(item) for item in claims) == [0, 1]
    # A leased target is not claimable again while the lease is live.
    assert await case.worker().claim_due() == []
    async with case.sessions() as session:
        target = await session.scalar(select(SocialPostTarget).where(SocialPostTarget.post_id == post["id"]))
        assert target.status == "publishing" and target.lease_owner in {first.worker_id, second.worker_id}
        assert target.idempotency_key and len(target.idempotency_key) == 64


@pytest.mark.asyncio
async def test_expired_lease_before_dispatch_is_retried_but_after_dispatch_never_replayed(publishing_case):
    case = publishing_case
    _feed_ok(case.graph)
    # 1) The worker died before the publish call: safe to retry.
    post = await _create(case, _post([case.fb.id]))
    await case.client.post(f"{PREFIX}/posts/{post['id']}/publish")
    crashed = case.worker(lease_seconds=120)
    [claim] = await crashed.claim_due()
    rescuer = case.worker(clock=lambda: datetime.now(UTC) + timedelta(seconds=200))
    assert await rescuer.run_once() == 1
    result = (await case.client.get(f"{PREFIX}/posts/{post['id']}")).json()
    assert result["status"] == "published"
    assert [a["outcome"] for a in result["targets"][0]["attempt_log"]] == ["abandoned", "published"]
    # The original worker's late result is rejected: it no longer holds the lease.
    assert await crashed.finalize(claim, None, None) == "lease-lost"
    assert len([c for c in case.graph.calls if c[1] == f"{PAGE_ID}/feed"]) == 1

    # 2) The worker died after recording dispatch: never published twice.
    other = await _create(case, _post([case.fb.id], caption="second"))
    await case.client.post(f"{PREFIX}/posts/{other['id']}/publish")
    crashed = case.worker(lease_seconds=120)
    [claim] = await crashed.claim_due()
    await crashed.mark_dispatch_started(claim)
    feed_calls = len([c for c in case.graph.calls if c[1] == f"{PAGE_ID}/feed"])
    rescuer = case.worker(clock=lambda: datetime.now(UTC) + timedelta(seconds=200))
    assert await rescuer.run_once() == 0
    target = (await case.client.get(f"{PREFIX}/posts/{other['id']}")).json()["targets"][0]
    assert target["status"] == "failed" and target["error_code"] == "publish-outcome-unknown"
    assert [a["outcome"] for a in target["attempt_log"]] == ["unknown"]
    assert len([c for c in case.graph.calls if c[1] == f"{PAGE_ID}/feed"]) == feed_calls
    assert await case.worker(clock=lambda: datetime.now(UTC) + timedelta(days=1)).run_once() == 0


@pytest.mark.asyncio
async def test_create_is_idempotent_per_client_key_and_publish_queues_once(publishing_case):
    case = publishing_case
    _feed_ok(case.graph, "77")
    body = _post([case.fb.id], client_idempotency_key="composer-key-0001")
    first = await _create(case, body)
    second = await _create(case, body)
    assert first["id"] == second["id"]
    await case.client.post(f"{PREFIX}/posts/{first['id']}/publish")
    # A second "publish now" on a post that is already publishing is refused.
    again = await case.client.post(f"{PREFIX}/posts/{first['id']}/publish")
    assert again.status_code == 409
    await case.worker().run_once()
    await case.worker().run_once()
    assert len([c for c in case.graph.calls if c[1] == f"{PAGE_ID}/feed"]) == 1
    async with case.sessions() as session:
        count = len((await session.scalars(select(SocialPost.id).where(SocialPost.user_id == case.alice.id))).all())
    assert count == 1
