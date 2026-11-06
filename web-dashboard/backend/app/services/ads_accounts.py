"""P4 user ad-account connect (roadmap 4.1).

A user grants the Marketing API scopes incrementally on their Meta login
(``social_connections`` with ``purpose="ads"``), lists the ad accounts that
grant can reach (``me/adaccounts``), and picks which ones the platform may
manage. Selections are stored per tenant *and* per user in
``ad_account_links``; one member never sees another member's links.

The Super Owner keeps the operator token file (``AIOS_META_OWNED_TOKEN_FILE``)
as a fallback source; no other role can list or link through it, and the
worker re-checks the role before every use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import AdAccountLink, AdCampaign, AuditEvent, Role, SocialConnection, User
from app.services import ads_entitlement as entitlement
from app.services import growth_meta_owned_connector as owner_token
from app.services import social_connectors as framework
from app.services.ads_meta_graph import AdAccount, AdsAuth, AdsGraphError, MetaAdsGraph, numeric_id
from app.services.social_connectors import SocialConnectorError
from app.services.social_meta_provider import MetaConnector, ads_scopes

SOURCE_OAUTH = "oauth"
SOURCE_OWNER_TOKEN = "owner_token"
SUPER_OWNER = "Super Owner"
_LIVE_LINK_STATUSES = ("active", "error", "reconnect")


def _now() -> datetime:
    return datetime.now(UTC)


class AdsError(RuntimeError):
    """Client-safe P4 ads error with a stable code."""

    def __init__(self, code: str, *, status_code: int = 400, extra: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.extra = dict(extra or {})

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.code.replace("-", " "), **self.extra}


def audit(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str | None,
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
            details={"ads_management": "p4", "live_verified": False, **details},
        )
    )


def public_link(row: AdAccountLink) -> dict[str, Any]:
    return {
        "id": row.id,
        "ad_account_id": row.ad_account_id,
        "name": row.name,
        "currency": row.currency,
        "timezone_name": row.timezone_name,
        "account_status": row.account_status,
        "business_name": row.business_name,
        "source": row.source,
        "connection_id": row.connection_id,
        "status": row.status,
        "cpa_target_minor": row.cpa_target_minor,
        "insights_synced_through": (
            row.insights_synced_through.isoformat() if row.insights_synced_through else None
        ),
        "last_sync_at": row.last_sync_at,
        "next_sync_at": row.next_sync_at,
        "throttle_until": row.throttle_until,
        "sync_state": row.sync_state,
        "sync_error": row.sync_error,
        "created_at": row.created_at,
    }


# --- tokens ----------------------------------------------------------------------------


def _app_secret() -> str:
    try:
        _app_id, secret = MetaConnector()._require_credentials()
    except SocialConnectorError as exc:
        raise AdsError(exc.code, status_code=exc.status_code) from None
    return secret


def connection_auth(connection: SocialConnection) -> AdsAuth:
    if connection.status == "revoked" or not connection.token_ciphertext:
        raise AdsError("ads-connection-revoked", status_code=409)
    missing = [scope for scope in ("ads_read",) if scope not in set(connection.granted_scopes or [])]
    if missing:
        raise AdsError("ads-permission-not-granted", status_code=409, extra={"missing_scopes": missing})
    try:
        token = framework.open_token(connection.token_ciphertext)
    except SocialConnectorError as exc:
        raise AdsError(exc.code, status_code=exc.status_code) from None
    return AdsAuth(access_token=token, app_secret=_app_secret())


def owner_token_auth() -> AdsAuth:
    """The Owner's operator token file (owner-only fallback, no app proof)."""

    try:
        token_file, _version = owner_token._safe_config()
        token = owner_token._read_token(token_file)
    except owner_token.MetaOwnedReadOnlyValidationError as exc:
        raise AdsError(str(exc), status_code=409) from None
    return AdsAuth(access_token=token, app_secret=None)


def can_manage(connection: SocialConnection) -> bool:
    return "ads_management" in set(connection.granted_scopes or [])


