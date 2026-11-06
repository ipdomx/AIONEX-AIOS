"""P3 per-user social connections on top of the connector framework.

Tenancy: every read and write is scoped to the caller's organization *and* to
the caller's own user id, so one member never sees or changes another
member's grants or connected accounts.

Flow: ``start_connect`` stores a single-use, browser-bound OAuth state (only
digests plus an encrypted PKCE verifier) and returns the provider's authorize
URL. ``complete_callback`` validates and consumes that state, exchanges the
code, upgrades to a long-lived token and stores the grant encrypted as a
``SocialConnection`` awaiting asset selection. ``connect_assets`` stores the
chosen Pages/accounts as ``GrowthSocialAccount`` rows with their own encrypted
tokens. ``check_account_health`` runs a real token inspection and
``disconnect_*`` revokes at the provider and deletes the stored tokens.

Nothing here returns, logs or audits a token value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ACTIVE_USER_STATUSES, UserRecord
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    SocialConnection,
    SocialOAuthState,
    User,
)
from app.services import social_connectors as framework
from app.services.social_connectors import SocialConnectorError

PORTAL_LOCALES = ("ar", "en", "fr", "de", "es", "tr")
DEFAULT_LOCALE = "en"
MAX_OPEN_STATES_PER_USER = 5
MAX_SELECTED_ASSETS = 50
EXPIRING_WINDOW = timedelta(days=7)
CONNECTED_VIA = "oauth"
_ACTIVE_ACCOUNT_STATUSES = ("active", "paused", "expired", "error")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def normalize_locale(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in PORTAL_LOCALES else DEFAULT_LOCALE


def _audit(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details={"connector_framework": "p3", **details},
        )
    )


# --- public shapes (explicit allow-lists; no token or ciphertext fields) -----------


def public_connection(row: SocialConnection) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "external_user_id": row.external_user_id,
        "display_name": row.display_name,
        "avatar_url": row.avatar_url,
        "requested_scopes": list(row.requested_scopes or []),
        "granted_scopes": list(row.granted_scopes or []),
        "token_expires_at": row.token_expires_at,
        "status": row.status,
        "health_state": row.health_state,
        "health_reasons": list(row.health_reasons or []),
        "last_health_at": row.last_health_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def public_account(row: GrowthSocialAccount) -> dict[str, Any]:
    metadata = dict(row.provider_metadata or {})
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "provider": row.provider,
        "connector": metadata.get("connector"),
        "account_kind": row.account_kind,
        "external_account_id": row.external_account_id,
        "display_name": row.display_name,
        "handle": row.public_handle,
        "avatar_url": row.avatar_url,
        "scopes": list(row.scopes or []),
        "linked_external_id": metadata.get("linked_external_id"),
        "status": row.status,
        "health_state": row.health_state,
        "health_reasons": list(row.health_reasons or []),
        "token_expires_at": row.token_expires_at,
        "last_health_at": row.last_health_at,
        "credential_stored": bool(row.token_ciphertext),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# --- start / callback ----------------------------------------------------------------


@dataclass(frozen=True)
class StartResult:
    authorize_url: str
    browser_binding: str
    expires_in: int


@dataclass(frozen=True)
class CallbackResult:
    provider: str
    locale: str
    ok: bool
    code: str
    connection_id: str | None = None
    purpose: str = "social"


PURPOSES = ("social", "ads")


def purpose_scopes(provider: str, purpose: str) -> tuple[str, ...]:
    """Extra scopes a purpose adds on top of the connector's base scopes (P4)."""

    if purpose == "social":
        return ()
    if purpose == "ads" and provider == "meta":
        from app.services.social_meta_provider import ads_scopes

        return ads_scopes()
    raise SocialConnectorError("connect-purpose-unsupported", status_code=422)


