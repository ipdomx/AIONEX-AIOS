"""Real PostgreSQL contract for P4 Meta Ads: API, tenancy, worker and spend guard.

Every case runs in a private random schema of an explicitly test-named
database and drives the real ``/api/v1/ads`` router, the real insights job and
the real spend guard. Marketing API traffic is answered in-process by
``httpx.MockTransport``; no provider is contacted and no money is spent.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs
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

from app.api.v1.endpoints import ads as ads_api
from app.api.v1.endpoints import social as social_api
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AdAccountLink,
    AdCampaign,
    AdInsightDaily,
    AdInsightSyncRun,
    AdRecommendationRun,
    AuditEvent,
    GrowthSocialAccount,
    Organization,
    OwnerControlRecord,
    SocialConnection,
    SocialMediaUpload,
    SocialOAuthState,
    SocialPost,
    SocialPostTarget,
    User,
)
from app.services import ads_entitlement as entitlement
from app.services import social_connectors as framework
from app.services.ads_insights import InsightsJob
from app.services.ads_meta_graph import MetaAdsGraph

PREFIX = "/api/v1/ads"
APP_ID = "1234567890123"
APP_SECRET = "p4-ads-db-test-secret"
USER_TOKEN = "EAAuser-ads-db-token"
ACCOUNT = "4455667788"
PAGE_ID = "1111111"
CAMPAIGN, ADSET, CREATIVE, AD = "120000000000001", "120000000000002", "120000000000003", "120000000000004"
REPORT = "6123456789"


class AdsGraph:
    """Marketing API stand-in that answers by path, level and breakdown."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], dict[str, str]]] = []
        self.spend = "10.00"
        self.headers: dict[str, str] = {}
        self.report_states: list[str] = ["Job Completed"]
        self.fail_status = False

    def _rows(self, level: str, breakdowns: str | None) -> list[dict]:
        today = datetime.now(UTC).date().isoformat()
        base = {
            "campaign_id": CAMPAIGN,
            "campaign_name": "Spring sale",
            "adset_id": ADSET,
            "adset_name": "Spring ad set",
            "ad_id": AD,
            "ad_name": "Spring ad",
            "date_start": today,
            "date_stop": today,
            "spend": self.spend,
            "impressions": "2000",
            "reach": "1500",
            "clicks": "60",
            "inline_link_clicks": "50",
            "actions": [{"action_type": "purchase", "value": "2"}],
            "action_values": [{"action_type": "purchase", "value": "80"}],
        }
        if breakdowns == "age":
            return [{**base, "age": "25-34", "spend": "6.00"}, {**base, "age": "18-24", "spend": "4.00"}]
        return [base]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/v26.0/")
        assert request.headers["Authorization"] == f"Bearer {USER_TOKEN}"
        assert USER_TOKEN not in str(request.url)
        path = request.url.path.removeprefix("/v26.0/")
        params = dict(request.url.params)
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
        self.calls.append((request.method, path, params, body))
        method = request.method
        if path == "me/adaccounts":
            return httpx.Response(200, json={"data": [
                {"id": f"act_{ACCOUNT}", "account_id": ACCOUNT, "name": "Alice Ads", "currency": "USD",
                 "timezone_name": "UTC", "account_status": 1},
            ]})
        if path == f"act_{ACCOUNT}/insights" and method == "GET":
            rows = self._rows(params["level"], params.get("breakdowns"))
            return httpx.Response(200, json={"data": rows}, headers=self.headers)
        if path == f"act_{ACCOUNT}/insights" and method == "POST":
            return httpx.Response(200, json={"report_run_id": REPORT})
        if path == REPORT:
            state = self.report_states.pop(0) if len(self.report_states) > 1 else self.report_states[0]
            return httpx.Response(200, json={"async_status": state, "async_percent_completion": 50})
        if path == f"{REPORT}/insights":
            started = next(call for call in reversed(self.calls) if call[0] == "POST" and call[1].endswith("/insights"))
            return httpx.Response(200, json={"data": self._rows(started[3]["level"], started[3].get("breakdowns"))})
        created = {"campaigns": CAMPAIGN, "adsets": ADSET, "adcreatives": CREATIVE, "ads": AD}
        for suffix, object_id in created.items():
            if path == f"act_{ACCOUNT}/{suffix}" and method == "POST":
                return httpx.Response(200, json={"id": object_id})
        if method == "POST" and path in {CAMPAIGN, ADSET, AD}:
            if self.fail_status:
                return httpx.Response(500, json={"error": {"code": 2, "is_transient": True}})
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"error": {"code": 803}})

    def statuses(self) -> list[tuple[str, str]]:
        return [(path, body["status"]) for method, path, _p, body in self.calls if method == "POST" and path in {CAMPAIGN, ADSET, AD}]


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AdAccountLink, AdCampaign, AdInsightDaily, AdInsightSyncRun, AdRecommendationRun,
            AuditEvent, GrowthSocialAccount, Organization, OwnerControlRecord, SocialConnection,
            SocialMediaUpload, SocialOAuthState, SocialPost, SocialPostTarget, User,
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
async def ads_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("ads contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])", (url.database or "").lower()
    ) is None:
        raise RuntimeError("ads tests require an isolated test database")
    schema = f"p4_ads_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "application_name": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_a, org_c = str(uuid4()), str(uuid4())
    user_a, user_b, user_c = str(uuid4()), str(uuid4()), str(uuid4())
    graph = AdsGraph()
    case = SimpleNamespace(
        sessions=sessions,
        graph=graph,
        alice=_actor(user_a, org_a, "alice"),
        bob=_actor(user_b, org_a, "bob"),
        carol=_actor(user_c, org_c, "carol"),
        entitled=True,
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
    monkeypatch.setattr(settings, "ADS_INSIGHTS_INITIAL_BACKFILL_DAYS", 3)
    monkeypatch.setattr(settings, "ADS_INSIGHTS_ASYNC_MIN_DAYS", 14)
    monkeypatch.setattr(settings, "ADS_INSIGHTS_BREAKDOWNS", "age")
    if len(str(settings.SECRET_KEY or "")) < 32:
        monkeypatch.setattr(settings, "SECRET_KEY", "p4-ads-test-secret-key-0123456789abcdef")

    async def no_rate_limit(_actor, _action):
        return None

    async def plan_gate(session, actor, *, policy=None):
        resolved = policy or await entitlement.get_policy(session)
        if case.entitled:
            return entitlement.AdsAccess("subscriber", "subscription", "entitled", "pro", policy=resolved)
        return entitlement.AdsAccess(None, None, "not-entitled", "basic", policy=resolved)

    monkeypatch.setattr(social_api, "enforce_rate_limit", no_rate_limit)
    # Billing is covered by its own suites; here the plan gate is driven per case.
    monkeypatch.setattr(entitlement, "resolve_access", plan_gate)

    def ads_graph() -> MetaAdsGraph:
        return MetaAdsGraph(transport=httpx.MockTransport(graph), sleep=_no_sleep)

    case.ads_graph = ads_graph
    case.job = lambda **kwargs: InsightsJob(
        session_factory=sessions, graph=ads_graph(), report_poll_attempts=1, report_poll_interval=0, **kwargs
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
                    id=org_id, name=f"Org {org_id[:8]}", slug=f"p4a-{org_id}", plan="business", status="active",
                ))
            await session.flush()
            for actor in (case.alice, case.bob, case.carol):
                session.add(User(
                    id=actor.id, organization_id=actor.organization_id, name=actor.name,
                    email=actor.email, password_hash="unused-synthetic-hash", status="active",
                ))
            await session.flush()
            case.connection = SocialConnection(
                id=str(uuid4()), organization_id=org_a, user_id=user_a, provider="meta",
                external_user_id="900000001", display_name="Alice Meta",
                requested_scopes=["ads_read", "ads_management"],
                granted_scopes=["ads_read", "ads_management", "pages_show_list"],
                token_ciphertext=framework.seal_token(USER_TOKEN), status="active",
                health_state="healthy", health_reasons=[], version=1,
            )
            session.add(case.connection)
            await session.flush()
            case.page = GrowthSocialAccount(
                id=str(uuid4()), organization_id=org_a, created_by_id=user_a, provider="facebook",
                account_kind="page", external_account_id=PAGE_ID, display_name="Alice Page",
                status="active", health_state="healthy", health_reasons=[],
                provider_metadata={"connector": "meta"}, settings={}, version=1,
                connected_via="oauth", connection_id=case.connection.id,
                token_ciphertext=framework.seal_token("EAApage"),
            )
            session.add(case.page)
            post = SocialPost(
                id=str(uuid4()), organization_id=org_a, user_id=user_a, status="published",
                post_type="text", caption="Spring", media=[], timezone="UTC", retry_policy={}, version=1,
            )
            session.add(post)
            await session.flush()
            case.target = SocialPostTarget(
                id=str(uuid4()), post_id=post.id, organization_id=org_a, user_id=user_a,
                account_id=case.page.id, provider="facebook", account_name="Alice Page", overrides={},
                status="published", idempotency_key=uuid4().hex, remote_post_id=f"{PAGE_ID}_9001",
                version=1,
            )
            session.add(case.target)
            session.add(OwnerControlRecord(
                domain=entitlement.POLICY_DOMAIN, resource_id=entitlement.POLICY_RESOURCE,
                status="active", enabled=True,
                payload={"daily_cap_minor": 3000, "lifetime_cap_minor": 10000},
                version=1,
            ))
            await session.commit()

        async def request_db():
            async with sessions() as session:
                yield session

        async def actor_dependency():
            return case.current

        app = FastAPI()
        app.include_router(ads_api.router, prefix=PREFIX)
        app.dependency_overrides[get_db] = request_db
        app.dependency_overrides[current_user] = actor_dependency
        app.dependency_overrides[ads_api.get_ads_graph] = ads_graph
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated.test") as client:
            case.client = client
            yield case
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