async def link_auth(session: AsyncSession, link: AdAccountLink) -> AdsAuth:
    """Resolve the token for a link at call time; fails closed on any doubt."""

    if link.status == "revoked":
        raise AdsError("ads-link-revoked", status_code=409)
    if link.source == SOURCE_OWNER_TOKEN:
        if not await is_super_owner(session, link.user_id, link.organization_id):
            raise AdsError("ads-owner-token-not-allowed", status_code=403)
        return owner_token_auth()
    connection = await session.scalar(
        select(SocialConnection).where(
            SocialConnection.id == link.connection_id,
            SocialConnection.organization_id == link.organization_id,
            SocialConnection.user_id == link.user_id,
        )
    )
    if connection is None:
        raise AdsError("ads-connection-not-found", status_code=409)
    return connection_auth(connection)


async def is_super_owner(session: AsyncSession, user_id: str, organization_id: str) -> bool:
    name = await session.scalar(
        select(Role.name)
        .join(User, User.role_id == Role.id)
        .where(User.id == user_id, User.organization_id == organization_id, User.status == "active")
    )
    return name == SUPER_OWNER


# --- connect and list ------------------------------------------------------------------


async def _own_connection(
    session: AsyncSession, actor: UserRecord, connection_id: str
) -> SocialConnection:
    row = await session.scalar(
        select(SocialConnection).where(
            SocialConnection.id == connection_id,
            SocialConnection.organization_id == actor.organization_id,
            SocialConnection.user_id == actor.id,
            SocialConnection.provider == "meta",
        )
    )
    if row is None:
        raise AdsError("ads-connection-not-found", status_code=404)
    return row


async def ads_connections(session: AsyncSession, actor: UserRecord) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(SocialConnection)
            .where(
                SocialConnection.organization_id == actor.organization_id,
                SocialConnection.user_id == actor.id,
                SocialConnection.provider == "meta",
                SocialConnection.status != "revoked",
            )
            .order_by(SocialConnection.created_at.desc())
            .limit(20)
        )
    ).all()
    required = ads_scopes()
    items = []
    for row in rows:
        granted = set(row.granted_scopes or [])
        items.append(
            {
                "id": row.id,
                "display_name": row.display_name,
                "status": row.status,
                "ads_scopes_granted": [scope for scope in required if scope in granted],
                "ads_scopes_missing": [scope for scope in required if scope not in granted],
                "can_read": "ads_read" in granted,
                "can_manage": "ads_management" in granted,
                "token_expires_at": row.token_expires_at,
            }
        )
    return items


async def available_accounts(
    session: AsyncSession,
    actor: UserRecord,
    *,
    connection_id: str | None,
    source: str,
    graph: MetaAdsGraph,
) -> dict[str, Any]:
    access = await entitlement.resolve_access(session, actor)
    access.require()
    if source == SOURCE_OWNER_TOKEN:
        if actor.role != SUPER_OWNER:
            raise AdsError("ads-owner-token-not-allowed", status_code=403)
        auth = owner_token_auth()
    elif source == SOURCE_OAUTH and connection_id:
        auth = connection_auth(await _own_connection(session, actor, connection_id))
    else:
        raise AdsError("ads-connection-required", status_code=422)
    try:
        accounts = await graph.list_ad_accounts(auth)
    except AdsGraphError as exc:
        raise AdsError(exc.code, status_code=exc.status_code) from None
    linked = {
        row.ad_account_id
        for row in (
            await session.scalars(
                select(AdAccountLink).where(
                    AdAccountLink.organization_id == actor.organization_id,
                    AdAccountLink.user_id == actor.id,
                    AdAccountLink.status != "revoked",
                )
            )
        ).all()
    }
    return {
        "source": source,
        "connection_id": connection_id,
        "items": [{**account.public(), "linked": account.ad_account_id in linked} for account in accounts],
    }