async def start_connect(
    session: AsyncSession,
    actor: UserRecord,
    provider_key: str,
    *,
    locale: str | None,
    purpose: str = "social",
) -> StartResult:
    connector = framework.get_connector(provider_key)
    status = connector.status()
    if not status.configured:
        raise SocialConnectorError("provider-not-configured", status_code=409)
    if purpose not in PURPOSES:
        raise SocialConnectorError("connect-purpose-unsupported", status_code=422)
    extra_scopes = purpose_scopes(connector.key, purpose)
    now = _now()
    await session.execute(
        delete(SocialOAuthState).where(
            SocialOAuthState.user_id == actor.id,
            (SocialOAuthState.expires_at < now) | (SocialOAuthState.consumed_at.is_not(None)),
        )
    )
    open_states = (
        await session.scalars(
            select(SocialOAuthState)
            .where(SocialOAuthState.user_id == actor.id)
            .order_by(SocialOAuthState.created_at.desc())
        )
    ).all()
    for stale in open_states[MAX_OPEN_STATES_PER_USER - 1 :]:
        await session.delete(stale)

    state = framework.new_state()
    binding = framework.new_browser_binding()
    verifier = framework.new_code_verifier() if connector.supports_pkce else None
    challenge = framework.code_challenge_s256(verifier) if verifier else None
    authorize_url = (
        connector.authorize_url(
            state=state, code_challenge=challenge, extra_scopes=extra_scopes
        )
        if extra_scopes
        else connector.authorize_url(state=state, code_challenge=challenge)
    )
    ttl = int(settings.SOCIAL_OAUTH_STATE_TTL_SECONDS)
    normalized_locale = normalize_locale(locale)
    session.add(
        SocialOAuthState(
            state_hash=framework.digest(state),
            organization_id=actor.organization_id,
            user_id=actor.id,
            provider=connector.key,
            browser_binding_hash=framework.digest(binding),
            code_verifier_ciphertext=framework.seal_token(verifier) if verifier else None,
            locale=normalized_locale,
            expires_at=now + timedelta(seconds=ttl),
            purpose=purpose,
        )
    )
    _audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="social.oauth.started",
        resource_type="social_connection",
        resource_id=None,
        details={
            "provider": connector.key,
            "pkce": bool(verifier),
            "locale": normalized_locale,
            "purpose": purpose,
            "extra_scopes": list(extra_scopes),
        },
    )
    await session.flush()
    return StartResult(authorize_url=authorize_url, browser_binding=binding, expires_in=ttl)


