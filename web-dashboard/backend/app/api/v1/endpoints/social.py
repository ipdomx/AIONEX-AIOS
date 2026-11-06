"""P3 social connector API: providers, OAuth connect, assets and accounts.

Every route except the OAuth callback requires the signed-in portal user and
is scoped to that user's own grants and accounts. The callback is reached by
the provider's browser redirect; it trusts nothing but a single-use state that
is bound to the browser by an HttpOnly cookie set when the flow started, and it
always ends with a redirect to the portal carrying a result code. No response
ever contains a token.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, _cookie_secure, current_user
from app.core.logging import get_logger
from app.db.base import get_db
from app.db.redis import get_redis
from app.services import social_connections as connections
from app.services import social_connectors as framework
from app.services.social_connectors import SocialConnectorError

router = APIRouter()
logger = get_logger(__name__)

BINDING_COOKIE = "aionex_social_oauth"
BINDING_COOKIE_PATH = "/api/v1/social/oauth"
_RATE_PREFIX = "aionex:social:rate:"
# (limit, window seconds) per user and action.
RATE_LIMITS: dict[str, tuple[int, int]] = {
    "start": (10, 600),
    "assets": (30, 600),
    "connect": (20, 600),
    "health": (30, 600),
    "disconnect": (30, 600),
    # P3 publishing (social_publishing.py).
    "validate": (240, 600),
    "post_write": (120, 600),
    "publish": (60, 600),
    "upload": (60, 600),
    "ai_assist": (30, 600),
}

Locale = Literal["ar", "en", "fr", "de", "es", "tr"]


class StartConnectRequest(BaseModel):
    locale: Locale = "en"


class ConnectAssetsRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=connections.MAX_SELECTED_ASSETS)


def _error(exc: SocialConnectorError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.code.replace("-", " ")},
    )


async def enforce_rate_limit(actor: UserRecord, action: str) -> None:
    limit, window = RATE_LIMITS[action]
    key = _RATE_PREFIX + hashlib.sha256(f"{action}:{actor.id}".encode()).hexdigest()
    try:
        redis = await get_redis()
        count = int(await redis.incr(key))
        if count == 1:
            await redis.expire(key, window)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "rate-limit-unavailable", "message": "Try again shortly"},
            headers={"Retry-After": "5"},
        ) from exc
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "rate-limited", "message": "Too many requests"},
            headers={"Retry-After": str(window)},
        )


@router.get("/providers")
async def list_providers(actor: UserRecord = Depends(current_user)) -> dict[str, Any]:
    return {"items": framework.provider_catalog()}


@router.post("/connect/{provider}/start")
async def start_connect(
    provider: str,
    payload: StartConnectRequest,
    response: Response,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await enforce_rate_limit(actor, "start")
    try:
        result = await connections.start_connect(
            session, actor, provider, locale=payload.locale
        )
        await session.commit()
    except SocialConnectorError as exc:
        await session.rollback()
        raise _error(exc) from exc
    response.set_cookie(
        BINDING_COOKIE,
        result.browser_binding,
        max_age=result.expires_in,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=BINDING_COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authorize_url": result.authorize_url, "expires_in": result.expires_in}


@router.get("/oauth/{provider}/callback", include_in_schema=False)
async def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = Query(default=None, max_length=2048),
    state: str | None = Query(default=None, max_length=512),
    error: str | None = Query(default=None, max_length=200),
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    # Only a registered connector key ever reaches the redirect or the DB
    # lookup; the raw path segment is never echoed back.
    normalized = (provider or "").strip().lower()
    provider_key = next(
        (key for key in framework.registered_keys() if key == normalized), "unknown"
    )
    try:
        result = await connections.complete_callback(
            session,
            provider_key,
            state=state,
            code=code,
            provider_error=error,
            browser_binding=request.cookies.get(BINDING_COOKIE),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error("Social OAuth callback failed", error_type=type(exc).__name__)
        result = connections.CallbackResult(
            provider=provider_key,
            locale=connections.DEFAULT_LOCALE,
            ok=False,
            code="oauth-callback-failed",
        )
    redirect = RedirectResponse(
        connections.portal_redirect_url(result), status_code=status.HTTP_303_SEE_OTHER
    )
    redirect.headers["Cache-Control"] = "no-store"
    redirect.headers["Referrer-Policy"] = "no-referrer"
    redirect.delete_cookie(
        BINDING_COOKIE,
        path=BINDING_COOKIE_PATH,
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    return redirect


@router.get("/connections")
async def list_connections(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"items": await connections.list_connections(session, actor)}


@router.get("/connections/{connection_id}/assets")
async def list_connection_assets(
    connection_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await enforce_rate_limit(actor, "assets")
    try:
        return await connections.list_assets(session, actor, connection_id)
    except SocialConnectorError as exc:
        raise _error(exc) from exc


@router.post("/connections/{connection_id}/assets")
async def connect_connection_assets(
    connection_id: str,
    payload: ConnectAssetsRequest,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await enforce_rate_limit(actor, "connect")
    try:
        result = await connections.connect_assets(
            session, actor, connection_id, payload.asset_ids
        )
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.delete("/connections/{connection_id}")
async def disconnect_connection(
    connection_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await enforce_rate_limit(actor, "disconnect")
    try:
        result = await connections.disconnect_connection(session, actor, connection_id)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.get("/accounts")
async def list_accounts(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"items": await connections.list_accounts(session, actor)}


@router.post("/accounts/{account_id}/health")
async def check_account_health(
    account_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await enforce_rate_limit(actor, "health")
    try:
        result = await connections.check_account_health(session, actor, account_id)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _error(exc) from exc


@router.delete("/accounts/{account_id}")
async def disconnect_account(
    account_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await enforce_rate_limit(actor, "disconnect")
    try:
        result = await connections.disconnect_account(session, actor, account_id)
        await session.commit()
        return result
    except SocialConnectorError as exc:
        await session.rollback()
        raise _error(exc) from exc