async def _link(case) -> dict:
    response = await case.client.post(
        PREFIX + "/accounts",
        json={"source": "oauth", "connection_id": case.connection.id, "ad_account_ids": [ACCOUNT]},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def _campaign_body(link_id: str, **extra) -> dict:
    body = {
        "link_id": link_id,
        "name": "Spring traffic",
        "objective": "traffic",
        "daily_budget_minor": 2000,
        "targeting": {"countries": ["ae", "SA"], "age_min": 21, "age_max": 45, "publisher_platforms": ["facebook"]},
        "creative": {"source": "post", "post_target_id": None},
        "client_idempotency_key": "spring-1",
    }
    body.update(extra)
    return body


async def _count(case, model, *conditions) -> int:
    async with case.sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


# --- 4.1 connect, tenancy and entitlement --------------------------------------------


@pytest.mark.asyncio
async def test_ad_account_connect_is_per_user_and_tenant(ads_case):
    case = ads_case
    access = (await case.client.get(PREFIX + "/access")).json()
    assert access["allowed"] is True and access["daily_cap_minor"] == 3000
    assert access["activation_phrase"] == "ACTIVATE AD SPEND" and access["live_verified"] is False
    connections = (await case.client.get(PREFIX + "/connections")).json()["items"]
    assert connections[0]["can_manage"] is True and connections[0]["ads_scopes_missing"] == ["business_management"]
    available = await case.client.get(PREFIX + "/accounts/available", params={"connection_id": case.connection.id})
    assert available.status_code == 200, available.text
    assert available.json()["items"][0]["ad_account_id"] == ACCOUNT
    assert USER_TOKEN not in available.text and "ciphertext" not in available.text
    link = await _link(case)
    assert (link["currency"], link["source"], link["sync_state"]) == ("USD", "oauth", "pending")
    assert [item["id"] for item in (await case.client.get(PREFIX + "/accounts")).json()["items"]] == [link["id"]]

    # Not available for an account the grant cannot reach.
    response = await case.client.post(
        PREFIX + "/accounts", json={"connection_id": case.connection.id, "ad_account_ids": ["999"]}
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "ad-account-not-available"
    # The owner-token fallback is owner-only.
    response = await case.client.get(PREFIX + "/accounts/available", params={"source": "owner_token"})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "ads-owner-token-not-allowed"

    for other in (case.bob, case.carol):
        case.current = other
        assert (await case.client.get(PREFIX + "/accounts")).json()["items"] == []
        assert (await case.client.get(PREFIX + "/connections")).json()["items"] == []
        response = await case.client.get(PREFIX + "/accounts/available", params={"connection_id": case.connection.id})
        assert response.status_code == 404
        assert (await case.client.get(PREFIX + "/analytics", params={"link_id": link["id"]})).status_code == 404
        assert (await case.client.delete(f"{PREFIX}/accounts/{link['id']}")).status_code == 404
    audits = await _count(case, AuditEvent, AuditEvent.action == "ads.account.linked")
    assert audits == 1


@pytest.mark.asyncio
async def test_every_ads_route_is_gated_by_the_plan_entitlement(ads_case):
    case = ads_case
    link = await _link(case)
    case.entitled = False
    access = (await case.client.get(PREFIX + "/access")).json()
    assert access["allowed"] is False and access["reason"] == "not-entitled"
    for method, path, kwargs in (
        ("GET", "/connections", {}),
        ("GET", "/accounts", {}),
        ("GET", "/accounts/available", {"params": {"connection_id": case.connection.id}}),
        ("GET", "/analytics", {"params": {"link_id": link["id"]}}),
        ("GET", "/campaigns", {}),
        ("POST", "/campaigns", {"json": _campaign_body(link["id"])}),
        ("POST", "/recommendations", {"json": {"link_id": link["id"]}}),
        ("POST", f"/accounts/{link['id']}/sync", {}),
        ("POST", "/connect/meta/start", {"json": {"locale": "ar"}}),
    ):
        response = await case.client.request(method, PREFIX + path, **kwargs)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"]["code"] == entitlement.PLAN_REQUIRED, path


# --- 4.2 insights ingestion ----------------------------------------------------------


@pytest.mark.asyncio
async def test_insights_job_is_incremental_idempotent_and_throttle_aware(ads_case):
    case = ads_case
    link = await _link(case)
    job = case.job()
    assert await job.run_once() == 1
    async with case.sessions() as session:
        row = await session.get(AdAccountLink, link["id"])
        assert row.sync_state == "ok" and row.insights_synced_through == datetime.now(UTC).date()
        assert row.lease_owner is None and row.next_sync_at > datetime.now(UTC)
    by_level = {
        level: await _count(case, AdInsightDaily, AdInsightDaily.level == level, AdInsightDaily.breakdown == "none")
        for level in ("campaign", "adset", "ad")
    }
    assert by_level == {"campaign": 1, "adset": 1, "ad": 1}
    assert await _count(case, AdInsightDaily, AdInsightDaily.breakdown == "age") == 2
    total = await _count(case, AdInsightDaily)

    # Re-run with new numbers: same rows, updated values (upsert on the natural key).
    case.graph.spend = "12.00"
    async with case.sessions() as session:
        row = await session.get(AdAccountLink, link["id"])
        row.next_sync_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert await job.run_once() == 1
    assert await _count(case, AdInsightDaily) == total
    async with case.sessions() as session:
        spend = await session.scalar(
            select(AdInsightDaily.spend).where(AdInsightDaily.level == "campaign", AdInsightDaily.breakdown == "none")
        )
    assert spend == 12.0

    analytics = (await case.client.get(PREFIX + "/analytics", params={"link_id": link["id"]})).json()
    assert analytics["kpis"]["spend"]["value"] == 12.0 and analytics["kpis"]["conversions"]["value"] == 2.0
    assert analytics["kpis"]["roas"]["value"] == round(80 / 12, 4)
    assert analytics["breakdowns"]["age"][0]["value"] == "25-34" and analytics["simulated"] is False
    assert analytics["campaigns"]["top"][0]["campaign_id"] == CAMPAIGN

    # Meta reports 95% utilization: the run stores the first job, then backs off.
    case.graph.headers = {"x-ad-account-usage": json.dumps({"acc_id_util_pct": 95, "reset_time_duration": 600})}
    async with case.sessions() as session:
        row = await session.get(AdAccountLink, link["id"])
        row.next_sync_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    calls_before = len(case.graph.calls)
    assert await job.run_once() == 1
    assert len(case.graph.calls) == calls_before + 1
    async with case.sessions() as session:
        row = await session.get(AdAccountLink, link["id"])
        assert row.sync_state == "throttled" and row.throttle_until > datetime.now(UTC) + timedelta(seconds=500)
        last = await session.scalar(
            select(AdInsightSyncRun).order_by(AdInsightSyncRun.started_at.desc()).limit(1)
        )
        assert last.status == "throttled" and last.throttle["usage_pct"] == 95
    # Throttled links are not picked up, and a manual sync is refused until the reset.
    row_due = await case.client.post(f"{PREFIX}/accounts/{link['id']}/sync")
    assert row_due.status_code == 429
    assert await job.run_once() == 0


@pytest.mark.asyncio
async def test_large_ranges_use_a_resumable_async_report_run(ads_case, monkeypatch):
    case = ads_case
    monkeypatch.setattr(settings, "ADS_INSIGHTS_ASYNC_MIN_DAYS", 1)
    monkeypatch.setattr(settings, "ADS_INSIGHTS_BREAKDOWNS", "")
    link = await _link(case)
    case.graph.report_states = ["Job Running"]
    job = case.job()
    assert await job.run_once() == 1
    async with case.sessions() as session:
        run = await session.scalar(select(AdInsightSyncRun).limit(1))
        assert run.status == "pending" and run.report_run_ids == {"campaign:none": REPORT}
        row = await session.get(AdAccountLink, link["id"])
        assert row.sync_state == "report_pending" and row.insights_synced_through is None
        row.next_sync_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    posts = sum(1 for call in case.graph.calls if call[0] == "POST")
    case.graph.report_states = ["Job Completed"]
    assert await job.run_once() == 1
    async with case.sessions() as session:
        run = await session.scalar(select(AdInsightSyncRun).where(AdInsightSyncRun.id == run.id))
        assert run.status == "succeeded"
    # The campaign-level report was resumed, not started again.
    reports = [call for call in case.graph.calls if call[0] == "POST"]
    assert len(reports) == posts + 2  # adset and ad reports only
    assert await _count(case, AdInsightDaily) == 3


# --- 4.5 campaigns and spend guards ---------------------------------------------------


@pytest.mark.asyncio
async def test_campaigns_start_paused_activate_with_confirmation_and_auto_pause(ads_case):
    case = ads_case
    link = await _link(case)
    creative = {"source": "post", "post_target_id": case.target.id}

    over = await case.client.post(PREFIX + "/campaigns", json=_campaign_body(link["id"], daily_budget_minor=5000, creative=creative))
    assert over.status_code == 422 and over.json()["detail"]["code"] == "ads-daily-cap-exceeded"
    assert not [call for call in case.graph.calls if call[1].startswith(f"act_{ACCOUNT}/campaigns")]

    response = await case.client.post(PREFIX + "/campaigns", json=_campaign_body(link["id"], creative=creative))
    assert response.status_code == 200, response.text
    campaign = response.json()
    assert campaign["status"] == "paused" and campaign["provisioned"] is True
    assert campaign["meta_campaign_id"] == CAMPAIGN and campaign["live_verified"] is False
    creates = {path: body for method, path, _p, body in case.graph.calls if method == "POST" and path.startswith("act_")}
    assert creates[f"act_{ACCOUNT}/campaigns"]["status"] == "PAUSED"
    assert creates[f"act_{ACCOUNT}/adsets"]["status"] == "PAUSED"
    assert creates[f"act_{ACCOUNT}/adsets"]["daily_budget"] == "2000"
    assert json.loads(creates[f"act_{ACCOUNT}/adsets"]["targeting"])["geo_locations"] == {"countries": ["AE", "SA"]}
    assert creates[f"act_{ACCOUNT}/adcreatives"]["object_story_id"] == f"{PAGE_ID}_9001"
    assert creates[f"act_{ACCOUNT}/ads"]["status"] == "PAUSED"
    assert case.graph.statuses() == []

    # Same idempotency key: the same campaign, no new Graph objects.
    calls = len(case.graph.calls)
    again = await case.client.post(PREFIX + "/campaigns", json=_campaign_body(link["id"], creative=creative))
    assert again.json()["id"] == campaign["id"] and len(case.graph.calls) == calls

    activate = f"{PREFIX}/campaigns/{campaign['id']}/activate"
    for body, code in (
        ({"confirmation": "activate", "confirmed_budget_minor": 2000}, "activation-confirmation-mismatch"),
        ({"confirmation": "ACTIVATE AD SPEND", "confirmed_budget_minor": 1999}, "activation-confirmation-mismatch"),
    ):
        refused = await case.client.post(activate, json=body)
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == code
    assert case.graph.statuses() == []

    for other in (case.bob, case.carol):
        case.current = other
        assert (await case.client.post(activate, json={"confirmation": "ACTIVATE AD SPEND", "confirmed_budget_minor": 2000})).status_code in {403, 404}
        assert (await case.client.get(PREFIX + "/campaigns")).json()["items"] == []
    case.current = case.alice

    live = await case.client.post(activate, json={"confirmation": "ACTIVATE AD SPEND", "confirmed_budget_minor": 2000})
    assert live.status_code == 200, live.text
    assert live.json()["status"] == "active"
    assert case.graph.statuses() == [(AD, "ACTIVE"), (ADSET, "ACTIVE"), (CAMPAIGN, "ACTIVE")]

    # Meta reports 35.00 spent today: over the 30.00 daily cap, the worker pauses it.
    case.graph.spend = "35.00"
    assert await case.job().run_once() == 1
    async with case.sessions() as session:
        row = await session.get(AdCampaign, campaign["id"])
        assert row.status == "auto_paused" and row.pause_reason == "ads-daily-cap-reached"
        assert row.spend_today == 35.0
    assert case.graph.statuses()[-1] == (CAMPAIGN, "PAUSED")
    assert await _count(case, AuditEvent, AuditEvent.action == "ads.guard.auto_paused") == 1

    again = await case.client.post(activate, json={"confirmation": "ACTIVATE AD SPEND", "confirmed_budget_minor": 2000})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "ads-daily-cap-reached"
    assert again.json()["detail"]["evidence"]["spend_today_minor"] == 3500
    for action in (
        "ads.campaign.created", "ads.campaign.provisioned_paused", "ads.campaign.activation_refused",
        "ads.campaign.activated",
    ):
        assert await _count(case, AuditEvent, AuditEvent.action == action) >= 1, action


@pytest.mark.asyncio
async def test_a_failed_auto_pause_is_audited_and_retried(ads_case):
    case = ads_case
    link = await _link(case)
    creative = {"source": "post", "post_target_id": case.target.id}
    campaign = (await case.client.post(PREFIX + "/campaigns", json=_campaign_body(link["id"], creative=creative))).json()
    response = await case.client.post(
        f"{PREFIX}/campaigns/{campaign['id']}/activate",
        json={"confirmation": "ACTIVATE AD SPEND", "confirmed_budget_minor": 2000},
    )
    assert response.status_code == 200, response.text
    case.graph.spend = "99.00"
    case.graph.fail_status = True
    assert await case.job().run_once() == 1
    async with case.sessions() as session:
        row = await session.get(AdCampaign, campaign["id"])
        assert row.status == "active" and row.error_code
        link_row = await session.get(AdAccountLink, link["id"])
        assert link_row.next_sync_at <= datetime.now(UTC) + timedelta(minutes=2)
    assert await _count(case, AuditEvent, AuditEvent.action == "ads.guard.pause_failed") == 1
    case.graph.fail_status = False
    async with case.sessions() as session:
        link_row = await session.get(AdAccountLink, link["id"])
        link_row.next_sync_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert await case.job().run_once() == 1
    async with case.sessions() as session:
        assert (await session.get(AdCampaign, campaign["id"])).status == "auto_paused"