async def complete_callback(
    session: AsyncSession,
    provider_key: str,
    *,
    state: str | None,
    code: str | None,
    provider_error: str | None,
    browser_binding: str | None,
) -> CallbackResult:
    """Validate and consume the state, then finish the grant. Never raises."""

    provider = (provider_key or "").strip().lower()[:40]
    if not state or len(state) > 512:
        return CallbackResult(provider, DEFAULT_LOCALE, False, "oauth-state-missing")
    row = await session.scalar(
        select(SocialOAuthState)
        .where(SocialOAuthState.state_hash == framework.digest(state))
        .with_for_update()
    )
    if row is None or row.provider != provider:
        return CallbackResult(provider, DEFAULT_LOCALE, False, "oauth-state-invalid")
    locale = normalize_locale(row.locale)
    purpose = row.purpose if row.purpose in PURPOSES else "social"
    if row.consumed_at is not None:
        return CallbackResult(provider, locale, False, "oauth-state-replayed", purpose=purpose)
    row.consumed_at = _now()
    await session.flush()
    organization_id, user_id = row.organization_id, row.user_id

    def fail(reason: str) -> CallbackResult:
        _audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action="social.oauth.failed",
            resource_type="social_connection",
            resource_id=None,
            details={"provider": provider, "reason": reason, "purpose": purpose},
        )
        return CallbackResult(provider, locale, False, reason, purpose=purpose)

    if (_aware(row.expires_at) or _now()) <= _now():
        return fail("oauth-state-expired")
    if not framework.digest_matches(browser_binding, row.browser_binding_hash):
        return fail("oauth-state-binding-mismatch")
    if provider_error:
        return fail("oauth-access-denied")
    if not code:
        return fail("oauth-code-missing")
    user = await session.scalar(
        select(User).where(User.id == row.user_id, User.organization_id == row.organization_id)
    )
    if user is None or user.status not in ACTIVE_USER_STATUSES:
        return fail("oauth-user-inactive")

    try:
        connector = framework.get_connector(provider)
        verifier = (
            framework.open_token(row.code_verifier_ciphertext)
            if row.code_verifier_ciphertext
            else None
        )
        short_lived = await connector.exchange_code(code=code, code_verifier=verifier)
        grant = await connector.upgrade_token(short_lived)
        identity = await connector.identity(grant.access_token)
        health = await connector.inspect_token(grant.access_token)
    except SocialConnectorError as exc:
        return fail(exc.code)
    if not health.valid:
        return fail("oauth-token-invalid")
    try:
        requested = framework_scopes(connector, purpose)
    except SocialConnectorError as exc:
        return fail(exc.code)

    connection = await session.scalar(
        select(SocialConnection).where(
            SocialConnection.organization_id == row.organization_id,
            SocialConnection.user_id == row.user_id,
            SocialConnection.provider == provider,
            SocialConnection.external_user_id == identity.external_id,
        )
    )
    if connection is None:
        connection = SocialConnection(
            organization_id=row.organization_id,
            user_id=row.user_id,
            provider=provider,
            external_user_id=identity.external_id,
            display_name=identity.display_name,
            version=1,
        )
        session.add(connection)
    else:
        connection.version += 1
    connection.display_name = identity.display_name
    connection.avatar_url = identity.avatar_url
    if purpose == "ads":
        # Keep any scope an earlier grant asked for in the requested set.
        requested = tuple(dict.fromkeys([*(connection.requested_scopes or []), *requested]))
    connection.requested_scopes = list(requested)
    connection.granted_scopes = list(health.scopes)
    connection.token_ciphertext = framework.seal_token(grant.access_token)
    connection.token_expires_at = health.expires_at or grant.expires_at
    # An ads grant needs no Page selection; a social grant waits for it.
    connection.status = "active" if purpose == "ads" else "pending_selection"
    connection.health_state = "healthy"
    connection.health_reasons = _missing_scope_reasons(requested, health.scopes)
    connection.last_health_at = _now()
    connection.revoked_at = None
    await session.flush()
    _audit(
        session,
        organization_id=row.organization_id,
        user_id=row.user_id,
        action="social.oauth.connected",
        resource_type="social_connection",
        resource_id=connection.id,
        details={
            "provider": provider,
            "granted_scopes": list(health.scopes),
            "long_lived": True,
            "purpose": purpose,
        },
    )
    await session.flush()
    return CallbackResult(provider, locale, True, "connected", connection.id, purpose=purpose)


def framework_scopes(connector: framework.SocialConnector, purpose: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys([*connector.scopes(), *purpose_scopes(connector.key, purpose)]))


def _missing_scope_reasons(
    requested: tuple[str, ...], granted: tuple[str, ...]
) -> list[str]:
    missing = [scope for scope in requested if scope not in set(granted)]
    return [f"missing-scope:{scope}" for scope in missing]


def portal_redirect_url(result: CallbackResult) -> str:
    base = str(settings.SOCIAL_PORTAL_URL or "").rstrip("/")
    query: dict[str, str] = {
        "connect": result.provider or "unknown",
        "result": "success" if result.ok else "error",
        "code": result.code,
    }
    if result.connection_id:
        query["connection"] = result.connection_id
    page = "campaigns" if result.purpose == "ads" else "social"
    return f"{base}/{result.locale}/{page}/?{urlencode(query)}"


# --- connections and assets ---------------------------------------------------------


