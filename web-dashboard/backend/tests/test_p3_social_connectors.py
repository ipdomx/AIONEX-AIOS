"""P3 social connector framework and Meta connector contracts (no database).

Graph API traffic is served by ``httpx.MockTransport``; nothing leaves the
process. Covers state/PKCE, token sealing, configuration honesty, the code
exchange and long-lived upgrade, asset listing, health inspection, revocation
and the client-safe serializers.
"""

from __future__ import annotations

import ast
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.config import settings
from app.services import social_connections as connections
from app.services import social_connectors as framework
from app.services.social_meta_provider import DEFAULT_SCOPES, MetaConnector

BACKEND = Path(__file__).resolve().parents[1]
APP_ID = "1234567890123"
APP_SECRET = "p3-test-app-secret-value"
USER_TOKEN_SHORT = "EAAshort-lived-user-token"
USER_TOKEN_LONG = "EAAlong-lived-user-token"
PAGE_TOKEN = "EAApage-access-token-one"
PAGE_TOKEN_TWO = "EAApage-access-token-two"


@pytest.fixture
def meta_settings(monkeypatch):
    monkeypatch.setattr(settings, "META_APP_ID", APP_ID)
    monkeypatch.setattr(settings, "META_APP_ID_FILE", "")
    monkeypatch.setattr(settings, "META_APP_SECRET", APP_SECRET)
    monkeypatch.setattr(settings, "META_APP_SECRET_FILE", "")
    monkeypatch.setattr(settings, "META_GRAPH_API_VERSION", "v26.0")
    monkeypatch.setattr(
        settings,
        "META_OAUTH_REDIRECT_URI",
        "https://api.vip-e.net/api/v1/social/oauth/meta/callback",
    )
    monkeypatch.setattr(settings, "META_OAUTH_SCOPES", ",".join(DEFAULT_SCOPES))
    monkeypatch.setattr(settings, "META_OAUTH_USE_PKCE", True)
    return settings


@pytest.fixture
def unconfigured(monkeypatch):
    for name in ("META_APP_ID", "META_APP_ID_FILE", "META_APP_SECRET", "META_APP_SECRET_FILE"):
        monkeypatch.setattr(settings, name, "")
    return settings


