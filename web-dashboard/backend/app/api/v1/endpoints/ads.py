"""P4 Meta Ads API for portal users: connect, insights analytics, AI advice, campaigns.

Every route requires the signed-in portal user, is scoped to that user's own
organization *and* user id, and (except ``/access``) requires the ``ads.manage``
entitlement. The incremental ads permission reuses the P3 OAuth callback
(``/social/oauth/{provider}/callback``) and its browser-binding cookie. No
response ever contains a token. Campaigns are created PAUSED; activation is a
separate, typed-confirmation action under the Owner spend guard.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import social as social_api
from app.core.auth import UserRecord, _cookie_secure, current_user
from app.db.base import get_db
from app.services import ads_accounts as accounts
from app.services import ads_ai_recommendations as recommendations
from app.services import ads_analytics as analytics
from app.services import ads_campaigns as campaigns
from app.services import ads_entitlement as entitlement
from app.services import social_connections as connections
from app.services.ads_meta_graph import AdsGraphError, MetaAdsGraph
from app.services.social_connectors import SocialConnectorError

router = APIRouter()

Locale = Literal["ar", "en", "fr", "de", "es", "tr"]
Source = Literal["oauth", "owner_token"]
Platform = Literal["facebook", "instagram"]


def _all_platforms() -> list[Platform]:
    return ["facebook", "instagram"]


_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def get_ads_graph() -> MetaAdsGraph:
    return MetaAdsGraph()


class StartAdsConnect(BaseModel):
    locale: Locale = "en"


class LinkAccountsRequest(BaseModel):
    source: Source = "oauth"
    connection_id: str | None = Field(default=None, pattern=_UUID)
    ad_account_ids: list[str] = Field(min_length=1, max_length=20)


class UpdateLinkRequest(BaseModel):
    cpa_target_minor: int | None = Field(default=None, ge=1)


class RecommendRequest(BaseModel):
    link_id: str = Field(pattern=_UUID)
    language: Locale = "en"
    external_processing_confirmed: bool = False


class TargetingInput(BaseModel):
    countries: list[str] = Field(min_length=1, max_length=25)
    age_min: int = Field(default=18, ge=18, le=65)
    age_max: int = Field(default=65, ge=18, le=65)
    genders: list[int] = Field(default_factory=list, max_length=2)
    publisher_platforms: list[Platform] = Field(
        default_factory=_all_platforms, min_length=1, max_length=2
    )


class CreativeInput(BaseModel):
    source: Literal["upload", "studio", "post"]
    media_ref: str | None = Field(default=None, max_length=64)
    post_target_id: str | None = Field(default=None, pattern=_UUID)
    page_account_id: str | None = Field(default=None, pattern=_UUID)
    instagram_account_id: str | None = Field(default=None, pattern=_UUID)
    message: str = Field(default="", max_length=2000)
    headline: str = Field(default="", max_length=120)
    link_url: str | None = Field(default=None, max_length=2048)
    call_to_action: str = Field(default="LEARN_MORE", max_length=24)


class CreateCampaignRequest(BaseModel):
    link_id: str = Field(pattern=_UUID)
    name: str = Field(min_length=1, max_length=200)
    objective: Literal["traffic", "awareness", "engagement", "sales", "leads"]
    daily_budget_minor: int | None = Field(default=None, ge=1)
    lifetime_budget_minor: int | None = Field(default=None, ge=1)
    start_time: datetime | None = None
    end_time: datetime | None = None
    targeting: TargetingInput
    creative: CreativeInput
    client_idempotency_key: str | None = Field(default=None, max_length=80)


class ActivateRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=80)
    confirmed_budget_minor: int = Field(ge=1)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, accounts.AdsError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail())
    if isinstance(exc, entitlement.AdsAccessError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail())
    if isinstance(exc, AdsGraphError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.code.replace("-", " ")},
        )
    if isinstance(exc, SocialConnectorError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.code.replace("-", " ")},
        )
    raise exc


_HANDLED = (accounts.AdsError, entitlement.AdsAccessError, AdsGraphError, SocialConnectorError)


@router.get("/access")
async def ads_access(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    access = await entitlement.resolve_access(session, actor)
    return {**access.public(actor.id), "activation_phrase": campaigns.ACTIVATION_PHRASE}


@router.post("/connect/meta/start")
async def start_ads_connect(
    payload: StartAdsConnect,
    response: Response,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "start")
    try:
        (await entitlement.resolve_access(session, actor)).require()
        result = await connections.start_connect(
            session, actor, "meta", locale=payload.locale, purpose="ads"
        )
        await session.commit()
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc
    response.set_cookie(
        social_api.BINDING_COOKIE,
        result.browser_binding,
        max_age=result.expires_in,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=social_api.BINDING_COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authorize_url": result.authorize_url, "expires_in": result.expires_in}


@router.get("/connections")
async def ads_connections(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        (await entitlement.resolve_access(session, actor)).require()
    except _HANDLED as exc:
        raise _error(exc) from exc
    return {"items": await accounts.ads_connections(session, actor)}


@router.get("/accounts/available")
async def available_ad_accounts(
    source: Source = Query(default="oauth"),
    connection_id: str | None = Query(default=None, pattern=_UUID),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
    graph: MetaAdsGraph = Depends(get_ads_graph),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_read")
    try:
        return await accounts.available_accounts(
            session, actor, connection_id=connection_id, source=source, graph=graph
        )
    except _HANDLED as exc:
        raise _error(exc) from exc


@router.post("/accounts")
async def link_ad_accounts(
    payload: LinkAccountsRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
    graph: MetaAdsGraph = Depends(get_ads_graph),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_write")
    try:
        result = await accounts.link_accounts(
            session,
            actor,
            connection_id=payload.connection_id,
            source=payload.source,
            ad_account_ids=payload.ad_account_ids,
            graph=graph,
        )
        await session.commit()
        return result
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/accounts")
async def list_ad_accounts(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        (await entitlement.resolve_access(session, actor)).require()
    except _HANDLED as exc:
        raise _error(exc) from exc
    return {"items": await accounts.list_links(session, actor)}


@router.patch("/accounts/{link_id}")
async def update_ad_account(
    link_id: str,
    payload: UpdateLinkRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_write")
    try:
        (await entitlement.resolve_access(session, actor)).require()
        result = await accounts.update_link(
            session, actor, link_id, cpa_target_minor=payload.cpa_target_minor
        )
        await session.commit()
        return result
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.delete("/accounts/{link_id}")
async def unlink_ad_account(
    link_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_write")
    try:
        result = await accounts.unlink(session, actor, link_id)
        await session.commit()
        return result
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/accounts/{link_id}/sync")
async def request_sync(
    link_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_sync")
    try:
        (await entitlement.resolve_access(session, actor)).require()
        link = await accounts.own_link(session, actor, link_id)
        now = datetime.now(UTC)
        throttle_until = link.throttle_until
        if throttle_until is not None and throttle_until.tzinfo is None:
            throttle_until = throttle_until.replace(tzinfo=UTC)
        if throttle_until is not None and throttle_until > now:
            raise accounts.AdsError(
                "ads-insights-throttled",
                status_code=429,
                extra={"retry_at": throttle_until.isoformat()},
            )
        link.next_sync_at = now
        link.version += 1
        await session.commit()
        return {**accounts.public_link(link), "sync_requested": True}
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/analytics")
async def ads_analytics(
    link_id: str = Query(pattern=_UUID),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_read")
    try:
        return await analytics.dashboard(
            session, actor, link_id, date_from=date_from, date_to=date_to
        )
    except _HANDLED as exc:
        raise _error(exc) from exc


@router.get("/usage")
async def ads_usage(
    link_id: str = Query(pattern=_UUID),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        access = await entitlement.resolve_access(session, actor)
        access.require()
        link = await accounts.own_link(session, actor, link_id)
        caps = access.caps_for(actor.id)
        current = await campaigns.usage(session, actor, currency=link.currency)
    except _HANDLED as exc:
        raise _error(exc) from exc
    return {**current, "daily_cap_minor": caps.daily_minor, "lifetime_cap_minor": caps.lifetime_minor}


@router.post("/recommendations")
async def create_recommendations(
    payload: RecommendRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_ai")
    try:
        return await recommendations.recommend(
            session,
            actor,
            payload.link_id,
            language=payload.language,
            external_processing_confirmed=payload.external_processing_confirmed,
        )
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/recommendations")
async def latest_recommendations(
    link_id: str = Query(pattern=_UUID),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return {"item": await recommendations.latest(session, actor, link_id)}
    except _HANDLED as exc:
        raise _error(exc) from exc


@router.get("/campaigns")
async def list_campaigns(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        (await entitlement.resolve_access(session, actor)).require()
    except _HANDLED as exc:
        raise _error(exc) from exc
    return {"items": await campaigns.list_campaigns(session, actor)}


@router.post("/campaigns")
async def create_campaign(
    payload: CreateCampaignRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
    graph: MetaAdsGraph = Depends(get_ads_graph),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_write")
    try:
        return await campaigns.create_campaign(
            session, actor, payload.model_dump(), graph=graph
        )
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/campaigns/{campaign_id}/provision")
async def provision_campaign(
    campaign_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
    graph: MetaAdsGraph = Depends(get_ads_graph),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_write")
    try:
        (await entitlement.resolve_access(session, actor)).require()
        return await campaigns.provision(session, actor, campaign_id, graph=graph)
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/campaigns/{campaign_id}/activate")
async def activate_campaign(
    campaign_id: str,
    payload: ActivateRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
    graph: MetaAdsGraph = Depends(get_ads_graph),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_activate")
    try:
        return await campaigns.activate(
            session,
            actor,
            campaign_id,
            confirmation=payload.confirmation,
            confirmed_budget_minor=payload.confirmed_budget_minor,
            graph=graph,
        )
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
    graph: MetaAdsGraph = Depends(get_ads_graph),
) -> dict[str, Any]:
    await social_api.enforce_rate_limit(actor, "ads_write")
    try:
        return await campaigns.pause(session, actor, campaign_id, graph=graph)
    except _HANDLED as exc:
        await session.rollback()
        raise _error(exc) from exc
