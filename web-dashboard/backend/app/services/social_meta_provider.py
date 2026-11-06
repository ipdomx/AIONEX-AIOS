"""Meta (Facebook Pages + Instagram Business) connector for the P3 framework.

Facebook Login (manual web flow) with ``state`` and PKCE, code exchange, the
long-lived user token upgrade, Page listing with Page access tokens, the
Instagram Business accounts linked to those Pages, ``debug_token`` health
checks and permission revocation. Every Graph call is pinned to
``settings.META_GRAPH_API_VERSION`` and carries ``appsecret_proof``.

The app id and secret are read from the environment or private secret files
at call time. When they are missing or unreadable the connector reports
``not_configured`` and refuses to start a flow; it never pretends to work.
Tokens are never logged and never included in an error.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from app.core.config import _read_private_runtime_secret, settings
from app.services.social_connectors import (
    ConnectableAsset,
    ProviderIdentity,
    ProviderStatus,
    SocialConnectorError,
    TokenGrant,
    TokenHealth,
)

GRAPH_HOST = "https://graph.facebook.com"
DIALOG_HOST = "https://www.facebook.com"
DEFAULT_SCOPES: tuple[str, ...] = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "pages_messaging",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_messages",
    "instagram_manage_comments",
    "business_management",
)
# Capabilities the requested scopes are meant for. Publishing and inbox are
# later roadmap items (3.3 and 3.6); the catalog marks only connect-level
# features as live.
CAPABILITIES: dict[str, tuple[str, ...]] = {
    "facebook": ("account.read", "content.publish", "inbox.read", "inbox.reply"),
    "instagram": ("account.read", "content.publish", "inbox.read", "inbox.reply"),
}
MAX_ASSET_PAGES = 5
PAGE_SIZE = 100
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_VERSION_RE = re.compile(r"^v\d{1,3}\.\d{1,2}$")
_SCOPE_RE = re.compile(r"^[a-z][a-z_]{2,63}$")
_ID_RE = re.compile(r"^\d{3,32}$")
_ALLOWED_TASKS = frozenset(
    {"ADVERTISE", "ANALYZE", "CREATE_CONTENT", "MANAGE", "MESSAGING", "MODERATE"}
)


def configured_scopes() -> tuple[str, ...]:
    raw = str(settings.META_OAUTH_SCOPES or "")
    scopes: list[str] = []
    for item in re.split(r"[\s,]+", raw):
        scope = item.strip().lower()
        if scope and _SCOPE_RE.fullmatch(scope) and scope not in scopes:
            scopes.append(scope)
    return tuple(scopes) or DEFAULT_SCOPES


def _secret_value(direct: str, file_path: str, *, label: str) -> tuple[str, str | None]:
    """Return (value, reason). The file wins when its path is configured."""

    if (file_path or "").strip():
        try:
            return _read_private_runtime_secret(file_path, label=label), None
        except ValueError:
            return "", f"{label.lower().replace('_', '-')}-file-unreadable"
    value = (direct or "").strip()
    if not value:
        return "", f"{label.lower().replace('_', '-')}-missing"
    return value, None


def _redirect_uri_valid(uri: str) -> bool:
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}


def _expires_at(expires_in: Any, *, now: datetime | None = None) -> datetime | None:
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return (now or datetime.now(UTC)) + timedelta(seconds=seconds)


def _epoch(value: Any) -> datetime | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, UTC)


def _error_code(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:12] or "unknown"


def _clean_text(value: Any, *, limit: int, fallback: str = "") -> str:
    text = " ".join(str(value or "").split())
    return (text or fallback)[:limit]


def _https_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 1024:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    return value


def _picture_url(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    data = node.get("data")
    if isinstance(data, dict):
        return _https_url(data.get("url"))
    return None


def _tasks(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        sorted(
            {
                task
                for raw in value
                if isinstance(raw, str) and (task := raw.strip().upper()) in _ALLOWED_TASKS
            }
        )
    )


class MetaConnector:
    key = "meta"
    display_name = "Meta (Facebook & Instagram)"
    account_providers: tuple[str, ...] = ("facebook", "instagram")
    supports_refresh = True

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    # --- configuration -------------------------------------------------------------

    @property
    def supports_pkce(self) -> bool:
        return bool(settings.META_OAUTH_USE_PKCE)

    @property
    def api_version(self) -> str:
        return str(settings.META_GRAPH_API_VERSION or "").strip()

    @property
    def redirect_uri(self) -> str:
        return str(settings.META_OAUTH_REDIRECT_URI or "").strip()

    def _credentials(self) -> tuple[str, str, str | None]:
        app_id, id_reason = _secret_value(
            settings.META_APP_ID, settings.META_APP_ID_FILE, label="META_APP_ID"
        )
        secret, secret_reason = _secret_value(
            settings.META_APP_SECRET, settings.META_APP_SECRET_FILE, label="META_APP_SECRET"
        )
        reason = id_reason or secret_reason
        if reason is None and not _ID_RE.fullmatch(app_id):
            reason = "meta-app-id-invalid"
        if reason is None and not _VERSION_RE.fullmatch(self.api_version):
            reason = "meta-graph-version-invalid"
        if reason is None and not _redirect_uri_valid(self.redirect_uri):
            reason = "meta-redirect-uri-invalid"
        return app_id, secret, reason

    def status(self) -> ProviderStatus:
        _app_id, _secret, reason = self._credentials()
        if reason is not None:
            return ProviderStatus(configured=False, reason=reason)
        return ProviderStatus(configured=True)

    def _require_credentials(self) -> tuple[str, str]:
        app_id, secret, reason = self._credentials()
        if reason is not None:
            raise SocialConnectorError("provider-not-configured", status_code=409)
        return app_id, secret

    def scopes(self) -> tuple[str, ...]:
        return configured_scopes()

    def capabilities(self) -> dict[str, tuple[str, ...]]:
        return dict(CAPABILITIES)

    # --- HTTP ----------------------------------------------------------------------

    def _graph(self, path: str) -> str:
        return f"{GRAPH_HOST}/{self.api_version}/{path.lstrip('/')}"

    @staticmethod
    def _proof(secret: str, access_token: str) -> str:
        return hmac.new(
            secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    async def _call(
        self,
        method: str,
        path: str,
        *,
        action: str,
        params: dict[str, str],
        access_token: str | None = None,
        secret: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        query = dict(params)
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"
            if secret:
                query["appsecret_proof"] = self._proof(secret, access_token)
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
            ) as client:
                response = await client.request(
                    method, self._graph(path), params=query, headers=headers
                )
        except httpx.HTTPError as exc:
            raise SocialConnectorError(
                f"meta-{action}-unreachable-{type(exc).__name__.lower()}", status_code=502
            ) from None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400 or not isinstance(payload, dict):
            code: Any = response.status_code
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                code = payload["error"].get("code", code)
            raise SocialConnectorError(
                f"meta-{action}-api-error-{_error_code(code)}",
                status_code=502,
            )
        if isinstance(payload.get("error"), dict):
            raise SocialConnectorError(
                f"meta-{action}-api-error-{_error_code(payload['error'].get('code'))}",
                status_code=502,
            )
        return payload

    @staticmethod
    def _grant(payload: dict[str, Any], *, action: str) -> TokenGrant:
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip() or len(token) > 4096:
            raise SocialConnectorError(f"meta-{action}-response-invalid", status_code=502)
        return TokenGrant(
            access_token=token.strip(),
            expires_at=_expires_at(payload.get("expires_in")),
            token_type=_clean_text(payload.get("token_type"), limit=24, fallback="bearer"),
        )

    # --- OAuth ---------------------------------------------------------------------

    def authorize_url(self, *, state: str, code_challenge: str | None) -> str:
        app_id, _secret = self._require_credentials()
        if not state:
            raise SocialConnectorError("oauth-state-missing")
        params = {
            "client_id": app_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": ",".join(self.scopes()),
        }
        if self.supports_pkce:
            if not code_challenge:
                raise SocialConnectorError("pkce-challenge-missing")
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{DIALOG_HOST}/{self.api_version}/dialog/oauth?{urlencode(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str | None) -> TokenGrant:
        app_id, secret = self._require_credentials()
        if not code or len(code) > 2048:
            raise SocialConnectorError("oauth-code-invalid")
        params = {
            "client_id": app_id,
            "client_secret": secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }
        if self.supports_pkce:
            if not code_verifier:
                raise SocialConnectorError("pkce-verifier-missing")
            params["code_verifier"] = code_verifier
        payload = await self._call("GET", "oauth/access_token", action="exchange", params=params)
        return self._grant(payload, action="exchange")

    async def upgrade_token(self, grant: TokenGrant) -> TokenGrant:
        app_id, secret = self._require_credentials()
        payload = await self._call(
            "GET",
            "oauth/access_token",
            action="upgrade",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": secret,
                "fb_exchange_token": grant.access_token,
            },
        )
        upgraded = self._grant(payload, action="upgrade")
        return TokenGrant(
            access_token=upgraded.access_token,
            expires_at=upgraded.expires_at,
            scopes=grant.scopes,
            token_type=upgraded.token_type,
        )

    async def refresh(self, grant: TokenGrant) -> TokenGrant:
        # Meta has no refresh token: a still-valid long-lived user token is
        # re-extended through the same fb_exchange_token grant.
        return await self.upgrade_token(grant)

    async def revoke(self, *, access_token: str, external_user_id: str) -> bool:
        _app_id, secret = self._require_credentials()
        if not _ID_RE.fullmatch(external_user_id or ""):
            raise SocialConnectorError("meta-user-id-invalid")
        payload = await self._call(
            "DELETE",
            f"{external_user_id}/permissions",
            action="revoke",
            params={},
            access_token=access_token,
            secret=secret,
        )
        return payload.get("success") is True

    async def identity(self, access_token: str) -> ProviderIdentity:
        _app_id, secret = self._require_credentials()
        payload = await self._call(
            "GET",
            "me",
            action="identity",
            params={"fields": "id,name,picture.width(200).height(200)"},
            access_token=access_token,
            secret=secret,
        )
        external_id = str(payload.get("id") or "")
        if not _ID_RE.fullmatch(external_id):
            raise SocialConnectorError("meta-identity-response-invalid", status_code=502)
        return ProviderIdentity(
            external_id=external_id,
            display_name=_clean_text(payload.get("name"), limit=240, fallback="Meta user"),
            avatar_url=_picture_url(payload.get("picture")),
        )

    async def list_assets(self, access_token: str) -> list[ConnectableAsset]:
        _app_id, secret = self._require_credentials()
        assets: list[ConnectableAsset] = []
        seen: set[str] = set()
        after: str | None = None
        for _page in range(MAX_ASSET_PAGES):
            params = {
                "fields": (
                    "id,name,access_token,tasks,picture{url},"
                    "instagram_business_account{id,username,name,profile_picture_url}"
                ),
                "limit": str(PAGE_SIZE),
            }
            if after:
                params["after"] = after
            payload = await self._call(
                "GET",
                "me/accounts",
                action="assets",
                params=params,
                access_token=access_token,
                secret=secret,
            )
            data = payload.get("data")
            if not isinstance(data, list):
                raise SocialConnectorError("meta-assets-response-invalid", status_code=502)
            for raw in data:
                if isinstance(raw, dict):
                    self._collect_page(raw, assets, seen)
            paging = payload.get("paging")
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            next_after = cursors.get("after") if isinstance(cursors, dict) else None
            has_next = isinstance(paging, dict) and bool(paging.get("next"))
            if not has_next or not isinstance(next_after, str) or not next_after:
                break
            after = next_after
        return assets

    @staticmethod
    def _collect_page(
        raw: dict[str, Any], assets: list[ConnectableAsset], seen: set[str]
    ) -> None:
        page_id = str(raw.get("id") or "")
        page_token = raw.get("access_token")
        if not _ID_RE.fullmatch(page_id) or f"facebook:{page_id}" in seen:
            return
        token = page_token.strip() if isinstance(page_token, str) and page_token.strip() else None
        page_name = _clean_text(raw.get("name"), limit=240, fallback="Facebook Page")
        seen.add(f"facebook:{page_id}")
        assets.append(
            ConnectableAsset(
                provider="facebook",
                account_kind="page",
                external_id=page_id,
                display_name=page_name,
                avatar_url=_picture_url(raw.get("picture")),
                tasks=_tasks(raw.get("tasks")),
                access_token=token,
            )
        )
        instagram = raw.get("instagram_business_account")
        if not isinstance(instagram, dict):
            return
        ig_id = str(instagram.get("id") or "")
        if not _ID_RE.fullmatch(ig_id) or f"instagram:{ig_id}" in seen:
            return
        username = _clean_text(instagram.get("username"), limit=120) or None
        seen.add(f"instagram:{ig_id}")
        assets.append(
            ConnectableAsset(
                provider="instagram",
                account_kind="business",
                external_id=ig_id,
                display_name=_clean_text(
                    instagram.get("name") or username, limit=240, fallback="Instagram account"
                ),
                handle=username,
                avatar_url=_https_url(instagram.get("profile_picture_url")),
                linked_external_id=page_id,
                # Instagram Graph calls for a Business account use the linked
                # Page's access token.
                access_token=token,
            )
        )

    async def inspect_token(self, access_token: str) -> TokenHealth:
        app_id, secret = self._require_credentials()
        payload = await self._call(
            "GET",
            "debug_token",
            action="health",
            params={"input_token": access_token, "access_token": f"{app_id}|{secret}"},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SocialConnectorError("meta-health-response-invalid", status_code=502)
        scopes = tuple(
            sorted(
                {
                    scope
                    for scope in data.get("scopes") or []
                    if isinstance(scope, str) and _SCOPE_RE.fullmatch(scope)
                }
            )
        )
        reasons: list[str] = []
        valid = data.get("is_valid") is True
        if str(data.get("app_id") or "") not in {"", app_id}:
            valid = False
            reasons.append("token-issued-for-another-app")
        if isinstance(data.get("error"), dict):
            reasons.append(f"meta-token-error-{_error_code(data['error'].get('code'))}")
        if not valid and not reasons:
            reasons.append("token-invalid")
        return TokenHealth(
            valid=valid,
            expires_at=_epoch(data.get("expires_at")),
            scopes=scopes,
            reasons=tuple(reasons),
        )
