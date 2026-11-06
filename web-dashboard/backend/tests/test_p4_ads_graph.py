"""P4 Marketing API client, incremental scopes, Owner policy and AI grounding units.

No provider is contacted: every Graph call is answered by ``httpx.MockTransport``
and the AI provider is a stub. Live verification waits for the full web launch
(owner decision 2026-11-06).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import defaultdict
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services import ads_ai_recommendations as recommendations
from app.services import ads_entitlement as entitlement
from app.services import social_connections as connections
from app.services.ads_accounts import AdsError
from app.services.ads_meta_graph import AdsAuth, AdsGraphError, MetaAdsGraph
from app.services.social_meta_provider import MetaConnector, ads_scopes

APP_ID = "1234567890123"
APP_SECRET = "p4-ads-test-app-secret"
USER_TOKEN = "EAAuser-ads-token"
ACCOUNT = "4455667788"


@pytest.fixture(autouse=True)
def meta_settings(monkeypatch):
    monkeypatch.setattr(settings, "META_APP_ID", APP_ID)
    monkeypatch.setattr(settings, "META_APP_ID_FILE", "")
    monkeypatch.setattr(settings, "META_APP_SECRET", APP_SECRET)
    monkeypatch.setattr(settings, "META_APP_SECRET_FILE", "")
    monkeypatch.setattr(settings, "META_GRAPH_API_VERSION", "v26.0")
    monkeypatch.setattr(
        settings, "META_OAUTH_REDIRECT_URI", "https://api.vip-e.net/api/v1/social/oauth/meta/callback"
    )


class Graph:
    """Programmable Marketing API responder: queued responses per (method, path)."""

    def __init__(self, token: str = USER_TOKEN, *, proof: bool = True) -> None:
        self.token = token
        self.proof = proof
        self.routes: dict[tuple[str, str], list] = defaultdict(list)
        self.calls: list[tuple[str, str, dict[str, str], dict[str, str]]] = []

    def on(self, method: str, path: str, *responses) -> "Graph":
        self.routes[(method, path)].extend(responses)
        return self

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.facebook.com"
        assert request.url.path.startswith("/v26.0/")
        path = request.url.path.removeprefix("/v26.0/")
        params = dict(request.url.params)
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
        assert request.headers["Authorization"] == f"Bearer {self.token}"
        assert self.token not in str(request.url) and self.token not in request.content.decode()
        expected = hmac.new(APP_SECRET.encode(), self.token.encode(), hashlib.sha256).hexdigest()
        assert (params.get("appsecret_proof") == expected) is self.proof
        self.calls.append((request.method, path, params, body))
        queue = self.routes.get((request.method, path))
        if not queue:
            return httpx.Response(404, json={"error": {"code": 803, "message": f"no route {path}"}})
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        status, payload, *rest = item
        return httpx.Response(status, json=payload, headers=rest[0] if rest else None)


async def _no_sleep(_seconds: float) -> None:
    return None


def _client(graph: Graph) -> MetaAdsGraph:
    return MetaAdsGraph(transport=httpx.MockTransport(graph), sleep=_no_sleep)


def _auth() -> AdsAuth:
    return AdsAuth(access_token=USER_TOKEN, app_secret=APP_SECRET)


def _account(account_id: str, **extra):
    return {
        "id": f"act_{account_id}",
        "account_id": account_id,
        "name": f"Account {account_id}",
        "currency": "AED",
        "timezone_name": "Asia/Dubai",
        "account_status": 1,
        "business": {"name": "IPDOMX"},
        **extra,
    }


@pytest.mark.asyncio
async def test_ad_account_listing_pages_and_drops_malformed_accounts():
    graph = Graph().on(
        "GET",
        "me/adaccounts",
        (200, {"data": [_account(ACCOUNT), {"id": "act_x"}], "paging": {"cursors": {"after": "c2"}, "next": "https://n"}}),
        (200, {"data": [_account("9988776655", currency="usd"), _account(ACCOUNT)], "paging": {}}),
    )
    accounts = await _client(graph).list_ad_accounts(_auth())
    assert [item.ad_account_id for item in accounts] == [ACCOUNT, "9988776655"]
    assert accounts[1].currency == "USD" and accounts[0].timezone_name == "Asia/Dubai"
    assert accounts[0].public()["active"] is True and "token" not in json.dumps(accounts[0].public())
    assert graph.calls[1][2]["after"] == "c2"
    assert USER_TOKEN not in repr(_auth()) and APP_SECRET not in repr(_auth())


@pytest.mark.asyncio
async def test_owner_token_calls_carry_no_app_proof():
    graph = Graph("EAAowner-token", proof=False).on("GET", "me/adaccounts", (200, {"data": [_account(ACCOUNT)]}))
    accounts = await _client(graph).list_ad_accounts(AdsAuth(access_token="EAAowner-token"))
    assert len(accounts) == 1


@pytest.mark.asyncio
async def test_insights_follow_paging_and_report_throttle_headers():
    usage = {"x-business-use-case-usage": json.dumps({"1": [{"call_count": 82, "estimated_time_to_regain_access": 0}]})}
    graph = Graph().on(
        "GET",
        f"act_{ACCOUNT}/insights",
        (200, {"data": [{"campaign_id": "1", "date_start": "2026-11-01"}], "paging": {"cursors": {"after": "p2"}, "next": "https://n"}}, usage),
        (200, {"data": [{"campaign_id": "2", "date_start": "2026-11-01"}]}),
    )
    seen = []
    rows = await _client(graph).insights(
        _auth(), ACCOUNT, level="campaign", date_from=date(2026, 11, 1), date_to=date(2026, 11, 2),
        breakdown="platform_position", on_page=seen.append,
    )
    assert [row["campaign_id"] for row in rows] == ["1", "2"]
    params = graph.calls[0][2]
    assert params["level"] == "campaign" and params["time_increment"] == "1"
    assert json.loads(params["time_range"]) == {"since": "2026-11-01", "until": "2026-11-02"}
    assert params["breakdowns"] == "publisher_platform,platform_position"
    assert seen[0].usage_pct == 82 and seen[0].exceeded(75) and not seen[1].exceeded(75)


@pytest.mark.asyncio
async def test_throttling_token_and_permission_errors_are_classified():
    graph = Graph().on(
        "GET",
        f"act_{ACCOUNT}/insights",
        (400, {"error": {"code": 80004, "message": "too many calls"}}, {"x-ad-account-usage": '{"acc_id_util_pct": 100, "reset_time_duration": 900}'}),
    )
    with pytest.raises(AdsGraphError) as throttled:
        await _client(graph).insights(_auth(), ACCOUNT, level="ad", date_from=date(2026, 11, 1), date_to=date(2026, 11, 1))
    assert throttled.value.throttled and throttled.value.retry_after_seconds == 900
    assert USER_TOKEN not in throttled.value.code
    graph = Graph().on("GET", "me/adaccounts", (401, {"error": {"code": 190}}))
    with pytest.raises(AdsGraphError) as expired:
        await _client(graph).list_ad_accounts(_auth())
    assert expired.value.reconnect and expired.value.code == "meta-ads-accounts-token-invalid"
    graph = Graph().on("GET", "me/adaccounts", (403, {"error": {"code": 200}}))
    with pytest.raises(AdsGraphError) as denied:
        await _client(graph).list_ad_accounts(_auth())
    assert denied.value.code.startswith("meta-ads-accounts-permission-missing")


@pytest.mark.asyncio
async def test_async_report_run_start_poll_and_read():
    graph = (
        Graph()
        .on("POST", f"act_{ACCOUNT}/insights", (200, {"report_run_id": "6123456789"}))
        .on(
            "GET",
            "6123456789",
            (200, {"async_status": "Job Running", "async_percent_completion": 40}),
            (200, {"async_status": "Job Completed", "async_percent_completion": 100}),
        )
        .on("GET", "6123456789/insights", (200, {"data": [{"campaign_id": "1", "date_start": "2026-10-01"}]}))
    )
    client = _client(graph)
    report = await client.start_report(_auth(), ACCOUNT, level="campaign", date_from=date(2026, 10, 1), date_to=date(2026, 10, 30))
    assert report == "6123456789"
    assert json.loads(graph.calls[0][3]["time_range"])["since"] == "2026-10-01"
    assert await client.wait_report(_auth(), report, attempts=3, interval=0) is True
    assert len(await client.report_rows(_auth(), report)) == 1
    pending = Graph().on("GET", "6123456789", (200, {"async_status": "Job Running"}))
    assert await _client(pending).wait_report(_auth(), report, attempts=2, interval=0) is False
    failed = Graph().on("GET", "6123456789", (200, {"async_status": "Job Failed"}))
    with pytest.raises(AdsGraphError):
        await _client(failed).wait_report(_auth(), report, attempts=2, interval=0)


@pytest.mark.asyncio
async def test_campaign_objects_are_created_paused_and_status_is_confirmed():
    graph = (
        Graph()
        .on("POST", f"act_{ACCOUNT}/campaigns", (200, {"id": "120000000000001"}))
        .on("POST", f"act_{ACCOUNT}/adsets", (200, {"id": "120000000000002"}))
        .on("POST", f"act_{ACCOUNT}/ads", (200, {"id": "120000000000004"}))
        .on("POST", "120000000000001", (200, {"success": True}))
        .on("POST", "120000000000009", (200, {"success": False}))
    )
    client = _client(graph)
    assert await client.create_campaign(_auth(), ACCOUNT, name="Spring", objective="OUTCOME_TRAFFIC") == "120000000000001"
    form = graph.calls[0][3]
    assert form["status"] == "PAUSED" and form["special_ad_categories"] == "[]"
    assert form["objective"] == "OUTCOME_TRAFFIC"
    with pytest.raises(AdsGraphError):
        await client.create_adset(_auth(), ACCOUNT, form={"status": "ACTIVE"})
    await client.create_adset(_auth(), ACCOUNT, form={"status": "PAUSED", "targeting": {"geo_locations": {"countries": ["AE"]}}})
    assert json.loads(graph.calls[1][3]["targeting"]) == {"geo_locations": {"countries": ["AE"]}}
    await client.create_ad(_auth(), ACCOUNT, name="Ad", adset_id="120000000000002", creative_id="120000000000003")
    assert graph.calls[2][3]["status"] == "PAUSED"
    await client.set_status(_auth(), "120000000000001", "ACTIVE")
    with pytest.raises(AdsGraphError):
        await client.set_status(_auth(), "120000000000009", "PAUSED")
    with pytest.raises(AdsGraphError):
        await client.set_status(_auth(), "120000000000001", "DELETED")


def test_ads_scopes_are_configurable_and_requested_incrementally(monkeypatch):
    assert ads_scopes() == ("ads_read", "ads_management", "business_management")
    monkeypatch.setattr(settings, "META_ADS_OAUTH_SCOPES", "ads_read, ads_management")
    assert ads_scopes() == ("ads_read", "ads_management")
    assert connections.purpose_scopes("meta", "social") == ()
    assert connections.purpose_scopes("meta", "ads") == ("ads_read", "ads_management")
    with pytest.raises(Exception):
        connections.purpose_scopes("tiktok", "ads")
    url = MetaConnector().authorize_url(state="s" * 43, code_challenge="c" * 43, extra_scopes=ads_scopes())
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    scopes = query["scope"].split(",")
    assert "pages_show_list" in scopes and "ads_management" in scopes
    assert len(scopes) == len(set(scopes)) and query["auth_type"] == "rerequest"
    plain = MetaConnector().authorize_url(state="s" * 43, code_challenge="c" * 43)
    assert "ads_read" not in plain and "auth_type" not in plain
    ads = connections.CallbackResult("meta", "ar", True, "connected", "conn-1", purpose="ads")
    assert "/ar/campaigns/?" in connections.portal_redirect_url(ads)
    assert "/en/social/?" in connections.portal_redirect_url(connections.CallbackResult("meta", "en", False, "x"))


def test_owner_policy_normalizes_caps_and_plan_entitlement():
    policy = entitlement.normalize_policy(
        {
            "daily_cap_minor": "2500",
            "lifetime_cap_minor": -4,
            "plan_codes": ["Pro Plus", "pro_plus"],
            "user_caps": {"u-1": {"daily_cap_minor": 100, "lifetime_cap_minor": 1000}},
        }
    )
    assert policy["daily_cap_minor"] == 2500 and policy["lifetime_cap_minor"] == 0
    assert policy["plan_codes"] == ["pro-plus"]
    access = entitlement.AdsAccess("subscriber", "subscription", "entitled", policy=policy)
    assert access.caps_for("u-1").daily_minor == 100 and access.caps_for("u-2").daily_minor == 2500
    assert access.public("u-1")["live_verified"] is False
    assert entitlement.plan_entitled("pro-plus", [], policy)
    assert not entitlement.plan_entitled("basic", ["ads.manage"], policy)
    flags = entitlement.normalize_policy({})
    assert entitlement.plan_entitled("basic", ["ads.manage"], flags)
    assert entitlement.plan_entitled("basic", ["growth.ads.manage"], flags)
    assert not entitlement.plan_entitled("basic", ["security.web_scanning"], flags)
    with pytest.raises(entitlement.AdsAccessError) as denied:
        entitlement.AdsAccess(None, None, "not-entitled", policy=flags).require()
    assert denied.value.code == entitlement.PLAN_REQUIRED
    with pytest.raises(ValueError):
        entitlement.normalize_policy({"user_caps": {"": {}}})


# --- AI recommendations ---------------------------------------------------------------


class _Session:
    def __init__(self, recent: int = 0) -> None:
        self.recent = recent
        self.added: list = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.recent

    def add(self, item) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def _actor():
    return SimpleNamespace(id="u-1", organization_id="o-1", organization_plan="business", role="User")


BOARD = {
    "currency": "AED",
    "period": {"from": "2026-10-24", "to": "2026-11-06"},
    "kpis": {"spend": {"value": 400.0, "previous": 300.0, "change_pct": 33.3}, "cpa": {"value": 20.0, "previous": 15.0, "change_pct": 33.3}},
    "campaigns": {
        "basis": "roas",
        "top": [{"campaign_id": "11", "name": "Winner", "spend": 300.0, "roas": 3.2, "ctr": 2.0, "cpa": 10.0, "frequency": 1.4}],
        "bottom": [{"campaign_id": "12", "name": "Loser", "spend": 100.0, "roas": 0.4, "ctr": 0.6, "cpa": 50.0, "frequency": 3.8}],
    },
    "breakdowns": {"age": [{"value": "25-34", "spend": 200.0, "ctr": 1.9}]},
    "alerts": [{"type": "frequency_fatigue", "campaign_id": "12", "evidence": {"frequency_last_7_days": 3.8}}],
    "has_data": True,
}


def _wire(monkeypatch, order, *, provider_text):
    link = SimpleNamespace(id="link-1", insights_synced_through=date(2026, 11, 6))
    policy = entitlement.normalize_policy({})

    async def access(_session, _actor):
        return entitlement.AdsAccess("subscriber", "subscription", "entitled", policy=policy)

    async def own_link(_session, _actor, _link_id):
        return link

    async def board(_session, _link, *, date_from, date_to):
        order.append(f"board:{date_from}:{date_to}")
        return BOARD

    async def charge(_session, _actor, *, characters, permission="projects:write"):
        order.append("charge")
        return {"default_agent_id": ""}

    async def choose(_session, _actor, _policy, *, allow_external):
        order.append(f"select:{allow_external}")
        return SimpleNamespace(id="agent-1", model="aionex-ai"), SimpleNamespace(type="ollama")

    async def allowed(_session, service):
        order.append(f"owner:{service}")

    async def provider(_provider, _agent, prompt):
        order.append("provider")
        assert '"campaigns.0.roas": 3.2' in prompt and "Never invent numbers" in prompt
        return {"text": provider_text, "model": "aionex-ai"}

    monkeypatch.setattr(recommendations.entitlement, "resolve_access", access)
    monkeypatch.setattr(recommendations.accounts, "own_link", own_link)
    monkeypatch.setattr(recommendations.analytics, "build_dashboard", board)
    monkeypatch.setattr(recommendations.governance, "charge_project_request", charge)
    monkeypatch.setattr(recommendations.social_ai_assist, "select_agent", choose)
    monkeypatch.setattr(recommendations, "require_owner_service_allowed", allowed)
    monkeypatch.setattr(recommendations.ai, "_execute_provider", provider)


@pytest.mark.asyncio
async def test_recommendations_charge_quota_first_and_keep_only_grounded_advice(monkeypatch):
    order: list[str] = []
    text = json.dumps(
        {
            "recommendations": [
                {
                    "type": "budget_shift",
                    "title": "Shift budget to Winner",
                    "action": "Move 20% of Loser's budget to Winner",
                    "rationale": "ROAS 3.2 vs 0.4",
                    "evidence": ["campaigns.0.roas", "campaigns.1.roas"],
                },
                {"type": "creative_fatigue", "title": "Refresh", "action": "New creative", "evidence": ["campaigns.1.ctr_trend"]},
            ]
        }
    )
    _wire(monkeypatch, order, provider_text=text)
    session = _Session()
    result = await recommendations.recommend(session, _actor(), "link-1", language="ar", external_processing_confirmed=False)
    assert order == ["board:2026-10-24:2026-11-06", "charge", "select:False", "owner:ollama", "provider"]
    assert session.commits == 2  # quota reservation before the provider, the run after
    assert result["aionex_ai"] is True and result["advisory_only"] is True and result["auto_apply"] is False
    assert result["rejected"] == 1 and len(result["items"]) == 1
    assert result["items"][0]["evidence"] == {"campaigns.0.roas": 3.2, "campaigns.1.roas": 0.4}
    assert session.added[-1].items == result["items"]


@pytest.mark.asyncio
async def test_recommendations_respect_plan_quota_and_daily_limit(monkeypatch):
    order: list[str] = []
    _wire(monkeypatch, order, provider_text="{}")

    async def exhausted(_session, _actor, *, characters, permission="projects:write"):
        raise HTTPException(status_code=429, detail={"code": "DAILY_MESSAGE_LIMIT"})

    monkeypatch.setattr(recommendations.governance, "charge_project_request", exhausted)
    with pytest.raises(HTTPException) as quota:
        await recommendations.recommend(_Session(), _actor(), "link-1", language="en", external_processing_confirmed=False)
    assert quota.value.status_code == 429 and "provider" not in order
    with pytest.raises(AdsError) as limit:
        await recommendations.recommend(_Session(recent=10), _actor(), "link-1", language="en", external_processing_confirmed=False)
    assert limit.value.code == "ads-recommendation-daily-limit"
    with pytest.raises(AdsError) as language:
        await recommendations.recommend(_Session(), _actor(), "link-1", language="xx", external_processing_confirmed=False)
    assert language.value.code == "ai-language-invalid"


def test_grounding_is_numeric_and_prompt_labels_campaigns():
    grounding = recommendations.grounding_from(BOARD)
    assert [item["campaign_id"] for item in grounding["campaigns"]] == ["11", "12"]
    prompt = recommendations.build_prompt(grounding, language="ar")
    assert "Winner (11)" in prompt and "Arabic" in prompt
    with pytest.raises(AdsError):
        recommendations.parse_output("no json here")