async def _own_connection(
    session: AsyncSession, actor: UserRecord, connection_id: str
) -> SocialConnection:
    row = await session.scalar(
        select(SocialConnection).where(
            SocialConnection.id == connection_id,
            SocialConnection.organization_id == actor.organization_id,
            SocialConnection.user_id == actor.id,
        )
    )
    if row is None:
        raise SocialConnectorError("connection-not-found", status_code=404)
    return row


async def list_connections(session: AsyncSession, actor: UserRecord) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(SocialConnection)
            .where(
                SocialConnection.organization_id == actor.organization_id,
                SocialConnection.user_id == actor.id,
                SocialConnection.status != "revoked",
            )
            .order_by(SocialConnection.created_at.desc())
            .limit(100)
        )
    ).all()
    return [public_connection(row) for row in rows]


async def _fetch_assets(
    connection: SocialConnection,
) -> tuple[framework.SocialConnector, list[framework.ConnectableAsset]]:
    if connection.status == "revoked":
        raise SocialConnectorError("connection-revoked", status_code=409)
    connector = framework.get_connector(connection.provider)
    token = framework.open_token(connection.token_ciphertext)
    return connector, await connector.list_assets(token)


async def list_assets(
    session: AsyncSession, actor: UserRecord, connection_id: str
) -> dict[str, Any]:
    connection = await _own_connection(session, actor, connection_id)
    _connector, assets = await _fetch_assets(connection)
    connected = {
        (row.provider, row.external_account_id)
        for row in (
            await session.scalars(
                select(GrowthSocialAccount).where(
                    GrowthSocialAccount.organization_id == actor.organization_id,
                    GrowthSocialAccount.created_by_id == actor.id,
                    GrowthSocialAccount.connection_id == connection.id,
                    GrowthSocialAccount.status != "revoked",
                )
            )
        ).all()
    }
    items = []
    for asset in assets:
        payload = asset.public()
        payload["connected"] = (asset.provider, asset.external_id) in connected
        payload["connectable"] = bool(asset.access_token)
        items.append(payload)
    return {"connection": public_connection(connection), "items": items}


async def connect_assets(
    session: AsyncSession,
    actor: UserRecord,
    connection_id: str,
    asset_ids: list[str],
) -> dict[str, Any]:
    wanted = list(dict.fromkeys(item.strip() for item in asset_ids if item and item.strip()))
    if not wanted:
        raise SocialConnectorError("assets-required")
    if len(wanted) > MAX_SELECTED_ASSETS:
        raise SocialConnectorError("too-many-assets")
    connection = await _own_connection(session, actor, connection_id)
    _connector, assets = await _fetch_assets(connection)
    by_id = {asset.asset_id: asset for asset in assets}
    unknown = [item for item in wanted if item not in by_id]
    if unknown:
        raise SocialConnectorError("asset-not-available", status_code=422)

    connected: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    now = _now()
    for asset_id in wanted:
        asset = by_id[asset_id]
        asset_token = asset.access_token
        if not asset_token:
            skipped.append({"asset_id": asset_id, "reason": "asset-token-not-granted"})
            continue
        row = await session.scalar(
            select(GrowthSocialAccount).where(
                GrowthSocialAccount.organization_id == actor.organization_id,
                GrowthSocialAccount.provider == asset.provider,
                GrowthSocialAccount.external_account_id == asset.external_id,
            )
        )
        if row is not None and row.created_by_id != actor.id and row.status != "revoked":
            skipped.append({"asset_id": asset_id, "reason": "asset-connected-by-another-member"})
            continue
        if row is None:
            row = GrowthSocialAccount(
                organization_id=actor.organization_id,
                created_by_id=actor.id,
                provider=asset.provider,
                account_kind=asset.account_kind,
                external_account_id=asset.external_id,
                display_name=asset.display_name,
                settings={},
                version=1,
            )
            session.add(row)
        else:
            row.created_by_id = actor.id
            row.version += 1
        row.account_kind = asset.account_kind
        row.display_name = asset.display_name[:240]
        row.public_handle = asset.handle
        row.avatar_url = asset.avatar_url
        row.connection_id = connection.id
        row.connected_via = CONNECTED_VIA
        row.scopes = list(connection.granted_scopes or [])
        row.token_ciphertext = framework.seal_token(asset_token)
        row.status = "active"
        row.paused_at = None
        row.health_state = "unknown"
        row.health_reasons = ["health-check-required"]
        row.token_expires_at = None
        row.last_health_at = None
        row.provider_metadata = {
            "connector": connection.provider,
            "linked_external_id": asset.linked_external_id,
            "tasks": list(asset.tasks),
            "connected_at": now.isoformat(),
        }
        await session.flush()
        # GS-03 treats a credential reference as "configured"; the value lives
        # encrypted in this row, so the reference names the vault column only.
        row.credential_ref = f"vault:social-account/{row.id}"
        _audit(
            session,
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="social.account.connected",
            resource_type="growth_social_account",
            resource_id=row.id,
            details={
                "provider": asset.provider,
                "account_kind": asset.account_kind,
                "connection_id": connection.id,
            },
        )
        connected.append(public_account(row))
    if connected:
        connection.status = "active"
        connection.version += 1
    await session.flush()
    return {"items": connected, "skipped": skipped}