class GraphStub:
    """Deterministic Graph API responder recording every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.revoked = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "graph.facebook.com"
        assert request.url.path.startswith("/v26.0/")
        path = request.url.path.removeprefix("/v26.0/")
        params = dict(request.url.params)
        if path == "oauth/access_token" and "code" in params:
            if params["code"] != "good-code":
                return httpx.Response(400, json={"error": {"code": 100, "message": "bad code"}})
            return httpx.Response(
                200, json={"access_token": USER_TOKEN_SHORT, "token_type": "bearer", "expires_in": 3600}
            )
        if path == "oauth/access_token" and params.get("grant_type") == "fb_exchange_token":
            return httpx.Response(
                200,
                json={"access_token": USER_TOKEN_LONG, "token_type": "bearer", "expires_in": 5_184_000},
            )
        if path == "me":
            return httpx.Response(
                200,
                json={
                    "id": "99887766",
                    "name": "Owner Person",
                    "picture": {"data": {"url": "https://cdn.example.test/me.jpg"}},
                },
            )
        if path == "me/accounts":
            if params.get("after") == "cursor-2":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "2222222",
                                "name": "Second Page",
                                "access_token": PAGE_TOKEN_TWO,
                                "tasks": ["CREATE_CONTENT", "UNKNOWN_TASK"],
                            }
                        ],
                        "paging": {"cursors": {"after": "cursor-3"}},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "1111111",
                            "name": "Main Page",
                            "access_token": PAGE_TOKEN,
                            "tasks": ["MANAGE", "CREATE_CONTENT", "MESSAGING"],
                            "picture": {"data": {"url": "https://cdn.example.test/p1.jpg"}},
                            "instagram_business_account": {
                                "id": "17841400000000001",
                                "username": "main.brand",
                                "name": "Main Brand",
                                "profile_picture_url": "https://cdn.example.test/ig.jpg",
                            },
                        },
                        {"id": "not-numeric", "name": "Broken"},
                    ],
                    "paging": {"cursors": {"after": "cursor-2"}, "next": "https://graph.facebook.com/next"},
                },
            )
        if path == "debug_token":
            assert params["access_token"] == f"{APP_ID}|{APP_SECRET}"
            expires = int((datetime.now(UTC) + timedelta(days=50)).timestamp())
            return httpx.Response(
                200,
                json={
                    "data": {
                        "app_id": APP_ID,
                        "is_valid": True,
                        "expires_at": expires,
                        "scopes": list(DEFAULT_SCOPES),
                        "user_id": "99887766",
                    }
                },
            )
        if path == "99887766/permissions" and request.method == "DELETE":
            self.revoked = True
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"error": {"code": 803, "message": "unknown"}})


def _connector(stub: GraphStub) -> MetaConnector:
    return MetaConnector(transport=httpx.MockTransport(stub))


# --- state / PKCE -----------------------------------------------------------------------


def test_pkce_s256_matches_rfc7636_appendix_b() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert framework.code_challenge_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_generated_verifier_state_and_binding_are_high_entropy_and_unique() -> None:
    verifiers = {framework.new_code_verifier() for _ in range(32)}
    assert len(verifiers) == 32
    assert all(43 <= len(item) <= 128 for item in verifiers)
    states = {framework.new_state() for _ in range(32)}
    assert len(states) == 32 and all(len(item) >= 43 for item in states)
    assert framework.new_browser_binding() != framework.new_browser_binding()


def test_pkce_rejects_out_of_range_verifiers() -> None:
    with pytest.raises(framework.SocialConnectorError, match="pkce-verifier-invalid"):
        framework.code_challenge_s256("short")
    with pytest.raises(framework.SocialConnectorError, match="pkce-verifier-invalid"):
        framework.code_challenge_s256("x" * 129)


def test_state_digest_matching_is_exact_and_rejects_missing_values() -> None:
    state = framework.new_state()
    expected = framework.digest(state)
    assert len(expected) == 64 and state not in expected
    assert framework.digest_matches(state, expected) is True
    assert framework.digest_matches(state + "x", expected) is False
    assert framework.digest_matches(None, expected) is False
    assert framework.digest_matches("", expected) is False


# --- token sealing ----------------------------------------------------------------------


def test_token_encryption_round_trip_never_stores_plaintext() -> None:
    sealed = framework.seal_token(PAGE_TOKEN)
    assert sealed.startswith(framework.SEALED_TOKEN_PREFIX)
    assert PAGE_TOKEN not in sealed
    assert framework.seal_token(PAGE_TOKEN) != sealed  # Fernet is randomized
    assert framework.open_token(sealed) == PAGE_TOKEN


def test_opening_a_missing_token_fails_closed() -> None:
    with pytest.raises(framework.SocialConnectorError, match="token-not-available"):
        framework.open_token(None)
    with pytest.raises(framework.SocialConnectorError, match="token-missing"):
        framework.seal_token("  ")


def test_token_values_are_hidden_from_repr() -> None:
    grant = framework.TokenGrant(access_token=USER_TOKEN_LONG, refresh_token="refresh-secret")
    asset = framework.ConnectableAsset(
        provider="facebook", account_kind="page", external_id="1111111",
        display_name="Main Page", access_token=PAGE_TOKEN,
    )
    assert USER_TOKEN_LONG not in repr(grant) and "refresh-secret" not in repr(grant)
    assert PAGE_TOKEN not in repr(asset)
    public = asset.public()
    assert "access_token" not in public and PAGE_TOKEN not in json.dumps(public)
    assert public["asset_id"] == "facebook:1111111"


# --- configuration honesty --------------------------------------------------------------


def test_meta_reports_not_configured_without_app_credentials(unconfigured) -> None:
    connector = MetaConnector()
    status = connector.status()
    assert status.configured is False
    assert status.reason == "meta-app-id-missing"
    with pytest.raises(framework.SocialConnectorError) as raised:
        connector.authorize_url(state="s" * 43, code_challenge="c" * 43)
    assert raised.value.code == "provider-not-configured"
    assert raised.value.status_code == 409


def test_catalog_lists_meta_honestly_and_planned_providers_as_coming_soon(unconfigured) -> None:
    catalog = {item["key"]: item for item in framework.provider_catalog()}
    assert catalog["meta"]["status"] == "not_configured"
    assert catalog["meta"]["connectable"] is False
    for key in ("tiktok", "x", "linkedin", "youtube", "snapchat", "pinterest", "whatsapp"):
        assert catalog[key]["status"] == "coming_soon"
        assert catalog[key]["connectable"] is False
    with pytest.raises(framework.SocialConnectorError) as raised:
        framework.get_connector("tiktok")
    assert raised.value.code == "provider-coming-soon"
    with pytest.raises(framework.SocialConnectorError) as raised:
        framework.get_connector("myspace")
    assert raised.value.code == "unsupported-provider"


def test_catalog_reports_configured_meta(meta_settings) -> None:
    item = next(row for row in framework.provider_catalog() if row["key"] == "meta")
    assert item["status"] == "configured" and item["connectable"] is True
    assert item["account_providers"] == ["facebook", "instagram"]
    assert item["scopes"] == list(DEFAULT_SCOPES)
    assert APP_SECRET not in json.dumps(item)


def test_secret_file_is_read_and_unsafe_file_is_not_configured(meta_settings, monkeypatch, tmp_path) -> None:
    secret_file = tmp_path / "meta-app-secret"
    secret_file.write_text("file-backed-secret\n", encoding="utf-8")
    os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)
    monkeypatch.setattr(settings, "META_APP_SECRET", "")
    monkeypatch.setattr(settings, "META_APP_SECRET_FILE", str(secret_file))
    assert MetaConnector().status().configured is True
    os.chmod(secret_file, 0o644)
    status = MetaConnector().status()
    assert status.configured is False and status.reason == "meta-app-secret-file-unreadable"


def test_invalid_redirect_uri_or_version_is_not_configured(meta_settings, monkeypatch) -> None:
    monkeypatch.setattr(settings, "META_OAUTH_REDIRECT_URI", "http://api.vip-e.net/cb")
    assert MetaConnector().status().reason == "meta-redirect-uri-invalid"
    monkeypatch.setattr(settings, "META_OAUTH_REDIRECT_URI", "https://api.vip-e.net/cb")
    monkeypatch.setattr(settings, "META_GRAPH_API_VERSION", "latest")
    assert MetaConnector().status().reason == "meta-graph-version-invalid"


def test_scope_set_is_configurable_and_sanitized(meta_settings, monkeypatch) -> None:
    monkeypatch.setattr(settings, "META_OAUTH_SCOPES", "pages_show_list, instagram_basic,BAD SCOPE!,pages_show_list")
    assert MetaConnector().scopes() == ("pages_show_list", "instagram_basic", "bad")
    monkeypatch.setattr(settings, "META_OAUTH_SCOPES", " ,, ")
    assert MetaConnector().scopes() == DEFAULT_SCOPES


# --- OAuth with mocked Graph ------------------------------------------------------------


def test_authorize_url_carries_state_pkce_scopes_and_redirect(meta_settings) -> None:
    connector = MetaConnector()
    verifier = framework.new_code_verifier()
    challenge = framework.code_challenge_s256(verifier)
    url = connector.authorize_url(state="state-value-" + "a" * 40, code_challenge=challenge)
    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.netloc == "www.facebook.com"
    assert parts.path == "/v26.0/dialog/oauth"
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert query["client_id"] == APP_ID
    assert query["redirect_uri"] == "https://api.vip-e.net/api/v1/social/oauth/meta/callback"
    assert query["state"].startswith("state-value-")
    assert query["response_type"] == "code"
    assert query["scope"].split(",") == list(DEFAULT_SCOPES)
    assert query["code_challenge"] == challenge
    assert query["code_challenge_method"] == "S256"
    assert APP_SECRET not in url and verifier not in url


def test_pkce_can_be_disabled_by_configuration(meta_settings, monkeypatch) -> None:
    monkeypatch.setattr(settings, "META_OAUTH_USE_PKCE", False)
    url = MetaConnector().authorize_url(state="s" * 43, code_challenge=None)
    assert "code_challenge" not in url


@pytest.mark.asyncio
async def test_code_exchange_and_long_lived_upgrade(meta_settings) -> None:
    stub = GraphStub()
    connector = _connector(stub)
    short = await connector.exchange_code(code="good-code", code_verifier="v" * 64)
    assert short.access_token == USER_TOKEN_SHORT
    exchange = dict(stub.requests[0].url.params)
    assert exchange["code_verifier"] == "v" * 64
    assert exchange["redirect_uri"] == settings.META_OAUTH_REDIRECT_URI
    assert exchange["client_id"] == APP_ID

    long_lived = await connector.upgrade_token(short)
    assert long_lived.access_token == USER_TOKEN_LONG
    assert long_lived.expires_at is not None
    assert long_lived.expires_at > datetime.now(UTC) + timedelta(days=59)
    upgrade = dict(stub.requests[1].url.params)
    assert upgrade["grant_type"] == "fb_exchange_token"
    assert upgrade["fb_exchange_token"] == USER_TOKEN_SHORT

    refreshed = await connector.refresh(long_lived)
    assert refreshed.access_token == USER_TOKEN_LONG


@pytest.mark.asyncio
async def test_graph_errors_map_to_codes_without_provider_text(meta_settings) -> None:
    connector = _connector(GraphStub())
    with pytest.raises(framework.SocialConnectorError) as raised:
        await connector.exchange_code(code="bad-code", code_verifier="v" * 64)
    assert raised.value.code == "meta-exchange-api-error-100"
    assert "bad code" not in str(raised.value)
    with pytest.raises(framework.SocialConnectorError, match="pkce-verifier-missing"):
        await connector.exchange_code(code="good-code", code_verifier=None)


@pytest.mark.asyncio
async def test_network_failure_is_reported_as_unreachable(meta_settings) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    connector = MetaConnector(transport=httpx.MockTransport(broken))
    with pytest.raises(framework.SocialConnectorError) as raised:
        await connector.identity(USER_TOKEN_LONG)
    assert raised.value.code.startswith("meta-identity-unreachable")
    assert raised.value.status_code == 502


@pytest.mark.asyncio
async def test_identity_uses_bearer_and_appsecret_proof(meta_settings) -> None:
    stub = GraphStub()
    identity = await _connector(stub).identity(USER_TOKEN_LONG)
    assert identity.external_id == "99887766"
    assert identity.display_name == "Owner Person"
    assert identity.avatar_url == "https://cdn.example.test/me.jpg"
    request = stub.requests[0]
    assert request.headers["Authorization"] == f"Bearer {USER_TOKEN_LONG}"
    assert USER_TOKEN_LONG not in str(request.url)
    assert len(dict(request.url.params)["appsecret_proof"]) == 64


@pytest.mark.asyncio
async def test_asset_listing_returns_pages_and_linked_instagram_accounts(meta_settings) -> None:
    stub = GraphStub()
    assets = await _connector(stub).list_assets(USER_TOKEN_LONG)
    by_id = {asset.asset_id: asset for asset in assets}
    assert set(by_id) == {"facebook:1111111", "instagram:17841400000000001", "facebook:2222222"}
    page = by_id["facebook:1111111"]
    assert page.account_kind == "page" and page.access_token == PAGE_TOKEN
    assert page.tasks == ("CREATE_CONTENT", "MANAGE", "MESSAGING")
    instagram = by_id["instagram:17841400000000001"]
    assert instagram.account_kind == "business"
    assert instagram.handle == "main.brand"
    assert instagram.linked_external_id == "1111111"
    assert instagram.access_token == PAGE_TOKEN
    assert by_id["facebook:2222222"].tasks == ("CREATE_CONTENT",)
    # Pagination stopped once "next" disappeared.
    assert [dict(r.url.params).get("after") for r in stub.requests] == [None, "cursor-2"]
    serialized = json.dumps([asset.public() for asset in assets])
    assert PAGE_TOKEN not in serialized and PAGE_TOKEN_TWO not in serialized


@pytest.mark.asyncio
async def test_token_inspection_and_health_states(meta_settings) -> None:
    health = await _connector(GraphStub()).inspect_token(PAGE_TOKEN)
    assert health.valid is True
    assert set(health.scopes) == set(DEFAULT_SCOPES)
    state, reasons = connections.health_from_inspection(health, required_scopes=DEFAULT_SCOPES)
    assert (state, reasons) == ("healthy", ["token-valid"])

    now = datetime.now(UTC)
    soon = framework.TokenHealth(True, now + timedelta(days=2), DEFAULT_SCOPES)
    assert connections.health_from_inspection(soon, required_scopes=DEFAULT_SCOPES)[0] == "expiring"
    partial = framework.TokenHealth(True, None, ("pages_show_list",))
    state, reasons = connections.health_from_inspection(partial, required_scopes=DEFAULT_SCOPES)
    assert state == "degraded" and "missing-scope:pages_manage_posts" in reasons
    invalid = framework.TokenHealth(False, None, (), ("meta-token-error-190",))
    assert connections.health_from_inspection(invalid, required_scopes=DEFAULT_SCOPES) == (
        "invalid", ["meta-token-error-190"]
    )
    expired = framework.TokenHealth(True, now - timedelta(minutes=1), DEFAULT_SCOPES)
    assert connections.health_from_inspection(expired, required_scopes=DEFAULT_SCOPES)[0] == "expired"


@pytest.mark.asyncio
async def test_revoke_deletes_app_permissions_for_the_user(meta_settings) -> None:
    stub = GraphStub()
    assert await _connector(stub).revoke(access_token=USER_TOKEN_LONG, external_user_id="99887766") is True
    assert stub.revoked is True
    assert stub.requests[-1].method == "DELETE"
    with pytest.raises(framework.SocialConnectorError, match="meta-user-id-invalid"):
        await _connector(stub).revoke(access_token=USER_TOKEN_LONG, external_user_id="../me")


# --- serializers and redirects ----------------------------------------------------------


def _row(**values):
    base = dict(
        id="row-1", connection_id="conn-1", provider="facebook", account_kind="page",
        external_account_id="1111111", display_name="Main Page", public_handle=None,
        avatar_url=None, scopes=["pages_show_list"], status="active", health_state="healthy",
        health_reasons=["token-valid"], token_expires_at=None, last_health_at=None,
        token_ciphertext="fernet:v1:sealed-value", credential_ref="vault:social-account/row-1",
        provider_metadata={"connector": "meta", "linked_external_id": None},
        created_at=None, updated_at=None, external_user_id="99887766",
        requested_scopes=[], granted_scopes=[],
    )
    base.update(values)
    return SimpleNamespace(**base)


def test_public_serializers_never_expose_tokens_or_ciphertext() -> None:
    row = _row()
    for payload in (connections.public_account(row), connections.public_connection(row)):  # type: ignore[arg-type]
        text = json.dumps(payload, default=str)
        assert "fernet:" not in text and "sealed-value" not in text
        assert "vault:" not in text
        assert not any("token" in key and key != "token_expires_at" for key in payload)
        assert not any("cipher" in key or "credential_ref" == key for key in payload)
    assert connections.public_account(row)["credential_stored"] is True  # type: ignore[arg-type]


def test_portal_redirect_uses_locale_and_result_codes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SOCIAL_PORTAL_URL", "https://ai.vip-e.net")
    ok = connections.CallbackResult("meta", "ar", True, "connected", "conn-1")
    url = connections.portal_redirect_url(ok)
    assert url.startswith("https://ai.vip-e.net/ar/social/?")
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    assert query == {"connect": "meta", "result": "success", "code": "connected", "connection": "conn-1"}
    failed = connections.CallbackResult("meta", "en", False, "oauth-state-expired")
    assert "result=error" in connections.portal_redirect_url(failed)
    assert connections.normalize_locale("xx") == "en"
    assert connections.normalize_locale("TR") == "tr"


def test_social_modules_have_no_bare_pass_and_never_log_tokens() -> None:
    for relative in (
        "app/services/social_connectors.py",
        "app/services/social_meta_provider.py",
        "app/services/social_connections.py",
        "app/api/v1/endpoints/social.py",
    ):
        source = (BACKEND / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(isinstance(node, ast.Pass) for node in ast.walk(tree)), relative
        assert "NotImplementedError" not in source, relative
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"info", "warning", "error", "debug", "exception"}:
                    rendered = ast.unparse(node)
                    assert "token" not in rendered.lower(), (relative, rendered)