async def link_accounts(
    session: AsyncSession,
    actor: UserRecord,
    *,
    connection_id: str | None,
    source: str,
    ad_account_ids: list[str],
    graph: MetaAdsGraph,
) -> dict[str, Any]:
    access = await entitlement.resolve_access(session, actor)
    access.require()
    wanted = list(dict.fromkeys(numeric_id(item, "ad-account-id") for item in ad_account_ids))
    if not wanted:
        raise AdsError("ad-accounts-required", status_code=422)
    listing = await available_accounts(
        session, actor, connection_id=connection_id, source=source, graph=graph
    )
    by_id = {item["ad_account_id"]: item for item in listing["items"]}
    unknown = [item for item in wanted if item not in by_id]
    if unknown:
        raise AdsError("ad-account-not-available", status_code=422)
    existing = (
        await session.scalars(
            select(AdAccountLink).where(
                AdAccountLink.organization_id == actor.organization_id,
                AdAccountLink.user_id == actor.id,
            )
        )
    ).all()
    by_account = {row.ad_account_id: row for row in existing}
    live = sum(1 for row in existing if row.status != "revoked" and row.ad_account_id not in wanted)
    limit = int(access.policy["max_ad_accounts_per_user"])
    if live + len(wanted) > limit:
        raise AdsError("ad-account-limit-reached", status_code=429, extra={"allowed": limit})
    linked: list[dict[str, Any]] = []
    now = _now()
    for account_id in wanted:
        info = by_id[account_id]
        row = by_account.get(account_id)
        if row is None:
            row = AdAccountLink(
                organization_id=actor.organization_id,
                user_id=actor.id,
                ad_account_id=account_id,
                provider="meta",
                version=1,
            )
            session.add(row)
        else:
            row.version += 1
        row.source = source
        row.connection_id = connection_id if source == SOURCE_OAUTH else None
        row.name = info["name"]
        row.currency = info["currency"]
        row.timezone_name = info["timezone_name"]
        row.account_status = int(info["account_status"])
        row.business_name = info["business_name"]
        row.status = "active"
        row.sync_state = "pending"
        row.sync_error = None
        row.next_sync_at = now
        await session.flush()
        audit(
            session,
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="ads.account.linked",
            resource_type="ad_account_link",
            resource_id=row.id,
            details={"source": source, "currency": row.currency, "account_status": row.account_status},
        )
        linked.append(public_link(row))
    await session.flush()
    return {"items": linked}


async def list_links(session: AsyncSession, actor: UserRecord) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(AdAccountLink)
            .where(
                AdAccountLink.organization_id == actor.organization_id,
                AdAccountLink.user_id == actor.id,
                AdAccountLink.status.in_(_LIVE_LINK_STATUSES),
            )
            .order_by(AdAccountLink.name)
            .limit(100)
        )
    ).all()
    return [public_link(row) for row in rows]


async def own_link(session: AsyncSession, actor: UserRecord, link_id: str) -> AdAccountLink:
    row = await session.scalar(
        select(AdAccountLink).where(
            AdAccountLink.id == link_id,
            AdAccountLink.organization_id == actor.organization_id,
            AdAccountLink.user_id == actor.id,
            AdAccountLink.status != "revoked",
        )
    )
    if row is None:
        raise AdsError("ad-account-link-not-found", status_code=404)
    return row


async def update_link(
    session: AsyncSession, actor: UserRecord, link_id: str, *, cpa_target_minor: int | None
) -> dict[str, Any]:
    row = await own_link(session, actor, link_id)
    if cpa_target_minor is not None and not 0 < cpa_target_minor <= entitlement.MAX_MONEY_MINOR:
        raise AdsError("cpa-target-invalid", status_code=422)
    row.cpa_target_minor = cpa_target_minor
    row.version += 1
    audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="ads.account.target_updated",
        resource_type="ad_account_link",
        resource_id=row.id,
        details={"cpa_target_minor": cpa_target_minor},
    )
    await session.flush()
    return public_link(row)


async def unlink(session: AsyncSession, actor: UserRecord, link_id: str) -> dict[str, Any]:
    row = await own_link(session, actor, link_id)
    active = await session.scalar(
        select(func.count(AdCampaign.id)).where(
            AdCampaign.link_id == row.id,
            AdCampaign.organization_id == actor.organization_id,
            AdCampaign.user_id == actor.id,
            AdCampaign.status == "active",
        )
    )
    if int(active or 0) > 0:
        raise AdsError("ad-account-has-active-campaigns", status_code=409)
    row.status = "revoked"
    row.next_sync_at = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.version += 1
    audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="ads.account.unlinked",
        resource_type="ad_account_link",
        resource_id=row.id,
        details={},
    )
    await session.flush()
    return public_link(row)


def account_from_link(row: AdAccountLink) -> AdAccount:
    return AdAccount(
        ad_account_id=row.ad_account_id,
        name=row.name,
        currency=row.currency,
        timezone_name=row.timezone_name,
        account_status=row.account_status,
        business_name=row.business_name,
    )