# --- accounts ------------------------------------------------------------------------


async def _own_account(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> GrowthSocialAccount:
    row = await session.scalar(
        select(GrowthSocialAccount).where(
            GrowthSocialAccount.id == account_id,
            GrowthSocialAccount.organization_id == actor.organization_id,
            GrowthSocialAccount.created_by_id == actor.id,
            GrowthSocialAccount.connected_via == CONNECTED_VIA,
        )
    )
    if row is None:
        raise SocialConnectorError("account-not-found", status_code=404)
    return row


async def list_accounts(session: AsyncSession, actor: UserRecord) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(GrowthSocialAccount)
            .where(
                GrowthSocialAccount.organization_id == actor.organization_id,
                GrowthSocialAccount.created_by_id == actor.id,
                GrowthSocialAccount.connected_via == CONNECTED_VIA,
                GrowthSocialAccount.status.in_(_ACTIVE_ACCOUNT_STATUSES),
            )
            .order_by(GrowthSocialAccount.provider, GrowthSocialAccount.display_name)
            .limit(500)
        )
    ).all()
    return [public_account(row) for row in rows]


def health_from_inspection(
    health: framework.TokenHealth,
    *,
    required_scopes: tuple[str, ...],
    now: datetime | None = None,
) -> tuple[str, list[str]]:
    current = now or _now()
    if not health.valid:
        return "invalid", list(health.reasons) or ["token-invalid"]
    expiry = _aware(health.expires_at)
    if expiry is not None and expiry <= current:
        return "expired", ["token-expired"]
    missing = _missing_scope_reasons(required_scopes, health.scopes)
    if missing:
        return "degraded", missing
    if expiry is not None and expiry <= current + EXPIRING_WINDOW:
        return "expiring", ["token-expires-within-7-days"]
    return "healthy", ["token-valid"]


async def check_account_health(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> dict[str, Any]:
    row = await _own_account(session, actor, account_id)
    if row.status == "revoked":
        raise SocialConnectorError("account-revoked", status_code=409)
    connector_key = str((row.provider_metadata or {}).get("connector") or "")
    connector = framework.get_connector(connector_key)
    token = framework.open_token(row.token_ciphertext)
    required = connector.scopes()
    health: framework.TokenHealth | None
    try:
        health = await connector.inspect_token(token)
    except SocialConnectorError as exc:
        state, reasons = "error", [exc.code]
        health = None
    else:
        state, reasons = health_from_inspection(health, required_scopes=required)
    row.health_state = state
    row.health_reasons = reasons
    row.last_health_at = _now()
    if health is not None:
        row.token_expires_at = health.expires_at
    if state in {"invalid", "expired"} and row.status == "active":
        row.status = "expired"
    elif state in {"healthy", "expiring", "degraded"} and row.status == "expired":
        row.status = "active"
    row.version += 1
    _audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="social.account.health_checked",
        resource_type="growth_social_account",
        resource_id=row.id,
        details={"provider": row.provider, "health_state": state, "reasons": reasons},
    )
    await session.flush()
    return public_account(row)


async def _revoke_connection(
    session: AsyncSession, actor: UserRecord, connection: SocialConnection
) -> bool:
    """Revoke the grant at the provider and delete every stored token for it."""

    provider_revoked = False
    if connection.token_ciphertext:
        try:
            connector = framework.get_connector(connection.provider)
            token = framework.open_token(connection.token_ciphertext)
            provider_revoked = await connector.revoke(
                access_token=token, external_user_id=connection.external_user_id
            )
        except SocialConnectorError:
            provider_revoked = False
    accounts = (
        await session.scalars(
            select(GrowthSocialAccount).where(
                GrowthSocialAccount.organization_id == actor.organization_id,
                GrowthSocialAccount.connection_id == connection.id,
            )
        )
    ).all()
    for account in accounts:
        _clear_account(account)
    connection.token_ciphertext = None
    connection.token_expires_at = None
    connection.status = "revoked"
    connection.health_state = "revoked"
    connection.health_reasons = ["disconnected"]
    connection.revoked_at = _now()
    connection.version += 1
    _audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="social.connection.revoked",
        resource_type="social_connection",
        resource_id=connection.id,
        details={
            "provider": connection.provider,
            "provider_revoked": provider_revoked,
            "tokens_deleted": True,
            "accounts_cleared": len(accounts),
        },
    )
    await session.flush()
    return provider_revoked


def _clear_account(account: GrowthSocialAccount) -> None:
    account.token_ciphertext = None
    account.credential_ref = None
    account.status = "revoked"
    account.health_state = "revoked"
    account.health_reasons = ["disconnected"]
    account.paused_at = None
    account.version += 1


async def disconnect_account(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> dict[str, Any]:
    row = await _own_account(session, actor, account_id)
    _clear_account(row)
    _audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="social.account.disconnected",
        resource_type="growth_social_account",
        resource_id=row.id,
        details={"provider": row.provider, "tokens_deleted": True},
    )
    await session.flush()
    provider_revoked = False
    connection_revoked = False
    if row.connection_id:
        connection = await session.scalar(
            select(SocialConnection).where(
                SocialConnection.id == row.connection_id,
                SocialConnection.organization_id == actor.organization_id,
                SocialConnection.user_id == actor.id,
            )
        )
        if connection is not None and connection.status != "revoked":
            remaining = await session.scalar(
                select(GrowthSocialAccount.id)
                .where(
                    GrowthSocialAccount.connection_id == connection.id,
                    GrowthSocialAccount.status != "revoked",
                )
                .limit(1)
            )
            if remaining is None:
                # The last asset of the grant: revoke the app's permissions at
                # the provider so no token derived from this grant stays valid.
                provider_revoked = await _revoke_connection(session, actor, connection)
                connection_revoked = True
    return {
        "account": public_account(row),
        "connection_revoked": connection_revoked,
        "provider_revoked": provider_revoked,
    }


async def disconnect_connection(
    session: AsyncSession, actor: UserRecord, connection_id: str
) -> dict[str, Any]:
    connection = await _own_connection(session, actor, connection_id)
    if connection.status == "revoked":
        return {"connection": public_connection(connection), "provider_revoked": False}
    provider_revoked = await _revoke_connection(session, actor, connection)
    return {"connection": public_connection(connection), "provider_revoked": provider_revoked}
